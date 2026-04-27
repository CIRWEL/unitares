"""Epoch migration: state file from older epoch is archived and reset."""

import json
import pytest
from unittest.mock import patch
from src.sequential_calibration import SequentialCalibrationTracker


class TestEpochMigration:
    def test_state_from_older_epoch_is_archived(self, tmp_path):
        state_file = tmp_path / "seq_state.json"
        # Pre-existing state from an older epoch
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 100, "successes": 99},
            "agents": {},
            "epoch": 2,
        }))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)
        # Archive should exist
        archives = [p for p in tmp_path.iterdir() if "bak.epoch" in p.name]
        assert len(archives) == 1, f"expected one archive, got {archives}"
        # Tracker started fresh
        assert tracker.global_state["eligible_samples"] == 0

    def test_matching_epoch_does_not_archive(self, tmp_path):
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 50, "successes": 49},
            "agents": {},
            "epoch": 3,
        }))
        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg:
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)
        # No archive
        archives = [p for p in tmp_path.iterdir() if "bak.epoch" in p.name]
        assert archives == []
        # State preserved
        assert tracker.global_state["eligible_samples"] == 50

    def test_concurrent_migration_filenotfound_is_swallowed(self, tmp_path):
        """Simulate a TOCTOU race: the file disappears between epoch-check and rename.

        We can't easily induce a real race, so we patch Path.rename to raise
        FileNotFoundError at the moment the migration tries to archive.
        """
        state_file = tmp_path / "seq_state.json"
        state_file.write_text(json.dumps({
            "global": {"eligible_samples": 1, "successes": 1},
            "agents": {},
            "epoch": 2,
        }))

        original_rename = type(state_file).rename
        call_count = {"n": 0}

        def first_call_raises(self_path, target):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise FileNotFoundError("simulated concurrent migration")
            return original_rename(self_path, target)

        with patch("src.sequential_calibration.GovernanceConfig") as mock_cfg, \
             patch.object(type(state_file), "rename", first_call_raises):
            mock_cfg.CURRENT_EPOCH = 3
            tracker = SequentialCalibrationTracker(state_file=state_file)

        # Migration must complete without raising; tracker starts fresh.
        assert tracker.global_state["eligible_samples"] == 0
        assert call_count["n"] >= 1
