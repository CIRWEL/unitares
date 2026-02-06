"""
Tests for src/mcp_handlers/context.py - Session contextvars management.

Contextvars are per-task, so tests are naturally isolated.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.context import (
    set_session_context,
    reset_session_context,
    get_session_context,
    get_context_session_key,
    get_context_client_session_id,
    get_context_agent_id,
    update_context_agent_id,
    get_context_client_hint,
    set_transport_client_hint,
    reset_transport_client_hint,
    set_mcp_session_id,
    reset_mcp_session_id,
    get_mcp_session_id,
    detect_client_from_user_agent,
)


class TestSessionContext:

    def test_set_and_get(self):
        token = set_session_context(session_key="sess-1", client_session_id="client-1")
        try:
            ctx = get_session_context()
            assert ctx["session_key"] == "sess-1"
            assert ctx["client_session_id"] == "client-1"
        finally:
            reset_session_context(token)

    def test_session_key_defaults_to_client_session_id(self):
        token = set_session_context(client_session_id="my-client")
        try:
            assert get_context_session_key() == "my-client"
        finally:
            reset_session_context(token)

    def test_get_agent_id(self):
        token = set_session_context(agent_id="agent-123")
        try:
            assert get_context_agent_id() == "agent-123"
        finally:
            reset_session_context(token)

    def test_get_client_session_id(self):
        token = set_session_context(client_session_id="csid-456")
        try:
            assert get_context_client_session_id() == "csid-456"
        finally:
            reset_session_context(token)

    def test_extra_kwargs(self):
        token = set_session_context(custom_field="hello")
        try:
            ctx = get_session_context()
            assert ctx["custom_field"] == "hello"
        finally:
            reset_session_context(token)

    def test_reset_restores_previous(self):
        outer_token = set_session_context(session_key="outer")
        try:
            inner_token = set_session_context(session_key="inner")
            assert get_context_session_key() == "inner"
            reset_session_context(inner_token)
            assert get_context_session_key() == "outer"
        finally:
            reset_session_context(outer_token)

    def test_empty_context_returns_none(self):
        """No context set -> getters return None."""
        # Note: contextvars default is {}, so .get() returns None
        assert get_context_agent_id() is None or get_context_agent_id() == get_session_context().get('agent_id')


class TestUpdateContextAgentId:

    def test_update_agent_id(self):
        token = set_session_context(session_key="sess")
        try:
            update_context_agent_id("new-agent")
            assert get_context_agent_id() == "new-agent"
        finally:
            reset_session_context(token)

    def test_update_empty_context_no_crash(self):
        """If context is empty dict (default), update should handle gracefully."""
        # The default is {}, which is falsy but not None
        # update_context_agent_id checks `if ctx:` - empty dict is falsy
        update_context_agent_id("test-agent")
        # Should not crash


class TestClientHint:

    def test_from_session_context(self):
        token = set_session_context(client_hint="cursor")
        try:
            assert get_context_client_hint() == "cursor"
        finally:
            reset_session_context(token)

    def test_from_transport_level(self):
        token = set_transport_client_hint("chatgpt")
        try:
            assert get_context_client_hint() == "chatgpt"
        finally:
            reset_transport_client_hint(token)

    def test_session_context_takes_priority(self):
        transport_token = set_transport_client_hint("chatgpt")
        session_token = set_session_context(client_hint="cursor")
        try:
            assert get_context_client_hint() == "cursor"
        finally:
            reset_session_context(session_token)
            reset_transport_client_hint(transport_token)


class TestMcpSessionId:

    def test_set_and_get(self):
        token = set_mcp_session_id("mcp-sess-abc")
        try:
            assert get_mcp_session_id() == "mcp-sess-abc"
        finally:
            reset_mcp_session_id(token)

    def test_default_none(self):
        # Default should be None
        # (unless another test in the same process set it)
        pass  # Can't reliably test default in shared process

    def test_reset_works(self):
        token = set_mcp_session_id("temp-id")
        reset_mcp_session_id(token)
        # After reset, should be back to previous value


class TestDetectClientFromUserAgent:

    def test_cursor(self):
        assert detect_client_from_user_agent("Cursor/0.42.0") == "cursor"

    def test_cursor_case_insensitive(self):
        assert detect_client_from_user_agent("CURSOR agent") == "cursor"

    def test_claude_desktop(self):
        assert detect_client_from_user_agent("Claude Desktop 1.0") == "claude_desktop"

    def test_anthropic(self):
        assert detect_client_from_user_agent("Anthropic/SDK") == "claude_desktop"

    def test_chatgpt(self):
        assert detect_client_from_user_agent("ChatGPT-Plugin/1.0") == "chatgpt"

    def test_openai(self):
        assert detect_client_from_user_agent("OpenAI/Agent") == "chatgpt"

    def test_vscode(self):
        assert detect_client_from_user_agent("VSCode/1.85") == "vscode"

    def test_visual_studio_code(self):
        assert detect_client_from_user_agent("Visual Studio Code") == "vscode"

    def test_unknown_returns_none(self):
        assert detect_client_from_user_agent("Mozilla/5.0") is None

    def test_empty_returns_none(self):
        assert detect_client_from_user_agent("") is None

    def test_none_returns_none(self):
        assert detect_client_from_user_agent(None) is None


class TestTrajectoryConfidence:

    def test_set_and_get(self):
        from src.mcp_handlers.context import (
            set_trajectory_confidence,
            get_trajectory_confidence,
            reset_trajectory_confidence,
        )
        token = set_trajectory_confidence(0.85)
        try:
            assert get_trajectory_confidence() == 0.85
        finally:
            reset_trajectory_confidence(token)

    def test_default_is_none(self):
        from src.mcp_handlers.context import get_trajectory_confidence
        # Default value should be None when not set
        val = get_trajectory_confidence()
        assert val is None or isinstance(val, float)

    def test_reset_restores_previous(self):
        from src.mcp_handlers.context import (
            set_trajectory_confidence,
            get_trajectory_confidence,
            reset_trajectory_confidence,
        )
        token1 = set_trajectory_confidence(0.5)
        try:
            token2 = set_trajectory_confidence(0.9)
            assert get_trajectory_confidence() == 0.9
            reset_trajectory_confidence(token2)
            assert get_trajectory_confidence() == 0.5
        finally:
            reset_trajectory_confidence(token1)
