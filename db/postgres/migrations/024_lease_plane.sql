-- 024_lease_plane.sql
--
-- Surface Lease Plane v0 contract anchor.
--
-- Creates the Postgres durable mirror for the Elixir/OTP lease plane. The
-- invariant is intentionally narrow: BEAM may own live coordination, but this
-- schema is only lease/outbox state. It does not become an identity, EISV, KG,
-- or calibration source of truth.

CREATE SCHEMA IF NOT EXISTS lease_plane;

CREATE TABLE IF NOT EXISTS lease_plane.surface_leases (
    lease_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    surface_id         text NOT NULL,
    surface_kind       text NOT NULL,
    holder_agent_uuid  uuid NOT NULL,
    holder_class       text NOT NULL,
    holder_kind        text NOT NULL,
    holder_pid         text,
    heartbeat_required boolean NOT NULL,
    intent             text,
    acquired_at        timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL,
    last_heartbeat_at  timestamptz,
    released_at        timestamptz,
    release_reason     text,
    audit_session      text,
    original_ttl_s     int NOT NULL,
    CHECK (
        (heartbeat_required = true  AND holder_kind = 'remote_heartbeat') OR
        (heartbeat_required = false AND holder_kind = 'local_beam')
    ),
    CHECK (holder_class IN ('process_instance', 'substrate_earned')),
    CHECK (holder_kind IN ('local_beam', 'remote_heartbeat')),
    CHECK (original_ttl_s > 0 AND original_ttl_s <= 3600),
    CHECK (
        release_reason IS NULL OR release_reason IN (
            'normal',
            'down_local',
            'reaped_after_supervisor_failed',
            'reaped_local_ttl',
            'reaped_remote_ttl',
            'handoff',
            'forced'
        )
    )
);

CREATE OR REPLACE FUNCTION lease_plane.enforce_immutable_lease_fields()
RETURNS trigger AS $$
BEGIN
    IF NEW.holder_kind IS DISTINCT FROM OLD.holder_kind THEN
        RAISE EXCEPTION 'holder_kind is immutable per lease_id; release+reacquire to change';
    END IF;
    IF NEW.holder_class IS DISTINCT FROM OLD.holder_class THEN
        RAISE EXCEPTION 'holder_class is immutable per lease_id';
    END IF;
    IF NEW.original_ttl_s IS DISTINCT FROM OLD.original_ttl_s THEN
        RAISE EXCEPTION 'original_ttl_s is immutable per lease_id; renew uses this fixed value';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS surface_leases_immutable_fields ON lease_plane.surface_leases;
CREATE TRIGGER surface_leases_immutable_fields
    BEFORE UPDATE ON lease_plane.surface_leases
    FOR EACH ROW
    EXECUTE FUNCTION lease_plane.enforce_immutable_lease_fields();

CREATE UNIQUE INDEX IF NOT EXISTS surface_leases_active_unique
    ON lease_plane.surface_leases (surface_id)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS surface_leases_holder
    ON lease_plane.surface_leases (holder_agent_uuid)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS surface_leases_active_expiry
    ON lease_plane.surface_leases (expires_at)
    WHERE released_at IS NULL;

CREATE TABLE IF NOT EXISTS lease_plane.lease_plane_events (
    event_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts               timestamptz NOT NULL DEFAULT now(),
    event_type       text NOT NULL,
    lease_id         uuid,
    surface_id       text NOT NULL,
    surface_kind     text NOT NULL,
    holder_agent_uuid uuid,
    holder_class     text,
    advisory_mode    boolean NOT NULL,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    forwarded_at     timestamptz,
    forward_attempts int NOT NULL DEFAULT 0,
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
            'service_unavailable'
        )
    )
);

CREATE INDEX IF NOT EXISTS lease_plane_events_unforwarded
    ON lease_plane.lease_plane_events (ts)
    WHERE forwarded_at IS NULL;

CREATE INDEX IF NOT EXISTS lease_plane_events_surface_ts
    ON lease_plane.lease_plane_events (surface_kind, surface_id, ts);

INSERT INTO core.schema_migrations (version, name, applied_at)
VALUES (24, 'lease_plane', NOW())
ON CONFLICT (version) DO NOTHING;
