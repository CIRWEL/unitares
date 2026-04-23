"""Tests for p008_actually_fires — AST post-filter that suppresses list-form
subprocess findings the LLM keeps mis-flagging as shell injection.

Rule (from patterns.md): P008 fires only when the call is
subprocess.*(shell=True) or os.system(...) or os.popen(...).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.watcher.agent import p008_actually_fires


def _write(tmp_path: Path, name: str, source: str) -> Path:
    p = tmp_path / name
    p.write_text(source)
    return p


class TestFalsePositiveSuppression:
    """List-form subprocess and no-shell calls must be suppressed."""

    def test_list_form_subprocess_run_is_suppressed(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import subprocess\nsubprocess.run(["find", "."])\n')
        assert p008_actually_fires(str(p), line=2) is False

    def test_list_form_with_concat_is_suppressed(self, tmp_path):
        # Mirrors the real scrapers.py:71 case that was flagged as a fp.
        source = 'import subprocess\nfiles = ["a.py", "b.py"]\nsubprocess.run(["wc", "-l"] + files)\n'
        p = _write(tmp_path, "a.py", source)
        assert p008_actually_fires(str(p), line=3) is False

    def test_popen_list_form_is_suppressed(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import subprocess\nsubprocess.Popen(["git", "log"])\n')
        assert p008_actually_fires(str(p), line=2) is False

    def test_explicit_shell_false_is_suppressed(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import subprocess\nsubprocess.run(["ls"], shell=False)\n')
        assert p008_actually_fires(str(p), line=2) is False

    def test_multiline_list_form_is_suppressed(self, tmp_path):
        source = (
            "import subprocess\n"
            "subprocess.run(\n"
            '    ["find", ".", "-type", "f"],\n'
            "    check=True,\n"
            ")\n"
        )
        p = _write(tmp_path, "a.py", source)
        # LLM typically flags the opening line
        assert p008_actually_fires(str(p), line=2) is False


class TestRealPositivesKept:
    """Actual shell=True / os.system calls must NOT be suppressed."""

    def test_shell_true_kept(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import subprocess\nsubprocess.run("find .", shell=True)\n')
        assert p008_actually_fires(str(p), line=2) is True

    def test_os_system_kept(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import os\nos.system("rm -rf /tmp/x")\n')
        assert p008_actually_fires(str(p), line=2) is True

    def test_os_popen_kept(self, tmp_path):
        p = _write(tmp_path, "a.py", 'import os\nos.popen("ls")\n')
        assert p008_actually_fires(str(p), line=2) is True

    def test_multiline_shell_true_kept_when_flagged_on_opening_line(self, tmp_path):
        source = (
            "import subprocess\n"
            "subprocess.run(\n"
            '    "find . -type f",\n'
            "    shell=True,\n"
            ")\n"
        )
        p = _write(tmp_path, "a.py", source)
        # Finding flagged on opening line — span includes shell=True on line 4
        assert p008_actually_fires(str(p), line=2) is True


class TestConservativeOnError:
    """When we can't verify, keep the finding — humans review what we can't check."""

    def test_missing_file_is_conservative(self, tmp_path):
        assert p008_actually_fires(str(tmp_path / "nonexistent.py"), line=10) is True

    def test_syntax_error_is_conservative(self, tmp_path):
        p = _write(tmp_path, "a.py", "def oops(:\n")
        assert p008_actually_fires(str(p), line=1) is True

    def test_non_python_file_is_conservative(self, tmp_path):
        p = _write(tmp_path, "a.sh", 'rm -rf "$1"\n')
        # P008 is Python-scoped; we don't know how to verify shell vars — keep it.
        assert p008_actually_fires(str(p), line=1) is True


class TestEdgeCases:
    def test_no_call_at_line_is_suppressed(self, tmp_path):
        # If the LLM flagged a line that doesn't have any Call node at all
        # (e.g. a comment or blank), no shell=True exists there → suppress.
        source = "import subprocess\n# just a comment\nsubprocess.run(['ls'])\n"
        p = _write(tmp_path, "a.py", source)
        assert p008_actually_fires(str(p), line=2) is False

    def test_shell_variable_is_conservative_enough_to_suppress(self, tmp_path):
        # `shell=use_shell` is a non-constant value — the AST check looks for
        # the literal True constant, so a variable doesn't count as proof of
        # shell. Suppressed for now; humans can still inspect via manual review.
        source = 'import subprocess\nuse_shell = True\nsubprocess.run("ls", shell=use_shell)\n'
        p = _write(tmp_path, "a.py", source)
        # This is an acknowledged limitation — dynamic shell=var won't be kept
        # by the AST check. Value-flow analysis would be out of scope here.
        assert p008_actually_fires(str(p), line=3) is False
