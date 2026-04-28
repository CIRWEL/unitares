#!/usr/bin/env python3
"""Operator repair tool for identity hijack / orphan cleanup incidents.

This script intentionally bypasses MCP identity resolution. Use it when a
client transport is stuck resolving to the wrong UUID and further tool calls
would create more pollution.

Dry-run by default. Pass --apply to write.

Examples:
    # Restore a resident label and archive accidentally minted orphans.
    python3 scripts/ops/identity_damage_control.py \
        --restore-label f92dcea8 Sentinel \
        --archive 366a5c42 --archive f4c5b8c2 --archive b91972b7 --archive 26570c5b

    # Apply after reviewing dry-run output.
    python3 scripts/ops/identity_damage_control.py --apply \
        --restore-label f92dcea8 Sentinel \
        --archive 366a5c42 --archive f4c5b8c2 --archive b91972b7 --archive 26570c5b \
        --reason "Hermes/Mnemos accidentally reused Sentinel resident UUID"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

MIN_PREFIX_LEN = 8
UUID_PREFIX_RE = re.compile(r"^[0-9a-fA-F-]+$")


class ResolutionError(RuntimeError):
    """Raised when an operator-supplied UUID/prefix is unsafe to use."""


def _validate_uuid_hint(value: str) -> str:
    hint = value.strip()
    if len(hint) < MIN_PREFIX_LEN:
        raise argparse.ArgumentTypeError(
            f"UUID hint must be at least {MIN_PREFIX_LEN} characters"
        )
    if not UUID_PREFIX_RE.match(hint):
        raise argparse.ArgumentTypeError(
            f"UUID hint may contain only hex digits and dashes: {value!r}"
        )
    return hint.lower()


def _note_suffix(reason: str) -> str:
    return f"identity_damage_control: {reason}"


async def resolve_agent_hint(conn: Any, hint: str) -> str:
    """Resolve an exact UUID or unique prefix across core.agents/identities."""
    rows = await conn.fetch(
        """
        SELECT id
        FROM (
            SELECT a.id::text AS id FROM core.agents a WHERE a.id::text LIKE $1
            UNION
            SELECT i.agent_id::text AS id FROM core.identities i WHERE i.agent_id::text LIKE $1
        ) candidates
        ORDER BY id
        """,
        f"{hint}%",
    )
    ids = [str(r["id"]) for r in rows]
    if not ids:
        raise ResolutionError(f"{hint}: no matching agent/identity UUID")
    if len(ids) > 1:
        sample = ", ".join(i[:12] for i in ids[:8])
        raise ResolutionError(
            f"{hint}: ambiguous prefix matched {len(ids)} UUIDs ({sample})"
        )
    return ids[0]


async def load_agent_snapshot(conn: Any, agent_id: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT
            a.id::text AS agent_id,
            a.label,
            a.status AS agent_status,
            a.tags,
            a.notes,
            a.archived_at,
            i.identity_id,
            i.status AS identity_status,
            i.disabled_at,
            i.metadata,
            EXISTS (
                SELECT 1 FROM core.substrate_claims sc
                WHERE sc.agent_id = a.id
            ) AS has_substrate_claim
        FROM core.agents a
        LEFT JOIN core.identities i ON i.agent_id = a.id
        WHERE a.id = $1
        """,
        agent_id,
    )
    if not row:
        raise ResolutionError(f"{agent_id}: no core.agents row found")
    return dict(row)


def _metadata_patch(label: str | None = None, reason: str | None = None) -> str:
    patch: dict[str, Any] = {
        "identity_damage_control": {
            "reason": reason,
            "tool": "scripts/ops/identity_damage_control.py",
        }
    }
    if label is not None:
        patch["label"] = label
    return json.dumps(patch)


async def restore_label(
    conn: Any,
    *,
    agent_id: str,
    label: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    before = await load_agent_snapshot(conn, agent_id)
    result = {
        "operation": "restore_label",
        "agent_id": agent_id,
        "before_label": before.get("label"),
        "after_label": label,
        "applied": apply,
    }
    if not apply:
        return result

    await conn.execute(
        """
        UPDATE core.agents
        SET label = $2,
            notes = concat_ws(E'\n', NULLIF(notes, ''), $3),
            updated_at = now()
        WHERE id = $1
        """,
        agent_id,
        label,
        _note_suffix(reason),
    )
    await conn.execute(
        """
        UPDATE core.identities
        SET metadata = metadata || $2::jsonb,
            updated_at = now()
        WHERE agent_id = $1
        """,
        agent_id,
        _metadata_patch(label=label, reason=reason),
    )
    return result


async def archive_agent(
    conn: Any,
    *,
    agent_id: str,
    reason: str,
    apply: bool,
    allow_resident_archive: bool,
) -> dict[str, Any]:
    before = await load_agent_snapshot(conn, agent_id)
    tags = before.get("tags") or []
    protected = bool(before.get("has_substrate_claim")) or "persistent" in tags
    if protected and not allow_resident_archive:
        raise ResolutionError(
            f"{agent_id[:12]}: refuses to archive resident/substrate agent "
            "(pass --allow-resident-archive only if this is intentional)"
        )

    result = {
        "operation": "archive",
        "agent_id": agent_id,
        "label": before.get("label"),
        "agent_status": before.get("agent_status"),
        "identity_status": before.get("identity_status"),
        "sessions_deactivated": 0,
        "applied": apply,
    }
    if not apply:
        return result

    await conn.execute(
        """
        UPDATE core.agents
        SET status = 'archived',
            archived_at = COALESCE(archived_at, now()),
            notes = concat_ws(E'\n', NULLIF(notes, ''), $2),
            updated_at = now()
        WHERE id = $1
        """,
        agent_id,
        _note_suffix(reason),
    )
    await conn.execute(
        """
        UPDATE core.identities
        SET status = 'archived',
            disabled_at = COALESCE(disabled_at, now()),
            metadata = metadata || $2::jsonb,
            updated_at = now()
        WHERE agent_id = $1
        """,
        agent_id,
        _metadata_patch(reason=reason),
    )
    sessions = await conn.execute(
        """
        UPDATE core.sessions s
        SET is_active = FALSE,
            expires_at = LEAST(expires_at, now()),
            metadata = s.metadata || $2::jsonb
        FROM core.identities i
        WHERE s.identity_id = i.identity_id
          AND i.agent_id = $1
          AND s.is_active = TRUE
        """,
        agent_id,
        json.dumps({"identity_damage_control": {"reason": reason}}),
    )
    try:
        result["sessions_deactivated"] = int(str(sessions).split()[-1])
    except (ValueError, IndexError):
        result["sessions_deactivated"] = 0
    return result


async def _run(args: argparse.Namespace) -> int:
    from src.db import get_db, init_db

    await init_db()
    db = get_db()

    reason = args.reason or "operator identity damage-control repair"
    async with db.acquire() as conn:
        restore_target = None
        archive_targets: list[str] = []

        if args.restore_label:
            restore_hint, label = args.restore_label
            restore_target = (await resolve_agent_hint(conn, restore_hint), label)
        for hint in args.archive:
            archive_targets.append(await resolve_agent_hint(conn, hint))

        if args.apply:
            async with conn.transaction():
                results = []
                if restore_target:
                    agent_id, label = restore_target
                    results.append(await restore_label(
                        conn, agent_id=agent_id, label=label, reason=reason, apply=True
                    ))
                for agent_id in archive_targets:
                    results.append(await archive_agent(
                        conn,
                        agent_id=agent_id,
                        reason=reason,
                        apply=True,
                        allow_resident_archive=args.allow_resident_archive,
                    ))
        else:
            results = []
            if restore_target:
                agent_id, label = restore_target
                results.append(await restore_label(
                    conn, agent_id=agent_id, label=label, reason=reason, apply=False
                ))
            for agent_id in archive_targets:
                results.append(await archive_agent(
                    conn,
                    agent_id=agent_id,
                    reason=reason,
                    apply=False,
                    allow_resident_archive=args.allow_resident_archive,
                ))

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"identity_damage_control {mode}")
    print(json.dumps(results, indent=2, sort_keys=True, default=str))
    if not args.apply:
        print("\nNo changes written. Re-run with --apply after reviewing the plan.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair labels and archive explicit orphan agents without MCP identity resolution.",
    )
    parser.add_argument(
        "--restore-label",
        nargs=2,
        metavar=("UUID_OR_PREFIX", "LABEL"),
        help="Restore the display label for one agent UUID/prefix.",
    )
    parser.add_argument(
        "--archive",
        action="append",
        default=[],
        type=_validate_uuid_hint,
        metavar="UUID_OR_PREFIX",
        help="Archive an explicit orphan UUID/prefix. May be repeated.",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Incident note written to affected rows.",
    )
    parser.add_argument(
        "--allow-resident-archive",
        action="store_true",
        help="Allow archiving a persistent/substrate-claimed agent. Dangerous.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run only.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.restore_label:
        args.restore_label[0] = _validate_uuid_hint(args.restore_label[0])
    if not args.restore_label and not args.archive:
        parser.error("provide --restore-label and/or at least one --archive")
    try:
        return asyncio.run(_run(args))
    except ResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: identity damage-control failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
