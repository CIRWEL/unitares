"""Regression test: hooks invoke agent.py by absolute path from arbitrary cwd.

Background: on 2026-04-23, both SessionStart and UserPromptSubmit Claude Code
hooks failed with ``ModuleNotFoundError: No module named 'agents'`` in every
new session. Root cause was an import-order bug introduced by the
watcher-findings-split refactor (commit 384aca64):

    from agents.watcher._util import ...     # line 65 — fails here
    ...
    sys.path.insert(0, str(PROJECT_ROOT))    # line 74 — too late

When the hook runs ``python3 /abs/path/agent.py --print-unresolved`` from the
user's home directory, Python adds ``agents/watcher/`` to sys.path (the
script's directory) but *not* the repo root, so the top-level ``agents.*``
import fails before the sys.path patch on line 74 runs.

The existing test_agent.py tests load the module via
``importlib.util.spec_from_file_location`` with an explicit path, which
bypasses sys.path resolution entirely — so they never exercised the
hook-invocation path and the regression slipped through.

This test invokes agent.py the same way the hook does: as a subprocess, by
absolute path, from an unrelated cwd, with no PYTHONPATH. If the import
order regresses again, this will fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


AGENT_PATH = (
    Path(__file__).resolve().parent.parent / "agent.py"
)


def test_agent_imports_from_foreign_cwd(tmp_path):
    """Replicate the hook invocation: absolute script path, unrelated cwd, no PYTHONPATH."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"PYTHONPATH"}
    }
    result = subprocess.run(
        [sys.executable, str(AGENT_PATH), "--print-unresolved"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"agent.py failed to import from foreign cwd.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "ModuleNotFoundError" not in result.stderr, (
        f"Import-order regression: {result.stderr}"
    )
