"""Backfill script: replays task_* outcomes from audit.outcome_events."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def isolated_tracker(tmp_path):
    from src.sequential_calibration import SequentialCalibrationTracker
    state_file = tmp_path / "seq_state.json"
    # Seed with current-epoch state so the migration guard inside backfill passes.
    with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
        mock_cfg.CURRENT_EPOCH = 3
        tracker = SequentialCalibrationTracker(state_file=state_file)
        tracker.save_state()
    return tracker, state_file


class TestBackfillScript:
    def test_dry_run_reports_counts_without_mutating_state(self, isolated_tracker):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker
        original_mtime = state_file.stat().st_mtime

        fake_rows = [
            {"outcome_type": "task_completed", "agent_id": "a1", "is_bad": False, "confidence": 0.8},
            {"outcome_type": "task_failed", "agent_id": "a1", "is_bad": True, "confidence": 0.6},
        ]
        with patch.object(backfill, "fetch_eligible_rows", AsyncMock(return_value=fake_rows)):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
                    mock_cfg.CURRENT_EPOCH = 3
                    summary = asyncio.run(backfill.backfill(days=30, dry_run=True))

        assert summary["candidates"] == 2
        assert summary["replayed"] == 0  # dry-run
        assert summary["skipped_no_confidence"] == 0
        assert state_file.stat().st_mtime == original_mtime

    def test_live_run_calls_save_state_exactly_once(self, isolated_tracker):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker

        fake_rows = [
            {"outcome_type": "task_completed", "agent_id": "a1", "is_bad": False, "confidence": 0.8},
            {"outcome_type": "task_failed", "agent_id": "a1", "is_bad": True, "confidence": 0.6},
        ]
        save_calls = []
        original_save = tracker.save_state
        def counted_save():
            save_calls.append(1)
            original_save()
        tracker.save_state = counted_save

        with patch.object(backfill, "fetch_eligible_rows", AsyncMock(return_value=fake_rows)):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
                    mock_cfg.CURRENT_EPOCH = 3
                    summary = asyncio.run(backfill.backfill(days=30, dry_run=False))

        assert summary["replayed"] == 2
        assert len(save_calls) == 1, f"Expected exactly 1 save_state call, got {len(save_calls)}"

    def test_db_error_mid_run_does_not_save_state(self, isolated_tracker):
        from scripts.dev import backfill_tactical_calibration as backfill
        tracker, state_file = isolated_tracker
        original_mtime = state_file.stat().st_mtime

        with patch.object(backfill, "fetch_eligible_rows",
                          AsyncMock(side_effect=RuntimeError("DB down"))):
            with patch.object(backfill, "sequential_calibration_tracker", tracker):
                with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
                    mock_cfg.CURRENT_EPOCH = 3
                    with pytest.raises(RuntimeError):
                        asyncio.run(backfill.backfill(days=30, dry_run=False))

        assert state_file.stat().st_mtime == original_mtime

    def test_epoch_mismatch_exits_with_instructions(self, tmp_path):
        from scripts.dev import backfill_tactical_calibration as backfill
        from src.sequential_calibration import SequentialCalibrationTracker

        # Seed state file at epoch 2; bypass init migration so the on-disk
        # epoch stays at 2 when backfill checks it.
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({"global": {}, "agents": {}, "epoch": 2}))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 2  # init won't archive
            tracker = SequentialCalibrationTracker(state_file=state_file)

        # Now tracker has epoch-2 on disk; backfill checks under epoch=3 and must refuse.
        with patch.object(backfill, "sequential_calibration_tracker", tracker):
            with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
                mock_cfg.CURRENT_EPOCH = 3
                with pytest.raises(SystemExit):
                    asyncio.run(backfill.backfill(days=30, dry_run=False))
