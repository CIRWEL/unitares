# UNITARES SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the standalone `unitares_sdk` package described in [docs/superpowers/specs/2026-04-13-unitares-sdk-design.md](/Users/cirwel/projects/governance-mcp-v1/docs/superpowers/specs/2026-04-13-unitares-sdk-design.md), then migrate Watcher, Vigil, and Sentinel onto it without changing governance-server behavior.

**Architecture:** The SDK lives in-repo at `agents/sdk/` with a normal `src/` layout and its own `pyproject.toml`. It exposes three layers: `GovernanceClient` (async MCP), `SyncGovernanceClient` (sync REST or sync-over-async), and `GovernanceAgent` plus `CycleResult` (long-running agent lifecycle). Watcher adopts the sync client first; Vigil and Sentinel then adopt the base class while keeping their existing domain logic.

**Tech Stack:** Python 3.12, `httpx`, `mcp`, `pydantic` v2, `pytest`, `pytest-asyncio`

## Constraints

- No imports from repo `src/` inside `agents/sdk/src/unitares_sdk/`.
- The SDK maps to canonical server tools, not compatibility aliases:
  - `checkin()` -> `process_agent_update`
  - `get_metrics()` -> `get_governance_metrics`
  - KG write/read helpers -> `knowledge(action=...)` where specified by the spec
- The root test command must keep working. Because the SDK uses `agents/sdk/src`, root pytest config must be updated so `unitares_sdk` is importable without a manual editable install.
- Each migration step must leave the resident agents runnable.
- This phase does not modify governance-server handlers except where tests expose a pre-existing mismatch that blocks the SDK contract.

## Files

### New files

```text
agents/sdk/
  pyproject.toml
  src/
    unitares_sdk/
      __init__.py
      agent.py
      client.py
      errors.py
      models.py
      sync_client.py
      utils.py
  tests/
    test_agent.py
    test_client.py
    test_sync_client.py
    test_utils.py
docs/superpowers/plans/2026-04-13-unitares-sdk-implementation.md
```

### Files to modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `agents/sdk/src` to pytest `pythonpath` so root test runs can import `unitares_sdk` |
| `agents/watcher/agent.py` | Replace raw governance REST calls with `SyncGovernanceClient`; keep direct Ollama fallback |
| `agents/vigil/agent.py` | Migrate transport/session boilerplate to `GovernanceAgent` + SDK utilities |
| `agents/sentinel/agent.py` | Migrate transport/session boilerplate to `GovernanceAgent` + SDK utilities while preserving WebSocket loop |
| `agents/common/__init__.py` | Re-export SDK entry points if compatibility shims are needed |
| `agents/common/mcp_client.py` | Remove dead transport code or leave a thin compatibility shim |
| `agents/common/config.py` | Keep endpoint constants if still used by agents |
| `agents/vigil/tests/*` | Update tests to exercise the migrated base-class behavior |
| `agents/sentinel/tests/*` | Update tests to exercise the migrated base-class behavior |
| `agents/watcher/tests/test_agent.py` | Update tests for SDK-backed governance calls |

### Existing files to use as implementation references

- `agents/vigil/agent.py`
- `agents/sentinel/agent.py`
- `agents/watcher/agent.py`
- `agents/common/mcp_client.py`
- `tests/test_identity_handlers.py`
- `tests/test_http_endpoints.py`
- `tests/test_unitares_cli_script.py`
- `tests/test_core_update.py`
- `tests/test_model_inference.py`

## Task 1: Scaffold the SDK package and repo test wiring

**Files:**
- Create: `agents/sdk/pyproject.toml`
- Create: `agents/sdk/src/unitares_sdk/__init__.py`
- Create: `agents/sdk/tests/test_client.py`, `test_sync_client.py`, `test_agent.py`, `test_utils.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create the directory structure**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
mkdir -p agents/sdk/src/unitares_sdk agents/sdk/tests
```

- [ ] **Step 2: Add `agents/sdk/pyproject.toml`**

Use the nested package metadata from the spec:
- package name: `unitares-sdk`
- Python: `>=3.12`
- dependencies: `httpx`, `mcp`, `pydantic`
- optional dev deps: `pytest`, `pytest-asyncio`
- setuptools `src/` layout pointing at `src/unitares_sdk`

- [ ] **Step 3: Add repo-level pytest import wiring**

Update root [pyproject.toml](/Users/cirwel/projects/governance-mcp-v1/pyproject.toml) so root pytest can import `unitares_sdk`:

```toml
[tool.pytest.ini_options]
pythonpath = [".", "agents/sdk/src"]
```

Keep `testpaths = ["tests", "agents"]` unchanged so `python3 -m pytest tests/ agents/ -q --tb=short -x` still discovers the SDK tests.

- [ ] **Step 4: Add a minimal package smoke import**

Start `agents/sdk/src/unitares_sdk/__init__.py` with the public re-export surface only:
- `GovernanceClient`
- `SyncGovernanceClient`
- `GovernanceAgent`
- `CycleResult`
- public result models
- public exceptions

- [ ] **Step 5: Commit**

```bash
git add agents/sdk pyproject.toml
git commit -m "feat(sdk): scaffold unitares_sdk package layout"
```

## Task 2: Implement SDK primitives first

**Files:**
- Create: `agents/sdk/src/unitares_sdk/errors.py`
- Create: `agents/sdk/src/unitares_sdk/models.py`
- Create: `agents/sdk/src/unitares_sdk/utils.py`
- Modify: `agents/sdk/tests/test_utils.py`

- [ ] **Step 1: Implement `errors.py`**

Define:
- `GovernanceError`
- `GovernanceConnectionError`
- `GovernanceTimeoutError`
- `IdentityDriftError`
- `VerdictError`

Implementation detail:
- `IdentityDriftError` and `VerdictError` should carry structured fields and readable `__str__` output so agents can log them without custom formatting.

- [ ] **Step 2: Implement `models.py`**

Add:
- `_GovModel` with `extra="ignore"`
- `OnboardResult`
- `IdentityResult`
- `CheckinResult`
- `NoteResult`
- `SearchResult`
- `AuditResult`
- `CleanupResult`
- `ArchiveResult`
- `RecoveryResult`
- `MetricsResult`
- `ModelResult`

Implementation detail:
- Use `Field(default_factory=list)` and `Field(default_factory=dict)` rather than mutable literal defaults.
- Keep field names aligned with current server payloads first; friendly remapping belongs in parsing helpers, not in the model definitions.

- [ ] **Step 3: Implement `utils.py`**

Port and consolidate the shared local utilities from Vigil and Sentinel:
- `atomic_write`
- `notify`
- `load_json_state`
- `save_json_state`
- `parse_continuity_token`
- `validate_token_uuid`

Implementation detail:
- `parse_continuity_token()` should only parse `v1.<payload>.<sig>` and decode the payload JSON. It must not attempt signature verification because the SDK does not hold the server secret.
- `notify()` must stay best-effort and no-op on non-macOS systems.

- [ ] **Step 4: Add unit tests for the primitives**

Cover:
- atomic writes and corrupt/missing JSON fallback
- continuity token parse success, malformed token rejection, UUID mismatch detection
- model construction against representative payload shapes copied from current tests and live agent code paths

- [ ] **Step 5: Commit**

```bash
git add agents/sdk
git commit -m "feat(sdk): add models errors and utilities"
```

## Task 3: Implement the async `GovernanceClient`

**Files:**
- Create: `agents/sdk/src/unitares_sdk/client.py`
- Modify: `agents/sdk/tests/test_client.py`

- [ ] **Step 1: Implement connection lifecycle**

Wrap streamable HTTP MCP using:
- `httpx.AsyncClient`
- `mcp.client.streamable_http.streamable_http_client`
- `mcp.client.session.ClientSession`

The client must support:
- `connect()`
- `disconnect()`
- `async with GovernanceClient(...)`

- [ ] **Step 2: Implement the raw `call_tool()` path**

`call_tool()` is the source of truth for:
- per-call `asyncio.wait_for(...)`
- one retry on transient connection/timeout errors
- MCP `content[*].text` aggregation and `json.loads(...)`
- raw dict return for typed methods
- session injection for all non-identity tools

Use the extraction logic already proven in Vigil/Sentinel for:
- `client_session_id`
- `continuity_token`
- resolved UUID from `uuid`, `agent_uuid`, or `bound_identity.uuid`

- [ ] **Step 3: Implement typed methods using canonical server mapping**

Map SDK methods exactly as specified:
- `onboard()` -> `onboard`
- `identity()` -> `identity`
- `checkin()` -> `process_agent_update`
- `leave_note()` -> `leave_note`
- `search_knowledge()` -> `knowledge(action="search")`
- `store_discovery()` -> `knowledge(action="store")`
- `audit_knowledge()` -> `knowledge(action="audit")`
- `cleanup_knowledge()` -> `knowledge(action="cleanup")`
- `archive_orphan_agents()` -> `archive_orphan_agents`
- `self_recovery()` -> `self_recovery`
- `get_metrics()` -> `get_governance_metrics`
- `call_model()` -> `call_model`

- [ ] **Step 4: Implement error mapping**

Translate low-level failures into SDK exceptions:
- transport failures -> `GovernanceConnectionError`
- timeout/deadlock path -> `GovernanceTimeoutError`
- UUID mismatch after identity capture -> `IdentityDriftError`
- pause/reject governance verdicts -> `VerdictError`

Implementation rule:
- Only raise `VerdictError` once the response parser has positively identified the verdict from the current server payload. Do not guess field names.

- [ ] **Step 5: Add unit tests**

Cover:
- tool-name mapping
- kwargs passthrough
- timeout and retry
- session injection skip for `onboard` and `identity`
- identity capture from multiple response shapes
- verdict error raising
- `call_model(provider=None, model=None)` passing server-decided defaults through untouched

- [ ] **Step 6: Commit**

```bash
git add agents/sdk
git commit -m "feat(sdk): implement async governance client"
```

## Task 4: Implement `SyncGovernanceClient`

**Files:**
- Create: `agents/sdk/src/unitares_sdk/sync_client.py`
- Modify: `agents/sdk/tests/test_sync_client.py`

- [ ] **Step 1: Implement `transport="rest"`**

Use `urllib.request` to POST to `/v1/tools/call`.

REST parsing rules:
- read the outer envelope `{name, result, success}`
- if `success` is false, raise an SDK error
- for normalized core tools, use `data["result"]` directly
- keep a compatibility fallback for `result.content[0].text` only if an HTTP fallback path returns raw MCP content blocks

- [ ] **Step 2: Implement `transport="mcp"`**

Wrap the async client via `asyncio.run()` for standalone sync consumers.

Guardrail:
- detect an already-running event loop and raise `RuntimeError` immediately for `transport="mcp"`

- [ ] **Step 3: Share identity/session logic with the async client**

Do not fork the extraction or session-persistence logic. Keep one code path for:
- session capture
- UUID capture
- typed-method argument shaping

- [ ] **Step 4: Add unit tests**

Cover:
- REST envelope parsing
- outer vs inner failure handling
- event-loop guard for sync-over-async mode
- typed methods returning the same models as the async client

- [ ] **Step 5: Commit**

```bash
git add agents/sdk
git commit -m "feat(sdk): implement sync governance client"
```

## Task 5: Implement `GovernanceAgent` and `CycleResult`

**Files:**
- Create: `agents/sdk/src/unitares_sdk/agent.py`
- Modify: `agents/sdk/tests/test_agent.py`

- [ ] **Step 1: Implement `CycleResult`**

Add the dataclass exactly as planned:
- `summary`
- `complexity`
- `confidence`
- `response_mode`
- `notes`
- `CycleResult.simple()`

- [ ] **Step 2: Implement identity/session lifecycle**

Port the three-step resolution flow from Vigil/Sentinel:
1. continuity-token resume
2. name resume
3. fresh onboard fallback

Requirements:
- persist `client_session_id` and `continuity_token`
- validate token structure and embedded `aid`
- detect UUID drift and raise `IdentityDriftError`

- [ ] **Step 3: Implement agent loop helpers**

Add:
- `run_once()`
- `run_forever(interval, heartbeat_interval)`
- `load_state()`
- `save_state()`
- signal-handler shutdown support

Check-in behavior:
- `CycleResult` -> `client.checkin(...)`
- `CycleResult.notes` -> `client.leave_note(...)`
- `None` -> skip normal check-in
- heartbeat timer -> compact heartbeat check-in

- [ ] **Step 4: Keep verdict policy conservative**

Do not over-generalize recovery logic into the base class yet. The base class should surface `VerdictError` cleanly; any aggressive self-recovery policy that is currently unique to Vigil stays in the agent migration layer unless a shared pattern emerges during implementation.

- [ ] **Step 5: Add unit tests**

Cover:
- token/name/onboard resolution order
- stale token discard
- session persistence
- heartbeat behavior
- note fan-out
- graceful shutdown
- verdict error propagation

- [ ] **Step 6: Commit**

```bash
git add agents/sdk
git commit -m "feat(sdk): implement governance agent base class"
```

## Task 6: Migrate Watcher onto `SyncGovernanceClient`

**Files:**
- Modify: `agents/watcher/agent.py`
- Modify: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Replace raw governance REST `call_model` code**

Swap `call_model_via_governance()` to use `SyncGovernanceClient(transport="rest")`.

Preserve current behavior:
- governance-first path
- direct Ollama fallback on governance error
- deterministic `temperature=0.0`

- [ ] **Step 2: Replace raw KG escalation POSTs**

Use `client.store_discovery(...)` for critical findings instead of hand-rolled `urllib` JSON.

- [ ] **Step 3: Keep Watcher-specific fallback logic local**

The SDK should not absorb Watcher’s direct-Ollama fallback or its finding lifecycle logic. Only governance communication moves.

- [ ] **Step 4: Update Watcher tests**

Add assertions for:
- SDK client invocation
- unchanged fallback semantics
- unchanged critical-finding escalation behavior

- [ ] **Step 5: Commit**

```bash
git add agents/watcher agents/sdk
git commit -m "refactor(watcher): adopt sync governance sdk client"
```

## Task 7: Migrate Vigil onto `GovernanceAgent`

**Files:**
- Modify: `agents/vigil/agent.py`
- Modify: `agents/vigil/tests/test_groundskeeper.py`
- Modify: `agents/vigil/tests/test_cycle_timeout.py`

- [ ] **Step 1: Remove duplicated transport/session boilerplate**

Delete or replace the local Vigil copies of:
- `_atomic_write`
- `notify`
- `load_session`
- `save_session`
- `load_state`
- `save_state`
- `call_tool`
- identity extraction and capture helpers

Use SDK primitives instead.

- [ ] **Step 2: Make Vigil a `GovernanceAgent` subclass**

Keep Vigil-specific logic local:
- governance/anima health checks
- optional test runs
- groundskeeper audit/cleanup/orphan archival
- state diffing and change-note generation

Return `CycleResult` from `run_cycle()` with:
- summary
- computed complexity
- computed confidence
- note tuples for interesting changes

- [ ] **Step 3: Preserve Vigil-specific recovery behavior**

If current behavior depends on trying `self_recovery(action="quick")` after a paused check-in, keep that logic in Vigil during the migration rather than forcing it into the shared base class.

- [ ] **Step 4: Update Vigil tests**

Cover:
- cycle timeout behavior still bounds hung SDK calls
- groundskeeper actions still fire
- change notes still persist
- state persistence still works through SDK utilities

- [ ] **Step 5: Commit**

```bash
git add agents/vigil agents/sdk
git commit -m "refactor(vigil): migrate to governance sdk base agent"
```

## Task 8: Migrate Sentinel onto `GovernanceAgent`

**Files:**
- Modify: `agents/sentinel/agent.py`
- Modify: `agents/sentinel/tests/test_cycle_timeout.py`

- [ ] **Step 1: Remove duplicated transport/session boilerplate**

Delete or replace the local Sentinel copies of:
- `_atomic_write`
- `notify`
- `load_state`
- `save_state`
- `load_session`
- `save_session`
- `call_tool`
- identity extraction and capture helpers

- [ ] **Step 2: Keep WebSocket management Sentinel-local**

`GovernanceAgent` should not own `/ws/eisv`. Sentinel keeps:
- `ws_consumer()`
- fleet-state ingestion
- analysis scheduling

The migration target is:
- WebSocket loop remains local
- per-analysis governance check-in uses inherited SDK lifecycle

- [ ] **Step 3: Convert analysis output to `CycleResult`**

Map fleet findings into:
- check-in summary
- computed complexity/confidence
- note tuples for high-severity non-self findings

- [ ] **Step 4: Update Sentinel tests**

Cover:
- cycle timeout behavior
- WebSocket disconnect handling still does not wedge the agent
- high-severity findings still emit notes/notifications

- [ ] **Step 5: Commit**

```bash
git add agents/sentinel agents/sdk
git commit -m "refactor(sentinel): migrate to governance sdk base agent"
```

## Task 9: Cleanup compatibility layers and verify end to end

**Files:**
- Modify: `agents/common/__init__.py`
- Modify: `agents/common/mcp_client.py`
- Modify: any imports that still reference dead duplicated helpers

- [ ] **Step 1: Remove or slim `agents/common/`**

After Watcher, Vigil, and Sentinel no longer need the old shared transport layer:
- delete dead helpers, or
- leave thin compatibility re-exports if other local code still imports them

Do not keep two independent implementations of the same governance client logic.

- [ ] **Step 2: Run targeted SDK and agent tests**

Run:

```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 -m pytest agents/sdk/tests agents/watcher/tests agents/vigil/tests agents/sentinel/tests -q --tb=short -x
```

- [ ] **Step 3: Run a final full repo validation pass**

Run:

```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 -m pytest tests/ agents/ -q --tb=short -x
```

- [ ] **Step 4: Optional live smoke test against a running server**

Manually verify:
1. `SyncGovernanceClient().onboard(...)`
2. `GovernanceClient().checkin(...)`
3. Watcher critical finding -> `store_discovery(...)`
4. Vigil once-cycle
5. Sentinel one bounded analysis cycle

- [ ] **Step 5: Final cleanup commit**

```bash
git add agents/common agents/sdk agents/watcher agents/vigil agents/sentinel pyproject.toml
git commit -m "chore(sdk): remove duplicated governance client code"
```

## Commit Plan

1. `feat(sdk): scaffold unitares_sdk package layout`
2. `feat(sdk): add models errors and utilities`
3. `feat(sdk): implement async governance client`
4. `feat(sdk): implement sync governance client`
5. `feat(sdk): implement governance agent base class`
6. `refactor(watcher): adopt sync governance sdk client`
7. `refactor(vigil): migrate to governance sdk base agent`
8. `refactor(sentinel): migrate to governance sdk base agent`
9. `chore(sdk): remove duplicated governance client code`

## Definition of Done

- `unitares_sdk` builds from `agents/sdk/pyproject.toml`
- Root pytest can import `unitares_sdk` without manual path hacking
- Watcher uses `SyncGovernanceClient`
- Vigil and Sentinel use `GovernanceAgent` plus `CycleResult`
- duplicated session/transport parsing code is removed from Vigil and Sentinel
- compatibility shims in `agents/common/` are either deleted or intentionally thin
- `python3 -m pytest tests/ agents/ -q --tb=short -x` passes
