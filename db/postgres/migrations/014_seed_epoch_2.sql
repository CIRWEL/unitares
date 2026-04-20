-- Migration 014: Seed epoch 2 in core.epochs
--
-- Epoch 2 was introduced in v2.9.0 (commit cbaaed95, 2026-03-29) when
-- behavioral EISV replaced ODE dynamics. That release bumped
-- GovernanceConfig.CURRENT_EPOCH directly instead of running
-- scripts/dev/bump_epoch.py, so the corresponding core.epochs INSERT
-- was never executed. Data tables (core.agent_state, core.agent_baselines)
-- have epoch=2 rows but core.epochs had no matching registry entry.
--
-- This migration restores the invariant: every value in agent_state.epoch
-- must appear in core.epochs. A pytest (tests/test_epoch_registry.py)
-- enforces this going forward by asserting MAX(core.epochs.epoch)
-- equals GovernanceConfig.CURRENT_EPOCH.

INSERT INTO core.epochs (epoch, started_at, reason, started_by)
VALUES (
    2,
    '2026-03-29 13:54:24-06',
    'behavioral EISV replaces ODE dynamics — old state data incompatible (v2.9.0 / commit cbaaed95)',
    'backfill'
)
ON CONFLICT (epoch) DO NOTHING;

INSERT INTO core.schema_migrations (version, name)
VALUES (14, 'seed_epoch_2')
ON CONFLICT (version) DO NOTHING;
