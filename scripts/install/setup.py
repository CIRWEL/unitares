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

import sys

SCHEMA_VERSION = 1


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


def main(argv: list[str] | None = None) -> int:
    bootstrap_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
