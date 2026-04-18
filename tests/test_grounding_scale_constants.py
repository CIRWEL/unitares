"""Tests for grounding scale constants — provenance invariants.

Spec §3.4 requires every scale constant to carry measurement metadata.
These tests enforce that requirement at import time.
"""
import math

import pytest

from config.governance_config import (
    ScaleConstant,
    S_SCALE,
    I_SCALE,
    E_SCALE,
    DELTA_NORM_MAX,
    ALL_SCALE_CONSTANTS,
)


def test_scale_constant_has_required_fields():
    sc = S_SCALE
    assert sc.value > 0
    assert sc.measured_on
    assert sc.corpus_size >= 0
    assert sc.percentile in {50, 75, 90, 95, 99, None}
    assert sc.provenance in {"measured", "placeholder", "derived"}


def test_all_constants_registered_in_manifest():
    assert S_SCALE in ALL_SCALE_CONSTANTS
    assert I_SCALE in ALL_SCALE_CONSTANTS
    assert E_SCALE in ALL_SCALE_CONSTANTS
    assert DELTA_NORM_MAX in ALL_SCALE_CONSTANTS


def test_scale_constants_are_finite_floats():
    for sc in ALL_SCALE_CONSTANTS:
        assert isinstance(sc.value, float)
        assert math.isfinite(sc.value)
        assert sc.value > 0


def test_placeholder_provenance_flagged_loudly():
    """Phase 1 ships all placeholders — this test flips when Phase 2 measures land."""
    placeholders = [sc for sc in ALL_SCALE_CONSTANTS if sc.provenance == "placeholder"]
    assert len(placeholders) == len(ALL_SCALE_CONSTANTS)


def test_delta_norm_max_covers_full_state_space_diagonal():
    assert DELTA_NORM_MAX.value >= math.sqrt(3) - 0.01
