"""Tests for the class indicator that maps agent metadata to calibration class."""
import pytest
from types import SimpleNamespace

from src.grounding.class_indicator import (
    classify_agent,
    KNOWN_RESIDENT_LABELS,
    CLASS_EMBODIED,
    CLASS_RESIDENT_PERSISTENT,
    CLASS_EPHEMERAL,
    CLASS_DEFAULT,
)


def _meta(label=None, tags=None):
    return SimpleNamespace(label=label, tags=tags or [])


def test_none_meta_returns_default():
    assert classify_agent(None) == CLASS_DEFAULT


def test_known_resident_labels_return_themselves():
    for label in KNOWN_RESIDENT_LABELS:
        assert classify_agent(_meta(label=label)) == label


def test_embodied_tag_takes_precedence_over_persistent():
    """Lumen has both 'embodied' and 'persistent' but should classify as embodied."""
    assert classify_agent(_meta(tags=["embodied", "persistent"])) == CLASS_EMBODIED


def test_resident_persistent_for_autonomous_persistent():
    assert (
        classify_agent(_meta(tags=["autonomous", "persistent"]))
        == CLASS_RESIDENT_PERSISTENT
    )


def test_ephemeral_tag_classifies_ephemeral():
    assert classify_agent(_meta(tags=["ephemeral"])) == CLASS_EPHEMERAL


def test_unknown_tags_fall_through_to_default():
    assert classify_agent(_meta(tags=["random", "tag"])) == CLASS_DEFAULT


def test_no_tags_no_label_returns_default():
    assert classify_agent(_meta()) == CLASS_DEFAULT


def test_label_overrides_tags_for_known_residents():
    """A 'Vigil' label wins even if tags say something else."""
    assert classify_agent(_meta(label="Vigil", tags=["embodied"])) == "Vigil"


def test_unknown_label_falls_through_to_tag_resolution():
    """An unknown label doesn't short-circuit tag resolution."""
    assert (
        classify_agent(_meta(label="random_session_agent", tags=["ephemeral"]))
        == CLASS_EPHEMERAL
    )


def test_meta_without_tags_attribute_is_safe():
    class Bare:
        label = "Lumen"
    assert classify_agent(Bare()) == "Lumen"
