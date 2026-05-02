-- 030_lease_plane_aborted_event.sql
--
-- Extends lease_plane.lease_plane_events.event_type CHECK constraint to include
-- 'lease.deprecation_aborted' — emitted by the new deprecate-and-finalize
-- super-command (R1, RFC §7.11.2 atomicity rewrite) when Phase 3 fails after
-- Phase 2 succeeded. Without an aborted event class, an operator who fails
-- Phase 3 multiple times has no audit trail of the abandonment (architect
-- council finding, deferred-from-PR-7 latent gap closed here).
--
-- Idempotent: detects prior application by checking whether the existing
-- CHECK already permits 'lease.deprecation_aborted', and skips the
-- DROP+ADD when so.

DO $$
DECLARE
    migration_already_recorded bool;
    aborted_already_permitted bool;
BEGIN
    -- Council CONCERN 2 (reviewer): primary guard via core.schema_migrations
    -- so the constraint-text probe (secondary) doesn't risk a double-CHECK if
    -- the constraint were ever renamed and the migration re-ran.
    SELECT EXISTS (
        SELECT 1 FROM core.schema_migrations WHERE version = 30
    ) INTO migration_already_recorded;

    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'lease_plane.lease_plane_events'::regclass
          AND conname = 'lease_plane_events_event_type_check'
          AND pg_get_constraintdef(oid) LIKE '%lease.deprecation_aborted%'
    ) INTO aborted_already_permitted;

    IF migration_already_recorded OR aborted_already_permitted THEN
        RAISE NOTICE 'migration 030: already applied (recorded=% / permitted=%); skipping',
            migration_already_recorded, aborted_already_permitted;
    ELSE
        ALTER TABLE lease_plane.lease_plane_events
            DROP CONSTRAINT IF EXISTS lease_plane_events_event_type_check;
        ALTER TABLE lease_plane.lease_plane_events
            ADD CONSTRAINT lease_plane_events_event_type_check
            CHECK (
                event_type IN (
                    'acquire',
                    'renew',
                    'release',
                    'heartbeat',
                    'handoff_offer',
                    'handoff_accept',
                    'conflict_held_by_other',
                    'reaped_remote_ttl',
                    'reaped_local_ttl',
                    'down_local',
                    'forced',
                    'service_unavailable',
                    'lease.deprecation_marked',
                    'lease.deprecation_swept',
                    'lease.deprecation_migrated',
                    'lease.deprecation_aborted'
                )
            );
        RAISE NOTICE 'migration 030: event_type CHECK extended with lease.deprecation_aborted';
    END IF;
END $$;

INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (30, 'lease_plane_aborted_event', NOW())
ON CONFLICT (version) DO NOTHING;
