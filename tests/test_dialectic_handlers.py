"""
Comprehensive tests for dialectic MCP handlers (src/mcp_handlers/dialectic.py).

Tests the 6 key handler functions:
1. handle_request_dialectic_review - Create dialectic session
2. handle_submit_thesis - Submit thesis in session
3. handle_submit_antithesis - Submit antithesis
4. handle_submit_synthesis - Submit synthesis
5. handle_list_dialectic_sessions - List all sessions
6. handle_get_dialectic_session - Get session by ID or agent

Each handler is tested for: happy path, missing required args, error/exception handling.

All database and external calls are mocked - no PostgreSQL required.
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from types import SimpleNamespace
from datetime import datetime, timedelta

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dialectic_protocol import (
    DialecticSession,
    DialecticMessage,
    DialecticPhase,
    Resolution,
)
from mcp.types import TextContent


# ============================================================================
# Helpers
# ============================================================================

def _parse(result):
    """Parse TextContent result(s) to dict."""
    if isinstance(result, (list, tuple)):
        return json.loads(result[0].text)
    return json.loads(result.text)


def _make_mock_server(agents=None):
    """Create a mock mcp_server with agent_metadata."""
    mock = MagicMock()
    mock.agent_metadata = agents or {}
    mock.monitors = {}
    mock.load_metadata = MagicMock()
    mock.load_metadata_async = AsyncMock()
    mock.project_root = str(project_root)
    return mock


def _make_agent_meta(status="active", label="Test", api_key="key123"):
    """Create a SimpleNamespace mimicking agent metadata."""
    return SimpleNamespace(
        status=status,
        label=label,
        api_key=api_key,
        last_update=datetime.now().isoformat(),
        paused_at=None,
        structured_id=None,
    )


def _make_session(paused_id="agent-paused", reviewer_id="agent-reviewer",
                  phase=DialecticPhase.THESIS, session_type="recovery"):
    """Create a DialecticSession for testing."""
    session = DialecticSession(
        paused_agent_id=paused_id,
        reviewer_agent_id=reviewer_id,
        session_type=session_type,
    )
    session.phase = phase
    return session


# Common patch targets (module-level references in dialectic.py)
DIALECTIC = "src.mcp_handlers.dialectic"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_server():
    """Provide a mock mcp_server patched into dialectic module."""
    server = _make_mock_server({
        "agent-paused": _make_agent_meta(status="paused"),
        "agent-reviewer": _make_agent_meta(status="active"),
        "agent-active": _make_agent_meta(status="active"),
        "agent-waiting": _make_agent_meta(status="waiting_input"),
    })
    with patch(f"{DIALECTIC}.mcp_server", server):
        yield server


@pytest.fixture
def mock_require_registered():
    """Mock require_registered_agent to return a known agent_id."""
    def _factory(agent_id="agent-paused", error=None):
        return patch(
            f"{DIALECTIC}.require_registered_agent",
            return_value=(agent_id, error),
        )
    return _factory


@pytest.fixture
def mock_verify_ownership():
    """Mock verify_agent_ownership to return True.

    This is imported locally inside handle_request_dialectic_review,
    so we patch it at the source location.
    """
    return patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=True)


@pytest.fixture
def mock_pg_create():
    """Mock pg_create_session."""
    return patch(f"{DIALECTIC}.pg_create_session", new_callable=AsyncMock)


@pytest.fixture
def mock_pg_add_message():
    """Mock pg_add_message."""
    return patch(f"{DIALECTIC}.pg_add_message", new_callable=AsyncMock)


@pytest.fixture
def mock_pg_update_phase():
    """Mock pg_update_phase."""
    return patch(f"{DIALECTIC}.pg_update_phase", new_callable=AsyncMock)


@pytest.fixture
def mock_pg_resolve_session():
    """Mock pg_resolve_session."""
    return patch(f"{DIALECTIC}.pg_resolve_session", new_callable=AsyncMock)


@pytest.fixture
def mock_is_in_session():
    """Mock is_agent_in_active_session to return False."""
    return patch(
        f"{DIALECTIC}.is_agent_in_active_session",
        new_callable=AsyncMock,
        return_value=False,
    )


@pytest.fixture
def mock_save_session():
    """Mock save_session."""
    return patch(f"{DIALECTIC}.save_session", new_callable=AsyncMock)


@pytest.fixture
def mock_load_session():
    """Mock load_session."""
    return patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock)


@pytest.fixture
def mock_context_agent():
    """Mock get_context_agent_id used by success_response and error_response.

    This is imported locally from src.mcp_handlers.context in many places,
    so we patch it at its canonical location.
    """
    return patch(
        "src.mcp_handlers.context.get_context_agent_id",
        return_value=None,
    )


@pytest.fixture(autouse=True)
def clear_active_sessions():
    """Clear ACTIVE_SESSIONS between tests to prevent leakage."""
    from src.mcp_handlers.dialectic_session import ACTIVE_SESSIONS
    ACTIVE_SESSIONS.clear()
    yield
    ACTIVE_SESSIONS.clear()


# ============================================================================
# 1. handle_request_dialectic_review
# ============================================================================

class TestHandleRequestDialecticReview:
    """Tests for handle_request_dialectic_review handler."""

    @pytest.mark.asyncio
    async def test_happy_path_self_review(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_pg_create, mock_is_in_session, mock_context_agent,
    ):
        """Self-review mode creates session with reviewer = paused agent."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             mock_pg_create as pg_create, mock_is_in_session, mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
                "reason": "Test recovery",
                "reviewer_mode": "self",
            })

        data = _parse(result)
        assert data["success"] is True
        assert data["paused_agent_id"] == "agent-paused"
        assert data["reviewer_agent_id"] == "agent-paused"
        assert data["phase"] == "thesis"
        assert data["session_type"] == "recovery"
        assert "session_id" in data
        pg_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_auto_mode_no_reviewer(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_pg_create, mock_is_in_session, mock_context_agent,
    ):
        """Auto mode creates session with no reviewer assigned (awaiting assignment)."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             mock_pg_create, mock_is_in_session, mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
                "reason": "High risk score",
                "reviewer_mode": "auto",
            })

        data = _parse(result)
        assert data["success"] is True
        assert data["reviewer_agent_id"] is None
        assert data["awaiting_reviewer"] is True

    @pytest.mark.asyncio
    async def test_agent_not_registered(self, mock_server, mock_context_agent):
        """Returns error when agent is not registered."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review
        from src.mcp_handlers.utils import error_response

        err = error_response("Agent not registered")
        with patch(f"{DIALECTIC}.require_registered_agent", return_value=(None, err)), \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "unknown-agent",
            })

        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_agent_not_found_in_metadata(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_context_agent,
    ):
        """Returns error when agent passes registration but not in metadata."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        # Use an agent_id that is not in mock_server.agent_metadata
        with mock_require_registered("agent-nonexistent"), mock_verify_ownership, \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-nonexistent",
                "_agent_uuid": "agent-nonexistent",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_ownership_verification_fails(
        self, mock_server, mock_require_registered, mock_context_agent,
    ):
        """Returns auth error when ownership verification fails."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=False), \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "auth" in data.get("error_code", "").lower() or "auth" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_agent_waiting_input_skipped(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_context_agent,
    ):
        """Agent in waiting_input status is skipped (not stuck)."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-waiting"), mock_verify_ownership, \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-waiting",
                "_agent_uuid": "agent-waiting",
            })

        data = _parse(result)
        assert data["success"] is True
        assert data.get("skipped") is True
        assert "waiting_input" in data.get("reason", "")

    @pytest.mark.asyncio
    async def test_duplicate_session_prevented(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_context_agent,
    ):
        """Returns error if agent already has an active session."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             patch(f"{DIALECTIC}.is_agent_in_active_session",
                   new_callable=AsyncMock, return_value=True), \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
            })

        data = _parse(result)
        assert data["success"] is False
        assert data.get("error_code") == "SESSION_EXISTS"

    @pytest.mark.asyncio
    async def test_pg_create_failure(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_is_in_session, mock_context_agent,
    ):
        """Returns error when PostgreSQL session create fails."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             mock_is_in_session, \
             patch(f"{DIALECTIC}.pg_create_session",
                   new_callable=AsyncMock,
                   side_effect=Exception("DB connection lost")), \
             mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
                "reviewer_mode": "self",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "DB_WRITE_FAILED" in data.get("error_code", "")

    @pytest.mark.asyncio
    async def test_llm_reviewer_mode_delegates(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_is_in_session, mock_context_agent,
    ):
        """reviewer_mode='llm' delegates to handle_llm_assisted_dialectic."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        mock_llm_handler = AsyncMock(return_value=[TextContent(
            type="text", text=json.dumps({"success": True, "message": "LLM dialectic done"})
        )])

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             mock_is_in_session, mock_context_agent, \
             patch(f"{DIALECTIC}.handle_llm_assisted_dialectic", mock_llm_handler):
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
                "reason": "Test",
                "reviewer_mode": "llm",
            })

        mock_llm_handler.assert_awaited_once()
        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_custom_session_type_and_topic(
        self, mock_server, mock_require_registered, mock_verify_ownership,
        mock_pg_create, mock_is_in_session, mock_context_agent,
    ):
        """Custom session_type, topic, and discovery_id are passed through."""
        from src.mcp_handlers.dialectic import handle_request_dialectic_review

        with mock_require_registered("agent-paused"), mock_verify_ownership, \
             mock_pg_create as pg_create, mock_is_in_session, mock_context_agent:
            result = await handle_request_dialectic_review({
                "agent_id": "agent-paused",
                "_agent_uuid": "agent-paused",
                "session_type": "dispute",
                "topic": "Knowledge graph accuracy",
                "discovery_id": "disc-123",
                "reviewer_mode": "self",
            })

        data = _parse(result)
        assert data["success"] is True
        assert data["session_type"] == "dispute"
        # Verify pg_create was called with correct kwargs
        call_kwargs = pg_create.call_args.kwargs
        assert call_kwargs["session_type"] == "dispute"
        assert call_kwargs["topic"] == "Knowledge graph accuracy"
        assert call_kwargs["discovery_id"] == "disc-123"


# ============================================================================
# 2. handle_submit_thesis
# ============================================================================

class TestHandleSubmitThesis:
    """Tests for handle_submit_thesis handler."""

    @pytest.mark.asyncio
    async def test_happy_path(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Successful thesis submission advances phase to antithesis."""
        from src.mcp_handlers.dialectic import handle_submit_thesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "root_cause": "Complexity spike",
                "proposed_conditions": ["Lower threshold"],
                "reasoning": "Task was too complex",
                "api_key": "key123",
            })

        data = _parse(result)
        assert data["success"] is True
        assert "next_step" in data
        assert session.phase == DialecticPhase.ANTITHESIS

    @pytest.mark.asyncio
    async def test_missing_session_id(self, mock_context_agent):
        """Returns error when session_id is missing."""
        from src.mcp_handlers.dialectic import handle_submit_thesis

        with mock_context_agent:
            result = await handle_submit_thesis({
                "agent_id": "agent-paused",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_agent_id_no_bound(self, mock_context_agent):
        """Returns error when agent_id is missing and no bound identity."""
        from src.mcp_handlers.dialectic import handle_submit_thesis

        with mock_context_agent, \
             patch("src.mcp_handlers.identity_shared.get_bound_agent_id", return_value=None):
            result = await handle_submit_thesis({
                "session_id": "some-session",
            })

        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_load_session, mock_context_agent):
        """Returns error when session does not exist."""
        from src.mcp_handlers.dialectic import handle_submit_thesis

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock, return_value=None), \
             mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": "nonexistent-session",
                "agent_id": "agent-paused",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_wrong_agent_submits_thesis(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Thesis from non-paused agent fails (DialecticSession rejects it)."""
        from src.mcp_handlers.dialectic import handle_submit_thesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": session.session_id,
                "agent_id": "agent-reviewer",  # Wrong agent
                "root_cause": "Something",
                "api_key": "key",
            })

        data = _parse(result)
        # DialecticSession.submit_thesis returns {"success": False, "error": "Only paused agent can submit thesis"}
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_thesis_wrong_phase(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Thesis in wrong phase fails."""
        from src.mcp_handlers.dialectic import handle_submit_thesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "root_cause": "Something",
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "phase" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_thesis_loads_from_disk_on_miss(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Session not in memory is loaded from disk."""
        from src.mcp_handlers.dialectic import handle_submit_thesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "root_cause": "Loaded from disk",
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is True
        assert session.session_id in ACTIVE_SESSIONS

    @pytest.mark.asyncio
    async def test_pg_add_message_failure_nonfatal(
        self, mock_server, mock_pg_update_phase, mock_save_session,
        mock_context_agent,
    ):
        """pg_add_message failure is non-fatal (logged as warning)."""
        from src.mcp_handlers.dialectic import handle_submit_thesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with patch(f"{DIALECTIC}.pg_add_message", new_callable=AsyncMock,
                   side_effect=Exception("DB down")), \
             mock_pg_update_phase, mock_save_session, mock_context_agent:
            result = await handle_submit_thesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "root_cause": "Test",
                "api_key": "key",
            })

        data = _parse(result)
        # Still succeeds despite pg failure (non-fatal)
        assert data["success"] is True


# ============================================================================
# 3. handle_submit_antithesis
# ============================================================================

class TestHandleSubmitAntithesis:
    """Tests for handle_submit_antithesis handler."""

    @pytest.mark.asyncio
    async def test_happy_path(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Successful antithesis submission advances phase to synthesis."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_antithesis({
                "session_id": session.session_id,
                "agent_id": "agent-reviewer",
                "observed_metrics": {"risk_score": 0.65},
                "concerns": ["Risk too high", "Coherence dropping"],
                "reasoning": "Agent needs cooldown",
                "api_key": "key456",
            })

        data = _parse(result)
        assert data["success"] is True
        assert "next_step" in data
        assert session.phase == DialecticPhase.SYNTHESIS

    @pytest.mark.asyncio
    async def test_missing_required_args(self, mock_context_agent):
        """Returns error when session_id and agent_id both missing."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis

        with mock_context_agent, \
             patch("src.mcp_handlers.identity_shared.get_bound_agent_id", return_value=None):
            result = await handle_submit_antithesis({})

        data = _parse(result)
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_context_agent):
        """Returns error when session does not exist."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock, return_value=None), \
             mock_context_agent:
            result = await handle_submit_antithesis({
                "session_id": "nonexistent",
                "agent_id": "agent-reviewer",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_wrong_agent_submits_antithesis(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Antithesis from non-reviewer agent fails."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_antithesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",  # Wrong: paused agent, not reviewer
                "concerns": ["Something"],
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_antithesis_wrong_phase(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Antithesis in wrong phase fails."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)
        ACTIVE_SESSIONS[session.session_id] = session

        with mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_antithesis({
                "session_id": session.session_id,
                "agent_id": "agent-reviewer",
                "concerns": ["Test"],
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "phase" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_antithesis_loads_from_disk(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Session loaded from disk when not in memory."""
        from src.mcp_handlers.dialectic import handle_submit_antithesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.ANTITHESIS)

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_antithesis({
                "session_id": session.session_id,
                "agent_id": "agent-reviewer",
                "concerns": ["Concern"],
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is True
        assert session.session_id in ACTIVE_SESSIONS


# ============================================================================
# 4. handle_submit_synthesis
# ============================================================================

class TestHandleSubmitSynthesis:
    """Tests for handle_submit_synthesis handler."""

    @pytest.mark.asyncio
    async def test_happy_path_no_convergence(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Synthesis submission without convergence returns next step."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        session.synthesis_round = 1
        # We need to add the session to the load_session path since
        # handle_submit_synthesis always reloads from disk first
        ACTIVE_SESSIONS[session.session_id] = session

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "proposed_conditions": ["Lower threshold to 0.5"],
                "root_cause": "Complexity spike",
                "reasoning": "We should be more lenient",
                "agrees": False,
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_missing_required_args(self, mock_context_agent):
        """Returns error when session_id and agent_id both missing."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        with mock_context_agent, \
             patch("src.mcp_handlers.identity_shared.get_bound_agent_id", return_value=None):
            result = await handle_submit_synthesis({})

        data = _parse(result)
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_session_not_found(self, mock_context_agent):
        """Returns error when session not found anywhere."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock, return_value=None), \
             mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": "nonexistent",
                "agent_id": "agent-paused",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_synthesis_wrong_phase(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Synthesis in wrong phase fails."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        session = _make_session(phase=DialecticPhase.THESIS)

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "proposed_conditions": ["Test"],
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_synthesis_third_party_mediator(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Third-party mediator can submit synthesis (resolves if agrees=True)."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        session.synthesis_round = 1

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-mediator",
                "proposed_conditions": ["Test"],
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_max_rounds_exceeded(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_context_agent,
    ):
        """Max synthesis rounds exceeded returns conservative default."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        session.synthesis_round = 6  # Over max of 5
        session.max_synthesis_rounds = 5

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "proposed_conditions": ["Test"],
                "api_key": "key",
            })

        data = _parse(result)
        # Session escalated or conservative default
        assert data["success"] is False or data.get("autonomous_resolution") is True

    @pytest.mark.asyncio
    async def test_convergence_with_resolution(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_pg_resolve_session, mock_context_agent,
    ):
        """When both agents agree, synthesis converges and resolution is created."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        session.synthesis_round = 1

        # Mock the session's submit_synthesis to indicate convergence
        mock_result = {
            "success": True,
            "converged": True,
            "phase": "resolved",
        }

        # Mock finalize_resolution and check_hard_limits
        mock_resolution = MagicMock()
        mock_resolution.to_dict.return_value = {
            "action": "resume",
            "conditions": ["Lower threshold"],
            "signed_by": ["agent-paused", "agent-reviewer"],
        }

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock, return_value=session), \
             patch.object(session, "submit_synthesis", return_value=mock_result), \
             patch.object(session, "finalize_resolution", return_value=mock_resolution), \
             patch.object(session, "check_hard_limits", return_value=(True, None)), \
             patch(f"{DIALECTIC}.execute_resolution", new_callable=AsyncMock,
                   return_value={"resumed": True}), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_pg_resolve_session, mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "proposed_conditions": ["Lower threshold"],
                "agrees": True,
                "api_key": "key",
            })

        data = _parse(result)
        assert data["success"] is True
        assert data.get("converged") is True
        assert data.get("action") == "resume"

    @pytest.mark.asyncio
    async def test_convergence_safety_violation(
        self, mock_server, mock_pg_add_message, mock_pg_update_phase,
        mock_save_session, mock_pg_resolve_session, mock_context_agent,
    ):
        """Safety violation during convergence blocks resolution."""
        from src.mcp_handlers.dialectic import handle_submit_synthesis

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        session.synthesis_round = 1

        mock_result = {"success": True, "converged": True, "phase": "resolved"}
        mock_resolution = MagicMock()
        mock_resolution.to_dict.return_value = {"action": "block"}

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock, return_value=session), \
             patch.object(session, "submit_synthesis", return_value=mock_result), \
             patch.object(session, "finalize_resolution", return_value=mock_resolution), \
             patch.object(session, "check_hard_limits", return_value=(False, "Bypass safety check")), \
             mock_pg_add_message, mock_pg_update_phase, mock_save_session, \
             mock_pg_resolve_session, mock_context_agent:
            result = await handle_submit_synthesis({
                "session_id": session.session_id,
                "agent_id": "agent-paused",
                "proposed_conditions": ["Disable monitoring"],
                "agrees": True,
                "api_key": "key",
            })

        data = _parse(result)
        assert data.get("action") == "block"
        assert "safety" in data.get("reason", "").lower()


# ============================================================================
# 5. handle_list_dialectic_sessions
# ============================================================================

class TestHandleListDialecticSessions:
    """Tests for handle_list_dialectic_sessions handler."""

    @pytest.mark.asyncio
    async def test_happy_path_with_results(self, mock_context_agent):
        """Returns sessions when found."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        mock_sessions = [
            {"session_id": "s1", "phase": "resolved", "paused_agent_id": "a1"},
            {"session_id": "s2", "phase": "failed", "paused_agent_id": "a2"},
        ]

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=mock_sessions), \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({})

        data = _parse(result)
        assert data["success"] is True
        assert data["session_count"] == 2
        assert len(data["sessions"]) == 2

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_context_agent):
        """Returns empty list with helpful tip when no sessions found."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=[]), \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({})

        data = _parse(result)
        assert data["success"] is True
        assert data["sessions"] == []
        assert "tip" in data

    @pytest.mark.asyncio
    async def test_filters_passed_through(self, mock_context_agent):
        """Filters (agent_id, status, limit) are passed to list_all_sessions."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=[]) as mock_list, \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({
                "agent_id": "agent-1",
                "status": "resolved",
                "limit": 10,
                "include_transcript": True,
            })

        mock_list.assert_awaited_once_with(
            agent_id="agent-1",
            status="resolved",
            limit=10,
            include_transcript=True,
        )

    @pytest.mark.asyncio
    async def test_limit_capped_at_200(self, mock_context_agent):
        """Limit is capped at 200 even if larger value provided."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=[]) as mock_list, \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({
                "limit": 999,
            })

        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["limit"] == 200

    @pytest.mark.asyncio
    async def test_exception_returns_error(self, mock_context_agent):
        """Exception during listing returns error response."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   side_effect=Exception("DB error")), \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({})

        data = _parse(result)
        assert data["success"] is False
        assert "error" in data

    @pytest.mark.asyncio
    async def test_default_limit_is_50(self, mock_context_agent):
        """Default limit is 50 when not specified."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=[]) as mock_list, \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({})

        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["limit"] == 50

    @pytest.mark.asyncio
    async def test_filters_in_response(self, mock_context_agent):
        """Response includes filters_applied for transparency."""
        from src.mcp_handlers.dialectic import handle_list_dialectic_sessions

        with patch(f"{DIALECTIC}.list_all_sessions", new_callable=AsyncMock,
                   return_value=[{"session_id": "s1"}]), \
             mock_context_agent:
            result = await handle_list_dialectic_sessions({
                "agent_id": "a1",
                "status": "failed",
            })

        data = _parse(result)
        assert data["filters_applied"]["agent_id"] == "a1"
        assert data["filters_applied"]["status"] == "failed"


# ============================================================================
# 6. handle_get_dialectic_session
# ============================================================================

class TestHandleGetDialecticSession:
    """Tests for handle_get_dialectic_session handler."""

    @pytest.mark.asyncio
    async def test_happy_path_by_session_id_in_memory(self, mock_context_agent):
        """Returns session data when found in memory by session_id."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.RESOLVED)
        # Set created_at to recent time so check_timeout won't fire
        session.created_at = datetime.now()
        ACTIVE_SESSIONS[session.session_id] = session

        # Mock check_reviewer_stuck to return False
        with patch(f"{DIALECTIC}.check_reviewer_stuck", new_callable=AsyncMock,
                   return_value=False), \
             mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": session.session_id,
            })

        data = _parse(result)
        assert data["success"] is True
        assert data["session_id"] == session.session_id

    @pytest.mark.asyncio
    async def test_no_args_provided(self, mock_context_agent):
        """Returns error when neither session_id nor agent_id provided."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        with mock_context_agent:
            result = await handle_get_dialectic_session({})

        data = _parse(result)
        assert data["success"] is False
        assert "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_session_not_found_by_id(self, mock_context_agent):
        """Returns error when session_id not found."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=None), \
             mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": "nonexistent-session",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_fast_path_no_timeout_check(self, mock_context_agent):
        """check_timeout=False uses fast path via load_session_as_dict."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        fast_dict = {
            "session_id": "fast-session",
            "phase": "resolved",
            "paused_agent_id": "a1",
        }

        with patch(f"{DIALECTIC}.load_session_as_dict", new_callable=AsyncMock,
                   return_value=fast_dict), \
             mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": "fast-session",
                "check_timeout": False,
            })

        data = _parse(result)
        assert data["success"] is True
        assert data["session_id"] == "fast-session"

    @pytest.mark.asyncio
    async def test_session_timed_out(
        self, mock_pg_add_message, mock_pg_update_phase, mock_context_agent,
    ):
        """Session that has timed out returns failure with recovery guidance."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.THESIS)
        session.created_at = datetime.now()
        ACTIVE_SESSIONS[session.session_id] = session

        # Mock check_timeout to return a timeout reason
        with patch.object(session, "check_timeout",
                          return_value="Session timeout - total time exceeded 6 hours"), \
             mock_pg_add_message, mock_pg_update_phase, mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": session.session_id,
                "check_timeout": True,
            })

        data = _parse(result)
        assert data["success"] is False
        assert "timeout" in data["error"].lower()
        assert "recovery" in data

    @pytest.mark.asyncio
    async def test_reviewer_stuck_detection(
        self, mock_pg_add_message, mock_pg_update_phase, mock_context_agent,
    ):
        """Reviewer stuck causes session to be marked as failed."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        session.created_at = datetime.now()
        ACTIVE_SESSIONS[session.session_id] = session

        # check_timeout returns None (not timed out), but reviewer is stuck
        with patch.object(session, "check_timeout", return_value=None), \
             patch(f"{DIALECTIC}.check_reviewer_stuck", new_callable=AsyncMock,
                   return_value=True), \
             mock_pg_add_message, mock_pg_update_phase, mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": session.session_id,
                "check_timeout": True,
            })

        data = _parse(result)
        assert data["success"] is False
        assert "reviewer" in data["error"].lower() or "stuck" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_session_loaded_from_disk(self, mock_context_agent):
        """Session loaded from disk is restored to in-memory cache."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session, ACTIVE_SESSIONS

        session = _make_session(phase=DialecticPhase.RESOLVED)
        session.created_at = datetime.now()

        with patch(f"{DIALECTIC}.load_session", new_callable=AsyncMock,
                   return_value=session), \
             patch(f"{DIALECTIC}.check_reviewer_stuck", new_callable=AsyncMock,
                   return_value=False), \
             mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": session.session_id,
            })

        data = _parse(result)
        assert data["success"] is True
        assert session.session_id in ACTIVE_SESSIONS

    @pytest.mark.asyncio
    async def test_by_agent_id_found(self, mock_server, mock_context_agent):
        """Find sessions by agent_id."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session, ACTIVE_SESSIONS

        session = _make_session(
            paused_id="agent-active", reviewer_id="agent-reviewer",
            phase=DialecticPhase.RESOLVED,
        )
        ACTIVE_SESSIONS[session.session_id] = session

        # Mock disk session listing to return empty (only test in-memory)
        with mock_context_agent, \
             patch(f"{DIALECTIC}.SESSION_STORAGE_DIR") as mock_dir:
            mock_dir.mkdir = MagicMock()
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = []  # No disk sessions
            result = await handle_get_dialectic_session({
                "agent_id": "agent-active",
            })

        data = _parse(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_by_agent_id_not_registered(self, mock_server, mock_context_agent):
        """Returns error if agent_id is not in metadata."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        with mock_context_agent:
            result = await handle_get_dialectic_session({
                "agent_id": "nonexistent-agent",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_by_agent_id_no_sessions(self, mock_server, mock_context_agent):
        """Returns error when agent exists but has no sessions."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        # Mock disk session listing to return empty
        with mock_context_agent, \
             patch(f"{DIALECTIC}.SESSION_STORAGE_DIR") as mock_dir:
            mock_dir.mkdir = MagicMock()
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = []  # No disk sessions
            result = await handle_get_dialectic_session({
                "agent_id": "agent-active",
            })

        data = _parse(result)
        assert data["success"] is False
        assert "no dialectic sessions" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_exception_returns_error(self, mock_context_agent):
        """General exceptions are caught and returned as errors."""
        from src.mcp_handlers.dialectic import handle_get_dialectic_session

        with patch(f"{DIALECTIC}.ACTIVE_SESSIONS",
                   new_callable=lambda: MagicMock(get=MagicMock(side_effect=RuntimeError("boom")))), \
             mock_context_agent:
            result = await handle_get_dialectic_session({
                "session_id": "any",
            })

        data = _parse(result)
        assert data["success"] is False


# ============================================================================
# 7. check_reviewer_stuck (helper function)
# ============================================================================

class TestCheckReviewerStuck:
    """Tests for check_reviewer_stuck helper."""

    @pytest.mark.asyncio
    async def test_reviewer_not_found_is_stuck(self, mock_server):
        """Reviewer not in metadata is considered stuck (ANTITHESIS phase)."""
        from src.mcp_handlers.dialectic import check_reviewer_stuck

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        session.reviewer_agent_id = "nonexistent-reviewer"

        result = await check_reviewer_stuck(session)
        assert result is True

    @pytest.mark.asyncio
    async def test_paused_reviewer_is_stuck(self, mock_server):
        """Paused reviewer is considered stuck (ANTITHESIS phase)."""
        from src.mcp_handlers.dialectic import check_reviewer_stuck

        mock_server.agent_metadata["agent-reviewer"] = _make_agent_meta(status="paused")
        session = _make_session(phase=DialecticPhase.ANTITHESIS)

        result = await check_reviewer_stuck(session)
        assert result is True

    @pytest.mark.asyncio
    async def test_active_recent_reviewer_not_stuck(self, mock_server):
        """Active reviewer with recent thesis is not stuck."""
        from src.mcp_handlers.dialectic import check_reviewer_stuck
        from src.dialectic_protocol import DialecticMessage

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        # Add a recent thesis to transcript so get_thesis_timestamp() returns now
        session.transcript.append(DialecticMessage(
            phase="thesis", agent_id="agent-paused",
            timestamp=datetime.now().isoformat(),
            reasoning="test thesis"
        ))

        result = await check_reviewer_stuck(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_active_old_session_is_stuck(self, mock_server):
        """Active reviewer but thesis submitted >2h ago is stuck."""
        from src.mcp_handlers.dialectic import check_reviewer_stuck
        from src.dialectic_protocol import DialecticMessage

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        # Add an old thesis to transcript (>2h threshold)
        session.transcript.append(DialecticMessage(
            phase="thesis", agent_id="agent-paused",
            timestamp=(datetime.now() - timedelta(hours=3)).isoformat(),
            reasoning="test thesis"
        ))

        result = await check_reviewer_stuck(session)
        assert result is True


# ============================================================================
# 8. _get_dialectic_next_steps (helper function)
# ============================================================================

class TestGetDialecticNextSteps:
    """Tests for _get_dialectic_next_steps helper."""

    def test_resume_steps(self):
        from src.mcp_handlers.dialectic import _get_dialectic_next_steps
        steps = _get_dialectic_next_steps("RESUME")
        assert len(steps) == 3
        assert any("resume" in s.lower() for s in steps)

    def test_cooldown_steps(self):
        from src.mcp_handlers.dialectic import _get_dialectic_next_steps
        steps = _get_dialectic_next_steps("COOLDOWN")
        assert len(steps) == 3
        assert any("pause" in s.lower() for s in steps)

    def test_escalate_steps(self):
        from src.mcp_handlers.dialectic import _get_dialectic_next_steps
        steps = _get_dialectic_next_steps("ESCALATE")
        assert len(steps) == 3
        assert any("human" in s.lower() for s in steps)

    def test_unknown_defaults_to_escalate(self):
        from src.mcp_handlers.dialectic import _get_dialectic_next_steps
        steps = _get_dialectic_next_steps("SOMETHING_ELSE")
        assert len(steps) == 3
        # Falls through to ESCALATE branch
        assert any("human" in s.lower() for s in steps)
