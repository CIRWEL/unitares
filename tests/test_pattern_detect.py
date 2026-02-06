"""
Tests for detect_code_changes in src/mcp_handlers/pattern_helpers.py.

This function is pure (no I/O, no tracker) - just inspects tool names and arguments.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.pattern_helpers import detect_code_changes


class TestDetectCodeChanges:

    def test_search_replace_python(self):
        result = detect_code_changes("search_replace", {"file_path": "src/main.py"})
        assert result is not None
        assert result["change_type"] == "code_edit"
        assert "src/main.py" in result["files_changed"]
        assert result["tool"] == "search_replace"

    def test_write_tool(self):
        result = detect_code_changes("write", {"file_path": "src/app.js"})
        assert result is not None
        assert "src/app.js" in result["files_changed"]

    def test_edit_notebook(self):
        result = detect_code_changes("edit_notebook", {"target_notebook": "analysis.py"})
        assert result is not None

    def test_non_code_tool(self):
        result = detect_code_changes("read_file", {"file_path": "src/main.py"})
        assert result is None

    def test_non_code_extension(self):
        result = detect_code_changes("search_replace", {"file_path": "README.md"})
        assert result is None

    def test_txt_not_code(self):
        result = detect_code_changes("write", {"file_path": "notes.txt"})
        assert result is None

    def test_typescript(self):
        result = detect_code_changes("write", {"file_path": "src/index.ts"})
        assert result is not None

    def test_tsx(self):
        result = detect_code_changes("write", {"file_path": "App.tsx"})
        assert result is not None

    def test_java(self):
        result = detect_code_changes("write", {"file_path": "Main.java"})
        assert result is not None

    def test_go(self):
        result = detect_code_changes("write", {"file_path": "main.go"})
        assert result is not None

    def test_rust(self):
        result = detect_code_changes("write", {"file_path": "lib.rs"})
        assert result is not None

    def test_cpp(self):
        result = detect_code_changes("write", {"file_path": "main.cpp"})
        assert result is not None

    def test_c_file(self):
        result = detect_code_changes("write", {"file_path": "main.c"})
        assert result is not None

    def test_header_file(self):
        result = detect_code_changes("write", {"file_path": "main.h"})
        assert result is not None

    def test_no_file_path(self):
        result = detect_code_changes("search_replace", {"text": "hello"})
        assert result is None

    def test_list_file_paths(self):
        """When file_path is a list."""
        result = detect_code_changes("search_replace", {"file_path": ["a.py", "b.js"]})
        assert result is not None
        assert len(result["files_changed"]) == 2

    def test_mixed_code_and_non_code(self):
        """Only code files should be in the result."""
        result = detect_code_changes("search_replace", {"file_path": ["a.py", "README.md"]})
        assert result is not None
        assert "a.py" in result["files_changed"]
        assert "README.md" not in result["files_changed"]

    def test_empty_arguments(self):
        result = detect_code_changes("search_replace", {})
        assert result is None

    def test_jsx_file(self):
        result = detect_code_changes("write", {"file_path": "Component.jsx"})
        assert result is not None
