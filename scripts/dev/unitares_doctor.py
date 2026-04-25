#!/usr/bin/env python3
"""Diagnose a UNITARES install.

Usage:
    python3 scripts/dev/unitares_doctor.py
    python3 scripts/dev/unitares_doctor.py --mode local
    python3 scripts/dev/unitares_doctor.py --mode operator
    python3 scripts/dev/unitares_doctor.py --json

Modes:
    local      Checks needed for stdio-only adoption (postgres + schema +
               anchor dir). Sufficient for a fresh-machine bring-up where the
               agent client spawns governance directly via stdio.
    operator   Adds HTTP/launchd checks: 8767 listening, PID file, LaunchAgent
               loaded, resident-agent plists, cloudflared sidecar.
    all        local + operator. Default.

Stdlib-only. Safe to run before `pip install -e .` finishes — used to verify
that the install can finish.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/governance"
REQUIRED_PG_EXTENSIONS = ("age", "pgcrypto", "pg_trgm", "uuid-ossp", "vector")
RESIDENT_PLISTS = (
    "com.unitares.vigil",
    "com.unitares.sentinel",
    "com.unitares.chronicler",
)
ANCHOR_DIR = Path.home() / ".unitares"
SECRETS_FILE = Path.home() / ".config" / "cirwel" / "secrets.env"
HTTP_HEALTH_URL = "http://127.0.0.1:8767/health/live"
PID_FILE_REL = "data/.mcp_server.pid"


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    mode: str
    status: Status
    message: str
    detail: str = ""


@dataclass
class Check:
    name: str
    mode: str  # "local" or "operator"
    fn: Callable[[], CheckResult]


# ---------------------------------------------------------------------------
# Local-mode checks
# ---------------------------------------------------------------------------


def check_python_version() -> CheckResult:
    name, mode = "python_version", "local"
    v = sys.version_info
    if v >= (3, 12):
        return CheckResult(name, mode, Status.PASS, f"Python {v.major}.{v.minor}.{v.micro}")
    return CheckResult(
        name, mode, Status.FAIL,
        f"Python 3.12+ required (got {v.major}.{v.minor}.{v.micro})",
    )


def check_postgres_running(db_url: str) -> CheckResult:
    name, mode = "postgres_running", "local"
    if shutil.which("pg_isready") is None:
        return CheckResult(name, mode, Status.WARN,
                           "pg_isready not on PATH; install postgresql@17")
    rc = subprocess.run(
        ["pg_isready", "-d", db_url],
        capture_output=True, text=True, timeout=5,
    ).returncode
    if rc == 0:
        return CheckResult(name, mode, Status.PASS, f"reachable at {_redact(db_url)}")
    return CheckResult(name, mode, Status.FAIL,
                       f"pg_isready failed (rc={rc}); try `brew services start postgresql@17`")


def check_governance_database(db_url: str) -> CheckResult:
    name, mode = "governance_database", "local"
    if shutil.which("psql") is None:
        return CheckResult(name, mode, Status.SKIP, "psql not on PATH")
    proc = subprocess.run(
        ["psql", db_url, "-Atqc", "SELECT 1"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode == 0 and proc.stdout.strip() == "1":
        return CheckResult(name, mode, Status.PASS, "governance database accepts queries")
    return CheckResult(name, mode, Status.FAIL,
                       "cannot query governance database",
                       detail=proc.stderr.strip())


def check_pg_extensions(db_url: str) -> CheckResult:
    name, mode = "pg_extensions", "local"
    if shutil.which("psql") is None:
        return CheckResult(name, mode, Status.SKIP, "psql not on PATH")
    proc = subprocess.run(
        ["psql", db_url, "-Atqc", "SELECT extname FROM pg_extension ORDER BY extname"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        return CheckResult(name, mode, Status.FAIL,
                           "could not list extensions", detail=proc.stderr.strip())
    present = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    missing = [e for e in REQUIRED_PG_EXTENSIONS if e not in present]
    if not missing:
        return CheckResult(name, mode, Status.PASS,
                           f"all required extensions present ({len(REQUIRED_PG_EXTENSIONS)})")
    return CheckResult(name, mode, Status.FAIL,
                       f"missing extensions: {', '.join(missing)}")


def check_schema_migrations(db_url: str) -> CheckResult:
    name, mode = "schema_migrations", "local"
    if shutil.which("psql") is None:
        return CheckResult(name, mode, Status.SKIP, "psql not on PATH")
    proc = subprocess.run(
        ["psql", db_url, "-Atqc",
         "SELECT MAX(version) FROM core.schema_migrations"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        return CheckResult(name, mode, Status.FAIL,
                           "core.schema_migrations not queryable",
                           detail=proc.stderr.strip())
    version = proc.stdout.strip()
    if not version:
        return CheckResult(name, mode, Status.FAIL,
                           "core.schema_migrations is empty (run migrations)")
    return CheckResult(name, mode, Status.PASS, f"schema at version {version}")


def check_anchor_dir() -> CheckResult:
    name, mode = "anchor_directory", "local"
    if ANCHOR_DIR.is_dir():
        return CheckResult(name, mode, Status.PASS, f"{ANCHOR_DIR} exists")
    return CheckResult(name, mode, Status.WARN,
                       f"{ANCHOR_DIR} missing — first onboard() will create it")


def check_secrets_file() -> CheckResult:
    name, mode = "secrets_file", "local"
    if not SECRETS_FILE.exists():
        return CheckResult(name, mode, Status.WARN,
                           f"{SECRETS_FILE} not present (only needed if calling external providers)")
    actual = stat.S_IMODE(SECRETS_FILE.stat().st_mode)
    if actual == 0o600:
        return CheckResult(name, mode, Status.PASS, f"{SECRETS_FILE} (0600)")
    return CheckResult(name, mode, Status.FAIL,
                       f"{SECRETS_FILE} mode is {oct(actual)} — must be 0600",
                       detail=f"chmod 600 {SECRETS_FILE}")


# ---------------------------------------------------------------------------
# Operator-mode checks
# ---------------------------------------------------------------------------


def check_http_health() -> CheckResult:
    name, mode = "http_health", "operator"
    try:
        with urllib.request.urlopen(HTTP_HEALTH_URL, timeout=2) as resp:
            if resp.status == 200:
                return CheckResult(name, mode, Status.PASS,
                                   f"{HTTP_HEALTH_URL} returned 200")
            return CheckResult(name, mode, Status.FAIL,
                               f"{HTTP_HEALTH_URL} returned {resp.status}")
    except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as e:
        return CheckResult(name, mode, Status.FAIL,
                           "HTTP health endpoint unreachable",
                           detail=str(e))


def check_pid_file(repo_root: Path) -> CheckResult:
    name, mode = "pid_file", "operator"
    pid_file = repo_root / PID_FILE_REL
    if not pid_file.exists():
        return CheckResult(name, mode, Status.WARN,
                           f"{pid_file} missing — server not running, or stdio mode")
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return CheckResult(name, mode, Status.FAIL,
                           f"{pid_file} is not a valid PID")
    try:
        os.kill(pid, 0)
        return CheckResult(name, mode, Status.PASS, f"pid {pid} alive")
    except ProcessLookupError:
        return CheckResult(name, mode, Status.FAIL, f"pid {pid} not running (stale file)")
    except PermissionError:
        return CheckResult(name, mode, Status.PASS, f"pid {pid} alive (not signalable)")


def _launchctl_loaded() -> set[str]:
    if shutil.which("launchctl") is None:
        return set()
    proc = subprocess.run(["launchctl", "list"],
                          capture_output=True, text=True, timeout=5)
    if proc.returncode != 0:
        return set()
    out = set()
    for line in proc.stdout.splitlines()[1:]:  # skip header
        parts = line.split(None, 2)
        if len(parts) == 3:
            out.add(parts[2])
    return out


def check_launchagent(loaded: set[str]) -> CheckResult:
    name, mode = "launchagent_loaded", "operator"
    label = "com.unitares.governance-mcp"
    if label in loaded:
        return CheckResult(name, mode, Status.PASS, f"{label} loaded")
    return CheckResult(name, mode, Status.WARN,
                       f"{label} not loaded — stdio mode is fine, "
                       f"but `unitares` CLI / remote MCP clients need this")


def check_resident_agents(loaded: set[str]) -> CheckResult:
    name, mode = "resident_agents", "operator"
    missing = [p for p in RESIDENT_PLISTS if p not in loaded]
    if not missing:
        return CheckResult(name, mode, Status.PASS,
                           f"vigil + sentinel + chronicler loaded")
    return CheckResult(name, mode, Status.WARN,
                       f"resident agents not loaded: {', '.join(missing)}")


def check_ipv6_sidecar(loaded: set[str]) -> CheckResult:
    name, mode = "ipv6_sidecar", "operator"
    label = "com.unitares.ipv6-loopback-proxy"
    if label in loaded:
        return CheckResult(name, mode, Status.PASS, f"{label} loaded")
    return CheckResult(name, mode, Status.SKIP,
                       f"{label} not loaded (only needed if cloudflared 2026.3+ is exposing /ws/eisv)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _redact(db_url: str) -> str:
    if "@" in db_url:
        creds, _, rest = db_url.partition("@")
        scheme, _, _ = creds.partition("://")
        return f"{scheme}://***@{rest}"
    return db_url


def build_checks(repo_root: Path, db_url: str) -> list[Check]:
    loaded_cache: dict[str, set[str]] = {}

    def loaded() -> set[str]:
        if "v" not in loaded_cache:
            loaded_cache["v"] = _launchctl_loaded()
        return loaded_cache["v"]

    return [
        Check("python_version", "local", check_python_version),
        Check("postgres_running", "local", lambda: check_postgres_running(db_url)),
        Check("governance_database", "local", lambda: check_governance_database(db_url)),
        Check("pg_extensions", "local", lambda: check_pg_extensions(db_url)),
        Check("schema_migrations", "local", lambda: check_schema_migrations(db_url)),
        Check("anchor_directory", "local", check_anchor_dir),
        Check("secrets_file", "local", check_secrets_file),
        Check("http_health", "operator", check_http_health),
        Check("pid_file", "operator", lambda: check_pid_file(repo_root)),
        Check("launchagent_loaded", "operator", lambda: check_launchagent(loaded())),
        Check("resident_agents", "operator", lambda: check_resident_agents(loaded())),
        Check("ipv6_sidecar", "operator", lambda: check_ipv6_sidecar(loaded())),
    ]


def run_checks(checks: list[Check], mode: str) -> list[CheckResult]:
    selected = [c for c in checks if mode == "all" or c.mode == mode]
    results = []
    for c in selected:
        try:
            results.append(c.fn())
        except Exception as e:  # never crash the whole run
            results.append(CheckResult(c.name, c.mode, Status.FAIL,
                                       "check raised exception", detail=repr(e)))
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_GLYPH = {
    Status.PASS: ("✓", "\033[32m"),
    Status.FAIL: ("✗", "\033[31m"),
    Status.WARN: ("⚠", "\033[33m"),
    Status.SKIP: ("·", "\033[90m"),
}
_RESET = "\033[0m"


def render_text(results: list[CheckResult], use_color: bool) -> str:
    lines = []
    by_mode: dict[str, list[CheckResult]] = {}
    for r in results:
        by_mode.setdefault(r.mode, []).append(r)
    for mode in ("local", "operator"):
        if mode not in by_mode:
            continue
        lines.append(f"\n=== {mode} ===")
        for r in by_mode[mode]:
            glyph, color = _GLYPH[r.status]
            prefix = f"{color}{glyph}{_RESET}" if use_color else glyph
            lines.append(f"  {prefix} {r.name}: {r.message}")
            if r.detail:
                lines.append(f"      {r.detail}")
    fails = sum(1 for r in results if r.status == Status.FAIL)
    warns = sum(1 for r in results if r.status == Status.WARN)
    passes = sum(1 for r in results if r.status == Status.PASS)
    lines.append(f"\n{passes} pass · {fails} fail · {warns} warn")
    return "\n".join(lines)


def exit_code(results: list[CheckResult]) -> int:
    return 1 if any(r.status == Status.FAIL for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("local", "operator", "all"), default="all")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--db-url", default=os.environ.get("DB_POSTGRES_URL", DEFAULT_DB_URL))
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent.parent
    checks = build_checks(repo_root, args.db_url)
    results = run_checks(checks, args.mode)

    if args.json:
        payload = {
            "mode": args.mode,
            "results": [
                {**asdict(r), "status": r.status.value} for r in results
            ],
            "exit_code": exit_code(results),
        }
        print(json.dumps(payload, indent=2))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        print(render_text(results, use_color))

    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
