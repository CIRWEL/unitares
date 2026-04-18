import importlib
import os
from pathlib import Path

from src import process_management as pm


def test_ensure_server_pid_file_rewrites_missing(tmp_path, monkeypatch):
    pid_file = tmp_path / ".mcp_server.pid"
    monkeypatch.setattr(pm, "SERVER_PID_FILE", pid_file)
    monkeypatch.setattr(pm, "CURRENT_PID", 42424)

    pm.ensure_server_pid_file()

    assert pid_file.read_text().strip() == "42424"


def test_ensure_server_lock_recreates_missing(tmp_path, monkeypatch):
    lock_file = tmp_path / ".mcp_server.lock"
    monkeypatch.setattr(pm, "SERVER_LOCK_FILE", lock_file)
    monkeypatch.setattr(pm, "CURRENT_PID", 51515)

    lock_fd = pm.acquire_server_lock()
    try:
        assert lock_file.exists()
        lock_file.unlink()
        assert not lock_file.exists()

        lock_fd = pm.ensure_server_lock(lock_fd)

        assert lock_file.exists()
        assert "51515" in lock_file.read_text()
    finally:
        pm.release_server_lock(lock_fd)


def test_server_marker_paths_honor_env_overrides(tmp_path, monkeypatch):
    pid_file = tmp_path / "custom.pid"
    lock_file = tmp_path / "custom.lock"
    monkeypatch.setenv("UNITARES_SERVER_PID_FILE", str(pid_file))
    monkeypatch.setenv("UNITARES_SERVER_LOCK_FILE", str(lock_file))

    reloaded = importlib.reload(pm)
    try:
        assert reloaded.SERVER_PID_FILE == pid_file
        assert reloaded.SERVER_LOCK_FILE == lock_file
    finally:
        monkeypatch.delenv("UNITARES_SERVER_PID_FILE", raising=False)
        monkeypatch.delenv("UNITARES_SERVER_LOCK_FILE", raising=False)
        importlib.reload(pm)
