"""
Tests for src/process_cleanup.py - Process management and zombie cleanup.

Tests ProcessManager init and heartbeat writing using tmp_path.
"""

import os
import time
import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.process_cleanup import ProcessManager


# ============================================================================
# ProcessManager - init
# ============================================================================

class TestProcessManagerInit:

    def test_creates_pid_dir(self, tmp_path):
        pid_dir = tmp_path / "processes"
        pm = ProcessManager(pid_dir=pid_dir)
        assert pid_dir.exists()

    def test_current_pid(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        assert pm.current_pid == os.getpid()

    def test_heartbeat_file_path(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        assert f"heartbeat_{os.getpid()}" in str(pm.heartbeat_file)


# ============================================================================
# ProcessManager - write_heartbeat
# ============================================================================

class TestWriteHeartbeat:

    def test_writes_file(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        pm.write_heartbeat()
        assert pm.heartbeat_file.exists()

    def test_writes_timestamp(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        before = time.time()
        pm.write_heartbeat()
        after = time.time()

        with open(pm.heartbeat_file) as f:
            ts = float(f.read())
        assert before <= ts <= after

    def test_overwrites_previous(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        pm.write_heartbeat()
        time.sleep(0.01)
        pm.write_heartbeat()

        with open(pm.heartbeat_file) as f:
            ts = float(f.read())
        # Should be very recent
        assert time.time() - ts < 1.0


# ============================================================================
# ProcessManager - get_active_processes
# ============================================================================

class TestGetActiveProcesses:

    def test_returns_list(self, tmp_path):
        pm = ProcessManager(pid_dir=tmp_path)
        result = pm.get_active_processes()
        assert isinstance(result, list)
