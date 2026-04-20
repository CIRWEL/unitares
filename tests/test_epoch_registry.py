"""
Ensures GovernanceConfig.CURRENT_EPOCH is registered in core.epochs.

Regression guard for v2.9.0 (commit cbaaed95), where CURRENT_EPOCH was bumped
in config but scripts/dev/bump_epoch.py wasn't run, so the core.epochs INSERT
never happened. Data tables had epoch=2 rows for 3 weeks before anyone
noticed the registry gap.

Any future epoch bump must either (a) run bump_epoch.py, or (b) add a
migration that seeds the new epoch row — otherwise this test fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import asyncpg  # noqa: F401
except ImportError:
    pytest.skip("asyncpg not installed", allow_module_level=True)

from tests.test_db_utils import (
    TEST_DB_URL,
    can_connect_to_test_db,
    ensure_test_database_schema,
)

if not can_connect_to_test_db():
    pytest.skip("governance_test database not available", allow_module_level=True)


@pytest.mark.asyncio
async def test_current_epoch_has_registry_row():
    from config.governance_config import GovernanceConfig

    await ensure_test_database_schema()

    conn = await asyncpg.connect(TEST_DB_URL)
    try:
        max_epoch = await conn.fetchval("SELECT MAX(epoch) FROM core.epochs")
    finally:
        await conn.close()

    current = GovernanceConfig.CURRENT_EPOCH
    assert max_epoch is not None, "core.epochs is empty — migrations not applied?"
    assert max_epoch >= current, (
        f"GovernanceConfig.CURRENT_EPOCH={current} is not registered in core.epochs "
        f"(MAX(epoch)={max_epoch}). If you bumped CURRENT_EPOCH, either run "
        f"scripts/dev/bump_epoch.py or add a migration that INSERTs the new epoch row."
    )


@pytest.mark.asyncio
async def test_all_data_epochs_are_registered():
    """Every epoch value used on data rows must appear in core.epochs."""

    await ensure_test_database_schema()

    conn = await asyncpg.connect(TEST_DB_URL)
    try:
        orphans = await conn.fetch(
            """
            SELECT DISTINCT s.epoch
            FROM core.agent_state s
            LEFT JOIN core.epochs e ON e.epoch = s.epoch
            WHERE e.epoch IS NULL
            """
        )
    finally:
        await conn.close()

    assert not orphans, (
        f"agent_state has rows with epoch values not in core.epochs: "
        f"{[r['epoch'] for r in orphans]}"
    )
