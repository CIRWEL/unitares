"""Tests for GovernanceAgent base class."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unitares_sdk.agent import CycleResult, GovernanceAgent
from unitares_sdk.client import GovernanceClient
from unitares_sdk.errors import IdentityDriftError, VerdictError
from unitares_sdk.models import CheckinResult, IdentityResult, OnboardResult


# --- CycleResult ---


class TestCycleResult:
    def test_simple_factory(self):
        r = CycleResult.simple("did some work")
        assert r.summary == "did some work"
        assert r.complexity == 0.3
        assert r.confidence == 0.7
        assert r.response_mode == "compact"
        assert r.notes is None

    def test_full_construction(self):
        r = CycleResult(
            summary="cleaned 3 entries",
            complexity=0.6,
            confidence=0.85,
            response_mode="full",
            notes=[("entry 1 cleaned", ["vigil", "cleanup"])],
        )
        assert r.complexity == 0.6
        assert len(r.notes) == 1
        assert r.notes[0][1] == ["vigil", "cleanup"]


# --- Test Agent Implementation ---


class SimpleAgent(GovernanceAgent):
    """Minimal test agent."""

    def __init__(self, cycle_result=None, **kwargs):
        super().__init__("TestAgent", **kwargs)
        self._cycle_result = cycle_result
        self.cycle_count = 0

    async def run_cycle(self, client: GovernanceClient) -> CycleResult | None:
        self.cycle_count += 1
        return self._cycle_result


# --- Helpers ---


def _make_token(aid: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aid": aid}).encode()).decode().rstrip("=")
    return f"v1.{payload}.sig"


def _mock_client_connected():
    """Create a mocked GovernanceClient that behaves as if connected."""
    client = AsyncMock(spec=GovernanceClient)
    client.client_session_id = "sid-test"
    client.continuity_token = _make_token("uuid-test")
    client.agent_uuid = "uuid-test"

    client.identity = AsyncMock(return_value=IdentityResult(
        client_session_id="sid-test",
        uuid="uuid-test",
        continuity_token=_make_token("uuid-test"),
    ))
    client.onboard = AsyncMock(return_value=OnboardResult(
        success=True,
        client_session_id="sid-test",
        uuid="uuid-test",
    ))
    client.checkin = AsyncMock(return_value=CheckinResult(
        success=True,
        verdict="proceed",
    ))
    client.leave_note = AsyncMock()
    return client


# --- Identity resolution ---


class TestIdentityResolution:
    @pytest.mark.asyncio
    async def test_token_resume_first(self, tmp_path):
        """Should try token resume first."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.continuity_token = _make_token("uuid-test")
        agent.agent_uuid = "uuid-test"

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.identity.assert_called_once()
        args = client.identity.call_args
        assert args.kwargs.get("continuity_token") == agent.continuity_token

    @pytest.mark.asyncio
    async def test_name_resume_fallback(self, tmp_path):
        """If no token, should try name resume."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.identity.assert_called_once()
        args = client.identity.call_args
        assert args.kwargs.get("name") == "TestAgent"

    @pytest.mark.asyncio
    async def test_onboard_fallback(self, tmp_path):
        """If name resume fails, should onboard fresh."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")

        client = _mock_client_connected()
        client.identity = AsyncMock(side_effect=Exception("not found"))
        await agent._ensure_identity(client)

        client.onboard.assert_called_once_with("TestAgent")

    @pytest.mark.asyncio
    async def test_stale_token_discarded(self, tmp_path):
        """If token's aid doesn't match agent_uuid, discard it."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.continuity_token = _make_token("wrong-uuid")
        agent.agent_uuid = "correct-uuid"

        # Mock must return the same UUID the agent expects
        client = _mock_client_connected()
        client.agent_uuid = "correct-uuid"
        client.identity = AsyncMock(return_value=IdentityResult(
            client_session_id="sid-test",
            uuid="correct-uuid",
            continuity_token=_make_token("correct-uuid"),
        ))
        await agent._ensure_identity(client)

        # Token was discarded, so identity should be called with name (not token)
        args = client.identity.call_args
        assert args.kwargs.get("name") == "TestAgent"
        assert "continuity_token" not in args.kwargs

    @pytest.mark.asyncio
    async def test_identity_drift_during_token_resume_falls_through_to_name(self, tmp_path):
        """If token resume causes drift (e.g., server secret rotated),
        discard the stale token and fall through to name resume."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.continuity_token = _make_token("uuid-test")
        agent.agent_uuid = "uuid-test"

        client = _mock_client_connected()
        # First call (token resume) drifts; second call (name resume) succeeds
        client.identity = AsyncMock(side_effect=[
            IdentityDriftError("uuid-test", "other-uuid"),
            IdentityResult(
                client_session_id="sid-test",
                uuid="uuid-test",
                continuity_token=_make_token("uuid-test"),
            ),
        ])

        await agent._ensure_identity(client)

        assert client.identity.call_count == 2
        # Second call should use name, not token
        second_call = client.identity.call_args_list[1]
        assert second_call.kwargs.get("name") == "TestAgent"
        assert "continuity_token" not in second_call.kwargs
        client.onboard.assert_not_called()


# --- Session persistence ---


class TestSessionPersistence:
    def test_save_and_load(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.client_session_id = "sid-1"
        agent.continuity_token = "tok-1"
        agent.agent_uuid = "uuid-1"
        agent._save_session()

        agent2 = SimpleAgent(session_file=tmp_path / ".test_session")
        agent2._load_session()
        assert agent2.client_session_id == "sid-1"
        assert agent2.continuity_token == "tok-1"
        assert agent2.agent_uuid == "uuid-1"

    def test_load_missing_file(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".nope")
        agent._load_session()
        assert agent.client_session_id is None


# --- Check-in handling ---


class TestCheckinHandling:
    @pytest.mark.asyncio
    async def test_cycle_result_triggers_checkin(self, tmp_path):
        agent = SimpleAgent(
            cycle_result=CycleResult.simple("did work"),
            session_file=tmp_path / ".test_session",
        )
        client = _mock_client_connected()

        await agent._handle_cycle_result(client, CycleResult.simple("did work"))
        client.checkin.assert_called_once()
        args = client.checkin.call_args
        assert args.kwargs["response_text"] == "did work"

    @pytest.mark.asyncio
    async def test_none_skips_checkin(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        client = _mock_client_connected()

        await agent._handle_cycle_result(client, None)
        client.checkin.assert_not_called()

    @pytest.mark.asyncio
    async def test_notes_posted(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        client = _mock_client_connected()

        result = CycleResult(
            summary="work done",
            notes=[
                ("note 1", ["tag1"]),
                ("note 2", ["tag2", "tag3"]),
            ],
        )
        await agent._handle_cycle_result(client, result)
        assert client.leave_note.call_count == 2

    @pytest.mark.asyncio
    async def test_pause_verdict_raises(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        client = _mock_client_connected()
        client.checkin = AsyncMock(return_value=CheckinResult(
            success=True,
            verdict="pause",
            guidance="Entropy too high",
        ))

        with pytest.raises(VerdictError) as exc_info:
            await agent._handle_cycle_result(client, CycleResult.simple("test"))
        assert exc_info.value.verdict == "pause"


# --- Heartbeat ---


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_sends_heartbeat(self, tmp_path):
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent._last_checkin_time = 0  # long ago
        client = _mock_client_connected()

        await agent._send_heartbeat(client)
        client.checkin.assert_called_once()
        args = client.checkin.call_args
        assert args.kwargs["response_text"] == "heartbeat"
        assert args.kwargs["complexity"] == 0.05


# --- State persistence ---


class TestStatePersistence:
    def test_save_and_load_state(self, tmp_path):
        agent = SimpleAgent(state_dir=tmp_path / "test_state")
        agent.save_state({"health": "ok", "cycles": 42})

        loaded = agent.load_state()
        assert loaded["health"] == "ok"
        assert loaded["cycles"] == 42

    def test_load_missing_state(self, tmp_path):
        agent = SimpleAgent(state_dir=tmp_path / "nonexistent")
        assert agent.load_state() == {}


# --- Graceful shutdown ---


class TestGracefulShutdown:
    def test_handle_signal(self):
        agent = SimpleAgent()
        assert agent.running is True
        agent._handle_signal(2)  # SIGINT
        assert agent.running is False


# --- sync_from_client ---


class TestSyncFromClient:
    def test_copies_identity(self):
        agent = SimpleAgent()
        client = MagicMock()
        client.client_session_id = "sid-new"
        client.continuity_token = "tok-new"
        client.agent_uuid = "uuid-new"

        agent._sync_from_client(client)
        assert agent.client_session_id == "sid-new"
        assert agent.continuity_token == "tok-new"
        assert agent.agent_uuid == "uuid-new"

    def test_raises_on_drift(self):
        agent = SimpleAgent()
        agent.agent_uuid = "uuid-original"

        client = MagicMock()
        client.client_session_id = "sid"
        client.continuity_token = "tok"
        client.agent_uuid = "uuid-different"

        with pytest.raises(IdentityDriftError):
            agent._sync_from_client(client)
