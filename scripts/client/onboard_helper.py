#!/usr/bin/env python3
"""Onboard helper for UNITARES client hooks.

Owns the flow:

1. Read existing ``.unitares/session.json`` cache (if any).
2. Call ``onboard`` — preferring ``continuity_token`` from cache, then
   ``client_session_id``.
3. If the server reports ``trajectory_required`` (identity exists but lacks
   a verifiable signal), return status=``trajectory_required`` with the
   server's recovery hint. We do NOT auto-retry with ``force_new=true``;
   that is an explicit operator decision, not an automatic one (see commit
   718ccd3 and the identity "never silently substitute" invariant).
4. ``force_new=true`` is set only when the caller passed ``--force-new``.
5. Only write the cache when onboard succeeded and produced a usable uuid.

Emits a JSON line on stdout with the resolved fields for the shell hook to
consume. Never raises — always returns a dict on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_SERVER_URL = "http://localhost:8767"
DEFAULT_TIMEOUT = 10.0
CACHE_DIR = ".unitares"
CACHE_FILE = "session.json"


# --- IO primitives (separable for tests) -----------------------------------

def _post_json(url: str, payload: dict, timeout: float, token: str | None) -> dict:
    """POST JSON to ``url`` and return the parsed response, or ``{}`` on error."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _read_cache(workspace: Path) -> dict:
    path = workspace / CACHE_DIR / CACHE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(workspace: Path, payload: dict) -> None:
    path = workspace / CACHE_DIR / CACHE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --- Response unwrap -------------------------------------------------------

def unwrap_tool_response(raw: dict) -> dict:
    """Unwrap the REST ``/v1/tools/call`` envelope.

    Handles two shapes:

    * Native MCP: ``{"result": {"content": [{"text": "<json>"}]}}``
    * REST-direct: ``{"result": {...fields...}}``

    Returns the inner dict, or ``{}`` if unrecognizable.
    """
    if not isinstance(raw, dict):
        return {}
    result = raw.get("result", raw)
    if not isinstance(result, dict):
        return {}
    content = result.get("content")
    if isinstance(content, list) and content:
        item = content[0]
        if isinstance(item, dict) and "text" in item:
            try:
                return json.loads(item["text"])
            except (json.JSONDecodeError, TypeError):
                return {}
    return result


def is_successful_onboard(parsed: dict) -> bool:
    """Onboard is successful iff the response has ``success != False`` and a uuid."""
    if not isinstance(parsed, dict):
        return False
    if parsed.get("success") is False:
        return False
    return bool(parsed.get("uuid"))


def trajectory_required(parsed: dict) -> bool:
    """Detect the ``trajectory_required`` recovery reason."""
    if not isinstance(parsed, dict):
        return False
    if parsed.get("success") is not False:
        return False
    recovery = parsed.get("recovery") or {}
    return isinstance(recovery, dict) and recovery.get("reason") == "trajectory_required"


# --- Core flow -------------------------------------------------------------

def run_onboard(
    *,
    server_url: str,
    agent_name: str,
    model_type: str,
    workspace: Path,
    force_new: bool = False,
    auth_token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    post_json: Callable[[str, dict, float, str | None], dict] = _post_json,
    read_cache: Callable[[Path], dict] = _read_cache,
    write_cache: Callable[[Path, dict], None] = _write_cache,
) -> dict:
    """Run the onboard flow. Returns a dict with status info."""
    url = f"{server_url.rstrip('/')}/v1/tools/call"
    cache = read_cache(workspace)

    arguments: dict[str, Any] = {"name": agent_name, "model_type": model_type}
    if force_new:
        arguments["force_new"] = True
    else:
        cached_token = (cache.get("continuity_token") or "").strip()
        cached_session = (cache.get("client_session_id") or "").strip()
        if cached_token:
            arguments["continuity_token"] = cached_token
        elif cached_session:
            arguments["client_session_id"] = cached_session

    raw = post_json(url, {"name": "onboard", "arguments": arguments}, timeout, auth_token)
    parsed = unwrap_tool_response(raw)

    if not is_successful_onboard(parsed):
        # Per 718ccd3: never auto-force_new. Surface the error so the operator
        # can decide (run `/governance-start --force` or clear the cache).
        # Clobbering trajectory with force_new silently substitutes identity.
        recovery = parsed.get("recovery") or {}
        return {
            "status": "trajectory_required" if trajectory_required(parsed) else "onboard_failed",
            "error": parsed.get("error", "onboard returned no uuid"),
            "recovery_reason": recovery.get("reason", ""),
            "recovery_hint": recovery.get("hint", ""),
        }

    # Build fresh cache payload — never preserve stale fields.
    new_cache = {
        "server_url": server_url,
        "agent_name": agent_name,
        "uuid": parsed.get("uuid"),
        "agent_id": parsed.get("agent_id") or parsed.get("resolved_agent_id") or "",
        "client_session_id": parsed.get("client_session_id", ""),
        "continuity_token": parsed.get("continuity_token", ""),
        "session_resolution_source": parsed.get("session_resolution_source", ""),
        "continuity_token_supported": parsed.get("continuity_token_supported", False),
        "display_name": parsed.get("display_name", ""),
    }
    write_cache(workspace, new_cache)

    return {
        "status": "ok",
        "uuid": new_cache["uuid"],
        "agent_id": new_cache["agent_id"],
        "client_session_id": new_cache["client_session_id"],
        "continuity_token": new_cache["continuity_token"],
        "session_resolution_source": new_cache["session_resolution_source"],
        "continuity_token_supported": new_cache["continuity_token_supported"],
        "display_name": new_cache["display_name"],
    }


# --- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default=os.environ.get("UNITARES_SERVER_URL", DEFAULT_SERVER_URL))
    parser.add_argument("--name", required=True, help="Agent display name")
    parser.add_argument("--model-type", default="claude-code")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--force-new", action="store_true",
                        help="Explicit opt-in to create a fresh identity (never automatic)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    auth_token = os.environ.get("UNITARES_HTTP_API_TOKEN") or None
    workspace = Path(args.workspace).expanduser().resolve()
    result = run_onboard(
        server_url=args.server_url,
        agent_name=args.name,
        model_type=args.model_type,
        workspace=workspace,
        force_new=args.force_new,
        auth_token=auth_token,
        timeout=args.timeout,
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
