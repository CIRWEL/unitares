"""Shared utilities for UNITARES agents — extracted from vigil/sentinel."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


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
    """Save JSON state atomically."""
    atomic_write(path, json.dumps(state))


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


def capture_process_fingerprint(
    transport: str = "unknown",
    anchor_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the client-reported process_fingerprint for onboard().

    Concurrent identity binding invariant (issue #123). The server uses this
    tuple to detect same-UUID siphoning across live execution contexts. The
    fingerprint is declaration-only: it is recorded for audit, never used to
    resolve or recover identity.

    Fields:
      - host_id: stable per-machine identifier (hostname + machine-id hash)
      - pid, pid_start_time: identify the current process even across PID reuse
      - ppid: optional evidence for lineage verification
      - tty: nullable — daemons have no controlling TTY
      - transport: caller-declared MCP channel (stdio/http/websocket/...)
      - anchor_path_hash: SHA-256 of the resident's anchor file path if any

    All fields are best-effort: any capture failure yields a skipped field
    rather than an exception. The caller passes the resulting dict straight
    into onboard(process_fingerprint=...).
    """
    fp: Dict[str, Any] = {}

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    machine_id = ""
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(candidate, "r") as f:
                machine_id = f.read().strip()
            if machine_id:
                break
        except Exception:
            continue
    if not machine_id and sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode()
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    machine_id = line.split('"')[-2]
                    break
        except Exception:
            pass

    fp["host_id"] = hashlib.sha256(
        f"{hostname}:{machine_id}".encode()
    ).hexdigest()[:16]

    try:
        fp["pid"] = os.getpid()
    except Exception:
        pass

    try:
        fp["ppid"] = os.getppid()
    except Exception:
        pass

    try:
        import psutil  # type: ignore
        fp["pid_start_time"] = psutil.Process().create_time()
    except Exception:
        # Linux fallback: parse /proc/self/stat field 22 (starttime in clock ticks
        # since boot). Combine with /proc/stat's btime to get epoch seconds.
        try:
            with open(f"/proc/{os.getpid()}/stat", "r") as f:
                stat_fields = f.read().split()
            starttime_ticks = int(stat_fields[21])
            with open("/proc/stat", "r") as f:
                for line in f:
                    if line.startswith("btime "):
                        btime = int(line.split()[1])
                        break
                else:
                    btime = 0
            hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
            if hz > 0 and btime > 0:
                fp["pid_start_time"] = float(btime + starttime_ticks / hz)
        except Exception:
            pass

    try:
        if os.isatty(0):
            fp["tty"] = os.ttyname(0)
    except Exception:
        pass

    if transport:
        fp["transport"] = transport

    if anchor_path:
        try:
            fp["anchor_path_hash"] = hashlib.sha256(
                anchor_path.encode()
            ).hexdigest()[:16]
        except Exception:
            pass

    return fp
