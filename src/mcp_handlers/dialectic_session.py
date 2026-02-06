"""
Dialectic Session Persistence

Handles saving and loading dialectic sessions to/from disk.
All I/O operations are async to prevent blocking the event loop.
"""

from typing import Dict, Optional, List, Any
from pathlib import Path
import json
import os
import asyncio
from datetime import datetime, timedelta

from src.dialectic_protocol import DialecticSession, DialecticPhase
from src.logging_utils import get_logger
from .shared import get_mcp_server

logger = get_logger(__name__)

# Optional SQLite backend (cross-process shared state)
from src.dialectic_db import (
    get_session_async as sqlite_get_session,
    get_active_sessions_async as sqlite_get_active_sessions,
)

# Get project root for session storage
try:
    project_root = Path(get_mcp_server().project_root)
except (AttributeError, TypeError):
    project_root = Path(__file__).parent.parent.parent

SESSION_STORAGE_DIR = project_root / "data" / "dialectic_sessions"
# Note: Directory creation is deferred to first use (in save_session/load_session)
# to avoid blocking during module import

# Active dialectic sessions (in-memory + persistent storage)
ACTIVE_SESSIONS: Dict[str, DialecticSession] = {}

# Session metadata cache for fast lookups (avoids repeated disk I/O)
# Format: {agent_id: {'in_session': bool, 'timestamp': float, 'session_ids': [str]}}
_SESSION_METADATA_CACHE: Dict[str, Dict] = {}
_CACHE_TTL = 60.0  # Cache TTL in seconds (1 minute)

UNITARES_DIALECTIC_BACKEND = os.getenv("UNITARES_DIALECTIC_BACKEND", "auto").strip().lower()  # json|sqlite|postgres|auto
UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT = os.getenv("UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)


def _resolve_dialectic_backend() -> str:
    """
    Resolve dialectic backend.

    - postgres: use PostgreSQL (primary, recommended)
    - json: read/write JSON files only
    - sqlite: prefer SQLite for reads (legacy)
    - auto: prefer postgres if available, else sqlite, else json.
    """
    if UNITARES_DIALECTIC_BACKEND in ("json", "sqlite", "postgres"):
        return UNITARES_DIALECTIC_BACKEND
    # auto: prefer postgres
    return "postgres"


def _reconstruct_session_from_dict(session_id: str, session_data: Dict) -> Optional[DialecticSession]:
    """Reconstruct DialecticSession from a dict (from JSON file or SQLite)."""
    try:
        from src.dialectic_protocol import DialecticMessage, Resolution

        # Reconstruct transcript
        transcript = []
        for msg_dict in session_data.get("transcript") or session_data.get("messages") or []:
            # SQLite uses message_type; JSON uses phase.
            phase = msg_dict.get("phase") or msg_dict.get("message_type") or "thesis"
            msg = DialecticMessage(
                phase=phase,
                agent_id=msg_dict.get("agent_id", ""),
                timestamp=msg_dict.get("timestamp", ""),
                root_cause=msg_dict.get("root_cause"),
                observed_metrics=msg_dict.get("observed_metrics"),
                proposed_conditions=msg_dict.get("proposed_conditions"),
                reasoning=msg_dict.get("reasoning"),
                agrees=msg_dict.get("agrees"),
                concerns=msg_dict.get("concerns"),
            )
            transcript.append(msg)

        # Reconstruct resolution if present
        resolution = None
        if session_data.get("resolution"):
            res_dict = session_data["resolution"]
            resolution = Resolution(
                action=res_dict.get("action", "resume"),
                conditions=res_dict.get("conditions", []),
                root_cause=res_dict.get("root_cause", ""),
                reasoning=res_dict.get("reasoning", ""),
                signature_a=res_dict.get("signature_a", ""),
                signature_b=res_dict.get("signature_b", ""),
                timestamp=res_dict.get("timestamp", datetime.now().isoformat()),
            )

        # Phase
        phase_str = session_data.get("phase", "thesis")
        try:
            phase = DialecticPhase(phase_str)
        except ValueError:
            phase = DialecticPhase.THESIS

        paused_agent_state = session_data.get("paused_agent_state", {}) or {}
        session_type = session_data.get("session_type", "recovery") or "recovery"
        topic = session_data.get("topic")
        max_synthesis_rounds = session_data.get("max_synthesis_rounds", 5) or 5

        session = DialecticSession(
            paused_agent_id=session_data.get("paused_agent_id", ""),
            reviewer_agent_id=session_data.get("reviewer_agent_id", ""),
            paused_agent_state=paused_agent_state,
            discovery_id=session_data.get("discovery_id"),
            dispute_type=session_data.get("dispute_type"),
            session_type=session_type,
            topic=topic,
            max_synthesis_rounds=max_synthesis_rounds,
        )

        session.session_id = session_id
        session.phase = phase
        session.transcript = transcript
        session.resolution = resolution
        session.synthesis_round = int(session_data.get("synthesis_round", 0) or 0)
        created_at_str = session_data.get("created_at")
        if created_at_str:
            # Handle both string and datetime objects from different backends
            if isinstance(created_at_str, str):
                session.created_at = datetime.fromisoformat(created_at_str)
            elif isinstance(created_at_str, datetime):
                session.created_at = created_at_str

        # Restore timeouts based on session type
        if session.session_type == "exploration":
            session._max_antithesis_wait = timedelta(hours=24)
            session._max_synthesis_wait = timedelta(hours=6)
            session._max_total_time = timedelta(hours=72)
        else:
            session._max_antithesis_wait = session.MAX_ANTITHESIS_WAIT
            session._max_synthesis_wait = session.MAX_SYNTHESIS_WAIT
            session._max_total_time = session.MAX_TOTAL_TIME

        return session
    except Exception as e:
        logger.error(f"Error reconstructing session {session_id}: {e}", exc_info=True)
        return None


async def save_session(session: DialecticSession) -> None:
    """
    Persist dialectic session to disk - ASYNC to prevent Claude Desktop freezing.
    
    Dialectic sessions are critical for recovery - they must be saved before handler returns.
    Using async executor ensures file is on disk without blocking the event loop.
    """
    try:
        if not UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT:
            return

        session_file = SESSION_STORAGE_DIR / f"{session.session_id}.json"
        session_data = session.to_dict()
        
        # CRITICAL: Run file I/O in executor to avoid blocking event loop
        # These are small files (<10KB) but blocking I/O freezes Claude Desktop
        # Using executor ensures non-blocking persistence
        loop = asyncio.get_running_loop()
        
        def _write_session_sync():
            """Synchronous file write - runs in executor to avoid blocking"""
            # Ensure directory exists (inside executor to avoid blocking)
            SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            
            json_str = json.dumps(session_data, indent=2)
            with open(session_file, 'w', encoding='utf-8') as f:
                f.write(json_str)
                f.flush()  # Ensure buffered data written
                os.fsync(f.fileno())  # Force write to disk
            
            # Verify file exists and has content
            if not session_file.exists():
                raise FileNotFoundError(f"Session file not found after write: {session_file}")
            
            file_size = session_file.stat().st_size
            if file_size == 0:
                raise ValueError(f"Session file is empty: {session_file}")
            
            return file_size
        
        # Run in executor to avoid blocking event loop (prevents Claude Desktop freezing)
        await loop.run_in_executor(None, _write_session_sync)
            
    except Exception as e:
        import traceback
        logger.error(f"Could not save session {session.session_id}: {e}", exc_info=True)
        # Re-raise to ensure caller knows save failed
        raise


async def load_all_sessions() -> int:
    """
    Load all active dialectic sessions from disk into ACTIVE_SESSIONS.
    Called on server startup to restore sessions after restart.
    
    OPTIMIZED: Loads sessions in parallel to prevent blocking startup.
    This prevents Claude Desktop from freezing during initialization.
    
    Returns:
        Number of sessions loaded
    """
    loaded_count = 0
    try:
        backend = _resolve_dialectic_backend()
        if backend in ("sqlite", "postgres"):
            # Load active sessions from PostgreSQL/SQLite (cross-process visibility).
            # We still keep ACTIVE_SESSIONS as a process-local cache for speed.
            sessions = await sqlite_get_active_sessions(limit=500)
            for s in sessions:
                session_id = s.get("session_id")
                if not session_id:
                    continue
                if session_id in ACTIVE_SESSIONS:
                    continue
                # Prefer fully reconstructed session with messages
                full = await sqlite_get_session(session_id)
                if not full:
                    continue
                session = _reconstruct_session_from_dict(session_id, full)
                if session and session.phase not in [DialecticPhase.RESOLVED, DialecticPhase.FAILED, DialecticPhase.ESCALATED]:
                    ACTIVE_SESSIONS[session_id] = session
                    loaded_count += 1
            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} active dialectic session(s) from SQLite")
            return loaded_count

        loop = asyncio.get_running_loop()
        
        # Check directory existence and list files in executor to avoid blocking
        def _list_sessions_sync():
            """Synchronous directory check and file listing - runs in executor"""
            SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            if not SESSION_STORAGE_DIR.exists():
                return []
            return list(SESSION_STORAGE_DIR.glob("*.json"))
        
        session_files = await loop.run_in_executor(None, _list_sessions_sync)
        
        if not session_files:
            return 0
        
        # OPTIMIZATION: Load sessions in parallel instead of sequentially
        # This prevents blocking startup when there are many sessions
        async def load_and_restore(session_file: Path) -> Optional[str]:
            """Load a single session and restore if active"""
            try:
                session_id = session_file.stem
                # Skip if already in memory
                if session_id in ACTIVE_SESSIONS:
                    return None
                
                # Load session (already async, uses executor)
                session = await load_session(session_id)
                if session:
                    # Only restore active sessions (not resolved/failed/escalated)
                    if session.phase not in [DialecticPhase.RESOLVED, DialecticPhase.FAILED, DialecticPhase.ESCALATED]:
                        ACTIVE_SESSIONS[session_id] = session
                        return session_id
                    # Check for timeout - mark as failed if expired
                    elif session.phase == DialecticPhase.THESIS or session.phase == DialecticPhase.ANTITHESIS:
                        max_total = getattr(session, '_max_total_time', DialecticSession.MAX_TOTAL_TIME)
                        if datetime.now() - session.created_at > max_total:
                            # Session expired - mark as failed
                            session.phase = DialecticPhase.FAILED
                            await save_session(session)
                return None
            except (IOError, json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Could not load session {session_file.stem}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error loading session {session_file.stem}: {e}", exc_info=True)
                return None
        
        # Load all sessions in parallel (much faster than sequential)
        if session_files:
            results = await asyncio.gather(*[load_and_restore(f) for f in session_files], return_exceptions=True)
            loaded_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
        
        if loaded_count > 0:
            logger.info(f"Loaded {loaded_count} active dialectic session(s) from disk")
        
        return loaded_count
    except (IOError, OSError) as e:
        logger.warning(f"Could not load sessions from disk: {e}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error loading sessions from disk: {e}", exc_info=True)
        return 0


async def load_session(session_id: str) -> Optional[DialecticSession]:
    """Load dialectic session from disk - ASYNC to prevent blocking"""
    try:
        backend = _resolve_dialectic_backend()
        if backend in ("sqlite", "postgres"):
            try:
                session_data = await sqlite_get_session(session_id)
                if session_data:
                    # Normalize keys to match reconstruction function expectations
                    if "messages" in session_data and "transcript" not in session_data:
                        session_data["transcript"] = session_data["messages"]
                    # If schema didn't store these yet, keep safe defaults
                    session_data.setdefault("session_type", session_data.get("session_type") or "recovery")
                    session_data.setdefault("max_synthesis_rounds", session_data.get("max_synthesis_rounds") or 5)
                    session_data.setdefault("synthesis_round", session_data.get("synthesis_round") or 0)
                    session = _reconstruct_session_from_dict(session_id, session_data)
                    if session:
                        return session
            except Exception as e:
                logger.warning(f"PostgreSQL load failed for session {session_id}, falling back to JSON: {e}")

        session_file = SESSION_STORAGE_DIR / f"{session_id}.json"
        
        # Use executor for file I/O to avoid blocking event loop (prevents Claude Desktop freezing)
        loop = asyncio.get_running_loop()
        
        def _load_session_sync():
            """Synchronous file read - runs in executor"""
            # Ensure directory exists (inside executor to avoid blocking)
            SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            
            if not session_file.exists():
                return None
            
            with open(session_file, 'r') as f:
                return json.load(f)
        
        session_data = await loop.run_in_executor(None, _load_session_sync)
        
        if session_data is None:
            return None
        
        return _reconstruct_session_from_dict(session_id, session_data)
    except (IOError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read session file {session_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading session {session_id}: {e}", exc_info=True)
        return None


async def load_session_as_dict(session_id: str) -> Optional[Dict[str, Any]]:
    """Load session data formatted for API response, skipping object reconstruction.

    This is a fast path for read-only consumers (e.g. dashboard) that don't need
    DialecticSession objects — avoids the reconstruct→to_dict() round-trip.
    Returns None if DB unavailable so caller can fall back to full load_session().
    """
    backend = _resolve_dialectic_backend()
    if backend not in ("sqlite", "postgres"):
        return None
    try:
        from src.dialectic_db import get_dialectic_db
        db = await get_dialectic_db()
        await db._ensure_pool()
        async with db._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT session_id, phase, status, session_type,
                       paused_agent_id, reviewer_agent_id, topic,
                       created_at, resolution_json
                FROM core.dialectic_sessions WHERE session_id = $1
            """, session_id)
            if not row:
                return None

            msg_rows = await conn.fetch("""
                SELECT message_type, agent_id, timestamp, reasoning,
                       root_cause, proposed_conditions, concerns, agrees
                FROM core.dialectic_messages
                WHERE session_id = $1 ORDER BY message_id
            """, session_id)

            created = row["created_at"]
            result = {
                "session_id": row["session_id"],
                "phase": row["phase"] or row["status"] or "unknown",
                "session_type": row["session_type"] or "unknown",
                "paused_agent": row["paused_agent_id"] or "unknown",
                "reviewer": row["reviewer_agent_id"],
                "topic": row["topic"] or "",
                "created": created.isoformat() if hasattr(created, 'isoformat') else str(created or ""),
                "message_count": len(msg_rows),
                "transcript": [],
            }

            res = row["resolution_json"]
            if res:
                result["resolution"] = res if isinstance(res, dict) else json.loads(res)

            for msg in msg_rows:
                m = {
                    "phase": msg["message_type"],
                    "role": msg["message_type"],
                    "agent_id": msg["agent_id"],
                    "timestamp": msg["timestamp"].isoformat() if hasattr(msg["timestamp"], 'isoformat') else msg["timestamp"],
                    "reasoning": msg["reasoning"],
                }
                if msg["root_cause"]:
                    m["root_cause"] = msg["root_cause"]
                if msg["proposed_conditions"]:
                    val = msg["proposed_conditions"]
                    m["proposed_conditions"] = val if isinstance(val, (list, dict)) else json.loads(val)
                if msg["concerns"]:
                    val = msg["concerns"]
                    m["concerns"] = val if isinstance(val, (list, dict)) else json.loads(val)
                if msg["agrees"] is not None:
                    m["agrees"] = bool(msg["agrees"])
                result["transcript"].append(m)

            return result
    except Exception as e:
        logger.warning(f"Fast load failed for session {session_id}: {e}")
        return None


async def verify_data_consistency() -> Dict[str, Any]:
    """
    Verify that SQLite and JSON dialectic data are consistent.
    Called on startup and periodically to detect data loss.

    Returns:
        Dict with consistency status and any issues found
    """
    import sqlite3

    loop = asyncio.get_running_loop()

    def _check_consistency():
        issues = []
        stats = {
            "json_sessions": 0,
            "sqlite_sessions": 0,
            "missing_json_backup": [],
            "missing_sqlite": [],
            "message_mismatches": [],
            "empty_sessions": [],
        }

        # Count JSON sessions
        json_sessions = {}
        if SESSION_STORAGE_DIR.exists():
            for f in SESSION_STORAGE_DIR.glob("*.json"):
                try:
                    with open(f) as fp:
                        data = json.load(fp)
                        sid = data.get("session_id", f.stem)
                        json_sessions[sid] = len(data.get("transcript", []))
                except Exception:
                    pass
        stats["json_sessions"] = len(json_sessions)

        # Count SQLite sessions
        sqlite_sessions = {}
        sqlite_messages = {}
        db_path = Path(__file__).parent.parent.parent / "data" / "governance.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path), timeout=5.0)
                c = conn.cursor()
                c.execute("SELECT session_id FROM dialectic_sessions")
                for row in c.fetchall():
                    sqlite_sessions[row[0]] = True
                c.execute("SELECT session_id, COUNT(*) FROM dialectic_messages GROUP BY session_id")
                for row in c.fetchall():
                    sqlite_messages[row[0]] = row[1]
                conn.close()
            except Exception as e:
                issues.append(f"SQLite query failed: {e}")
        stats["sqlite_sessions"] = len(sqlite_sessions)

        # Find discrepancies
        for sid in sqlite_sessions:
            if sid not in json_sessions:
                stats["missing_json_backup"].append(sid)
            sqlite_count = sqlite_messages.get(sid, 0)
            json_count = json_sessions.get(sid, 0)
            if json_count > sqlite_count:
                stats["message_mismatches"].append((sid, json_count, sqlite_count))
            if sqlite_count == 0 and json_count == 0:
                stats["empty_sessions"].append(sid)

        for sid in json_sessions:
            if sid not in sqlite_sessions:
                stats["missing_sqlite"].append(sid)

        return {
            "consistent": len(stats["missing_json_backup"]) == 0 and len(stats["missing_sqlite"]) == 0,
            "stats": stats,
            "issues": issues,
        }

    return await loop.run_in_executor(None, _check_consistency)


async def run_startup_consolidation() -> Dict[str, Any]:
    """
    Run data consolidation on startup to ensure all sessions are backed up.
    This prevents data loss from sessions that exist only in SQLite.
    """
    import sqlite3

    result = {
        "exported": 0,
        "synced": 0,
        "errors": [],
    }

    loop = asyncio.get_running_loop()

    def _consolidate():
        exported = 0
        db_path = Path(__file__).parent.parent.parent / "data" / "governance.db"

        if not db_path.exists():
            return exported

        try:
            conn = sqlite3.connect(str(db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            # Get all sessions from SQLite
            c.execute("""
                SELECT session_id, paused_agent_id, reviewer_agent_id, phase, status,
                       created_at, topic, session_type, paused_agent_state_json
                FROM dialectic_sessions
            """)
            sessions = c.fetchall()

            for row in sessions:
                sid = row["session_id"]
                json_path = SESSION_STORAGE_DIR / f"{sid}.json"

                # Get messages
                c.execute("""
                    SELECT agent_id, message_type, timestamp, reasoning, root_cause,
                           proposed_conditions_json, observed_metrics_json, concerns_json, agrees
                    FROM dialectic_messages
                    WHERE session_id = ?
                    ORDER BY timestamp
                """, (sid,))
                messages = []
                for msg in c.fetchall():
                    messages.append({
                        "phase": msg["message_type"],
                        "agent_id": msg["agent_id"],
                        "timestamp": msg["timestamp"],
                        "reasoning": msg["reasoning"],
                        "root_cause": msg["root_cause"],
                        "proposed_conditions": json.loads(msg["proposed_conditions_json"]) if msg["proposed_conditions_json"] else [],
                        "observed_metrics": json.loads(msg["observed_metrics_json"]) if msg["observed_metrics_json"] else None,
                        "concerns": json.loads(msg["concerns_json"]) if msg["concerns_json"] else None,
                        "agrees": bool(msg["agrees"]) if msg["agrees"] is not None else None,
                    })

                sqlite_count = len(messages)

                # Check if JSON needs update
                json_count = 0
                if json_path.exists():
                    try:
                        with open(json_path) as f:
                            existing = json.load(f)
                            json_count = len(existing.get("transcript", []))
                    except Exception:
                        pass

                # Export if SQLite has more data
                if sqlite_count > json_count or not json_path.exists():
                    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                    export_data = {
                        "session_id": sid,
                        "paused_agent_id": row["paused_agent_id"],
                        "reviewer_agent_id": row["reviewer_agent_id"],
                        "phase": row["phase"],
                        "synthesis_round": 0,
                        "transcript": messages,
                        "resolution": None,
                        "created_at": row["created_at"],
                        "session_type": row["session_type"],
                        "topic": row["topic"],
                        "paused_agent_state": json.loads(row["paused_agent_state_json"]) if row["paused_agent_state_json"] else {},
                    }
                    with open(json_path, 'w') as f:
                        json.dump(export_data, f, indent=2)
                    exported += 1

            conn.close()
        except Exception as e:
            result["errors"].append(str(e))

        return exported

    result["exported"] = await loop.run_in_executor(None, _consolidate)

    if result["exported"] > 0:
        logger.info(f"Startup consolidation: exported {result['exported']} sessions to JSON backup")

    return result


async def list_all_sessions(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    include_transcript: bool = False
) -> List[Dict[str, Any]]:
    """
    List all dialectic sessions with optional filtering.

    Primary backend is PostgreSQL (core.dialectic_sessions).
    Falls back to JSON files if PostgreSQL fails.

    Args:
        agent_id: Filter by agent (requestor or reviewer)
        status: Filter by phase (e.g., 'resolved', 'failed', 'pending')
        limit: Max sessions to return (default 50)
        include_transcript: Include full transcript (default False for performance)

    Returns:
        List of session summaries
    """
    # Primary: Query PostgreSQL
    try:
        from src.dialectic_db import get_dialectic_db
        db = await get_dialectic_db()
        await db._ensure_pool()

        async with db._pool.acquire() as conn:
            # Build query with filters (LEFT JOIN for pre-aggregated message count)
            query = """
                SELECT
                    ds.session_id,
                    ds.phase,
                    ds.status,
                    ds.session_type,
                    ds.paused_agent_id,
                    ds.reviewer_agent_id,
                    ds.topic,
                    ds.created_at,
                    ds.resolution_json,
                    COALESCE(mc.cnt, 0) as message_count
                FROM core.dialectic_sessions ds
                LEFT JOIN (
                    SELECT session_id, COUNT(*) as cnt
                    FROM core.dialectic_messages
                    GROUP BY session_id
                ) mc ON mc.session_id = ds.session_id
                WHERE 1=1
            """
            params = []
            param_idx = 1

            if agent_id:
                query += f" AND (ds.paused_agent_id = ${param_idx} OR ds.reviewer_agent_id = ${param_idx + 1})"
                params.extend([agent_id, agent_id])
                param_idx += 2

            if status:
                query += f" AND (LOWER(ds.phase) LIKE ${param_idx} OR LOWER(ds.status) LIKE ${param_idx})"
                params.append(f"%{status.lower()}%")
                param_idx += 1

            query += f" ORDER BY ds.created_at DESC LIMIT ${param_idx}"
            params.append(limit)

            rows = await conn.fetch(query, *params)

            result = []
            for row in rows:
                created_at = row["created_at"]
                if created_at and hasattr(created_at, 'isoformat'):
                    created_at = created_at.isoformat()

                summary = {
                    "session_id": row["session_id"],
                    "phase": row["phase"] or row["status"] or "unknown",
                    "session_type": row["session_type"] or "unknown",
                    "paused_agent": row["paused_agent_id"] or "unknown",
                    "reviewer": row["reviewer_agent_id"],
                    "topic": row["topic"] or "",
                    "created": created_at or "",
                    "message_count": row["message_count"] or 0,
                }

                # Parse resolution if present
                resolution = row["resolution_json"]
                if resolution:
                    if isinstance(resolution, str):
                        try:
                            summary["resolution"] = json.loads(resolution)
                        except Exception:
                            pass
                    elif isinstance(resolution, dict):
                        summary["resolution"] = resolution

                # Include transcript if requested
                if include_transcript:
                    msg_rows = await conn.fetch("""
                        SELECT message_type, agent_id, timestamp, root_cause,
                               proposed_conditions, reasoning, observed_metrics,
                               concerns, agrees
                        FROM core.dialectic_messages
                        WHERE session_id = $1
                        ORDER BY message_id
                    """, row["session_id"])

                    messages = []
                    for msg_row in msg_rows:
                        msg = {
                            "phase": msg_row["message_type"],
                            "agent_id": msg_row["agent_id"],
                            "timestamp": msg_row["timestamp"].isoformat() if msg_row["timestamp"] and hasattr(msg_row["timestamp"], 'isoformat') else msg_row["timestamp"],
                            "reasoning": msg_row["reasoning"],
                            "root_cause": msg_row["root_cause"],
                        }
                        if msg_row["proposed_conditions"]:
                            val = msg_row["proposed_conditions"]
                            msg["proposed_conditions"] = val if isinstance(val, (list, dict)) else json.loads(val)
                        if msg_row["concerns"]:
                            val = msg_row["concerns"]
                            msg["concerns"] = val if isinstance(val, (list, dict)) else json.loads(val)
                        if msg_row["agrees"] is not None:
                            msg["agrees"] = bool(msg_row["agrees"])
                        messages.append(msg)

                    summary["transcript"] = messages

                result.append(summary)

        logger.debug(f"Listed {len(result)} sessions from PostgreSQL")
        return result
    except Exception as e:
        logger.warning(f"PostgreSQL list_sessions failed: {e}")

    # Fallback: JSON files
    loop = asyncio.get_running_loop()
    SESSION_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _list_sessions_json():
        """Fallback to JSON files"""
        result = []
        session_files = sorted(
            SESSION_STORAGE_DIR.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for session_file in session_files[:limit * 2]:
            if len(result) >= limit:
                break
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)

                session_id = session_file.stem

                if agent_id:
                    paused = data.get("paused_agent_id", "")
                    reviewer = data.get("reviewer_agent_id", "")
                    if agent_id not in [paused, reviewer]:
                        continue

                if status:
                    phase = data.get("phase", "")
                    if status.lower() not in phase.lower():
                        continue

                summary = {
                    "session_id": session_id,
                    "phase": data.get("phase", "unknown"),
                    "session_type": data.get("session_type", "unknown"),
                    "paused_agent": data.get("paused_agent_id", "unknown"),
                    "reviewer": data.get("reviewer_agent_id"),
                    "topic": data.get("topic", ""),
                    "created": data.get("created_at", ""),
                    "message_count": len(data.get("transcript", data.get("messages", []))),
                }

                if include_transcript:
                    summary["transcript"] = data.get("transcript", data.get("messages", []))

                result.append(summary)

            except Exception as e:
                logger.warning(f"Could not read session {session_file}: {e}")
                continue

        return result

    sessions = await loop.run_in_executor(None, _list_sessions_json)
    return sessions
