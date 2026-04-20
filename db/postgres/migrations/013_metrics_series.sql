-- 013_metrics_series.sql
--
-- Introduce a minimal time-series store for catalog-defined fleet metrics
-- (LOC, test counts, KG discovery totals, agent fleet snapshots, etc.).
--
-- Design notes:
-- * One table, dotted metric names (`tokei.unitares.src.code`) instead of
--   JSONB labels — Postgres indexes the TEXT name cheaply and we have no
--   ad-hoc label-filter use case yet. Labels can be added as a follow-up
--   migration if a concrete need surfaces.
-- * Writes are constrained at the application layer by a catalog allowlist
--   (`src/metrics/catalog.py`) so a leaked bearer token cannot pollute
--   history with arbitrary names.
-- * Primary query is "name X over last N days"; the (name, ts DESC) index
--   handles that without needing a composite over labels.

CREATE SCHEMA IF NOT EXISTS metrics;

CREATE TABLE IF NOT EXISTS metrics.series (
    ts    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    name  TEXT             NOT NULL,
    value DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_series_name_ts
    ON metrics.series (name, ts DESC);

INSERT INTO core.schema_migrations (version, name)
VALUES (13, 'metrics time-series substrate')
ON CONFLICT (version) DO NOTHING;
