"""Tests for demotion + probe behavior in _format_findings_block.

Behavior matrix:

  ci_lower=None (unmeasured) → no demotion, original severity surfaces
  ci_lower≥0.3                → no demotion
  ci_lower<0.3 AND probe       → exempt (surface at original severity)
  ci_lower<0.3 AND no probe    → demote one severity notch

Demotion ladder: critical → high → medium → low. Low never demotes
further (it's already file-only)."""

from unittest.mock import patch

from agents.watcher.calibration import BucketStats
from agents.watcher.findings import _apply_floor_to_finding, _format_findings_block
from agents.watcher.floor_state import FloorState


def _f(*, pattern, severity, fingerprint, file="/repo/src/x.py"):
    return {
        "pattern": pattern,
        "file": file,
        "line": 1,
        "hint": "h",
        "severity": severity,
        "status": "open",
        "detected_at": "2026-04-27T00:00:00Z",
        "fingerprint": fingerprint,
        "violation_class": "BEH",
    }


def _bucket(*, ci, n=15.0):
    return BucketStats(
        pattern="X",
        file_class="app",
        weighted_confirmed=n,
        weighted_dismissed=0.0,
        weighted_n=n,
        ci_lower=ci,
        latest_observation="2026-04-26T00:00:00Z",
    )


class TestApplyFloorToFinding:
    TODAY = "2026-04-27"

    def test_unmeasured_bucket_no_demotion(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=None, n=5.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"
        assert out.get("calibration_demoted_from") is None

    def test_high_ci_no_demotion(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.85)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"

    def test_low_ci_no_probe_demotes(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="zzzz9999")
        with patch("agents.watcher.findings.should_probe", return_value=False):
            out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "medium"
        assert out["calibration_demoted_from"] == "high"

    def test_low_ci_probe_exempts(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        with patch("agents.watcher.findings.should_probe", return_value=True):
            out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"
        assert out.get("calibration_probe") is True

    def test_demotion_ladder(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        with patch("agents.watcher.findings.should_probe", return_value=False):
            for src, expected in [
                ("critical", "high"),
                ("high", "medium"),
                ("medium", "low"),
                ("low", "low"),
            ]:
                finding = _f(pattern="P1", severity=src, fingerprint="abcd1234")
                out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
                assert out["severity"] == expected, f"{src} should demote to {expected}"

    def test_pattern_not_in_floor_no_demotion(self):
        floor = FloorState(updated_at="t", buckets={})
        finding = _f(pattern="UNKNOWN", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"


class TestFormatBlockWithFloor:
    def test_demoted_high_does_not_appear_in_block_when_dropped_to_low(self):
        """High → medium still surfaces (medium shows under cap). Verify
        the single-step demotion still keeps the finding visible."""
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        rows = [_f(pattern="P1", severity="high", fingerprint="abcd1234")]
        with patch("agents.watcher.findings.load_floor", return_value=floor), \
             patch("agents.watcher.findings.should_probe", return_value=False):
            block, shown = _format_findings_block(rows, header="hdr")
        assert block is not None
        assert "[MEDIUM]" in block, "demoted-to-medium should still surface"
        assert len(shown) == 1


class TestDemotionLogDeduplication:
    """The 'calibration: demoted ...' log line fires inside
    _format_findings_block which renders on every UserPromptSubmit. Without
    de-dup, a stable demoted finding would emit one line per render,
    drowning the calibration signal. Council-flagged log spam (dialectic)."""

    def test_log_emitted_on_first_render_only(self):
        from agents.watcher import findings as findings_mod

        # Reset the dedup set so test ordering doesn't matter
        findings_mod._DEMOTION_LOG_SEEN.clear()

        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        rows = [_f(pattern="P1", severity="high", fingerprint="abcd1234")]

        log_calls = []

        def capture_log(msg, level="info"):
            if "calibration: demoted" in msg:
                log_calls.append(msg)

        with patch("agents.watcher.findings.load_floor", return_value=floor), \
             patch("agents.watcher.findings.should_probe", return_value=False), \
             patch("agents.watcher.findings.log", side_effect=capture_log):
            # First render: log fires
            _format_findings_block(rows, header="hdr")
            # Second and third renders within the same day: log does NOT fire
            _format_findings_block(rows, header="hdr")
            _format_findings_block(rows, header="hdr")

        assert len(log_calls) == 1, (
            f"expected exactly 1 demote log line on first render, got {len(log_calls)}"
        )

    def test_distinct_fingerprints_each_log_once(self):
        from agents.watcher import findings as findings_mod
        findings_mod._DEMOTION_LOG_SEEN.clear()

        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        rows = [
            _f(pattern="P1", severity="high", fingerprint="aaaa0001"),
            _f(pattern="P1", severity="high", fingerprint="aaaa0002"),
            _f(pattern="P1", severity="high", fingerprint="aaaa0003"),
        ]

        log_calls = []

        def capture_log(msg, level="info"):
            if "calibration: demoted" in msg:
                log_calls.append(msg)

        with patch("agents.watcher.findings.load_floor", return_value=floor), \
             patch("agents.watcher.findings.should_probe", return_value=False), \
             patch("agents.watcher.findings.log", side_effect=capture_log):
            _format_findings_block(rows, header="hdr")
            _format_findings_block(rows, header="hdr")  # second render: no new logs

        assert len(log_calls) == 3, (
            f"each distinct fingerprint should log once on first sighting; "
            f"got {len(log_calls)} for 3 fingerprints"
        )
