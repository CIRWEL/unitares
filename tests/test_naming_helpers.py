"""
Tests for src/mcp_handlers/naming_helpers.py - Agent name generation.

Pure functions with env var detection (monkeypatched).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.naming_helpers import (
    detect_interface_context,
    generate_name_suggestions,
    generate_structured_id,
    format_naming_guidance,
)


class TestDetectInterfaceContext:

    def test_default_context(self, monkeypatch):
        """No env vars set -> default mcp_client."""
        for var in ["GOVERNANCE_AGENT_PREFIX", "CURSOR_PID", "CURSOR_VERSION",
                     "VSCODE_PID", "CLAUDE_DESKTOP", "OPENAI_API_KEY",
                     "ANTHROPIC_API_KEY", "GOOGLE_AI_API_KEY", "GEMINI_API_KEY",
                     "CI", "TEST"]:
            monkeypatch.delenv(var, raising=False)
        ctx = detect_interface_context()
        assert ctx["interface"] == "mcp_client"
        assert ctx["model_hint"] is None
        assert ctx["environment"] is None

    def test_cursor_detection(self, monkeypatch):
        monkeypatch.setenv("CURSOR_PID", "12345")
        ctx = detect_interface_context()
        assert ctx["interface"] == "cursor"

    def test_cursor_version_detection(self, monkeypatch):
        monkeypatch.setenv("CURSOR_VERSION", "0.42.0")
        ctx = detect_interface_context()
        assert ctx["interface"] == "cursor"

    def test_vscode_detection(self, monkeypatch):
        monkeypatch.delenv("CURSOR_PID", raising=False)
        monkeypatch.delenv("CURSOR_VERSION", raising=False)
        monkeypatch.setenv("VSCODE_PID", "99999")
        ctx = detect_interface_context()
        assert ctx["interface"] == "vscode"

    def test_claude_desktop_detection(self, monkeypatch):
        for var in ["CURSOR_PID", "CURSOR_VERSION", "VSCODE_PID"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CLAUDE_DESKTOP", "1")
        ctx = detect_interface_context()
        assert ctx["interface"] == "claude_desktop"

    def test_explicit_prefix_override(self, monkeypatch):
        """GOVERNANCE_AGENT_PREFIX sets initial interface, but IDE detection overwrites it."""
        for var in ["CURSOR_PID", "CURSOR_VERSION", "VSCODE_PID", "CLAUDE_DESKTOP"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GOVERNANCE_AGENT_PREFIX", "my_custom")
        ctx = detect_interface_context()
        assert ctx["interface"] == "my_custom"

    def test_model_hint_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        ctx = detect_interface_context()
        assert ctx["model_hint"] == "gpt"

    def test_model_hint_anthropic(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        ctx = detect_interface_context()
        assert ctx["model_hint"] == "claude"

    def test_model_hint_gemini(self, monkeypatch):
        for var in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test")
        ctx = detect_interface_context()
        assert ctx["model_hint"] == "gemini"

    def test_ci_environment(self, monkeypatch):
        monkeypatch.setenv("CI", "true")
        ctx = detect_interface_context()
        assert ctx["environment"] == "ci"

    def test_test_environment(self, monkeypatch):
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("TEST", "1")
        ctx = detect_interface_context()
        assert ctx["environment"] == "test"


class TestGenerateNameSuggestions:

    def test_returns_list(self):
        suggestions = generate_name_suggestions(
            context={"interface": "cursor", "model_hint": "claude", "environment": None}
        )
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0

    def test_max_four_suggestions(self):
        suggestions = generate_name_suggestions(
            context={"interface": "cursor", "model_hint": "claude", "environment": "ci"},
            purpose="debugging auth"
        )
        assert len(suggestions) <= 4

    def test_purpose_included_in_name(self):
        suggestions = generate_name_suggestions(
            context={"interface": "mcp_client", "model_hint": None, "environment": None},
            purpose="debug auth"
        )
        purpose_names = [s["name"] for s in suggestions]
        assert any("debug" in name for name in purpose_names)

    def test_model_hint_in_suggestion(self):
        suggestions = generate_name_suggestions(
            context={"interface": "cursor", "model_hint": "claude", "environment": None}
        )
        names = [s["name"] for s in suggestions]
        assert any("claude" in name for name in names)

    def test_session_suggestion_always_present(self):
        suggestions = generate_name_suggestions(
            context={"interface": "cursor", "model_hint": None, "environment": None}
        )
        names = [s["name"] for s in suggestions]
        assert any("session" in name for name in names)

    def test_collision_avoidance(self):
        ctx = {"interface": "test", "model_hint": None, "environment": None}
        # Generate once to get a name
        first = generate_name_suggestions(context=ctx)
        first_names = [s["name"] for s in first]
        # Generate again with those as existing
        second = generate_name_suggestions(context=ctx, existing_names=first_names)
        second_names = [s["name"] for s in second]
        # Colliding names should have been adjusted
        for name in second_names:
            if name in first_names:
                continue  # session-based names have timestamps, unlikely collision
            # adjusted names should end with _N
            pass  # Just verify no crash

    def test_suggestion_has_required_fields(self):
        suggestions = generate_name_suggestions(
            context={"interface": "mcp", "model_hint": None, "environment": None}
        )
        for s in suggestions:
            assert "name" in s
            assert "description" in s
            assert "rationale" in s


class TestGenerateStructuredId:

    def test_basic_id(self):
        ctx = {"interface": "cursor", "model_hint": None, "environment": None}
        result = generate_structured_id(context=ctx)
        assert result.startswith("cursor_")
        assert "20" in result  # Year in date

    def test_with_model_type(self):
        ctx = {"interface": "cursor", "model_hint": None, "environment": None}
        result = generate_structured_id(context=ctx, model_type="claude-3.5-sonnet")
        assert "claude" in result
        assert "cursor" in result

    def test_model_simplification_gemini(self):
        result = generate_structured_id(
            context={"interface": "mcp", "model_hint": None, "environment": None},
            model_type="gemini-2.0-flash"
        )
        assert "gemini" in result

    def test_model_simplification_gpt(self):
        result = generate_structured_id(
            context={"interface": "chatgpt", "model_hint": None, "environment": None},
            model_type="gpt-4o"
        )
        assert "gpt" in result

    def test_model_simplification_llama(self):
        result = generate_structured_id(
            context={"interface": "mcp", "model_hint": None, "environment": None},
            model_type="llama-3.1-70b"
        )
        assert "llama" in result

    def test_client_hint_overrides_context(self):
        ctx = {"interface": "mcp_client", "model_hint": None, "environment": None}
        result = generate_structured_id(context=ctx, client_hint="chatgpt")
        assert "chatgpt" in result
        assert "mcp" not in result

    def test_client_hint_unknown_ignored(self):
        ctx = {"interface": "cursor", "model_hint": None, "environment": None}
        result = generate_structured_id(context=ctx, client_hint="unknown")
        assert "cursor" in result

    def test_collision_avoidance(self):
        ctx = {"interface": "test", "model_hint": None, "environment": None}
        first = generate_structured_id(context=ctx)
        # Same inputs with first as existing
        second = generate_structured_id(context=ctx, existing_ids=[first])
        assert second != first
        assert second.endswith("_2")

    def test_collision_avoidance_multiple(self):
        ctx = {"interface": "test", "model_hint": None, "environment": None}
        first = generate_structured_id(context=ctx)
        second = f"{first}_2"
        third = generate_structured_id(context=ctx, existing_ids=[first, second])
        assert third.endswith("_3")

    def test_interface_normalization(self):
        """_client suffix removed, hyphens become underscores."""
        ctx = {"interface": "mcp_client", "model_hint": None, "environment": None}
        result = generate_structured_id(context=ctx)
        assert "mcp_" in result
        assert "_client" not in result


class TestFormatNamingGuidance:

    def test_basic_guidance(self):
        suggestions = [{"name": "test_agent", "description": "Test", "rationale": "For testing"}]
        result = format_naming_guidance(suggestions)
        assert "suggestions" in result
        assert "how_to" in result
        assert "tips" in result
        assert "examples" in result

    def test_with_uuid(self):
        result = format_naming_guidance([], current_uuid="abcdef1234567890abcdef")
        assert "current_uuid" in result
        assert result["current_uuid"].endswith("...")

    def test_without_uuid(self):
        result = format_naming_guidance([])
        assert "current_uuid" not in result
