"""Tests for the onboard-side seed_genesis_from_parent background wrapper.

The primitive itself is covered by test_seed_genesis_from_parent.py.
This file covers the fire-and-forget helper in mcp_handlers.identity.handlers
that the onboard flow schedules alongside the SPAWNED edge task.
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestSeedGenesisBgTask:
    @pytest.mark.asyncio
    async def test_seeded_path_calls_primitive(self):
        """Happy path: bg wrapper calls the primitive with (child, parent)."""
        mock_primitive = AsyncMock(return_value={
            "seeded": True,
            "reason": "seeded from parent trajectory_current",
            "parent_agent_id": "parent-uuid",
            "source": "parent_lineage",
        })
        with patch(
            "src.trajectory_identity.seed_genesis_from_parent",
            mock_primitive,
        ):
            from src.mcp_handlers.identity.handlers import (
                _seed_genesis_from_parent_bg,
            )
            await _seed_genesis_from_parent_bg("child-uuid", "parent-uuid")

        mock_primitive.assert_awaited_once_with("child-uuid", "parent-uuid")

    @pytest.mark.asyncio
    async def test_no_op_path_does_not_raise(self):
        """Primitive returning seeded=False (e.g. parent has no trajectory)
        must not propagate as error — onboard path continues."""
        mock_primitive = AsyncMock(return_value={
            "seeded": False,
            "reason": "parent has no trajectory_current to seed from",
            "parent_agent_id": "parent-uuid",
            "source": None,
        })
        with patch(
            "src.trajectory_identity.seed_genesis_from_parent",
            mock_primitive,
        ):
            from src.mcp_handlers.identity.handlers import (
                _seed_genesis_from_parent_bg,
            )
            await _seed_genesis_from_parent_bg("child-uuid", "parent-uuid")

        mock_primitive.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_primitive_exception_is_swallowed(self):
        """Primitive raising (e.g. DB down) must be non-fatal — onboard path
        already committed the identity; seeding is best-effort."""
        mock_primitive = AsyncMock(side_effect=RuntimeError("db unavailable"))
        with patch(
            "src.trajectory_identity.seed_genesis_from_parent",
            mock_primitive,
        ):
            from src.mcp_handlers.identity.handlers import (
                _seed_genesis_from_parent_bg,
            )
            # Must not raise
            await _seed_genesis_from_parent_bg("child-uuid", "parent-uuid")
