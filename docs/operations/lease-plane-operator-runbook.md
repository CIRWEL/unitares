# Surface Lease Plane Operator Runbook

Status: **STUB — service does not exist yet.** This runbook is shipped alongside the v0 RFC (`docs/proposals/surface-lease-plane-v0.md`) so the operator-facing surface is visible before any code lands. Concrete commands and ports get filled in when the service ships.

The audience is Kenny (operator-as-reviewer, not author). This runbook teaches what the BEAM node does, not Elixir-the-language. PRs will read clearly enough without prior fluency once these terms are familiar.

## What the lease plane is

A standalone Elixir/OTP application running on the governance MCP host (Mac). It owns coordination state for shared mutable surfaces (file paths, dialectic sessions, resident lifecycles, capture windows). Backed by Postgres for durable truth. Single-node by design — there is no Erlang clustering across Mac↔Pi.

It does not own EISV, calibration, KG, or identity issuance. Those stay in Python. (RFC §2 invariant.)

## Vocabulary you'll see in PRs

- **GenServer** — a process that holds state and serves messages from its mailbox one at a time. The "process as actor" primitive. Mailbox-serialized = no two callers stomping its state.
- **DynamicSupervisor** — a supervisor that starts and stops child processes at runtime. The lease plane uses one for per-lease holder processes.
- **Registry** — a process directory. "Find me the holder process for surface X."
- **`:DOWN`** — the message a supervisor or monitor receives when a watched process dies. The corpse-lock fix: when a local lease holder dies, the supervisor sees `:DOWN`, releases the lease, writes the Postgres release row.
- **Oban** — durable job queue. Reaper sweeps, handoff timeouts, audit-outbox drains run as Oban jobs. If the BEAM node restarts, Oban jobs resume from Postgres.
- **PromEx** — Prometheus metrics exporter. Lease-plane metrics flow into the existing Sentinel/dashboard surface.
- **Telemetry** — structured event emission. Lease events fire telemetry; PromEx aggregates, audit-outbox persists.
- **Ecto / Postgrex** — the Postgres ORM and driver. The lease plane talks to the same `governance` database UNITARES uses.

## Start

TBD. Likely a launchd plist (`com.unitares.lease-plane`), matching the pattern for Vigil / Sentinel / Chronicler. Service should start automatically on boot and after upgrades.

## Stop

TBD. Graceful stop releases all *local-holder* leases (the BEAM-monitored ones) by writing release rows. *Remote-holder* leases are unaffected and continue to be tracked via Postgres heartbeat-TTL until their holders re-heartbeat or expire naturally.

## Health check

TBD. Sentinel will monitor `GET /v1/lease/status?surface_id=__healthcheck__` (RFC §7.7). Alarm fires if unreachable for >5min.

## Live introspection (the BEAM superpower)

This is the part most worth learning. From your laptop:

```bash
# Connect to the running BEAM node interactively
iex --sname operator --remsh unitares-lease-plane@localhost
```

Once attached, useful commands:

```elixir
# GUI: full supervision tree, mailbox depths, ETS tables, message rates
:observer.start()

# Quick: show the supervision tree as text
:observer_cli.start()    # if observer_cli is added as a dep

# Inspect a specific GenServer's state without restarting it
:sys.get_state(UnitaresLeasePlane.HandoffServer)

# Trace a process's messages live (sparingly — it's heavy)
:dbg.tracer()
:dbg.p(pid, [:m, :c])

# Count active leases right now
UnitaresLeasePlane.Stats.active_lease_count()
```

The point: when something is wrong, you don't add print statements and redeploy. You attach, look, and decide.

## Deprecating a surface_kind (RFC §7.11.2 — R1 canonical path)

The 4-phase deprecation procedure runs through the Python CLI at
`scripts/dev/lease_plane_deprecate.py`. R1 (PR #284) introduced
`deprecate-and-finalize` as the canonical Phase 2+3 super-command; the
standalone `deprecation-sweep` and `deprecation-finalize` subcommands remain
as **operator escape hatches** for emergency partial recovery only.

### Canonical sequence (production deprecation)

```bash
# Phase 0: mark the scheme deprecated (writes deprecated_schemes row,
#   emits lease.deprecation_marked event)
python3 scripts/dev/lease_plane_deprecate.py deprecate <kind> --days 30

# Phase 1 (operator-driven): wait the drain window; verify no Elixir source
#   still references the deprecated scheme (unitares_doctor lint — Phase B prep)

# Phase 2+3: atomic on a single connection, correlated under shared run_id
python3 scripts/dev/lease_plane_deprecate.py deprecate-and-finalize <kind>
```

The super-command runs Phase 2 (sweep — force-release surviving leases) and
Phase 3 (finalize — record `check_migrated_at`) on a single asyncpg
connection in two transactions. Both phases share a `run_id` (uuid4) that
appears in every emitted event payload + every log line, so partial
completion is correlatable in audit queries:

```sql
SELECT event_type, ts FROM lease_plane.lease_plane_events
WHERE payload->>'run_id' = '<uuid-from-stderr-log>'
ORDER BY ts;
```

### Recovery from partial failure

The super-command uses **two transactions on one connection** (operator
decision 2026-05-02): if Phase 3 fails after Phase 2 succeeded, the swept
rows STAY released (no rollback of operator work). The super-command:

1. Emits `lease.deprecation_aborted` event with run_id + reason payload
2. Logs clear "rerun deprecation-finalize <kind>" guidance to stderr
3. Returns exit code 3

The §7.11.4 idempotent-sweep predicate makes the rerun safe. To recover:

```bash
# Fix the underlying issue that caused Phase 3 to fail, then:
python3 scripts/dev/lease_plane_deprecate.py deprecation-finalize <kind>
```

### Escape-hatch sub-commands (DO NOT use in routine deprecation)

Use ONLY when the super-command itself is unavailable or has failed in
ways that prevent normal recovery:

- `deprecation-sweep <kind>` — Phase 2 standalone. Requires
  `LEASE_FORCE_RELEASE_TOKEN`. Idempotent.
- `deprecation-finalize <kind>` — Phase 3 standalone. Used as the canonical
  recovery path after a failed super-command (see "Recovery from partial
  failure" above).

### Audit query: any abandoned deprecations?

Two queries — run both. The first catches abandons where the super-command
emitted the abort event before exiting. The second catches the
SIGKILL-between-phases case (Phase 2 committed, super-command was killed
before Phase 3 could run, no abort event was written).

```sql
-- (1) Explicit abandon: abort event emitted
SELECT
  payload->>'kind' AS kind,
  payload->>'run_id' AS run_id,
  payload->>'reason' AS reason,
  ts
FROM lease_plane.lease_plane_events
WHERE event_type = 'lease.deprecation_aborted'
ORDER BY ts DESC;

-- (2) Implicit abandon: Phase 2 committed but Phase 3 never ran
-- (SIGKILL / power loss / OOM mid-super-command)
SELECT
  surface_kind,
  sweep_completed_at,
  check_migrated_at
FROM lease_plane.deprecated_schemes
WHERE sweep_completed_at IS NOT NULL
  AND check_migrated_at IS NULL
ORDER BY sweep_completed_at DESC;
```

If a row appears in either query for `<kind>`, that deprecation is in
"swept but unfinalized" state. Recovery: rerun
`deprecation-finalize <kind>` (the §7.11.4 idempotent-sweep predicate
makes this safe even if Phase 2 is also re-attempted via the super-command).

### Recovery from SIGKILL mid-Phase-2

If `deprecate-and-finalize` was killed (SIGKILL, OOM, parent-process death)
while Phase 2 was running, the in-flight transaction is rolled back by
Postgres when it detects the dead client. Until that happens, row-level
locks (`FOR UPDATE SKIP LOCKED`) on `lease_plane.surface_leases` rows for
the deprecated kind may be held. To inspect:

```sql
-- Check for stuck backends with active transactions on surface_leases
SELECT pid, state, query_start, wait_event, query
FROM pg_stat_activity
WHERE state IN ('active', 'idle in transaction')
  AND query LIKE '%lease_plane.surface_leases%'
ORDER BY query_start;
```

Postgres has no `idle_in_transaction_session_timeout` by default, so a
stuck backend may persist indefinitely until the operator either: (a)
restores the killed super-command (it'll observe its tx was lost), (b)
manually `pg_terminate_backend(<pid>)` the stuck backend, or (c) restarts
Postgres. Once the stuck backend is gone, rerun `deprecate-and-finalize <kind>`
— Phase 2 will sweep zero rows (idempotent predicate) and Phase 3 will
finalize cleanly.

## Common operations

TBD. Will include:

- **Drain a surface kind** (e.g. release all `dialectic:/` leases held by a specific UUID — for a stuck-agent recovery)
- **Promote a surface kind from advisory to enforcement** (config flag flip, no restart needed; documented in RFC §6.2)
- **Demote a surface kind back to advisory** (single config flag flip; the reversal must be cheap, never a code change)
- **Inspect the audit-outbox backlog** (`SELECT count(*) FROM lease_plane_events WHERE forwarded_at IS NULL`)
- **Force-release a lease the operator knows is corpse-held** (last-resort manual override; logged to audit with `release_reason='operator_forced'`)

## Hot code reload (the BEAM thing that matters operationally)

When a new version of a module is deployed, the BEAM node can swap it in place without dropping leases. This directly addresses `feedback_running-process-vs-master-commit.md` — the running-process-vs-master-commit drift class:

- Old: `ps -o etime` + `git log --since=` to figure out if the resident has the fix you think it has
- New: deploy = module swap = the running node *has the fix*. The "is this code running?" question becomes "what version is loaded?", which `:application.loaded_applications/0` answers directly.

v0 does not *automate* hot-reload deploys. Initial deploys are full-restart. But the capability is the floor, not a feature add.

## When things go wrong

TBD. Will include incident-class playbooks for:

- Lease plane unreachable (callers fall through to advisory-skip; no work blocked, but conflict telemetry stops)
- Postgres flapping (Oban retries the audit-outbox drains; the synchronous lease writes return `service_unavailable` to callers)
- Reaper falling behind (active-lease count grows, expired-but-not-released count grows; Sentinel alerts fire on threshold)
- Audit-outbox backlog growing (UNITARES-side worker stalled or DB partition issue)
- Phantom local holder (`:observer` shows the process alive, but Postgres has no lease row for it — schema invariant violated, file an incident)

## Related

- RFC: `docs/proposals/surface-lease-plane-v0.md` (v0.1, pre-council)
- Pattern precedent: `docs/proposals/path1-sync-fingerprint-check.md` (advisory→strict rollout)
- Existing operator runbook: `docs/operations/OPERATOR_RUNBOOK.md` (Python governance MCP)
- Memory anchors: `feedback_running-process-vs-master-commit.md`, `multi-agent-git-reset-incident.md`, `feedback_check-in-during-long-sessions.md`
