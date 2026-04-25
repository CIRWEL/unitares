"""Concurrent identity binding invariant (issue #123).

Covers:
  * validate_fingerprint — schema coercion
  * capture_process_fingerprint — client-side helper
  * record_binding_bg — detection fires exactly when ≥2 live bindings exist
    with distinct execution contexts AND allow_concurrent_contexts=false
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_handlers.identity import process_binding
from src.mcp_handlers.identity.process_binding import (
    ProcessFingerprint,
    validate_fingerprint,
)


# -----------------------------------------------------------------------------
# validate_fingerprint
# -----------------------------------------------------------------------------


def test_validate_fingerprint_happy_path():
    raw = {
        "host_id": "host-abc",
        "pid": 1234,
        "pid_start_time": 1_777_013_157.42,
        "transport": "http",
        "ppid": 1,
        "tty": "/dev/ttys003",
        "anchor_path_hash": "deadbeef",
    }
    fp = validate_fingerprint(raw)
    assert isinstance(fp, ProcessFingerprint)
    assert fp.host_id == "host-abc"
    assert fp.pid == 1234
    assert fp.pid_start_time == 1_777_013_157.42
    assert fp.transport == "http"
    assert fp.ppid == 1
    assert fp.tty == "/dev/ttys003"
    assert fp.anchor_path_hash == "deadbeef"


def test_validate_fingerprint_rejects_non_dict():
    assert validate_fingerprint(None) is None
    assert validate_fingerprint("nope") is None
    assert validate_fingerprint(42) is None


def test_validate_fingerprint_requires_identity_key_fields():
    assert validate_fingerprint({"pid": 1, "pid_start_time": 1.0}) is None
    assert validate_fingerprint({"host_id": "h", "pid_start_time": 1.0}) is None
    assert validate_fingerprint({"host_id": "h", "pid": 1}) is None


def test_validate_fingerprint_rejects_nonpositive_pid():
    raw = {"host_id": "h", "pid": 0, "pid_start_time": 1.0}
    assert validate_fingerprint(raw) is None
    raw["pid"] = -1
    assert validate_fingerprint(raw) is None


def test_validate_fingerprint_unknown_transport_falls_through_to_unknown():
    raw = {
        "host_id": "h",
        "pid": 1,
        "pid_start_time": 1.0,
        "transport": "bogus-transport",
    }
    fp = validate_fingerprint(raw)
    assert fp is not None
    assert fp.transport == "unknown"


def test_validate_fingerprint_optional_fields_dropped_when_wrong_type():
    raw = {
        "host_id": "h",
        "pid": 1,
        "pid_start_time": 1.0,
        "ppid": "not-an-int",
        "tty": 12345,
        "anchor_path_hash": {"not": "a string"},
    }
    fp = validate_fingerprint(raw)
    assert fp is not None
    assert fp.ppid is None
    assert fp.tty is None
    assert fp.anchor_path_hash is None


# -----------------------------------------------------------------------------
# client-side capture helper
# -----------------------------------------------------------------------------


def test_capture_process_fingerprint_returns_identity_key_fields():
    from unitares_sdk.utils import capture_process_fingerprint

    fp = capture_process_fingerprint(transport="http")
    assert "host_id" in fp and isinstance(fp["host_id"], str) and fp["host_id"]
    assert "pid" in fp and fp["pid"] > 0
    assert fp["transport"] == "http"
    # pid_start_time may be missing if psutil + /proc both unavailable, but the
    # identity-key fields host_id/pid must always be present.
    if "pid_start_time" in fp:
        assert fp["pid_start_time"] > 0


def test_capture_process_fingerprint_hashes_anchor_path():
    from unitares_sdk.utils import capture_process_fingerprint

    fp = capture_process_fingerprint(anchor_path="/etc/unitares/anchor.json")
    assert "anchor_path_hash" in fp
    assert len(fp["anchor_path_hash"]) == 16  # truncated sha256


# -----------------------------------------------------------------------------
# record_binding_bg — DB side with mocked pool
# -----------------------------------------------------------------------------


def _make_mock_db(live_rows, allow_concurrent=False):
    """Build a mock async DB backend that exposes .acquire() -> conn."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=live_rows)
    conn.fetchrow = AsyncMock(
        return_value={"allow_concurrent": allow_concurrent}
    )

    # Async context manager returned by acquire()
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = False

    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)
    return db, conn


def _row(host="h1", pid=100, start=1.0, transport="http", tty=None, ppid=None):
    from datetime import datetime, timezone
    return {
        "host_id": host,
        "pid": pid,
        "pid_start_time": start,
        "transport": transport,
        "tty": tty,
        "ppid": ppid,
        "last_seen": datetime.now(timezone.utc),
    }


@pytest.fixture
def fp():
    return ProcessFingerprint(
        host_id="h1",
        pid=100,
        pid_start_time=1.0,
        transport="http",
    )


@pytest.mark.asyncio
async def test_record_binding_single_live_no_event(fp):
    """One live binding → no collision → no audit event."""
    db, conn = _make_mock_db(live_rows=[_row()])
    emit = MagicMock()
    with patch("src.db.get_db", return_value=db), \
         patch.object(process_binding, "_emit_concurrent_binding_event", emit):
        await process_binding.record_binding_bg("agent-1", fp)
    conn.execute.assert_awaited()
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_record_binding_two_live_distinct_contexts_emits_event(fp):
    """Two live bindings with distinct tuples + policy=false → audit event fires."""
    rows = [
        _row(host="h1", pid=100, transport="http"),
        _row(host="h1", pid=200, transport="stdio"),
    ]
    db, conn = _make_mock_db(live_rows=rows, allow_concurrent=False)
    emit = MagicMock()
    with patch("src.db.get_db", return_value=db), \
         patch.object(process_binding, "_emit_concurrent_binding_event", emit):
        await process_binding.record_binding_bg("agent-1", fp)
    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[0] == "agent-1"
    assert len(args[1]) == 2


@pytest.mark.asyncio
async def test_record_binding_allow_concurrent_suppresses_event(fp):
    """Two live bindings but allow_concurrent_contexts=true → no event."""
    rows = [
        _row(host="h1", pid=100, transport="http"),
        _row(host="h1", pid=200, transport="stdio"),
    ]
    db, _ = _make_mock_db(live_rows=rows, allow_concurrent=True)
    emit = MagicMock()
    with patch("src.db.get_db", return_value=db), \
         patch.object(process_binding, "_emit_concurrent_binding_event", emit):
        await process_binding.record_binding_bg("agent-1", fp)
    emit.assert_not_called()


@pytest.mark.asyncio
async def test_record_binding_swallows_db_errors(fp):
    """DB failure in record_binding_bg is non-fatal — onboard must not break."""
    db = MagicMock()
    db.acquire = MagicMock(side_effect=RuntimeError("pool exhausted"))
    with patch("src.db.get_db", return_value=db):
        # Should not raise.
        await process_binding.record_binding_bg("agent-1", fp)


@pytest.mark.asyncio
async def test_sweep_stale_bindings_returns_row_count():
    """Sweeper parses asyncpg's 'UPDATE N' status string."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 42")
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__.return_value = conn
    acquire_cm.__aexit__.return_value = False
    db = MagicMock()
    db.acquire = MagicMock(return_value=acquire_cm)
    with patch("src.db.get_db", return_value=db):
        count = await process_binding.sweep_stale_bindings()
    assert count == 42


@pytest.mark.asyncio
async def test_sweep_stale_bindings_swallows_errors():
    """Sweeper failure must not propagate — next tick retries."""
    db = MagicMock()
    db.acquire = MagicMock(side_effect=RuntimeError("boom"))
    with patch("src.db.get_db", return_value=db):
        count = await process_binding.sweep_stale_bindings()
    assert count == 0


@pytest.mark.asyncio
async def test_record_binding_pid_reuse_disambiguated_by_start_time(fp):
    """Same host+pid with different pid_start_time = different contexts.

    This is the PID-reuse case: a prior process exited, a new process got the
    same PID from the kernel, and both claim the same UUID. pid_start_time
    distinguishes them, so two rows exist and the event fires.
    """
    rows = [
        _row(host="h1", pid=100, start=1.0, transport="http"),
        _row(host="h1", pid=100, start=99999.0, transport="http"),
    ]
    db, _ = _make_mock_db(live_rows=rows, allow_concurrent=False)
    emit = MagicMock()
    with patch("src.db.get_db", return_value=db), \
         patch.object(process_binding, "_emit_concurrent_binding_event", emit):
        await process_binding.record_binding_bg("agent-1", fp)
    emit.assert_called_once()


# -----------------------------------------------------------------------------
# get_live_bindings + list_process_bindings MCP tool
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_live_bindings_returns_serialized_rows():
    """Helper returns dict-per-row with ISO-formatted timestamps."""
    from datetime import datetime, timezone

    ts = datetime(2026, 4, 24, 1, 2, 3, tzinfo=timezone.utc)
    row = {
        "host_id": "h1", "pid": 100, "pid_start_time": 1.0,
        "transport": "http", "tty": "/dev/ttys0", "ppid": 1,
        "anchor_path_hash": None, "client_session_id": None,
        "onboard_ts": ts, "last_seen": ts,
        "same_host_ppid_consistent": None,
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
    assert len(bindings) == 1
    assert bindings[0]["host_id"] == "h1"
    assert bindings[0]["last_seen"] == "2026-04-24T01:02:03+00:00"


@pytest.mark.asyncio
async def test_get_live_bindings_returns_empty_on_db_failure():
    db = MagicMock()
    db.acquire = MagicMock(side_effect=RuntimeError("nope"))
    with patch("src.db.get_db", return_value=db):
        result = await process_binding.get_live_bindings("agent-1")
    assert result == []


@pytest.mark.asyncio
async def test_list_process_bindings_requires_agent():
    """Tool errors when neither agent_uuid nor a bound session is present."""
    from src.mcp_handlers.identity import process_binding_handler

    with patch.object(
        process_binding_handler, "get_bound_agent_id", return_value=None
    ):
        result = await process_binding_handler.handle_list_process_bindings({})
    # error_response returns a Sequence[TextContent]; just confirm it is non-empty.
    assert result
    text = result[0].text
    assert "agent_uuid" in text.lower() or "bound session" in text.lower()


@pytest.mark.asyncio
async def test_list_process_bindings_flags_concurrent_collision():
    """Tool sets concurrent_binding_detected=true when ≥2 distinct contexts."""
    from src.mcp_handlers.identity import process_binding_handler

    bindings = [
        {"host_id": "h1", "pid": 100, "pid_start_time": 1.0, "transport": "http",
         "tty": None, "ppid": None, "anchor_path_hash": None,
         "client_session_id": None, "onboard_ts": None, "last_seen": None},
        {"host_id": "h1", "pid": 200, "pid_start_time": 2.0, "transport": "stdio",
         "tty": None, "ppid": None, "anchor_path_hash": None,
         "client_session_id": None, "onboard_ts": None, "last_seen": None},
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
    assert payload["live_binding_count"] == 2
    assert payload["concurrent_binding_detected"] is True
    assert "note" in payload


@pytest.mark.asyncio
async def test_list_process_bindings_single_binding_not_flagged():
    """One live binding → concurrent_binding_detected=false, no note."""
    from src.mcp_handlers.identity import process_binding_handler

    bindings = [
        {"host_id": "h1", "pid": 100, "pid_start_time": 1.0, "transport": "http",
         "tty": None, "ppid": None, "anchor_path_hash": None,
         "client_session_id": None, "onboard_ts": None, "last_seen": None},
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
    assert payload["live_binding_count"] == 1
    assert payload["concurrent_binding_detected"] is False
    assert "note" not in payload
