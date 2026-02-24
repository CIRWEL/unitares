-- Partition Management for audit.events and audit.tool_usage
-- Run after schema.sql
--
-- Partition strategy: Monthly, with 180-day retention for events, 90-day for tool_usage
--
-- Usage:
--   1. Run this file to create initial partitions
--   2. Schedule partition_maintenance() weekly via pg_cron or external cron

-- =============================================================================
-- PARTITION CREATION FUNCTIONS
-- =============================================================================

-- Create a monthly partition for audit.events
CREATE OR REPLACE FUNCTION audit.create_events_partition(
    p_year INTEGER,
    p_month INTEGER
)
RETURNS TEXT AS $$
DECLARE
    v_partition_name TEXT;
    v_start_date DATE;
    v_end_date DATE;
BEGIN
    v_partition_name := format('events_%s_%s', p_year, lpad(p_month::text, 2, '0'));
    v_start_date := make_date(p_year, p_month, 1);
    v_end_date := v_start_date + INTERVAL '1 month';

    -- Check if partition already exists
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'audit' AND c.relname = v_partition_name
    ) THEN
        RETURN format('Partition %s already exists', v_partition_name);
    END IF;

    -- Create partition
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS audit.%I PARTITION OF audit.events
         FOR VALUES FROM (%L) TO (%L)',
        v_partition_name,
        v_start_date,
        v_end_date
    );

    -- Create indexes on the partition
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_agent_ts ON audit.%I (agent_id, ts DESC)',
        v_partition_name, v_partition_name
    );
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_type_ts ON audit.%I (event_type, ts DESC)',
        v_partition_name, v_partition_name
    );
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_hash ON audit.%I (raw_hash) WHERE raw_hash IS NOT NULL',
        v_partition_name, v_partition_name
    );

    RETURN format('Created partition %s', v_partition_name);
END;
$$ LANGUAGE plpgsql;

-- Create a monthly partition for audit.tool_usage
CREATE OR REPLACE FUNCTION audit.create_tool_usage_partition(
    p_year INTEGER,
    p_month INTEGER
)
RETURNS TEXT AS $$
DECLARE
    v_partition_name TEXT;
    v_start_date DATE;
    v_end_date DATE;
BEGIN
    v_partition_name := format('tool_usage_%s_%s', p_year, lpad(p_month::text, 2, '0'));
    v_start_date := make_date(p_year, p_month, 1);
    v_end_date := v_start_date + INTERVAL '1 month';

    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'audit' AND c.relname = v_partition_name
    ) THEN
        RETURN format('Partition %s already exists', v_partition_name);
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS audit.%I PARTITION OF audit.tool_usage
         FOR VALUES FROM (%L) TO (%L)',
        v_partition_name,
        v_start_date,
        v_end_date
    );

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_agent_ts ON audit.%I (agent_id, ts DESC)',
        v_partition_name, v_partition_name
    );
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_tool_ts ON audit.%I (tool_name, ts DESC)',
        v_partition_name, v_partition_name
    );

    RETURN format('Created partition %s', v_partition_name);
END;
$$ LANGUAGE plpgsql;

-- Create a monthly partition for audit.outcome_events
CREATE OR REPLACE FUNCTION audit.create_outcome_partition(
    p_year INTEGER,
    p_month INTEGER
)
RETURNS TEXT AS $$
DECLARE
    v_partition_name TEXT;
    v_start_date DATE;
    v_end_date DATE;
BEGIN
    v_partition_name := format('outcome_events_%s_%s', p_year, lpad(p_month::text, 2, '0'));
    v_start_date := make_date(p_year, p_month, 1);
    v_end_date := v_start_date + INTERVAL '1 month';

    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'audit' AND c.relname = v_partition_name
    ) THEN
        RETURN format('Partition %s already exists', v_partition_name);
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS audit.%I PARTITION OF audit.outcome_events
         FOR VALUES FROM (%L) TO (%L)',
        v_partition_name,
        v_start_date,
        v_end_date
    );

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_agent_ts ON audit.%I (agent_id, ts DESC)',
        v_partition_name, v_partition_name
    );
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS idx_%s_type_ts ON audit.%I (outcome_type, ts DESC)',
        v_partition_name, v_partition_name
    );

    RETURN format('Created partition %s', v_partition_name);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- RETENTION / CLEANUP FUNCTIONS
-- =============================================================================

-- Drop old event partitions (older than retention_days)
CREATE OR REPLACE FUNCTION audit.drop_old_events_partitions(
    p_retention_days INTEGER DEFAULT 180
)
RETURNS TABLE(partition_name TEXT, action TEXT) AS $$
DECLARE
    v_cutoff DATE;
    v_rec RECORD;
BEGIN
    v_cutoff := current_date - (p_retention_days || ' days')::INTERVAL;

    FOR v_rec IN
        SELECT c.relname as partition_name,
               pg_get_expr(c.relpartbound, c.oid) as partition_bound
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE n.nspname = 'audit'
          AND parent.relname = 'events'
          AND c.relkind = 'r'
    LOOP
        -- Extract end date from partition bound (e.g., "FOR VALUES FROM ('2025-01-01') TO ('2025-02-01')")
        -- If end date < cutoff, drop it
        IF v_rec.partition_bound ~ 'TO \(''(\d{4}-\d{2}-\d{2})' THEN
            DECLARE
                v_end_date DATE;
            BEGIN
                v_end_date := (regexp_match(v_rec.partition_bound, 'TO \(''(\d{4}-\d{2}-\d{2})'))[1]::DATE;
                IF v_end_date < v_cutoff THEN
                    EXECUTE format('DROP TABLE IF EXISTS audit.%I', v_rec.partition_name);
                    partition_name := v_rec.partition_name;
                    action := 'dropped';
                    RETURN NEXT;
                END IF;
            END;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Drop old tool_usage partitions (older than retention_days)
CREATE OR REPLACE FUNCTION audit.drop_old_tool_usage_partitions(
    p_retention_days INTEGER DEFAULT 90
)
RETURNS TABLE(partition_name TEXT, action TEXT) AS $$
DECLARE
    v_cutoff DATE;
    v_rec RECORD;
BEGIN
    v_cutoff := current_date - (p_retention_days || ' days')::INTERVAL;

    FOR v_rec IN
        SELECT c.relname as partition_name,
               pg_get_expr(c.relpartbound, c.oid) as partition_bound
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE n.nspname = 'audit'
          AND parent.relname = 'tool_usage'
          AND c.relkind = 'r'
    LOOP
        IF v_rec.partition_bound ~ 'TO \(''(\d{4}-\d{2}-\d{2})' THEN
            DECLARE
                v_end_date DATE;
            BEGIN
                v_end_date := (regexp_match(v_rec.partition_bound, 'TO \(''(\d{4}-\d{2}-\d{2})'))[1]::DATE;
                IF v_end_date < v_cutoff THEN
                    EXECUTE format('DROP TABLE IF EXISTS audit.%I', v_rec.partition_name);
                    partition_name := v_rec.partition_name;
                    action := 'dropped';
                    RETURN NEXT;
                END IF;
            END;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Drop old outcome_events partitions (older than retention_days)
CREATE OR REPLACE FUNCTION audit.drop_old_outcome_partitions(
    p_retention_days INTEGER DEFAULT 365
)
RETURNS TABLE(partition_name TEXT, action TEXT) AS $$
DECLARE
    v_cutoff DATE;
    v_rec RECORD;
BEGIN
    v_cutoff := current_date - (p_retention_days || ' days')::INTERVAL;

    FOR v_rec IN
        SELECT c.relname as partition_name,
               pg_get_expr(c.relpartbound, c.oid) as partition_bound
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits i ON i.inhrelid = c.oid
        JOIN pg_class parent ON parent.oid = i.inhparent
        WHERE n.nspname = 'audit'
          AND parent.relname = 'outcome_events'
          AND c.relkind = 'r'
    LOOP
        IF v_rec.partition_bound ~ 'TO \(''(\d{4}-\d{2}-\d{2})' THEN
            DECLARE
                v_end_date DATE;
            BEGIN
                v_end_date := (regexp_match(v_rec.partition_bound, 'TO \(''(\d{4}-\d{2}-\d{2})'))[1]::DATE;
                IF v_end_date < v_cutoff THEN
                    EXECUTE format('DROP TABLE IF EXISTS audit.%I', v_rec.partition_name);
                    partition_name := v_rec.partition_name;
                    action := 'dropped';
                    RETURN NEXT;
                END IF;
            END;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- MAINTENANCE FUNCTION (call weekly)
-- =============================================================================

CREATE OR REPLACE FUNCTION audit.partition_maintenance()
RETURNS JSONB AS $$
DECLARE
    v_result JSONB := '{}'::jsonb;
    v_current_year INTEGER;
    v_current_month INTEGER;
    v_next_year INTEGER;
    v_next_month INTEGER;
    v_msg TEXT;
BEGIN
    -- Get current and next month
    v_current_year := EXTRACT(YEAR FROM current_date)::INTEGER;
    v_current_month := EXTRACT(MONTH FROM current_date)::INTEGER;

    IF v_current_month = 12 THEN
        v_next_year := v_current_year + 1;
        v_next_month := 1;
    ELSE
        v_next_year := v_current_year;
        v_next_month := v_current_month + 1;
    END IF;

    -- Ensure current month partitions exist
    v_msg := audit.create_events_partition(v_current_year, v_current_month);
    v_result := v_result || jsonb_build_object('events_current', v_msg);

    v_msg := audit.create_tool_usage_partition(v_current_year, v_current_month);
    v_result := v_result || jsonb_build_object('tool_usage_current', v_msg);

    v_msg := audit.create_outcome_partition(v_current_year, v_current_month);
    v_result := v_result || jsonb_build_object('outcome_events_current', v_msg);

    -- Create next month partitions (look-ahead)
    v_msg := audit.create_events_partition(v_next_year, v_next_month);
    v_result := v_result || jsonb_build_object('events_next', v_msg);

    v_msg := audit.create_tool_usage_partition(v_next_year, v_next_month);
    v_result := v_result || jsonb_build_object('tool_usage_next', v_msg);

    v_msg := audit.create_outcome_partition(v_next_year, v_next_month);
    v_result := v_result || jsonb_build_object('outcome_events_next', v_msg);

    -- Clean up old partitions
    v_result := v_result || jsonb_build_object(
        'events_dropped',
        (SELECT jsonb_agg(partition_name) FROM audit.drop_old_events_partitions(180))
    );
    v_result := v_result || jsonb_build_object(
        'tool_usage_dropped',
        (SELECT jsonb_agg(partition_name) FROM audit.drop_old_tool_usage_partitions(90))
    );
    v_result := v_result || jsonb_build_object(
        'outcome_events_dropped',
        (SELECT jsonb_agg(partition_name) FROM audit.drop_old_outcome_partitions(365))
    );

    -- Clean up expired sessions
    v_result := v_result || jsonb_build_object(
        'sessions_cleaned',
        core.cleanup_expired_sessions()
    );

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- INITIAL PARTITION CREATION
-- Create partitions for current month and next 2 months
-- =============================================================================

DO $$
DECLARE
    v_year INTEGER;
    v_month INTEGER;
    v_i INTEGER;
BEGIN
    FOR v_i IN 0..2 LOOP
        v_year := EXTRACT(YEAR FROM current_date + (v_i || ' month')::INTERVAL)::INTEGER;
        v_month := EXTRACT(MONTH FROM current_date + (v_i || ' month')::INTERVAL)::INTEGER;

        PERFORM audit.create_events_partition(v_year, v_month);
        PERFORM audit.create_tool_usage_partition(v_year, v_month);
        PERFORM audit.create_outcome_partition(v_year, v_month);
    END LOOP;
END $$;

-- =============================================================================
-- OPTIONAL: pg_cron SCHEDULING
-- Uncomment if pg_cron is installed
-- =============================================================================

-- SELECT cron.schedule(
--     'partition-maintenance',
--     '0 3 * * 0',  -- Every Sunday at 3 AM
--     'SELECT audit.partition_maintenance()'
-- );

-- =============================================================================
-- UTILITY VIEWS
-- =============================================================================

-- List all partitions with row counts and sizes
CREATE OR REPLACE VIEW audit.v_partition_stats AS
SELECT
    n.nspname as schema_name,
    parent.relname as parent_table,
    c.relname as partition_name,
    pg_get_expr(c.relpartbound, c.oid) as partition_bounds,
    pg_size_pretty(pg_relation_size(c.oid)) as size,
    (SELECT count(*) FROM pg_class WHERE oid = c.oid) as approx_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_inherits i ON i.inhrelid = c.oid
JOIN pg_class parent ON parent.oid = i.inhparent
WHERE n.nspname = 'audit'
  AND c.relkind = 'r'
ORDER BY parent.relname, c.relname;

COMMENT ON VIEW audit.v_partition_stats IS 'Shows all audit partitions with sizes and bounds';
