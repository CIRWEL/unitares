"""
Tests for src/runtime_config.py - Runtime threshold configuration.

Tests get_thresholds, set_thresholds, get_effective_threshold, clear_overrides.
Uses module-level _runtime_overrides dict (cleaned up after each test).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.runtime_config import (
    get_thresholds,
    set_thresholds,
    get_effective_threshold,
    clear_overrides,
    _runtime_overrides,
)


@pytest.fixture(autouse=True)
def clean_overrides():
    """Ensure overrides are cleared before and after each test."""
    _runtime_overrides.clear()
    yield
    _runtime_overrides.clear()


# ============================================================================
# get_thresholds
# ============================================================================

class TestGetThresholds:

    def test_returns_dict(self):
        result = get_thresholds()
        assert isinstance(result, dict)

    def test_contains_expected_keys(self):
        result = get_thresholds()
        expected = {
            "risk_approve_threshold",
            "risk_revise_threshold",
            "coherence_critical_threshold",
            "void_threshold_initial",
            "void_threshold_min",
            "void_threshold_max",
            "lambda1_min",
            "lambda1_max",
            "target_coherence",
            "target_void_freq",
        }
        assert expected.issubset(set(result.keys()))

    def test_values_are_floats(self):
        result = get_thresholds()
        for key, value in result.items():
            assert isinstance(value, (int, float)), f"{key} is not numeric: {type(value)}"

    def test_reflects_overrides(self):
        _runtime_overrides["risk_approve_threshold"] = 0.99
        result = get_thresholds()
        assert result["risk_approve_threshold"] == 0.99


# ============================================================================
# set_thresholds
# ============================================================================

class TestSetThresholds:

    def test_set_valid_threshold(self):
        result = set_thresholds({"risk_approve_threshold": 0.3})
        assert result["success"] is True
        assert "risk_approve_threshold" in result["updated"]

    def test_set_unknown_threshold(self):
        result = set_thresholds({"nonexistent_threshold": 0.5})
        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert "Unknown threshold" in result["errors"][0]

    def test_set_out_of_range(self):
        result = set_thresholds({"risk_approve_threshold": 1.5})
        assert result["success"] is False
        assert any("out of range" in e for e in result["errors"])

    def test_set_negative_rejected(self):
        result = set_thresholds({"risk_approve_threshold": -0.1})
        assert result["success"] is False

    def test_set_multiple(self):
        result = set_thresholds({
            "risk_approve_threshold": 0.2,
            "coherence_critical_threshold": 0.3,
        })
        assert result["success"] is True
        assert len(result["updated"]) == 2

    def test_set_persists_in_overrides(self):
        set_thresholds({"risk_approve_threshold": 0.42})
        assert _runtime_overrides["risk_approve_threshold"] == 0.42

    def test_skip_validation(self):
        result = set_thresholds({"risk_approve_threshold": 999.0}, validate=False)
        assert result["success"] is True

    def test_partial_failure(self):
        result = set_thresholds({
            "risk_approve_threshold": 0.2,
            "fake_threshold": 0.5,
        })
        # One succeeds, one fails
        assert "risk_approve_threshold" in result["updated"]
        assert len(result["errors"]) > 0
        assert result["success"] is False


# ============================================================================
# get_effective_threshold
# ============================================================================

class TestGetEffectiveThreshold:

    def test_default_value(self):
        val = get_effective_threshold("risk_approve_threshold")
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0

    def test_with_override(self):
        _runtime_overrides["risk_approve_threshold"] = 0.77
        val = get_effective_threshold("risk_approve_threshold")
        assert val == 0.77

    def test_known_thresholds(self):
        for name in ["risk_approve_threshold", "risk_revise_threshold",
                     "coherence_critical_threshold", "void_threshold_initial"]:
            val = get_effective_threshold(name)
            assert isinstance(val, float)

    def test_unknown_threshold_raises(self):
        with pytest.raises(ValueError, match="Unknown threshold"):
            get_effective_threshold("nonexistent")

    def test_unknown_threshold_with_default(self):
        val = get_effective_threshold("nonexistent", default=0.5)
        assert val == 0.5


# ============================================================================
# clear_overrides
# ============================================================================

class TestClearOverrides:

    def test_clears_all(self):
        _runtime_overrides["risk_approve_threshold"] = 0.5
        _runtime_overrides["coherence_critical_threshold"] = 0.3
        clear_overrides()
        assert len(_runtime_overrides) == 0

    def test_clear_empty(self):
        clear_overrides()  # Should not crash
        assert len(_runtime_overrides) == 0

    def test_thresholds_revert_after_clear(self):
        original = get_thresholds()
        set_thresholds({"risk_approve_threshold": 0.99})
        clear_overrides()
        reverted = get_thresholds()
        assert reverted["risk_approve_threshold"] == original["risk_approve_threshold"]
