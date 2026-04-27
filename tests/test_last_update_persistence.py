"""
Tests for cross-restart persistence of UNITARESMonitor.last_update.

Council finding (2026-04-27): self.last_update is set in __init__ at
governance_monitor.py:131 but never serialized in save_persisted_state.
Combined with lazy monitor construction in agent_lifecycle.py:21-56, this
silently freezes cross-restart gaps to ~0 — a 17-hour overnight gap
integrates as 0.5s of decay, losing decay terms (μ·S, δ·V) that should
have integrated.

Also covers:
- NTP-backward-jump clamp (negative elapsed_seconds guard)
- Saturation log line when effective_dt clips to DT_MAX
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor
from config.governance_config import config


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect ensure_project_root to tmp_path so state files are isolated."""
    import src._imports
    monkeypatch.setattr(src._imports, 'ensure_project_root', lambda: str(tmp_path))
    (tmp_path / "data" / "agents").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_one_update(monitor):
    """Run one process_update so save has something to persist."""
    monitor.process_update({
        "response_text": "seed",
        "complexity": 0.3,
        "parameters": [0.5] * 128,
    })


class TestLastUpdatePersistence:

    def test_last_update_persists_across_save_load_roundtrip(self, isolated_data_dir):
        """save_persisted_state must serialize last_update; load_persisted_state must restore it."""
        monitor = UNITARESMonitor(agent_id="persist_roundtrip", load_state=False)
        _write_one_update(monitor)

        # Pin last_update to a known value distinct from "now"
        pinned = datetime(2026, 4, 26, 17, 0, 0)
        monitor.last_update = pinned

        monitor.save_persisted_state()

        monitor2 = UNITARESMonitor(agent_id="persist_roundtrip", load_state=True)
        assert monitor2.last_update == pinned, (
            f"last_update should round-trip; got {monitor2.last_update!r}, expected {pinned!r}"
        )

    def test_persisted_json_contains_last_update_iso_field(self, isolated_data_dir):
        """The serialized JSON must include an ISO timestamp at a stable key."""
        monitor = UNITARESMonitor(agent_id="json_shape", load_state=False)
        _write_one_update(monitor)
        monitor.last_update = datetime(2026, 4, 26, 17, 0, 0)
        monitor.save_persisted_state()

        state_file = isolated_data_dir / "data" / "agents" / "json_shape_state.json"
        data = json.loads(state_file.read_text())
        assert "last_update_iso" in data, (
            f"State JSON missing last_update_iso. Keys present: {sorted(data.keys())}"
        )
        # Must be ISO-parseable
        parsed = datetime.fromisoformat(data["last_update_iso"])
        assert parsed == datetime(2026, 4, 26, 17, 0, 0)

    def test_load_with_absent_last_update_falls_back_to_now(self, isolated_data_dir):
        """Backward compat: old state files without last_update_iso must not crash."""
        # Hand-write a legacy-format state file with no last_update_iso
        legacy_file = isolated_data_dir / "data" / "agents" / "legacy_agent_state.json"
        legacy_payload = {
            "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0,
            "coherence": 0.5, "lambda1": 0.4, "void_active": False,
            "time": 0.0, "update_count": 0,
            "unitaires_state": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0},
            "unitaires_theta": {"C1": 1.0, "eta1": 0.5},
            "regime": "divergence",
            "regime_history": [],
            "locked_persistence_count": 0,
            "E_history": [], "I_history": [], "S_history": [], "V_history": [],
            "coherence_history": [], "risk_history": [], "lambda1_history": [],
            "decision_history": [], "verdict_history": [], "timestamp_history": [],
            "pi_integral": 0.0,
            "rho_history": [], "CE_history": [], "current_rho": 0.0,
            "oi_history": [], "resonance_events": 0,
            "damping_applied_count": 0, "lambda1_update_skips": 0,
        }
        legacy_file.write_text(json.dumps(legacy_payload))

        before = datetime.now()
        monitor = UNITARESMonitor(agent_id="legacy_agent", load_state=True)
        after = datetime.now()

        # Fallback should be roughly "now" (no crash, reasonable default)
        assert monitor.last_update is not None
        assert before <= monitor.last_update <= after, (
            f"Legacy fallback should be ~now; got {monitor.last_update!r} "
            f"outside [{before!r}, {after!r}]"
        )


class TestEffectiveDtIsGapHonored:
    """After persistence, a long real gap must produce a non-trivial dt."""

    def _capture_dt_on_next_update(self, monitor):
        """Spy: run process_update once, return the dt passed to update_dynamics."""
        captured = {}
        original = monitor.update_dynamics

        def spy(*args, **kwargs):
            captured["dt"] = kwargs.get("dt")
            return original(*args, **kwargs)

        monitor.update_dynamics = spy
        monitor.process_update({
            "response_text": "after_long_gap",
            "complexity": 0.3,
            "parameters": [0.5] * 128,
        })
        return captured["dt"]

    def test_long_persisted_gap_clips_to_dt_max_not_floor(self, isolated_data_dir):
        """A 17h persisted gap must reach DT_MAX, not collapse to DT floor."""
        monitor = UNITARESMonitor(agent_id="long_gap", load_state=False)
        _write_one_update(monitor)
        # Pin last_update to 17 hours ago
        monitor.last_update = datetime.now() - timedelta(hours=17)
        monitor.save_persisted_state()

        # Reload — simulates server restart
        monitor2 = UNITARESMonitor(agent_id="long_gap", load_state=True)
        dt_seen = self._capture_dt_on_next_update(monitor2)

        assert dt_seen == pytest.approx(config.DT_MAX, abs=1e-9), (
            f"17h gap should saturate to DT_MAX={config.DT_MAX}, got dt={dt_seen}"
        )

    def test_short_gap_uses_dt_floor(self, isolated_data_dir):
        """Sub-cadence gap (1s) must clip up to the DT floor."""
        monitor = UNITARESMonitor(agent_id="short_gap", load_state=False)
        _write_one_update(monitor)
        monitor.last_update = datetime.now() - timedelta(seconds=1)
        dt_seen = TestEffectiveDtIsGapHonored._capture_dt_on_next_update(self, monitor)

        # 1s * 0.1/15 = 0.0067, floored to DT=0.1
        assert dt_seen == pytest.approx(config.DT, abs=1e-9), (
            f"1s gap should hit DT floor={config.DT}, got dt={dt_seen}"
        )


class TestNtpBackwardClamp:

    def test_negative_elapsed_clamps_to_dt_floor(self, isolated_data_dir):
        """NTP step-back (last_update in future) must not produce negative dt."""
        monitor = UNITARESMonitor(agent_id="ntp_back", load_state=False)
        _write_one_update(monitor)
        # Pin last_update to 30s in the future
        monitor.last_update = datetime.now() + timedelta(seconds=30)

        captured = {}
        original = monitor.update_dynamics

        def spy(*args, **kwargs):
            captured["dt"] = kwargs.get("dt")
            return original(*args, **kwargs)

        monitor.update_dynamics = spy
        monitor.process_update({
            "response_text": "after_ntp_back",
            "complexity": 0.3,
            "parameters": [0.5] * 128,
        })

        assert captured["dt"] == pytest.approx(config.DT, abs=1e-9), (
            f"Negative elapsed should clamp to DT={config.DT}, got dt={captured['dt']}"
        )
        assert captured["dt"] >= 0, "dt must never be negative"


class TestSaturationLog:

    def test_saturation_emits_log_line(self, isolated_data_dir, caplog):
        """When effective_dt clips to DT_MAX, an info-level log line must mention saturation."""
        monitor = UNITARESMonitor(agent_id="sat_log", load_state=False)
        _write_one_update(monitor)
        monitor.last_update = datetime.now() - timedelta(hours=17)

        with caplog.at_level(logging.INFO, logger="src.governance_monitor"):
            monitor.process_update({
                "response_text": "saturating",
                "complexity": 0.3,
                "parameters": [0.5] * 128,
            })

        saturation_lines = [
            r for r in caplog.records
            if "saturat" in r.getMessage().lower()
            or "dt_max" in r.getMessage().lower()
        ]
        assert saturation_lines, (
            f"Expected a saturation log line; saw: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_no_saturation_log_for_normal_gap(self, isolated_data_dir, caplog):
        """A normal 15s-cadence gap must NOT emit a saturation log line."""
        monitor = UNITARESMonitor(agent_id="no_sat", load_state=False)
        _write_one_update(monitor)
        monitor.last_update = datetime.now() - timedelta(seconds=15)

        with caplog.at_level(logging.INFO, logger="src.governance_monitor"):
            monitor.process_update({
                "response_text": "normal_cadence",
                "complexity": 0.3,
                "parameters": [0.5] * 128,
            })

        saturation_lines = [
            r for r in caplog.records
            if "saturat" in r.getMessage().lower()
            or "dt_max" in r.getMessage().lower()
        ]
        assert not saturation_lines, (
            f"Normal-cadence gap should not emit saturation log; saw: "
            f"{[r.getMessage() for r in saturation_lines]}"
        )
