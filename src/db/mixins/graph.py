"""Graph (AGE) operations mixin for PostgresBackend."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from src.logging_utils import get_logger

logger = get_logger(__name__)


class GraphMixin:
    """Apache AGE graph query operations."""

    async def graph_available(self) -> bool:
        """Check if AGE graph queries are available."""
        async with self.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                return True
            except Exception:
                return False

    async def graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
        conn=None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the AGE graph.

        Parameters are validated and safely interpolated since AGE doesn't support
        parameterized Cypher queries ($1, $2 style).

        Args:
            cypher: Cypher query with ${param} placeholders
            params: Parameter dict for interpolation
            conn: Optional existing connection (for use within transactions).
                  When provided, reuses this connection instead of acquiring from pool.
        """
        return await self._execute_graph_query(cypher, params, conn)

    async def _execute_graph_query(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]],
        conn=None,
    ) -> List[Dict[str, Any]]:
        """Internal graph query execution, supports both pooled and passed connections."""
        if conn is not None:
            return await self._run_cypher_on_conn(conn, cypher, params)

        async with self.acquire() as pooled_conn:
            return await self._run_cypher_on_conn(pooled_conn, cypher, params)

    async def _run_cypher_on_conn(
        self,
        conn,
        cypher: str,
        params: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query on a specific connection."""
        try:
            # Always LOAD + SET before every query. asyncpg's pool runs
            # RESET ALL on connection release, which clears search_path.
            # The 2 extra round-trips per query are worth correctness.
            await conn.execute("LOAD 'age'")
            await conn.execute("SET search_path = ag_catalog, core, audit, public")

            safe_cypher = cypher
            if params:
                for k, v in params.items():
                    safe_value = self._sanitize_cypher_param(v)
                    safe_cypher = re.sub(rf'\$\{{{re.escape(k)}\}}', safe_value, safe_cypher)

            rows = await conn.fetch(
                f"SELECT * FROM cypher('{self._age_graph}', $$ {safe_cypher} $$) as (result agtype)"
            )

            results = []
            for row in rows:
                result = row["result"]
                if isinstance(result, str):
                    clean_result = result
                    for suffix in ("::vertex", "::edge", "::agtype"):
                        if clean_result.endswith(suffix):
                            clean_result = clean_result[:-len(suffix)]
                            break
                    try:
                        results.append(json.loads(clean_result))
                    except json.JSONDecodeError:
                        results.append(result)
                elif isinstance(result, (dict, list)):
                    results.append(result)
                else:
                    results.append(result)
            return results

        except Exception as e:
            logger.error(f"Cypher query failed: {e}")
            raise

    # Maximum byte length for a single string parameter (10 KB)
    _MAX_PARAM_LENGTH = 10_240
    # Maximum recursion depth for nested list/dict params
    _MAX_PARAM_DEPTH = 8

    def _sanitize_cypher_param(self, value: Any, _depth: int = 0) -> str:
        """
        Sanitize a parameter value for safe inclusion in a Cypher query.

        AGE doesn't support parameterized queries, so we must validate values.
        Enforces length limits, rejects null bytes, and escapes all dangerous chars.
        """
        if _depth > self._MAX_PARAM_DEPTH:
            raise ValueError(f"Cypher param nesting too deep (>{self._MAX_PARAM_DEPTH})")

        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            import math as _math
            if isinstance(value, float) and (_math.isnan(value) or _math.isinf(value)):
                raise ValueError(f"Cypher param cannot be NaN or Inf: {value}")
            return str(value)
        elif isinstance(value, str):
            if '\x00' in value:
                raise ValueError("Cypher param contains null byte")
            if len(value) > self._MAX_PARAM_LENGTH:
                raise ValueError(
                    f"Cypher param too long ({len(value)} > {self._MAX_PARAM_LENGTH})"
                )
            escaped = (
                value
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace('"', '\\"')
            )
            return f"'{escaped}'"
        elif isinstance(value, list):
            sanitized_elements = [
                self._sanitize_cypher_param(item, _depth + 1) for item in value
            ]
            return f"[{', '.join(sanitized_elements)}]"
        elif isinstance(value, dict):
            json_str = json.dumps(value)
            if len(json_str) > self._MAX_PARAM_LENGTH:
                raise ValueError(
                    f"Cypher dict param too long ({len(json_str)} > {self._MAX_PARAM_LENGTH})"
                )
            escaped = json_str.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        else:
            raise ValueError(f"Unsupported Cypher param type: {type(value)}")
