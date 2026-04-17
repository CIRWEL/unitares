"""Tests for tag-driven agent archival protection and check-in cadence.

Exercise the generic paths introduced by the Lumen-decoupling A3 changes:
  - ``is_agent_protected`` honours ``persistent`` / ``protected`` tags.
  - ``_get_expected_interval`` resolves from ``cadence.*`` tags first.

Each function also keeps a back-compat fallback (``label == "Lumen"`` and the
hardcoded label → interval map). The fallback is exercised explicitly below
so a later removal pass can see what's being relied on.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agent_lifecycle import is_agent_protected
from src.background_tasks import (
    CADENCE_FROM_TAG,
    _get_expected_interval,
    cadence_from_tags,
)


def _meta(label=None, tags=None, trust_tier=None):
    return SimpleNamespace(
        label=label,
        display_name=label,
        tags=tags or [],
        trust_tier=trust_tier,
    )


# ---------------------------------------------------------------------------
# is_agent_protected — tag-driven
# ---------------------------------------------------------------------------

def test_persistent_tag_protects_agent_without_name_match():
    meta = _meta(label="SomeOtherAgent", tags=["persistent"])
    assert is_agent_protected("some-uuid", meta) is True


def test_protected_tag_protects_agent_without_name_match():
    meta = _meta(label="SomeOtherAgent", tags=["protected"])
    assert is_agent_protected("some-uuid", meta) is True


def test_untagged_ephemeral_agent_is_not_protected():
    meta = _meta(label="claude_cirwel_20260412", tags=[])
    assert is_agent_protected("some-uuid", meta) is False


def test_pioneer_tag_still_protects():
    """Preserve the pre-existing ``pioneer`` tag behaviour."""
    meta = _meta(label="Pioneer", tags=["pioneer"])
    assert is_agent_protected("some-uuid", meta) is True


def test_verified_trust_tier_still_protects():
    """Trust-tier gating is independent of tag-based protection."""
    meta = _meta(label="TrustedBot", tags=[], trust_tier="verified")
    assert is_agent_protected("some-uuid", meta) is True


def test_lumen_label_backcompat_still_protects():
    """Back-compat: Lumen is protected by label until she's tagged ``persistent``.

    When Lumen carries a ``persistent`` tag, the label path is dead code and
    can be deleted. Until then, this guard keeps her safe from archival.
    """
    meta = _meta(label="Lumen", tags=[])
    assert is_agent_protected("lumen-uuid", meta) is True


# ---------------------------------------------------------------------------
# cadence_from_tags — pure helper
# ---------------------------------------------------------------------------

def test_cadence_from_tags_returns_interval_for_known_tag():
    assert cadence_from_tags(["cadence.5min"]) == 300
    assert cadence_from_tags(["cadence.30min"]) == 1800
    assert cadence_from_tags(["cadence.1hr"]) == 3600


def test_cadence_from_tags_picks_first_match():
    # Multiple cadence tags is a user error, but first-wins is a stable rule.
    assert cadence_from_tags(["cadence.5min", "cadence.30min"]) == 300


def test_cadence_from_tags_ignores_non_cadence_tags():
    assert cadence_from_tags(["persistent", "embodied", "autonomous"]) is None


def test_cadence_from_tags_handles_none_and_empty():
    assert cadence_from_tags(None) is None
    assert cadence_from_tags([]) is None


def test_cadence_from_tag_constant_keys_are_well_formed():
    """Every declared cadence key must be ``cadence.<suffix>`` with a positive int value."""
    for tag, seconds in CADENCE_FROM_TAG.items():
        assert tag.startswith("cadence."), tag
        assert isinstance(seconds, int) and seconds > 0, (tag, seconds)


# ---------------------------------------------------------------------------
# _get_expected_interval — tag > label fallback > embodied/autonomous default
# ---------------------------------------------------------------------------

def test_expected_interval_prefers_cadence_tag_over_label():
    """Tag-driven cadence wins even when the label matches the legacy map."""
    meta = _meta(label="Lumen", tags=["cadence.10min"])
    assert _get_expected_interval(meta) == 600


def test_expected_interval_falls_back_to_label_map_when_untagged():
    """Back-compat: Lumen label still resolves to 300s until tagged."""
    meta = _meta(label="Lumen", tags=[])
    assert _get_expected_interval(meta) == 300


def test_expected_interval_falls_back_to_embodied_default():
    meta = _meta(label="SomeEmbodied", tags=["embodied"])
    assert _get_expected_interval(meta) == 300


def test_expected_interval_falls_back_to_autonomous_default():
    meta = _meta(label="SomeAutonomous", tags=["autonomous"])
    assert _get_expected_interval(meta) == 300


def test_expected_interval_returns_none_for_ephemeral_untagged_agent():
    meta = _meta(label="claude_cirwel_20260412", tags=[])
    assert _get_expected_interval(meta) is None


def test_expected_interval_vigil_cadence_30min_tag_matches_legacy_default():
    """Tag-based resolution for Vigil equals the old hardcoded value.

    Guards against accidental drift in cadence semantics during the migration:
    whatever Vigil's silence threshold was before, she keeps after tagging.
    """
    tagged = _meta(label="Vigil", tags=["cadence.30min"])
    untagged = _meta(label="Vigil", tags=[])
    assert _get_expected_interval(tagged) == _get_expected_interval(untagged) == 1800
