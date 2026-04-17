"""Tests for Vigil's check registry and plugin loader."""

from __future__ import annotations

import sys
import textwrap

import pytest


def _reset_registry():
    """Clear any state so each test starts from an empty registry."""
    from agents.vigil.checks import registry
    registry._CHECKS.clear()
    registry._LOADED = False


@pytest.fixture(autouse=True)
def clean_registry():
    _reset_registry()
    yield
    _reset_registry()


def test_check_result_defaults():
    from agents.vigil.checks.base import CheckResult

    r = CheckResult(ok=True, summary="Governance: healthy")
    assert r.ok is True
    assert r.summary == "Governance: healthy"
    assert r.detail is None
    assert r.severity == "warning"
    assert r.fingerprint_key == ""


def test_register_adds_check_to_registry():
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult

    class DummyCheck:
        name = "dummy"
        service_key = "dummy"

        async def run(self) -> CheckResult:
            return CheckResult(ok=True, summary="dummy ok")

    check = DummyCheck()
    registry.register(check)
    assert check in registry.all_checks()
    assert len(registry.all_checks()) == 1


def test_all_checks_returns_copy_not_internal_list():
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult

    class DummyCheck:
        name = "dummy"
        service_key = "dummy"

        async def run(self) -> CheckResult:
            return CheckResult(ok=True, summary="")

    registry.register(DummyCheck())
    snapshot = registry.all_checks()
    snapshot.clear()  # mutating the returned list must not affect the registry
    assert len(registry.all_checks()) == 1


def test_load_plugins_imports_modules_listed_in_env_var(monkeypatch, tmp_path):
    """VIGIL_CHECK_PLUGINS is a colon-separated list of importable modules.
    Each module is expected to call register() on import."""
    from agents.vigil.checks import registry

    plugin_dir = tmp_path / "pluginpkg"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "my_plugin.py").write_text(textwrap.dedent("""
        from agents.vigil.checks import registry
        from agents.vigil.checks.base import CheckResult

        class FromPlugin:
            name = "from_plugin"
            service_key = "from_plugin"
            async def run(self):
                return CheckResult(ok=True, summary="plugin ran")

        registry.register(FromPlugin())
    """))

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("VIGIL_CHECK_PLUGINS", "pluginpkg.my_plugin")

    try:
        registry.load_plugins()
        names = [c.name for c in registry.all_checks()]
        assert "from_plugin" in names
    finally:
        sys.modules.pop("pluginpkg.my_plugin", None)
        sys.modules.pop("pluginpkg", None)


def test_load_plugins_is_idempotent(monkeypatch):
    """Calling load_plugins twice must not double-register built-ins."""
    from agents.vigil.checks import registry

    monkeypatch.setenv("VIGIL_CHECK_PLUGINS", "")
    registry.load_plugins()
    first_count = len(registry.all_checks())
    registry.load_plugins()
    assert len(registry.all_checks()) == first_count


def test_load_plugins_tolerates_empty_env_var(monkeypatch):
    from agents.vigil.checks import registry

    monkeypatch.delenv("VIGIL_CHECK_PLUGINS", raising=False)
    registry.load_plugins()  # must not raise


def test_load_plugins_raises_on_missing_plugin_module(monkeypatch):
    """A typo in VIGIL_CHECK_PLUGINS should fail loudly, not silently."""
    from agents.vigil.checks import registry

    monkeypatch.setenv("VIGIL_CHECK_PLUGINS", "definitely_not_a_real_module_xyz")
    with pytest.raises(ImportError):
        registry.load_plugins()
