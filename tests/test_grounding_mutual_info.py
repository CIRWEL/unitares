"""Tests for the mutual-information grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.mutual_info import compute_mutual_info
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_tier3_heuristic_wraps_legacy_i():
    result = compute_mutual_info(_mk_ctx(), metrics={"I": 0.73})
    assert result.source == "heuristic"
    assert result.value == 0.73


def test_tier3_missing_metric_returns_neutral():
    result = compute_mutual_info(_mk_ctx(), metrics={})
    assert result.source == "heuristic"
    assert result.value == 0.5


def test_tier3_clamps_out_of_range():
    assert compute_mutual_info(_mk_ctx(), {"I": 1.2}).value == 1.0
    assert compute_mutual_info(_mk_ctx(), {"I": -0.1}).value == 0.0


def test_tier1_stub_falls_through():
    ctx = _mk_ctx(arguments={"logprobs": [[-0.1]], "context_logprobs": [[-0.2]]})
    result = compute_mutual_info(ctx, metrics={"I": 0.4})
    assert result.source == "heuristic"
    assert result.value == 0.4


def test_tier2_stub_falls_through():
    ctx = _mk_ctx(arguments={"samples": ["a", "b"]})
    result = compute_mutual_info(ctx, metrics={"I": 0.5})
    assert result.source == "heuristic"
    assert result.value == 0.5
