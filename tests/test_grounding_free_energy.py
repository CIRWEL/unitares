"""Tests for the free-energy (E) grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.free_energy import compute_free_energy
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None, response_text=""):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    ctx.response_text = response_text
    return ctx


def test_resource_form_uses_explicit_tokens_and_seconds():
    ctx = _mk_ctx(arguments={"response_tokens": 400, "response_seconds": 4.0})
    result = compute_free_energy(ctx, metrics={})
    assert result.source == "resource"
    assert abs(result.value - 0.5) < 0.01


def test_resource_form_caps_at_one():
    ctx = _mk_ctx(arguments={"response_tokens": 10000, "response_seconds": 1.0})
    result = compute_free_energy(ctx, metrics={})
    assert result.value == 1.0


def test_resource_form_handles_zero_seconds():
    ctx = _mk_ctx(arguments={"response_tokens": 100, "response_seconds": 0.0})
    result = compute_free_energy(ctx, metrics={"E": 0.6})
    assert result.source == "heuristic"
    assert result.value == 0.6


def test_fep_stub_falls_through_to_resource():
    ctx = _mk_ctx(
        arguments={
            "response_tokens": 200,
            "response_seconds": 2.0,
            "expected_outcome": {"value": 0.7},
            "observed_outcome": {"value": 0.6},
        }
    )
    result = compute_free_energy(ctx, metrics={})
    assert result.source == "resource"


def test_heuristic_when_nothing_present():
    ctx = _mk_ctx()
    result = compute_free_energy(ctx, metrics={"E": 0.42})
    assert result.source == "heuristic"
    assert result.value == 0.42


def test_heuristic_clamps_out_of_range():
    ctx = _mk_ctx()
    assert compute_free_energy(ctx, metrics={"E": 1.5}).value == 1.0
    assert compute_free_energy(ctx, metrics={"E": -0.3}).value == 0.0
