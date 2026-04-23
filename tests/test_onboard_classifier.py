"""Unit tests for S8a Phase-1 default-stamp rule.

Covers `src/grounding/onboard_classifier.py:default_tags_for_onboard`
and the handler-side wiring `_stamp_default_tags_on_onboard`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.grounding.onboard_classifier import (
    EPHEMERAL_DEFAULT_TAGS,
    RESIDENT_DEFAULT_TAGS,
    default_tags_for_onboard,
)


class TestDefaultTagsForOnboard:
    def test_resident_name_returns_resident_tags(self):
        for name in ("Lumen", "Vigil", "Sentinel", "Watcher", "Steward", "Chronicler"):
            assert default_tags_for_onboard(name, existing_tags=None) == RESIDENT_DEFAULT_TAGS

    def test_unknown_name_returns_ephemeral(self):
        assert default_tags_for_onboard("some-agent", existing_tags=None) == EPHEMERAL_DEFAULT_TAGS

    def test_none_name_returns_ephemeral(self):
        assert default_tags_for_onboard(None, existing_tags=None) == EPHEMERAL_DEFAULT_TAGS

    def test_empty_name_returns_ephemeral(self):
        assert default_tags_for_onboard("", existing_tags=None) == EPHEMERAL_DEFAULT_TAGS

    def test_resident_name_with_existing_tags_returns_none(self):
        assert default_tags_for_onboard("Lumen", existing_tags=["custom"]) is None

    def test_unknown_name_with_existing_tags_returns_none(self):
        assert default_tags_for_onboard("some-agent", existing_tags=["persistent"]) is None

    def test_empty_list_is_treated_as_no_tags(self):
        assert default_tags_for_onboard("Lumen", existing_tags=[]) == RESIDENT_DEFAULT_TAGS
        assert default_tags_for_onboard("other", existing_tags=[]) == EPHEMERAL_DEFAULT_TAGS

    def test_return_value_is_a_new_list_not_shared_reference(self):
        a = default_tags_for_onboard("Lumen", existing_tags=None)
        b = default_tags_for_onboard("Lumen", existing_tags=None)
        a.append("mutated")
        assert b == RESIDENT_DEFAULT_TAGS

    def test_resident_label_matching_is_case_sensitive(self):
        assert default_tags_for_onboard("lumen", existing_tags=None) == EPHEMERAL_DEFAULT_TAGS
        assert default_tags_for_onboard("LUMEN", existing_tags=None) == EPHEMERAL_DEFAULT_TAGS

    def test_structured_agent_id_does_not_match_resident(self):
        assert default_tags_for_onboard("Lumen_abc123", existing_tags=None) == EPHEMERAL_DEFAULT_TAGS


def _make_meta(tags=None):
    class _Meta:
        pass
    m = _Meta()
    m.tags = tags
    return m


async def _run_stamp(name, existing_tags, *, missing_meta=False):
    meta = None if missing_meta else _make_meta(tags=existing_tags)
    agent_uuid = "uuid-1234"
    fake_server = MagicMock()
    fake_server.agent_metadata = {} if missing_meta else {agent_uuid: meta}
    fake_update = AsyncMock()

    with patch(
        "src.mcp_handlers.identity.handlers.mcp_server", fake_server
    ), patch("src.agent_storage.update_agent", fake_update):
        from src.mcp_handlers.identity.handlers import _stamp_default_tags_on_onboard
        await _stamp_default_tags_on_onboard(agent_uuid, name)

    return meta, fake_update


@pytest.mark.asyncio
async def test_stamp_unknown_name_gets_ephemeral_and_persists():
    meta, fake_update = await _run_stamp("some-agent", existing_tags=None)
    assert meta.tags == ["ephemeral"]
    fake_update.assert_awaited_once_with(agent_id="uuid-1234", tags=["ephemeral"])


@pytest.mark.asyncio
async def test_stamp_resident_name_gets_persistent_autonomous():
    meta, fake_update = await _run_stamp("Sentinel", existing_tags=None)
    assert meta.tags == ["persistent", "autonomous"]
    fake_update.assert_awaited_once_with(
        agent_id="uuid-1234", tags=["persistent", "autonomous"]
    )


@pytest.mark.asyncio
async def test_stamp_preexisting_tags_are_not_overwritten():
    meta, fake_update = await _run_stamp("Sentinel", existing_tags=["custom"])
    assert meta.tags == ["custom"]
    fake_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_stamp_missing_metadata_object_still_writes_tags_to_db():
    """Identity with no in-memory metadata entry yet — DB write is still
    source of truth; next load_metadata_async picks it up."""
    _, fake_update = await _run_stamp("some-agent", existing_tags=None, missing_meta=True)
    fake_update.assert_awaited_once_with(agent_id="uuid-1234", tags=["ephemeral"])
