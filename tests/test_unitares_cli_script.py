"""Regression tests for scripts/unitares — the bash CLI wrapper.

The script is a thin REST client for the governance MCP server, so these tests
require a live server on localhost:8767. The server is started by the user's
LaunchAgent in normal dev; in CI without it, these tests skip cleanly.

What we verify:
    * URL sanitization strips trailing "/mcp" and "/" so a stale
      UNITARES_URL with the streamable-http path still hits the REST API.
    * Clear error reporting on unreachable hosts (no Python traceback leaks).
    * The end-to-end happy path: diag → health → tools → onboard → metrics →
      update, all against a sacrificial agent name and temp session file.
    * Session file persistence of client_session_id + continuity_token.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "unitares"
DEFAULT_URL = "http://localhost:8767"
TEST_AGENT = "cli-pytest-probe"


def _server_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8767), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(),
    reason="governance-mcp not running on localhost:8767",
)


@pytest.fixture
def cli_env(tmp_path):
    """Minimal env for the CLI: clean URL, sacrificial agent, temp session file."""
    env = os.environ.copy()
    env.pop("UNITARES_URL", None)  # force default localhost
    env["UNITARES_AGENT"] = TEST_AGENT
    env["UNITARES_SESSION_FILE"] = str(tmp_path / "session.json")
    env["UNITARES_TIMEOUT"] = "15"
    return env


def _run(env, *args, check=True):
    result = subprocess.run(
        [str(CLI), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"CLI exited {result.returncode}\n"
            f"cmd: {args}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def test_cli_is_executable():
    assert CLI.exists(), f"missing {CLI}"
    assert os.access(CLI, os.X_OK), f"{CLI} is not executable"


def test_diag_reports_localhost_reachable(cli_env):
    result = _run(cli_env, "diag")
    assert "UNITARES_URL    : http://localhost:8767" in result.stdout
    assert f"UNITARES_AGENT  : {TEST_AGENT}" in result.stdout
    assert "Reachability    : OK" in result.stdout


def test_url_sanitization_strips_mcp_suffix(cli_env):
    """A stale URL with /mcp baked on should still hit the REST API."""
    cli_env["UNITARES_URL"] = f"{DEFAULT_URL}/mcp"
    result = _run(cli_env, "diag")
    # After sanitization, the printed URL must NOT contain /mcp.
    assert "UNITARES_URL    : http://localhost:8767" in result.stdout
    assert "/mcp" not in result.stdout.split("UNITARES_URL")[1].split("\n")[0]
    assert "Reachability    : OK" in result.stdout


def test_url_sanitization_strips_trailing_slash(cli_env):
    cli_env["UNITARES_URL"] = f"{DEFAULT_URL}/"
    result = _run(cli_env, "diag")
    assert "UNITARES_URL    : http://localhost:8767" in result.stdout


def test_unreachable_host_fails_cleanly_without_traceback(cli_env):
    """Dead host must exit non-zero with a readable error, not a python traceback."""
    # RFC 5737 TEST-NET-1 — guaranteed non-routable.
    cli_env["UNITARES_URL"] = "http://192.0.2.1:9"
    cli_env["UNITARES_TIMEOUT"] = "2"
    result = _run(cli_env, "health", check=False)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "error" in result.stderr.lower()


def test_health_reports_status_and_version(cli_env):
    result = _run(cli_env, "health")
    assert "Status:" in result.stdout
    assert "Version:" in result.stdout
    assert "DB:" in result.stdout


def test_tools_lists_core_governance_tools(cli_env):
    result = _run(cli_env, "tools")
    assert "Tools:" in result.stdout
    # A few tools are always exposed in lite mode.
    assert "onboard" in result.stdout
    assert "process_agent_update" in result.stdout
    assert "get_governance_metrics" in result.stdout


def test_onboard_persists_session_and_continuity_token(cli_env, tmp_path):
    session_file = Path(cli_env["UNITARES_SESSION_FILE"])
    assert not session_file.exists()

    result = _run(cli_env, "onboard", TEST_AGENT, "pytest regression run")
    assert "Welcome:" in result.stdout
    assert "Session:" in result.stdout

    assert session_file.exists(), "onboard should create the session file"
    payload = json.loads(session_file.read_text())
    assert payload.get("agent_id") == TEST_AGENT
    # Server returns client_session_id — CLI must persist it.
    assert payload.get("client_session_id"), "session id not persisted"
    # Continuity token is recommended for resume.
    assert payload.get("continuity_token"), "continuity token not persisted"


def test_metrics_after_onboard_shows_eisv(cli_env):
    _run(cli_env, "onboard", TEST_AGENT, "pytest")
    result = _run(cli_env, "metrics")
    assert "EISV:" in result.stdout
    assert "E=" in result.stdout and "I=" in result.stdout


def test_update_returns_verdict(cli_env):
    _run(cli_env, "onboard", TEST_AGENT, "pytest")
    result = _run(cli_env, "update", "pytest regression cli update", "0.2", "0.75")
    assert "Verdict:" in result.stdout
    # Proceed is the overwhelmingly common outcome for a low-complexity update.
    assert any(v in result.stdout for v in ("proceed", "guide", "pause", "reject"))


def test_session_command_shows_config(cli_env):
    _run(cli_env, "onboard", TEST_AGENT, "pytest")
    result = _run(cli_env, "session")
    assert f"Agent ID:     {TEST_AGENT}" in result.stdout
    assert "URL:          http://localhost:8767" in result.stdout
    assert "Continuity:   present" in result.stdout


def test_reset_removes_session_file(cli_env):
    _run(cli_env, "onboard", TEST_AGENT, "pytest")
    session_file = Path(cli_env["UNITARES_SESSION_FILE"])
    assert session_file.exists()
    _run(cli_env, "reset")
    assert not session_file.exists()


def test_call_command_returns_pretty_json(cli_env):
    result = _run(cli_env, "call", "get_governance_metrics", "{}")
    # Pretty-printed JSON should be parseable.
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"call output is not valid JSON:\n{result.stdout}")
    assert parsed.get("name") == "get_governance_metrics"
    assert "result" in parsed


def test_call_with_invalid_json_arguments_errors_cleanly(cli_env):
    result = _run(cli_env, "call", "get_governance_metrics", "{not-json}", check=False)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "invalid JSON" in result.stderr or "error" in result.stderr.lower()
