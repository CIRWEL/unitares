# Remove Neighbor Coupling Dead Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the dormant neighbor-pressure coupling scaffolding from both `unitares` and `unitares-core` so the governance code reflects the actual (uncoupled) runtime behavior.

**Architecture:** Neighbor pressure was disabled in production at `src/mcp_handlers/updates/phases.py:1005-1007` (the only call site of `maybe_apply_neighbor_pressure` was removed, replaced with a comment). The supporting scaffolding — `AdaptiveGovernor.apply_neighbor_pressure` / `decay_neighbor_pressure`, the `neighbor_pressure` / `agents_in_resonance` state fields, and the `cirs.hooks` neighbor-pressure plumbing — remains as dead code plus tests. This plan removes it. Serialization is forward-compatible: `GovernorState.from_dict` already ignores unknown keys, so old persisted snapshots that still carry `neighbor_pressure` keep loading.

**Tech Stack:** Python 3.12, pytest, two repos (`unitares`, `unitares-core` as an installed compiled wheel that is also symlinked for dev).

**Prerequisites (not tasks):**
- Work in a worktree: `cd /Users/cirwel/projects/unitares && git worktree add .worktrees/remove-neighbor-coupling -b remove-neighbor-coupling`. `unitares-core` doesn't need a worktree (it's master-only and uncommitted-clean per initial check); create a branch in place: `cd /Users/cirwel/projects/unitares-core && git checkout -b remove-neighbor-coupling`.
- `governance_core` is the dev symlink `unitares/governance_core -> unitares-core/governance_core`, so the unitares test suite exercises the live unitares-core code.

---

## File Structure

**Files modified (7):**

- `unitares-core/governance_core/adaptive_governor.py` — delete `apply_neighbor_pressure` + `decay_neighbor_pressure` methods, `neighbor_pressure` + `agents_in_resonance` state fields, their `to_dict`/`from_dict`/`_build_result` entries, line 22 docstring bullet, and lines 295-297 pressure adjustment.
- `unitares-core/tests/test_adaptive_governor.py` — delete `TestNeighborPressure` class, delete `test_neighbor_pressure_tightens_thresholds`, update `test_default_initialization` (drop the `neighbor_pressure` assert), update `test_update_returns_expected_dict` (drop `neighbor_pressure`/`agents_in_resonance` from `expected_keys`).
- `unitares/src/mcp_handlers/cirs/hooks.py` — delete `auto_emit_coherence_reports` (lines 163-207), `maybe_apply_neighbor_pressure` (lines 209-247), `_lookup_similarity` (lines 249-264), and update the module docstring.
- `unitares/src/mcp_handlers/cirs/protocol.py` — drop `maybe_apply_neighbor_pressure`, `_lookup_similarity` from the `.hooks` import block.
- `unitares/src/mcp_handlers/cirs/__init__.py` — drop `maybe_apply_neighbor_pressure` from imports and `__all__`.
- `unitares/src/mcp_handlers/__init__.py` — drop `maybe_apply_neighbor_pressure` from the `from .cirs import (...)` block.
- `unitares/src/mcp_handlers/updates/phases.py` — delete the "CIRS: Neighbor pressure disabled" tombstone comment at lines 1005-1007.
- `unitares/tests/test_cirs_resonance_wiring.py` — delete the `TestMaybeApplyNeighborPressure` class and the neighbor-pressure tail of `TestResonanceFullLoop.test_full_resonance_propagation_loop` (Phases 3-6); remove now-unused imports (`maybe_apply_neighbor_pressure`, `_coherence_report_buffer`).
- `unitares/docs/CHANGELOG.md` — add a Removed entry under the next release block.

**Memory update (outside both repos):**
- `/Users/cirwel/.claude/projects/-Users-cirwel/memory/project_neighbor-coupling.md` — mark structurally removed, update `MEMORY.md` index line accordingly.

---

### Task 1: Delete unitares test coverage for neighbor pressure

**Files:**
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/tests/test_cirs_resonance_wiring.py`

- [ ] **Step 1: Remove `TestMaybeApplyNeighborPressure` class**

Open `tests/test_cirs_resonance_wiring.py`. Delete the entire class starting at `class TestMaybeApplyNeighborPressure:` (line 119) through the end of its last method `test_decays_pressure_on_stability_restored` (line 243). Also remove the blank line separator before the next class.

- [ ] **Step 2: Trim `TestResonanceFullLoop.test_full_resonance_propagation_loop`**

In the same file, in `class TestResonanceFullLoop`, edit `test_full_resonance_propagation_loop` (starts around line 253). Keep Phases 1-2 (drive Agent A into resonance, emit the signal). Delete Phase 3 onward (from the comment `# Phase 3: Set up similarity between A and B` through the end of the method, including the pressure-propagation and STABILITY_RESTORED assertions that reference `gov_b.state.neighbor_pressure`). Replace with a single trailing line:

```python
        # Coupling is structurally removed — emission is the full loop we cover here.
```

Drop `gov_b` from the setup if it becomes unused (check after editing).

- [ ] **Step 3: Clean up imports**

At the top of the file, edit the import block to remove `maybe_apply_neighbor_pressure` and `_coherence_report_buffer` (they are no longer referenced after Steps 1-2). Keep the other names.

Before:
```python
from src.mcp_handlers.cirs.protocol import (
    maybe_emit_resonance_signal,
    maybe_apply_neighbor_pressure,
    _resonance_alert_buffer,
    _coherence_report_buffer,
    _get_recent_resonance_signals,
    _emit_resonance_alert,
    _emit_stability_restored,
    ResonanceAlert,
    StabilityRestored,
)
```

After:
```python
from src.mcp_handlers.cirs.protocol import (
    maybe_emit_resonance_signal,
    _resonance_alert_buffer,
    _get_recent_resonance_signals,
    _emit_resonance_alert,
    _emit_stability_restored,
    ResonanceAlert,
    StabilityRestored,
)
```

Also remove `_coherence_report_buffer.clear()` from any remaining `setup_method` bodies (e.g. `TestResonanceFullLoop.setup_method`). Leave `_resonance_alert_buffer.clear()`.

- [ ] **Step 4: Verify the trimmed file still parses and collects**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && pytest tests/test_cirs_resonance_wiring.py --collect-only -q`
Expected: all remaining tests collect cleanly, no ImportError, no references to the removed names.

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git add tests/test_cirs_resonance_wiring.py
git commit -m "test(cirs): drop neighbor-pressure test coverage

Neighbor pressure was disabled in production at phases.py:1005. The
scaffolding is dead code; removing its tests first so the subsequent
deletions don't break imports."
```

---

### Task 2: Delete neighbor-pressure hooks in unitares

**Files:**
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/src/mcp_handlers/cirs/hooks.py`

- [ ] **Step 1: Remove `maybe_apply_neighbor_pressure`, `auto_emit_coherence_reports`, `_lookup_similarity`**

Open `src/mcp_handlers/cirs/hooks.py`. Delete three functions in full:
- `auto_emit_coherence_reports` (lines 163-207) — exists only to feed neighbor pressure
- `maybe_apply_neighbor_pressure` (lines 209-247)
- `_lookup_similarity` (lines 249-264) — only used by `maybe_apply_neighbor_pressure`

Keep `maybe_emit_void_alert`, `auto_emit_state_announce`, `maybe_emit_resonance_signal` untouched.

- [ ] **Step 2: Update the module docstring**

Replace lines 1-6:
```python
"""
CIRS auto-emit hooks — called from process_agent_update.

Houses maybe_emit_void_alert, auto_emit_state_announce,
maybe_emit_resonance_signal, maybe_apply_neighbor_pressure.
"""
```

With:
```python
"""
CIRS auto-emit hooks — called from process_agent_update.

Houses maybe_emit_void_alert, auto_emit_state_announce,
maybe_emit_resonance_signal.
"""
```

- [ ] **Step 3: Drop now-unused imports**

After removing the three functions, `_get_recent_resonance_signals` and `_coherence_report_buffer` are no longer referenced in this file. Edit the `.storage` import block to drop them:

Before:
```python
from .storage import (
    _store_void_alert, _store_state_announce,
    _emit_resonance_alert, _emit_stability_restored,
    _get_recent_resonance_signals, _coherence_report_buffer,
)
```

After:
```python
from .storage import (
    _store_void_alert, _store_state_announce,
    _emit_resonance_alert, _emit_stability_restored,
)
```

- [ ] **Step 4: Verify the module still imports**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && python -c "from src.mcp_handlers.cirs import hooks; print([n for n in dir(hooks) if not n.startswith('_')])"`
Expected: prints a list that does NOT contain `maybe_apply_neighbor_pressure`, `auto_emit_coherence_reports`, or `_lookup_similarity`. No ImportError.

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git add src/mcp_handlers/cirs/hooks.py
git commit -m "refactor(cirs): delete neighbor-pressure hooks

Remove maybe_apply_neighbor_pressure, auto_emit_coherence_reports,
and _lookup_similarity. These served only the disabled neighbor
coupling path (phases.py:1005). Exports fixed in the next commit."
```

---

### Task 3: Drop the removed names from cirs/protocol and package exports

**Files:**
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/src/mcp_handlers/cirs/protocol.py`
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/src/mcp_handlers/cirs/__init__.py`
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/src/mcp_handlers/__init__.py`

- [ ] **Step 1: Edit `cirs/protocol.py` imports from `.hooks`**

Find the `from .hooks import (...)` block at around line 88. Remove `maybe_apply_neighbor_pressure` and `_lookup_similarity`.

Before:
```python
from .hooks import (
    maybe_emit_void_alert,
    auto_emit_state_announce,
    maybe_emit_resonance_signal,
    maybe_apply_neighbor_pressure,
    _lookup_similarity,
)
```

After:
```python
from .hooks import (
    maybe_emit_void_alert,
    auto_emit_state_announce,
    maybe_emit_resonance_signal,
)
```

- [ ] **Step 2: Edit `cirs/__init__.py`**

Remove `maybe_apply_neighbor_pressure` from both the `from .protocol import (...)` list and the `__all__` list. After the edit the file should have 9 names in `__all__` (was 10).

- [ ] **Step 3: Edit `mcp_handlers/__init__.py`**

Find the `from .cirs import (...)` block near line 118. Remove the `maybe_apply_neighbor_pressure,  # Hook for process_agent_update` line.

- [ ] **Step 4: Verify package imports still work**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && python -c "from src.mcp_handlers import cirs; assert not hasattr(cirs, 'maybe_apply_neighbor_pressure'); print('ok')"`
Expected: prints `ok`.

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && python -c "import src.mcp_handlers; print('ok')"`
Expected: prints `ok` (the top-level handlers package imports cleanly).

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git add src/mcp_handlers/cirs/protocol.py src/mcp_handlers/cirs/__init__.py src/mcp_handlers/__init__.py
git commit -m "refactor(cirs): drop maybe_apply_neighbor_pressure from public exports"
```

---

### Task 4: Remove the tombstone comment in phases.py

**Files:**
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/src/mcp_handlers/updates/phases.py`

- [ ] **Step 1: Delete the three-line comment**

Open `src/mcp_handlers/updates/phases.py`. Find lines 1005-1007:

```python
    # CIRS: Neighbor pressure disabled — caused cross-agent EISV convergence,
    # destroying individual diagnostic value by coupling all agents toward
    # a shared equilibrium via governor threshold tightening.
```

Delete these three lines. Keep surrounding blank lines tidy (one blank between the preceding `# CIRS: Resonance signal` block's `logger.debug` line and the next `# CIRS: Persist resonance event` block).

- [ ] **Step 2: Run the unitares test suite**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && ./scripts/dev/test-cache.sh --fresh`
Expected: full suite passes. (This exercises `governance_core` via the dev symlink — at this point `unitares-core` still has the `apply_neighbor_pressure` method, so nothing the handlers do calls it, and the passing run proves removal of the caller side was clean.)

If any test fails: read the error. Do NOT paper over — identify whether the failure is a genuine regression (fix it) or stale import elsewhere (add it to this task).

- [ ] **Step 3: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git add src/mcp_handlers/updates/phases.py
git commit -m "chore(cirs): drop the neighbor-pressure tombstone comment

Caller has been absent for some time; the comment is no longer
guarding against accidental reintroduction since the scaffolding
it referenced is also gone."
```

---

### Task 5: Delete unitares-core test coverage for neighbor pressure

**Files:**
- Modify: `/Users/cirwel/projects/unitares-core/tests/test_adaptive_governor.py`

- [ ] **Step 1: Delete the `TestNeighborPressure` class**

Open `tests/test_adaptive_governor.py`. Delete the class header comment block (lines ~628-630) and the `TestNeighborPressure` class (lines 633-697) in full. The class ends at `test_pressure_affects_update`.

- [ ] **Step 2: Delete `test_neighbor_pressure_tightens_thresholds`**

In the same file, find `test_neighbor_pressure_tightens_thresholds` (lines 270-286). Delete the entire method plus its preceding blank line.

- [ ] **Step 3: Trim `test_default_initialization`**

Find `test_default_initialization` (around line 62). Remove the line `assert state.neighbor_pressure == 0.0` (line 74). The other initialization assertions stay.

- [ ] **Step 4: Trim `test_update_returns_expected_dict` expected keys**

In the same test class, find the `expected_keys = { ... }` set (lines 255-259). Remove `"neighbor_pressure"` and `"agents_in_resonance"`.

Before:
```python
        expected_keys = {
            "verdict", "tau", "beta", "tau_default", "beta_default",
            "phase", "controller", "oi", "flips", "resonant", "trigger",
            "response_tier", "neighbor_pressure", "agents_in_resonance",
        }
```

After:
```python
        expected_keys = {
            "verdict", "tau", "beta", "tau_default", "beta_default",
            "phase", "controller", "oi", "flips", "resonant", "trigger",
            "response_tier",
        }
```

- [ ] **Step 5: Verify the file still parses**

Run: `cd /Users/cirwel/projects/unitares-core && pytest tests/test_adaptive_governor.py --collect-only -q`
Expected: remaining tests collect; no references to deleted names.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares-core
git add tests/test_adaptive_governor.py
git commit -m "test(governor): drop neighbor-pressure test coverage

The coupling path is disabled in production (see unitares
phases.py commit). Removing tests first so the next commit
can delete the method/state fields without leaving orphans."
```

---

### Task 6: Remove neighbor-pressure from `AdaptiveGovernor`

**Files:**
- Modify: `/Users/cirwel/projects/unitares-core/governance_core/adaptive_governor.py`

- [ ] **Step 1: Renumber the docstring update-cycle list**

Find the update-cycle list in the module docstring (lines 21-27). Delete step 6 (neighbor pressure) and renumber steps 7-10 down to 6-9.

Before:
```python
  5. Apply bounded adjustment: tau/beta clamped to [floor, ceiling]
  6. Include neighbor pressure (tightens: tau gets higher, beta gets lower)
  7. Update oscillation metrics (OI via incremental EMA, flips, resonance)
  8. Threshold decay when stable (OI < threshold and flips == 0)
  9. Store controller output for observability
  10. Make verdict and return result dict
```

After:
```python
  5. Apply bounded adjustment: tau/beta clamped to [floor, ceiling]
  6. Update oscillation metrics (OI via incremental EMA, flips, resonance)
  7. Threshold decay when stable (OI < threshold and flips == 0)
  8. Store controller output for observability
  9. Make verdict and return result dict
```

- [ ] **Step 2: Remove state fields**

In `GovernorState`, delete lines 119-121:
```python
    # Neighbor pressure
    neighbor_pressure: float = 0.0
    agents_in_resonance: int = 0
```

- [ ] **Step 3: Remove `to_dict` entries**

In `GovernorState.to_dict` (around lines 153-154), remove:
```python
            "neighbor_pressure": self.neighbor_pressure,
            "agents_in_resonance": self.agents_in_resonance,
```

- [ ] **Step 4: Remove `from_dict` entries**

In `GovernorState.from_dict`:
- Remove `"neighbor_pressure",` from the tuple at line 168.
- Remove the line `state.agents_in_resonance = int(data.get("agents_in_resonance", 0))` at line 175.

Forward-compat guaranteed: `from_dict` only `setattr`s keys that are in the tuple; unknown keys in old persisted data are ignored silently.

- [ ] **Step 5: Remove the pressure adjustment in `update()`**

Delete lines 295-297:
```python
        # Include neighbor pressure (tightens: tau gets HIGHER, beta gets LOWER)
        adjustment_tau += self.state.neighbor_pressure
        adjustment_beta -= self.state.neighbor_pressure
```

(The adjustment variables `adjustment_tau`/`adjustment_beta` are still used on the following lines — just without the pressure term.)

- [ ] **Step 6: Remove `apply_neighbor_pressure` and `decay_neighbor_pressure` methods**

Delete lines 424-456 inclusive (both method definitions plus their surrounding blank lines). The next method in the file is `_update_oscillation`.

- [ ] **Step 7: Remove `_build_result` entries**

In `_build_result` (around lines 545-546), remove:
```python
            "neighbor_pressure": self.state.neighbor_pressure,
            "agents_in_resonance": self.state.agents_in_resonance,
```

- [ ] **Step 8: Run the unitares-core test suite**

Run: `cd /Users/cirwel/projects/unitares-core && pytest tests/ -x`
Expected: all tests pass. Deleted tests are gone, remaining tests exercise `AdaptiveGovernor.update()` without neighbor pressure and should produce identical numerical results (the pressure term was multiplying a zero field, but we've removed the code path entirely).

- [ ] **Step 9: Commit**

```bash
cd /Users/cirwel/projects/unitares-core
git add governance_core/adaptive_governor.py
git commit -m "refactor(governor): remove neighbor-pressure coupling

Structural removal of apply_neighbor_pressure / decay_neighbor_pressure
methods, the neighbor_pressure / agents_in_resonance state fields, and
the update()-loop injection.

The production call site was disabled in unitares phases.py (the
comment at line 1005 cited cross-agent EISV convergence as the
reason). Since then the path has been cold: state.neighbor_pressure
was always 0.0 in production, so the adjustment term was always a
no-op. This commit deletes the scaffolding.

Serialization is forward-compatible: GovernorState.from_dict
silently ignores the old neighbor_pressure / agents_in_resonance
keys in persisted snapshots."
```

---

### Task 7: Cross-repo integration check

**Files:** none modified

- [ ] **Step 1: Run the full unitares suite against the updated governance_core**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && ./scripts/dev/test-cache.sh --fresh`
Expected: pass. This is the load-bearing gate. The dev symlink means unitares' handlers now import the slimmed-down `AdaptiveGovernor`. Any stale `.neighbor_pressure` access inside the monitor/serialization path would surface here.

If this fails: likely cause is a hidden `.neighbor_pressure` access via `GovernorState.to_dict()` consumers (dashboard JSON payloads, persisted state reloads). Grep for `neighbor_pressure` inside `/Users/cirwel/projects/unitares/src` and `/Users/cirwel/projects/unitares/agents` and fix each site.

- [ ] **Step 2: Grep for any lingering references**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling && grep -rn "neighbor_pressure\|agents_in_resonance\|apply_neighbor_pressure\|decay_neighbor_pressure\|_lookup_similarity\|auto_emit_coherence_reports" src/ tests/ agents/ docs/plans/ || echo NONE`
Expected: `NONE`. (CHANGELOG updated in Task 8 will still show the old entry — that's historical, keep it.)

Run: `cd /Users/cirwel/projects/unitares-core && grep -rn "neighbor_pressure\|agents_in_resonance\|apply_neighbor_pressure\|decay_neighbor_pressure" governance_core/ tests/ || echo NONE`
Expected: `NONE`.

---

### Task 8: Update CHANGELOG + memory

**Files:**
- Modify: `/Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling/docs/CHANGELOG.md`
- Modify: `/Users/cirwel/.claude/projects/-Users-cirwel/memory/project_neighbor-coupling.md`
- Modify: `/Users/cirwel/.claude/projects/-Users-cirwel/memory/MEMORY.md`

- [ ] **Step 1: Add CHANGELOG entry**

Open `docs/CHANGELOG.md`. Add a new entry at the top of the currently-unreleased section (or create a dated block above the existing entries) under a `### Removed` heading:

```markdown
### Removed — Neighbor coupling (2026-04-17)
- Deleted `AdaptiveGovernor.apply_neighbor_pressure` / `decay_neighbor_pressure` and the `neighbor_pressure` / `agents_in_resonance` state fields.
- Deleted `cirs.hooks.maybe_apply_neighbor_pressure`, `auto_emit_coherence_reports`, `_lookup_similarity` and all re-exports.
- Production call site has been disabled since `phases.py:1005` landed. This commit removes the dormant scaffolding so the code reflects actual runtime behavior. Rationale: agent-to-agent threshold coupling undermined independent per-agent judgment and produced correlated EISV drift that confounded fleet anomaly detection.
- Forward-compatible: persisted `GovernorState` snapshots carrying `neighbor_pressure` keys continue to load (unknown keys ignored).
```

- [ ] **Step 2: Rewrite the neighbor-coupling memory**

Replace the full contents of `/Users/cirwel/.claude/projects/-Users-cirwel/memory/project_neighbor-coupling.md` with:

```markdown
---
name: Neighbor coupling structurally removed
description: governance_core no longer has agent-to-agent coupling; removal shipped 2026-04-17. Fleet lockstep findings are not caused by coupling.
type: project
---
Neighbor coupling was structurally removed from `governance_core` on 2026-04-17. `AdaptiveGovernor.apply_neighbor_pressure` / `decay_neighbor_pressure`, the `neighbor_pressure` / `agents_in_resonance` state fields, and the `cirs.hooks` plumbing are gone. The production call site in `unitares/src/mcp_handlers/updates/phases.py` had already been disabled earlier; this cleanup deleted the dormant scaffolding.

**Why:** Coupling silently herded similar agents into the same verdict, destroyed the meaning of "coordinated drift" findings from Sentinel, and created a feedback channel (A → B via RESONANCE_ALERT + coherence similarity) that made per-agent state hard to interpret.

**How to apply:** If you see Sentinel report "coordinated degradation" / "3 agents drifting in lockstep", it is NOT caused by governor coupling. Real candidates: (1) sensor anchoring (`k_anchor=0.1`) when multiple agents share a `sensor_eisv` source, (2) the Sentinel fleet detector at `agents/sentinel/agent.py:181-204` measures each agent's drop independently and fires on ≥3 simultaneous drops without requiring correlation — it triggers on independent degradations too, (3) shared environmental drivers. Do not add new agent-to-agent coupling primitives without re-opening this decision.
```

- [ ] **Step 3: Update `MEMORY.md` index line**

Open `/Users/cirwel/.claude/projects/-Users-cirwel/memory/MEMORY.md`. Find the existing line:

```markdown
- [Neighbor coupling may still be active](project_neighbor-coupling.md) — EISV dynamics may still couple agents; coordinated movement is expected, not anomalous
```

Replace with:

```markdown
- [Neighbor coupling structurally removed](project_neighbor-coupling.md) — removed 2026-04-17; Sentinel lockstep findings come from sensor anchoring or independent drops, not coupling
```

- [ ] **Step 4: Commit the CHANGELOG (memory is not version-controlled)**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git add docs/CHANGELOG.md
git commit -m "docs(changelog): note neighbor-coupling removal"
```

---

### Task 9: Finish the branch

**Files:** none modified

- [ ] **Step 1: Push both branches and open PRs**

Decide with the user whether to bundle into one PR (cross-repo) or two. Default to two PRs — one per repo — since the repos are independent. Order the merges: `unitares-core` first (slim method surface), then `unitares` (drop callers). Actually the commits are already ordered so that each repo passes tests independently regardless of merge order.

Confirm with user before pushing. If approved:

```bash
cd /Users/cirwel/projects/unitares-core
git push -u origin remove-neighbor-coupling
gh pr create --title "Remove neighbor-pressure coupling" --body "Dormant scaffolding removal. Production call site has been disabled since phases.py:1005 landed; see CHANGELOG in the companion unitares PR for the full rationale. Forward-compat: GovernorState.from_dict ignores unknown keys."

cd /Users/cirwel/projects/unitares/.worktrees/remove-neighbor-coupling
git push -u origin remove-neighbor-coupling
gh pr create --title "Remove neighbor-pressure coupling (caller + tests + docs)" --body "Companion to the unitares-core PR. Deletes cirs.hooks neighbor-pressure plumbing, tombstone comment in phases.py, related tests, and adds CHANGELOG entry."
```

- [ ] **Step 2: Clean up the worktree after merge**

After the unitares PR merges:

```bash
cd /Users/cirwel/projects/unitares
git worktree remove .worktrees/remove-neighbor-coupling
git branch -d remove-neighbor-coupling
```
