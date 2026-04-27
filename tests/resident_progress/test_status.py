from __future__ import annotations

import pytest

from src.resident_progress.status import resolve_status


def _row(**overrides):
    base = {
        "candidate": False, "heartbeat_alive": True,
        "metric_below_threshold": False, "suppressed_reason": None,
        "error_details": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("row,expected", [
    (_row(error_details={"source": "kg_writes"}), "source-error"),
    (_row(suppressed_reason="unresolved_label"), "unresolved"),
    (_row(suppressed_reason="startup_unresolved_label"), "startup-grace"),
    (_row(suppressed_reason="heartbeat_not_alive", heartbeat_alive=False), "silent"),
    (_row(suppressed_reason="heartbeat_eval_error", heartbeat_alive=False), "silent"),
    (_row(candidate=True, metric_below_threshold=True), "flat-candidate"),
    (_row(), "OK"),
    # Tie-break: source-error wins over unresolved
    (_row(error_details={"source": "x"}, suppressed_reason="unresolved_label"),
     "source-error"),
    # Tie-break: silent wins over flat-candidate when both could apply
    (_row(suppressed_reason="heartbeat_not_alive", heartbeat_alive=False,
          candidate=False, metric_below_threshold=True), "silent"),
])
def test_status_priority(row, expected):
    assert resolve_status(row) == expected
