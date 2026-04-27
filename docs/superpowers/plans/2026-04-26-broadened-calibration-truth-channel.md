# Broadened Calibration Truth Channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden the tactical calibration truth channel from `test_*` only to `test_* ∪ task_*`, add per-channel breakdown to the API + dashboard, bump epoch 2 → 3, and backfill historical `task_*` outcomes — so `check_calibration` returns an honest signal instead of a permanently-pinned "miscalibrated" read.

**Architecture:** Two coupled gates in `outcome_events.py` are unified behind a `HARD_EXOGENOUS_TYPES` constant. `CalibrationChecker` gains `tactical_bin_stats_by_channel` parallel to its existing aggregate `tactical_bin_stats`. A canonical epoch bump via `scripts/dev/bump_epoch.py` marks the definition change. A backfill script replays historical `task_*` events from `audit.outcome_events`. Dashboard renders per-channel chips next to the existing Yes/No headline.

**Tech Stack:** Python 3.12, asyncio, PostgreSQL@17 + AGE, Pydantic v2, MCP server, vanilla JS dashboard.

**Spec:** `docs/superpowers/specs/2026-04-26-broadened-calibration-truth-channel-design.md`

---

## Task 1: Single-source-of-truth constant for hard-exogenous types

**Files:**
- Modify: `src/mcp_handlers/observability/outcome_events.py:33-40` (rewrite `_classify_hard_exogenous_signal`) + add module-level constant
- Test: `tests/test_outcome_events_classification.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_outcome_events_classification.py
"""Direct unit tests on the tactical-truth-channel gate.

Council finding (rev 2 of design doc): _classify_hard_exogenous_signal is
the *real* whitelist — the inline tuple at line 266 only governs the
CalibrationChecker call, not the SequentialCalibrationTracker call.
Both must derive from the same constant.
"""

import pytest

from src.mcp_handlers.observability.outcome_events import (
    HARD_EXOGENOUS_TYPES,
    _HARD_EXOGENOUS_TYPE_TO_CHANNEL,
    _classify_hard_exogenous_signal,
)


class TestHardExogenousClassification:
    def test_test_passed_classifies_as_tests(self):
        assert _classify_hard_exogenous_signal("test_passed", {}) == "tests"

    def test_test_failed_classifies_as_tests(self):
        assert _classify_hard_exogenous_signal("test_failed", {}) == "tests"

    def test_task_completed_classifies_as_tasks(self):
        assert _classify_hard_exogenous_signal("task_completed", {}) == "tasks"

    def test_task_failed_classifies_as_tasks(self):
        assert _classify_hard_exogenous_signal("task_failed", {}) == "tasks"

    def test_cirs_resonance_returns_none(self):
        # cirs_resonance is a detector output, not a prediction outcome.
        # No stated-confidence anchor → not eligible for tactical calibration.
        assert _classify_hard_exogenous_signal("cirs_resonance", {}) is None

    def test_trajectory_validated_returns_none(self):
        # Strategic-only signal; tactical channel must reject.
        assert _classify_hard_exogenous_signal("trajectory_validated", {}) is None

    def test_detail_key_fallback_still_works(self):
        # Pre-existing behavior: if outcome_type isn't in the whitelist but
        # detail carries a known signal key, return that label.
        assert _classify_hard_exogenous_signal("custom_event", {"tests": True}) == "tests"
        assert _classify_hard_exogenous_signal("custom_event", {"commands": [1]}) == "commands"

    def test_constant_and_routing_dict_agree(self):
        # If they ever drift, that drift IS the bug.
        assert set(_HARD_EXOGENOUS_TYPE_TO_CHANNEL.keys()) == HARD_EXOGENOUS_TYPES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_outcome_events_classification.py -v --no-cov --tb=short`
Expected: ImportError on `HARD_EXOGENOUS_TYPES` and `_HARD_EXOGENOUS_TYPE_TO_CHANNEL` (constants don't exist yet).

- [ ] **Step 3: Add the constant + rewrite the classification function**

Replace lines 24-40 of `src/mcp_handlers/observability/outcome_events.py` with:

```python
_HARD_EXOGENOUS_DETAIL_KEYS = (
    ("tests", "tests"),
    ("commands", "commands"),
    ("files", "files"),
    ("lint", "lint"),
    ("tool_results", "tool_observations"),
)

# Hard-exogenous outcome types eligible for tactical calibration.
# Must be binary pass/fail from real work — not graded scores, not retroactive.
# Both this constant and the line-266 gate below must stay in sync; the
# classifier function below is driven from _HARD_EXOGENOUS_TYPE_TO_CHANNEL,
# and the line-266 call uses HARD_EXOGENOUS_TYPES directly.
HARD_EXOGENOUS_TYPES = frozenset({
    "test_passed", "test_failed",
    "task_completed", "task_failed",
})

_HARD_EXOGENOUS_TYPE_TO_CHANNEL = {
    "test_passed": "tests", "test_failed": "tests",
    "task_completed": "tasks", "task_failed": "tasks",
}


def _classify_hard_exogenous_signal(outcome_type: str, detail: Dict[str, Any]) -> str | None:
    """Return the hard exogenous signal source when this outcome is e-process eligible."""
    channel = _HARD_EXOGENOUS_TYPE_TO_CHANNEL.get(outcome_type)
    if channel:
        return channel
    for key, label in _HARD_EXOGENOUS_DETAIL_KEYS:
        if detail.get(key):
            return label
    return None
```

- [ ] **Step 4: Update the line-266 gate to use the constant**

Find the existing line (was at `:266`, may shift slightly):

```python
if outcome_type in ('test_passed', 'test_failed'):
    calibration_checker.record_tactical_decision(
```

Replace `('test_passed', 'test_failed')` with `HARD_EXOGENOUS_TYPES`. The handler now feeds `task_*` to the `CalibrationChecker` aggregate too.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_outcome_events_classification.py -v --no-cov --tb=short`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add src/mcp_handlers/observability/outcome_events.py tests/test_outcome_events_classification.py
git commit -m "calibration: unify hard-exogenous gates behind HARD_EXOGENOUS_TYPES constant; add task_*"
```

---

## Task 2: Per-channel bin stats on `CalibrationChecker`

**Files:**
- Modify: `src/calibration.py:150` (init), `:224-280` (`record_tactical_decision`), `:412-447` (add `compute_tactical_metrics_per_channel`), `:780-810` (serialize), `:840-855` (load)
- Test: `tests/test_calibration_per_channel.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calibration_per_channel.py
"""Per-channel tactical calibration breakdown.

Tests that record_tactical_decision routes to a per-channel structure when
signal_source is provided, and that the aggregate path is preserved.
"""

import pytest
from pathlib import Path
from src.calibration import CalibrationChecker


@pytest.fixture
def checker(tmp_path):
    return CalibrationChecker(state_file=tmp_path / "calibration_state.json")


class TestPerChannelTacticalStats:
    def test_record_with_signal_source_populates_channel_dict(self, checker):
        checker.record_tactical_decision(
            confidence=0.8, decision="proceed", immediate_outcome=True,
            signal_source="tasks",
        )
        channel_stats = checker.tactical_bin_stats_by_channel["tasks"]
        # Bin 0.7-0.8 captures confidence=0.8
        assert any(stats["count"] == 1 for stats in channel_stats.values())

    def test_record_without_signal_source_leaves_per_channel_empty(self, checker):
        checker.record_tactical_decision(
            confidence=0.8, decision="proceed", immediate_outcome=True,
        )
        # Aggregate gets the row
        assert any(s["count"] == 1 for s in checker.tactical_bin_stats.values())
        # Per-channel does not
        assert sum(
            s["count"] for ch in checker.tactical_bin_stats_by_channel.values()
            for s in ch.values()
        ) == 0

    def test_record_with_signal_source_also_populates_aggregate(self, checker):
        # Back-compat: aggregate must remain populated when signal_source is given.
        checker.record_tactical_decision(
            confidence=0.8, decision="proceed", immediate_outcome=True,
            signal_source="tasks",
        )
        assert sum(s["count"] for s in checker.tactical_bin_stats.values()) == 1

    def test_compute_per_channel_returns_per_bin_breakdown(self, checker):
        for _ in range(5):
            checker.record_tactical_decision(0.8, "proceed", True, signal_source="tasks")
        for _ in range(3):
            checker.record_tactical_decision(0.3, "pause", False, signal_source="tasks")
        for _ in range(4):
            checker.record_tactical_decision(0.9, "proceed", True, signal_source="tests")

        per_channel = checker.compute_tactical_metrics_per_channel()
        assert "tasks" in per_channel and "tests" in per_channel
        # tasks should have 2 populated bins (0.7-0.8 and 0.0-0.5 or similar)
        assert sum(b.count for b in per_channel["tasks"].values()) == 8
        assert sum(b.count for b in per_channel["tests"].values()) == 4

    def test_per_channel_state_round_trips_through_persistence(self, checker, tmp_path):
        checker.record_tactical_decision(0.8, "proceed", True, signal_source="tasks")
        checker.save_state()

        reloaded = CalibrationChecker(state_file=tmp_path / "calibration_state.json")
        per_channel = reloaded.compute_tactical_metrics_per_channel()
        assert sum(b.count for b in per_channel["tasks"].values()) == 1

    def test_unknown_state_key_load_does_not_crash(self, tmp_path):
        # Existing state files lack tactical_bin_stats_by_channel; loading
        # should not raise — must default to empty per-channel state.
        import json
        state_file = tmp_path / "calibration_state.json"
        state_file.write_text(json.dumps({"tactical_bins": {}, "bins": {}}))
        checker = CalibrationChecker(state_file=state_file)
        assert checker.tactical_bin_stats_by_channel == {} or all(
            len(v) == 0 for v in checker.tactical_bin_stats_by_channel.values()
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calibration_per_channel.py -v --no-cov --tb=short`
Expected: AttributeError on `tactical_bin_stats_by_channel`, missing `signal_source` kwarg, missing `compute_tactical_metrics_per_channel`.

- [ ] **Step 3: Add per-channel state to `CalibrationChecker.__init__`**

In `src/calibration.py`, find the existing `tactical_bin_stats` initialization (around line 150):

```python
self.tactical_bin_stats = defaultdict(lambda: {
    'count': 0, 'predicted_correct': 0, 'actual_correct': 0,
    'confidence_sum': 0.0,
})
```

Add immediately after:

```python
# Per-channel tactical bin stats (parallel to aggregate above).
# Populated when record_tactical_decision is called with signal_source.
# Aggregate stats remain populated for back-compat regardless.
self.tactical_bin_stats_by_channel = defaultdict(lambda: defaultdict(lambda: {
    'count': 0, 'predicted_correct': 0, 'actual_correct': 0,
    'confidence_sum': 0.0,
}))
```

- [ ] **Step 4: Extend `record_tactical_decision` to accept `signal_source`**

Find the existing `record_tactical_decision` method (around line 224). Update its signature:

```python
def record_tactical_decision(
    self,
    confidence: float,
    decision: str,
    immediate_outcome: bool,
    signal_source: str | None = None,
):
```

Inside the function, after the existing block that updates `self.tactical_bin_stats[bin_key]`, add:

```python
# Per-channel routing (additive — aggregate above is unchanged).
if signal_source:
    if not hasattr(self, 'tactical_bin_stats_by_channel'):
        # Backward-compat for instances created before this field existed.
        self.tactical_bin_stats_by_channel = defaultdict(lambda: defaultdict(lambda: {
            'count': 0, 'predicted_correct': 0, 'actual_correct': 0,
            'confidence_sum': 0.0,
        }))
    channel_stats = self.tactical_bin_stats_by_channel[signal_source][bin_key]
    channel_stats['count'] += 1
    channel_stats['confidence_sum'] += confidence
    if immediate_outcome:
        channel_stats['actual_correct'] += 1
    if confidence >= 0.5:
        channel_stats['predicted_correct'] += 1
```

- [ ] **Step 5: Add `compute_tactical_metrics_per_channel`**

In `src/calibration.py`, immediately after the existing `compute_tactical_metrics` method (around line 447), add:

```python
def compute_tactical_metrics_per_channel(self) -> Dict[str, Dict[str, CalibrationBin]]:
    """
    Compute per-channel tactical calibration metrics.

    Returns {channel: {bin_key: CalibrationBin}} so callers can ask
    "miscalibrated where?" instead of just "miscalibrated".
    """
    results: Dict[str, Dict[str, CalibrationBin]] = {}

    if not hasattr(self, 'tactical_bin_stats_by_channel'):
        return results

    for channel, channel_bins in self.tactical_bin_stats_by_channel.items():
        channel_results: Dict[str, CalibrationBin] = {}
        for bin_key, stats in channel_bins.items():
            if stats['count'] == 0:
                continue
            bin_min, bin_max = map(float, bin_key.split('-'))
            accuracy = stats['actual_correct'] / stats['count']
            expected_accuracy = stats['confidence_sum'] / stats['count']
            calibration_error = abs(accuracy - expected_accuracy)
            channel_results[bin_key] = CalibrationBin(
                bin_range=(bin_min, bin_max),
                count=stats['count'],
                predicted_correct=stats['predicted_correct'],
                actual_correct=stats['actual_correct'],
                accuracy=accuracy,
                expected_accuracy=expected_accuracy,
                calibration_error=calibration_error,
            )
        if channel_results:
            results[channel] = channel_results

    return results
```

- [ ] **Step 6: Round-trip per-channel state through persistence**

Find the existing `_serialize` method (~line 780-810) and locate the line:

```python
'tactical_bins': {k: dict(v) for k, v in self.tactical_bin_stats.items()} if hasattr(self, 'tactical_bin_stats') else {}
```

Add a new key on the dict being serialized:

```python
'tactical_bins_by_channel': {
    channel: {k: dict(v) for k, v in bins.items()}
    for channel, bins in self.tactical_bin_stats_by_channel.items()
} if hasattr(self, 'tactical_bin_stats_by_channel') else {},
```

Then find the existing load logic for `tactical_bin_stats` (around line 845):

```python
self.tactical_bin_stats = defaultdict(lambda: {
    'count': 0, 'predicted_correct': 0, 'actual_correct': 0,
    'confidence_sum': 0.0,
})
for bin_key, stats in data.get('tactical_bins', {}).items():
    self.tactical_bin_stats[bin_key] = stats
```

Add immediately after:

```python
# Per-channel breakdown (may be absent in older state files).
self.tactical_bin_stats_by_channel = defaultdict(lambda: defaultdict(lambda: {
    'count': 0, 'predicted_correct': 0, 'actual_correct': 0,
    'confidence_sum': 0.0,
}))
for channel, channel_bins in data.get('tactical_bins_by_channel', {}).items():
    for bin_key, stats in channel_bins.items():
        self.tactical_bin_stats_by_channel[channel][bin_key] = stats
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_calibration_per_channel.py -v --no-cov --tb=short`
Expected: PASS (6 tests).

- [ ] **Step 8: Commit**

```bash
git add src/calibration.py tests/test_calibration_per_channel.py
git commit -m "calibration: add tactical_bin_stats_by_channel + compute_tactical_metrics_per_channel"
```

---

## Task 3: Wire `signal_source` from outcome_events handler into the CalibrationChecker call

**Files:**
- Modify: `src/mcp_handlers/observability/outcome_events.py` (the line-266 gate now passes signal_source)
- Test: `tests/integration/test_outcome_event_calibration_wiring.py` (new)

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_outcome_event_calibration_wiring.py
"""End-to-end: posting outcome_event must populate per-channel tactical state."""

import pytest
from unittest.mock import patch, MagicMock
from src.calibration import calibration_checker
from src.mcp_handlers.observability.outcome_events import handle_outcome_event


@pytest.fixture
def fresh_checker(tmp_path, monkeypatch):
    from src.calibration import CalibrationChecker
    fresh = CalibrationChecker(state_file=tmp_path / "calibration_state.json")
    monkeypatch.setattr("src.calibration.calibration_checker", fresh)
    monkeypatch.setattr(
        "src.mcp_handlers.observability.outcome_events.calibration_checker",
        fresh, raising=False,
    )
    return fresh


@pytest.mark.asyncio
class TestOutcomeEventToTacticalChannel:
    async def test_task_completed_populates_tasks_channel(self, fresh_checker, monkeypatch):
        # Mock the DB write path so we exercise only the calibration recording.
        monkeypatch.setattr(
            "src.mcp_handlers.observability.outcome_events.get_db",
            lambda: MagicMock(record_outcome_event=MagicMock(return_value="outcome-id")),
        )
        monkeypatch.setattr(
            "src.mcp_handlers.observability.outcome_events.get_context_agent_id",
            lambda: "test-agent",
        )

        await handle_outcome_event({
            "outcome_type": "task_completed",
            "agent_id": "test-agent",
            "reported_confidence": 0.8,
        })

        per_channel = fresh_checker.compute_tactical_metrics_per_channel()
        assert "tasks" in per_channel
        assert sum(b.count for b in per_channel["tasks"].values()) == 1

    async def test_cirs_resonance_does_not_populate_tactical(self, fresh_checker, monkeypatch):
        monkeypatch.setattr(
            "src.mcp_handlers.observability.outcome_events.get_db",
            lambda: MagicMock(record_outcome_event=MagicMock(return_value="outcome-id")),
        )
        monkeypatch.setattr(
            "src.mcp_handlers.observability.outcome_events.get_context_agent_id",
            lambda: "test-agent",
        )

        await handle_outcome_event({
            "outcome_type": "cirs_resonance",
            "agent_id": "test-agent",
            "reported_confidence": 0.8,
            "is_bad": True,
        })

        per_channel = fresh_checker.compute_tactical_metrics_per_channel()
        assert per_channel == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_outcome_event_calibration_wiring.py -v --no-cov --tb=short`
Expected: FAIL — `task_completed` flow does not pass `signal_source` to `record_tactical_decision`, so per-channel state stays empty.

- [ ] **Step 3: Pass signal_source from the handler**

In `src/mcp_handlers/observability/outcome_events.py`, find the existing block:

```python
if outcome_type in HARD_EXOGENOUS_TYPES:
    calibration_checker.record_tactical_decision(
        confidence=_confidence,
        decision='proceed',
        immediate_outcome=not is_bad,
    )
```

Add `signal_source` derived from the outcome_type:

```python
if outcome_type in HARD_EXOGENOUS_TYPES:
    calibration_checker.record_tactical_decision(
        confidence=_confidence,
        decision='proceed',
        immediate_outcome=not is_bad,
        signal_source=_HARD_EXOGENOUS_TYPE_TO_CHANNEL[outcome_type],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_outcome_event_calibration_wiring.py -v --no-cov --tb=short`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mcp_handlers/observability/outcome_events.py tests/integration/test_outcome_event_calibration_wiring.py
git commit -m "calibration: wire signal_source from outcome_event handler into CalibrationChecker"
```

---

## Task 4: Surface per-channel breakdown in `check_calibration` response

**Files:**
- Modify: `src/calibration.py` — `check_calibration` (around line 449-580)
- Test: `tests/test_check_calibration_per_channel.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_check_calibration_per_channel.py
"""check_calibration must include per_channel_calibration when channels exist."""

import pytest
from src.calibration import CalibrationChecker


@pytest.fixture
def checker(tmp_path):
    return CalibrationChecker(state_file=tmp_path / "calibration_state.json")


class TestCheckCalibrationPerChannel:
    def test_response_contains_per_channel_key_when_channels_exist(self, checker):
        # Seed enough samples to clear min_samples_per_bin
        for _ in range(15):
            checker.record_tactical_decision(0.8, "proceed", True, signal_source="tasks")
        for _ in range(15):
            checker.record_tactical_decision(0.9, "proceed", True, signal_source="tests")

        is_calibrated, result = checker.check_calibration()
        assert "per_channel_calibration" in result
        assert "tasks" in result["per_channel_calibration"]
        assert "tests" in result["per_channel_calibration"]

    def test_per_channel_entry_has_required_fields(self, checker):
        for _ in range(15):
            checker.record_tactical_decision(0.8, "proceed", True, signal_source="tasks")

        _, result = checker.check_calibration()
        tasks_entry = result["per_channel_calibration"]["tasks"]
        assert "calibrated" in tasks_entry
        assert "samples" in tasks_entry
        assert "calibration_gap" in tasks_entry
        assert "issues" in tasks_entry
        assert isinstance(tasks_entry["calibrated"], bool)
        assert tasks_entry["samples"] == 15

    def test_response_omits_per_channel_when_no_channels_recorded(self, checker):
        # Aggregate-only path (legacy): no per-channel data.
        for _ in range(15):
            checker.record_tactical_decision(0.8, "proceed", True)
        _, result = checker.check_calibration()
        # Either omit the key or surface empty dict; back-compat is "no key".
        assert result.get("per_channel_calibration", {}) == {}

    def test_aggregate_calibrated_field_unchanged_with_per_channel_data(self, checker):
        # Adding per-channel state must not change aggregate Yes/No semantics.
        for _ in range(15):
            checker.record_tactical_decision(0.8, "proceed", True, signal_source="tasks")
        is_calibrated, result = checker.check_calibration()
        assert "is_calibrated" in result
        # Aggregate cal is still computed from tactical_bin_stats (which is also populated).
        assert isinstance(result["is_calibrated"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_check_calibration_per_channel.py -v --no-cov --tb=short`
Expected: FAIL — `per_channel_calibration` key absent from response.

- [ ] **Step 3: Compose `per_channel_calibration` in `check_calibration`**

In `src/calibration.py::check_calibration` (around line 510-540), after the existing `result = {...}` block but before the final `return is_calibrated, result`, add:

```python
# Per-channel breakdown (additive — aggregate fields above are unchanged).
per_channel_metrics = self.compute_tactical_metrics_per_channel()
if per_channel_metrics:
    per_channel_response = {}
    for channel, bin_metrics in per_channel_metrics.items():
        channel_samples = sum(b.count for b in bin_metrics.values())
        channel_issues = []
        max_gap = 0.0
        for bin_key, b in bin_metrics.items():
            if b.count < min_samples_per_bin:
                continue
            if b.calibration_error > 0.2:
                channel_issues.append(
                    f"Bin {bin_key}: large calibration error ({b.calibration_error:.2f})"
                )
            max_gap = max(max_gap, b.calibration_error)
        per_channel_response[channel] = {
            "calibrated": len(channel_issues) == 0,
            "samples": channel_samples,
            "calibration_gap": max_gap,
            "issues": channel_issues,
        }
    result["per_channel_calibration"] = per_channel_response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_check_calibration_per_channel.py -v --no-cov --tb=short`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/calibration.py tests/test_check_calibration_per_channel.py
git commit -m "calibration: surface per_channel_calibration in check_calibration response"
```

---

## Task 5: Reporting-hygiene guard — `bad_rate_pinned_to_zero`

**Files:**
- Modify: `src/sequential_calibration.py` — add `compute_per_channel_health` method
- Modify: `src/calibration.py::check_calibration` — surface `per_channel_health`
- Test: `tests/test_sequential_calibration_hygiene.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sequential_calibration_hygiene.py
"""Hygiene guard: alert when a channel's bad_rate pins to zero with non-trivial samples."""

import pytest
from pathlib import Path
from src.sequential_calibration import SequentialCalibrationTracker


@pytest.fixture
def tracker(tmp_path):
    return SequentialCalibrationTracker(state_file=tmp_path / "seq_state.json")


class TestPerChannelHealthGuard:
    def test_pinned_when_100_samples_all_correct(self, tracker):
        for _ in range(100):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tests",
                persist=False,
            )
        health = tracker.compute_per_channel_health()
        assert health["tests"]["bad_rate_pinned_to_zero"] is True

    def test_not_pinned_when_under_100_samples(self, tracker):
        for _ in range(50):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tests",
                persist=False,
            )
        health = tracker.compute_per_channel_health()
        # Below 100 samples threshold — pinned flag must be False even if bad_rate is 0.
        assert health["tests"]["bad_rate_pinned_to_zero"] is False

    def test_not_pinned_when_any_failure(self, tracker):
        for _ in range(99):
            tracker.record_exogenous_tactical_outcome(
                confidence=0.6, outcome_correct=True, signal_source="tasks",
                persist=False,
            )
        tracker.record_exogenous_tactical_outcome(
            confidence=0.6, outcome_correct=False, signal_source="tasks",
            persist=False,
        )
        health = tracker.compute_per_channel_health()
        assert health["tasks"]["bad_rate_pinned_to_zero"] is False
        assert 0.0 < health["tasks"]["bad_rate"] < 0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sequential_calibration_hygiene.py -v --no-cov --tb=short`
Expected: AttributeError on `compute_per_channel_health`.

- [ ] **Step 3: Add per-channel sample/outcome tracking to `SequentialCalibrationTracker`**

In `src/sequential_calibration.py`, modify `_empty_state()` (around line 67):

```python
def _empty_state() -> Dict[str, Any]:
    return {
        "eligible_samples": 0,
        "successes": 0,
        "confidence_sum": 0.0,
        "log_e_value": 0.0,
        "last_e_value": 1.0,
        "last_alt_probability": 0.5,
        "signal_sources": {},
        "signal_source_outcomes": {},  # NEW: {channel: {samples: int, successes: int}}
        "last_updated": None,
    }
```

In `_update_state` (around line 163-197), after the existing `signal_sources` increment (lines 189-190), add:

```python
source_outcomes = state.setdefault("signal_source_outcomes", {})
ch_outcomes = source_outcomes.setdefault(signal_source, {"samples": 0, "successes": 0})
ch_outcomes["samples"] += 1
if y == 1.0:
    ch_outcomes["successes"] += 1
```

- [ ] **Step 4: Add `compute_per_channel_health` method**

In `src/sequential_calibration.py`, add as a new method on `SequentialCalibrationTracker` (after `record_exogenous_tactical_outcome`):

```python
def compute_per_channel_health(self, min_samples_for_pin: int = 100) -> Dict[str, Dict[str, Any]]:
    """
    Reporting-hygiene check on per-channel outcome stream.

    A channel "pinned to zero" means it has accumulated enough samples to
    be diagnostic but every observed outcome was a success — exactly the
    pathology the broadened truth channel was meant to escape. Sentinel
    can subscribe to this and raise an anomaly when a previously-non-zero
    channel pins.

    Args:
        min_samples_for_pin: minimum samples before pinned flag can fire.
    """
    out: Dict[str, Dict[str, Any]] = {}
    source_outcomes = self.global_state.get("signal_source_outcomes", {})
    for channel, counts in source_outcomes.items():
        samples = int(counts.get("samples", 0))
        successes = int(counts.get("successes", 0))
        bad_rate = 0.0 if samples == 0 else (samples - successes) / samples
        pinned = (samples >= min_samples_for_pin) and (bad_rate == 0.0)
        out[channel] = {
            "samples": samples,
            "successes": successes,
            "bad_rate": bad_rate,
            "bad_rate_pinned_to_zero": pinned,
        }
    return out
```

- [ ] **Step 5: Surface in `check_calibration` response**

In `src/calibration.py::check_calibration`, after the per-channel-calibration block from Task 4, add:

```python
# Hygiene guard from sequential tracker (signal_source_outcomes).
try:
    from src.sequential_calibration import sequential_calibration_tracker
    health = sequential_calibration_tracker.compute_per_channel_health()
    if health:
        result["per_channel_health"] = health
except Exception as e_health:
    # Hygiene guard is informational; do not break the response on import error.
    import logging
    logging.getLogger(__name__).debug("per_channel_health unavailable: %s", e_health)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_sequential_calibration_hygiene.py -v --no-cov --tb=short`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add src/sequential_calibration.py src/calibration.py tests/test_sequential_calibration_hygiene.py
git commit -m "calibration: add per-channel hygiene guard (bad_rate_pinned_to_zero)"
```

---

## Task 6: Epoch migration on `SequentialCalibrationTracker.__init__`

**Files:**
- Modify: `src/sequential_calibration.py:_empty_state` + `__init__` + `load_state`
- Test: `tests/test_sequential_calibration_epoch.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sequential_calibration_epoch.py
"""Epoch migration: state file from older epoch is archived and reset."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from src.sequential_calibration import SequentialCalibrationTracker


class TestEpochMigration:
    def test_state_from_older_epoch_is_archived(self, tmp_path):
        state_file = tmp_path / "seq_state.json"
        # Pre-existing state from an older epoch
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 100, "successes": 99},
            "agents": {},
            "epoch": 2,
        }))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)
        # Archive should exist
        assert (tmp_path / "seq_state.bak.epoch2").exists() or any(
            p.name.startswith("seq_state.bak.epoch") for p in tmp_path.iterdir()
        )
        # Tracker started fresh
        assert tracker.global_state["eligible_samples"] == 0

    def test_matching_epoch_does_not_archive(self, tmp_path):
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 50, "successes": 49},
            "agents": {},
            "epoch": 3,
        }))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)
        # No archive
        archives = [p for p in tmp_path.iterdir() if "bak.epoch" in p.name]
        assert archives == []
        # State preserved
        assert tracker.global_state["eligible_samples"] == 50

    def test_concurrent_migration_filenotfound_is_swallowed(self, tmp_path):
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 1, "successes": 1},
            "epoch": 2,
        }))
        # Simulate another process having renamed the file already.
        state_file.unlink()
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            # Must not raise
            tracker = SequentialCalibrationTracker(state_file=state_file)
        assert tracker.global_state["eligible_samples"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sequential_calibration_epoch.py -v --no-cov --tb=short`
Expected: FAIL — no migration logic exists yet; epoch is not in state file at all.

- [ ] **Step 3: Add `epoch` to `_empty_state`**

```python
def _empty_state() -> Dict[str, Any]:
    return {
        "eligible_samples": 0,
        "successes": 0,
        "confidence_sum": 0.0,
        "log_e_value": 0.0,
        "last_e_value": 1.0,
        "last_alt_probability": 0.5,
        "signal_sources": {},
        "signal_source_outcomes": {},
        "last_updated": None,
    }
```

`epoch` lives top-level in the serialized JSON, not inside the per-state dict. Update `_serialize`:

```python
def _serialize(self) -> Dict[str, Any]:
    from config.governance_config import GovernanceConfig
    return {
        "global": dict(self.global_state),
        "agents": {agent_id: dict(state) for agent_id, state in self.agent_states.items()},
        "prior_success": self.prior_success,
        "prior_failure": self.prior_failure,
        "epoch": GovernanceConfig.CURRENT_EPOCH,
    }
```

- [ ] **Step 4: Add migration logic at the start of `load_state`**

In `src/sequential_calibration.py::load_state` (around line 130), insert before the existing JSON-load block:

```python
def load_state(self) -> None:
    try:
        if not self.state_file.exists():
            self.reset()
            self._loaded_mtime = 0.0
            return

        # Epoch migration check — read just the epoch first.
        with open(self.state_file, "r") as f:
            data = json.load(f)

        from config.governance_config import GovernanceConfig
        file_epoch = int(data.get("epoch", 1))
        if file_epoch != GovernanceConfig.CURRENT_EPOCH:
            archive_path = self.state_file.with_suffix(f".bak.epoch{file_epoch}")
            try:
                self.state_file.rename(archive_path)
            except FileNotFoundError:
                # Concurrent process already migrated; safe to no-op.
                pass
            print(
                f"Calibration epoch changed ({file_epoch} → {GovernanceConfig.CURRENT_EPOCH}); "
                f"archived prior state to {archive_path}",
                file=sys.stderr,
            )
            self.reset()
            self._loaded_mtime = 0.0
            return

        # ... rest of existing load logic continues unchanged ...
        self.global_state = _empty_state()
        self.global_state.update(data.get("global", {}))
        self.agent_states = defaultdict(_empty_state)
        for agent_id, state in data.get("agents", {}).items():
            restored = _empty_state()
            restored.update(state or {})
            self.agent_states[agent_id] = restored
        self._loaded_mtime = self._file_mtime()
    except Exception as e:
        print(f"Warning: Failed to load sequential calibration state: {e}, resetting", file=sys.stderr)
        self.reset()
        self._loaded_mtime = 0.0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sequential_calibration_epoch.py -v --no-cov --tb=short`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/sequential_calibration.py tests/test_sequential_calibration_epoch.py
git commit -m "calibration: epoch-aware state-file migration on tracker init"
```

---

## Task 7: Backfill script (`task_*` only)

**Files:**
- Create: `scripts/dev/backfill_tactical_calibration.py`
- Test: `tests/test_backfill_tactical_calibration.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backfill_tactical_calibration.py
"""Backfill script: replays task_* outcomes from audit.outcome_events."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    from src.sequential_calibration import SequentialCalibrationTracker
    state_file = tmp_path / "seq_state.json"
    # Seed with current-epoch state so migration guard passes.
    with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
        mock_cfg.CURRENT_EPOCH = 3
        tracker = SequentialCalibrationTracker(state_file=state_file)
        tracker.save_state()
    return tracker, state_file


class TestBackfillScript:
    def test_dry_run_reports_counts_without_mutating_state(self, isolated_tracker, monkeypatch):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker
        original_mtime = state_file.stat().st_mtime

        fake_rows = [
            {"outcome_type": "task_completed", "agent_id": "a1", "is_bad": False, "confidence": 0.8},
            {"outcome_type": "task_failed", "agent_id": "a1", "is_bad": True, "confidence": 0.6},
        ]
        with patch.object(backfill, "fetch_eligible_rows", AsyncMock(return_value=fake_rows)):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                summary = asyncio.run(backfill.backfill(days=30, dry_run=True))

        assert summary["candidates"] == 2
        assert summary["replayed"] == 0  # dry-run
        assert summary["skipped_no_confidence"] == 0
        # State file untouched
        assert state_file.stat().st_mtime == original_mtime

    def test_live_run_calls_save_state_exactly_once(self, isolated_tracker, monkeypatch):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker

        fake_rows = [
            {"outcome_type": "task_completed", "agent_id": "a1", "is_bad": False, "confidence": 0.8},
            {"outcome_type": "task_failed", "agent_id": "a1", "is_bad": True, "confidence": 0.6},
        ]
        save_calls = []
        original_save = tracker.save_state
        def counted_save():
            save_calls.append(1)
            original_save()
        tracker.save_state = counted_save

        with patch.object(backfill, "fetch_eligible_rows", AsyncMock(return_value=fake_rows)):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                summary = asyncio.run(backfill.backfill(days=30, dry_run=False))

        assert summary["replayed"] == 2
        assert len(save_calls) == 1, f"Expected exactly 1 save_state call, got {len(save_calls)}"

    def test_db_error_mid_run_does_not_save_state(self, isolated_tracker):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker
        original_mtime = state_file.stat().st_mtime

        # fetch_eligible_rows raises mid-stream
        with patch.object(backfill, "fetch_eligible_rows",
                          AsyncMock(side_effect=RuntimeError("DB down"))):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                with pytest.raises(RuntimeError):
                    asyncio.run(backfill.backfill(days=30, dry_run=False))

        # State file unchanged
        assert state_file.stat().st_mtime == original_mtime

    def test_epoch_mismatch_exits_with_instructions(self, tmp_path):
        from scripts.dev import backfill_tactical_calibration as backfill
        from src.sequential_calibration import SequentialCalibrationTracker

        # Tracker stamped epoch=2; current=3 → mismatch
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 0},
            "agents": {},
            "epoch": 2,
        }))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)
            # Tracker init already migrated; force an epoch-mismatch detection
            # at the backfill layer too by re-stamping.
            with open(state_file, "w") as f:
                json.dump({"global": {}, "agents": {}, "epoch": 2}, f)

            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                with pytest.raises(SystemExit):
                    asyncio.run(backfill.backfill(days=30, dry_run=False))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backfill_tactical_calibration.py -v --no-cov --tb=short`
Expected: ImportError — `scripts.dev.backfill_tactical_calibration` doesn't exist.

- [ ] **Step 3: Create the backfill script**

Write `scripts/dev/backfill_tactical_calibration.py`:

```python
#!/usr/bin/env python3
"""Backfill historical task_* outcomes into per-channel tactical calibration state.

After bumping epoch to 3, the new `tasks` channel starts empty. This script
replays eligible rows from audit.outcome_events.task_* through the tracker so
the channel begins with real history instead of a cold start.

test_* is NOT backfilled: production rows do not carry detail->>'reported_confidence'
for tests (verified 2026-04-26 against live DB — 0/2300 coverage). The tests
channel accumulates forward from this PR's deployment.

Usage:
    python3 scripts/dev/backfill_tactical_calibration.py [--dry-run] [--days 30]
"""

import argparse
import asyncio
import json
import sys
from typing import Dict, List

from src.db import get_db
from src.sequential_calibration import sequential_calibration_tracker
from src.mcp_handlers.observability.outcome_events import HARD_EXOGENOUS_TYPES, _HARD_EXOGENOUS_TYPE_TO_CHANNEL


# task_* are the only types this script backfills — see module docstring.
BACKFILL_TYPES = ("task_completed", "task_failed")


async def fetch_eligible_rows(days: int) -> List[Dict]:
    """Read task_* rows from the current-epoch partition with reconstructable confidence."""
    db = get_db()
    sql = """
        SELECT
            ts,
            outcome_type,
            agent_id,
            is_bad,
            (detail->>'reported_confidence')::float AS confidence
        FROM audit.outcome_events
        WHERE outcome_type = ANY($1)
          AND epoch = (SELECT MAX(epoch) FROM core.epochs)
          AND ts > NOW() - ($2 || ' days')::interval
          AND detail->>'reported_confidence' IS NOT NULL
        ORDER BY ts ASC
    """
    rows = await db.fetch(sql, list(BACKFILL_TYPES), str(days))
    return [dict(r) for r in rows]


async def backfill(days: int, dry_run: bool) -> Dict[str, int]:
    """Replay eligible historical rows into the tracker.

    On any exception during fetch or replay, exit non-zero before save_state();
    state file is not partially mutated.
    """
    summary = {
        "candidates": 0,
        "replayed": 0,
        "skipped_no_confidence": 0,
        "skipped_unknown_channel": 0,
    }

    # Verify epoch alignment: tracker init handles migration, but if someone
    # ran backfill before letting the server restart once, the tracker may
    # still hold pre-migration state. Refuse rather than silently corrupt.
    from config.governance_config import GovernanceConfig
    if not sequential_calibration_tracker.state_file.exists():
        # No state yet — first run is fine; tracker will create it.
        pass
    else:
        with open(sequential_calibration_tracker.state_file, "r") as f:
            on_disk = json.load(f)
        on_disk_epoch = int(on_disk.get("epoch", 1))
        if on_disk_epoch != GovernanceConfig.CURRENT_EPOCH:
            print(
                f"State file is at epoch {on_disk_epoch}; current is "
                f"{GovernanceConfig.CURRENT_EPOCH}. Restart governance-mcp "
                f"once first to trigger the migration, then re-run.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    rows = await fetch_eligible_rows(days)
    summary["candidates"] = len(rows)

    for row in rows:
        confidence = row.get("confidence")
        if confidence is None:
            summary["skipped_no_confidence"] += 1
            continue
        channel = _HARD_EXOGENOUS_TYPE_TO_CHANNEL.get(row["outcome_type"])
        if not channel:
            summary["skipped_unknown_channel"] += 1
            continue

        if not dry_run:
            sequential_calibration_tracker.record_exogenous_tactical_outcome(
                confidence=float(confidence),
                outcome_correct=not bool(row["is_bad"]),
                agent_id=row.get("agent_id"),
                signal_source=channel,
                outcome_type=row["outcome_type"],
                persist=False,  # critical: no per-row writes
            )
            summary["replayed"] += 1

    if not dry_run and summary["replayed"] > 0:
        # Single atomic save after the loop completes.
        sequential_calibration_tracker.save_state()

    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts without mutating state.")
    parser.add_argument("--days", type=int, default=30,
                        help="Look-back window in days (default 30).")
    args = parser.parse_args()

    summary = asyncio.run(backfill(days=args.days, dry_run=args.dry_run))
    print("Backfill summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("\nNext: restart governance-mcp; check_calibration should now report"
          " per_channel_calibration with a populated 'tasks' entry.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backfill_tactical_calibration.py -v --no-cov --tb=short`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/dev/backfill_tactical_calibration.py tests/test_backfill_tactical_calibration.py
git commit -m "calibration: backfill script for task_* historical events"
```

---

## Task 8: Dashboard render extension

**Files:**
- Modify: `dashboard/dashboard.js:1196-1238` (`loadCalibration`)
- Test: manual verification (no JS test infrastructure for this surface)

- [ ] **Step 1: Extend `loadCalibration` to render per-channel chips**

In `dashboard/dashboard.js`, find the existing `loadCalibration` function. After the line `const samples = result.total_samples ?? 0;`, the existing logic computes a `detailEl.textContent`. Modify the `else` branch (where `calibrated ? 'Yes' : 'No'` is set) to append per-channel chips when `result.per_channel_calibration` is present.

Find this block (~line 1215-1224):

```javascript
} else {
    var calibrated = (result.calibration_status
        ? result.calibration_status === 'calibrated'
        : result.calibrated === true);
    valueEl.textContent = calibrated ? 'Yes' : 'No';
    valueEl.style.color = calibrated
        ? 'var(--color-success, #22c55e)'
        : 'var(--color-danger, #ef4444)';
    var trajectoryPct = (th * 100).toFixed(0);
    detailEl.textContent = samples + ' samples · ' + trajectoryPct + '% trajectory';
}
```

Replace with:

```javascript
} else {
    var calibrated = (result.calibration_status
        ? result.calibration_status === 'calibrated'
        : result.calibrated === true);
    valueEl.textContent = calibrated ? 'Yes' : 'No';
    valueEl.style.color = calibrated
        ? 'var(--color-success, #22c55e)'
        : 'var(--color-danger, #ef4444)';
    var trajectoryPct = (th * 100).toFixed(0);

    // Per-channel chips (additive — falls back to old detail when absent).
    var perChannel = result.per_channel_calibration;
    if (perChannel && Object.keys(perChannel).length > 0) {
        var chips = Object.entries(perChannel).map(function (entry) {
            var name = entry[0];
            var c = entry[1];
            var icon = c.calibrated ? '✓' : '✕';
            return name + ': ' + icon;
        }).join(' · ');
        detailEl.textContent = samples + ' samples · ' + chips + ' · ' + trajectoryPct + '% trajectory';
    } else {
        detailEl.textContent = samples + ' samples · ' + trajectoryPct + '% trajectory';
    }
}
```

- [ ] **Step 2: Verify CSS allowlist (dashboard skill)**

`dashboard/dashboard.js` is already in the static-file allowlist; no allowlist change needed for an in-place edit.

Run: `curl -sI http://127.0.0.1:8767/dashboard/dashboard.js | head -1`
Expected: `HTTP/1.1 200 OK` after the governance-mcp picks up the change.

- [ ] **Step 3: Manual verification (after epoch bump + backfill in Task 9-10)**

After Tasks 9 and 10 complete, restart governance-mcp, hard-refresh `http://127.0.0.1:8767/dashboard`, and confirm:
- The Calibration card detail line shows `N samples · tasks: ✓ · tests: ✕ · 98% trajectory` (or similar).
- The headline still shows Yes / No / Stale / — based on aggregate.

- [ ] **Step 4: Commit**

```bash
git add dashboard/dashboard.js
git commit -m "dashboard: render per-channel calibration chips when present"
```

---

## Task 9: Paper note (v6.10 §11.6)

**Files:**
- Modify: `~/projects/unitares-paper-v6/sections/12_limits.md` (or whichever file holds calibration grounding) — separate repo

- [ ] **Step 1: Locate the calibration-grounding paragraph in v6**

```bash
grep -rn -iE "calibration.*chann|truth.*chann|test_passed|tactical.*calibration" ~/projects/unitares-paper-v6/sections/ | head -10
```

The grounding discussion lives near §11.6 / §12.4; pick the closest existing paragraph to insert near.

- [ ] **Step 2: Add the paragraph**

Append to the relevant section:

```markdown
### Truth-channel definition (v6.10)

Tactical calibration in v6.x was grounded against `test_*` outcomes only. As of
governance epoch 3 (introduced 2026-04-26), the truth channel is broadened to
`test_* ∪ task_*` and the API surfaces per-channel reliability. The narrow
`test_*` channel was structurally biased toward an under-confidence read because
tests are a high-prior signal — they are run only when expected to pass —
producing an empirical accuracy pinned at 1.0. The broadened channel pairs a
high-prior source (`task_completed`) with a real-failure source (`task_failed`)
so the empirical-accuracy denominator is no longer pinned. A reporting-hygiene
guard (`bad_rate_pinned_to_zero`) raises an alarm if any channel re-pins.
```

- [ ] **Step 3: Commit in the paper repo**

```bash
cd ~/projects/unitares-paper-v6
git add sections/12_limits.md
git commit -m "v6.10: document truth-channel broadening (test_* → test_* ∪ task_*)"
```

If the paper PR cannot land in the same window as the runtime PR, add the feature flag from §6 of the spec (`UNITARES_BROADENED_CALIBRATION=1`) defaulted off in the runtime PR; flip it on after the paper merges.

---

## Task 10: Bump epoch (2 → 3) via canonical script

**Files:**
- Run: `scripts/dev/bump_epoch.py` (existing)

> **Sequencing note:** This task ships as the *last* code change but must be coordinated with deployment. Order per `unitares` repo: merge code (Tasks 1-9), then run `bump_epoch.py`, then run the backfill from Task 7. Restarting governance-mcp between steps is fine — `SequentialCalibrationTracker` migration handles the state file.

- [ ] **Step 1: Verify current epoch**

```bash
psql -h localhost -U postgres -d governance -c "SELECT * FROM core.epochs ORDER BY epoch;"
```

Expected: rows for epoch 1 and 2. If epoch 3 already exists, stop and investigate before proceeding.

- [ ] **Step 2: Dry-run the bump**

```bash
python3 scripts/dev/bump_epoch.py --reason "broadened tactical calibration truth channel — task_* added; per-channel surface in API" --dry-run
```

Expected output: prints "Current epoch: 2 / New epoch: 3" and shows what it *would* do without modifying anything.

- [ ] **Step 3: Bump for real (after Tasks 1-9 merged + governance-mcp restarted)**

```bash
python3 scripts/dev/bump_epoch.py --reason "broadened tactical calibration truth channel — task_* added; per-channel surface in API"
```

Expected:
- `config/governance_config.py::CURRENT_EPOCH` updated 2 → 3.
- New row in `core.epochs` with epoch=3 and the reason.
- Old-epoch baselines cleared.

- [ ] **Step 4: Restart governance-mcp**

```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

- [ ] **Step 5: Verify state file migration ran**

```bash
ls -la data/sequential_calibration_state.* data/sequential_calibration_state.bak.epoch* 2>&1 | head -5
tail -20 data/logs/mcp_server.log | grep -i "epoch"
```

Expected: a `data/sequential_calibration_state.bak.epoch2` file appeared, and the log shows `Calibration epoch changed (2 → 3); archived prior state to ...`.

- [ ] **Step 6: Run the backfill**

```bash
python3 scripts/dev/backfill_tactical_calibration.py --dry-run
# review summary
python3 scripts/dev/backfill_tactical_calibration.py
```

Expected dry-run output: `candidates: ~898 / skipped_no_confidence: ~660 / skipped_unknown_channel: 0` (numbers approximate based on 30-day live data).

- [ ] **Step 7: Verify the dashboard**

```bash
curl -s -X POST http://127.0.0.1:8767/v1/tools/call -H "Content-Type: application/json" \
  -d '{"name":"check_calibration","arguments":{}}' | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print('per_channel:', list(r.get('per_channel_calibration', {}).keys())); print('per_channel_health:', list(r.get('per_channel_health', {}).keys()))"
```

Expected: `per_channel: ['tasks']` (and `'tests'` if any forward inflow; likely empty initially), `per_channel_health: ['tasks', ...]`.

Hard-refresh `http://127.0.0.1:8767/dashboard` and confirm the Calibration card shows per-channel chips.

- [ ] **Step 8: Commit the config bump**

```bash
git add config/governance_config.py
git commit -m "calibration: bump CURRENT_EPOCH 2 → 3 (truth-channel broadening)"
```

---

## Final verification

- [ ] **Step 1: Run full test cache wrapper (per repo CLAUDE.md)**

```bash
./scripts/dev/test-cache.sh
```

Expected: all tests pass; coverage above the 25% gate.

- [ ] **Step 2: Live calibration check**

```bash
curl -s -X POST http://127.0.0.1:8767/v1/tools/call -H "Content-Type: application/json" \
  -d '{"name":"check_calibration","arguments":{}}' | python3 -m json.tool | head -50
```

Expected: response includes `per_channel_calibration.tasks` with non-zero samples and `per_channel_health.tasks.bad_rate > 0`.

- [ ] **Step 3: Ship**

```bash
./scripts/dev/ship.sh "calibration: broaden tactical truth channel + per-channel surface (epoch 2→3)"
```

`ship.sh` will classify as runtime (touches `src/mcp_handlers/`) → opens a PR with auto-merge enabled. After merge, the operator (Kenny) handles paper PR + epoch bump + backfill in production order per Task 10.
