"""
Tests for src/eisv_validator.py - EISV response validation.

All pure validation functions, no mocking needed.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.eisv_validator import (
    IncompleteEISVError,
    validate_eisv_in_dict,
    validate_governance_response,
    validate_csv_row,
    validate_state_file,
    auto_validate_response,
    VALIDATION_ENABLED,
)


# --- validate_eisv_in_dict Tests ---


class TestValidateEISVInDict:

    def test_valid_complete(self):
        warnings = validate_eisv_in_dict({"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07})
        assert warnings == []

    def test_missing_v(self):
        with pytest.raises(IncompleteEISVError, match="Missing.*V"):
            validate_eisv_in_dict({"E": 0.8, "I": 1.0, "S": 0.03})

    def test_missing_multiple(self):
        with pytest.raises(IncompleteEISVError, match="Missing"):
            validate_eisv_in_dict({"E": 0.8})

    def test_empty_dict(self):
        with pytest.raises(IncompleteEISVError):
            validate_eisv_in_dict({})

    def test_none_values_rejected(self):
        with pytest.raises(IncompleteEISVError, match="None values"):
            validate_eisv_in_dict({"E": 0.8, "I": 1.0, "S": 0.03, "V": None})

    def test_multiple_none_values(self):
        with pytest.raises(IncompleteEISVError, match="None"):
            validate_eisv_in_dict({"E": None, "I": None, "S": 0.03, "V": 0.0})

    def test_extra_keys_ok(self):
        warnings = validate_eisv_in_dict({
            "E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07,
            "coherence": 0.47, "risk": 0.3
        })
        assert warnings == []

    def test_context_in_error_message(self):
        with pytest.raises(IncompleteEISVError, match="my_context"):
            validate_eisv_in_dict({"E": 0.8}, context="my_context")

    def test_zero_values_valid(self):
        """Zero is a valid numeric value, not None."""
        warnings = validate_eisv_in_dict({"E": 0.0, "I": 0.0, "S": 0.0, "V": 0.0})
        assert warnings == []


# --- validate_governance_response Tests ---


class TestValidateGovernanceResponse:

    def test_valid_response(self):
        response = {
            "success": True,
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07}
        }
        validate_governance_response(response)  # Should not raise

    def test_no_metrics_section(self):
        """Response without metrics should not raise (e.g., error responses)."""
        response = {"success": False, "error": "something failed"}
        validate_governance_response(response)  # Should not raise

    def test_incomplete_metrics_raises(self):
        response = {
            "success": True,
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03}  # Missing V
        }
        with pytest.raises(IncompleteEISVError):
            validate_governance_response(response)

    def test_none_metric_raises(self):
        response = {
            "success": True,
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03, "V": None}
        }
        with pytest.raises(IncompleteEISVError):
            validate_governance_response(response)

    def test_valid_with_eisv_labels(self):
        response = {
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07},
            "eisv_labels": {"E": "Energy", "I": "Integrity", "S": "Entropy", "V": "Void"}
        }
        validate_governance_response(response)  # Should not raise

    def test_incomplete_eisv_labels_warns(self):
        """Incomplete labels should warn but not raise."""
        response = {
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07},
            "eisv_labels": {"E": "Energy", "I": "Integrity"}  # Missing S, V
        }
        # Should not raise - labels are just a warning
        validate_governance_response(response)


# --- validate_csv_row Tests ---


class TestValidateCSVRow:

    def test_valid_row(self):
        validate_csv_row({"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07}, row_num=1)

    def test_invalid_row(self):
        with pytest.raises(IncompleteEISVError, match="CSV row 5"):
            validate_csv_row({"E": 0.8}, row_num=5)


# --- validate_state_file Tests ---


class TestValidateStateFile:

    def test_valid_state(self):
        validate_state_file(
            {"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07},
            filename="agent_state.json"
        )

    def test_invalid_state(self):
        with pytest.raises(IncompleteEISVError, match="state file my_state.json"):
            validate_state_file({"E": 0.8}, filename="my_state.json")


# --- auto_validate_response Tests ---


class TestAutoValidateResponse:

    def test_valid_passes_through(self):
        response = {
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07}
        }
        result = auto_validate_response(response)
        assert result is response  # Same object

    def test_invalid_raises_and_annotates(self):
        response = {
            "metrics": {"E": 0.8, "I": 1.0, "S": 0.03}  # Missing V
        }
        with pytest.raises(IncompleteEISVError):
            auto_validate_response(response)
        # Should have annotated the response
        assert "_eisv_validation_error" in response

    def test_no_metrics_passes_through(self):
        response = {"success": True}
        result = auto_validate_response(response)
        assert result is response


# --- IncompleteEISVError Tests ---


class TestIncompleteEISVError:

    def test_is_value_error(self):
        """Should be a subclass of ValueError."""
        assert issubclass(IncompleteEISVError, ValueError)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(IncompleteEISVError):
            raise IncompleteEISVError("test error")

    def test_caught_by_value_error(self):
        with pytest.raises(ValueError):
            raise IncompleteEISVError("test error")
