"""
Export knowledge graph data from SQLite (data/governance.db) into an Apache AGE SQL script.

Design goals:
- No new Python deps (stdlib only).
- Non-invasive: does NOT modify runtime backends; this is a prototype/evaluation helper.
- Export is a plain .sql file you can pipe into psql inside the AGE container.

AGE execution model reminder:
- Each session must run:
  LOAD 'age';
  SET search_path = ag_catalog, "$user", public;
- Cypher is executed via:
  SELECT * FROM cypher('graph_name', $$ ... $$) AS (v agtype);

Example:
  python3 scripts/age/export_knowledge_sqlite_to_age.py \
    --sqlite data/governance.db \
    --out /tmp/age_import.sql

  docker compose -f scripts/age/docker-compose.age.yml up -d
  docker exec -i postgres-age psql -U postgres -d postgres < scripts/age/bootstrap.sql
  docker exec -i postgres-age psql -U postgres -d postgres < /tmp/age_import.sql
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Literal


def _sql_quote(s: Optional[str]) -> str:
    """
    Quote a Python string as a Cypher single-quoted literal.
    We do minimal escaping: backslash and single quote.
    """
    if s is None:
        return "null"
    s = str(s)
    # Keep literals single-line to avoid accidental statement formatting issues.
    s = s.replace("\r", "\\r").replace("\n", "\\n")
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def _cypher_stmt(graph: str, cypher: str) -> str:
    # Return at least 1 column so AGE is happy with SELECT ... AS (v agtype)
    return (
        "SELECT * FROM cypher("
        + _sql_quote(graph)
        + ", $$\n"
        + cypher.strip()
        + "\n$$) AS (v agtype);\n"
    )


def _iter_rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Iterable[sqlite3.Row]:
    cur = conn.execute(sql, params)
    for row in cur.fetchall():
        yield row


ExportMode = Literal["create", "merge"]

def _safe_json_list(v: Optional[str]) -> list:
    if not v:
        return []
    try:
        parsed = json.loads(v)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _truncate(s: Optional[str], max_len: int) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _emit_graph_recreate(f, graph: str) -> None:
    # Apache AGE graph lifecycle helpers.
    # drop_graph(name, cascade) throws if graph doesn't exist; catch and ignore.
    f.write("-- Recreate graph (optional)\n")
    f.write("DO $$\n")
    f.write("BEGIN\n")
    f.write(f"  PERFORM drop_graph({_sql_quote(graph)}, true);\n")
    f.write("EXCEPTION\n")
    f.write("  WHEN undefined_function THEN\n")
    f.write("    -- AGE not loaded; ignore (bootstrap should have run)\n")
    f.write("    NULL;\n")
    f.write("  WHEN invalid_parameter_value THEN\n")
    f.write("    -- graph doesn't exist\n")
    f.write("    NULL;\n")
    f.write("  WHEN others THEN\n")
    f.write("    NULL;\n")
    f.write("END $$;\n\n")
    f.write("DO $$\n")
    f.write("BEGIN\n")
    f.write(f"  PERFORM create_graph({_sql_quote(graph)});\n")
    f.write("EXCEPTION\n")
    f.write("  WHEN duplicate_object THEN\n")
    f.write("    NULL;\n")
    f.write("  WHEN others THEN\n")
    f.write("    NULL;\n")
    f.write("END $$;\n\n")


def export(
    sqlite_path: Path,
    out_path: Path,
    graph: str,
    limit: Optional[int],
    mode: ExportMode,
    recreate_graph: bool,
    include_agents: bool,
    include_dialectic: bool,
) -> None:
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- AUTO-GENERATED: SQLite → Apache AGE import\n")
        f.write(f"-- Source: {sqlite_path}\n")
        f.write(f"-- Graph: {graph}\n\n")

        # Session prelude
        f.write("BEGIN;\n")
        f.write("LOAD 'age';\n")
        f.write('SET search_path = ag_catalog, "$user", public;\n\n')

        if recreate_graph:
            _emit_graph_recreate(f, graph)

        # ---------------------------------------------------------------------
        # Agents (nodes + tags + lineage)
        # ---------------------------------------------------------------------
        if include_agents:
            f.write("-- Agents\n")
            agents_sql = """
                SELECT
                  agent_id, status, created_at, last_update, version,
                  total_updates, tags_json, notes, parent_agent_id, spawn_reason,
                  paused_at, archived_at, health_status
                FROM agent_metadata
                ORDER BY created_at ASC
            """
            for row in _iter_rows(conn, agents_sql):
                aid = row["agent_id"]
                if not aid:
                    continue
                tags = _safe_json_list(row["tags_json"])
                props = {
                    "id": aid,
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "last_update": row["last_update"],
                    "version": row["version"],
                    "total_updates": int(row["total_updates"] or 0),
                    "paused_at": row["paused_at"],
                    "archived_at": row["archived_at"],
                    "health_status": row["health_status"],
                    "tag_count": len(tags),
                    "notes": _truncate(row["notes"], 500),
                }

                if mode == "create":
                    kv = []
                    for k, v in props.items():
                        if v is None or v == "":
                            continue
                        if k in ("total_updates", "tag_count"):
                            kv.append(f"{k}: {int(v)}")
                        else:
                            kv.append(f"{k}: {_sql_quote(v)}")
                    cy = f"CREATE (:Agent {{{', '.join(kv)}}}) RETURN 1"
                else:
                    sets = []
                    for k, v in props.items():
                        if k == "id" or v is None or v == "":
                            continue
                        if k in ("total_updates", "tag_count"):
                            sets.append(f"a.{k} = {int(v)}")
                        else:
                            sets.append(f"a.{k} = {_sql_quote(v)}")
                    cy = f"MERGE (a:Agent {{id: {_sql_quote(aid)}}})"
                    if sets:
                        cy += " SET " + ", ".join(sets)
                    cy += " RETURN 1"
                f.write(_cypher_stmt(graph, cy))

                # Agent tags (reuse Tag label)
                rel_kw = "CREATE" if mode == "create" else "MERGE"
                for tag in tags:
                    if not tag:
                        continue
                    f.write(_cypher_stmt(graph, f"MERGE (:Tag {{name: {_sql_quote(tag)}}}) RETURN 1"))
                    cy = (
                        f"MATCH (a:Agent {{id: {_sql_quote(aid)}}}), (t:Tag {{name: {_sql_quote(tag)}}}) "
                        f"{rel_kw} (a)-[:HAS_TAG]->(t) RETURN 1"
                    )
                    f.write(_cypher_stmt(graph, cy))

            # Lineage edges (parent -> child)
            f.write("\n-- Agent lineage (SPAWNED)\n")
            for row in _iter_rows(conn, "SELECT agent_id, parent_agent_id, spawn_reason FROM agent_metadata"):
                child = row["agent_id"]
                parent = row["parent_agent_id"]
                reason = row["spawn_reason"]
                if not child or not parent:
                    continue
                if mode == "create":
                    cy = (
                        f"MATCH (p:Agent {{id: {_sql_quote(parent)}}}), (c:Agent {{id: {_sql_quote(child)}}}) "
                        f"CREATE (p)-[:SPAWNED {{reason: {_sql_quote(_truncate(reason, 300))}}}]->(c) RETURN 1"
                    )
                else:
                    cy = (
                        f"MATCH (p:Agent {{id: {_sql_quote(parent)}}}), (c:Agent {{id: {_sql_quote(child)}}}) "
                        f"MERGE (p)-[r:SPAWNED]->(c) "
                        f"SET r.reason = {_sql_quote(_truncate(reason, 300))} "
                        f"RETURN 1"
                    )
                f.write(_cypher_stmt(graph, cy))

            f.write("\n")

        # ---------------------------------------------------------------------
        # Discoveries (nodes)
        # ---------------------------------------------------------------------
        discoveries_sql = """
            SELECT
              id, agent_id, type, severity, status,
              created_at, updated_at, resolved_at,
              summary, details, confidence, related_files
            FROM discoveries
            ORDER BY created_at ASC
        """
        count = 0
        for row in _iter_rows(conn, discoveries_sql):
            if limit is not None and count >= limit:
                break
            props = {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "type": row["type"],
                "severity": row["severity"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "resolved_at": row["resolved_at"],
                "summary": row["summary"],
                "details": row["details"],
                "confidence": row["confidence"],
            }
            # Related files is a JSON array string in SQLite; store as raw JSON string for now.
            related_files = row["related_files"]
            if related_files:
                try:
                    _ = json.loads(related_files)
                    props["related_files_json"] = related_files
                except Exception:
                    props["related_files_json"] = str(related_files)

            did = props.get("id")
            if not did:
                continue

            if mode == "create":
                kv = []
                for k, v in props.items():
                    if v is None or v == "":
                        continue
                    if isinstance(v, (int, float)) and k == "confidence":
                        kv.append(f"{k}: {float(v)}")
                    else:
                        kv.append(f"{k}: {_sql_quote(v)}")
                cy = f"CREATE (:Discovery {{{', '.join(kv)}}}) RETURN 1"
            else:
                # Idempotent import: MERGE by stable id, then SET other properties.
                # This avoids duplicate nodes on re-run and allows incremental updates.
                sets = []
                for k, v in props.items():
                    if k == "id" or v is None or v == "":
                        continue
                    if isinstance(v, (int, float)) and k == "confidence":
                        sets.append(f"d.{k} = {float(v)}")
                    else:
                        sets.append(f"d.{k} = {_sql_quote(v)}")
                cy = f"MERGE (d:Discovery {{id: {_sql_quote(did)}}})"
                if sets:
                    cy += " SET " + ", ".join(sets)
                cy += " RETURN 1"
            f.write(_cypher_stmt(graph, cy))
            count += 1

        f.write(f"\n-- Imported discoveries: {count}\n\n")

        # ---------------------------------------------------------------------
        # Tags (Tag nodes + HAS_TAG edges)
        # ---------------------------------------------------------------------
        # Create tag nodes
        f.write("-- Tags\n")
        for row in _iter_rows(conn, "SELECT DISTINCT tag FROM discovery_tags ORDER BY tag ASC"):
            tag = row["tag"]
            cy = f"MERGE (:Tag {{name: {_sql_quote(tag)}}}) RETURN 1"
            f.write(_cypher_stmt(graph, cy))
        f.write("\n")

        # Create HAS_TAG edges
        tag_edges_sql = """
            SELECT t.discovery_id, t.tag
            FROM discovery_tags t
        """
        for row in _iter_rows(conn, tag_edges_sql):
            did = row["discovery_id"]
            tag = row["tag"]
            rel_kw = "CREATE" if mode == "create" else "MERGE"
            cy = (
                f"MATCH (d:Discovery {{id: {_sql_quote(did)}}}), (t:Tag {{name: {_sql_quote(tag)}}}) "
                f"{rel_kw} (d)-[:HAS_TAG]->(t) RETURN 1"
            )
            f.write(_cypher_stmt(graph, cy))
        f.write("\n")

        # ---------------------------------------------------------------------
        # Discovery edges
        # - response_to edges (src -> dst) with response_type property
        # - related_to edges (src -> dst)
        # ---------------------------------------------------------------------
        edge_sql = """
            SELECT src_id, dst_id, edge_type, response_type, weight, created_at, created_by, metadata
            FROM discovery_edges
        """
        for row in _iter_rows(conn, edge_sql):
            et = (row["edge_type"] or "").strip().lower()
            src = row["src_id"]
            dst = row["dst_id"]
            if not src or not dst:
                continue

            if et == "response_to":
                resp_type = row["response_type"] or "extend"
                if mode == "create":
                    cy = (
                        f"MATCH (a:Discovery {{id: {_sql_quote(src)}}}), (b:Discovery {{id: {_sql_quote(dst)}}}) "
                        f"CREATE (a)-[:RESPONSE_TO {{response_type: {_sql_quote(resp_type)}}}]->(b) RETURN 1"
                    )
                else:
                    # MERGE edge and set response_type for idempotency.
                    cy = (
                        f"MATCH (a:Discovery {{id: {_sql_quote(src)}}}), (b:Discovery {{id: {_sql_quote(dst)}}}) "
                        f"MERGE (a)-[r:RESPONSE_TO]->(b) "
                        f"SET r.response_type = {_sql_quote(resp_type)} "
                        f"RETURN 1"
                    )
                f.write(_cypher_stmt(graph, cy))
            elif et == "related_to":
                rel_kw = "CREATE" if mode == "create" else "MERGE"
                cy = (
                    f"MATCH (a:Discovery {{id: {_sql_quote(src)}}}), (b:Discovery {{id: {_sql_quote(dst)}}}) "
                    f"{rel_kw} (a)-[:RELATED_TO]->(b) RETURN 1"
                )
                f.write(_cypher_stmt(graph, cy))
            else:
                # Keep prototype bounded to edges currently used by the codebase.
                continue

        # ---------------------------------------------------------------------
        # Dialectic sessions + messages
        # ---------------------------------------------------------------------
        if include_dialectic:
            f.write("\n-- Dialectic sessions\n")
            sessions_sql = """
                SELECT
                  session_id, paused_agent_id, reviewer_agent_id,
                  phase, status, created_at, updated_at,
                  reason, discovery_id, dispute_type,
                  session_type, topic, max_synthesis_rounds, synthesis_round
                FROM dialectic_sessions
                ORDER BY created_at ASC
            """
            for row in _iter_rows(conn, sessions_sql):
                sid = row["session_id"]
                if not sid:
                    continue
                props = {
                    "id": sid,
                    "status": row["status"],
                    "phase": row["phase"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "reason": _truncate(row["reason"], 600),
                    "discovery_id": row["discovery_id"],
                    "dispute_type": row["dispute_type"],
                    "session_type": row["session_type"],
                    "topic": _truncate(row["topic"], 300),
                    "max_synthesis_rounds": row["max_synthesis_rounds"],
                    "synthesis_round": row["synthesis_round"],
                }

                if mode == "create":
                    kv = []
                    for k, v in props.items():
                        if v is None or v == "":
                            continue
                        if k in ("max_synthesis_rounds", "synthesis_round"):
                            kv.append(f"{k}: {int(v)}")
                        else:
                            kv.append(f"{k}: {_sql_quote(v)}")
                    cy = f"CREATE (:DialecticSession {{{', '.join(kv)}}}) RETURN 1"
                else:
                    sets = []
                    for k, v in props.items():
                        if k == "id" or v is None or v == "":
                            continue
                        if k in ("max_synthesis_rounds", "synthesis_round"):
                            sets.append(f"s.{k} = {int(v)}")
                        else:
                            sets.append(f"s.{k} = {_sql_quote(v)}")
                    cy = f"MERGE (s:DialecticSession {{id: {_sql_quote(sid)}}})"
                    if sets:
                        cy += " SET " + ", ".join(sets)
                    cy += " RETURN 1"
                f.write(_cypher_stmt(graph, cy))

                # Link session to agents and discovery (best-effort; nodes may not exist)
                rel_kw = "CREATE" if mode == "create" else "MERGE"
                paused = row["paused_agent_id"]
                reviewer = row["reviewer_agent_id"]
                disc_id = row["discovery_id"]
                if paused and include_agents:
                    f.write(
                        _cypher_stmt(
                            graph,
                            f"MATCH (s:DialecticSession {{id: {_sql_quote(sid)}}}), (a:Agent {{id: {_sql_quote(paused)}}}) "
                            f"{rel_kw} (s)-[:PAUSED_AGENT]->(a) RETURN 1",
                        )
                    )
                if reviewer and include_agents:
                    f.write(
                        _cypher_stmt(
                            graph,
                            f"MATCH (s:DialecticSession {{id: {_sql_quote(sid)}}}), (r:Agent {{id: {_sql_quote(reviewer)}}}) "
                            f"{rel_kw} (s)-[:REVIEWER]->(r) RETURN 1",
                        )
                    )
                if disc_id:
                    f.write(
                        _cypher_stmt(
                            graph,
                            f"MATCH (s:DialecticSession {{id: {_sql_quote(sid)}}}), (d:Discovery {{id: {_sql_quote(disc_id)}}}) "
                            f"{rel_kw} (s)-[:ABOUT_DISCOVERY]->(d) RETURN 1",
                        )
                    )

            f.write("\n-- Dialectic messages\n")
            messages_sql = """
                SELECT
                  id, session_id, agent_id, message_type, timestamp,
                  root_cause, proposed_conditions_json, reasoning,
                  agrees, signature
                FROM dialectic_messages
                ORDER BY session_id ASC, id ASC
            """
            for row in _iter_rows(conn, messages_sql):
                mid = row["id"]
                sid = row["session_id"]
                aid = row["agent_id"]
                if mid is None or not sid:
                    continue
                msg_id = f"{sid}:{mid}"
                props = {
                    "id": msg_id,
                    "session_id": sid,
                    "agent_id": aid,
                    "message_type": row["message_type"],
                    "timestamp": row["timestamp"],
                    "root_cause": _truncate(row["root_cause"], 600),
                    "reasoning": _truncate(row["reasoning"], 1200),
                    "signature": _truncate(row["signature"], 200),
                    "seq": int(mid),
                }
                if row["agrees"] is not None:
                    props["agrees"] = 1 if int(row["agrees"]) else 0
                if row["proposed_conditions_json"]:
                    props["proposed_conditions_json"] = _truncate(row["proposed_conditions_json"], 1500)

                if mode == "create":
                    kv = []
                    for k, v in props.items():
                        if v is None or v == "":
                            continue
                        if k in ("seq", "agrees"):
                            kv.append(f"{k}: {int(v)}")
                        else:
                            kv.append(f"{k}: {_sql_quote(v)}")
                    cy = f"CREATE (:DialecticMessage {{{', '.join(kv)}}}) RETURN 1"
                else:
                    sets = []
                    for k, v in props.items():
                        if k == "id" or v is None or v == "":
                            continue
                        if k in ("seq", "agrees"):
                            sets.append(f"m.{k} = {int(v)}")
                        else:
                            sets.append(f"m.{k} = {_sql_quote(v)}")
                    cy = f"MERGE (m:DialecticMessage {{id: {_sql_quote(msg_id)}}})"
                    if sets:
                        cy += " SET " + ", ".join(sets)
                    cy += " RETURN 1"
                f.write(_cypher_stmt(graph, cy))

                rel_kw = "CREATE" if mode == "create" else "MERGE"
                f.write(
                    _cypher_stmt(
                        graph,
                        f"MATCH (s:DialecticSession {{id: {_sql_quote(sid)}}}), (m:DialecticMessage {{id: {_sql_quote(msg_id)}}}) "
                        f"{rel_kw} (s)-[:HAS_MESSAGE]->(m) RETURN 1",
                    )
                )
                if aid and include_agents:
                    f.write(
                        _cypher_stmt(
                            graph,
                            f"MATCH (a:Agent {{id: {_sql_quote(aid)}}}), (m:DialecticMessage {{id: {_sql_quote(msg_id)}}}) "
                            f"{rel_kw} (a)-[:WROTE]->(m) RETURN 1",
                        )
                    )

        # Finish
        f.write("COMMIT;\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Export SQLite knowledge graph to Apache AGE SQL import file.")
    p.add_argument("--sqlite", type=str, default="data/governance.db", help="Path to SQLite DB (default: data/governance.db)")
    p.add_argument("--out", type=str, required=True, help="Output SQL file path (to be piped into psql)")
    p.add_argument("--graph", type=str, default="governance", help="AGE graph name (default: governance)")
    p.add_argument("--limit", type=int, default=None, help="Optional max number of discoveries to export (for quick tests)")
    p.add_argument("--mode", type=str, default="merge", choices=["create", "merge"], help="Import mode: create (duplicates on rerun) or merge (idempotent). Default: merge")
    p.add_argument("--recreate-graph", action="store_true", help="Emit SQL to drop+create the AGE graph before import (clean test cycles).")
    p.add_argument("--no-agents", action="store_true", help="Skip exporting agents/lineage.")
    p.add_argument("--no-dialectic", action="store_true", help="Skip exporting dialectic sessions/messages.")
    args = p.parse_args()

    export(
        Path(args.sqlite),
        Path(args.out),
        graph=args.graph,
        limit=args.limit,
        mode=args.mode,  # type: ignore[arg-type]
        recreate_graph=bool(args.recreate_graph),
        include_agents=not bool(args.no_agents),
        include_dialectic=not bool(args.no_dialectic),
    )


if __name__ == "__main__":
    main()


