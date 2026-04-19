"""Tests for the coherence grounding module."""
import math

import pytest
from unittest.mock import MagicMock

from src.grounding.coherence import compute_coherence
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_manifold_at_healthy_point_is_one():
    """Agent sitting exactly at healthy baseline → coherence 1.0."""
    from config.governance_config import BASIN_HIGH
    metrics = {"E": BASIN_HIGH.E_min, "I": BASIN_HIGH.I_min, "S": 0.0}
    result = compute_coherence(_mk_ctx(), metrics)
    assert result.source == "manifold"
    assert abs(result.value - 1.0) < 1e-9


def test_manifold_far_from_healthy_approaches_zero():
    metrics = {"E": 0.0, "I": 0.0, "S": 1.0}
    result = compute_coherence(_mk_ctx(), metrics)
    assert result.source == "manifold"
    assert result.value < 0.5


def test_manifold_missing_dims_falls_through():
    result = compute_coherence(_mk_ctx(), metrics={"coherence": 0.65})
    assert result.source == "heuristic"
    assert result.value == 0.65


def test_kl_stub_falls_through():
    metrics = {
        "E": 0.5, "I": 0.5, "S": 0.5,
        "q_now": [0.25, 0.25, 0.25, 0.25],
        "q_ref": [0.3, 0.3, 0.2, 0.2],
    }
    result = compute_coherence(_mk_ctx(), metrics)
    assert result.source == "manifold"


def test_heuristic_clamps():
    assert compute_coherence(_mk_ctx(), {"coherence": 1.5}).value == 1.0
    assert compute_coherence(_mk_ctx(), {"coherence": -0.1}).value == 0.0
