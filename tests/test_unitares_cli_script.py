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
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "unitares"
DEFAULT_URL = "http://localhost:8767"


def _unique_agent_name() -> str:
    """Give each test a fresh identity so repeat runs don't collide with
    the server's trajectory-verification guard on resume."""
    return f"cli-pytest-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


TEST_AGENT_RESUMABLE = "cli-pytest-probe-resume-fixture"


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
    """Minimal env for the CLI: clean URL, unique per-test agent, temp session file.

    A unique agent name avoids collisions with the server's
    trajectory-verification guard when the test is rerun in the same
    governance database.
    """
    env = os.environ.copy()
    env.pop("UNITARES_URL", None)  # force default localhost
    env["UNITARES_AGENT"] = _unique_agent_name()
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
    assert f"UNITARES_AGENT  : {cli_env['UNITARES_AGENT']}" in result.stdout
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

    agent = cli_env["UNITARES_AGENT"]
    result = _run(cli_env, "onboard", agent, "pytest regression run")
    assert "Welcome:" in result.stdout
    assert "Session:" in result.stdout

    assert session_file.exists(), "onboard should create the session file"
    payload = json.loads(session_file.read_text())
    assert payload.get("agent_id") == agent
    # Server returns client_session_id — CLI must persist it.
    assert payload.get("client_session_id"), "session id not persisted"
    # Continuity token is recommended for resume.
    assert payload.get("continuity_token"), "continuity token not persisted"


def test_metrics_after_onboard_shows_eisv(cli_env):
    _run(cli_env, "onboard", cli_env["UNITARES_AGENT"], "pytest")
    result = _run(cli_env, "metrics")
    assert "EISV:" in result.stdout
    assert "E=" in result.stdout and "I=" in result.stdout


def test_update_returns_verdict(cli_env):
    _run(cli_env, "onboard", cli_env["UNITARES_AGENT"], "pytest")
    result = _run(cli_env, "update", "pytest regression cli update", "0.2", "0.75")
    assert "Verdict:" in result.stdout
    # Proceed is the overwhelmingly common outcome for a low-complexity update.
    assert any(v in result.stdout for v in ("proceed", "guide", "pause", "reject"))


def test_session_command_shows_config(cli_env):
    agent = cli_env["UNITARES_AGENT"]
    _run(cli_env, "onboard", agent, "pytest")
    result = _run(cli_env, "session")
    assert f"Agent ID:     {agent}" in result.stdout
    assert "URL:          http://localhost:8767" in result.stdout
    assert "Continuity:   present" in result.stdout


def test_reset_removes_session_file(cli_env):
    _run(cli_env, "onboard", cli_env["UNITARES_AGENT"], "pytest")
    session_file = Path(cli_env["UNITARES_SESSION_FILE"])
    assert session_file.exists()
    _run(cli_env, "reset")
    assert not session_file.exists()


def _run_parser(parser_name: str, body: dict):
    """Invoke a CLI parser function by sourcing the script and piping a
    synthetic response body. Returns the CompletedProcess.

    This is how we regression-test the nested-success-false handling
    (trajectory_required and friends) without needing the live server to
    actually produce that response, which depends on an agent having an
    established trajectory — something hard to stage deterministically in
    a unit test against a shared dev database.
    """
    script = (
        f". {CLI} help >/dev/null 2>&1; "
        f"cat | {parser_name}"
    )
    return subprocess.run(
        ["bash", "-c", script],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_parse_onboard_detects_nested_success_false():
    """Regression for the silent-failure bug: when the server returns
    result.success:false (e.g. established trajectory), parse_onboard
    must exit non-zero with a readable error and hint, not print
    "Welcome: onboarded" and return success.

    This was the bug that caused test_onboard_persists_session_and_
    continuity_token to fail in the full suite on 2026-04-10: the CLI
    wrote an empty session file because it treated a tool-level error
    as success.
    """
    response = {
        "name": "onboard",
        "success": True,  # outer envelope is "OK"
        "result": {
            "success": False,  # but the tool itself failed
            "error": "Identity 'cli-test' has an established trajectory.",
            "recovery": {
                "reason": "trajectory_required",
                "hint": "Provide trajectory_signature or use force_new=true",
            },
        },
    }
    result = _run_parser("parse_onboard", response)
    assert result.returncode != 0, (
        "parse_onboard must exit non-zero on nested success:false\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Traceback" not in result.stderr
    assert "trajectory" in result.stderr.lower()
    assert "hint:" in result.stderr.lower()
    # And critically: must NOT print a "Welcome" line, which would mislead
    # the caller into thinking the onboard succeeded.
    assert "Welcome" not in result.stdout


def test_parse_onboard_accepts_valid_response():
    """Happy path for the parser: success:true, expected fields present."""
    response = {
        "name": "onboard",
        "success": True,
        "result": {
            "success": True,
            "welcome": "Welcome! Session established.",
            "display_name": "cli-happy-path",
            "agent_id": "mcp_20260410",
            "uuid": "11111111-2222-3333-4444-555555555555",
        },
    }
    result = _run_parser("parse_onboard", response)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert "Welcome" in result.stdout
    assert "cli-happy-path" in result.stdout
    assert "11111111" in result.stdout


def test_onboard_with_force_creates_fresh_identity(cli_env):
    """Passing 'force' as the 3rd arg should set force_new=true and let
    the same agent name re-onboard cleanly."""
    agent = cli_env["UNITARES_AGENT"]
    _run(cli_env, "onboard", agent, "pytest force-first")
    first = json.loads(Path(cli_env["UNITARES_SESSION_FILE"]).read_text())

    result = _run(cli_env, "onboard", agent, "pytest force-second", "force")
    assert "Welcome:" in result.stdout
    second = json.loads(Path(cli_env["UNITARES_SESSION_FILE"]).read_text())
    assert second.get("client_session_id"), "force onboard should persist a new session id"
    # The continuity token must be present (value may or may not differ;
    # what we care about is that the path didn't silently produce an empty
    # write, which is what the trajectory-required regression was about).
    assert second.get("continuity_token")


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
