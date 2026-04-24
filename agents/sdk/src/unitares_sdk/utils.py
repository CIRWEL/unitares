"""Shared utilities for UNITARES agents — extracted from vigil/sentinel."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def atomic_write(path: Path, data: str, mode: int = 0o600) -> None:
    """Write data to a file atomically via temp file + os.replace.

    File is created with ``mode`` (default 0o600 — owner read/write only).
    ``tempfile.mkstemp`` already creates temp files 0o600 on POSIX, but
    ``os.fchmod`` is called explicitly as defense-in-depth: anchor and
    session files carry continuity tokens, and a future Python/OS change
    to mkstemp defaults would silently regress every caller.
    """
    fd = None
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.write(fd, data.encode())
        os.fchmod(fd, mode)
        os.close(fd)
        fd = None
        os.replace(tmp, str(path))
        tmp = None
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def notify(title: str, message: str) -> None:
    """Send a macOS notification via osascript. No-op on non-macOS."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def load_json_state(path: Path) -> dict:
    """Load JSON state from file. Returns {} if missing or corrupt.

    Handles the current dict format and legacy bare-string format
    (migrated to dict on read).
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
        if isinstance(data, str) and data:
            return {"client_session_id": data}
        return {}
    except (json.JSONDecodeError, OSError):
        try:
            text = path.read_text().strip()
            if text and not text.startswith(("{", "[")):
                return {"client_session_id": text}
        except Exception:
            pass
    return {}


def save_json_state(path: Path, state: dict) -> None:
    """Save JSON state atomically.

    Non-JSON-serializable values (datetime, Path, custom objects) are coerced
    to their str() representation rather than raising TypeError — matching the
    defensive behavior that Vigil's original save_state override provided.
    """
    atomic_write(path, json.dumps(state, default=str))


def parse_continuity_token(token: str) -> dict | None:
    """Parse a v1.<payload>.<sig> continuity token.

    Extracts the payload (base64url-decoded JSON with aid, model, exp, etc.).
    Returns None if the token is malformed or not v1 format.
    Does NOT verify the HMAC signature — that's the server's responsibility.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            return None
        # base64url decode with padding
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        payload = json.loads(payload_bytes.decode())
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception:
        return None


def trim_log(log_file: Path, max_lines: int) -> None:
    """Keep log_file bounded to the last ``max_lines`` lines.

    Silent no-op on OSError or if the file doesn't exist — log rotation
    should never be the reason an agent crashes.
    """
    if not log_file.exists():
        return
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    try:
        log_file.write_text("\n".join(lines[-max_lines:]) + "\n")
    except OSError:
        pass


def validate_token_uuid(token: str, expected_uuid: str) -> bool:
    """Parse token, extract aid, return True if it matches expected_uuid.

    Returns False if token is unparseable or aid doesn't match.
    """
    payload = parse_continuity_token(token)
    if payload is None:
        return False
    aid = payload.get("aid")
    if not aid:
        return False
    return aid == expected_uuid
