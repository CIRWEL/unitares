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
from dataclasses import dataclass, asdict
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


@dataclass
class PlanItem:
    """One actionable item in the wizard's plan. Phase 1 items are
    remediation commands the user copy-pastes; phase 2 items are filesystem
    operations setup will perform under --apply; phase 3 items are
    MCP-client snippets the user pastes into their own config files.
    """
    phase: int  # 1 = remediation, 2 = mkdir/file, 3 = snippet
    kind: str   # "remediation" | "mkdir" | "file" | "snippet"
    finding: str = ""        # phase 1: doctor finding name
    command: str = ""        # phase 1: shell command to run
    path: str = ""           # phase 2: filesystem target
    mode: str = ""           # phase 2: octal mode as string
    client: str = ""         # phase 3: client name (claude_code, codex, etc.)
    config_path: str = ""    # phase 3: target config file
    snippet: str = ""        # phase 3: copy-paste payload
    applied: bool = False
    note: str = ""           # human-readable note (e.g., superuser caveat)


# Remediation commands keyed by doctor finding name. Lookup misses fall through
# to a generic "see doctor output" message. The schema-migrations entry is
# computed at runtime because it depends on which migration files exist.
_REMEDIATIONS = {
    "postgres_running":
        "brew install postgresql@17 && brew services start postgresql@17",
    "governance_database":
        "createdb -h localhost -U postgres governance",
    "pg_extensions":
        "psql -U postgres -d governance -f db/postgres/init-extensions.sql",
    "secrets_file":  # mode-fail variant; the missing-file variant is phase 2
        "chmod 600 ~/.config/cirwel/secrets.env",
    "anchor_directory":
        "mkdir -m 700 ~/.unitares",
}

_REMEDIATION_NOTES = {
    "pg_extensions":
        "AGE + pgvector require superuser. The -U postgres is intentional; "
        "do not substitute -U $USER on a typical local install.",
}


def build_remediation(doctor_payload: dict) -> list[PlanItem]:
    """For each fail/warn in the doctor payload, emit a PlanItem with a
    remediation command. pass results are skipped (no action needed).
    """
    items: list[PlanItem] = []
    for r in doctor_payload.get("results", []):
        if r["status"] not in ("fail", "warn"):
            continue
        name = r["name"]
        if name == "schema_migrations":
            command = _build_migrations_command()
        else:
            command = _REMEDIATIONS.get(
                name,
                f"# No automated remediation for '{name}'. See doctor output: {r['message']}",
            )
        items.append(PlanItem(
            phase=1,
            kind="remediation",
            finding=name,
            command=command,
            note=_REMEDIATION_NOTES.get(name, ""),
        ))
    return items


def _build_migrations_command() -> str:
    """List the SQL files in db/postgres/migrations/ in lexical order, plus
    the canonical schema files. The user runs them in order with psql.
    """
    migrations_dir = REPO_ROOT / "db" / "postgres" / "migrations"
    pieces = [
        "psql -U postgres -d governance -f db/postgres/schema.sql",
        "psql -U postgres -d governance -f db/postgres/knowledge_schema.sql",
    ]
    if migrations_dir.is_dir():
        for sql in sorted(migrations_dir.glob("*.sql")):
            rel = sql.relative_to(REPO_ROOT)
            pieces.append(f"psql -U postgres -d governance -f {rel}")
    return " && \\\n    ".join(pieces)


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
