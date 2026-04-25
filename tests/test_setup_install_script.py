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
