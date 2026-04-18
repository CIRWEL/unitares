"""Tests for the entropy grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.entropy import compute_entropy
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_tier3_heuristic_wraps_legacy_s():
    result = compute_entropy(_mk_ctx(), metrics={"S": 0.42})
    assert isinstance(result, GroundedValue)
    assert result.source == "heuristic"
    assert result.value == 0.42


def test_tier3_missing_metric_returns_neutral():
    result = compute_entropy(_mk_ctx(), metrics={})
    assert result.source == "heuristic"
    assert result.value == 0.5


def test_tier3_clamps_out_of_range_metric():
    assert compute_entropy(_mk_ctx(), metrics={"S": 1.3}).value == 1.0
    assert compute_entropy(_mk_ctx(), metrics={"S": -0.05}).value == 0.0


def test_tier1_logprobs_stub_falls_through_to_heuristic():
    ctx = _mk_ctx(arguments={"logprobs": [[-0.1, -0.3, -0.8]]})
    result = compute_entropy(ctx, metrics={"S": 0.2})
    assert result.source == "heuristic"
    assert result.value == 0.2


def test_tier2_samples_stub_falls_through_to_heuristic():
    ctx = _mk_ctx(arguments={"samples": ["a", "b", "c"]})
    result = compute_entropy(ctx, metrics={"S": 0.3})
    assert result.source == "heuristic"
    assert result.value == 0.3
