"""Lineage verification (issue #128).

verify_lineage_bg cross-checks a child's declared parent_agent_id against
the observable parent ppid:

  - Look up parent's live bindings on the same host_id.
  - If any parent binding's pid matches child's ppid → verified=True.
  - Else if parent has live bindings on the host (but no pid match) →
    verified=False, emit identity_lineage_mismatch.
  - Else (no parent live binding on host, or cross-host) → verified=None,
    no event.

Audit-only — never resolves or recovers identity. Same posture as #123.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_handlers.identity import process_binding


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _binding(host="h1", pid=100, start=1.0, transport="http", ppid=None):
    return {
        "host_id": host,
        "pid": pid,
        "pid_start_time": start,
        "transport": transport,
        "tty": None,
        "ppid": ppid,
        "anchor_path_hash": None,
        "client_session_id": None,
        "onboard_ts": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }


def _make_mock_db_for_update(rows_updated: int = 1):
    """Build a mock DB whose acquire().__aenter__() returns a conn with execute().

    `execute` returns a fake asyncpg "UPDATE N" status string so the verdict
    persistence path can detect 0-row writes (the dangling-state case).
    """
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=f"UPDATE {rows_updated}")
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = False
    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)
    return db, conn


# -----------------------------------------------------------------------------
# verify_lineage_bg — core cases
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_lineage_matching_ppid_marks_verified():
    """Parent binding's pid matches child's ppid → verified=True, no event, DB updated."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=4242)]
    db, conn = _make_mock_db_for_update()
    emit = MagicMock()
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", emit):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert result is True
    emit.assert_not_called()
    conn.execute.assert_awaited()
    # Confirm the UPDATE wrote True to same_host_ppid_consistent
    sql = conn.execute.await_args.args[0]
    assert "same_host_ppid_consistent" in sql
    assert conn.execute.await_args.args[1] is True


@pytest.mark.asyncio
async def test_verify_lineage_payload_includes_child_pid_and_scope():
    """Mismatch payload must include child_pid (operator triage) and scope tag."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=9999)]
    db, _ = _make_mock_db_for_update()
    captured = {}

    def _capture(child_uuid, payload):
        captured["payload"] = payload

    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", _capture):
        await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    p = captured["payload"]
    assert p["child_pid"] == 5555
    assert p["scope"] == "same_host_process_ancestry"
    assert p["persist_succeeded"] is True


@pytest.mark.asyncio
async def test_verify_lineage_zero_row_update_flags_dangling_state():
    """Combined-failure path: record_binding_bg silently failed earlier so the
    binding row does not exist; verify_lineage_bg's UPDATE matches 0 rows.

    The mismatch event must still fire (audit trail) but persist_succeeded
    must be False so an operator can distinguish "checked and recorded"
    from "checked but the row was missing." Without this signal, an
    operator looking at the bindings table sees the column as NULL and
    has no way to correlate it with the event.
    """
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=9999)]
    db, _ = _make_mock_db_for_update(rows_updated=0)  # row was never inserted
    captured = {}

    def _capture(child_uuid, payload):
        captured["payload"] = payload

    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", _capture):
        await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert captured["payload"]["persist_succeeded"] is False


@pytest.mark.asyncio
async def test_verify_lineage_persist_failure_surfaces_in_event_payload():
    """When the UPDATE fails, the mismatch event still fires but flags persist_succeeded=false.

    Operator reading the event with persist_succeeded=false knows the
    same_host_ppid_consistent column will be NULL despite a verdict, and
    should treat the event as the authoritative record.
    """
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=9999)]
    db = MagicMock()
    db.acquire = MagicMock(side_effect=RuntimeError("write failed"))
    captured = {}

    def _capture(child_uuid, payload):
        captured["payload"] = payload

    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", _capture):
        await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert captured["payload"]["persist_succeeded"] is False


@pytest.mark.asyncio
async def test_verify_lineage_mismatch_emits_event():
    """Parent live on same host but pid != child.ppid → verified=False + audit event."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=9999)]
    db, conn = _make_mock_db_for_update()
    emit = MagicMock()
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", emit):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert result is False
    emit.assert_called_once()
    payload = emit.call_args.kwargs or emit.call_args.args
    # Event must include child uuid, parent uuid, child ppid, host, parent live pids
    # We check the function got positional args for child_uuid + the diagnostic payload.
    assert "child-1" in str(payload)
    assert "parent-1" in str(payload)
    assert conn.execute.await_args.args[1] is False


@pytest.mark.asyncio
async def test_verify_lineage_no_parent_binding_on_host_unverified():
    """No parent binding visible on child's host → verified=None, no event, no DB write."""
    from src.mcp_handlers.identity import lineage_verification

    db, conn = _make_mock_db_for_update()
    emit = MagicMock()
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=[]),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", emit):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert result is None
    emit.assert_not_called()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_lineage_cross_host_skipped():
    """Parent only has bindings on a different host → verified=None, no event.

    ppid is a per-host concept; cross-host lineage is out of scope (issue #128).
    """
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h2", pid=4242)]
    db, conn = _make_mock_db_for_update()
    emit = MagicMock()
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", emit):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert result is None
    emit.assert_not_called()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_lineage_multiple_parent_pids_one_matches():
    """Parent has multiple live bindings on host; one pid matches → verified=True."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [
        _binding(host="h1", pid=1111),
        _binding(host="h1", pid=4242),  # match
        _binding(host="h1", pid=2222),
    ]
    db, conn = _make_mock_db_for_update()
    emit = MagicMock()
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", emit):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert result is True
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_verify_lineage_swallows_db_errors():
    """DB failure during UPDATE is non-fatal — onboard must not break."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [_binding(host="h1", pid=4242)]
    db = MagicMock()
    db.acquire = MagicMock(side_effect=RuntimeError("pool exhausted"))
    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db):
        # Should not raise.
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )
    # On DB failure we still return the verification verdict (True here),
    # the persistence side just couldn't write — this is a debug log, not a raise.
    assert result is True


@pytest.mark.asyncio
async def test_verify_lineage_swallows_get_live_bindings_errors():
    """If parent lookup itself errors, return None and emit nothing."""
    from src.mcp_handlers.identity import lineage_verification

    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(side_effect=RuntimeError("nope")),
    ):
        result = await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )
    assert result is None


@pytest.mark.asyncio
async def test_verify_lineage_mismatch_event_payload_shape():
    """Audit event payload includes diagnostic fields for operator triage."""
    from src.mcp_handlers.identity import lineage_verification

    parent_bindings = [
        _binding(host="h1", pid=9999),
        _binding(host="h1", pid=8888),
    ]
    db, _ = _make_mock_db_for_update()
    captured = {}

    def _capture(child_uuid, payload):
        captured["child_uuid"] = child_uuid
        captured["payload"] = payload

    with patch.object(
        lineage_verification, "get_live_bindings",
        AsyncMock(return_value=parent_bindings),
    ), patch("src.db.get_db", return_value=db), \
         patch.object(lineage_verification, "_emit_lineage_mismatch_event", _capture):
        await lineage_verification.verify_lineage_bg(
            child_uuid="child-1",
            parent_uuid="parent-1",
            child_host_id="h1",
            child_ppid=4242,
            child_pid=5555,
            child_pid_start_time=1.0,
            child_transport="http",
        )

    assert captured["child_uuid"] == "child-1"
    p = captured["payload"]
    assert p["declared_parent_uuid"] == "parent-1"
    assert p["child_ppid"] == 4242
    assert p["host_id"] == "h1"
    # parent_live_pids is the set of pids the parent has live on this host
    assert set(p["parent_live_pids_on_host"]) == {9999, 8888}


# -----------------------------------------------------------------------------
# get_live_bindings — extended to include same_host_ppid_consistent column
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_live_bindings_includes_same_host_ppid_consistent():
    """get_live_bindings returns same_host_ppid_consistent in each row (post-#128 schema)."""
    ts = datetime(2026, 4, 25, 1, 2, 3, tzinfo=timezone.utc)
    row = {
        "host_id": "h1", "pid": 100, "pid_start_time": 1.0,
        "transport": "http", "tty": None, "ppid": 1,
        "anchor_path_hash": None, "client_session_id": None,
        "onboard_ts": ts, "last_seen": ts,
        "same_host_ppid_consistent": True,
    }
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[row])
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = False
    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)

    with patch("src.db.get_db", return_value=db):
        bindings = await process_binding.get_live_bindings("agent-1")
    assert bindings[0]["same_host_ppid_consistent"] is True


# -----------------------------------------------------------------------------
# list_process_bindings — surfaces same_host_ppid_consistent to operator
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_process_bindings_surfaces_same_host_ppid_consistent():
    """MCP tool propagates same_host_ppid_consistent from get_live_bindings to operator payload."""
    from src.mcp_handlers.identity import process_binding_handler

    bindings = [
        {"host_id": "h1", "pid": 100, "pid_start_time": 1.0, "transport": "http",
         "tty": None, "ppid": 4242, "anchor_path_hash": None,
         "client_session_id": None, "onboard_ts": None, "last_seen": None,
         "same_host_ppid_consistent": True},
    ]
    with patch.object(
        process_binding_handler,
        "get_live_bindings",
        AsyncMock(return_value=bindings),
    ):
        result = await process_binding_handler.handle_list_process_bindings(
            {"agent_uuid": "agent-1"}
        )
    import json
    payload = json.loads(result[0].text)
    assert payload["bindings"][0]["same_host_ppid_consistent"] is True


# -----------------------------------------------------------------------------
# Advisory-only contract — pin the posture in code per dialectic review.
# This test fails if any code path consumes the mismatch event or column
# value to trigger an identity-mutating action (force_new, archival, etc).
# -----------------------------------------------------------------------------


def test_no_auto_enforcement_consumers():
    """No code path may treat same_host_ppid_consistent or the mismatch event
    as grounds for auto-archival, force-new, or any identity-mutating action.

    The signal is advisory-only by contract (issue #128 §"Why this is
    strictly observational"). If a future change wires an automated
    consumer, this test fails and the change must reopen the threat model
    in the original issue rather than silently inverting the posture.
    """
    import subprocess
    import re

    # Search the production tree (excluding tests and the verifier itself
    # which legitimately mention these names) for any reference paired with
    # an identity-mutating action.
    forbidden_co_occurrence = re.compile(
        r"(same_host_ppid_consistent|identity_same_host_ppid_mismatch).{0,500}"
        r"(force_new\s*=\s*True|archive_orphan|update_agent_fields\(.*status\s*=\s*[\"']archived)",
        re.DOTALL,
    )
    result = subprocess.run(
        ["grep", "-rln", "-E",
         "same_host_ppid_consistent|identity_same_host_ppid_mismatch",
         "src/", "agents/"],
        capture_output=True, text=True,
    )
    files = [f for f in result.stdout.splitlines()
             if f and "lineage_verification" not in f
             and "process_binding" not in f]  # owners of the signal
    for path in files:
        with open(path) as fh:
            content = fh.read()
        assert not forbidden_co_occurrence.search(content), (
            f"{path}: detected a likely auto-enforcement consumer of the "
            f"same-host ppid signal. Per issue #128 the signal is "
            f"advisory-only — reopen the threat model before adding "
            f"enforcement."
        )
