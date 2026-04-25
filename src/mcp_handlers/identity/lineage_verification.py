"""Same-host ppid consistency check (issue #128).

Cross-checks a child's self-declared `parent_agent_id` against the parent's
observable process state on the same host. Strictly observational — same
posture as #123: the agent still declares lineage; we add a *scope-bounded*
confidence signal on the declaration. Verified or mismatched, the audit
trail records what the server saw.

Verdict logic:
  - True  — at least one of the parent's live bindings on the child's host
            has pid == child.ppid
  - False — parent has live bindings on the child's host, but none match
            child.ppid → emit `identity_same_host_ppid_mismatch`
  - None  — no parent live binding on the child's host (cross-host or
            parent never recorded a binding); the column stays NULL

Naming discipline (per dialectic review): the column is
`same_host_ppid_consistent` and the event is
`identity_same_host_ppid_mismatch` rather than `verified_lineage` /
`identity_lineage_mismatch`. The narrower name prevents the inference
trap "no event = lineage was verified" — the system only ever checks
*same-host process ancestry*, never cross-host lineage.

Advisory-only contract: no internal consumer may treat
`same_host_ppid_consistent=false` or the mismatch event as grounds for
auto-archival, force-new, or any identity-mutating action. See
`tests/test_lineage_verification.py::test_no_auto_enforcement_consumers`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .process_binding import get_live_bindings

logger = logging.getLogger(__name__)


async def verify_lineage_bg(
    *,
    child_uuid: str,
    parent_uuid: str,
    child_host_id: str,
    child_ppid: int,
    child_pid: int,
    child_pid_start_time: float,
    child_transport: str,
) -> Optional[bool]:
    """Verify declared parent lineage against observable parent ppid (same host).

    Fire-and-forget background coroutine — caller schedules via
    `create_tracked_task`. Never raises; all failures are logged.

    Returns the verdict (True/False/None) for the test-side; production
    callers ignore it because the persistence and audit-event side-effects
    are the contract.
    """
    try:
        parent_bindings = await get_live_bindings(parent_uuid)
    except Exception as e:
        logger.debug(f"[PPID_CHECK] parent lookup failed (non-fatal): {e}")
        return None

    same_host = [b for b in parent_bindings if b.get("host_id") == child_host_id]
    if not same_host:
        # Cross-host or parent never recorded a binding → unverified.
        return None

    parent_pids_on_host = [int(b["pid"]) for b in same_host if b.get("pid") is not None]
    matched = child_ppid in parent_pids_on_host

    verdict = True if matched else False
    persist_succeeded = await _persist_verdict(
        child_uuid=child_uuid,
        child_host_id=child_host_id,
        child_pid=child_pid,
        child_pid_start_time=child_pid_start_time,
        child_transport=child_transport,
        verdict=verdict,
    )

    if not matched:
        _emit_lineage_mismatch_event(
            child_uuid,
            {
                "declared_parent_uuid": parent_uuid,
                "child_pid": child_pid,
                "child_ppid": child_ppid,
                "host_id": child_host_id,
                "parent_live_pids_on_host": parent_pids_on_host,
                "scope": "same_host_process_ancestry",
                "persist_succeeded": persist_succeeded,
            },
        )

    return verdict


async def _persist_verdict(
    *,
    child_uuid: str,
    child_host_id: str,
    child_pid: int,
    child_pid_start_time: float,
    child_transport: str,
    verdict: bool,
) -> bool:
    """Write same_host_ppid_consistent onto the child's binding row.

    Identifies the row by the same five-tuple used as the binding's UNIQUE
    constraint. Returns True iff the write completed without exception so
    the caller can include the status in the audit event payload —
    operators reading a mismatch event with persist_succeeded=false know
    to treat the column value as missing rather than authoritative.
    """
    try:
        from src.db import get_db
        db = get_db()
        async with db.acquire() as conn:
            status = await conn.execute(
                """
                UPDATE core.agent_process_bindings
                SET same_host_ppid_consistent = $1
                WHERE agent_id = $2
                  AND host_id = $3
                  AND pid = $4
                  AND pid_start_time = $5
                  AND transport = $6
                """,
                verdict,
                child_uuid,
                child_host_id,
                child_pid,
                child_pid_start_time,
                child_transport,
            )
        # asyncpg returns "UPDATE N" — 0 rows means the binding row was
        # never INSERTed (record_binding_bg failed silently before us).
        # Treat that as persist_succeeded=False so the audit event flags
        # the dangling state rather than implying the column was written.
        try:
            rows_updated = int((status or "UPDATE 0").split()[-1])
        except Exception:
            rows_updated = 0
        return rows_updated > 0
    except Exception as e:
        logger.debug(f"[PPID_CHECK] persist verdict failed (non-fatal): {e}")
        return False


def _emit_lineage_mismatch_event(child_uuid: str, payload: Dict[str, Any]) -> None:
    """Broadcast `identity_same_host_ppid_mismatch` for an observed mismatch.

    Event name is intentionally narrow: the absence of this event does NOT
    mean lineage is consistent — it only means same-host process ancestry
    was not observed to disagree with the declaration. Cross-host lineage
    is never checked.
    """
    logger.warning(
        "[PPID_MISMATCH] Agent %s declared parent_agent_id=%s; "
        "child pid=%s ppid=%s does not match any of parent's live pids %s on host %s",
        child_uuid[:8] + "...",
        str(payload.get("declared_parent_uuid", ""))[:8] + "...",
        payload.get("child_pid"),
        payload.get("child_ppid"),
        payload.get("parent_live_pids_on_host"),
        payload.get("host_id"),
    )

    try:
        from src.broadcaster import broadcaster_instance
    except Exception:
        return

    async def _broadcast():
        try:
            await broadcaster_instance.broadcast_event(
                event_type="identity_same_host_ppid_mismatch",
                agent_id=child_uuid,
                payload=payload,
            )
        except Exception as e:
            logger.debug(f"[PPID_MISMATCH] broadcast failed: {e}")

    try:
        from src.background_tasks import create_tracked_task
        create_tracked_task(_broadcast(), name="same_host_ppid_mismatch_event")
    except Exception:
        import asyncio
        try:
            asyncio.ensure_future(_broadcast())
        except Exception:
            pass
