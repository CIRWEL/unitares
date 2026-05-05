"""R2 PR 5: process_agent_update lineage trigger tests.

Verifies that ``_r2_post_update_hook`` (called at the end of
``execute_post_update_effects``):

- Skips dispatch and increment when the agent has no lineage edge.
- Dispatches ``evaluate_lineage_for`` via ``create_tracked_task`` for
  any lineage edge (provisional or confirmed).
- Increments ``chain_obs_count`` only for confirmed lineage rows.
- Fails soft when the backend raises (does not propagate).

Tests target the helper directly so the full ``execute_post_update_effects``
fixture surface (monitors, baselines, CIRS, outcome events) does not need
to be assembled — that surface has its own integration coverage. The
helper is a single, well-bounded code path.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_ctx(agent_id: str) -> MagicMock:
    """Minimal stand-in for UpdateContext — only ``agent_id`` is read."""
    ctx = MagicMock()
    ctx.agent_id = agent_id
    return ctx


@pytest.mark.asyncio
async def test_r2_post_update_no_parent_skips_dispatch_and_increment():
    """Agent with no parent_agent_id → no dispatch, no increment."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-no-parent-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(
        return_value={"parent_agent_id": None}
    )
    backend_mock.increment_chain_obs_count = AsyncMock()

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        await _r2_post_update_hook(ctx)

    assert dispatched == []
    assert backend_mock.increment_chain_obs_count.await_count == 0


@pytest.mark.asyncio
async def test_r2_post_update_no_lineage_row_returns_silently():
    """read_lineage_state → None (no row) skips both effects, no error."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-no-row-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(return_value=None)
    backend_mock.increment_chain_obs_count = AsyncMock()

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        await _r2_post_update_hook(ctx)

    assert dispatched == []
    assert backend_mock.increment_chain_obs_count.await_count == 0


@pytest.mark.asyncio
async def test_r2_post_update_provisional_dispatches_no_increment():
    """Provisional lineage → dispatch FSM eval, no chain counter increment."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-prov-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(
        return_value={
            "parent_agent_id": "parent-x",
            "provisional_lineage": True,
            "confirmed_at": None,
        }
    )
    backend_mock.increment_chain_obs_count = AsyncMock()

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        await _r2_post_update_hook(ctx)

    assert any(
        n and n.startswith("r2_lineage_eval_") for n in dispatched
    ), f"expected r2_lineage_eval_* dispatch, got {dispatched!r}"
    assert backend_mock.increment_chain_obs_count.await_count == 0


@pytest.mark.asyncio
async def test_r2_post_update_confirmed_increments_and_dispatches():
    """Confirmed lineage → increment chain counter AND dispatch FSM eval."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-conf-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(
        return_value={
            "parent_agent_id": "parent-x",
            "provisional_lineage": False,
            "confirmed_at": "2026-05-04T00:00:00Z",
        }
    )
    backend_mock.increment_chain_obs_count = AsyncMock(return_value=42)

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        await _r2_post_update_hook(ctx)

    assert any(
        n and n.startswith("r2_lineage_eval_") for n in dispatched
    ), f"expected r2_lineage_eval_* dispatch, got {dispatched!r}"
    backend_mock.increment_chain_obs_count.assert_awaited_once_with(
        "agent-conf-12345678"
    )


@pytest.mark.asyncio
async def test_r2_post_update_failsoft_on_read_lineage_exception():
    """If read_lineage_state raises, hook returns silently — no propagation."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-fail-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(
        side_effect=RuntimeError("DB down")
    )
    backend_mock.increment_chain_obs_count = AsyncMock()

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        # Must NOT raise
        await _r2_post_update_hook(ctx)

    assert dispatched == []
    assert backend_mock.increment_chain_obs_count.await_count == 0


@pytest.mark.asyncio
async def test_r2_post_update_increment_failure_still_dispatches():
    """If increment_chain_obs_count raises, dispatch still proceeds."""
    from src.mcp_handlers.updates.phases import _r2_post_update_hook

    ctx = _make_ctx("agent-incfail-12345678")

    backend_mock = MagicMock()
    backend_mock.read_lineage_state = AsyncMock(
        return_value={
            "parent_agent_id": "parent-x",
            "provisional_lineage": False,
            "confirmed_at": "2026-05-04T00:00:00Z",
        }
    )
    backend_mock.increment_chain_obs_count = AsyncMock(
        side_effect=RuntimeError("counter UPDATE failed")
    )

    dispatched: list[str | None] = []

    def fake_track(coro, *, name=None):
        dispatched.append(name)
        coro.close()
        return MagicMock()

    with patch("src.db.get_db", return_value=backend_mock), patch(
        "src.background_tasks.create_tracked_task", side_effect=fake_track
    ):
        await _r2_post_update_hook(ctx)

    # Dispatch should still happen even though increment raised
    assert any(
        n and n.startswith("r2_lineage_eval_") for n in dispatched
    ), f"expected r2_lineage_eval_* dispatch, got {dispatched!r}"
