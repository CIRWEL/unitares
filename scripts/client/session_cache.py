#!/usr/bin/env python3
"""Transport-neutral local cache helper for UNITARES client adapters.

Stores lightweight continuity state in:

    .unitares/session.json
    .unitares/last-milestone.json

This helper is intentionally small and dependency-free so Claude hooks, Codex
commands, and other thin clients can share one cache format.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = ".unitares"
CACHE_FILES = {
    "session": "session.json",
    "milestone": "last-milestone.json",
}


def _workspace_path(raw: str | None) -> Path:
    base = raw or os.getcwd()
    return Path(base).expanduser().resolve()


def _cache_path(kind: str, workspace: Path) -> Path:
    try:
        filename = CACHE_FILES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown cache kind: {kind}") from exc
    return workspace / CACHE_DIR / filename


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.json
    if raw is None and not sys.stdin.isatty():
        raw = sys.stdin.read()
    if raw is None:
        return {}
    raw = raw.strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    return data


def cmd_path(args: argparse.Namespace) -> int:
    workspace = _workspace_path(args.workspace)
    print(_cache_path(args.kind, workspace))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    workspace = _workspace_path(args.workspace)
    payload = _read_json(_cache_path(args.kind, workspace))
    if args.key:
        value = payload.get(args.key)
        if value is None:
            return 0
        if isinstance(value, (dict, list)):
            print(json.dumps(value))
        else:
            print(value)
        return 0
    print(json.dumps(payload))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    workspace = _workspace_path(args.workspace)
    path = _cache_path(args.kind, workspace)
    payload = _load_payload(args)
    if args.merge:
        existing = _read_json(path)
        existing.update(payload)
        payload = existing
    if args.stamp:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(path, payload)
    if args.echo:
        print(json.dumps(payload))
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    workspace = _workspace_path(args.workspace)
    path = _cache_path(args.kind, workspace)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_path = sub.add_parser("path", help="Print the absolute cache path")
    p_path.add_argument("kind", choices=sorted(CACHE_FILES))
    p_path.add_argument("--workspace")
    p_path.set_defaults(func=cmd_path)

    p_get = sub.add_parser("get", help="Read cached JSON")
    p_get.add_argument("kind", choices=sorted(CACHE_FILES))
    p_get.add_argument("--workspace")
    p_get.add_argument("--key")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="Write cached JSON")
    p_set.add_argument("kind", choices=sorted(CACHE_FILES))
    p_set.add_argument("--workspace")
    p_set.add_argument("--json")
    p_set.add_argument("--merge", action="store_true")
    p_set.add_argument("--stamp", action="store_true")
    p_set.add_argument("--echo", action="store_true")
    p_set.set_defaults(func=cmd_set)

    p_clear = sub.add_parser("clear", help="Delete a cache file")
    p_clear.add_argument("kind", choices=sorted(CACHE_FILES))
    p_clear.add_argument("--workspace")
    p_clear.set_defaults(func=cmd_clear)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"session_cache.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
