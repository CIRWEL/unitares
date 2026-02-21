"""
Tests for src/mcp_server_std.py -- MCP stdio server module.

Covers:
- _normalize_http_proxy_base (pure URL normalization)
- _load_version (version file loading)
- _resolve_metadata_backend (backend selection logic)
- _parse_metadata_dict (metadata parsing with validation)
- AgentMetadata dataclass (construction, validation, lifecycle events)
- validate_agent_id_format (input validation)
- check_agent_status (status gating)
- check_agent_id_default (default ID warning)
- _detect_ci_status (CI environment detection)
- generate_api_key (key generation)
- verify_agent_ownership (auth verification)
- require_agent_id (argument validation)
- require_agent_auth (auth flow)
- get_agent_or_error (monitor lookup)
- build_standardized_agent_info (output structure building)
- detect_loop_pattern (loop detection logic)
- _should_use_sqlite_state (state backend selection)
- get_state_file (state file path resolution)
- list_tools / call_tool (MCP handlers with mocked dispatch)
- read_resource / list_resources (MCP resource handlers)
"""

import pytest
import json
import sys
import os
import time
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from dataclasses import asdict

# Ensure project root is on path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# Helpers
# ============================================================================

def _parse(result):
    """Parse TextContent result(s) into a dict."""
    if isinstance(result, (list, tuple)):
        return json.loads(result[0].text)
    return json.loads(result.text)


# ============================================================================
# Test: _normalize_http_proxy_base
# ============================================================================

class TestNormalizeHttpProxyBase:
    """Tests for URL normalization used by stdio proxy mode."""

    def test_plain_url_unchanged(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("http://localhost:8765") == "http://localhost:8765"

    def test_strips_trailing_slash(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("http://localhost:8765/") == "http://localhost:8765"

    def test_strips_v1_tools(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("http://localhost:8765/v1/tools") == "http://localhost:8765"

    def test_strips_v1_tools_call(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("http://localhost:8765/v1/tools/call") == "http://localhost:8765"

    def test_strips_v1_tools_with_trailing_slash(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        result = _normalize_http_proxy_base("http://localhost:8765/v1/tools/")
        # After rstrip("/"), becomes "http://localhost:8765/v1/tools", then strips suffix
        assert result == "http://localhost:8765"

    def test_empty_string(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("") == ""

    def test_none_value(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base(None) == ""

    def test_whitespace_only(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        assert _normalize_http_proxy_base("   ") == ""

    def test_url_with_subpath(self):
        from src.mcp_server_std import _normalize_http_proxy_base
        # URL with a subpath that does not end in /v1/tools
        result = _normalize_http_proxy_base("http://localhost:8765/api/governance")
        assert result == "http://localhost:8765/api/governance"


# ============================================================================
# Test: _load_version
# ============================================================================

class TestLoadVersion:
    """Tests for version file loading."""

    def test_loads_from_version_file(self, tmp_path):
        from src.mcp_server_std import _load_version
        version_file = tmp_path / "VERSION"
        version_file.write_text("3.1.4\n")
        with patch("src.mcp_server_std.project_root", tmp_path):
            result = _load_version()
        assert result == "3.1.4"

    def test_fallback_when_file_missing(self, tmp_path):
        from src.mcp_server_std import _load_version
        with patch("src.mcp_server_std.project_root", tmp_path):
            result = _load_version()
        assert result == "2.7.0"

    def test_strips_whitespace(self, tmp_path):
        from src.mcp_server_std import _load_version
        version_file = tmp_path / "VERSION"
        version_file.write_text("  2.8.0  \n")
        with patch("src.mcp_server_std.project_root", tmp_path):
            result = _load_version()
        assert result == "2.8.0"


# ============================================================================
# Test: AgentMetadata dataclass
# ============================================================================

class TestAgentMetadata:
    """Tests for the AgentMetadata dataclass behavior."""

    def _make_meta(self, **kwargs):
        from src.mcp_server_std import AgentMetadata
        defaults = {
            "agent_id": "test_agent_001",
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "last_update": datetime.now().isoformat(),
        }
        defaults.update(kwargs)
        return AgentMetadata(**defaults)

    def test_post_init_defaults(self):
        """Mutable defaults (lists) should be initialized in __post_init__."""
        meta = self._make_meta()
        assert meta.tags == []
        assert meta.lifecycle_events == []
        assert meta.recent_update_timestamps == []
        assert meta.recent_decisions == []
        assert meta.dialectic_conditions == []

    def test_to_dict_roundtrip(self):
        """to_dict should produce a serializable dict matching dataclass fields."""
        meta = self._make_meta(notes="test note", total_updates=5)
        d = meta.to_dict()
        assert d["agent_id"] == "test_agent_001"
        assert d["notes"] == "test note"
        assert d["total_updates"] == 5
        assert isinstance(d, dict)

    def test_add_lifecycle_event(self):
        """Lifecycle events should be appended with timestamp."""
        meta = self._make_meta()
        meta.add_lifecycle_event("paused", reason="test pause")
        assert len(meta.lifecycle_events) == 1
        event = meta.lifecycle_events[0]
        assert event["event"] == "paused"
        assert event["reason"] == "test pause"
        assert "timestamp" in event

    def test_validate_consistency_valid(self):
        """Valid metadata should pass consistency check."""
        meta = self._make_meta(total_updates=2)
        meta.recent_update_timestamps = [datetime.now().isoformat(), datetime.now().isoformat()]
        meta.recent_decisions = ["approve", "approve"]
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True
        assert errors == []

    def test_validate_consistency_mismatched_arrays(self):
        """Mismatched timestamp/decision arrays should fail validation."""
        meta = self._make_meta(total_updates=3)
        meta.recent_update_timestamps = [datetime.now().isoformat()] * 3
        meta.recent_decisions = ["approve", "approve"]  # Only 2
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("mismatched" in e.lower() for e in errors)

    def test_validate_consistency_paused_without_timestamp(self):
        """Status 'paused' without paused_at should fail."""
        meta = self._make_meta(status="paused", paused_at=None, total_updates=0)
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("paused" in e.lower() for e in errors)

    def test_validate_consistency_invalid_timestamp_format(self):
        """Invalid timestamp format should fail."""
        meta = self._make_meta(created_at="not-a-date", total_updates=0)
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("timestamp" in e.lower() for e in errors)

    def test_validate_consistency_capped_arrays(self):
        """For total_updates > 10, arrays should not exceed 10 entries."""
        meta = self._make_meta(total_updates=15)
        meta.recent_update_timestamps = [datetime.now().isoformat()] * 15
        meta.recent_decisions = ["approve"] * 15
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("exceeds cap" in e.lower() for e in errors)


# ============================================================================
# Test: _parse_metadata_dict
# ============================================================================

class TestParseMetadataDict:
    """Tests for metadata parsing from raw dict."""

    def test_valid_dict_parsed(self):
        from src.mcp_server_std import _parse_metadata_dict, AgentMetadata
        now = datetime.now().isoformat()
        data = {
            "agent1": {
                "agent_id": "agent1",
                "status": "active",
                "created_at": now,
                "last_update": now,
            }
        }
        result = _parse_metadata_dict(data)
        assert "agent1" in result
        assert isinstance(result["agent1"], AgentMetadata)
        assert result["agent1"].status == "active"

    def test_non_dict_entry_skipped(self):
        from src.mcp_server_std import _parse_metadata_dict
        data = {
            "bad_agent": "this is a string, not a dict"
        }
        result = _parse_metadata_dict(data)
        assert "bad_agent" not in result

    def test_unknown_fields_dropped(self):
        """Fields not present on AgentMetadata should be dropped (forward compat)."""
        from src.mcp_server_std import _parse_metadata_dict, AgentMetadata
        now = datetime.now().isoformat()
        data = {
            "agent1": {
                "agent_id": "agent1",
                "status": "active",
                "created_at": now,
                "last_update": now,
                "unknown_future_field": "should be dropped",
            }
        }
        result = _parse_metadata_dict(data)
        assert "agent1" in result
        meta = result["agent1"]
        assert not hasattr(meta, "unknown_future_field")

    def test_defaults_applied_for_missing_fields(self):
        """Missing optional fields should get defaults."""
        from src.mcp_server_std import _parse_metadata_dict
        now = datetime.now().isoformat()
        data = {
            "agent1": {
                "agent_id": "agent1",
                "status": "active",
                "created_at": now,
                "last_update": now,
                # No parent_agent_id, spawn_reason, etc.
            }
        }
        result = _parse_metadata_dict(data)
        meta = result["agent1"]
        assert meta.parent_agent_id is None
        assert meta.spawn_reason is None
        assert meta.health_status == "unknown"

    def test_invalid_metadata_skipped(self):
        """Entries that fail AgentMetadata construction should be skipped."""
        from src.mcp_server_std import _parse_metadata_dict
        data = {
            "bad": {"agent_id": "bad"}  # Missing required fields
        }
        result = _parse_metadata_dict(data)
        assert "bad" not in result

    def test_empty_dict_returns_empty(self):
        from src.mcp_server_std import _parse_metadata_dict
        result = _parse_metadata_dict({})
        assert result == {}


# ============================================================================
# Test: validate_agent_id_format
# ============================================================================

class TestValidateAgentIdFormat:
    """Tests for agent ID validation rules."""

    def test_valid_id_accepted(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("cursor_ide_20251124_143022")
        assert is_valid is True
        assert error == ""

    def test_generic_id_rejected(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("test")
        assert is_valid is False
        assert "generic" in error.lower()
        assert suggestion  # Should suggest an alternative

    def test_too_short_rejected(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("ab")
        assert is_valid is False
        assert "too short" in error.lower()

    def test_invalid_characters_rejected(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("agent with spaces")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_test_prefix_without_timestamp_rejected(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("test_foo")
        assert is_valid is False
        assert "timestamp" in error.lower()

    def test_demo_prefix_without_timestamp_rejected(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("demo_foo")
        assert is_valid is False
        assert "timestamp" in error.lower()

    def test_test_with_timestamp_accepted(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("test_20251124_143022")
        assert is_valid is True

    def test_generic_tool_ids_rejected(self):
        """IDs like 'claude_code_cli' should be rejected as too generic."""
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("claude_code_cli")
        assert is_valid is False
        assert "generic" in error.lower() or "collision" in error.lower()

    def test_uuid_format_accepted(self):
        """UUID-format IDs should be accepted."""
        from src.mcp_server_std import validate_agent_id_format
        import uuid
        test_uuid = str(uuid.uuid4())
        is_valid, error, suggestion = validate_agent_id_format(test_uuid)
        assert is_valid is True

    def test_hyphenated_id_accepted(self):
        from src.mcp_server_std import validate_agent_id_format
        is_valid, error, suggestion = validate_agent_id_format("production-agent-v2")
        assert is_valid is True


# ============================================================================
# Test: check_agent_status
# ============================================================================

class TestCheckAgentStatus:
    """Tests for agent status gating logic."""

    def test_active_agent_allowed(self):
        from src.mcp_server_std import check_agent_status, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        agent_metadata["status_test_active"] = AgentMetadata(
            agent_id="status_test_active", status="active", created_at=now, last_update=now
        )
        try:
            result = check_agent_status("status_test_active")
            assert result is None
        finally:
            del agent_metadata["status_test_active"]

    def test_paused_agent_blocked(self):
        from src.mcp_server_std import check_agent_status, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        agent_metadata["status_test_paused"] = AgentMetadata(
            agent_id="status_test_paused", status="paused", created_at=now, last_update=now
        )
        try:
            result = check_agent_status("status_test_paused")
            assert result is not None
            assert "paused" in result.lower()
        finally:
            del agent_metadata["status_test_paused"]

    def test_archived_agent_blocked(self):
        from src.mcp_server_std import check_agent_status, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        agent_metadata["status_test_arch"] = AgentMetadata(
            agent_id="status_test_arch", status="archived", created_at=now, last_update=now
        )
        try:
            result = check_agent_status("status_test_arch")
            assert result is not None
            assert "archived" in result.lower()
        finally:
            del agent_metadata["status_test_arch"]

    def test_deleted_agent_blocked(self):
        from src.mcp_server_std import check_agent_status, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        agent_metadata["status_test_del"] = AgentMetadata(
            agent_id="status_test_del", status="deleted", created_at=now, last_update=now
        )
        try:
            result = check_agent_status("status_test_del")
            assert result is not None
            assert "deleted" in result.lower()
        finally:
            del agent_metadata["status_test_del"]

    def test_unknown_agent_allowed(self):
        """Agent not in metadata should return None (no error)."""
        from src.mcp_server_std import check_agent_status
        result = check_agent_status("nonexistent_agent_xyz_99999")
        assert result is None


# ============================================================================
# Test: check_agent_id_default
# ============================================================================

class TestCheckAgentIdDefault:
    """Tests for default agent ID warning."""

    def test_default_agent_id_warns(self):
        from src.mcp_server_std import check_agent_id_default
        result = check_agent_id_default("default_agent")
        assert result is not None
        assert "default" in result.lower()

    def test_empty_agent_id_warns(self):
        from src.mcp_server_std import check_agent_id_default
        result = check_agent_id_default("")
        assert result is not None

    def test_specific_agent_id_no_warning(self):
        from src.mcp_server_std import check_agent_id_default
        result = check_agent_id_default("my_specific_agent_20260207")
        assert result is None


# ============================================================================
# Test: _detect_ci_status
# ============================================================================

class TestDetectCiStatus:
    """Tests for CI environment detection logic."""

    def test_not_in_ci(self):
        from src.mcp_server_std import _detect_ci_status
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_ci_status() is False

    def test_ci_true_no_status(self):
        from src.mcp_server_std import _detect_ci_status
        with patch.dict(os.environ, {"CI": "true"}, clear=True):
            assert _detect_ci_status() is False

    def test_ci_with_custom_status_passed(self):
        from src.mcp_server_std import _detect_ci_status
        with patch.dict(os.environ, {"CI": "true", "CI_STATUS": "passed"}, clear=True):
            assert _detect_ci_status() is True

    def test_ci_with_custom_status_success(self):
        from src.mcp_server_std import _detect_ci_status
        with patch.dict(os.environ, {"CI": "true", "CI_STATUS": "success"}, clear=True):
            assert _detect_ci_status() is True

    def test_github_actions_success(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "GITHUB_ACTIONS": "true", "GITHUB_WORKFLOW_STATUS": "success"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is True

    def test_github_actions_no_status(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "GITHUB_ACTIONS": "true"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is False

    def test_travis_ci_passed(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "TRAVIS": "true", "TRAVIS_TEST_RESULT": "0"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is True

    def test_travis_ci_failed(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "TRAVIS": "true", "TRAVIS_TEST_RESULT": "1"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is False

    def test_circle_ci_success(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "CIRCLE_CI": "true", "CIRCLE_BUILD_STATUS": "success"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is True

    def test_gitlab_ci_success(self):
        from src.mcp_server_std import _detect_ci_status
        env = {"CI": "true", "GITLAB_CI": "true", "CI_JOB_STATUS": "success"}
        with patch.dict(os.environ, env, clear=True):
            assert _detect_ci_status() is True


# ============================================================================
# Test: generate_api_key
# ============================================================================

class TestGenerateApiKey:
    """Tests for API key generation."""

    def test_returns_string(self):
        from src.mcp_server_std import generate_api_key
        key = generate_api_key()
        assert isinstance(key, str)

    def test_key_is_nonempty(self):
        from src.mcp_server_std import generate_api_key
        key = generate_api_key()
        assert len(key) > 0

    def test_keys_are_unique(self):
        from src.mcp_server_std import generate_api_key
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100

    def test_key_has_no_padding(self):
        from src.mcp_server_std import generate_api_key
        key = generate_api_key()
        assert "=" not in key

    def test_key_is_url_safe(self):
        """Key should only contain URL-safe base64 characters."""
        from src.mcp_server_std import generate_api_key
        import re
        key = generate_api_key()
        assert re.match(r'^[A-Za-z0-9_-]+$', key)


# ============================================================================
# Test: verify_agent_ownership
# ============================================================================

class TestVerifyAgentOwnership:
    """Tests for agent ownership verification logic."""

    def test_session_bound_always_valid(self):
        from src.mcp_server_std import verify_agent_ownership
        is_valid, error = verify_agent_ownership("any_agent", None, session_bound=True)
        assert is_valid is True
        assert error is None

    def test_nonexistent_agent(self):
        from src.mcp_server_std import verify_agent_ownership, agent_metadata
        # Make sure agent does not exist
        test_id = "nonexistent_verify_test_99999"
        agent_metadata.pop(test_id, None)
        is_valid, error = verify_agent_ownership(test_id, "some_key")
        assert is_valid is False
        assert "does not exist" in error

    def test_agent_with_no_stored_key_allows_access(self):
        """Agents without stored keys (legacy/UUID-based) should pass."""
        from src.mcp_server_std import verify_agent_ownership, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "verify_no_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key=None
        )
        try:
            is_valid, error = verify_agent_ownership(test_id, None)
            assert is_valid is True
        finally:
            del agent_metadata[test_id]

    def test_correct_key_passes(self):
        from src.mcp_server_std import verify_agent_ownership, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "verify_correct_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="secret_key_123"
        )
        try:
            is_valid, error = verify_agent_ownership(test_id, "secret_key_123")
            assert is_valid is True
            assert error is None
        finally:
            del agent_metadata[test_id]

    def test_wrong_key_fails(self):
        from src.mcp_server_std import verify_agent_ownership, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "verify_wrong_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="real_secret_key"
        )
        try:
            is_valid, error = verify_agent_ownership(test_id, "wrong_key")
            assert is_valid is False
            assert "invalid" in error.lower()
        finally:
            del agent_metadata[test_id]

    def test_empty_api_key_with_stored_key_fails(self):
        from src.mcp_server_std import verify_agent_ownership, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "verify_empty_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="stored_key"
        )
        try:
            is_valid, error = verify_agent_ownership(test_id, "")
            assert is_valid is False
        finally:
            del agent_metadata[test_id]

    def test_none_api_key_with_stored_key_fails(self):
        from src.mcp_server_std import verify_agent_ownership, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "verify_none_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="stored_key"
        )
        try:
            is_valid, error = verify_agent_ownership(test_id, None)
            assert is_valid is False
        finally:
            del agent_metadata[test_id]


# ============================================================================
# Test: require_agent_id
# ============================================================================

class TestRequireAgentId:
    """Tests for agent_id argument extraction and validation."""

    def test_missing_agent_id(self):
        from src.mcp_server_std import require_agent_id
        agent_id, error = require_agent_id({})
        assert agent_id is None
        assert error is not None
        parsed = json.loads(error.text)
        assert parsed["success"] is False

    def test_empty_agent_id(self):
        from src.mcp_server_std import require_agent_id
        agent_id, error = require_agent_id({"agent_id": ""})
        assert agent_id is None
        assert error is not None

    def test_valid_agent_id_new(self):
        from src.mcp_server_std import require_agent_id, agent_metadata
        test_id = "cursor_session_20260207_test"
        agent_metadata.pop(test_id, None)
        agent_id, error = require_agent_id({"agent_id": test_id})
        assert agent_id == test_id
        assert error is None

    def test_reject_existing_true_blocks_existing(self):
        from src.mcp_server_std import require_agent_id, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "require_existing_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now
        )
        try:
            agent_id, error = require_agent_id({"agent_id": test_id}, reject_existing=True)
            assert agent_id is None
            assert error is not None
            parsed = json.loads(error.text)
            assert "collision" in parsed.get("error", "").lower()
        finally:
            del agent_metadata[test_id]

    def test_reject_existing_false_allows_existing(self):
        from src.mcp_server_std import require_agent_id, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "require_allow_existing_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now
        )
        try:
            agent_id, error = require_agent_id({"agent_id": test_id}, reject_existing=False)
            assert agent_id == test_id
            assert error is None
        finally:
            del agent_metadata[test_id]


# ============================================================================
# Test: require_agent_auth
# ============================================================================

class TestRequireAgentAuth:
    """Tests for authentication requirement logic."""

    def test_new_agent_passes(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata
        test_id = "auth_new_agent_test_99999"
        agent_metadata.pop(test_id, None)
        is_valid, error = require_agent_auth(test_id, {})
        assert is_valid is True
        assert error is None

    def test_agent_no_key_no_enforce_passes(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "auth_nokey_noforce_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key=None
        )
        try:
            is_valid, error = require_agent_auth(test_id, {}, enforce=False)
            assert is_valid is True
        finally:
            del agent_metadata[test_id]

    def test_agent_no_key_enforce_fails(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "auth_nokey_enforce_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key=None
        )
        try:
            is_valid, error = require_agent_auth(test_id, {}, enforce=True)
            assert is_valid is False
            assert error is not None
        finally:
            del agent_metadata[test_id]

    def test_agent_with_key_correct_passes(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "auth_correct_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="my_secret_key"
        )
        try:
            is_valid, error = require_agent_auth(test_id, {"api_key": "my_secret_key"})
            assert is_valid is True
            assert error is None
        finally:
            del agent_metadata[test_id]

    def test_agent_with_key_missing_key_fails(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "auth_missing_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="my_secret_key"
        )
        try:
            is_valid, error = require_agent_auth(test_id, {})
            assert is_valid is False
            assert error is not None
        finally:
            del agent_metadata[test_id]

    def test_agent_with_key_wrong_key_fails(self):
        from src.mcp_server_std import require_agent_auth, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "auth_wrong_key_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            api_key="correct_key"
        )
        try:
            is_valid, error = require_agent_auth(test_id, {"api_key": "wrong_key"})
            assert is_valid is False
            assert error is not None
            parsed = json.loads(error.text)
            assert "authentication failed" in parsed.get("error", "").lower()
        finally:
            del agent_metadata[test_id]


# ============================================================================
# Test: get_agent_or_error
# ============================================================================

class TestGetAgentOrError:
    """Tests for monitor lookup with error messaging."""

    def test_existing_monitor_returned(self):
        from src.mcp_server_std import get_agent_or_error, monitors
        mock_monitor = MagicMock()
        monitors["lookup_test_agent"] = mock_monitor
        try:
            monitor, error = get_agent_or_error("lookup_test_agent")
            assert monitor is mock_monitor
            assert error is None
        finally:
            del monitors["lookup_test_agent"]

    def test_missing_monitor_no_agents(self):
        from src.mcp_server_std import get_agent_or_error, monitors
        # Ensure no agents
        saved = dict(monitors)
        monitors.clear()
        try:
            monitor, error = get_agent_or_error("missing_agent")
            assert monitor is None
            assert "not found" in error.lower()
            assert "no agents initialized" in error.lower()
        finally:
            monitors.update(saved)

    def test_missing_monitor_with_other_agents(self):
        from src.mcp_server_std import get_agent_or_error, monitors
        monitors["other_agent"] = MagicMock()
        try:
            monitor, error = get_agent_or_error("missing_agent")
            assert monitor is None
            assert "not found" in error.lower()
            assert "available agents" in error.lower()
        finally:
            monitors.pop("other_agent", None)


# ============================================================================
# Test: _should_use_sqlite_state
# ============================================================================

class TestShouldUseSqliteState:
    """Tests for state backend selection logic."""

    def test_json_backend_returns_false(self):
        from src.mcp_server_std import _should_use_sqlite_state
        with patch("src.mcp_server_std.UNITARES_STATE_BACKEND", "json"):
            assert _should_use_sqlite_state() is False

    def test_sqlite_backend_returns_true(self):
        from src.mcp_server_std import _should_use_sqlite_state
        with patch("src.mcp_server_std.UNITARES_STATE_BACKEND", "sqlite"):
            assert _should_use_sqlite_state() is True

    def test_auto_backend_with_db_returns_true(self):
        from src.mcp_server_std import _should_use_sqlite_state
        with patch("src.mcp_server_std.UNITARES_STATE_BACKEND", "auto"):
            with patch("pathlib.Path.exists", return_value=True):
                assert _should_use_sqlite_state() is True

    def test_auto_backend_without_db_returns_false(self):
        from src.mcp_server_std import _should_use_sqlite_state
        with patch("src.mcp_server_std.UNITARES_STATE_BACKEND", "auto"):
            with patch("pathlib.Path.exists", return_value=False):
                assert _should_use_sqlite_state() is False


# ============================================================================
# Test: _resolve_metadata_backend
# ============================================================================

class TestResolveMetadataBackend:
    """Tests for metadata backend resolution logic."""

    def test_json_returns_json(self):
        from src.mcp_server_std import _resolve_metadata_backend
        with patch("src.mcp_server_std._metadata_backend_resolved", None):
            with patch("src.mcp_server_std.UNITARES_METADATA_BACKEND", "json"):
                result = _resolve_metadata_backend()
                assert result == "json"

    def test_sqlite_returns_sqlite(self):
        from src.mcp_server_std import _resolve_metadata_backend
        with patch("src.mcp_server_std._metadata_backend_resolved", None):
            with patch("src.mcp_server_std.UNITARES_METADATA_BACKEND", "sqlite"):
                result = _resolve_metadata_backend()
                assert result == "sqlite"

    def test_auto_with_db_file_returns_sqlite(self):
        from src.mcp_server_std import _resolve_metadata_backend
        with patch("src.mcp_server_std._metadata_backend_resolved", None):
            with patch("src.mcp_server_std.UNITARES_METADATA_BACKEND", "auto"):
                with patch.object(Path, "exists", return_value=True):
                    result = _resolve_metadata_backend()
                    assert result == "sqlite"

    def test_auto_without_db_file_returns_json(self):
        from src.mcp_server_std import _resolve_metadata_backend
        with patch("src.mcp_server_std._metadata_backend_resolved", None):
            with patch("src.mcp_server_std.UNITARES_METADATA_BACKEND", "auto"):
                with patch.object(Path, "exists", return_value=False):
                    result = _resolve_metadata_backend()
                    assert result == "json"

    def test_cached_result_returned(self):
        """Once resolved, should return cached result without re-computing."""
        from src.mcp_server_std import _resolve_metadata_backend
        with patch("src.mcp_server_std._metadata_backend_resolved", "cached_value"):
            result = _resolve_metadata_backend()
            assert result == "cached_value"


# ============================================================================
# Test: detect_loop_pattern
# ============================================================================

class TestDetectLoopPattern:
    """Tests for recursive loop detection logic."""

    def _setup_agent(self, agent_id, timestamps, decisions, **kwargs):
        """Helper to set up agent metadata for loop detection testing."""
        from src.mcp_server_std import agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        meta = AgentMetadata(
            agent_id=agent_id,
            status="active",
            created_at=(datetime.now() - timedelta(hours=1)).isoformat(),
            last_update=now,
            **kwargs,
        )
        meta.recent_update_timestamps = timestamps
        meta.recent_decisions = decisions
        agent_metadata[agent_id] = meta
        return meta

    def _cleanup(self, agent_id):
        from src.mcp_server_std import agent_metadata
        agent_metadata.pop(agent_id, None)

    def test_nonexistent_agent_no_loop(self):
        from src.mcp_server_std import detect_loop_pattern
        is_loop, reason = detect_loop_pattern("does_not_exist_loop_test")
        assert is_loop is False
        assert reason == ""

    def test_fewer_than_3_updates_no_loop(self):
        from src.mcp_server_std import detect_loop_pattern
        test_id = "loop_few_updates_test"
        now = datetime.now()
        self._setup_agent(
            test_id,
            timestamps=[(now - timedelta(seconds=i)).isoformat() for i in range(2)],
            decisions=["approve", "approve"],
        )
        try:
            is_loop, reason = detect_loop_pattern(test_id)
            assert is_loop is False
        finally:
            self._cleanup(test_id)

    def test_cooldown_active(self):
        from src.mcp_server_std import detect_loop_pattern
        test_id = "loop_cooldown_test"
        now = datetime.now()
        self._setup_agent(
            test_id,
            timestamps=[(now - timedelta(seconds=i)).isoformat() for i in range(3)],
            decisions=["approve"] * 3,
            loop_cooldown_until=(now + timedelta(seconds=30)).isoformat(),
        )
        try:
            is_loop, reason = detect_loop_pattern(test_id)
            assert is_loop is True
            assert "cooldown" in reason.lower()
        finally:
            self._cleanup(test_id)

    def test_pattern2_reject_loop_detected(self):
        """Pattern 2: 3+ updates within 10s with 2+ reject/pause decisions."""
        from src.mcp_server_std import detect_loop_pattern
        test_id = "loop_pattern2_test"
        now = datetime.now()
        # Server start was recent, so skip Pattern 1 but Pattern 2 should still fire
        timestamps = [
            (now - timedelta(seconds=5)).isoformat(),
            (now - timedelta(seconds=3)).isoformat(),
            (now - timedelta(seconds=1)).isoformat(),
        ]
        decisions = ["reject", "reject", "approve"]
        self._setup_agent(test_id, timestamps, decisions)
        try:
            is_loop, reason = detect_loop_pattern(test_id)
            assert is_loop is True
            assert "pause" in reason.lower() or "pattern" in reason.lower() or "reject" in reason.lower() or "stuck" in reason.lower()
        finally:
            self._cleanup(test_id)

    def test_pattern4_decision_loop_detected(self):
        """Pattern 4: Same decision repeated 5+ times (pause only)."""
        from src.mcp_server_std import detect_loop_pattern
        test_id = "loop_pattern4_test"
        now = datetime.now()
        # Space them out so rapid-fire patterns don't trigger
        timestamps = [
            (now - timedelta(minutes=10 - i)).isoformat()
            for i in range(6)
        ]
        decisions = ["pause"] * 6
        self._setup_agent(test_id, timestamps, decisions)
        try:
            is_loop, reason = detect_loop_pattern(test_id)
            assert is_loop is True
            assert "decision loop" in reason.lower() or "pause" in reason.lower()
        finally:
            self._cleanup(test_id)

    def test_normal_proceed_no_loop(self):
        """All-proceed with reasonable spacing should NOT trigger loop detection."""
        from src.mcp_server_std import detect_loop_pattern
        test_id = "loop_normal_test"
        now = datetime.now()
        # Well-spaced updates, all proceed
        timestamps = [
            (now - timedelta(minutes=30 - i * 5)).isoformat()
            for i in range(4)
        ]
        decisions = ["proceed"] * 4
        self._setup_agent(test_id, timestamps, decisions)
        try:
            is_loop, reason = detect_loop_pattern(test_id)
            assert is_loop is False
        finally:
            self._cleanup(test_id)


# ============================================================================
# Test: build_standardized_agent_info
# ============================================================================

class TestBuildStandardizedAgentInfo:
    """Tests for standardized agent info structure building."""

    def test_basic_structure_without_monitor(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata
        now = datetime.now().isoformat()
        meta = AgentMetadata(
            agent_id="info_test",
            status="active",
            created_at=now,
            last_update=now,
            total_updates=5,
            tags=["test"],
            notes="some notes",
        )
        result = build_standardized_agent_info("info_test", meta, monitor=None)
        assert result["agent_id"] == "info_test"
        assert result["lifecycle_status"] == "active"
        assert result["health_status"] == "unknown"
        assert result["metrics"] is None
        assert result["summary"]["updates"] == 5
        assert result["metadata"]["tags"] == ["test"]
        assert result["state"]["loaded_in_process"] is False

    def test_notes_preview_truncation(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata
        now = datetime.now().isoformat()
        long_notes = "A" * 200
        meta = AgentMetadata(
            agent_id="info_notes_test",
            status="active",
            created_at=now,
            last_update=now,
            notes=long_notes,
        )
        result = build_standardized_agent_info("info_notes_test", meta)
        notes_preview = result["metadata"]["notes_preview"]
        assert len(notes_preview) <= 103 + 3  # 100 chars + "..."
        assert notes_preview.endswith("...")

    def test_short_notes_no_truncation(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata
        now = datetime.now().isoformat()
        meta = AgentMetadata(
            agent_id="info_short_notes_test",
            status="active",
            created_at=now,
            last_update=now,
            notes="short note",
        )
        result = build_standardized_agent_info("info_short_notes_test", meta)
        assert result["metadata"]["notes_preview"] == "short note"

    def test_lineage_info_with_parent(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata, agent_metadata
        now = datetime.now().isoformat()
        # Create parent in metadata
        parent_meta = AgentMetadata(
            agent_id="parent_agent", status="active", created_at=now, last_update=now
        )
        agent_metadata["parent_agent"] = parent_meta
        try:
            child_meta = AgentMetadata(
                agent_id="child_agent",
                status="active",
                created_at=now,
                last_update=now,
                parent_agent_id="parent_agent",
                spawn_reason="test_spawn",
            )
            result = build_standardized_agent_info("child_agent", child_meta)
            lineage = result["metadata"]["lineage_info"]
            assert lineage is not None
            assert lineage["parent_agent_id"] == "parent_agent"
            assert lineage["parent_status"] == "active"
            assert lineage["creation_reason"] == "test_spawn"
        finally:
            agent_metadata.pop("parent_agent", None)

    def test_lineage_info_missing_parent(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata, agent_metadata
        now = datetime.now().isoformat()
        # Do NOT create parent
        agent_metadata.pop("nonexistent_parent", None)
        meta = AgentMetadata(
            agent_id="orphan_agent",
            status="active",
            created_at=now,
            last_update=now,
            parent_agent_id="nonexistent_parent",
        )
        result = build_standardized_agent_info("orphan_agent", meta)
        lineage = result["metadata"]["lineage_info"]
        assert lineage is not None
        assert lineage["parent_status"] == "deleted"

    def test_no_lineage_without_parent(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata
        now = datetime.now().isoformat()
        meta = AgentMetadata(
            agent_id="solo_agent",
            status="active",
            created_at=now,
            last_update=now,
        )
        result = build_standardized_agent_info("solo_agent", meta)
        assert result["metadata"]["lineage_info"] is None

    def test_primary_tags_capped_at_3(self):
        from src.mcp_server_std import build_standardized_agent_info, AgentMetadata
        now = datetime.now().isoformat()
        meta = AgentMetadata(
            agent_id="tags_test",
            status="active",
            created_at=now,
            last_update=now,
            tags=["a", "b", "c", "d", "e"],
        )
        result = build_standardized_agent_info("tags_test", meta)
        assert len(result["summary"]["primary_tags"]) == 3


# ============================================================================
# Test: get_state_file
# ============================================================================

class TestGetStateFile:
    """Tests for state file path resolution and migration."""

    def test_returns_agents_subdir_path(self, tmp_path):
        from src.mcp_server_std import get_state_file
        with patch("src.mcp_server_std.project_root", tmp_path):
            agents_dir = tmp_path / "data" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            result = get_state_file("my_agent")
            assert result == agents_dir / "my_agent_state.json"

    def test_migrates_from_old_path(self, tmp_path):
        from src.mcp_server_std import get_state_file
        with patch("src.mcp_server_std.project_root", tmp_path):
            data_dir = tmp_path / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            agents_dir = data_dir / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            # Create file at old location
            old_file = data_dir / "migrate_agent_state.json"
            old_file.write_text('{"test": true}')
            # Should migrate
            result = get_state_file("migrate_agent")
            new_path = agents_dir / "migrate_agent_state.json"
            assert result == new_path
            assert new_path.exists()
            assert not old_file.exists()


# ============================================================================
# Test: auto_archive_old_test_agents
# ============================================================================

class TestAutoArchiveOldTestAgents:
    """Tests for automatic archival of old test agents."""

    @pytest.mark.asyncio
    async def test_archives_low_update_test_agent(self):
        from src.mcp_server_std import auto_archive_old_test_agents, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "test_archive_low_update"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            total_updates=1,
        )
        try:
            archived = await auto_archive_old_test_agents(6.0)
            assert archived >= 1
            assert agent_metadata[test_id].status == "archived"
        finally:
            agent_metadata.pop(test_id, None)

    @pytest.mark.asyncio
    async def test_skips_already_archived(self):
        from src.mcp_server_std import auto_archive_old_test_agents, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "test_already_archived"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="archived", created_at=now, last_update=now,
            total_updates=1,
        )
        try:
            archived = await auto_archive_old_test_agents(6.0)
            # Should not count already-archived agents
            assert agent_metadata[test_id].status == "archived"
        finally:
            agent_metadata.pop(test_id, None)

    @pytest.mark.asyncio
    async def test_skips_non_test_agents(self):
        from src.mcp_server_std import auto_archive_old_test_agents, agent_metadata, AgentMetadata
        now = datetime.now().isoformat()
        test_id = "production_agent_v2_20260207"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=now, last_update=now,
            total_updates=1,
        )
        try:
            await auto_archive_old_test_agents(6.0)
            assert agent_metadata[test_id].status == "active"
        finally:
            agent_metadata.pop(test_id, None)

    @pytest.mark.asyncio
    async def test_archives_old_test_agent_by_age(self):
        from src.mcp_server_std import auto_archive_old_test_agents, agent_metadata, AgentMetadata
        old_time = (datetime.now() - timedelta(hours=10)).isoformat()
        test_id = "test_old_agent_age"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=old_time, last_update=old_time,
            total_updates=5,  # More than 2 -- age-based archival
        )
        try:
            archived = await auto_archive_old_test_agents(6.0)
            assert archived >= 1
            assert agent_metadata[test_id].status == "archived"
        finally:
            agent_metadata.pop(test_id, None)


# ============================================================================
# Test: auto_archive_orphan_agents
# ============================================================================

class TestAutoArchiveOrphanAgents:
    """Tests for orphan agent archival logic."""

    @pytest.mark.asyncio
    async def test_archives_uuid_agent_zero_updates(self):
        from src.mcp_server_std import auto_archive_orphan_agents, agent_metadata, AgentMetadata
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        test_id = "12345678-1234-4234-8234-123456789abc"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=old_time, last_update=old_time,
            total_updates=0,
        )
        try:
            archived = await auto_archive_orphan_agents(zero_update_hours=1.0)
            assert archived >= 1
            assert agent_metadata[test_id].status == "archived"
        finally:
            agent_metadata.pop(test_id, None)

    @pytest.mark.asyncio
    async def test_preserves_pioneer_agents(self):
        from src.mcp_server_std import auto_archive_orphan_agents, agent_metadata, AgentMetadata
        old_time = (datetime.now() - timedelta(hours=24)).isoformat()
        test_id = "12345678-1234-4234-8234-123456789999"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=old_time, last_update=old_time,
            total_updates=0, tags=["pioneer"],
        )
        try:
            await auto_archive_orphan_agents(zero_update_hours=1.0)
            assert agent_metadata[test_id].status == "active"
        finally:
            agent_metadata.pop(test_id, None)

    @pytest.mark.asyncio
    async def test_preserves_labeled_agents(self):
        """Labeled non-UUID agents should be preserved (Rule 2 checks has_label)."""
        from src.mcp_server_std import auto_archive_orphan_agents, agent_metadata, AgentMetadata
        old_time = (datetime.now() - timedelta(hours=24)).isoformat()
        # Use a non-UUID agent_id so Rule 1 (UUID-specific) does not fire
        # Rule 2 checks: not has_label and updates <= 1 -- so labeled agent is preserved
        test_id = "labeled_orphan_agent_test"
        agent_metadata[test_id] = AgentMetadata(
            agent_id=test_id, status="active", created_at=old_time, last_update=old_time,
            total_updates=0, label="My Important Agent",
        )
        try:
            await auto_archive_orphan_agents(zero_update_hours=1.0, low_update_hours=3.0)
            # Should NOT be archived because it has a label
            assert agent_metadata[test_id].status == "active"
        finally:
            agent_metadata.pop(test_id, None)


# ============================================================================
# Test: MCP list_tools handler
# ============================================================================

class TestListToolsHandler:
    """Tests for the MCP list_tools handler."""

    @pytest.mark.asyncio
    async def test_local_tools_returned_no_proxy(self):
        """When no proxy is configured, should return local tool definitions."""
        from src.mcp_server_std import list_tools
        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                tools = await list_tools()
                assert isinstance(tools, list)
                assert len(tools) > 0
                # Each tool should have a name
                for tool in tools:
                    assert hasattr(tool, "name")
                    assert hasattr(tool, "description")

    @pytest.mark.asyncio
    async def test_proxy_http_fallback_non_strict(self):
        """When HTTP proxy fails in non-strict mode, should fallback to local tools."""
        from src.mcp_server_std import list_tools
        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", "http://broken:9999"):
            with patch("src.mcp_server_std.STDIO_PROXY_STRICT", False):
                with patch("src.mcp_server_std._proxy_http_list_tools", new_callable=AsyncMock, side_effect=Exception("connection failed")):
                    tools = await list_tools()
                    assert isinstance(tools, list)
                    assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_proxy_http_strict_raises(self):
        """When HTTP proxy fails in strict mode, should raise."""
        from src.mcp_server_std import list_tools
        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", "http://broken:9999"):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_server_std.STDIO_PROXY_STRICT", True):
                    with patch("src.mcp_server_std._proxy_http_list_tools", new_callable=AsyncMock, side_effect=Exception("connection failed")):
                        with pytest.raises(Exception, match="connection failed"):
                            await list_tools()


# ============================================================================
# Test: MCP call_tool handler
# ============================================================================

class TestCallToolHandler:
    """Tests for the MCP call_tool handler."""

    @pytest.mark.asyncio
    async def test_dispatch_to_handler(self):
        """Should dispatch to handler registry and return result."""
        from src.mcp_server_std import call_tool
        from mcp.types import TextContent

        mock_result = [TextContent(type="text", text=json.dumps({"success": True}))]

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_handlers.dispatch_tool", new_callable=AsyncMock, return_value=mock_result) as mock_dispatch:
                    result = await call_tool("health_check", {})
                    assert result == mock_result
                    mock_dispatch.assert_called_once_with("health_check", {})

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """When dispatch returns None (unknown tool), should return error."""
        from src.mcp_server_std import call_tool

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_handlers.dispatch_tool", new_callable=AsyncMock, return_value=None):
                    result = await call_tool("nonexistent_tool_xyz", {})
                    assert isinstance(result, list)
                    parsed = json.loads(result[0].text)
                    assert parsed["success"] is False
                    assert "unknown tool" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_none_arguments_default_to_empty_dict(self):
        """When arguments is None, should default to empty dict."""
        from src.mcp_server_std import call_tool
        from mcp.types import TextContent

        mock_result = [TextContent(type="text", text=json.dumps({"success": True}))]

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_handlers.dispatch_tool", new_callable=AsyncMock, return_value=mock_result) as mock_dispatch:
                    await call_tool("health_check", None)
                    mock_dispatch.assert_called_once_with("health_check", {})

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self):
        """When handler raises an exception, should return sanitized error."""
        from src.mcp_server_std import call_tool

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_handlers.dispatch_tool", new_callable=AsyncMock, side_effect=RuntimeError("handler crashed")):
                    result = await call_tool("broken_tool", {})
                    assert isinstance(result, list)
                    parsed = json.loads(result[0].text)
                    assert "error" in parsed or "success" in parsed

    @pytest.mark.asyncio
    async def test_import_error_returns_error(self):
        """When handler registry import fails, should return error."""
        from src.mcp_server_std import call_tool

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", None):
                with patch("src.mcp_handlers.dispatch_tool", new_callable=AsyncMock, side_effect=ImportError("module not found")):
                    # dispatch_tool raises ImportError which is caught in call_tool
                    result = await call_tool("some_tool", {})
                    assert isinstance(result, list)
                    parsed = json.loads(result[0].text)
                    assert parsed["success"] is False

    @pytest.mark.asyncio
    async def test_proxy_http_strict_returns_json_error(self):
        """When HTTP proxy fails in strict mode, should return JSON error."""
        from src.mcp_server_std import call_tool

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", "http://broken:9999"):
            with patch("src.mcp_server_std.STDIO_PROXY_STRICT", True):
                with patch("src.mcp_server_std._proxy_http_call_tool", new_callable=AsyncMock, side_effect=Exception("proxy fail")):
                    result = await call_tool("some_tool", {})
                    assert isinstance(result, list)
                    parsed = json.loads(result[0].text)
                    assert parsed["success"] is False
                    assert "proxy" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_proxy_sse_strict_returns_json_error(self):
        """When SSE proxy fails in strict mode, should return JSON error."""
        from src.mcp_server_std import call_tool

        with patch("src.mcp_server_std.STDIO_PROXY_HTTP_URL", None):
            with patch("src.mcp_server_std.STDIO_PROXY_SSE_URL", "http://broken:9999"):
                with patch("src.mcp_server_std.STDIO_PROXY_STRICT", True):
                    with patch("src.mcp_server_std._proxy_call_tool", new_callable=AsyncMock, side_effect=Exception("sse fail")):
                        result = await call_tool("some_tool", {})
                        assert isinstance(result, list)
                        parsed = json.loads(result[0].text)
                        assert parsed["success"] is False
                        assert "proxy" in parsed["error"].lower()


# ============================================================================
# Test: MCP resource handlers
# ============================================================================

class TestResourceHandlers:
    """Tests for MCP resource list/read handlers."""

    @pytest.mark.asyncio
    async def test_list_resources_returns_skill_resource(self):
        from src.mcp_server_std import list_resources
        resources = await list_resources()
        assert len(resources) >= 1
        names = [r.name for r in resources]
        assert any("SKILL" in name for name in names)

    @pytest.mark.asyncio
    async def test_read_resource_skill_exists(self, tmp_path):
        from src.mcp_server_std import read_resource
        # Create skill file
        skill_dir = tmp_path / "skills" / "unitares-governance"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("# Test Skill Content")
        with patch("src.mcp_server_std.project_root", tmp_path):
            content = await read_resource("unitares://skill")
            assert "Test Skill Content" in content

    @pytest.mark.asyncio
    async def test_read_resource_skill_not_found(self, tmp_path):
        from src.mcp_server_std import read_resource
        with patch("src.mcp_server_std.project_root", tmp_path):
            content = await read_resource("unitares://skill")
            assert "SKILL.md not found" in content

    @pytest.mark.asyncio
    async def test_read_resource_unknown_uri(self):
        from src.mcp_server_std import read_resource
        with pytest.raises(ValueError, match="Unknown resource"):
            await read_resource("unitares://nonexistent")


# ============================================================================
# Test: signal_handler
# ============================================================================

class TestSignalHandler:
    """Tests for graceful shutdown signal handling."""

    def test_signal_handler_sets_flag(self):
        import src.mcp_server_std as mod
        original = mod._shutdown_requested
        try:
            mod._shutdown_requested = False
            mod.signal_handler(None, None)
            assert mod._shutdown_requested is True
        finally:
            mod._shutdown_requested = original


# ============================================================================
# Test: write_pid_file / remove_pid_file
# ============================================================================

class TestPidFile:
    """Tests for PID file management."""

    def test_write_and_remove_pid_file(self, tmp_path):
        import src.mcp_server_std as mod
        pid_file = tmp_path / ".mcp_server.pid"
        original_pid_file = mod.PID_FILE
        try:
            mod.PID_FILE = pid_file
            mod.write_pid_file()
            assert pid_file.exists()
            content = pid_file.read_text().strip()
            assert content == str(os.getpid())
            mod.remove_pid_file()
            assert not pid_file.exists()
        finally:
            mod.PID_FILE = original_pid_file

    def test_remove_nonexistent_pid_file(self, tmp_path):
        import src.mcp_server_std as mod
        pid_file = tmp_path / ".mcp_server.pid"
        original_pid_file = mod.PID_FILE
        try:
            mod.PID_FILE = pid_file
            # Should not raise
            mod.remove_pid_file()
        finally:
            mod.PID_FILE = original_pid_file


# ============================================================================
# Test: deprecated no-op functions
# ============================================================================

class TestDeprecatedNoOps:
    """Verify deprecated functions are true no-ops that don't crash."""

    @pytest.mark.asyncio
    async def test_schedule_metadata_save(self):
        from src.mcp_server_std import schedule_metadata_save
        await schedule_metadata_save()
        await schedule_metadata_save(force=True)

    @pytest.mark.asyncio
    async def test_batched_metadata_save(self):
        from src.mcp_server_std import _batched_metadata_save
        await _batched_metadata_save()

    @pytest.mark.asyncio
    async def test_flush_metadata_save(self):
        from src.mcp_server_std import flush_metadata_save
        await flush_metadata_save()

    def test_schedule_metadata_save_sync(self):
        from src.mcp_server_std import _schedule_metadata_save_sync
        _schedule_metadata_save_sync()
        _schedule_metadata_save_sync(force=True)

    @pytest.mark.asyncio
    async def test_save_metadata_async(self):
        from src.mcp_server_std import save_metadata_async
        await save_metadata_async()

    def test_save_metadata(self):
        from src.mcp_server_std import save_metadata
        save_metadata()


# ============================================================================
# Test: dispatch_tool middleware pipeline
# ============================================================================

class TestDispatchTool:
    """Tests for the dispatch_tool middleware pipeline in mcp_handlers."""

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self):
        """Unknown tools should return a tool-not-found error."""
        from src.mcp_handlers import dispatch_tool
        result = await dispatch_tool("this_tool_definitely_does_not_exist_99999", {})
        assert result is not None
        parsed = json.loads(result[0].text)
        assert parsed.get("success") is False or "not found" in parsed.get("error", "").lower() or "unknown" in parsed.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_dispatch_health_check(self):
        """health_check should be a registered tool that returns success."""
        from src.mcp_handlers import dispatch_tool
        result = await dispatch_tool("health_check", {})
        assert result is not None
        parsed = json.loads(result[0].text)
        assert parsed.get("status") in ("ok", "healthy") or parsed.get("success") is True or "version" in parsed


# ============================================================================
# Test: DispatchContext dataclass
# ============================================================================

class TestDispatchContext:
    """Tests for DispatchContext initialization."""

    def test_defaults(self):
        from src.mcp_handlers.middleware import DispatchContext
        ctx = DispatchContext()
        assert ctx.session_key is None
        assert ctx.client_session_id is None
        assert ctx.bound_agent_id is None
        assert ctx.context_token is None
        assert ctx.trajectory_confidence_token is None
        assert ctx.migration_note is None
        assert ctx.original_name is None
        assert ctx.client_hint is None
        assert ctx.identity_result is None

    def test_custom_values(self):
        from src.mcp_handlers.middleware import DispatchContext
        ctx = DispatchContext(
            session_key="sk_123",
            bound_agent_id="agent_456",
            migration_note="aliased from old_tool",
        )
        assert ctx.session_key == "sk_123"
        assert ctx.bound_agent_id == "agent_456"
        assert ctx.migration_note == "aliased from old_tool"


# ============================================================================
# Test: TOOL_HANDLERS registry
# ============================================================================

class TestToolHandlersRegistry:
    """Tests for the tool handler registry population."""

    def test_registry_is_populated(self):
        from src.mcp_handlers import TOOL_HANDLERS
        assert isinstance(TOOL_HANDLERS, dict)
        assert len(TOOL_HANDLERS) > 0

    def test_known_tools_registered(self):
        """Key tools should be in the registry."""
        from src.mcp_handlers import TOOL_HANDLERS
        expected_tools = [
            "health_check",
            "process_agent_update",
            "get_governance_metrics",
            "onboard",
            "identity",
            "agent",
            "knowledge",
            "calibration",
        ]
        for tool_name in expected_tools:
            assert tool_name in TOOL_HANDLERS, f"Expected tool '{tool_name}' not found in registry"

    def test_all_handlers_are_callable(self):
        from src.mcp_handlers import TOOL_HANDLERS
        for name, handler in TOOL_HANDLERS.items():
            assert callable(handler), f"Handler for '{name}' is not callable"


# ============================================================================
# Test: _write_state_file
# ============================================================================

class TestWriteStateFile:
    """Tests for state file writing helper."""

    def test_writes_json_to_file(self, tmp_path):
        from src.mcp_server_std import _write_state_file
        state_file = tmp_path / "test_state.json"
        state_data = {"key": "value", "nested": {"a": 1}}
        _write_state_file(state_file, state_data)
        assert state_file.exists()
        loaded = json.loads(state_file.read_text())
        assert loaded == state_data

    def test_overwrites_existing_file(self, tmp_path):
        from src.mcp_server_std import _write_state_file
        state_file = tmp_path / "overwrite_test.json"
        _write_state_file(state_file, {"version": 1})
        _write_state_file(state_file, {"version": 2})
        loaded = json.loads(state_file.read_text())
        assert loaded["version"] == 2


# ============================================================================
# Test: _migrate_metadata_json_to_sqlite_sync
# ============================================================================

class TestMigrateMetadataJsonToSqlite:
    """Tests for JSON to SQLite metadata migration."""

    def test_no_json_file_returns_zero(self, tmp_path):
        from src.mcp_server_std import _migrate_metadata_json_to_sqlite_sync
        with patch("src.mcp_server_std.METADATA_FILE", tmp_path / "nonexistent.json"):
            result = _migrate_metadata_json_to_sqlite_sync()
            assert result == 0

    def test_empty_json_returns_zero(self, tmp_path):
        from src.mcp_server_std import _migrate_metadata_json_to_sqlite_sync
        json_file = tmp_path / "metadata.json"
        json_file.write_text("{}")
        with patch("src.mcp_server_std.METADATA_FILE", json_file):
            result = _migrate_metadata_json_to_sqlite_sync()
            assert result == 0

    def test_invalid_json_returns_zero(self, tmp_path):
        from src.mcp_server_std import _migrate_metadata_json_to_sqlite_sync
        json_file = tmp_path / "metadata.json"
        json_file.write_text("not valid json {{{")
        with patch("src.mcp_server_std.METADATA_FILE", json_file):
            result = _migrate_metadata_json_to_sqlite_sync()
            assert result == 0

    def test_non_dict_entries_skipped(self, tmp_path):
        from src.mcp_server_std import _migrate_metadata_json_to_sqlite_sync
        json_file = tmp_path / "metadata.json"
        json_file.write_text(json.dumps({"agent1": "not a dict", "agent2": 42}))
        mock_db = MagicMock()
        with patch("src.mcp_server_std.METADATA_FILE", json_file):
            with patch("src.mcp_server_std._get_metadata_db", return_value=mock_db):
                result = _migrate_metadata_json_to_sqlite_sync()
                assert result == 0

    def test_valid_entries_migrated(self, tmp_path):
        from src.mcp_server_std import _migrate_metadata_json_to_sqlite_sync
        now = datetime.now().isoformat()
        json_file = tmp_path / "metadata.json"
        json_file.write_text(json.dumps({
            "agent1": {"agent_id": "agent1", "status": "active", "created_at": now, "last_update": now},
            "agent2": {"agent_id": "agent2", "status": "active", "created_at": now, "last_update": now},
        }))
        mock_db = MagicMock()
        with patch("src.mcp_server_std.METADATA_FILE", json_file):
            with patch("src.mcp_server_std._get_metadata_db", return_value=mock_db):
                result = _migrate_metadata_json_to_sqlite_sync()
                assert result == 2
                mock_db.upsert_many.assert_called_once()
