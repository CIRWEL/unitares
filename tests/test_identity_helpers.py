"""
Tests for pure helper functions in src/mcp_handlers/identity_v2.py.

Tests _generate_agent_id and _get_date_context (pure date/string functions).
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.identity_v2 import (
    _generate_agent_id,
    _get_date_context,
    _derive_session_key,
)


# ============================================================================
# _get_date_context
# ============================================================================

class TestGetDateContext:

    def test_returns_dict(self):
        result = _get_date_context()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = _get_date_context()
        for key in ['full', 'short', 'compact', 'iso', 'iso_utc', 'year', 'month', 'weekday']:
            assert key in result, f"Missing key: {key}"

    def test_year_is_current(self):
        result = _get_date_context()
        assert result['year'] == datetime.now().strftime('%Y')

    def test_short_format(self):
        result = _get_date_context()
        # Should be YYYY-MM-DD
        assert len(result['short']) == 10
        assert result['short'][4] == '-'

    def test_compact_format(self):
        result = _get_date_context()
        # Should be YYYYMMDD
        assert len(result['compact']) == 8
        assert result['compact'].isdigit()

    def test_iso_utc_ends_with_z(self):
        result = _get_date_context()
        assert result['iso_utc'].endswith('Z')

    def test_full_contains_month_name(self):
        result = _get_date_context()
        months = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December']
        assert any(m in result['full'] for m in months)

    def test_weekday_is_valid(self):
        result = _get_date_context()
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        assert result['weekday'] in days


# ============================================================================
# _generate_agent_id
# ============================================================================

class TestGenerateAgentId:

    def test_with_model_type_basic(self):
        result = _generate_agent_id(model_type="claude-opus-4-5")
        assert "Claude_Opus_4_5" in result
        assert datetime.now().strftime("%Y%m%d") in result

    def test_with_model_type_gemini(self):
        result = _generate_agent_id(model_type="gemini-pro")
        assert "Gemini_Pro" in result

    def test_with_model_type_dots(self):
        result = _generate_agent_id(model_type="gpt.4.turbo")
        assert "Gpt_4_Turbo" in result

    def test_with_model_type_underscores(self):
        result = _generate_agent_id(model_type="llama_3_70b")
        assert "Llama_3_70B" in result or "Llama_3_70b" in result

    def test_model_type_stripped(self):
        result = _generate_agent_id(model_type="  claude-opus-4-5  ")
        assert "Claude_Opus_4_5" in result

    def test_with_client_hint(self):
        result = _generate_agent_id(client_hint="cursor")
        assert result.startswith("cursor_")
        assert datetime.now().strftime("%Y%m%d") in result

    def test_client_hint_lowercased(self):
        result = _generate_agent_id(client_hint="Cursor")
        assert result.startswith("cursor_")

    def test_model_type_takes_priority(self):
        result = _generate_agent_id(model_type="claude-opus-4-5", client_hint="cursor")
        assert "Claude_Opus_4_5" in result
        assert "cursor" not in result

    def test_fallback_mcp(self):
        result = _generate_agent_id()
        assert result.startswith("mcp_")
        assert datetime.now().strftime("%Y%m%d") in result

    def test_unknown_client_hint_falls_back(self):
        result = _generate_agent_id(client_hint="unknown")
        assert result.startswith("mcp_")

    def test_empty_client_hint_falls_back(self):
        result = _generate_agent_id(client_hint="")
        assert result.startswith("mcp_")

    def test_none_model_with_valid_client(self):
        result = _generate_agent_id(model_type=None, client_hint="vscode")
        assert result.startswith("vscode_")

    def test_returns_string(self):
        result = _generate_agent_id()
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================================
# _derive_session_key (deprecated sync wrapper)
# ============================================================================

class TestDeriveSessionKey:

    def test_explicit_client_session_id(self):
        result = _derive_session_key({"client_session_id": "my-session-123"})
        assert result == "my-session-123"

    def test_explicit_takes_priority(self):
        """client_session_id should take priority over context."""
        result = _derive_session_key({"client_session_id": "explicit-id"})
        assert result == "explicit-id"

    def test_empty_client_session_id_falls_through(self):
        """Empty string is falsy, should fall through."""
        result = _derive_session_key({"client_session_id": ""})
        # Should not be empty string, should fall through to other methods
        assert result != ""

    def test_none_client_session_id_falls_through(self):
        result = _derive_session_key({"client_session_id": None})
        assert result is not None
        assert len(result) > 0

    def test_no_args_returns_stdio_fallback(self):
        """With no context set, should fall through to stdio fallback."""
        import os
        result = _derive_session_key({})
        assert result == f"stdio:{os.getpid()}"

    def test_mcp_session_id_from_context(self):
        """When mcp_session_id is set in context, use it."""
        from src.mcp_handlers.context import set_mcp_session_id, reset_mcp_session_id
        token = set_mcp_session_id("mcp-session-abc123")
        try:
            result = _derive_session_key({})
            assert result == "mcp:mcp-session-abc123"
        finally:
            reset_mcp_session_id(token)

    def test_context_session_key_fallback(self):
        """When context session_key is set, use it as fallback."""
        from src.mcp_handlers.context import set_session_context, reset_session_context
        token = set_session_context(session_key="ctx-key-456")
        try:
            result = _derive_session_key({})
            assert result == "ctx-key-456"
        finally:
            reset_session_context(token)

    def test_returns_string(self):
        result = _derive_session_key({})
        assert isinstance(result, str)
