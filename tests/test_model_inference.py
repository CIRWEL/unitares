"""
Comprehensive tests for src/mcp_handlers/model_inference.py

Tests the handle_call_model tool handler and create_model_inference_client
factory function with fully mocked external API calls (OpenAI SDK).

IMPORTANT: The privacy parameter defaults to "local", which routes to Ollama
before any provider-specific logic. Tests for non-Ollama providers must
explicitly set privacy="cloud" or privacy="auto" to bypass the Ollama shortcut.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any

import pytest

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _parse_text_content(result):
    """
    Parse a TextContent or list-of-TextContent response from a tool handler.
    Returns the parsed JSON dict from the text field.
    """
    if isinstance(result, list):
        item = result[0]
    else:
        item = result
    # TextContent has a .text attribute that is a JSON string
    text = item.text if hasattr(item, "text") else str(item)
    return json.loads(text)


def _make_mock_response(content="Test response", tokens=42, model="gemini-flash"):
    """Create a mock OpenAI-style chat completion response."""
    mock_message = MagicMock()
    mock_message.content = content

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.total_tokens = tokens

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage
    mock_response.model = model

    return mock_response


# =============================================================================
# Tests: OpenAI SDK unavailable
# =============================================================================

class TestOpenAIUnavailable:
    """Tests when OpenAI SDK is not installed."""

    @pytest.mark.asyncio
    async def test_returns_error_when_openai_not_available(self):
        """handle_call_model returns error when OPENAI_AVAILABLE is False."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({"prompt": "test"})

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "OpenAI SDK required" in parsed["error"]
        assert parsed.get("error_code") == "DEPENDENCY_MISSING"


# =============================================================================
# Tests: Missing prompt
# =============================================================================

class TestMissingPrompt:
    """Tests for missing required arguments."""

    @pytest.mark.asyncio
    async def test_returns_error_when_prompt_missing(self):
        """handle_call_model returns error when prompt is not provided."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({})

        parsed = _parse_text_content(result)
        assert parsed["success"] is False


# =============================================================================
# Tests: Provider routing - Ollama (local / privacy=local)
# =============================================================================

class TestOllamaRouting:
    """Tests for Ollama (local) provider routing.

    Note: privacy defaults to "local", so Ollama is the default path
    unless privacy is explicitly set to something else.
    """

    @pytest.mark.asyncio
    async def test_privacy_local_routes_to_ollama(self):
        """privacy=local (the default) routes to Ollama."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="ollama response", model="llama3:70b"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "privacy": "local",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "ollama"
        assert parsed["response"] == "ollama response"

    @pytest.mark.asyncio
    async def test_default_privacy_routes_to_ollama(self):
        """Default privacy (no explicit value) routes to Ollama since default is 'local'."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="default ollama", model="llama3:70b"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "ollama"

    @pytest.mark.asyncio
    async def test_provider_ollama_routes_correctly(self):
        """provider=ollama routes to Ollama endpoint."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="ollama direct", model="llama3:70b"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance) as mock_openai:
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "ollama",
                "privacy": "cloud",  # must bypass default privacy=local
            })

        # Verify OpenAI was created with Ollama endpoint
        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args
        assert "localhost:11434" in call_kwargs[1]["base_url"]
        assert call_kwargs[1]["api_key"] == "ollama"

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "ollama"

    @pytest.mark.asyncio
    async def test_ollama_uses_default_model_for_auto(self):
        """Ollama with model=auto defaults to llama3:70b."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="llama3:70b"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "ollama",
                "model": "auto",
            })

        # Verify model passed to create
        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "llama3:70b"

    @pytest.mark.asyncio
    async def test_ollama_preserves_specified_model(self):
        """Ollama preserves a specific model name when not 'auto' or 'llama-3.1-8b'."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="my-custom-model"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "privacy": "local",
                "model": "my-custom-model",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "my-custom-model"


# =============================================================================
# Tests: Provider routing - Hugging Face
# =============================================================================

class TestHuggingFaceRouting:
    """Tests for Hugging Face Inference Provider routing.

    All HF tests must use privacy="cloud" to bypass the default
    privacy="local" Ollama shortcut.
    """

    @pytest.mark.asyncio
    async def test_hf_provider_requires_token(self):
        """HF provider returns error when no token is set."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch.dict("os.environ", {}, clear=True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "hf",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "HF_TOKEN" in parsed["error"]
        assert parsed.get("error_code") == "MISSING_CONFIG"

    @pytest.mark.asyncio
    async def test_hf_provider_with_token(self):
        """HF provider works when token is set."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="hf response", model="deepseek-ai/DeepSeek-R1:fastest"
        )

        env = {"HF_TOKEN": "hf_test_token_123"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance) as mock_openai, \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "hf",
                "privacy": "cloud",
            })

        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args[1]
        assert "router.huggingface.co" in call_kwargs["base_url"]
        assert call_kwargs["api_key"] == "hf_test_token_123"

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "huggingface"

    @pytest.mark.asyncio
    async def test_hf_strips_hf_prefix_from_model(self):
        """HF provider strips 'hf:' prefix from model name."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"HF_TOKEN": "hf_test_token"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "hf",
                "privacy": "cloud",
                "model": "hf:my-org/my-model",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        # Should strip "hf:" and add ":fastest"
        assert call_kwargs["model"] == "my-org/my-model:fastest"

    @pytest.mark.asyncio
    async def test_hf_model_with_colon_not_doubled(self):
        """HF provider does not add :fastest if model already has a colon."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"HF_TOKEN": "hf_test_token"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "hf",
                "privacy": "cloud",
                "model": "deepseek-ai/DeepSeek-R1:cheapest",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "deepseek-ai/DeepSeek-R1:cheapest"

    @pytest.mark.asyncio
    async def test_hf_auto_detection_by_model_prefix(self):
        """Auto-detects HF provider when model starts with deepseek-ai/."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"HF_TOKEN": "hf_test_token"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "model": "deepseek-ai/DeepSeek-V2",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "huggingface"

    @pytest.mark.asyncio
    async def test_hf_default_model_for_auto(self):
        """HF with model=auto defaults to deepseek-ai/DeepSeek-R1:fastest."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"HF_TOKEN": "hf_test_token"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "hf",
                "privacy": "cloud",
                "model": "auto",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "deepseek-ai/DeepSeek-R1:fastest"


# =============================================================================
# Tests: Provider routing - Gemini
# =============================================================================

class TestGeminiRouting:
    """Tests for Google Gemini provider routing.

    All Gemini tests must use privacy="cloud" to bypass default privacy="local".
    """

    @pytest.mark.asyncio
    async def test_gemini_provider_requires_api_key(self):
        """Gemini provider returns error when no API key is set."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch.dict("os.environ", {}, clear=True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "gemini",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "GOOGLE_AI_API_KEY" in parsed["error"]

    @pytest.mark.asyncio
    async def test_gemini_provider_with_api_key(self):
        """Gemini provider works with API key."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="gemini response", model="gemini-flash"
        )

        env = {"GOOGLE_AI_API_KEY": "test_google_key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance) as mock_openai, \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "gemini",
                "privacy": "cloud",
            })

        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["api_key"] == "test_google_key"

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "gemini-direct"

    @pytest.mark.asyncio
    async def test_gemini_auto_detection_by_model_prefix(self):
        """Auto-detects Gemini provider when model starts with 'gemini'."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="gemini-pro"
        )

        env = {"GOOGLE_AI_API_KEY": "test_google_key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "model": "gemini-pro",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_gemini_defaults_to_flash_for_auto_model(self):
        """Gemini with model=auto defaults to gemini-flash."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"GOOGLE_AI_API_KEY": "test_key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "gemini",
                "privacy": "cloud",
                "model": "auto",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gemini-flash"


# =============================================================================
# Tests: Provider routing - Auto selection
# =============================================================================

class TestAutoProviderSelection:
    """Tests for auto provider selection logic.

    These tests use privacy="cloud" + provider="auto" to test the full
    auto-selection logic (Ollama check via socket, fallback chain).
    """

    @pytest.mark.asyncio
    async def test_auto_selects_ollama_when_available(self):
        """Auto provider prefers Ollama when it is running."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="gemma3:27b"
        )

        # Mock socket to simulate Ollama running
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 0  # Connected successfully

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch("socket.socket", return_value=mock_socket):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "privacy": "cloud",
                "model": "auto",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "ollama"

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_gemini_when_ollama_down(self):
        """Auto provider falls back to Gemini when Ollama is not running."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="gemini-flash"
        )

        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 1  # Connection refused

        env = {"GOOGLE_AI_API_KEY": "test_key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch("socket.socket", return_value=mock_socket), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "privacy": "cloud",
                "model": "auto",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "gemini-direct"

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_hf_when_no_google_key(self):
        """Auto provider falls back to HF when no Ollama and no Google key."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="deepseek-ai/DeepSeek-R1:fastest"
        )

        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 1  # No Ollama

        # Only set HF_TOKEN, ensure Google keys are absent
        env = {"HF_TOKEN": "hf_test_token"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch("socket.socket", return_value=mock_socket), \
             patch.dict("os.environ", env, clear=True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "privacy": "cloud",
                "model": "auto",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "huggingface"

    @pytest.mark.asyncio
    async def test_auto_returns_error_when_nothing_available(self):
        """Auto provider returns error when no providers are available."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 1  # No Ollama

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("socket.socket", return_value=mock_socket), \
             patch.dict("os.environ", {}, clear=True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "auto",
                "privacy": "cloud",
                "model": "auto",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "No provider available" in parsed["error"]


# =============================================================================
# Tests: Default/other provider (ngrok/OpenAI endpoint)
# =============================================================================

class TestDefaultProvider:
    """Tests for default (ngrok/OpenAI) provider routing.

    These reach the final else branch in provider routing.
    Must use privacy="cloud" to skip the Ollama shortcut.
    """

    @pytest.mark.asyncio
    async def test_default_provider_requires_api_key(self):
        """Default provider returns error when no API key set."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch.dict("os.environ", {}, clear=True):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "openai",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "NGROK_API_KEY" in parsed["error"] or "OPENAI_API_KEY" in parsed["error"]

    @pytest.mark.asyncio
    async def test_default_provider_with_api_key(self):
        """Default provider works with API key."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="openai response", model="gpt-4"
        )

        env = {"OPENAI_API_KEY": "sk-test-key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "openai",
                "privacy": "cloud",
                "model": "gpt-4",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["routed_via"] == "direct"

    @pytest.mark.asyncio
    async def test_default_provider_defaults_model_to_gemini_flash(self):
        """Default provider with model=auto defaults to gemini-flash."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"OPENAI_API_KEY": "sk-test-key"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Hello",
                "provider": "openai",
                "privacy": "cloud",
                "model": "auto",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gemini-flash"


# =============================================================================
# Tests: Response content and energy cost
# =============================================================================

class TestResponseContent:
    """Tests for response content, tokens, and energy cost."""

    @pytest.mark.asyncio
    async def test_response_includes_all_fields(self):
        """Successful response includes all expected fields."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            content="The answer is 42", tokens=100, model="gemini-flash"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "What is the meaning of life?",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["response"] == "The answer is 42"
        assert parsed["tokens_used"] == 100
        assert "model_used" in parsed
        assert "energy_cost" in parsed
        assert "routed_via" in parsed
        assert "task_type" in parsed
        assert "message" in parsed

    @pytest.mark.asyncio
    async def test_energy_cost_free_tier_flash(self):
        """Free tier models (flash) get low energy cost."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="gemini-flash"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "model": "gemini-flash",
            })

        parsed = _parse_text_content(result)
        assert parsed["energy_cost"] == 0.01

    @pytest.mark.asyncio
    async def test_energy_cost_free_tier_llama(self):
        """Free tier models (llama) get low energy cost."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="llama3:70b"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "model": "llama-3.1-8b",
            })

        parsed = _parse_text_content(result)
        assert parsed["energy_cost"] == 0.01

    @pytest.mark.asyncio
    async def test_energy_cost_pro_tier(self):
        """Pro tier models get medium energy cost."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="gemini-pro"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "model": "gemini-pro",
            })

        parsed = _parse_text_content(result)
        assert parsed["energy_cost"] == 0.02

    @pytest.mark.asyncio
    async def test_energy_cost_default_tier(self):
        """Unknown models get default energy cost."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response(
            model="custom-model"
        )

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "model": "custom-model",
            })

        parsed = _parse_text_content(result)
        assert parsed["energy_cost"] == 0.03

    @pytest.mark.asyncio
    async def test_handles_missing_usage_attribute(self):
        """Handles responses without usage attribute gracefully."""
        mock_response = _make_mock_response()
        del mock_response.usage  # Remove usage attribute

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        assert parsed["tokens_used"] == 0


# =============================================================================
# Tests: Parameter handling
# =============================================================================

class TestParameterHandling:
    """Tests for optional parameter parsing."""

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        """Default parameters are applied when not specified."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        # Verify parameters passed to chat.completions.create
        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 500
        assert call_kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_custom_parameters(self):
        """Custom parameters override defaults."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "max_tokens": "1000",
                "temperature": "0.3",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 1000
        assert call_kwargs["temperature"] == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_task_type_included_in_response(self):
        """task_type parameter is included in response."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "task_type": "analysis",
            })

        parsed = _parse_text_content(result)
        assert parsed["task_type"] == "analysis"

    @pytest.mark.asyncio
    async def test_prompt_passed_to_messages(self):
        """The prompt is correctly passed in messages to the API."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "Analyze this code for bugs",
                "provider": "ollama",
            })

        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        assert call_kwargs["messages"] == [{"role": "user", "content": "Analyze this code for bugs"}]


# =============================================================================
# Tests: Error handling
# =============================================================================

class TestErrorHandling:
    """Tests for API call error handling."""

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Timeout errors get specific error code."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Request timeout exceeded")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert parsed.get("error_code") == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Rate limit errors get specific error code."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Rate limit exceeded")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert parsed.get("error_code") == "RATE_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_model_not_found_error(self):
        """Model not found errors get specific error code."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Model not found: bad-model")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "model": "bad-model",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert parsed.get("error_code") == "MODEL_NOT_AVAILABLE"

    @pytest.mark.asyncio
    async def test_invalid_model_error(self):
        """'invalid' in error message triggers MODEL_NOT_AVAILABLE."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("invalid model specified")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert parsed.get("error_code") == "MODEL_NOT_AVAILABLE"

    @pytest.mark.asyncio
    async def test_generic_error(self):
        """Generic errors get INFERENCE_ERROR code."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Something went wrong")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert parsed.get("error_code") == "INFERENCE_ERROR"

    @pytest.mark.asyncio
    async def test_error_includes_recovery_info(self):
        """Error responses include recovery guidance."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Something broke")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        assert "recovery" in parsed

    @pytest.mark.asyncio
    async def test_error_includes_model_details(self):
        """Error responses include model/base_url/task_type details."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = Exception("Something broke")

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "task_type": "analysis",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is False
        # The error details include model_requested, base_url, task_type
        assert "task_type" in parsed or "model_requested" in parsed


# =============================================================================
# Tests: Routing via detection
# =============================================================================

class TestRoutingViaDetection:
    """Tests for routed_via field detection in response."""

    @pytest.mark.asyncio
    async def test_routed_via_ollama(self):
        """Detects ollama routing."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["routed_via"] == "ollama"

    @pytest.mark.asyncio
    async def test_routed_via_huggingface(self):
        """Detects huggingface routing."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"HF_TOKEN": "test"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "hf",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["routed_via"] == "huggingface"

    @pytest.mark.asyncio
    async def test_routed_via_gemini_direct(self):
        """Detects gemini-direct routing."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"GOOGLE_AI_API_KEY": "test"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "gemini",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["routed_via"] == "gemini-direct"

    @pytest.mark.asyncio
    async def test_routed_via_direct_for_custom_endpoint(self):
        """Detects direct routing for non-standard endpoints."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        env = {"OPENAI_API_KEY": "sk-test"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "openai",
                "privacy": "cloud",
            })

        parsed = _parse_text_content(result)
        assert parsed["routed_via"] == "direct"


# =============================================================================
# Tests: EISV Energy tracking
# =============================================================================

class TestEnergyTracking:
    """Tests for EISV Energy consumption tracking."""

    @pytest.mark.asyncio
    async def test_energy_tracking_with_agent_id(self):
        """When agent_id is provided, Energy tracking is attempted."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        mock_monitor = MagicMock()
        mock_mcp_server = MagicMock()
        mock_mcp_server.get_or_create_monitor.return_value = mock_monitor

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch("src.mcp_handlers.shared.get_mcp_server", return_value=mock_mcp_server):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "agent_id": "test-agent-123",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True
        # Monitor should have been called
        mock_mcp_server.get_or_create_monitor.assert_called_once_with("test-agent-123")
        mock_monitor.process_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_energy_tracking_failure_non_blocking(self):
        """Energy tracking failure does not block the response."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance), \
             patch("src.mcp_handlers.shared.get_mcp_server", side_effect=Exception("server not ready")):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
                "agent_id": "test-agent-123",
            })

        # Should still succeed despite tracking failure
        parsed = _parse_text_content(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_no_energy_tracking_without_agent_id(self):
        """When no agent_id, Energy tracking is skipped gracefully."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = _make_mock_response()

        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("src.mcp_handlers.model_inference.OpenAI", return_value=mock_client_instance):
            from src.mcp_handlers.model_inference import handle_call_model
            result = await handle_call_model({
                "prompt": "test",
                "provider": "ollama",
            })

        parsed = _parse_text_content(result)
        assert parsed["success"] is True


# =============================================================================
# Tests: create_model_inference_client factory
# =============================================================================

class TestCreateModelInferenceClient:
    """Tests for the create_model_inference_client factory function."""

    def test_returns_none_when_openai_not_available(self):
        """Returns None when OpenAI SDK is not installed."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", False):
            from src.mcp_handlers.model_inference import create_model_inference_client
            result = create_model_inference_client()
        assert result is None

    def test_returns_none_when_no_api_key(self):
        """Returns None when no API key is configured."""
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch.dict("os.environ", {}, clear=True):
            from src.mcp_handlers.model_inference import create_model_inference_client
            result = create_model_inference_client()
        assert result is None

    def test_returns_client_when_configured(self):
        """Returns OpenAI client when properly configured."""
        mock_client = MagicMock()

        env = {"OPENAI_API_KEY": "sk-test"}
        # The factory function does `from openai import OpenAI` internally,
        # so we need to patch the openai module's OpenAI class
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("openai.OpenAI", return_value=mock_client), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import create_model_inference_client
            result = create_model_inference_client()
        assert result is mock_client

    def test_returns_none_on_creation_error(self):
        """Returns None if client creation raises an exception."""
        env = {"OPENAI_API_KEY": "sk-test"}
        with patch("src.mcp_handlers.model_inference.OPENAI_AVAILABLE", True), \
             patch("openai.OpenAI", side_effect=Exception("init error")), \
             patch.dict("os.environ", env, clear=False):
            from src.mcp_handlers.model_inference import create_model_inference_client
            result = create_model_inference_client()
        assert result is None
