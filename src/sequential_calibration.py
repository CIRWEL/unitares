"""
Sequential calibration evidence for hard exogenous tactical outcomes.

This module tracks an anytime-valid e-process against the null that each
reported confidence value matches the Bernoulli rate of an observed hard
exogenous outcome. It is intentionally narrow:

- tactical only (decision-time binary outcomes)
- exogenous only (tests, commands, files, lint, tool-result evidence)
- observational only (no governance coupling here)

We expose a bounded alarm transform for operator use and keep the raw
e-process internal to the tracker.

Null and construction
---------------------
- Null H0: for each eligible sample n, Y_n ~ Bernoulli(p_n) where p_n is
  the confidence reported by the agent before the outcome was observable.
  This is a sequential composite null — p_n varies across samples — not a
  single fixed Bernoulli.
- Alternative: Beta-Bernoulli predictive plug-in. q_n is the posterior
  mean of the success rate after n-1 observations, using a Beta(prior_success,
  prior_failure) prior (default Beta(1, 1)).
- Per-sample e-value: e_n = (q_n / p_n) if Y_n = 1 else ((1 - q_n) / (1 - p_n)).
  Clamped to avoid degenerate 0/1 confidences.
- q_n is computed from the state *before* the current sample is folded in,
  making the bet F_{n-1}-measurable. Under H0, E[e_n | F_{n-1}] = 1, so the
  running product is a nonnegative martingale with mean 1 and the cumulative
  log is a valid e-process for anytime-valid testing.
- The exposed alarm metric is capped_alarm = 1 - exp(-max(0, log_e_value)),
  which lives in [0, 1). log_evidence is similarly clamped at 0 from below
  so favorable trajectories do not produce negative alarms. Raw e-values
  remain internal to the tracker and are not exposed as governance state.

Known limitations
-----------------
- No prediction_id seam yet. Reported confidences are attached to outcomes
  via explicit argument or a monitor-level `_prev_confidence` fallback
  resolved at outcome time (see
  src/mcp_handlers/observability/outcome_events.py). This is sufficient when
  an agent has at most one tactical prediction in flight per outcome window,
  but degrades to approximate temporal matching when multiple predictions
  overlap. The filtration is therefore approximate, not exact, and forensic
  replay from an alarm back to the specific (confidence, outcome) pair is
  not guaranteed. A prediction_id seam is phase-two work and is required
  before composing this e-process with knowledge-graph or dialectic
  evidence streams.
- Global and per-agent trackers update from the same samples. Each is
  individually a valid e-process under H0, but they are correlated by
  construction and must not be multiplied together.
- prior_success / prior_failure are constructor parameters but are not
  wired to configuration in v1. Defaults (Beta(1, 1)) are intentional and
  should not be tuned without also reviewing downstream alarm thresholds.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional
import json
import math
import sys
from datetime import datetime, UTC

from config.governance_config import GovernanceConfig


def _empty_state() -> Dict[str, Any]:
    return {
        "eligible_samples": 0,
        "successes": 0,
        "confidence_sum": 0.0,
        "log_e_value": 0.0,
        "last_e_value": 1.0,
        "last_alt_probability": 0.5,
        "signal_sources": {},
        # Per-channel hygiene tracking — {channel: {samples: int, successes: int}}
        # Used by compute_per_channel_health to flag bad_rate_pinned_to_zero.
        "signal_source_outcomes": {},
        "last_updated": None,
    }


class SequentialCalibrationTracker:
    """Track exogenous tactical evidence with a predictable Bernoulli e-process."""

    def __init__(
        self,
        state_file: Path | None = None,
        *,
        prior_success: float = 1.0,
        prior_failure: float = 1.0,
    ):
        if state_file is None:
            state_file = Path(__file__).parent.parent / "data" / "sequential_calibration_state.json"
        self.state_file = Path(state_file)
        self.prior_success = float(prior_success)
        self.prior_failure = float(prior_failure)
        self.load_state()

    def reset(self) -> None:
        self.global_state = _empty_state()
        self.agent_states = defaultdict(_empty_state)

    def _serialize(self) -> Dict[str, Any]:
        return {
            "global": dict(self.global_state),
            "agents": {agent_id: dict(state) for agent_id, state in self.agent_states.items()},
            "prior_success": self.prior_success,
            "prior_failure": self.prior_failure,
            "epoch": GovernanceConfig.CURRENT_EPOCH,
        }

    def save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self._serialize(), f, indent=2)
            self._loaded_mtime = self._file_mtime()
        except Exception as e:
            print(f"Warning: Failed to save sequential calibration state: {e}", file=sys.stderr)

    def _file_mtime(self) -> float:
        try:
            return self.state_file.stat().st_mtime if self.state_file.exists() else 0.0
        except OSError:
            return 0.0

    def _reload_if_stale(self) -> None:
        """Reload from disk if the file was updated externally (e.g. by backfill)."""
        current_mtime = self._file_mtime()
        if current_mtime > getattr(self, "_loaded_mtime", 0.0):
            self.load_state()

    def load_state(self) -> None:
        try:
            if not self.state_file.exists():
                self.reset()
                self._loaded_mtime = 0.0
                return
            with open(self.state_file, "r") as f:
                data = json.load(f)

            # Epoch migration: when the truth-channel definition changes (or any
            # other governance epoch bump), historical state is no longer
            # comparable. Archive and reset rather than silently reinterpret.
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

    @staticmethod
    def _clamp_probability(value: float) -> float:
        return min(1.0 - 1e-6, max(1e-6, float(value)))

    def _predictive_alt_probability(self, state: Dict[str, Any]) -> float:
        total = float(state["eligible_samples"])
        successes = float(state["successes"])
        q = (self.prior_success + successes) / (self.prior_success + self.prior_failure + total)
        return self._clamp_probability(q)

    def _update_state(
        self,
        state: Dict[str, Any],
        *,
        confidence: float,
        outcome_correct: bool,
        signal_source: str,
        timestamp: str,
    ) -> Dict[str, float]:
        # Betting martingale step. See module docstring for the null and
        # construction. q is computed from the pre-update state to preserve
        # F_{n-1}-measurability; the state increments happen after e_value.
        p = self._clamp_probability(confidence)
        y = 1.0 if outcome_correct else 0.0
        q = self._predictive_alt_probability(state)
        e_value = (q / p) if y == 1.0 else ((1.0 - q) / (1.0 - p))
        e_value = max(e_value, 1e-12)

        state["eligible_samples"] += 1
        state["successes"] += int(y)
        state["confidence_sum"] += p
        state["log_e_value"] += math.log(e_value)
        state["last_e_value"] = e_value
        state["last_alt_probability"] = q
        state["last_updated"] = timestamp

        signal_sources = state.setdefault("signal_sources", {})
        signal_sources[signal_source] = int(signal_sources.get(signal_source, 0)) + 1

        # Per-channel sample/success tracking for the hygiene guard
        # (bad_rate_pinned_to_zero in compute_per_channel_health).
        source_outcomes = state.setdefault("signal_source_outcomes", {})
        ch_outcomes = source_outcomes.setdefault(signal_source, {"samples": 0, "successes": 0})
        ch_outcomes["samples"] = int(ch_outcomes.get("samples", 0)) + 1
        if y == 1.0:
            ch_outcomes["successes"] = int(ch_outcomes.get("successes", 0)) + 1

        return {
            "p": p,
            "q": q,
            "e_value": e_value,
            "log_e_value": state["log_e_value"],
        }

    def record_exogenous_tactical_outcome(
        self,
        *,
        confidence: float,
        outcome_correct: bool,
        agent_id: Optional[str] = None,
        signal_source: str,
        decision_action: Optional[str] = None,
        outcome_type: Optional[str] = None,
        timestamp: Optional[str] = None,
        prediction_id: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Record one eligible hard exogenous tactical outcome.

        prediction_id, if provided, is included in the return payload for
        forensic audit. The tracker state itself remains aggregate and is
        not indexed by prediction_id.
        """
        if not signal_source:
            raise ValueError("signal_source is required")

        ts = timestamp or datetime.now(UTC).isoformat()

        global_update = self._update_state(
            self.global_state,
            confidence=confidence,
            outcome_correct=outcome_correct,
            signal_source=signal_source,
            timestamp=ts,
        )

        agent_update = None
        if agent_id:
            agent_update = self._update_state(
                self.agent_states[agent_id],
                confidence=confidence,
                outcome_correct=outcome_correct,
                signal_source=signal_source,
                timestamp=ts,
            )

        if persist:
            self.save_state()

        return {
            "agent_id": agent_id,
            "prediction_id": prediction_id,
            "decision_action": decision_action,
            "outcome_type": outcome_type,
            "signal_source": signal_source,
            "global": global_update,
            "agent": agent_update,
        }

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

    def compute_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return bounded, operator-friendly metrics for the tracked e-process."""
        self._reload_if_stale()
        if agent_id:
            state = self.agent_states.get(agent_id)
            if not state:
                return {
                    "status": "no_data",
                    "eligible_samples": 0,
                    "scope": "agent",
                    "agent_id": agent_id,
                    "signal_sources": {},
                    "log_evidence": 0.0,
                    "capped_alarm": 0.0,
                }
            scope = "agent"
        else:
            state = self.global_state
            scope = "global"

        total = int(state["eligible_samples"])
        positive_log = max(0.0, float(state["log_e_value"]))

        if total == 0:
            return {
                "status": "no_data",
                "eligible_samples": 0,
                "scope": scope,
                "agent_id": agent_id,
                "signal_sources": dict(state.get("signal_sources", {})),
                "log_evidence": 0.0,
                "capped_alarm": 0.0,
            }

        mean_confidence = float(state["confidence_sum"]) / total
        empirical_accuracy = float(state["successes"]) / total
        calibration_gap = empirical_accuracy - mean_confidence

        return {
            "status": "tracking",
            "scope": scope,
            "agent_id": agent_id,
            "eligible_samples": total,
            "mean_confidence": round(mean_confidence, 4),
            "empirical_accuracy": round(empirical_accuracy, 4),
            "calibration_gap": round(calibration_gap, 4),
            "log_evidence": round(positive_log, 4),
            "capped_alarm": round(1.0 - math.exp(-positive_log), 4),
            "last_alt_probability": round(float(state["last_alt_probability"]), 4),
            "signal_sources": dict(state.get("signal_sources", {})),
            "last_updated": state.get("last_updated"),
        }


_sequential_calibration_tracker_instance: SequentialCalibrationTracker | None = None


def get_sequential_calibration_tracker() -> SequentialCalibrationTracker:
    global _sequential_calibration_tracker_instance
    if _sequential_calibration_tracker_instance is None:
        _sequential_calibration_tracker_instance = SequentialCalibrationTracker()
    return _sequential_calibration_tracker_instance


class _SequentialCalibrationTrackerProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_sequential_calibration_tracker(), name)


sequential_calibration_tracker = _SequentialCalibrationTrackerProxy()
