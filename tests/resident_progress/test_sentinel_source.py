from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.resident_progress.sentinel_source import SentinelPulseSource
from src.mcp_handlers.schemas.progress_flat import RecordProgressPulseParams
from src.mcp_handlers.resident_progress import handle_record_progress_pulse


# ---------------------------------------------------------------------------
# SentinelPulseSource — DB integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pulse_source_returns_latest_value_in_window(test_db):
    uuid = "55555555-0000-0000-0000-000000000005"
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO resident_progress_pulse "
            "(resident_uuid, metric_name, value, recorded_at) "
            "VALUES ($1, 'evaluated', 7, now() - interval '5 minutes'), "
            "       ($1, 'evaluated', 12, now() - interval '1 minute')",
            uuid,
        )
    src = SentinelPulseSource(test_db)
    out = await src.fetch([uuid], timedelta(minutes=30))
    assert out[uuid] == 12  # latest, not sum


@pytest.mark.asyncio
async def test_pulse_source_returns_zero_when_no_rows_in_window(test_db):
    src = SentinelPulseSource(test_db)
    out = await src.fetch(["66666666-0000-0000-0000-000000000006"], timedelta(minutes=30))
    assert out["66666666-0000-0000-0000-000000000006"] == 0


@pytest.mark.asyncio
async def test_pulse_source_excludes_rows_outside_window(test_db):
    uuid = "77777777-0000-0000-0000-000000000007"
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO resident_progress_pulse "
            "(resident_uuid, metric_name, value, recorded_at) "
            "VALUES ($1, 'evaluated', 99, now() - interval '2 hours')",
            uuid,
        )
    src = SentinelPulseSource(test_db)
    out = await src.fetch([uuid], timedelta(minutes=30))
    assert out[uuid] == 0  # row is outside 30-minute window


@pytest.mark.asyncio
async def test_pulse_source_empty_input_returns_empty_dict_no_query(test_db):
    """Empty resident_uuids must return {} without hitting the DB."""
    src = SentinelPulseSource(test_db)
    out = await src.fetch([], timedelta(minutes=30))
    assert out == {}


# ---------------------------------------------------------------------------
# RecordProgressPulseParams — schema unit tests
# ---------------------------------------------------------------------------

def test_schema_accepts_valid_params():
    p = RecordProgressPulseParams.model_validate(
        {"metric_name": "evaluated", "value": 5}
    )
    assert p.metric_name == "evaluated"
    assert p.value == 5
    assert p.resident_uuid is None


def test_schema_rejects_negative_value():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RecordProgressPulseParams.model_validate({"metric_name": "x", "value": -1})


def test_schema_rejects_empty_metric_name():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RecordProgressPulseParams.model_validate({"metric_name": "", "value": 0})


def test_schema_rejects_metric_name_with_space():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RecordProgressPulseParams.model_validate({"metric_name": "bad name", "value": 0})


def test_schema_accepts_dots_dashes_underscores():
    p = RecordProgressPulseParams.model_validate(
        {"metric_name": "a.b-c_d", "value": 0}
    )
    assert p.metric_name == "a.b-c_d"


def test_schema_accepts_optional_resident_uuid():
    p = RecordProgressPulseParams.model_validate(
        {"metric_name": "x", "value": 1, "resident_uuid": "aaaa-uuid"}
    )
    assert p.resident_uuid == "aaaa-uuid"


def test_schema_rejects_metric_name_over_128_chars():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RecordProgressPulseParams.model_validate(
            {"metric_name": "a" * 129, "value": 0}
        )


# ---------------------------------------------------------------------------
# handle_record_progress_pulse — auth binding tests
# ---------------------------------------------------------------------------

BOUND_UUID_A = "aaaaaaaa-0000-0000-0000-000000000001"
BOUND_UUID_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _make_mock_agent_meta(uuid: str):
    meta = MagicMock()
    meta.status = "active"
    return meta


def _make_mcp_server_mock(bound_uuid: str):
    server = MagicMock()
    server.agent_metadata = {bound_uuid: _make_mock_agent_meta(bound_uuid)}
    server.ensure_metadata_loaded = MagicMock()
    return server


@pytest.mark.asyncio
async def test_record_progress_pulse_inserts_row_for_bound_agent(test_db):
    """Bound agent posts pulse → row written with bound UUID."""
    inserted = []

    async def _fake_insert(query, *args, **kwargs):
        inserted.append(args)

    mock_conn = AsyncMock()
    mock_conn.execute = _fake_insert
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db = MagicMock()
    mock_db.acquire = MagicMock(return_value=mock_ctx)

    server_mock = _make_mcp_server_mock(BOUND_UUID_A)

    with patch("src.mcp_handlers.context.get_context_agent_id", return_value=BOUND_UUID_A), \
         patch("src.mcp_handlers.shared.get_mcp_server", return_value=server_mock), \
         patch("config.governance_config.identity_strict_mode", return_value="warn"), \
         patch("src.db.get_db", return_value=mock_db):
        result = await handle_record_progress_pulse({
            "metric_name": "evaluated",
            "value": 3,
        })

    import json
    payload = json.loads(result[0].text)
    assert payload.get("success") is True, f"Expected success but got: {payload}"
    assert len(inserted) == 1
    # args: (effective_uuid, metric_name, value)
    assert inserted[0][0] == BOUND_UUID_A
    assert inserted[0][1] == "evaluated"
    assert inserted[0][2] == 3


@pytest.mark.asyncio
async def test_record_progress_pulse_rejects_mismatched_resident_uuid(test_db):
    """Caller supplies resident_uuid != bound UUID → auth error, no row written."""
    inserted = []

    async def _fake_insert(query, *args, **kwargs):
        inserted.append(args)

    mock_conn = AsyncMock()
    mock_conn.execute = _fake_insert
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db = MagicMock()
    mock_db.acquire = MagicMock(return_value=mock_ctx)

    server_mock = _make_mcp_server_mock(BOUND_UUID_A)

    with patch("src.mcp_handlers.context.get_context_agent_id", return_value=BOUND_UUID_A), \
         patch("src.mcp_handlers.shared.get_mcp_server", return_value=server_mock), \
         patch("config.governance_config.identity_strict_mode", return_value="warn"), \
         patch("src.db.get_db", return_value=mock_db):
        result = await handle_record_progress_pulse({
            "metric_name": "evaluated",
            "value": 7,
            "resident_uuid": BOUND_UUID_B,  # mismatch!
        })

    import json
    payload = json.loads(result[0].text)
    assert payload.get("error") is not None or payload.get("success") is not True, (
        f"Expected auth error but got: {payload}"
    )
    # Verify error_code is AUTH_MISMATCH
    assert "AUTH_MISMATCH" in str(payload), f"Expected AUTH_MISMATCH in: {payload}"
    assert len(inserted) == 0, "No DB row should be written on auth mismatch"
