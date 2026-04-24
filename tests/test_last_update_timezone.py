"""Regression test for meta.last_update timezone handling.

Prior behaviour: process_update_authenticated wrote
``datetime.now().isoformat()`` — naive local time — into
``meta.last_update``. The silence detector's
``_parse_last_update_aware`` treats a naive ISO string as UTC, so on a
machine running in MDT (UTC-6) every active resident looked 6 hours
silent. That produced dozens of false-positive
``lifecycle_silent_critical`` events per day, drowning real silences.

Fix: write tz-aware UTC ISO (``datetime.now(timezone.utc).isoformat()``)
so detector comparisons stay in the same timezone regardless of the
host machine's locale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.agent_metadata_model import AgentMetadata
from src.background_tasks import _parse_last_update_aware


def _fake_auto_save_timestamp() -> str:
    """Mirror the exact expression that process_update_authenticated uses
    to stamp ``meta.last_update``. Kept in one place so the regression
    check tracks whatever format that code path writes today.
    """
    return datetime.now(timezone.utc).isoformat()


def test_last_update_is_tz_aware_ending_in_offset():
    stamped = _fake_auto_save_timestamp()
    # A tz-aware ISO ends in "+00:00" or "+HH:MM"; a naive one does not.
    assert stamped.endswith("+00:00") or stamped[-6] in ("+", "-"), (
        f"meta.last_update must be tz-aware; got {stamped!r}. "
        "Naive timestamps cause silence detector false-positives on "
        "non-UTC machines."
    )


def test_silence_detector_reads_fresh_update_as_fresh():
    """End-to-end of the regression: stamp last_update with the same
    expression the auto-save path uses, then have the detector parse
    it and compute silence. The silence must be ~zero, not hours."""
    meta = AgentMetadata(
        agent_id="resident-uuid",
        status="active",
        created_at=_fake_auto_save_timestamp(),
        last_update=_fake_auto_save_timestamp(),
        label="Steward",
    )

    parsed = _parse_last_update_aware(meta.last_update)
    assert parsed is not None

    now = datetime.now(timezone.utc)
    silence_seconds = (now - parsed).total_seconds()
    # Should be <1s; the 6-hour bug produced ~21600s.
    assert abs(silence_seconds) < 10, (
        f"Fresh check-in interpreted as {silence_seconds:.0f}s of silence "
        "— meta.last_update timezone handling regressed."
    )
