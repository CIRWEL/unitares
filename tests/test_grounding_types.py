"""Tests for GroundedValue dataclass — the shared return type for grounding modules."""
import pytest
from dataclasses import FrozenInstanceError

from src.grounding.types import GroundedValue, ALLOWED_SOURCES


def test_valid_construction():
    gv = GroundedValue(value=0.42, source="heuristic")
    assert gv.value == 0.42
    assert gv.source == "heuristic"


def test_all_allowed_sources_accepted():
    for source in ALLOWED_SOURCES:
        gv = GroundedValue(value=0.1, source=source)
        assert gv.source == source


def test_unknown_source_rejected():
    with pytest.raises(ValueError, match="unknown grounding source"):
        GroundedValue(value=0.5, source="banana")


def test_value_out_of_range_rejected():
    with pytest.raises(ValueError, match="out of range"):
        GroundedValue(value=1.5, source="heuristic")
    with pytest.raises(ValueError, match="out of range"):
        GroundedValue(value=-0.1, source="heuristic")


def test_frozen():
    gv = GroundedValue(value=0.5, source="heuristic")
    with pytest.raises(FrozenInstanceError):
        gv.value = 0.7  # type: ignore[misc]


def test_as_dict_shape():
    gv = GroundedValue(value=0.3, source="manifold")
    assert gv.as_dict() == {"value": 0.3, "source": "manifold"}
