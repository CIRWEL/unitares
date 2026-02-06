"""
Tests for src/auto_ground_truth.py - Automated Ground Truth Collection

Tests the objective outcome evaluators (pure functions, no external deps).
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.auto_ground_truth import (
    evaluate_test_outcome,
    evaluate_command_outcome,
    evaluate_file_operation,
    evaluate_lint_outcome,
    evaluate_objective_outcomes,
    evaluate_decision_outcome,
)


# --- evaluate_test_outcome Tests ---


class TestEvaluateTestOutcome:
    """Tests for evaluate_test_outcome()."""

    def test_none_input(self):
        assert evaluate_test_outcome(None) is None

    def test_empty_dict(self):
        assert evaluate_test_outcome({}) is None

    def test_exit_code_zero(self):
        assert evaluate_test_outcome({"exit_code": 0}) is True

    def test_exit_code_nonzero(self):
        assert evaluate_test_outcome({"exit_code": 1}) is False

    def test_passed_count(self):
        assert evaluate_test_outcome({"passed": 10, "failed": 0}) is True

    def test_failed_count(self):
        assert evaluate_test_outcome({"passed": 5, "failed": 2}) is False

    def test_errors_count(self):
        assert evaluate_test_outcome({"passed": 5, "errors": 1}) is False

    def test_exit_code_takes_priority(self):
        """exit_code should be checked first."""
        assert evaluate_test_outcome({"exit_code": 0, "failed": 5}) is True
        assert evaluate_test_outcome({"exit_code": 1, "passed": 10}) is False

    def test_no_test_results(self):
        assert evaluate_test_outcome({"other": "data"}) is None


# --- evaluate_command_outcome Tests ---


class TestEvaluateCommandOutcome:
    """Tests for evaluate_command_outcome()."""

    def test_none_input(self):
        assert evaluate_command_outcome(None) is None

    def test_empty_dict(self):
        assert evaluate_command_outcome({}) is None

    def test_success_true(self):
        assert evaluate_command_outcome({"success": True}) is True

    def test_success_false(self):
        assert evaluate_command_outcome({"success": False}) is False

    def test_exit_code_zero(self):
        assert evaluate_command_outcome({"exit_code": 0}) is True

    def test_exit_code_nonzero(self):
        assert evaluate_command_outcome({"exit_code": 2}) is False

    def test_error_field(self):
        assert evaluate_command_outcome({"error": "something broke"}) is False

    def test_success_flag_takes_priority(self):
        assert evaluate_command_outcome({"success": True, "error": "ignored"}) is True


# --- evaluate_file_operation Tests ---


class TestEvaluateFileOperation:
    """Tests for evaluate_file_operation()."""

    def test_existing_file_expected_exists(self):
        # Use this test file itself
        assert evaluate_file_operation(__file__, expected_exists=True) is True

    def test_existing_file_expected_not_exists(self):
        assert evaluate_file_operation(__file__, expected_exists=False) is False

    def test_nonexistent_file_expected_exists(self):
        assert evaluate_file_operation("/nonexistent/path/xyz.txt", expected_exists=True) is False

    def test_nonexistent_file_expected_not_exists(self):
        assert evaluate_file_operation("/nonexistent/path/xyz.txt", expected_exists=False) is True

    def test_with_temp_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            assert evaluate_file_operation(path, expected_exists=True) is True
        finally:
            os.unlink(path)


# --- evaluate_lint_outcome Tests ---


class TestEvaluateLintOutcome:
    """Tests for evaluate_lint_outcome()."""

    def test_none_input(self):
        assert evaluate_lint_outcome(None) is None

    def test_empty_dict(self):
        # Empty dict has no 'errors' key, errors defaults to 0, but
        # the function checks `if lint_result:` which is False for empty dict
        assert evaluate_lint_outcome({}) is None

    def test_no_errors(self):
        assert evaluate_lint_outcome({"errors": 0, "warnings": 3}) is True

    def test_errors_present(self):
        assert evaluate_lint_outcome({"errors": 5}) is False

    def test_error_count_key(self):
        assert evaluate_lint_outcome({"error_count": 2}) is False

    def test_errors_as_list(self):
        assert evaluate_lint_outcome({"errors": ["err1", "err2"]}) is False

    def test_errors_as_empty_list(self):
        assert evaluate_lint_outcome({"errors": []}) is True


# --- evaluate_objective_outcomes Tests ---


class TestEvaluateObjectiveOutcomes:
    """Tests for evaluate_objective_outcomes() composite evaluator."""

    def test_empty_outcomes(self):
        assert evaluate_objective_outcomes({}) is None

    def test_all_pass(self):
        outcomes = {
            "tests": {"exit_code": 0},
            "commands": {"success": True},
            "lint": {"errors": 0},
        }
        assert evaluate_objective_outcomes(outcomes) is True

    def test_any_failure_fails(self):
        """Conservative: any single failure = overall failure."""
        outcomes = {
            "tests": {"exit_code": 0},
            "commands": {"success": False},
            "lint": {"errors": 0},
        }
        assert evaluate_objective_outcomes(outcomes) is False

    def test_test_failure(self):
        outcomes = {"tests": {"exit_code": 1}}
        assert evaluate_objective_outcomes(outcomes) is False

    def test_command_list(self):
        """Commands can be a list."""
        outcomes = {
            "commands": [
                {"exit_code": 0},
                {"exit_code": 0},
            ]
        }
        assert evaluate_objective_outcomes(outcomes) is True

    def test_command_list_with_failure(self):
        outcomes = {
            "commands": [
                {"exit_code": 0},
                {"exit_code": 1},
            ]
        }
        assert evaluate_objective_outcomes(outcomes) is False

    def test_file_checks(self):
        outcomes = {
            "files": [
                {"path": __file__, "expected_exists": True},
            ]
        }
        assert evaluate_objective_outcomes(outcomes) is True

    def test_file_checks_failure(self):
        outcomes = {
            "files": [
                {"path": "/nonexistent/xyz.txt", "expected_exists": True},
            ]
        }
        assert evaluate_objective_outcomes(outcomes) is False

    def test_unevaluable_signals_ignored(self):
        """Signals that can't be evaluated (None result) are skipped."""
        outcomes = {
            "tests": {},  # returns None
            "commands": {"exit_code": 0},
        }
        assert evaluate_objective_outcomes(outcomes) is True


# --- evaluate_decision_outcome Tests ---


class TestEvaluateDecisionOutcome:
    """Tests for evaluate_decision_outcome() calibration evaluator."""

    def test_no_confidence_returns_none(self):
        entry = {"agent_id": "a1"}
        metadata = {"a1": {"status": "active"}}
        assert evaluate_decision_outcome(entry, metadata) is None

    def test_unknown_agent_returns_none(self):
        entry = {"confidence": 0.8, "agent_id": "a1"}
        metadata = {}  # No metadata for a1
        assert evaluate_decision_outcome(entry, metadata) is None

    def test_paused_agent_high_confidence_is_overconfident(self):
        """High confidence + paused agent = miscalibrated (overconfident)."""
        entry = {"confidence": 0.9, "agent_id": "a1"}
        metadata = {"a1": {"status": "paused"}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.9, outcome_quality=0.2 → gap=0.7 > 0.35 → False
        assert result is False

    def test_active_agent_appropriate_confidence(self):
        """Moderate confidence + active agent = well calibrated."""
        entry = {"confidence": 0.7, "agent_id": "a1"}
        metadata = {"a1": {"status": "active", "update_count": 5}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.7, outcome_quality=0.7+0.05=0.75 → gap=0.05 < 0.35 → True
        assert result is True

    def test_archived_agent_high_confidence(self):
        """High confidence + archived (completed) agent = well calibrated."""
        entry = {"confidence": 0.85, "agent_id": "a1"}
        metadata = {"a1": {"status": "archived"}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.85, outcome_quality=0.95 → gap=0.1 < 0.35 → True
        assert result is True

    def test_loop_detected_counts_as_poor_outcome(self):
        entry = {"confidence": 0.8, "agent_id": "a1"}
        metadata = {"a1": {"status": "active", "loop_detected_at": "2026-01-01"}}
        result = evaluate_decision_outcome(entry, metadata)
        # outcome_quality=0.2 (loop detected), gap=0.6 > 0.35 → False
        assert result is False

    def test_waiting_input_moderate_confidence(self):
        entry = {"confidence": 0.6, "agent_id": "a1"}
        metadata = {"a1": {"status": "waiting_input"}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.6, outcome_quality=0.6 → gap=0.0 < 0.35 → True
        assert result is True

    def test_confidence_from_details(self):
        """Should extract confidence from nested details dict."""
        entry = {"agent_id": "a1", "details": {"confidence": 0.7}}
        metadata = {"a1": {"status": "active", "update_count": 5}}
        result = evaluate_decision_outcome(entry, metadata)
        assert result is not None  # Should not be None

    def test_unknown_status_returns_none(self):
        entry = {"confidence": 0.8, "agent_id": "a1"}
        metadata = {"a1": {"status": "some_unknown_status"}}
        assert evaluate_decision_outcome(entry, metadata) is None

    def test_experience_bonus(self):
        """More experienced agents get slightly higher outcome_quality."""
        entry = {"confidence": 0.85, "agent_id": "a1"}
        # 15 updates * 0.01 = 0.15 bonus → outcome = 0.7 + 0.15 = 0.85
        metadata = {"a1": {"status": "active", "update_count": 15}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.85, outcome_quality=0.85 → gap=0.0 → True
        assert result is True

    def test_experience_bonus_capped(self):
        """Experience bonus should cap at 0.15."""
        entry = {"confidence": 0.85, "agent_id": "a1"}
        # 100 updates → bonus capped at 0.15
        metadata = {"a1": {"status": "active", "update_count": 100}}
        result = evaluate_decision_outcome(entry, metadata)
        # confidence=0.85, outcome_quality=0.7+0.15=0.85 → gap=0.0 → True
        assert result is True
