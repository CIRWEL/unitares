# Config Hot-Reload — Design

**Date:** 2026-04-25
**Status:** Approved (brainstorming → spec)
**Scope:** narrow — admin tools only, no watcher, no `config.yaml`

## Problem

UNITARES requires a `launchctl unload && load` cycle for any config change. The user wanted Hermes-style file-watched hot-reload (`config.yaml` → live reconnect).

## Why the Hermes pattern doesn't transfer

Hermes hot-reloads its **outbound MCP client connections** — cheap, idempotent socket reconnects against a static manifest.

UNITARES **is** the MCP server. Its "config" is not a file:

1. `config/governance_config.py` — Python `GovernanceConfig` class, static at import.
2. `governance_core/parameters.py` — `DynamicsParams`, `Theta` (ODE coefficients).
3. `src/runtime_config.py` — threshold overrides, **already runtime-mutable** via `set_thresholds()`.
4. `src/agent_state.py` — server constants.
5. Env vars, read at startup.

Adopting a watcher imports two problems UNITARES doesn't currently have: a second source of truth (file vs. existing `_runtime_overrides` dict), and split-brain reload semantics (stale `from config.governance_config import config` references in modules like `governance_monitor.py:22` would not see new values after `importlib.reload()`).

## Decision

**Option C — push, not pull.** Surface the existing runtime-mutable threshold path as MCP admin tools. No file watcher, no `config.yaml`, no module re-exec.

The mutation mechanism is already in place. The gap is operator access: `set_thresholds()` is callable from in-process Python, but is not exposed as a named MCP tool. Two new admin tools close that gap.

## Architecture

### New MCP admin tools (in `src/mcp_handlers/admin/`)

**`admin_configure_thresholds`**
- Wraps `src.runtime_config.set_thresholds()`.
- Accepts `{name: float}` dict; applies validation already implemented in `runtime_config`.
- Returns the same `{success, updated, errors}` shape `set_thresholds` already returns.
- Operator-gated: requires admin auth (same gate as existing admin handlers under `src/mcp_handlers/admin/`).
- anyio-safe: pure in-memory mutation of `_runtime_overrides`. No DB call. No `await` of asyncpg.

**`admin_get_config`**
- Returns the union of: current runtime overrides, defaults from `GovernanceConfig`, and the `runtime_changeable / static / core / server` taxonomy already produced by `ConfigManager.get_config_info()`.
- Read-only. Same auth gate.

### Documentation update

In `src/config_manager.py` docstring (top of file): add a "Restart-required fields" section listing fields that are intentionally **not** hot-reloadable, with reasoning. This frames the discipline rather than implying a missing feature.

Restart-required (load-bearing reasoning, do not soften):
- `CURRENT_EPOCH` — newly written rows must carry consistent epoch tags within a session; mid-flight change poisons epoch-gated queries.
- `DELTA_NORM_MAX_BY_CLASS`, `HEALTHY_OPERATING_POINT_BY_CLASS` — class-conditional calibration constants participating in every ODE manifold computation; mid-flight mutation produces incoherent per-agent distance calculations.
- `ADAPTIVE_GOVERNOR_ENABLED` — captured per-monitor at `UNITARESMonitor.__init__()` (governance_monitor.py:171); changing live creates inconsistent branches across monitors constructed before vs. after the change. Restart enforces a uniform branch.
- `SESSION_TTL_SECONDS` — derived from `SESSION_TTL_HOURS` at module import; the derived field is the landmine, not the primary one.
- `BEHAVIORAL_VERDICT_ENABLED` — captured at class-body time (governance_config.py:371) with no accessor indirection.
- DB pool / Redis URL / port bindings — resource-owning. Hot-swap requires teardown coordination with in-flight requests; out of scope.

## Data flow

```
operator
  → MCP call admin_configure_thresholds({risk_approve_threshold: 0.4})
  → admin auth gate
  → src.runtime_config.set_thresholds(...)
  → mutates _runtime_overrides dict (in-process)
  → returns {success, updated, errors}

next process_agent_update
  → src.runtime_config.get_effective_threshold("risk_approve_threshold", default)
  → reads new value from _runtime_overrides
  → governance decision uses new threshold
```

No reload step. No teardown. Effect is live on the next read.

## Resident agent coverage

The thresholds are evaluated **server-side** during `process_agent_update`. All resident agents (Vigil, Sentinel, Chronicler, Steward, Watcher) check in to the server, so verdict computation against the new thresholds is automatic. Agent-local constants (e.g. Sentinel's anomaly heuristics) are out of scope — they were never in scope; the user's question was about governance config, not arbitrary per-agent state.

## Error handling

- Validation failure (out-of-range threshold): `set_thresholds` already returns `{success: false, errors: [...]}`. Surface this in the MCP tool response unchanged.
- Auth failure: standard admin-handler 403-equivalent response.
- No retry, no rollback path — overrides are pure in-memory. To revert: call `admin_configure_thresholds` with the previous value, or restart for a clean default.

## Testing

- Unit: each tool's argument validation, auth gate, error shape.
- Integration: call `admin_configure_thresholds` → call `process_agent_update` → assert verdict reflects new threshold.
- Regression: existing `set_thresholds` contract tests stay green; new tools are wrappers.
- Tests ship with the implementation in the same commit (per project test-coverage policy).

## Out of scope (explicit)

- File watcher of any kind (`watchdog`, mtime poll, OS notification).
- `config.yaml` introduction.
- `importlib.reload()` of `config/governance_config.py`.
- Hot-reload of DB pool, MCP transport, port binding, Redis URL.
- Hot-reload of `DynamicsParams` / `Theta` beyond the env-var path that already exists in `governance_core/parameters.py:175-218` (per-call `os.getenv` — already live).
- Resident-agent local config reload (each launchd agent restarts on its own cadence).

## Risks

- **Surface-creep risk.** Once `admin_configure_thresholds` ships, there will be pressure to widen its accepted-name allowlist into restart-required fields. Validation in `runtime_config.set_thresholds` is the chokepoint — keep the allowlist explicit, do not switch to "any name passes."
- **Operator-error risk.** Live threshold change can flip basin assignments for in-flight check-ins. Acceptable: the current `launchctl` path has the same property and the operator population is small.
- **Audit risk.** Threshold changes via `set_thresholds` are not currently logged to the event stream. Recommend (post-design) emitting an admin-event row from the new tools so changes are visible in the dashboard. Tracked as a follow-up, not a blocker.

## Open follow-ups (not blocking this spec)

- Admin-event emission for threshold changes (dashboard visibility).
- Persistence: should overrides survive process restart, or is restart-clears-overrides intentional? Current behavior is restart-clears. Defer.
