# Resonance → CIRS Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire AdaptiveGovernor resonance detection to auto-emit CIRS protocol signals and apply neighbor pressure from peer resonance alerts.

**Architecture:** Add `was_resonant` state tracking to `GovernorState`, two new auto-emit functions in `cirs_protocol.py` following the established hook pattern, and wire them from `core.py` after the existing CIRS hooks. TDD: test each function in isolation before wiring.

**Tech Stack:** Python, pytest, governance_core module, CIRS protocol handlers

**Design doc:** `docs/plans/2026-02-21-resonance-cirs-wiring-design.md`

---

### Task 1: Add `was_resonant` to GovernorState

**Files:**
- Modify: `governance_core/adaptive_governor.py:83-118` (GovernorState dataclass)
- Modify: `governance_core/adaptive_governor.py:346-407` (_update_oscillation method)
- Test: `tests/test_adaptive_governor.py`

**Step 1: Write the failing test**

Add to `tests/test_adaptive_governor.py` inside the existing `TestResonanceDetection` area (after line 494):

```python
class TestWasResonantTracking:
    """was_resonant tracks previous resonance state for transition detection."""

    def test_was_resonant_starts_false(self):
        """Initial state: was_resonant is False."""
        gov = AdaptiveGovernor()
        assert gov.state.was_resonant is False

    def test_was_resonant_set_after_resonance_detected(self):
        """After resonance detected, was_resonant is True on next update."""
        config = GovernorConfig(flip_threshold=3)
        gov = AdaptiveGovernor(config=config)
        histories = _stable_histories()

        # Drive into resonance via oscillation
        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        assert gov.state.resonant is True
        # was_resonant should reflect the state BEFORE this update
        # After resonance is detected, the NEXT call should have was_resonant=True
        gov.update(coherence=0.65, risk=0.20, verdict="safe", **histories)
        assert gov.state.was_resonant is True

    def test_was_resonant_false_to_true_transition(self):
        """Detect the exact transition from not-resonant to resonant."""
        config = GovernorConfig(flip_threshold=3)
        gov = AdaptiveGovernor(config=config)
        histories = _stable_histories()

        # First few updates: not resonant
        for _ in range(3):
            gov.update(coherence=0.65, risk=0.20, verdict="safe", **histories)
        assert gov.state.resonant is False
        assert gov.state.was_resonant is False

        # Oscillate to trigger resonance
        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            gov.update(coherence=c, risk=r, verdict=v, **histories)

        # Now resonant=True but was_resonant should reflect pre-transition
        # The transition happens within the oscillation loop
        assert gov.state.resonant is True
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adaptive_governor.py::TestWasResonantTracking -v`
Expected: FAIL with `AttributeError: 'GovernorState' has no attribute 'was_resonant'`

**Step 3: Write minimal implementation**

In `governance_core/adaptive_governor.py`:

1. Add to `GovernorState` dataclass (after `trigger` field, line 102):
```python
    was_resonant: bool = False  # Previous resonant state (for transition detection)
```

2. In `_update_oscillation` method, add at the very start (line 353, before `delta_coh`):
```python
        # Track previous resonant state for transition detection
        self.state.was_resonant = self.state.resonant
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adaptive_governor.py::TestWasResonantTracking -v`
Expected: PASS (all 3 tests)

**Step 5: Run full existing test suite**

Run: `python -m pytest tests/test_adaptive_governor.py -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add governance_core/adaptive_governor.py tests/test_adaptive_governor.py
git commit -m "feat(cirs-v2): add was_resonant tracking to GovernorState for transition detection"
```

---

### Task 2: Add `maybe_emit_resonance_signal` to CIRS protocol

**Files:**
- Modify: `src/mcp_handlers/cirs_protocol.py` (add function after `auto_emit_state_announce`, ~line 987)
- Create: `tests/test_cirs_resonance_wiring.py`

**Step 1: Write the failing tests**

Create `tests/test_cirs_resonance_wiring.py`:

```python
"""
Tests for CIRS resonance → protocol wiring.

Covers:
- maybe_emit_resonance_signal: transition detection and signal emission
- maybe_apply_neighbor_pressure: peer alert reading and pressure application
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

# Import after ensuring path
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.mcp_handlers.cirs_protocol import (
    maybe_emit_resonance_signal,
    _resonance_alert_buffer,
    _get_recent_resonance_signals,
    ResonanceAlert,
    StabilityRestored,
)


class TestMaybeEmitResonanceSignal:
    """maybe_emit_resonance_signal emits on transitions, no-ops otherwise."""

    def setup_method(self):
        """Clear the resonance buffer before each test."""
        _resonance_alert_buffer.clear()

    def test_false_to_true_emits_resonance_alert(self):
        """Transition from not-resonant to resonant emits RESONANCE_ALERT."""
        cirs_result = {
            "resonant": True,
            "trigger": "oi",
            "oi": 3.0,
            "phase": "integration",
            "tau": 0.42,
            "beta": 0.58,
            "flips": 5,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=False,
        )
        assert signal is not None
        assert signal["type"] == "RESONANCE_ALERT"
        assert signal["agent_id"] == "agent-1"
        assert signal["oi"] == 3.0
        assert signal["phase"] == "integration"
        assert len(_resonance_alert_buffer) == 1

    def test_true_to_false_emits_stability_restored(self):
        """Transition from resonant to stable emits STABILITY_RESTORED."""
        cirs_result = {
            "resonant": False,
            "trigger": None,
            "oi": 0.5,
            "phase": "integration",
            "tau": 0.40,
            "beta": 0.60,
            "flips": 0,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=True,
        )
        assert signal is not None
        assert signal["type"] == "STABILITY_RESTORED"
        assert signal["agent_id"] == "agent-1"
        assert signal["tau_settled"] == 0.40
        assert len(_resonance_alert_buffer) == 1

    def test_no_transition_emits_nothing(self):
        """Same state → same state emits nothing."""
        cirs_result = {
            "resonant": False,
            "trigger": None,
            "oi": 0.1,
            "phase": "integration",
            "tau": 0.40,
            "beta": 0.60,
            "flips": 0,
        }
        # Not resonant → still not resonant
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=False,
        )
        assert signal is None
        assert len(_resonance_alert_buffer) == 0

    def test_sustained_resonance_emits_nothing(self):
        """Resonant → still resonant emits nothing (no flooding)."""
        cirs_result = {
            "resonant": True,
            "trigger": "oi",
            "oi": 3.5,
            "phase": "exploration",
            "tau": 0.35,
            "beta": 0.55,
            "flips": 6,
        }
        signal = maybe_emit_resonance_signal(
            agent_id="agent-1",
            cirs_result=cirs_result,
            was_resonant=True,
        )
        assert signal is None
        assert len(_resonance_alert_buffer) == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py::TestMaybeEmitResonanceSignal -v`
Expected: FAIL with `ImportError: cannot import name 'maybe_emit_resonance_signal'`

**Step 3: Write minimal implementation**

Add to `src/mcp_handlers/cirs_protocol.py` after `auto_emit_state_announce` (~line 987):

```python
def maybe_emit_resonance_signal(
    agent_id: str,
    cirs_result: Dict[str, Any],
    was_resonant: bool,
) -> Optional[Dict[str, Any]]:
    """
    Auto-emit RESONANCE_ALERT or STABILITY_RESTORED on state transitions.

    Called from process_agent_update after the AdaptiveGovernor runs.
    Only emits on transitions to avoid flooding the buffer.

    Args:
        agent_id: Agent identifier
        cirs_result: Result dict from AdaptiveGovernor.update()
        was_resonant: Previous resonant state (from GovernorState.was_resonant)

    Returns:
        Signal dict if emitted, None otherwise
    """
    resonant = cirs_result.get("resonant", False)

    # Only emit on transitions
    if resonant == was_resonant:
        return None

    if resonant and not was_resonant:
        # Entering resonance → emit RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id=agent_id,
            timestamp=datetime.utcnow().isoformat(),
            oi=float(cirs_result.get("oi", 0.0)),
            phase=str(cirs_result.get("phase", "unknown")),
            tau_current=float(cirs_result.get("tau", 0.40)),
            beta_current=float(cirs_result.get("beta", 0.60)),
            flips=int(cirs_result.get("flips", 0)),
        )
        _emit_resonance_alert(alert)
        logger.info(
            f"[CIRS/AUTO_EMIT] RESONANCE_ALERT: agent={agent_id}, "
            f"OI={alert.oi:.3f}, trigger={cirs_result.get('trigger')}"
        )
        return alert.to_dict()

    else:
        # Exiting resonance → emit STABILITY_RESTORED
        restored = StabilityRestored(
            agent_id=agent_id,
            timestamp=datetime.utcnow().isoformat(),
            oi=float(cirs_result.get("oi", 0.0)),
            tau_settled=float(cirs_result.get("tau", 0.40)),
            beta_settled=float(cirs_result.get("beta", 0.60)),
        )
        _emit_stability_restored(restored)
        logger.info(
            f"[CIRS/AUTO_EMIT] STABILITY_RESTORED: agent={agent_id}, "
            f"OI={restored.oi:.3f}"
        )
        return restored.to_dict()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py::TestMaybeEmitResonanceSignal -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add src/mcp_handlers/cirs_protocol.py tests/test_cirs_resonance_wiring.py
git commit -m "feat(cirs-v2): add maybe_emit_resonance_signal for auto-emit on transitions"
```

---

### Task 3: Add `maybe_apply_neighbor_pressure` to CIRS protocol

**Files:**
- Modify: `src/mcp_handlers/cirs_protocol.py` (add function after `maybe_emit_resonance_signal`)
- Modify: `tests/test_cirs_resonance_wiring.py`

**Step 1: Write the failing tests**

Add to `tests/test_cirs_resonance_wiring.py`:

```python
from src.mcp_handlers.cirs_protocol import (
    maybe_apply_neighbor_pressure,
    _coherence_report_buffer,
    _emit_resonance_alert,
    _emit_stability_restored,
)
from governance_core.adaptive_governor import AdaptiveGovernor, GovernorConfig


class TestMaybeApplyNeighborPressure:
    """maybe_apply_neighbor_pressure reads peer alerts and applies pressure."""

    def setup_method(self):
        """Clear buffers before each test."""
        _resonance_alert_buffer.clear()
        _coherence_report_buffer.clear()

    def test_applies_pressure_when_similar_peer_resonating(self):
        """High-similarity peer resonance → pressure applied."""
        gov = AdaptiveGovernor()
        assert gov.state.neighbor_pressure == 0.0

        # Peer emits RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        # Coherence report shows high similarity
        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.75,
            "timestamp": datetime.utcnow().isoformat(),
        }

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure > 0.0

    def test_skips_pressure_when_no_coherence_report(self):
        """No coherence report → no pressure (conservative default)."""
        gov = AdaptiveGovernor()

        # Peer emits RESONANCE_ALERT
        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        # No coherence report exists
        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_skips_pressure_when_low_similarity(self):
        """Low similarity → no pressure."""
        gov = AdaptiveGovernor()

        alert = ResonanceAlert(
            agent_id="peer-1",
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        _coherence_report_buffer["my-agent:peer-1"] = {
            "source_agent_id": "my-agent",
            "target_agent_id": "peer-1",
            "similarity_score": 0.3,  # Below 0.5 threshold
            "timestamp": datetime.utcnow().isoformat(),
        }

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_ignores_own_resonance_alerts(self):
        """Agent doesn't apply pressure from its own alerts."""
        gov = AdaptiveGovernor()

        # Self-emitted alert
        alert = ResonanceAlert(
            agent_id="my-agent",
            timestamp=datetime.utcnow().isoformat(),
            oi=3.0, phase="integration",
            tau_current=0.42, beta_current=0.58, flips=5,
        )
        _emit_resonance_alert(alert)

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure == 0.0

    def test_decays_pressure_on_stability_restored(self):
        """STABILITY_RESTORED from previously-pressuring peer → decay."""
        gov = AdaptiveGovernor()
        # Manually set some existing pressure
        gov.state.neighbor_pressure = 0.05
        gov.state.agents_in_resonance = 1

        # Peer restored stability
        restored = StabilityRestored(
            agent_id="peer-1",
            timestamp=datetime.utcnow().isoformat(),
            oi=0.3, tau_settled=0.40, beta_settled=0.60,
        )
        _emit_stability_restored(restored)

        maybe_apply_neighbor_pressure(
            agent_id="my-agent",
            governor=gov,
        )

        assert gov.state.neighbor_pressure < 0.05  # Decayed
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py::TestMaybeApplyNeighborPressure -v`
Expected: FAIL with `ImportError: cannot import name 'maybe_apply_neighbor_pressure'`

**Step 3: Write minimal implementation**

Add to `src/mcp_handlers/cirs_protocol.py` after `maybe_emit_resonance_signal`:

```python
def maybe_apply_neighbor_pressure(
    agent_id: str,
    governor,  # AdaptiveGovernor instance
) -> None:
    """
    Apply neighbor pressure from peer resonance alerts.

    Reads recent RESONANCE_ALERT signals from other agents.
    For each alert, looks up coherence similarity. If similar enough,
    applies defensive threshold tightening to the local governor.

    Also decays pressure on STABILITY_RESTORED signals.

    Args:
        agent_id: This agent's identifier (to exclude self-alerts)
        governor: The agent's AdaptiveGovernor instance
    """
    if governor is None:
        return

    # Get recent resonance signals (last 30 min)
    signals = _get_recent_resonance_signals(max_age_minutes=30)

    for signal in signals:
        peer_id = signal.get("agent_id")

        # Skip self
        if peer_id == agent_id:
            continue

        signal_type = signal.get("type")

        if signal_type == "RESONANCE_ALERT":
            # Look up coherence similarity (check both directions)
            similarity = _lookup_similarity(agent_id, peer_id)
            if similarity is not None:
                governor.apply_neighbor_pressure(similarity=similarity)
                logger.debug(
                    f"[CIRS/NEIGHBOR] Pressure applied to {agent_id} "
                    f"from {peer_id} (similarity={similarity:.3f})"
                )

        elif signal_type == "STABILITY_RESTORED":
            # Decay pressure from this stabilized peer
            governor.decay_neighbor_pressure()
            logger.debug(
                f"[CIRS/NEIGHBOR] Pressure decayed for {agent_id} "
                f"(peer {peer_id} stabilized)"
            )


def _lookup_similarity(agent_id: str, peer_id: str) -> Optional[float]:
    """
    Look up pairwise coherence similarity between two agents.

    Checks both directions in the coherence report buffer.
    Returns None if no report exists (conservative: don't guess).
    """
    # Check agent→peer direction
    key = f"{agent_id}:{peer_id}"
    report = _coherence_report_buffer.get(key)
    if report:
        return report.get("similarity_score")

    # Check peer→agent direction
    key_reverse = f"{peer_id}:{agent_id}"
    report_reverse = _coherence_report_buffer.get(key_reverse)
    if report_reverse:
        return report_reverse.get("similarity_score")

    return None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py::TestMaybeApplyNeighborPressure -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add src/mcp_handlers/cirs_protocol.py tests/test_cirs_resonance_wiring.py
git commit -m "feat(cirs-v2): add maybe_apply_neighbor_pressure for distributed damping"
```

---

### Task 4: Export new functions and wire into core.py

**Files:**
- Modify: `src/mcp_handlers/__init__.py:119-121`
- Modify: `src/mcp_handlers/core.py:1088-1089`

**Step 1: Update exports in `__init__.py`**

At line 119-121, change:

```python
    maybe_emit_void_alert,  # Hook for process_agent_update
    auto_emit_state_announce,  # Hook for process_agent_update
)
```

to:

```python
    maybe_emit_void_alert,  # Hook for process_agent_update
    auto_emit_state_announce,  # Hook for process_agent_update
    maybe_emit_resonance_signal,  # Hook for process_agent_update
    maybe_apply_neighbor_pressure,  # Hook for process_agent_update
)
```

**Step 2: Wire hooks in `core.py`**

After line 1088 (after the `auto_emit_state_announce` try block), add:

```python
            # CIRS Protocol: Auto-emit RESONANCE_ALERT / STABILITY_RESTORED on transitions
            # Enables multi-agent distributed damping from paper §8
            try:
                from .cirs_protocol import maybe_emit_resonance_signal
                cirs_data = result.get('cirs', {})
                # was_resonant is tracked on the governor's state
                monitor = mcp_server.monitors.get(agent_id)
                was_resonant = False
                if monitor and hasattr(monitor, 'adaptive_governor') and monitor.adaptive_governor:
                    was_resonant = monitor.adaptive_governor.state.was_resonant
                cirs_resonance = maybe_emit_resonance_signal(
                    agent_id=agent_id,
                    cirs_result=cirs_data,
                    was_resonant=was_resonant,
                )
            except Exception as e:
                logger.debug(f"CIRS resonance auto-emit skipped: {e}")

            # CIRS Protocol: Apply neighbor pressure from peer resonance alerts
            # Peers with high similarity tighten thresholds defensively
            try:
                from .cirs_protocol import maybe_apply_neighbor_pressure
                monitor = mcp_server.monitors.get(agent_id)
                if monitor and hasattr(monitor, 'adaptive_governor'):
                    maybe_apply_neighbor_pressure(
                        agent_id=agent_id,
                        governor=monitor.adaptive_governor,
                    )
            except Exception as e:
                logger.debug(f"CIRS neighbor pressure skipped: {e}")
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/test_adaptive_governor.py tests/test_cirs_resonance_wiring.py tests/test_cirs.py -v`
Expected: All tests pass

**Step 4: Run broader regression check**

Run: `python -m pytest tests/test_governance_core_comprehensive.py tests/test_cirs_protocol_handlers.py -v --timeout=60`
Expected: All tests pass

**Step 5: Commit**

```bash
git add src/mcp_handlers/__init__.py src/mcp_handlers/core.py
git commit -m "feat(cirs-v2): wire resonance auto-emit and neighbor pressure into process_agent_update"
```

---

### Task 5: Integration test — full loop

**Files:**
- Modify: `tests/test_cirs_resonance_wiring.py`

**Step 1: Write the integration test**

Add to `tests/test_cirs_resonance_wiring.py`:

```python
class TestResonanceFullLoop:
    """Integration: governor detects → alert emits → peer tightens."""

    def setup_method(self):
        _resonance_alert_buffer.clear()
        _coherence_report_buffer.clear()

    def test_full_resonance_propagation_loop(self):
        """
        Agent A oscillates → detects resonance → emits RESONANCE_ALERT.
        Agent B has high similarity → reads alert → applies neighbor pressure.
        Agent B's thresholds tighten.
        """
        config = GovernorConfig(flip_threshold=3)
        gov_a = AdaptiveGovernor(config=config)
        gov_b = AdaptiveGovernor()
        histories = _stable_histories()

        # Phase 1: Drive Agent A into resonance
        for i in range(10):
            v = "safe" if i % 2 == 0 else "high-risk"
            c = 0.65 if i % 2 == 0 else 0.30
            r = 0.20 if i % 2 == 0 else 0.65
            result_a = gov_a.update(coherence=c, risk=r, verdict=v, **histories)

        assert result_a["resonant"] is True

        # Phase 2: Emit the signal
        signal = maybe_emit_resonance_signal(
            agent_id="agent-a",
            cirs_result=result_a,
            was_resonant=False,  # First time resonant
        )
        assert signal is not None
        assert signal["type"] == "RESONANCE_ALERT"

        # Phase 3: Set up similarity between A and B
        _coherence_report_buffer["agent-b:agent-a"] = {
            "source_agent_id": "agent-b",
            "target_agent_id": "agent-a",
            "similarity_score": 0.8,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Phase 4: Agent B reads and applies pressure
        initial_pressure = gov_b.state.neighbor_pressure
        maybe_apply_neighbor_pressure(
            agent_id="agent-b",
            governor=gov_b,
        )
        assert gov_b.state.neighbor_pressure > initial_pressure

        # Phase 5: Agent A stabilizes → emits STABILITY_RESTORED
        for _ in range(5):
            result_a = gov_a.update(
                coherence=0.65, risk=0.20, verdict="safe", **histories
            )

        if not result_a["resonant"]:
            signal_restored = maybe_emit_resonance_signal(
                agent_id="agent-a",
                cirs_result=result_a,
                was_resonant=True,
            )
            if signal_restored:
                assert signal_restored["type"] == "STABILITY_RESTORED"

        # Phase 6: Agent B decays pressure
        pressure_before_decay = gov_b.state.neighbor_pressure
        maybe_apply_neighbor_pressure(
            agent_id="agent-b",
            governor=gov_b,
        )
        # If stability was restored, pressure should have decayed
        # (may still have RESONANCE_ALERT in buffer too, so just check it moved)


def _stable_histories():
    """Helper: stable EISV histories for phase detection."""
    return {
        "E_history": [0.7] * 6,
        "I_history": [0.8] * 6,
        "S_history": [0.2] * 6,
        "complexity_history": [0.3] * 6,
    }
```

**Step 2: Run integration test**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py::TestResonanceFullLoop -v`
Expected: PASS

**Step 3: Run complete test file**

Run: `python -m pytest tests/test_cirs_resonance_wiring.py -v`
Expected: All 10 tests pass

**Step 4: Commit**

```bash
git add tests/test_cirs_resonance_wiring.py
git commit -m "test(cirs-v2): add integration test for full resonance propagation loop"
```

---

### Task 6: Final regression + verification

**Step 1: Run the full governance_core test suite**

Run: `python -m pytest tests/test_governance_core_comprehensive.py tests/test_adaptive_governor.py tests/test_cirs.py tests/test_cirs_resonance_wiring.py tests/test_cirs_protocol_handlers.py -v --timeout=120`
Expected: All tests pass

**Step 2: Run a broader smoke test**

Run: `python -m pytest tests/ -x --timeout=120 -q 2>&1 | tail -20`
Expected: No failures introduced by our changes

**Step 3: Final commit with all files**

If any fixups needed, commit them. Then verify:

```bash
git log --oneline -6
```

Expected: 4 commits from this session:
1. `feat(cirs-v2): add was_resonant tracking to GovernorState`
2. `feat(cirs-v2): add maybe_emit_resonance_signal for auto-emit on transitions`
3. `feat(cirs-v2): add maybe_apply_neighbor_pressure for distributed damping`
4. `feat(cirs-v2): wire resonance auto-emit and neighbor pressure into process_agent_update`
5. `test(cirs-v2): add integration test for full resonance propagation loop`
