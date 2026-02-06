"""
Tests for src/mcp_handlers/pattern_helpers.py - Code change detection and hypothesis tracking.

detect_code_changes is pure. Others need light mocking of pattern_tracker.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.pattern_helpers import (
    detect_code_changes,
    record_hypothesis_if_needed,
    check_untested_hypotheses,
    mark_hypothesis_tested,
)


class TestDetectCodeChanges:
    """Pure function - no mocking needed."""

    def test_search_replace_with_py_file(self):
        result = detect_code_changes("search_replace", {"file_path": "src/main.py"})
        assert result is not None
        assert result["change_type"] == "code_edit"
        assert "src/main.py" in result["files_changed"]
        assert result["tool"] == "search_replace"

    def test_write_with_js_file(self):
        result = detect_code_changes("write", {"file_path": "app/index.js"})
        assert result is not None
        assert "app/index.js" in result["files_changed"]

    def test_edit_notebook(self):
        result = detect_code_changes("edit_notebook", {"target_notebook": "analysis.py"})
        assert result is not None

    def test_non_code_tool_returns_none(self):
        result = detect_code_changes("read_file", {"file_path": "src/main.py"})
        assert result is None

    def test_non_code_file_returns_none(self):
        result = detect_code_changes("write", {"file_path": "README.md"})
        assert result is None

    def test_txt_file_returns_none(self):
        result = detect_code_changes("search_replace", {"file_path": "notes.txt"})
        assert result is None

    def test_no_file_path_returns_none(self):
        result = detect_code_changes("write", {"other_key": "value"})
        assert result is None

    def test_multiple_code_extensions(self):
        """All code extensions should be detected."""
        extensions = [".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".h"]
        for ext in extensions:
            result = detect_code_changes("write", {"file_path": f"file{ext}"})
            assert result is not None, f"Failed for extension {ext}"

    def test_file_path_as_list(self):
        result = detect_code_changes("search_replace", {"file_path": ["a.py", "b.ts"]})
        assert result is not None
        assert len(result["files_changed"]) == 2

    def test_mixed_code_and_non_code(self):
        """Only code files are returned."""
        result = detect_code_changes("search_replace", {"file_path": ["a.py", "readme.md"]})
        assert result is not None
        assert result["files_changed"] == ["a.py"]


class TestRecordHypothesisIfNeeded:

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_records_on_code_change(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        record_hypothesis_if_needed("agent-123", "write", {"file_path": "src/app.py"})

        mock_tracker.record_hypothesis.assert_called_once()
        call_kwargs = mock_tracker.record_hypothesis.call_args
        assert call_kwargs[1]["agent_id"] == "agent-123"
        assert "src/app.py" in call_kwargs[1]["files_changed"]

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_skips_non_code_tool(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        record_hypothesis_if_needed("agent-123", "read_file", {"file_path": "src/app.py"})

        mock_tracker.record_hypothesis.assert_not_called()


class TestCheckUntestedHypotheses:

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_returns_message_when_untested(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_tracker.check_untested_hypotheses.return_value = {"message": "You have untested changes"}
        mock_get_tracker.return_value = mock_tracker

        result = check_untested_hypotheses("agent-123")
        assert result == "You have untested changes"

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_returns_none_when_no_untested(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_tracker.check_untested_hypotheses.return_value = None
        mock_get_tracker.return_value = mock_tracker

        result = check_untested_hypotheses("agent-123")
        assert result is None


class TestMarkHypothesisTested:

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_marks_when_test_tool(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        mark_hypothesis_tested("agent-123", "run_test", {"file_path": "tests/test_app.py"})

        mock_tracker.mark_hypothesis_tested.assert_called_once()

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_marks_when_test_in_args(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        mark_hypothesis_tested("agent-123", "run_terminal_cmd", {
            "command": "pytest tests/",
            "file_path": "tests/test_main.py"
        })

        mock_tracker.mark_hypothesis_tested.assert_called_once()

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_skips_when_not_testing(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        mark_hypothesis_tested("agent-123", "write", {"file_path": "src/app.py"})

        mock_tracker.mark_hypothesis_tested.assert_not_called()

    @patch("src.mcp_handlers.pattern_helpers.get_pattern_tracker")
    def test_skips_when_no_file_paths(self, mock_get_tracker):
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        mark_hypothesis_tested("agent-123", "run_test", {"command": "pytest"})

        mock_tracker.mark_hypothesis_tested.assert_not_called()
