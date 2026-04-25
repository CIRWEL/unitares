"""Smoke tests for scripts/install/setup.py.

Mirrors tests/test_unitares_doctor_script.py: imports the script as a module,
patches its internal subprocess wrapper, and uses tmp_path for filesystem
mutations. Never touches real ~/.unitares/, real client configs, or live
postgres.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "install" / "setup.py"


@pytest.fixture(scope="module")
def setup_mod():
    spec = importlib.util.spec_from_file_location("unitares_setup", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unitares_setup"] = mod  # Python 3.14 dataclass needs this
    spec.loader.exec_module(mod)
    return mod


def test_module_loads_and_exposes_main(setup_mod):
    assert callable(setup_mod.main)
    assert setup_mod.SCHEMA_VERSION == 1


def test_bootstrap_check_passes_when_mcp_importable(setup_mod, monkeypatch):
    # mcp SDK is installed in the project's full requirements; this is the
    # happy path — bootstrap_check should return without raising.
    setup_mod.bootstrap_check()  # no exception


def test_bootstrap_check_exits_when_mcp_missing(setup_mod, monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp":
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        setup_mod.bootstrap_check()
    assert exc.value.code == 2
    err = capsys.readouterr().out
    assert "pip install -r requirements-full.txt" in err


def test_run_doctor_parses_pass_payload(setup_mod, monkeypatch):
    fake_stdout = '{"mode": "local", "results": [{"name": "x", "mode": "local", "status": "pass", "message": "ok", "detail": ""}], "exit_code": 0}'

    class FakeProc:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    result = setup_mod.run_doctor()
    assert result["mode"] == "local"
    assert result["results"][0]["status"] == "pass"
    assert result["exit_code"] == 0


def test_run_doctor_handles_nonzero_exit_with_valid_json(setup_mod, monkeypatch):
    """Doctor exits 1 when any local check fails; setup must NOT treat that
    as an error — the JSON payload is still complete and is the input to
    remediation."""
    fake_stdout = '{"mode": "local", "results": [{"name": "postgres_running", "mode": "local", "status": "fail", "message": "down", "detail": ""}], "exit_code": 1}'

    class FakeProc:
        returncode = 1
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    result = setup_mod.run_doctor()
    assert result["results"][0]["status"] == "fail"
    assert result["exit_code"] == 1


def test_run_doctor_raises_on_invalid_json(setup_mod, monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(setup_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    with pytest.raises(setup_mod.DoctorError):
        setup_mod.run_doctor()
