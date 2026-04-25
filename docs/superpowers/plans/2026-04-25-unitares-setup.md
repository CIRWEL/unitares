# UNITARES Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/install/setup.py` — a guided UNITARES install wizard that runs `unitares_doctor.py` for diagnosis, prints remediation commands, scaffolds the anchor dir + secrets file, and generates copy-pasteable stdio MCP snippets for detected clients.

**Architecture:** Standalone Python script (stdlib + MCP SDK only), invokes `scripts/dev/unitares_doctor.py --json` as a subprocess for all server-side diagnosis. Five phases: bootstrap check → doctor + remediation → filesystem scaffold → client detection + snippets → final doctor pass. Default dry-run; `--apply` mutates two paths (`~/.unitares/`, `~/.config/cirwel/secrets.env`); never edits client configs.

**Tech Stack:** Python 3.12+ (project supports 3.14), stdlib (`argparse`, `dataclasses`, `enum`, `json`, `pathlib`, `subprocess`, `os`, `stat`), MCP SDK (`import mcp` for bootstrap check only — no further use; future-proofs for snippet validation if needed).

**Spec:** `docs/superpowers/specs/2026-04-25-unitares-setup-design.md`

**Companion (already shipped):** `scripts/dev/unitares_doctor.py` (commits `b699c443` + `7bad1405`); test pattern at `tests/test_unitares_doctor_script.py`.

**Worktree:** `.worktrees/unitares-setup` on branch `feat/unitares-setup`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/install/__init__.py` | Empty package marker. |
| `scripts/install/setup.py` | All wizard logic. Single file (~450 LOC). Composed of pure functions per phase + a `main()` orchestrator. No classes beyond dataclasses. |
| `tests/test_setup_install_script.py` | Smoke tests via `importlib.util` module load (matching doctor's pattern). Patches the internal `run_doctor()` function rather than `subprocess.run` globally. |

`scripts/install/setup.py` internal layout:

```python
# Constants (paths, templates, schema version)
# Dataclasses: PlanItem, Plan
# Phase 0: bootstrap_check()
# Phase 1: run_doctor() + build_remediation()
# Phase 2: ensure_anchor_dir() + ensure_secrets_file()
# Phase 3: detect_clients() + build_snippet()
# Orchestration: run_pipeline()
# CLI: main() + render_text() + render_json()
```

---

## Task 1: Module skeleton + bootstrap check

**Files:**
- Create: `scripts/install/__init__.py`
- Create: `scripts/install/setup.py`
- Create: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_setup_install_script.py`:

```python
"""Smoke tests for scripts/install/setup.py.

Mirrors tests/test_unitares_doctor_script.py: imports the script as a module,
patches its internal subprocess wrapper, and uses tmp_path for filesystem
mutations. Never touches real ~/.unitares/, real client configs, or live
postgres.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "install" / "setup.py"


@pytest.fixture(scope="module")
def setup_mod():
    spec = importlib.util.spec_from_file_location("unitares_setup", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unitares_setup"] = mod  # Python 3.14 dataclass needs this
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_main(setup_mod):
    assert callable(setup_mod.main)
    assert setup_mod.SCHEMA_VERSION == 1


def test_bootstrap_check_passes_when_mcp_importable(setup_mod, monkeypatch):
    # mcp SDK is installed in the project's full requirements; this is the
    # happy path — bootstrap_check should return without raising.
    setup_mod.bootstrap_check()  # no exception


def test_bootstrap_check_exits_when_mcp_missing(setup_mod, monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp":
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        setup_mod.bootstrap_check()
    assert exc.value.code == 2
    err = capsys.readouterr().out
    assert "pip install -r requirements-full.txt" in err
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/unitares-setup
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: collection error or ImportError because `scripts/install/setup.py` does not exist.

- [ ] **Step 3: Create the package marker**

Create `scripts/install/__init__.py` as an empty file:

```bash
mkdir -p scripts/install
touch scripts/install/__init__.py
```

- [ ] **Step 4: Write the minimal setup.py to pass these three tests**

Create `scripts/install/setup.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/install/__init__.py scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): module skeleton + bootstrap MCP-SDK import check"
```

---

## Task 2: Doctor subprocess wrapper

**Files:**
- Modify: `scripts/install/setup.py` (add `run_doctor()` + supporting types)
- Modify: `tests/test_setup_install_script.py` (add doctor-wrapper tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
def test_run_doctor_parses_pass_payload(setup_mod, monkeypatch):
    fake_stdout = '{"mode": "local", "results": [{"name": "x", "mode": "local", "status": "pass", "message": "ok", "detail": ""}], "exit_code": 0}'

    class FakeProc:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    result = setup_mod.run_doctor()
    assert result["mode"] == "local"
    assert result["results"][0]["status"] == "pass"
    assert result["exit_code"] == 0


def test_run_doctor_handles_nonzero_exit_with_valid_json(setup_mod, monkeypatch):
    """Doctor exits 1 when any local check fails; setup must NOT treat that
    as an error — the JSON payload is still complete and is the input to
    remediation."""
    fake_stdout = '{"mode": "local", "results": [{"name": "postgres_running", "mode": "local", "status": "fail", "message": "down", "detail": ""}], "exit_code": 1}'

    class FakeProc:
        returncode = 1
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    result = setup_mod.run_doctor()
    assert result["results"][0]["status"] == "fail"
    assert result["exit_code"] == 1


def test_run_doctor_raises_on_invalid_json(setup_mod, monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    with pytest.raises(setup_mod.DoctorError):
        setup_mod.run_doctor()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 3 new tests fail with `AttributeError: module 'unitares_setup' has no attribute 'run_doctor'`.

- [ ] **Step 3: Implement `run_doctor()`**

Edit `scripts/install/setup.py`. Add these imports at the top alongside existing ones:

```python
import json
import subprocess
from pathlib import Path
```

Add this constant block after `SCHEMA_VERSION = 1`:

```python
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
```

Then add `run_doctor()` after `bootstrap_check()`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): doctor subprocess wrapper with strict JSON parsing"
```

---

## Task 3: Remediation block generator

**Files:**
- Modify: `scripts/install/setup.py` (add `PlanItem`, `build_remediation()`)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
def _doctor_payload(*finds):
    """Build a doctor payload with the given (name, status, message) tuples."""
    return {
        "mode": "local",
        "results": [
            {"name": n, "mode": "local", "status": s, "message": m, "detail": ""}
            for n, s, m in finds
        ],
        "exit_code": 1 if any(s == "fail" for _, s, _ in finds) else 0,
    }


def test_remediation_for_postgres_fail(setup_mod):
    payload = _doctor_payload(("postgres_running", "fail", "down"))
    items = setup_mod.build_remediation(payload)
    assert len(items) == 1
    assert items[0].finding == "postgres_running"
    assert "brew install postgresql@17" in items[0].command
    assert items[0].applied is False


def test_remediation_for_pg_extensions_fail(setup_mod):
    payload = _doctor_payload(("pg_extensions", "fail", "missing: age, vector"))
    items = setup_mod.build_remediation(payload)
    assert "psql -U postgres -d governance" in items[0].command
    assert "init-extensions.sql" in items[0].command


def test_remediation_for_secrets_wrong_mode(setup_mod):
    payload = _doctor_payload(("secrets_file", "fail", "mode is 0o644 — must be 0600"))
    items = setup_mod.build_remediation(payload)
    assert "chmod 600" in items[0].command


def test_remediation_skips_pass_results(setup_mod):
    payload = _doctor_payload(
        ("python_version", "pass", "Python 3.14"),
        ("postgres_running", "fail", "down"),
    )
    items = setup_mod.build_remediation(payload)
    # python_version is pass, only postgres_running gets a remediation block.
    assert len(items) == 1
    assert items[0].finding == "postgres_running"


def test_remediation_includes_warns(setup_mod):
    payload = _doctor_payload(("anchor_directory", "warn", "missing"))
    items = setup_mod.build_remediation(payload)
    assert len(items) == 1
    assert items[0].finding == "anchor_directory"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 5 new tests fail with AttributeError on `build_remediation` / `PlanItem`.

- [ ] **Step 3: Implement `PlanItem` + `build_remediation()`**

Edit `scripts/install/setup.py`. Add to imports:

```python
from dataclasses import dataclass, field, asdict
```

Add after the `DoctorError` class:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): remediation generator for doctor fail/warn results"
```

---

## Task 4: Filesystem scaffolding

**Files:**
- Modify: `scripts/install/setup.py` (add `ensure_anchor_dir()`, `ensure_secrets_file()`)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
import stat


def test_ensure_anchor_dir_dry_run_no_writes(setup_mod, tmp_path):
    target = tmp_path / "unitares"
    assert not target.exists()
    item = setup_mod.ensure_anchor_dir(target, apply=False)
    assert not target.exists()
    assert item.applied is False
    assert item.path == str(target)
    assert item.mode == "0o700"


def test_ensure_anchor_dir_apply_creates_with_mode_0700(setup_mod, tmp_path):
    target = tmp_path / "unitares"
    item = setup_mod.ensure_anchor_dir(target, apply=True)
    assert target.is_dir()
    actual = stat.S_IMODE(target.stat().st_mode)
    assert actual == 0o700, f"expected 0o700 got {oct(actual)}"
    assert item.applied is True


def test_ensure_anchor_dir_apply_idempotent(setup_mod, tmp_path):
    target = tmp_path / "unitares"
    target.mkdir(mode=0o700)
    item = setup_mod.ensure_anchor_dir(target, apply=True)
    # Already existed — applied should be False (we did not mutate).
    assert item.applied is False


def test_ensure_secrets_file_dry_run_no_writes(setup_mod, tmp_path):
    target = tmp_path / "secrets.env"
    item = setup_mod.ensure_secrets_file(target, apply=False)
    assert not target.exists()
    assert item.applied is False
    assert item.mode == "0o600"


def test_ensure_secrets_file_apply_creates_with_mode_0600(setup_mod, tmp_path):
    target = tmp_path / "secrets.env"
    item = setup_mod.ensure_secrets_file(target, apply=True)
    assert target.is_file()
    actual = stat.S_IMODE(target.stat().st_mode)
    assert actual == 0o600, f"expected 0o600 got {oct(actual)}"
    content = target.read_text()
    assert "ANTHROPIC_API_KEY" in content
    assert "mode 0600, never commit" in content
    assert item.applied is True


def test_ensure_secrets_file_does_not_overwrite_existing(setup_mod, tmp_path):
    target = tmp_path / "secrets.env"
    target.write_text("ANTHROPIC_API_KEY=existing-secret\n")
    target.chmod(0o600)
    item = setup_mod.ensure_secrets_file(target, apply=True)
    # File preserved exactly.
    assert target.read_text() == "ANTHROPIC_API_KEY=existing-secret\n"
    assert item.applied is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 6 new tests fail (functions not defined).

- [ ] **Step 3: Implement filesystem scaffolding**

Edit `scripts/install/setup.py`. Add to imports:

```python
import os
```

Add after `_build_migrations_command()`:

```python
SECRETS_TEMPLATE = """\
# UNITARES external secrets — mode 0600, never commit.
# Used by handlers that call out to LLM providers.
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
"""


def ensure_anchor_dir(path: Path, apply: bool) -> PlanItem:
    """Plan/apply creation of the agent anchor directory.

    Default mkdir mode is umask-dependent and on a typical Mac dev machine
    (umask 022) yields 0o755 — world-readable. Anchor dir holds session state;
    explicit 0o700 is correct.
    """
    item = PlanItem(
        phase=2,
        kind="mkdir",
        path=str(path),
        mode="0o700",
        applied=False,
    )
    if path.is_dir():
        return item  # already exists; nothing to do
    if not apply:
        return item  # dry run; report only
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    item.applied = True
    return item


def ensure_secrets_file(path: Path, apply: bool) -> PlanItem:
    """Plan/apply scaffolding of ~/.config/cirwel/secrets.env.

    Creates parent directories if needed (e.g., ~/.config/cirwel/). Writes
    a commented template at mode 0o600. Never overwrites an existing file —
    the doctor flags wrong-mode separately, and we do not want to lose
    the user's keys.
    """
    item = PlanItem(
        phase=2,
        kind="file",
        path=str(path),
        mode="0o600",
        applied=False,
    )
    if path.exists():
        return item  # do not overwrite
    if not apply:
        return item  # dry run
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SECRETS_TEMPLATE)
    os.chmod(path, 0o600)
    item.applied = True
    return item
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): anchor-dir and secrets-file scaffolding (--apply only, idempotent)"
```

---

## Task 5: Client detection

**Files:**
- Modify: `scripts/install/setup.py` (add `detect_clients()`)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
def test_detect_clients_finds_existing_paths(setup_mod, tmp_path):
    # Build a fake home with claude_code + codex installed; gemini and
    # copilot absent.
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".codex").mkdir(parents=True)
    detected = setup_mod.detect_clients(fake_home)
    assert "claude_code" in detected
    assert "codex" in detected
    assert "gemini" not in detected
    assert "copilot" not in detected


def test_detect_clients_returns_config_paths(setup_mod, tmp_path):
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    detected = setup_mod.detect_clients(fake_home)
    assert detected["claude_code"]["config_path"].endswith(".claude/settings.json")
    assert detected["claude_code"]["format"] == "json"


def test_detect_clients_handles_empty_home(setup_mod, tmp_path):
    detected = setup_mod.detect_clients(tmp_path / "empty")
    assert detected == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 3 new tests fail.

- [ ] **Step 3: Implement `detect_clients()`**

Edit `scripts/install/setup.py`. Add after `ensure_secrets_file()`:

```python
# Client detection table. Detection path = directory whose existence implies
# the client is installed. config_path = where the user pastes the snippet.
# format = "json" or "toml" — controls render shape in build_snippet().
# These paths were sourced from each client's documented config locations as
# of 2026-04-25; the copilot path is speculative and prints a TODO instead
# of a real snippet (see build_snippet() handling).
_CLIENT_TABLE = {
    "claude_code": {
        "detect_subpath": ".claude",
        "config_subpath": ".claude/settings.json",
        "format": "json",
    },
    "codex": {
        "detect_subpath": ".codex",
        "config_subpath": ".codex/config.toml",
        "format": "toml",
    },
    "gemini": {
        "detect_subpath": ".config/gemini",
        "config_subpath": ".config/gemini/settings.json",
        "format": "json",
    },
    "copilot": {
        "detect_subpath": ".config/github-copilot-cli",
        "config_subpath": ".config/github-copilot-cli/config.json",
        "format": "todo",  # speculative — emits a note, not a snippet
    },
}


def detect_clients(home: Path) -> dict[str, dict]:
    """Probe the user's home directory for installed MCP clients.
    Returns {client_name: {"config_path": "...", "format": "..."}}.
    Clients whose detect path is missing are silently skipped.
    """
    out: dict[str, dict] = {}
    for client, entry in _CLIENT_TABLE.items():
        detect_path = home / entry["detect_subpath"]
        if detect_path.exists():
            out[client] = {
                "config_path": str(home / entry["config_subpath"]),
                "format": entry["format"],
            }
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): MCP client detection from home directory"
```

---

## Task 6: Snippet generation

**Files:**
- Modify: `scripts/install/setup.py` (add `build_snippet()`)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
import json as _json


def test_build_snippet_claude_code_json(setup_mod):
    item = setup_mod.build_snippet(
        client="claude_code",
        config_path="/Users/x/.claude/settings.json",
        fmt="json",
        repo_root=Path("/repo"),
        proxy_url=None,
    )
    parsed = _json.loads(item.snippet)
    assert "unitares-governance" in parsed
    entry = parsed["unitares-governance"]
    assert entry["command"] == "python3"
    assert entry["args"] == ["/repo/src/mcp_server_std.py"]
    assert "DB_POSTGRES_URL" in entry["env"]
    assert "UNITARES_STDIO_PROXY_HTTP_URL" not in entry["env"]


def test_build_snippet_codex_toml(setup_mod):
    item = setup_mod.build_snippet(
        client="codex",
        config_path="/Users/x/.codex/config.toml",
        fmt="toml",
        repo_root=Path("/repo"),
        proxy_url=None,
    )
    s = item.snippet
    assert "[mcp_servers.unitares-governance]" in s
    assert 'command = "python3"' in s
    assert '"/repo/src/mcp_server_std.py"' in s


def test_build_snippet_with_proxy_url_adds_env_entry(setup_mod):
    item = setup_mod.build_snippet(
        client="claude_code",
        config_path="/Users/x/.claude/settings.json",
        fmt="json",
        repo_root=Path("/repo"),
        proxy_url="https://gov.example.org/mcp/",
    )
    parsed = _json.loads(item.snippet)
    env = parsed["unitares-governance"]["env"]
    assert env["UNITARES_STDIO_PROXY_HTTP_URL"] == "https://gov.example.org/mcp/"


def test_build_snippet_copilot_todo_note(setup_mod):
    item = setup_mod.build_snippet(
        client="copilot",
        config_path="/Users/x/.config/github-copilot-cli/config.json",
        fmt="todo",
        repo_root=Path("/repo"),
        proxy_url=None,
    )
    assert "TODO" in item.snippet
    assert "speculative" in item.snippet.lower() or "not yet" in item.snippet.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 4 new tests fail.

- [ ] **Step 3: Implement `build_snippet()`**

Edit `scripts/install/setup.py`. Add after `detect_clients()`:

```python
DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/governance"


def build_snippet(
    client: str,
    config_path: str,
    fmt: str,
    repo_root: Path,
    proxy_url: str | None,
) -> PlanItem:
    """Render a copy-pasteable MCP server entry for one client.

    The snippet points at src/mcp_server_std.py (stdio transport, local mode).
    If proxy_url is set, an additional UNITARES_STDIO_PROXY_HTTP_URL env entry
    is added so the stdio process forwards to a remote HTTP governance server.
    """
    server_path = str(repo_root / "src" / "mcp_server_std.py")
    env: dict[str, str] = {"DB_POSTGRES_URL": DEFAULT_DB_URL}
    if proxy_url:
        env["UNITARES_STDIO_PROXY_HTTP_URL"] = proxy_url

    if fmt == "todo":
        snippet = (
            f"# TODO: Copilot CLI MCP config format is speculative as of 2026-04-25.\n"
            f"# Verify the actual config schema before pasting. Equivalent payload:\n"
            f"#   command: python3\n"
            f"#   args:    [{server_path}]\n"
            f"#   env:     {dict(env)}"
        )
    elif fmt == "json":
        snippet = json.dumps(
            {
                "unitares-governance": {
                    "command": "python3",
                    "args": [server_path],
                    "env": env,
                }
            },
            indent=2,
        )
    elif fmt == "toml":
        env_lines = "\n".join(f'{k} = "{v}"' for k, v in env.items())
        snippet = (
            f"[mcp_servers.unitares-governance]\n"
            f'command = "python3"\n'
            f'args = ["{server_path}"]\n\n'
            f"[mcp_servers.unitares-governance.env]\n"
            f"{env_lines}\n"
        )
    else:
        raise ValueError(f"unknown snippet format: {fmt!r}")

    return PlanItem(
        phase=3,
        kind="snippet",
        client=client,
        config_path=config_path,
        snippet=snippet,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): stdio MCP snippet generation for claude_code, codex, gemini, copilot"
```

---

## Task 7: Pipeline orchestration

**Files:**
- Modify: `scripts/install/setup.py` (add `run_pipeline()`)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
def _patch_doctor(monkeypatch, setup_mod, payload):
    monkeypatch.setattr(setup_mod, "run_doctor", lambda: payload)


def test_run_pipeline_dry_run_emits_full_plan(setup_mod, monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    initial = _doctor_payload(
        ("python_version", "pass", "ok"),
        ("postgres_running", "fail", "down"),
        ("anchor_directory", "warn", "missing"),
    )
    _patch_doctor(monkeypatch, setup_mod, initial)

    out = setup_mod.run_pipeline(
        apply=False, home=fake_home, proxy_url=None,
    )

    assert out["schema_version"] == 1
    assert out["doctor_initial"] == initial
    assert out["doctor_final"] is None  # dry-run does not re-run doctor
    phases = {p.phase for p in out["plan"]}
    assert 1 in phases  # remediation
    assert 2 in phases  # mkdir/file
    assert 3 in phases  # snippet
    # Nothing applied in dry-run.
    assert all(not p.applied for p in out["plan"])


def test_run_pipeline_apply_runs_final_doctor(setup_mod, monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    initial = _doctor_payload(("anchor_directory", "warn", "missing"))
    final = _doctor_payload(("anchor_directory", "pass", "exists"))

    calls = {"n": 0}

    def fake_run_doctor():
        calls["n"] += 1
        return initial if calls["n"] == 1 else final

    monkeypatch.setattr(setup_mod, "run_doctor", fake_run_doctor)

    out = setup_mod.run_pipeline(
        apply=True, home=fake_home, proxy_url=None,
    )
    assert out["doctor_final"] == final
    # Anchor dir was created.
    assert (fake_home / ".unitares").is_dir()


def test_run_pipeline_idempotent_apply_on_healthy_state(setup_mod, monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    (fake_home / ".unitares").mkdir(mode=0o700)
    secrets = fake_home / ".config" / "cirwel" / "secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("EXISTING=1\n")
    secrets.chmod(0o600)

    healthy = _doctor_payload(
        ("python_version", "pass", "ok"),
        ("postgres_running", "pass", "ok"),
    )
    _patch_doctor(monkeypatch, setup_mod, healthy)

    out = setup_mod.run_pipeline(apply=True, home=fake_home, proxy_url=None)

    # Phase 2 items are present but applied=False because everything already
    # existed.
    phase2 = [p for p in out["plan"] if p.phase == 2]
    assert phase2  # we still emit the items
    assert all(not p.applied for p in phase2)
    # Existing secret content untouched.
    assert secrets.read_text() == "EXISTING=1\n"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 3 new tests fail.

- [ ] **Step 3: Implement `run_pipeline()`**

Edit `scripts/install/setup.py`. Add after `build_snippet()`:

```python
def run_pipeline(
    *,
    apply: bool,
    home: Path,
    proxy_url: str | None,
) -> dict:
    """Execute all five phases. Returns a dict shaped like the --json schema.

    Phase 1 always runs (read-only doctor + remediation generation).
    Phase 2 emits items for the two filesystem targets; mutates only with
    apply=True and only when targets are missing.
    Phase 3 detects clients and emits snippets (always print-only).
    Phase 4 re-runs doctor IFF apply=True (no point re-running in dry mode).
    """
    initial = run_doctor()
    plan: list[PlanItem] = []

    # Phase 1: remediation for fail/warn doctor results.
    plan.extend(build_remediation(initial))

    # Phase 2: filesystem scaffolding.
    plan.append(ensure_anchor_dir(home / ".unitares", apply=apply))
    plan.append(ensure_secrets_file(
        home / ".config" / "cirwel" / "secrets.env",
        apply=apply,
    ))

    # Phase 3: client detection + snippet generation.
    detected = detect_clients(home)
    repo_root = REPO_ROOT
    for client, info in detected.items():
        plan.append(build_snippet(
            client=client,
            config_path=info["config_path"],
            fmt=info["format"],
            repo_root=repo_root,
            proxy_url=proxy_url,
        ))

    # Phase 4: re-run doctor only when we actually mutated something.
    final = run_doctor() if apply else None

    final_pass = (
        final is not None
        and not any(r["status"] == "fail" for r in final.get("results", []))
    )
    exit_code = 0 if (final is None or final_pass) else 1

    return {
        "schema_version": SCHEMA_VERSION,
        "doctor_initial": initial,
        "plan": plan,
        "doctor_final": final,
        "exit_code": exit_code,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): five-phase pipeline orchestration with idempotent apply"
```

---

## Task 8: CLI entrypoint + JSON output

**Files:**
- Modify: `scripts/install/setup.py` (replace stub `main()` with full CLI)
- Modify: `tests/test_setup_install_script.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_setup_install_script.py`:

```python
def test_main_json_dry_run(setup_mod, monkeypatch, tmp_path, capsys):
    initial = _doctor_payload(("python_version", "pass", "ok"))
    monkeypatch.setattr(setup_mod, "run_doctor", lambda: initial)
    monkeypatch.setattr(setup_mod, "Path", setup_mod.Path)
    # Redirect HOME so detect_clients sees nothing.
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = setup_mod.main(["--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = _json.loads(out)
    assert payload["schema_version"] == 1
    assert payload["doctor_final"] is None  # dry-run


def test_main_apply_with_non_interactive_skips_prompt(setup_mod, monkeypatch, tmp_path, capsys):
    healthy = _doctor_payload(("python_version", "pass", "ok"))
    monkeypatch.setattr(setup_mod, "run_doctor", lambda: healthy)
    monkeypatch.setenv("HOME", str(tmp_path))
    # If main attempted input(), this would block. The test passing proves
    # --non-interactive bypasses the prompt.
    rc = setup_mod.main(["--apply", "--non-interactive", "--json"])
    assert rc == 0


def test_main_text_output_lists_remediations(setup_mod, monkeypatch, tmp_path, capsys):
    failing = _doctor_payload(("postgres_running", "fail", "down"))
    monkeypatch.setattr(setup_mod, "run_doctor", lambda: failing)
    monkeypatch.setenv("HOME", str(tmp_path))
    setup_mod.main(["--non-interactive"])  # dry-run + non-interactive
    out = capsys.readouterr().out
    assert "brew install postgresql@17" in out
    assert "remediation" in out.lower() or "phase 1" in out.lower()


def test_main_proxy_url_propagates_to_snippet(setup_mod, monkeypatch, tmp_path, capsys):
    healthy = _doctor_payload(("python_version", "pass", "ok"))
    monkeypatch.setattr(setup_mod, "run_doctor", lambda: healthy)
    fake_home = tmp_path
    (fake_home / ".claude").mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    setup_mod.main([
        "--json",
        "--proxy-url=https://gov.example.org/mcp/",
    ])
    out = capsys.readouterr().out
    payload = _json.loads(out)
    snippet_items = [p for p in payload["plan"] if p["phase"] == 3]
    assert any("UNITARES_STDIO_PROXY_HTTP_URL" in p["snippet"] for p in snippet_items)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 4 new tests fail (main signature doesn't take args; output is empty).

- [ ] **Step 3: Implement the full CLI**

Edit `scripts/install/setup.py`. Add to imports:

```python
import argparse
```

Replace the stub `main()` at the bottom with:

```python
def render_text(result: dict, use_color: bool) -> str:
    """Human-readable rendering of the wizard plan + final doctor pass.
    Color codes match doctor's so the eye can scan both outputs the same way.
    """
    pass_color, fail_color, warn_color, reset = (
        ("\033[32m", "\033[31m", "\033[33m", "\033[0m") if use_color
        else ("", "", "", "")
    )
    lines: list[str] = []
    lines.append("=== UNITARES setup ===")

    initial = result["doctor_initial"]
    fails = sum(1 for r in initial["results"] if r["status"] == "fail")
    warns = sum(1 for r in initial["results"] if r["status"] == "warn")
    passes = sum(1 for r in initial["results"] if r["status"] == "pass")
    lines.append(f"\nInitial doctor: {passes} pass · {fails} fail · {warns} warn")

    by_phase: dict[int, list[PlanItem]] = {}
    for item in result["plan"]:
        by_phase.setdefault(item.phase, []).append(item)

    if 1 in by_phase:
        lines.append(f"\n--- Phase 1: remediation ({fail_color}commands you need to run{reset}) ---")
        for item in by_phase[1]:
            lines.append(f"\n# {item.finding}:")
            lines.append(item.command)
            if item.note:
                lines.append(f"# Note: {item.note}")

    if 2 in by_phase:
        lines.append(f"\n--- Phase 2: filesystem scaffolding ---")
        for item in by_phase[2]:
            tag = "applied" if item.applied else ("would create" if not Path(item.path).exists() else "ok (exists)")
            lines.append(f"  {item.kind} {item.path} (mode {item.mode}) — {tag}")

    if 3 in by_phase:
        lines.append(f"\n--- Phase 3: MCP client snippets ({warn_color}paste these manually{reset}) ---")
        for item in by_phase[3]:
            lines.append(f"\n# Client: {item.client}")
            lines.append(f"# Paste into: {item.config_path}")
            lines.append(item.snippet)

    if result["doctor_final"]:
        f_fails = sum(1 for r in result["doctor_final"]["results"] if r["status"] == "fail")
        f_passes = sum(1 for r in result["doctor_final"]["results"] if r["status"] == "pass")
        lines.append(f"\nFinal doctor: {f_passes} pass · {f_fails} fail")

    lines.append("\n--- Next steps ---")
    lines.append("1. Restart your MCP client(s) to pick up the new mcpServers entry.")
    lines.append("2. (Optional, operator path) Run `python src/mcp_server.py --port 8767` to start the HTTP server.")
    lines.append("3. Verify: in Claude Code run a quick onboard(). Logs at ~/Library/Logs/Claude/mcp*.log if it errors.")
    lines.append("4. Read docs/guides/START_HERE.md for the agent-side workflow.")

    return "\n".join(lines)


def _plan_to_json_safe(plan: list[PlanItem]) -> list[dict]:
    """Convert dataclass items to dicts; only include non-empty fields so the
    JSON envelope stays readable."""
    out: list[dict] = []
    for item in plan:
        d = asdict(item)
        out.append({k: v for k, v in d.items() if v not in ("", False) or k in ("phase", "kind")})
    return out


def main(argv: list[str] | None = None) -> int:
    bootstrap_check()

    parser = argparse.ArgumentParser(
        description="Guided UNITARES install wizard.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Mutate ~/.unitares/ and ~/.config/cirwel/secrets.env if missing.")
    parser.add_argument("--json", dest="json_out", action="store_true",
                        help="Emit machine-readable JSON; suppresses interactive prompts.")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip the apply confirmation prompt (for CI).")
    parser.add_argument("--proxy-url", default=None,
                        help="Generate snippets that forward to a remote HTTP governance server.")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if args.apply and not args.json_out and not args.non_interactive:
        # Show the dry-run plan first, then confirm.
        dry = run_pipeline(apply=False, home=Path.home(), proxy_url=args.proxy_url)
        print(render_text(dry, use_color=not args.no_color and sys.stdout.isatty()))
        ans = input("\nApply the filesystem mutations above? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1

    result = run_pipeline(
        apply=args.apply,
        home=Path.home(),
        proxy_url=args.proxy_url,
    )

    if args.json_out:
        payload = {
            "schema_version": result["schema_version"],
            "doctor_initial": result["doctor_initial"],
            "plan": _plan_to_json_safe(result["plan"]),
            "doctor_final": result["doctor_final"],
            "exit_code": result["exit_code"],
        }
        print(json.dumps(payload, indent=2))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print(render_text(result, use_color=use_color))

    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 31 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/install/setup.py tests/test_setup_install_script.py
git commit -m "feat(setup): CLI entrypoint with --apply/--json/--non-interactive/--proxy-url"
```

---

## Task 9: End-to-end live run + manual verification

**Files:**
- No new files. This task validates against the real install.

- [ ] **Step 1: Run the wizard against the live install (dry-run)**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/unitares-setup
python3 scripts/install/setup.py --non-interactive
```

Expected: a plan that lists Phase 2 items as "ok (exists)" for both `~/.unitares/` and `~/.config/cirwel/secrets.env` (because they exist on Kenny's main machine). Phase 3 lists snippets for whichever clients are detected. Final doctor section is absent (dry-run).

- [ ] **Step 2: Verify --json output validates schema**

```bash
python3 scripts/install/setup.py --json --non-interactive | jq '.schema_version'
```

Expected: `1`

```bash
python3 scripts/install/setup.py --json --non-interactive | jq '.plan | length'
```

Expected: a positive integer (the number of plan items).

- [ ] **Step 3: Run --apply against a tmpdir HOME (safe second-machine simulation)**

```bash
TMPHOME=$(mktemp -d)
HOME=$TMPHOME python3 scripts/install/setup.py --apply --non-interactive --json | jq '.doctor_final != null'
ls -la $TMPHOME/.unitares
ls -la $TMPHOME/.config/cirwel/secrets.env
```

Expected: `true`. Anchor dir is mode `drwx------` (0o700). Secrets file is mode `-rw-------` (0o600).

```bash
rm -rf $TMPHOME
```

- [ ] **Step 4: Run the full test suite locally**

```bash
python3 -m pytest tests/test_setup_install_script.py --no-cov --tb=short -q
```

Expected: 31 passed.

- [ ] **Step 5: Run test-cache.sh per repo convention**

```bash
./scripts/dev/test-cache.sh
```

Expected: cache hit if the working tree hasn't changed since the last run; otherwise a full pytest pass.

If anything fails: stop, do not commit, debug. The plan does not have a "fix it later" step.

---

## Task 10: Ship

**Files:** No new files. This is the delivery step.

- [ ] **Step 1: Verify clean tree on the worktree branch**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/unitares-setup
git status -sb
```

Expected: `## feat/unitares-setup` and no uncommitted changes (everything from tasks 1–8 was committed inline).

- [ ] **Step 2: Push via ship.sh**

```bash
./scripts/dev/ship.sh "feat: unitares setup wizard — guided install for stdio MCP clients"
```

Expected: ship.sh classifies as "other" (scripts/install/ + tests/ are not runtime), commits any straggler, and pushes to `feat/unitares-setup`. No PR required (per `feedback_ship-sh-routing.md`).

- [ ] **Step 3: Fast-forward master**

```bash
git -C /Users/cirwel/projects/unitares fetch origin master
git -C /Users/cirwel/projects/unitares push origin feat/unitares-setup:master
```

If non-fast-forward: rebase the branch on the worktree, then push:

```bash
git rebase origin/master
git -C /Users/cirwel/projects/unitares push origin HEAD:master
```

Expected: master advanced to the new commit.

- [ ] **Step 4: Clean up**

```bash
git -C /Users/cirwel/projects/unitares push origin --delete feat/unitares-setup
git -C /Users/cirwel/projects/unitares worktree remove /Users/cirwel/projects/unitares/.worktrees/unitares-setup
git -C /Users/cirwel/projects/unitares branch -D feat/unitares-setup
```

Expected: remote branch gone, worktree removed, local branch ref deleted.

---

## Self-review notes

**Spec coverage:**

- ✓ Bootstrap (Phase 0) → Task 1
- ✓ Phase 1 (doctor + remediation) → Tasks 2–3
- ✓ Phase 2 (anchor dir + secrets file) → Task 4
- ✓ Phase 3 (client detection + snippets) → Tasks 5–6
- ✓ Phases 4–5 (final doctor + next steps) → Task 7 + Task 8 render_text
- ✓ `--json` schema → Task 8
- ✓ `--apply` confirmation gate → Task 8
- ✓ `--non-interactive` for CI → Task 8
- ✓ `--proxy-url` for remote-server snippet → Task 6 + Task 8
- ✓ Idempotency invariants → Task 4 + Task 7 tests
- ✓ Acceptance criteria 1, 2, 4, 5 → Task 9 (criterion 3 requires real Claude Code restart, manual outside this plan)

**Type consistency:** All tasks use `PlanItem` with the fields declared in Task 3. `run_doctor()` returns `dict`; downstream consumers index by string keys. `detect_clients()` returns `dict[str, dict]`; `build_snippet()` consumes those dict values.

**Placeholder scan:** No TBD/TODO/"implement later" except the deliberate Copilot-CLI TODO note inside the speculative snippet (Task 6), which is an explicit contract with the user and is tested.

**Out of scope (per spec):** No postgres install, no SQL execution, no client-config mutation, no curl-installer, no operator-tier setup. None of these appear in any task.
