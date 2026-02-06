"""
Tests for src/drift_telemetry.py - DriftSample and DriftTelemetry.

DriftSample.to_dict is pure. DriftTelemetry uses file I/O but we use tmp dir.
"""

import pytest
import json
import sys
from pathlib import Path
from dataclasses import dataclass

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.drift_telemetry import DriftSample, DriftTelemetry


# ============================================================================
# DriftSample
# ============================================================================

class TestDriftSample:

    def test_create(self):
        s = DriftSample(
            timestamp="2026-02-05T12:00:00",
            agent_id="agent-1",
            calibration_deviation=0.1,
            complexity_divergence=0.2,
            coherence_deviation=0.3,
            stability_deviation=0.4,
            norm=0.5,
            norm_squared=0.25,
            update_count=10,
        )
        assert s.agent_id == "agent-1"
        assert s.norm == 0.5

    def test_defaults(self):
        s = DriftSample(
            timestamp="t", agent_id="a",
            calibration_deviation=0, complexity_divergence=0,
            coherence_deviation=0, stability_deviation=0,
            norm=0, norm_squared=0, update_count=0,
        )
        assert s.decision is None
        assert s.confidence is None
        assert s.baseline_coherence is None

    def test_to_dict(self):
        s = DriftSample(
            timestamp="2026-01-01",
            agent_id="test",
            calibration_deviation=0.1,
            complexity_divergence=0.2,
            coherence_deviation=0.3,
            stability_deviation=0.4,
            norm=0.5477,
            norm_squared=0.3,
            update_count=5,
            decision="approve",
            confidence=0.8,
            baseline_coherence=0.6,
            baseline_confidence=0.7,
            baseline_complexity=0.3,
        )
        d = s.to_dict()
        assert d["timestamp"] == "2026-01-01"
        assert d["agent_id"] == "test"
        assert d["calibration_deviation"] == 0.1
        assert d["complexity_divergence"] == 0.2
        assert d["coherence_deviation"] == 0.3
        assert d["stability_deviation"] == 0.4
        assert d["norm"] == 0.5477
        assert d["norm_squared"] == 0.3
        assert d["update_count"] == 5
        assert d["decision"] == "approve"
        assert d["confidence"] == 0.8
        assert d["baseline_coherence"] == 0.6

    def test_to_dict_none_fields(self):
        s = DriftSample(
            timestamp="t", agent_id="a",
            calibration_deviation=0, complexity_divergence=0,
            coherence_deviation=0, stability_deviation=0,
            norm=0, norm_squared=0, update_count=0,
        )
        d = s.to_dict()
        assert d["decision"] is None
        assert d["confidence"] is None
        assert d["baseline_coherence"] is None

    def test_to_dict_is_json_serializable(self):
        s = DriftSample(
            timestamp="t", agent_id="a",
            calibration_deviation=0.1, complexity_divergence=0.2,
            coherence_deviation=0.3, stability_deviation=0.4,
            norm=0.5, norm_squared=0.25, update_count=1,
        )
        json_str = json.dumps(s.to_dict())
        assert isinstance(json_str, str)


# ============================================================================
# DriftTelemetry - init and basic ops
# ============================================================================

class TestDriftTelemetry:

    def test_init_creates_dir(self, tmp_path):
        data_dir = tmp_path / "telemetry"
        dt = DriftTelemetry(data_dir=data_dir)
        assert data_dir.exists()

    def test_drift_file_path(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        assert dt.drift_file == tmp_path / "drift_telemetry.jsonl"

    def test_flush_empty_buffer(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        dt.flush()  # Should not crash with empty buffer
        assert not dt.drift_file.exists()

    def test_record_and_flush(self, tmp_path):
        """Record a sample and verify it gets written to disk."""
        dt = DriftTelemetry(data_dir=tmp_path)
        dt._buffer_size = 100  # Don't auto-flush

        @dataclass
        class MockDriftVector:
            calibration_deviation: float = 0.1
            complexity_divergence: float = 0.2
            coherence_deviation: float = 0.3
            stability_deviation: float = 0.4
            norm: float = 0.5
            norm_squared: float = 0.25

        dt.record(
            drift_vector=MockDriftVector(),
            agent_id="test-agent",
            update_count=1,
            decision="approve",
            confidence=0.8,
        )
        assert len(dt._buffer) == 1

        dt.flush()
        assert len(dt._buffer) == 0
        assert dt.drift_file.exists()

        # Verify content
        with open(dt.drift_file) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["agent_id"] == "test-agent"
            assert data["calibration_deviation"] == 0.1

    def test_auto_flush_at_buffer_size(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        dt._buffer_size = 2

        @dataclass
        class MockDriftVector:
            calibration_deviation: float = 0.0
            complexity_divergence: float = 0.0
            coherence_deviation: float = 0.0
            stability_deviation: float = 0.0
            norm: float = 0.0
            norm_squared: float = 0.0

        # Record 2 samples - should auto-flush
        dt.record(MockDriftVector(), "a1", 1)
        dt.record(MockDriftVector(), "a2", 2)
        assert len(dt._buffer) == 0
        assert dt.drift_file.exists()

    def test_get_recent_empty(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        result = dt.get_recent()
        assert result == []

    def test_get_recent_with_data(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        # Write some data manually
        samples = [
            {"agent_id": "a1", "timestamp": "t1", "norm": 0.1},
            {"agent_id": "a2", "timestamp": "t2", "norm": 0.2},
            {"agent_id": "a1", "timestamp": "t3", "norm": 0.3},
        ]
        with open(dt.drift_file, 'w') as f:
            for s in samples:
                f.write(json.dumps(s) + '\n')

        result = dt.get_recent()
        assert len(result) == 3
        # Most recent first
        assert result[0]["timestamp"] == "t3"

    def test_get_recent_filter_by_agent(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        samples = [
            {"agent_id": "a1", "timestamp": "t1", "norm": 0.1},
            {"agent_id": "a2", "timestamp": "t2", "norm": 0.2},
            {"agent_id": "a1", "timestamp": "t3", "norm": 0.3},
        ]
        with open(dt.drift_file, 'w') as f:
            for s in samples:
                f.write(json.dumps(s) + '\n')

        result = dt.get_recent(agent_id="a1")
        assert len(result) == 2
        assert all(s["agent_id"] == "a1" for s in result)

    def test_get_recent_limit(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        samples = [{"agent_id": "a", "timestamp": f"t{i}", "norm": i * 0.1} for i in range(20)]
        with open(dt.drift_file, 'w') as f:
            for s in samples:
                f.write(json.dumps(s) + '\n')

        result = dt.get_recent(limit=5)
        assert len(result) == 5


# ============================================================================
# DriftTelemetry - get_statistics
# ============================================================================

class TestDriftTelemetryStatistics:

    def test_no_data(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        stats = dt.get_statistics()
        assert stats["total_samples"] == 0
        assert "No telemetry data" in stats["message"]

    def test_with_data(self, tmp_path):
        dt = DriftTelemetry(data_dir=tmp_path)
        samples = []
        for i in range(5):
            samples.append({
                "agent_id": "a1",
                "timestamp": f"t{i}",
                "norm": 0.1 * (i + 1),
                "norm_squared": (0.1 * (i + 1)) ** 2,
                "calibration_deviation": 0.05,
                "complexity_divergence": 0.1,
                "coherence_deviation": 0.15,
                "stability_deviation": 0.2,
            })
        with open(dt.drift_file, 'w') as f:
            for s in samples:
                f.write(json.dumps(s) + '\n')

        stats = dt.get_statistics()
        assert stats["total_samples"] == 5
        assert stats["agent_count"] == 1
        assert "a1" in stats["agents"]
        assert "norm" in stats
        assert stats["norm"]["min"] == 0.1
        assert stats["norm"]["max"] == 0.5

    def test_trend_with_enough_data(self, tmp_path):
        """Trend only computed with >= 10 samples."""
        dt = DriftTelemetry(data_dir=tmp_path)
        # Create 12 samples with decreasing norms (improving)
        samples = []
        for i in range(12):
            samples.append({
                "agent_id": "a1",
                "timestamp": f"t{i}",
                "norm": 1.0 - (i * 0.05),
                "norm_squared": 0,
                "calibration_deviation": 0,
                "complexity_divergence": 0,
                "coherence_deviation": 0,
                "stability_deviation": 0,
            })
        with open(dt.drift_file, 'w') as f:
            for s in samples:
                f.write(json.dumps(s) + '\n')

        stats = dt.get_statistics()
        assert stats["trend"]["improving"] is not None
