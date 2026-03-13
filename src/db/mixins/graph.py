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
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the AGE graph.

        Parameters are validated and safely interpolated since AGE doesn't support
        parameterized Cypher queries ($1, $2 style).
        """
        async with self.acquire() as conn:
            try:
                await conn.execute("LOAD 'age'")
                await conn.execute(f"SET search_path = ag_catalog, core, audit, public")

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
                return [{"error": str(e)}]

    def _sanitize_cypher_param(self, value: Any) -> str:
        """
        Sanitize a parameter value for safe inclusion in a Cypher query.

        AGE doesn't support parameterized queries, so we must validate values.
        """
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        elif isinstance(value, list):
            sanitized_elements = [self._sanitize_cypher_param(item) for item in value]
            return f"[{', '.join(sanitized_elements)}]"
        elif isinstance(value, dict):
            json_str = json.dumps(value).replace("'", "\\'")
            return f"'{json_str}'"
        else:
            raise ValueError(f"Unsupported Cypher param type: {type(value)}")
