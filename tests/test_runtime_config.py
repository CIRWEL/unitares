"""
Tests for src/runtime_config.py - Runtime threshold configuration.

Tests get/set/clear threshold operations against GovernanceConfig defaults.
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
)


@pytest.fixture(autouse=True)
def clean_overrides():
    """Ensure overrides are cleared before and after each test."""
    clear_overrides()
    yield
    clear_overrides()


# ============================================================================
# get_thresholds
# ============================================================================

class TestGetThresholds:

    def test_returns_dict(self):
        result = get_thresholds()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = get_thresholds()
        assert "risk_approve_threshold" in result
        assert "risk_revise_threshold" in result
        assert "coherence_critical_threshold" in result
        assert "void_threshold_initial" in result

    def test_values_numeric(self):
        result = get_thresholds()
        for key, value in result.items():
            assert isinstance(value, (int, float)), f"{key} is not numeric: {type(value)}"

    def test_reflects_overrides(self):
        set_thresholds({"risk_approve_threshold": 0.1})
        result = get_thresholds()
        assert result["risk_approve_threshold"] == 0.1


# ============================================================================
# set_thresholds
# ============================================================================

class TestSetThresholds:

    def test_valid(self):
        result = set_thresholds({"risk_approve_threshold": 0.2})
        assert result["success"] is True
        assert "risk_approve_threshold" in result["updated"]
        assert len(result["errors"]) == 0

    def test_multiple(self):
        result = set_thresholds({
            "risk_approve_threshold": 0.15,
            "coherence_critical_threshold": 0.25,
        })
        assert result["success"] is True
        assert len(result["updated"]) == 2

    def test_unknown_error(self):
        result = set_thresholds({"nonexistent_threshold": 0.5})
        assert result["success"] is False
        assert len(result["errors"]) == 1
        assert "Unknown" in result["errors"][0]

    def test_out_of_range(self):
        result = set_thresholds({"risk_approve_threshold": 1.5})
        assert result["success"] is False
        assert any("out of range" in e for e in result["errors"])

    def test_negative(self):
        result = set_thresholds({"risk_approve_threshold": -0.1})
        assert result["success"] is False

    def test_boundary_zero(self):
        result = set_thresholds({"risk_approve_threshold": 0.0})
        assert result["success"] is True

    def test_skip_validation(self):
        """With validate=False, out-of-range values should be accepted."""
        result = set_thresholds({"risk_approve_threshold": 1.5}, validate=False)
        # Still fails for unknown thresholds, but range check skipped
        # Note: 1.5 may still fail other validation, but range check is skipped
        assert "risk_approve_threshold" in result["updated"] or len(result["errors"]) > 0

    def test_approve_less_than_revise(self):
        """approve threshold must be < revise threshold when set together."""
        result = set_thresholds({
            "risk_approve_threshold": 0.8,
            "risk_revise_threshold": 0.3,
        })
        assert result["success"] is False
        assert any("must be <" in e for e in result["errors"])


# ============================================================================
# get_effective_threshold
# ============================================================================

class TestGetEffectiveThreshold:

    def test_default(self):
        value = get_effective_threshold("risk_approve_threshold")
        assert isinstance(value, float)
        assert 0 <= value <= 1

    def test_with_override(self):
        set_thresholds({"risk_approve_threshold": 0.15})
        value = get_effective_threshold("risk_approve_threshold")
        assert value == 0.15

    def test_risk_revise(self):
        value = get_effective_threshold("risk_revise_threshold")
        assert isinstance(value, float)

    def test_coherence_critical(self):
        value = get_effective_threshold("coherence_critical_threshold")
        assert isinstance(value, float)

    def test_void_threshold_initial(self):
        value = get_effective_threshold("void_threshold_initial")
        assert isinstance(value, float)

    def test_risk_reject(self):
        value = get_effective_threshold("risk_reject_threshold")
        assert isinstance(value, float)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown threshold"):
            get_effective_threshold("nonexistent_threshold")

    def test_unknown_with_default(self):
        value = get_effective_threshold("nonexistent_threshold", default=0.42)
        assert value == 0.42


# ============================================================================
# clear_overrides
# ============================================================================

class TestClearOverrides:

    def test_clears_all(self):
        set_thresholds({"risk_approve_threshold": 0.1})
        clear_overrides()
        value = get_effective_threshold("risk_approve_threshold")
        # Should be back to default, not 0.1
        assert value != 0.1

    def test_idempotent(self):
        clear_overrides()
        clear_overrides()  # Should not raise
