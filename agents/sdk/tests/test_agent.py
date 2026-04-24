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
    async def test_uuid_resume_fast_path(self, tmp_path):
        """When agent_uuid is stored, should call identity(agent_uuid=...) directly."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.agent_uuid = "uuid-test"

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.identity.assert_called_once()
        args = client.identity.call_args
        assert args.kwargs.get("agent_uuid") == "uuid-test"
        assert args.kwargs.get("resume") is True
        client.onboard.assert_not_called()

    @pytest.mark.asyncio
    async def test_uuid_lookup_failure_raises(self, tmp_path):
        """If UUID lookup fails, must raise — never silently create a ghost."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")
        agent.agent_uuid = "uuid-dead"

        client = _mock_client_connected()
        client.identity = AsyncMock(side_effect=Exception("uuid_not_found"))
        with pytest.raises(Exception, match="uuid_not_found"):
            await agent._ensure_identity(client)

        # Must NOT fall through to onboard
        client.onboard.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_onboard_when_no_uuid(self, tmp_path):
        """If no stored UUID, should onboard fresh."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.onboard.assert_called_once_with("TestAgent")
        client.identity.assert_not_called()

    @pytest.mark.asyncio
    async def test_onboard_forwards_parent_agent_id(self, tmp_path):
        """When configured, parent_agent_id + spawn_reason reach the onboard call."""
        agent = SimpleAgent(
            session_file=tmp_path / ".test_session",
            parent_agent_id="parent-uuid-123",
            spawn_reason="subagent",
        )

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.onboard.assert_called_once_with(
            "TestAgent",
            parent_agent_id="parent-uuid-123",
            spawn_reason="subagent",
        )

    @pytest.mark.asyncio
    async def test_onboard_omits_lineage_when_unset(self, tmp_path):
        """Default (no parent) must preserve backward-compatible onboard call shape."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        # No parent_agent_id / spawn_reason kwargs when agent didn't set them
        call_kwargs = client.onboard.call_args.kwargs
        assert "parent_agent_id" not in call_kwargs
        assert "spawn_reason" not in call_kwargs

    @pytest.mark.asyncio
    async def test_resident_tags_stamped_on_fresh_onboard(self, tmp_path):
        """persistent=True agents stamp the full resident tag set after fresh onboard.

        Residents need BOTH 'persistent' (exempts orphan-sweep) AND 'autonomous'
        (exempts loop-detection pattern 4). Steward hit the pattern-4 gap on
        2026-04-20 because this path stamped only 'persistent'; once every 5min
        its sync was rejected, starving core.agent_state. RESIDENT_TAGS is the
        single source of truth.
        """
        from unitares_sdk.agent import RESIDENT_TAGS
        assert "persistent" in RESIDENT_TAGS
        assert "autonomous" in RESIDENT_TAGS

        agent = SimpleAgent(session_file=tmp_path / ".test_session", persistent=True)

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        # Fresh onboard + subsequent update_agent_metadata call
        client.onboard.assert_called_once()
        client.call_tool.assert_awaited_once_with(
            "update_agent_metadata",
            {"agent_id": "uuid-test", "tags": RESIDENT_TAGS},
        )

    @pytest.mark.asyncio
    async def test_persistent_tag_not_stamped_when_not_persistent(self, tmp_path):
        """Default persistent=False must not call update_agent_metadata."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session")

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.onboard.assert_called_once()
        client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistent_tag_not_stamped_on_uuid_resume(self, tmp_path):
        """Resuming an existing UUID skips tag stamping — it's already been tagged
        on the original fresh onboard (or manually).
        """
        agent = SimpleAgent(session_file=tmp_path / ".test_session", persistent=True)
        agent.agent_uuid = "uuid-test"  # triggers the resume fast path

        client = _mock_client_connected()
        await agent._ensure_identity(client)

        client.identity.assert_awaited_once()
        client.onboard.assert_not_called()
        client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistent_tag_failure_is_non_fatal(self, tmp_path):
        """If update_agent_metadata fails, the agent still onboards successfully."""
        agent = SimpleAgent(session_file=tmp_path / ".test_session", persistent=True)

        client = _mock_client_connected()
        client.call_tool = AsyncMock(side_effect=RuntimeError("db down"))

        # Must not raise — the exception is caught and logged.
        await agent._ensure_identity(client)

        client.onboard.assert_called_once()
        client.call_tool.assert_awaited_once()
        # Identity is still established.
        assert agent.agent_uuid == "uuid-test"


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

    def test_default_session_file_is_home_anchor(self, tmp_path, monkeypatch):
        """Without an explicit session_file, default is ~/.unitares/anchors/<name>.json."""
        monkeypatch.setenv("HOME", str(tmp_path))
        from unitares_sdk.agent import GovernanceAgent

        # Use the real class directly since SimpleAgent may override defaults.
        class _BareAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

        agent = _BareAgent(name="TestAgent")
        expected = Path(tmp_path) / ".unitares" / "anchors" / "testagent.json"
        assert agent.session_file == expected

    def test_save_creates_anchor_parent_dir(self, tmp_path):
        """_save_session mkdirs the anchor parent automatically."""
        anchor = tmp_path / "deep" / "nested" / "anchors" / "x.json"
        agent = SimpleAgent(session_file=anchor)
        agent.agent_uuid = "u-1"
        agent._save_session()
        assert anchor.exists()

    def test_migrates_from_legacy_when_anchor_missing(self, tmp_path):
        """Legacy session file is migrated to the anchor on first load."""
        anchor = tmp_path / "anchor.json"
        legacy = tmp_path / "legacy.session"
        legacy.write_text('{"agent_uuid": "u-legacy", "continuity_token": "t-legacy"}')

        agent = SimpleAgent(session_file=anchor, legacy_session_file=legacy)
        agent._load_session()

        assert agent.agent_uuid == "u-legacy"
        assert agent.continuity_token == "t-legacy"
        assert anchor.exists(), "anchor should have been written by migration"

    def test_anchor_wins_over_legacy_when_both_exist(self, tmp_path):
        """If both anchor and legacy exist, the anchor is the source of truth."""
        anchor = tmp_path / "anchor.json"
        anchor.write_text('{"agent_uuid": "u-anchor"}')
        legacy = tmp_path / "legacy.session"
        legacy.write_text('{"agent_uuid": "u-legacy"}')

        agent = SimpleAgent(session_file=anchor, legacy_session_file=legacy)
        agent._load_session()
        assert agent.agent_uuid == "u-anchor"


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


class TestCycleTimeout:
    @pytest.mark.asyncio
    async def test_cycle_timeout_fires(self):
        """run_once raises TimeoutError if the cycle exceeds cycle_timeout_seconds."""

        class SlowAgent(GovernanceAgent):
            async def run_cycle(self, client):
                await asyncio.sleep(10.0)
                return CycleResult.simple("never reached")

        agent = SlowAgent(
            name="Slow",
            mcp_url="http://127.0.0.1:9999/mcp/",
            cycle_timeout_seconds=0.05,
        )
        # Bypass network: patch the client context manager and identity
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(SlowAgent, "_ensure_identity", AsyncMock()):
                with pytest.raises(asyncio.TimeoutError):
                    await agent.run_once()

    @pytest.mark.asyncio
    async def test_cycle_timeout_none_means_no_bound(self):
        """cycle_timeout_seconds=None disables the wrapper (default); run_once completes."""

        class QuickAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None  # skip checkin path entirely

        agent = QuickAgent(name="Quick", mcp_url="http://127.0.0.1:9999/mcp/")
        assert agent.cycle_timeout_seconds is None

        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(QuickAgent, "_ensure_identity", AsyncMock()):
                # Must complete without raising — no wait_for wrapping when None.
                await agent.run_once()

    @pytest.mark.asyncio
    async def test_run_forever_respects_cycle_timeout(self):
        """run_forever also bounds each iteration by cycle_timeout_seconds."""

        timed_out = {"fired": False}

        class SlowForeverAgent(GovernanceAgent):
            async def run_cycle(self, client):
                self.running = False  # exit loop after this iteration
                try:
                    await asyncio.sleep(10.0)
                except asyncio.CancelledError:
                    timed_out["fired"] = True
                    raise

        agent = SlowForeverAgent(
            name="SlowForever",
            mcp_url="http://127.0.0.1:9999/mcp/",
            cycle_timeout_seconds=0.05,
        )
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(SlowForeverAgent, "_ensure_identity", AsyncMock()):
                with patch.object(SlowForeverAgent, "_install_signal_handlers"):
                    # notify() may be called during error logging — stub it out.
                    with patch("unitares_sdk.agent.notify"):
                        # run_forever catches the TimeoutError internally and
                        # sleeps "interval" seconds before retrying; set interval
                        # to 0 and running=False inside run_cycle to exit.
                        await agent.run_forever(interval=0)
        assert timed_out["fired"] is True


class TestLogFileTrim:
    @pytest.mark.asyncio
    async def test_log_file_trimmed_after_cycle(self, tmp_path):
        """Base class trims log_file to max_log_lines after each cycle."""
        log_path = tmp_path / "agent.log"
        log_path.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")

        class LoggingAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None  # skip checkin

        agent = LoggingAgent(
            name="Logger",
            mcp_url="http://127.0.0.1:9999/mcp/",
            log_file=log_path,
            max_log_lines=10,
        )
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(LoggingAgent, "_ensure_identity", AsyncMock()):
                await agent.run_once()

        surviving = log_path.read_text().splitlines()
        assert len(surviving) == 10
        assert surviving[-1] == "line 99"

    @pytest.mark.asyncio
    async def test_log_file_none_is_noop(self, tmp_path):
        """log_file=None (default) does not error."""

        class QuietAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

        agent = QuietAgent(name="Quiet", mcp_url="http://127.0.0.1:9999/mcp/")
        assert agent.log_file is None
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(QuietAgent, "_ensure_identity", AsyncMock()):
                await agent.run_once()

    @pytest.mark.asyncio
    async def test_log_file_trimmed_even_on_cycle_timeout(self, tmp_path):
        """Log trim happens in finally, so it fires even when the cycle times out."""
        log_path = tmp_path / "agent.log"
        log_path.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")

        class SlowAgent(GovernanceAgent):
            async def run_cycle(self, client):
                await asyncio.sleep(10.0)
                return None

        agent = SlowAgent(
            name="Slow",
            mcp_url="http://127.0.0.1:9999/mcp/",
            log_file=log_path,
            max_log_lines=5,
            cycle_timeout_seconds=0.05,
        )
        with patch("unitares_sdk.agent.GovernanceClient") as mock_cm:
            mock_client = AsyncMock()
            mock_cm.return_value.__aenter__.return_value = mock_client
            mock_cm.return_value.__aexit__.return_value = None
            with patch.object(SlowAgent, "_ensure_identity", AsyncMock()):
                with pytest.raises(asyncio.TimeoutError):
                    await agent.run_once()
        # Trim must have fired despite the TimeoutError.
        assert len(log_path.read_text().splitlines()) == 5


class TestOnAfterCheckin:
    @pytest.mark.asyncio
    async def test_hook_called_with_checkin_result(self):
        """on_after_checkin runs after a successful checkin with the result."""
        captured: dict = {}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("did work")

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["checkin_verdict"] = checkin_result.verdict
                captured["cycle_summary"] = cycle_result.summary

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="proceed", coherence=0.9,
                guidance="", metrics={}, _raw={},
            )
        )
        await agent._handle_cycle_result(mock_client, CycleResult.simple("did work"))

        assert captured["checkin_verdict"] == "proceed"
        assert captured["cycle_summary"] == "did work"

    @pytest.mark.asyncio
    async def test_hook_not_called_when_result_is_none(self):
        """on_after_checkin is skipped when run_cycle returned None."""
        captured: dict = {"called": False}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return None

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["called"] = True

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        await agent._handle_cycle_result(mock_client, None)
        assert captured["called"] is False

    @pytest.mark.asyncio
    async def test_hook_runs_before_verdict_error_on_pause(self):
        """Hook runs on pause verdict before VerdictError is raised, so state trackers see it."""
        captured: dict = {"called": False, "verdict": None}

        class HookedAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("work")

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                captured["called"] = True
                captured["verdict"] = checkin_result.verdict

        agent = HookedAgent(name="Hooked", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="pause", coherence=0.5,
                guidance="slow down", metrics={}, _raw={},
            )
        )
        with pytest.raises(VerdictError):
            await agent._handle_cycle_result(mock_client, CycleResult.simple("work"))
        assert captured["called"] is True
        assert captured["verdict"] == "pause"

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_break_cycle(self):
        """If on_after_checkin raises, it's logged but VerdictError is still decided from checkin_result."""

        class BrokenHookAgent(GovernanceAgent):
            async def run_cycle(self, client):
                return CycleResult.simple("work")

            async def on_after_checkin(self, client, checkin_result, cycle_result):
                raise RuntimeError("hook exploded")

        agent = BrokenHookAgent(name="Broken", mcp_url="http://127.0.0.1:9999/mcp/")
        mock_client = AsyncMock()
        mock_client.checkin = AsyncMock(
            return_value=CheckinResult(
                success=True, verdict="proceed", coherence=0.9,
                guidance="", metrics={}, _raw={},
            )
        )
        # Must NOT raise: hook failure is swallowed, verdict is proceed so no VerdictError.
        await agent._handle_cycle_result(mock_client, CycleResult.simple("work"))
