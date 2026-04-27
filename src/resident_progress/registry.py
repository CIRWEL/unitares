"""Label-keyed config for the resident-progress probe.

Resident UUIDs are NOT stored here. They resolve at tick time from
filesystem anchors, so a resident that re-onboards or rotates UUID is
picked up automatically. See
docs/superpowers/specs/2026-04-25-resident-progress-detection-design.md
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ANCHOR_DIR = Path.home() / ".unitares" / "anchors"


@dataclass(frozen=True)
class ResidentConfig:
    source: str       # source.name as defined in sources.py
    metric: str       # human-readable metric label, recorded on snapshot row
    window: timedelta
    threshold: int    # candidate fires when measured metric is strictly less than threshold


RESIDENT_PROGRESS_REGISTRY: dict[str, ResidentConfig] = {
    "vigil":      ResidentConfig("kg_writes",        "rows_written", timedelta(minutes=60),  1),
    "watcher":    ResidentConfig("watcher_findings", "rows_any",     timedelta(hours=6),     1),
    "steward":    ResidentConfig("eisv_sync_rows",   "rows_written", timedelta(minutes=30),  1),
    "chronicler": ResidentConfig("metrics_series",   "rows_written", timedelta(hours=26),    1),
    "sentinel":   ResidentConfig("sentinel_pulse",   "latest_count", timedelta(minutes=30),  1),
}


def resolve_resident_uuid(label: str) -> str | None:
    """Read ~/.unitares/anchors/<label>.json and return the agent_uuid, or None."""
    path = ANCHOR_DIR / f"{label}.json"
    try:
        with path.open() as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("anchor %s unreadable: %s", path, e)
        return None
    uuid = doc.get("agent_uuid")
    return uuid if isinstance(uuid, str) and uuid else None
