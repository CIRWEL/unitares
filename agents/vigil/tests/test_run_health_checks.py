"""Tests for Vigil's registry-driven health-check runner.

These test the helper that Vigil's run_cycle will delegate to. The helper
must: execute each registered check, aggregate summaries in order, tolerate
check exceptions without killing the cycle, and produce state keyed by
service_key so Vigil's existing state-diff logic keeps working unchanged.
"""

from __future__ import annotations

import asyncio

import pytest


def _reset_registry():
    from agents.vigil.checks import registry
    registry._CHECKS.clear()
    registry._LOADED = False


@pytest.fixture(autouse=True)
def clean_registry():
    _reset_registry()
    yield
    _reset_registry()


def _make_check(name, service_key, result_factory):
    class _C:
        def __init__(self):
            self.name = name
            self.service_key = service_key
            self.run_count = 0
        async def run(self):
            self.run_count += 1
            return result_factory()
    return _C()


def test_runner_calls_each_registered_check_once():
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult
    from agents.vigil.checks.runner import run_health_checks

    a = _make_check("a", "svc_a", lambda: CheckResult(ok=True, summary="a ok"))
    b = _make_check("b", "svc_b", lambda: CheckResult(ok=True, summary="b ok"))
    registry.register(a)
    registry.register(b)

    results = asyncio.run(run_health_checks(prev_state={}))
    assert a.run_count == 1
    assert b.run_count == 1
    assert [c.name for c, _ in results] == ["a", "b"]


def test_runner_preserves_registration_order():
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult
    from agents.vigil.checks.runner import run_health_checks

    for i in range(5):
        registry.register(
            _make_check(f"c{i}", f"s{i}", lambda: CheckResult(ok=True, summary=""))
        )

    results = asyncio.run(run_health_checks(prev_state={}))
    assert [c.name for c, _ in results] == ["c0", "c1", "c2", "c3", "c4"]


def test_runner_captures_exception_as_failure_without_raising():
    """A check that throws must not kill the cycle — the runner must convert
    it to an unhealthy CheckResult so Vigil keeps checking in."""
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult
    from agents.vigil.checks.runner import run_health_checks

    def boom():
        raise RuntimeError("plugin crashed")

    ok = _make_check("ok", "ok_svc", lambda: CheckResult(ok=True, summary="fine"))
    bad = _make_check("bad", "bad_svc", boom)
    registry.register(ok)
    registry.register(bad)

    results = asyncio.run(run_health_checks(prev_state={}))
    assert len(results) == 2
    bad_result = next(r for c, r in results if c.name == "bad")
    assert bad_result.ok is False
    assert "plugin crashed" in bad_result.summary.lower() or "crashed" in bad_result.summary
    # Other check still ran to completion
    assert next(r for c, r in results if c.name == "ok").ok is True


def test_runner_passes_prev_state_to_checks_that_accept_it():
    """Checks with run(prev_state=...) get the previous cycle's state so they
    can do stateful things like last-successful-URL reordering."""
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult
    from agents.vigil.checks.runner import run_health_checks

    seen = {}

    class StatefulCheck:
        name = "stateful"
        service_key = "stateful"
        async def run(self, prev_state=None):
            seen["prev_state"] = prev_state
            return CheckResult(ok=True, summary="ok")

    registry.register(StatefulCheck())
    asyncio.run(run_health_checks(prev_state={"foo": "bar"}))
    assert seen["prev_state"] == {"foo": "bar"}


def test_runner_still_calls_checks_without_prev_state_kwarg():
    """Legacy-shaped checks (run() with no args) must continue to work."""
    from agents.vigil.checks import registry
    from agents.vigil.checks.base import CheckResult
    from agents.vigil.checks.runner import run_health_checks

    class NoArgsCheck:
        name = "noargs"
        service_key = "noargs"
        async def run(self):
            return CheckResult(ok=True, summary="fine")

    registry.register(NoArgsCheck())
    results = asyncio.run(run_health_checks(prev_state={"anything": 1}))
    assert results[0][1].ok is True
