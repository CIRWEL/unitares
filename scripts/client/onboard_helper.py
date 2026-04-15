#!/usr/bin/env python3
"""Onboard helper for UNITARES client hooks.

Owns the flow:

1. Read existing ``.unitares/session.json`` cache (if any).
2. Call ``onboard`` — preferring ``continuity_token`` from cache, then
   ``client_session_id``.
3. If the server reports ``trajectory_required`` (identity exists but lacks a
   verifiable signal), retry once with ``force_new=true``.
4. Only write the cache when onboard succeeded and produced a usable uuid.

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
# Session identity is MACHINE-level, not workspace-level. A single agent
# identity persists across every workspace, git worktree, and Discord thread
# on the same machine. If callers want a workspace-specific identity, they
# can override via UNITARES_SESSION_CACHE_PATH.
DEFAULT_CACHE_ROOT_ENV = "HOME"


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


def _cache_path(cache_root: Path) -> Path:
    return cache_root / CACHE_DIR / CACHE_FILE


def _read_cache(cache_root: Path) -> dict:
    path = _cache_path(cache_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(cache_root: Path, payload: dict) -> None:
    path = _cache_path(cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_cache_root() -> Path:
    """Return the machine-level identity cache root (``$HOME`` by default)."""
    override = os.environ.get("UNITARES_SESSION_CACHE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    home = os.environ.get(DEFAULT_CACHE_ROOT_ENV) or os.path.expanduser("~")
    return Path(home).expanduser().resolve()


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
    cached_token = (cache.get("continuity_token") or "").strip()
    cached_session = (cache.get("client_session_id") or "").strip()
    if cached_token:
        arguments["continuity_token"] = cached_token
    elif cached_session:
        arguments["client_session_id"] = cached_session

    raw = post_json(url, {"name": "onboard", "arguments": arguments}, timeout, auth_token)
    parsed = unwrap_tool_response(raw)

    used_force_new = False
    if not is_successful_onboard(parsed) and trajectory_required(parsed):
        # Cache is stale or missing — identity exists server-side and refuses
        # to hand it back without a signature. Fall back to a new identity.
        retry_args = {"name": agent_name, "model_type": model_type, "force_new": True}
        raw = post_json(url, {"name": "onboard", "arguments": retry_args}, timeout, auth_token)
        parsed = unwrap_tool_response(raw)
        used_force_new = True

    if not is_successful_onboard(parsed):
        return {
            "status": "onboard_failed",
            "error": parsed.get("error", "onboard returned no uuid"),
            "recovery_reason": (parsed.get("recovery") or {}).get("reason", ""),
            "used_force_new": used_force_new,
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
        "used_force_new": used_force_new,
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
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    auth_token = os.environ.get("UNITARES_HTTP_API_TOKEN") or None
    workspace = Path(args.workspace).expanduser().resolve()
    result = run_onboard(
        server_url=args.server_url,
        agent_name=args.name,
        model_type=args.model_type,
        workspace=workspace,
        auth_token=auth_token,
        timeout=args.timeout,
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
