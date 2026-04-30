# BEAM Coordination Kernel Plan

**Created:** April 30, 2026  
**Last Updated:** April 30, 2026  
**Status:** Draft

---

## Purpose

This document scopes the "BEAM thing": a small OTP/Elixir coordination plane beside UNITARES, not a rewrite of UNITARES, Hermes, Lumen, or TouchDesigner.

The forcing function is concrete: our recurring failures are null/absence ambiguity, stale locks, race conditions, async task leaks, parallel-agent collision, stale-present confusion, and class-basin mismatch. These are not only code-quality failures. They are failures to represent live ownership of time-varying surfaces.

Core question:

> Who owns what surface, in which temporal basin, under what proof of life, until when, and how is it handed off?

## Non-goals

- Do not rewrite UNITARES in Elixir.
- Do not replace Hermes as the agent harness.
- Do not replace Lumen/anima as the embodied creature loop.
- Do not replace TouchDesigner as the expressive visual body.
- Do not create a broad agent chat/message board.
- Do not use KG as a transient coordination bus.
- Do not start with distributed BEAM clustering.
- Do not put secrets, continuity tokens, or opaque credentials in coordination events.

## Why BEAM / OTP fits

OTP operationalizes aliveness:

- every live coordinator is a process with a mailbox;
- state has an owner;
- death is observable through links/monitors;
- restart policy is explicit;
- supervision trees encode failure domains;
- GenServer serialization prevents shared-memory races inside a surface owner;
- telemetry is native enough to become UNITARES evidence.

This aligns with the real problem class better than ad hoc Python `asyncio` tasks and lock rows with unclear death semantics.

## Architecture posture

Use OTP for hot coordination and Postgres/UNITARES for durable truth.

```text
Hermes / Claude / Codex / Lumen / TouchDesigner
        │
        ▼
BEAM Coordination Kernel
  ├─ SurfaceRegistry
  ├─ LeaseServer
  ├─ HandoffServer
  ├─ BasinRouter
  ├─ EpisodeSupervisor
  ├─ BridgeSupervisor
  └─ TelemetryForwarder
        │
        ▼
UNITARES governance + Postgres
  ├─ durable lease/handoff audit rows
  ├─ process_agent_update / outcome_event evidence
  └─ KG only for promoted durable lessons
```

## Initial wedge: surface leases, not agent chat

Start with a narrow primitive that generalizes the existing coordination-lease dialectic conclusion:

> PostgreSQL-backed TTL surface leases, supervised by a local OTP service.

A surface is any shared mutation target:

- repo file path;
- repo branch;
- TouchDesigner network path;
- capture session;
- Lumen display/action surface;
- Discord thread/locus;
- cron job identity;
- MCP server config fragment.

V1 should support only two surface classes:

1. `repo_path` — whole-file single-writer leases.
2. `td_network` — TouchDesigner network mutation leases such as `/eisv_basin_v31`.

This keeps the first version testable without pretending to solve all multi-agent coordination.

## Core data model

### Lease

A lease is a live claim with explicit expiry and proof obligations.

Fields:

- `lease_id` — UUID.
- `surface_type` — enum: `repo_path`, `td_network` initially.
- `surface_id` — path-like identifier, for example `docs/ontology/plan.md` or `/eisv_basin_v31`.
- `holder_uuid` — UNITARES UUID of claimant, if known.
- `holder_label` — display label only, never identity proof.
- `episode_id` — current harness/session/thread locus if available.
- `harness` — `hermes`, `claude_code`, `codex`, `dispatch`, `lumen`, etc.
- `intent` — concise human-readable purpose.
- `evidence_ref` — validated reference proving why the lease was acquired; may be a task id, issue id, dialectic id, user request id, or local episode id.
- `acquired_at` — timestamp.
- `expires_at` — timestamp.
- `last_heartbeat_at` — timestamp.
- `status` — `active`, `released`, `expired`, `transferred`, `revoked`.
- `handoff_to` — optional holder target.
- `release_reason` — optional.

### Handoff

A handoff is not a chat message. It is a typed transfer proposal.

Fields:

- `handoff_id` — UUID.
- `lease_id` — lease being transferred.
- `from_holder_uuid`.
- `to_holder_uuid`.
- `state_snapshot_ref` — pointer to summary/artifact, not raw context dump.
- `known_hazards` — concise list.
- `freshness_horizon` — timestamp or TTL after which recipient must revalidate.
- `status` — `offered`, `accepted`, `rejected`, `expired`, `cancelled`.

### Typed absence

Do not return undifferentiated nulls. The API returns typed absence:

- `not_found`
- `not_yet_created`
- `pending`
- `expired`
- `revoked`
- `unreachable`
- `permission_denied`
- `stale`
- `conflicted`
- `tombstoned`
- `intentionally_absent`

This is the null-pointer cure: callers must handle what kind of absence occurred.

## OTP process shape

### `Coordination.Application`

Top-level supervision tree.

Children:

- `Coordination.Repo` — Postgres access.
- `Coordination.Telemetry` — event emission.
- `Coordination.SurfaceRegistry` — maps active surfaces to owner processes.
- `Coordination.LeaseSupervisor` — DynamicSupervisor for active lease processes.
- `Coordination.BridgeSupervisor` — external bridge processes.
- `CoordinationWeb.Endpoint` — HTTP API for non-BEAM clients.

### `Coordination.LeaseProcess`

One process per active lease.

Responsibilities:

- serialize lease renewal/release/handoff messages;
- maintain current live heartbeat deadline;
- monitor local BEAM holders when applicable;
- expire lease on TTL;
- write durable status changes;
- emit telemetry for UNITARES.

### `Coordination.SurfaceRegistry`

Registry for active surfaces.

Responsibilities:

- reject conflicting active leases;
- return existing lease status;
- spawn `LeaseProcess` through `LeaseSupervisor`;
- distinguish active local process from durable stale row.

### `Coordination.BasinRouter`

Small classifier that chooses coordination rule from surface/task class.

Initial modes:

- `single_writer` — repo path edits.
- `visual_surface_builder` — TouchDesigner network mutation.
- `calibration_capture` — screenshot/capture windows.
- `durable_memory` — KG/doc writes, no hot chat.

V1 can hardcode rules. Do not add ML classification.

## HTTP API v1

Expose a small JSON API first. MCP wrapper can come later.

### `POST /leases/acquire`

Request:

```json
{
  "surface_type": "repo_path",
  "surface_id": "docs/ontology/plan.md",
  "holder_uuid": "07d0f9c7-1512-4a1e-8cb1-a5225c20709f",
  "holder_label": "Mnemos",
  "episode_id": "hermes-cli-...",
  "harness": "hermes",
  "intent": "draft BEAM coordination kernel plan",
  "ttl_seconds": 900,
  "evidence_ref": "user-request:beam-coordination"
}
```

Responses:

- `201 acquired`
- `200 already_held_by_self`
- `409 conflicted` with current holder, expiry, and intent
- `422 invalid_evidence_ref`

### `POST /leases/:lease_id/renew`

Renews TTL if caller proves same holder/episode or valid handoff successor.

### `POST /leases/:lease_id/release`

Releases with `release_reason`.

### `GET /surfaces/:surface_type/:surface_id`

Returns active lease or typed absence.

### `POST /handoffs/offer`

Offers typed transfer.

### `POST /handoffs/:handoff_id/accept`

Accepts transfer and updates lease holder.

## Postgres schema sketch

```sql
CREATE TABLE coordination.surface_leases (
    lease_id UUID PRIMARY KEY,
    surface_type TEXT NOT NULL,
    surface_id TEXT NOT NULL,
    holder_uuid UUID,
    holder_label TEXT,
    episode_id TEXT,
    harness TEXT,
    intent TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    handoff_to UUID,
    release_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX surface_leases_one_active_surface
ON coordination.surface_leases (surface_type, surface_id)
WHERE status = 'active';
```

V1 can use application-level expiry checks plus a periodic reaper. Do not rely on partial index magic alone; expired rows must transition out of `active`.

## Telemetry to UNITARES

Emit structured events for:

- lease acquired;
- lease renewed;
- lease conflict;
- lease expired;
- lease released;
- handoff offered;
- handoff accepted;
- handoff rejected;
- stale surface read;
- typed absence returned;
- bridge unreachable;
- supervisor restart.

Forwarder behavior:

- ordinary events become `process_agent_update(... recent_tool_results=[...])` only when useful;
- completed lease lifecycle can emit `outcome_event(task_completed)`;
- only durable lessons become KG notes;
- no continuity tokens or secrets enter event payloads.

## Implementation sequence

### Phase 0 — repo and toolchain

1. Confirm Elixir/Mix availability.
2. If absent, install with Homebrew or asdf.
3. Create a separate repo or subdirectory only after deciding ownership:
   - preferred repo: `unitares-coordination-kernel` if it becomes a standalone service;
   - alternative: `services/coordination_kernel/` inside `unitares` if tightly coupled.
4. Add CI for `mix test` and formatting.

### Phase 1 — pure in-memory lease server

1. Generate Mix project.
2. Implement `LeaseProcess` and `SurfaceRegistry` without Postgres.
3. Add tests for acquire/release/conflict/expiry.
4. Add typed absence return values.
5. Expose HTTP endpoints.

Exit criterion: two concurrent requests for the same `surface_id` deterministically produce one acquired lease and one conflict.

### Phase 2 — Postgres durability

1. Add Ecto.
2. Add migration for `coordination.surface_leases`.
3. Persist lifecycle transitions.
4. Add expiry reaper.
5. Add tests around process crash/restart restoring active leases from DB.

Exit criterion: killing the BEAM process does not lose active lease knowledge; expired leases become expired, not corpse-locks.

### Phase 3 — Hermes/agent integration

1. Add a tiny Python client or direct HTTP helper.
2. Teach Hermes workflows to acquire a `repo_path` lease before editing known shared docs.
3. Add TouchDesigner builder lease around `/eisv_basin_v31` mutation.
4. Emit UNITARES telemetry.

Exit criterion: Hermes cannot silently mutate a leased surface without seeing the conflict.

### Phase 4 — handoff

1. Implement handoff offer/accept.
2. Add freshness horizon to handoff payloads.
3. Add tests for expiry/rejection.
4. Use handoff for compaction or subagent transfer.

Exit criterion: ownership can move without waiting for TTL expiry or creating ghost claims.

## Design risks

- Too broad too early: avoid agent chat, inboxes, or global routing until leases work.
- Hidden distributed truth: local BEAM process monitoring only proves local liveness; external agents need heartbeat TTL.
- Lock theater: if evidence refs are not validated, leases become performative claims.
- KG sludge: lease lifecycle should not flood KG.
- Overcoupling: UNITARES should consume evidence; it should not depend on BEAM runtime for core identity resolution.
- Split-brain: distributed BEAM clustering is out of scope until single-node semantics are proven.

## First decision needed

Where should the kernel live?

Recommendation: start as a separate repo, `unitares-coordination-kernel`, because it is a service boundary with its own runtime, dependencies, CI, and deployment cadence. Keep UNITARES integration through HTTP/MCP and Postgres schema migrations only after the primitive proves itself.

If the operator wants minimal repo sprawl, start under `unitares/services/coordination_kernel/` and split later.

## Immediate next action

Install/confirm Elixir, then spike Phase 1 in a scratch branch/repo:

```bash
brew install elixir
mix new coordination_kernel --sup
cd coordination_kernel
mix test
```

Then implement only in-memory `SurfaceRegistry` + `LeaseProcess` and test conflict/expiry behavior. Do not touch UNITARES production schema until Phase 1 proves the semantics.
