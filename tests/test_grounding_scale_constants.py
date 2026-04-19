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


def test_fleet_defaults_remain_placeholder():
    """Fleet-wide ALL_SCALE_CONSTANTS are placeholders (fallback only).

    Class-conditional constants in DELTA_NORM_MAX_BY_CLASS carry the
    measured values; fleet defaults exist only as a fallback for
    unclassified agents.
    """
    placeholders = [sc for sc in ALL_SCALE_CONSTANTS if sc.provenance == "placeholder"]
    assert len(placeholders) == len(ALL_SCALE_CONSTANTS)


def test_class_conditional_delta_norm_max_is_measured():
    """Phase 2 measurement populated DELTA_NORM_MAX_BY_CLASS with measured values."""
    from config.governance_config import DELTA_NORM_MAX_BY_CLASS
    assert len(DELTA_NORM_MAX_BY_CLASS) >= 5  # Lumen, default, Sentinel, Vigil, Watcher
    for cls_name, sc in DELTA_NORM_MAX_BY_CLASS.items():
        assert sc.provenance == "measured", (
            f"class-conditional {cls_name} should be measured, got {sc.provenance}"
        )
        assert sc.corpus_size > 0
        assert sc.percentile == 95


def test_class_conditional_lookup_falls_back_for_unknown_classes():
    """Unknown class falls back to fleet-wide DELTA_NORM_MAX_DEFAULT."""
    from config.governance_config import (
        get_delta_norm_max, DELTA_NORM_MAX_DEFAULT,
    )
    assert get_delta_norm_max("nonexistent_class") is DELTA_NORM_MAX_DEFAULT
    assert get_delta_norm_max("Lumen").provenance == "measured"


def test_healthy_operating_point_class_conditional():
    """Per-class healthy points exist for measured classes; default for others."""
    from config.governance_config import (
        get_healthy_operating_point, HEALTHY_OPERATING_POINT_DEFAULT,
    )
    lumen_hop = get_healthy_operating_point("Lumen")
    assert lumen_hop != HEALTHY_OPERATING_POINT_DEFAULT
    assert all(0.0 <= v <= 1.0 for v in lumen_hop)

    unknown_hop = get_healthy_operating_point("nonexistent")
    assert unknown_hop == HEALTHY_OPERATING_POINT_DEFAULT


def test_delta_norm_max_default_covers_full_state_space_diagonal():
    """Fleet-wide default must allow full diagonal so unclassified agents can hit C=0."""
    assert DELTA_NORM_MAX.value >= math.sqrt(3) - 0.01
