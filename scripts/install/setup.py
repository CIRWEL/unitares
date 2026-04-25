#!/usr/bin/env python3
"""Guided UNITARES install wizard.

Runs scripts/dev/unitares_doctor.py for diagnosis, prints remediation commands
for any failing checks, scaffolds ~/.unitares/ and ~/.config/cirwel/secrets.env
under --apply, and generates copy-pasteable stdio MCP snippets for detected
clients (Claude Code, Codex, Gemini CLI, Copilot CLI).

Setup PRINTS commands. It does NOT install postgres, run SQL, invoke brew, or
modify MCP client config files. The two filesystem mutations under --apply are
bounded exceptions documented in
docs/superpowers/specs/2026-04-25-unitares-setup-design.md.

Usage:
    python3 scripts/install/setup.py            # interactive, dry-run
    python3 scripts/install/setup.py --apply    # mutate the two paths
    python3 scripts/install/setup.py --json     # machine-readable plan
    python3 scripts/install/setup.py --apply --non-interactive --json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1

# REPO_ROOT derivation. The script lives at scripts/install/setup.py, so
# Path(__file__).resolve().parent.parent.parent is the repo root. This pattern
# matches scripts/dev/unitares_doctor.py and is robust against `cd`, symlinks,
# and worktrees. Do not "simplify" to os.getcwd() — that breaks when the user
# runs the script from any cwd other than the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "dev" / "unitares_doctor.py"


class DoctorError(RuntimeError):
    """Raised when the doctor subprocess emits something we cannot parse.
    Nonzero exit codes from doctor are NOT errors — failed checks are normal.
    Only invalid JSON or a missing executable raise this.
    """


def bootstrap_check() -> None:
    """Verify the MCP SDK is importable. Setup is not stdlib-only — it shares
    the server's runtime deps. If mcp is missing, exit early with the canonical
    install command before doing any work.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            "MCP SDK not found. Run:\n"
            "    pip install -r requirements-full.txt",
            file=sys.stdout,
        )
        sys.exit(2)


def run_doctor() -> dict:
    """Spawn unitares_doctor.py --json --mode=local and return the parsed
    payload. A nonzero exit code is normal (any local check failed); the
    payload is still complete. Only invalid JSON raises DoctorError.
    """
    proc = subprocess.run(
        [sys.executable, str(DOCTOR_SCRIPT), "--json", "--mode=local"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise DoctorError(
            f"doctor emitted invalid JSON (rc={proc.returncode}); "
            f"stdout[:200]={proc.stdout[:200]!r}; stderr={proc.stderr[:200]!r}"
        ) from e


def main(argv: list[str] | None = None) -> int:
    bootstrap_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
