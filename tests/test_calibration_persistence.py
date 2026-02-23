"""
Tests for calibration save/load without db.close().

Feb 2026 fix: calibration._save() and _load() were calling db.close() on the
shared singleton pool, destroying connections for all concurrent users.
The fix removed db.close() and db.init() from both functions.

These tests verify:
1. save_state() does NOT call db.close()
2. load_state() does NOT call db.close()
3. save_state() does NOT call db.init()
4. load_state() does NOT call db.init()
"""

import asyncio
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_db():
    """Mock the database singleton to track close()/init() calls."""
    db = AsyncMock()
    db.init = AsyncMock()
    db.close = AsyncMock()
    db.update_calibration = AsyncMock(return_value=True)
    db.get_calibration = AsyncMock(return_value={
        "bins": {},
        "complexity_bins": {},
        "tactical_bins": {},
    })
    return db


@pytest.fixture
def calibration_checker(tmp_path, mock_db):
    """Create a CalibrationChecker configured for postgres backend."""
    with patch.dict("os.environ", {
        "UNITARES_CALIBRATION_BACKEND": "postgres",
        "DB_BACKEND": "postgres",
    }):
        with patch("src.db.get_db", return_value=mock_db):
            from src.calibration import CalibrationChecker
            checker = CalibrationChecker(state_file=tmp_path / "cal.json")
            checker._backend = "postgres"
            yield checker, mock_db


class TestCalibrationSaveNoClose:
    """Verify save_state() does not call db.close() or db.init()."""

    def test_save_does_not_close_pool(self, calibration_checker):
        """save_state() must NOT call db.close() — it destroys the shared pool."""
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.save_state()
        mock_db.close.assert_not_called()

    def test_save_does_not_init_pool(self, calibration_checker):
        """save_state() must NOT call db.init() — pool is initialized at startup."""
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.save_state()
        mock_db.init.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_calls_update_calibration(self, calibration_checker):
        """save_state() should still call db.update_calibration().

        _run_async uses asyncio.get_running_loop() + create_task, so we must
        be inside an async context for the DB call to fire.
        """
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.save_state()
            # Allow the created task to execute
            await asyncio.sleep(0)
        mock_db.update_calibration.assert_called_once()


class TestCalibrationLoadNoClose:
    """Verify load_state() does not call db.close() or db.init()."""

    def test_load_does_not_close_pool(self, calibration_checker):
        """load_state() must NOT call db.close()."""
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.load_state()
        mock_db.close.assert_not_called()

    def test_load_does_not_init_pool(self, calibration_checker):
        """load_state() must NOT call db.init()."""
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.load_state()
        mock_db.init.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_calls_get_calibration(self, calibration_checker):
        """load_state() should still call db.get_calibration().

        _run_async uses asyncio.get_running_loop() + create_task, so we must
        be inside an async context for the DB call to fire.
        """
        checker, mock_db = calibration_checker
        with patch("src.db.get_db", return_value=mock_db):
            checker.load_state()
            # Allow the created task to execute
            await asyncio.sleep(0)
        mock_db.get_calibration.assert_called()
