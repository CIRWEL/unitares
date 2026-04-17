# Lumen / Anima Decoupling from Unitares — Design & Phasing

**Status:** Design doc. Phase A ready to execute. Phase B blocked on architectural decision.
**Author:** Kenny (via pair session with Claude, 2026-04-17)
**Scope:** Two repos — `unitares` and `anima-mcp`.

---

## Goal

Make `unitares` user-agnostic — a candidate for OSS / enterprise release — while keeping Lumen's hardware-specific features in `anima-mcp`. Today unitares carries ~700 lines of Lumen-specific code and four hardcoded `"Lumen"` special-cases.

## Non-Goals

- Eliminating the concept of embodied agents from governance. The *generic* `sensor_eisv` field in `agent_state` stays — it's already user-agnostic.
- Changing `governance_core` (compiled) semantics.
- Renaming or breaking Lumen's public MCP tool surface on `anima-mcp`.

---

## Current State — Leak Inventory (as of 2026-04-17)

| Class | Files | Approx Lines |
|-------|-------|--------------|
| **Whole Lumen-only modules in unitares** | `src/mcp_handlers/observability/pi_orchestration.py`; `src/sensor_buffer.py`; pi-action branch in `src/mcp_handlers/consolidated.py` | ~700 |
| **Hardcoded `"Lumen"` specials** | `src/agent_lifecycle.py:84`; `src/background_tasks.py:624`; `src/http_api.py:1079`; `src/mcp_handlers/admin/dashboard.py:43` | 4 sites |
| **Generic code with Lumen-named comments** | `src/governance_monitor.py:393, 811`; `src/mcp_handlers/updates/phases.py:541-550`; `src/mcp_handlers/observability/handlers.py:50` | ~15 lines |
| **Tool registration surface** | `src/tool_schemas.py:140`; `src/tool_modes.py:46`; `src/mcp_handlers/introspection/tool_introspection.py:394`; `src/mcp_handlers/tool_stability.py:245-269` (12 deprecated `pi_*` aliases) | ~30 lines |
| **Docs/comments only** | `src/trajectory_identity.py:242-245` ("Full computation happens in anima-mcp"); `src/agent_loop_detection.py:206` (`"anima"` in tag set) | ~4 lines |

False positives (not leaks, do not touch):
- `src/hck_reflexive.py` — `"PI"` = PI controller (control theory).
- `src/trajectory_identity.py:294, 300` — `Pi` = Preference (an EISV component).
- `src/behavioral_sensor.py` — pure function, no Lumen coupling.

---

## Target State

1. Unitares encodes one generic concept: **"agents that publish `sensor_eisv` in their check-in payload get spring-coupled."** Nothing named Lumen, Pi, anima, or brain-hat in `src/`.
2. Lumen ships its own integration shim in `anima-mcp` — `unitares_bridge.py` formats check-ins with the `sensor_eisv` field unitares expects.
3. Agent specials (archival protection, check-in intervals, dashboard filters) are driven by **agent tags/metadata**, not `if label == "Lumen"` branches.
4. (Phase B only) Mac→Pi orchestration lives outside unitares — either a plugin, a feature flag, or deleted entirely.

---

## Architectural Question That Gates Phase B

**Does Mac→Pi orchestration belong inside unitares at all?**

Today `pi_orchestration.py` exposes 12 `pi_*` tools (and the consolidated `pi` tool) that proxy to `anima-mcp` over Tailscale. This is convenient for Kenny-as-orchestrator, but fundamentally: unitares is reaching out to a specific embodied system.

### Option B1 — Plugin API
Build a tool-provider plugin contract in unitares. `unitares-anima-bridge` (new repo) registers the `pi` tool + 12 actions.

- **Cost:** Design a plugin contract. Doesn't exist today — `unitares-governance-plugin` is for *agent-side* integration, not server-side tool extension.
- **Value:** Scales to other embodied systems later. Cleanest long-term.

### Option B2 — Feature Flag
Keep `pi_orchestration.py` in unitares but gate the entire module behind `UNITARES_ANIMA_BRIDGE=1`.

- **Cost:** Low (one env check in `mcp_handlers/__init__.py` and `consolidated.py`).
- **Value:** Medium. OSS users can disable, but the code still ships in the repo.

### Option B3 — Unidirectional Inversion
Drop Mac→Pi tooling from unitares entirely. Callers that want to talk to Lumen connect to `anima-mcp` directly (MCP clients handle multiple servers natively). Orchestration ergonomics move to a separate `anima-cli` or multi-server MCP client config.

- **Cost:** Audit current callers of `pi_*` tools. Possible loss of convenience.
- **Value:** Highest. Zero coupling.

### Recommendation
**B3 if audit shows few real callers; B1 if the 12 `pi_*` tools are heavily used; B2 only as a short-term bridge.** Kenny to decide after Phase A lands.

---

## Phase A — Cheap Cleanups (ready to execute, ~1 day)

Self-contained, incremental, each step independently committable and reversible. No architectural decision needed.

### A1 — Flip `sensor_eisv` from pull to push

**Problem.** Today: Lumen's check-in lands in `phases.py`; phases.py calls `get_latest_sensor_eisv()` from `src/sensor_buffer.py`; `sensor_buffer` is filled by `pi_sync_eisv` (Mac→Pi pull) and by `eisv_sync_task` (background). That's bidirectional coupling + a side channel.

**Target.** Lumen's `process_agent_update` call carries `sensor_eisv` directly inside `agent_state`. Unitares never imports `sensor_buffer`.

**Verified today:**
- `anima-mcp/src/anima_mcp/unitares_bridge.py:410-418` builds `update_arguments` but does **not** currently include `sensor_eisv` (sends `sensor_data` only). Needs addition.
- `unitares/src/governance_monitor.py:395, 809` already reads `sensor_eisv` from `agent_state` generically. Once the payload has it, everything works.

**Changes — unitares side:**
- `src/mcp_handlers/updates/phases.py:541-550` — delete the `sensor_buffer` import block. `governance_monitor.py` already reads from `agent_state` — no further wiring needed.
- `src/mcp_handlers/process_agent_update/*` (or equivalent) — confirm `sensor_eisv` from call arguments lands in `agent_state`. Verify during execution.
- `src/background_tasks.py:1084` — the `eisv_sync_task` (Mac-side periodic Pi pull) becomes dead code. Delete after Lumen-side push lands.
- `src/sensor_buffer.py` — delete once no callers remain.
- `src/mcp_handlers/observability/pi_orchestration.py:603-605` — `update_sensor_eisv` call dies with `sensor_buffer`. The `pi(action='sync_eisv')` tool loses its write-to-buffer behavior but the anima→EISV mapping can stay as a diagnostic.

**Changes — anima-mcp side:**
- `src/anima_mcp/unitares_bridge.py:410-418` — add `sensor_eisv` to `update_arguments`, computed from `eisv_mapper.py` (the existing anima→EISV mapping used for governance reporting).
- Cross-check `eisv_mapper.py` returns the same keys unitares expects: `{E, I, S, V}` with `E, I ∈ [0,1]`, `S ∈ [0.001, 1.0]`, `V ∈ [-1, 1]`.

**Tests:**
- Unitares: `test_sensor_eisv_from_agent_state` — payload includes `sensor_eisv` → spring coupling activates. (Likely exists; verify.)
- Unitares: `test_behavioral_fallback_without_sensor_eisv` — payload missing → falls through to `compute_behavioral_sensor_eisv`. (Likely exists.)
- Anima-mcp: `test_unitares_bridge_includes_sensor_eisv` — bridge payload has `sensor_eisv` with correct shape and clipped ranges.

**Risk:** Low. Behavioral fallback path is already live in `governance_monitor.py:817`. If the Lumen-side push rolls out slowly, Lumen temporarily falls back to behavioral EISV — not broken, just not spring-coupled to sensors.

**Rollout order:**
1. Unitares: confirm `process_agent_update` routes `sensor_eisv` from arguments into `agent_state`. Commit as a defensive no-op if it already does.
2. Anima-mcp: add `sensor_eisv` to bridge payload. Deploy to Pi. Observe Lumen's EISV continues to move (verify via `observe(action=agent, target_agent_id=Lumen)`).
3. Unitares: remove `phases.py` import from `sensor_buffer`. Delete `eisv_sync_task` scheduling from `background_tasks.py`.
4. Unitares: delete `sensor_buffer.py` + `update_sensor_eisv` call in `pi_orchestration.py`.

**Commit boundaries:** 4 commits matching the rollout steps.

---

### A2 — Scrub Lumen-named comments from generic code

Pure string-level cleanup in code that is already generic. Zero behavior delta (except `agent_loop_detection.py:206`, which drops `"anima"` from an autonomy tag set — safe because Lumen already carries `"embodied"` and `"autonomous"`).

| File:line | Current | Target |
|-----------|---------|--------|
| `src/governance_monitor.py:393` | `# Extract sensor EISV for spring coupling (agents with physical sensors, e.g. Lumen)` | `# Extract sensor EISV for spring coupling (agents that publish sensor_eisv)` |
| `src/governance_monitor.py:811` | `# Lumen: use physical sensor EISV directly` | `# Use externally supplied sensor EISV directly when available` |
| `src/mcp_handlers/observability/handlers.py:50` | `"example": "observe(action='agent', target_agent_id='Lumen')"` | `"example": "observe(action='agent', target_agent_id='<agent-label>')"` |
| `src/trajectory_identity.py:242-245` | `"Full computation happens in anima-mcp; UNITARES receives and stores"` | `"Full computation happens upstream in the agent; UNITARES receives and stores"` |
| `src/agent_loop_detection.py:206` | `is_autonomous = bool({"autonomous", "embodied", "anima"} & agent_tags)` | `is_autonomous = bool({"autonomous", "embodied"} & agent_tags)` — drop `"anima"`; `"embodied"` covers it |

**Tests:** add a regression test asserting `is_autonomous` still returns `True` for an agent tagged `["embodied"]` alone.
**Commit boundary:** 1 commit.

---

### A3 — Replace `"Lumen"` hardcoded specials with agent metadata

Four sites; convert each to generic tag-driven behavior.

#### A3a — Archival protection (`src/agent_lifecycle.py:84`)

**Current:**
```python
label = getattr(meta, 'label', None) or getattr(meta, 'display_name', None) or ""
if label == "Lumen":
    return True
```

**Target:**
```python
tags = meta.tags or []
if "protected" in tags or "persistent" in tags:
    return True
```

**Migration:** Before landing code change — add `persistent` and `protected` tags to Lumen, Vigil, Sentinel via `mcp__unitares-governance__agent(action="update", agent_id=..., tags=[...])`. Verify with `agent(action="get")`.

#### A3b — Silence-interval dict (`src/background_tasks.py:622-626`)

**Current:**
```python
_PERSISTENT_AGENT_INTERVALS = {
    "Vigil": 1800,
    "Lumen": 300,
    "Sentinel": 600,
}
```

**Target:** Drive intervals from agent tags. Recommended scheme: tags like `cadence.5min`, `cadence.10min`, `cadence.30min`.

```python
_INTERVAL_FROM_TAG = {
    "cadence.1min": 60,
    "cadence.5min": 300,
    "cadence.10min": 600,
    "cadence.30min": 1800,
}

def _get_expected_interval(meta) -> int | None:
    for tag in (meta.tags or []):
        if tag in _INTERVAL_FROM_TAG:
            return _INTERVAL_FROM_TAG[tag]
    if "embodied" in (meta.tags or []) or "autonomous" in (meta.tags or []):
        return 300  # sensible default
    return None
```

**Migration:** Tag Lumen with `cadence.5min`, Sentinel with `cadence.10min`, Vigil with `cadence.30min` before landing code.

#### A3c — HTTP API poll map (`src/http_api.py:1079`)

```python
"lumen": 10 * 60,
```

Share the same `_INTERVAL_FROM_TAG` source used in A3b. Read intervals dynamically from the agent's tags at query time instead of hardcoding a dict keyed on name.

#### A3d — Dashboard filter (`src/mcp_handlers/admin/dashboard.py:43`)

**Current (comment reveals the logic):** "Filter: recent_days=1 by default (show today's agents + Lumen)".

**Target:** Default filter shows agents active in the last N days + any agent tagged `persistent`. Name-based exception removed.

**Tests (A3 group):**
- `test_is_agent_protected_by_persistent_tag` — agent with `persistent` tag is protected without a name match.
- `test_silence_interval_by_cadence_tag` — agent with `cadence.5min` gets 300s, no hardcoded name.
- `test_dashboard_filter_includes_persistent_agents` — persistent-tagged agents appear in the default filter even when outside the recent-days window.

**Risk:** Low-but-visible. If A3a lands before Lumen/Vigil/Sentinel have the tags, a cleanup cycle could archive them. **Tag first, code second.**

**Commit boundaries:** 3 commits — (1) tag updates for Lumen/Vigil/Sentinel, (2) A3a + A3b + A3c code change sharing `_INTERVAL_FROM_TAG`, (3) A3d dashboard filter.

---

### A4 — Note the fate of deprecated `pi_*` aliases

`src/mcp_handlers/tool_stability.py:245-269` has 12 deprecated `pi_*` → `pi` aliases. These die naturally in Phase B options B1/B3; they survive B2.

**Phase A action:** Add a single comment at the top of the alias block:

```python
# The `pi_*` aliases below are pending removal per the Lumen-decoupling plan
# (docs/specs/2026-04-17-lumen-decoupling-design.md). Final disposition depends
# on the Phase B architectural decision (B1/B2/B3). Do not add new `pi_*` aliases.
```

**Commit boundary:** 1 commit (can be folded into A2 if preferred).

---

## Phase B — Plugin Extraction (blocked on B1/B2/B3 decision)

Not planned in detail until the architectural decision lands. Sketches only:

**If B3 (unidirectional, recommended pending audit):**
1. Audit callers of `pi(action=...)` and the deprecated `pi_*` aliases across Kenny's MCP client configs, Discord dispatch, Sentinel, Watcher, Vigil.
2. For each real caller, migrate to a direct anima-mcp connection.
3. Delete `pi_orchestration.py`, the `pi` branch in `consolidated.py`, the 12 aliases in `tool_stability.py`, and the `pi` entries in `tool_schemas.py`, `tool_modes.py`, `tool_introspection.py`, `mcp_handlers/__init__.py`.
4. Update observability `__init__.py` docstring to drop "Pi orchestration".

**If B1 (plugin API):**
1. Write a separate design doc for the tool-provider plugin contract.
2. Implement plugin loader in unitares (likely `UNITARES_PLUGINS=module1,module2` env var; each module exposes `register_tools(mcp)`).
3. Create `unitares-anima-bridge` repo; move the three modules there; depend on unitares + `anima-mcp` types.
4. Delete corresponding code from unitares.

**If B2 (feature flag, short-term):**
1. Wrap `pi_*` imports in `src/mcp_handlers/__init__.py` and tool registration in `src/mcp_handlers/consolidated.py` with `if os.environ.get("UNITARES_ANIMA_BRIDGE") == "1": ...`.
2. Document flag in `docs/operations/SECRETS_AND_ENV.md`.
3. Ship. Revisit in 3 months.

---

## Sequencing

```
  A1 (sensor_eisv push)  ──┐
  A2 (comment scrub)     ──┼── Phase A — land in any order, ~1 day
  A3 (tag metadata)      ──┤
  A4 (alias note)        ──┘
                            
         ↓ decide B1 / B2 / B3
                            
  Phase B — separate follow-up (plugin / flag / delete)
```

**Ordering constraint inside A3:** Always tag before code change (see A3 migration notes).

**Ordering constraint inside A1:** Unitares-side `agent_state` routing first → anima-mcp push second → unitares cleanup third. Behavioral fallback covers the gap.

---

## Open Questions

1. **B1 vs B2 vs B3.** Blocked on a quick caller audit for `pi_*`. Kenny to answer before Phase B kicks off.
2. **Interval scheme in A3b** — is `cadence.Nmin` the right tag vocabulary, or is there already a convention in the governance agent tag taxonomy worth reusing?
3. **Mirror this plan into `anima-mcp/docs/`?** A1 has a Lumen-side change; a pointer from the Lumen repo would help future-you find this when working in anima-mcp. *(Done — see `anima-mcp/docs/plans/2026-04-17-unitares-decoupling-pointer.md`.)*
4. **`eisv_sync_task` removal vs retention** — the CLAUDE.md in anima-mcp describes the broker as the primary UNITARES caller with server as fallback. Worth confirming the broker's push in A1 is reliable enough to delete the Mac-side pull entirely, or whether to keep it as a belt-and-suspenders sync for a release cycle.

---

## Appendix — Cross-repo references

- **Unitares** `src/mcp_handlers/updates/phases.py:541-550` — the `sensor_buffer` leak originally flagged during design.
- **Unitares** `src/governance_monitor.py:395-405, 809-814` — the generic `sensor_eisv` reader that makes A1 trivial on the unitares side.
- **Anima-mcp** `src/anima_mcp/unitares_bridge.py:410-418` — the push point that needs `sensor_eisv` added.
- **Anima-mcp** `eisv_mapper.py` — existing anima→EISV mapping (used for governance reporting today); should supply the `sensor_eisv` value.
