-- Migration 021: Seed epoch 3 in core.epochs
--
-- Epoch 3 was introduced 2026-04-27 (PRs #219 / #220) when the tactical
-- calibration truth channel was broadened (task_* outcome types added,
-- per-channel surface in API). The bump was applied to the live governance
-- DB via scripts/dev/bump_epoch.py, but the test DB (governance_test) and
-- any other fresh PG instance need a migration to seed the registry row —
-- otherwise tests/test_epoch_registry.py fails on baseline.
--
-- Pattern mirrors migration 014_seed_epoch_2.sql.

INSERT INTO core.epochs (epoch, started_at, reason, started_by)
VALUES (
    3,
    '2026-04-27 03:49:24.45921-06',
    'broadened tactical calibration truth channel — task_* added; per-channel surface in API',
    'manual'
)
ON CONFLICT (epoch) DO NOTHING;

INSERT INTO core.schema_migrations (version, name)
VALUES (21, 'seed_epoch_3')
ON CONFLICT (version) DO NOTHING;
