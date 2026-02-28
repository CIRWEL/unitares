"""
Tests for AgentMetadata in src/mcp_server_std.py.

Tests to_dict, add_lifecycle_event, validate_consistency, and _normalize_http_proxy_base.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agent_state import AgentMetadata, _normalize_http_proxy_base


# ============================================================================
# _normalize_http_proxy_base
# ============================================================================

class TestNormalizeHttpProxyBase:

    def test_strips_v1_tools_call(self):
        assert _normalize_http_proxy_base("http://localhost:8767/v1/tools/call") == "http://localhost:8767"

    def test_strips_v1_tools(self):
        assert _normalize_http_proxy_base("http://localhost:8767/v1/tools") == "http://localhost:8767"

    def test_strips_trailing_slash(self):
        assert _normalize_http_proxy_base("http://localhost:8767/") == "http://localhost:8767"

    def test_plain_url_unchanged(self):
        assert _normalize_http_proxy_base("http://localhost:8767") == "http://localhost:8767"

    def test_empty_string(self):
        assert _normalize_http_proxy_base("") == ""

    def test_none_returns_empty(self):
        assert _normalize_http_proxy_base(None) == ""

    def test_whitespace_stripped(self):
        assert _normalize_http_proxy_base("  http://localhost:8767  ") == "http://localhost:8767"

    def test_preserves_port(self):
        result = _normalize_http_proxy_base("http://example.com:9000/v1/tools/call")
        assert result == "http://example.com:9000"

    def test_preserves_path_before_v1(self):
        result = _normalize_http_proxy_base("http://example.com/mcp/v1/tools/call")
        assert result == "http://example.com/mcp"


# ============================================================================
# AgentMetadata.to_dict
# ============================================================================

class TestAgentMetadataToDict:

    def test_returns_dict(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15T12:00:00",
                            last_update="2026-01-15T12:00:00")
        result = meta.to_dict()
        assert isinstance(result, dict)

    def test_contains_required_fields(self):
        meta = AgentMetadata(agent_id="test-agent", status="active",
                            created_at="2026-01-15T12:00:00",
                            last_update="2026-01-15T12:00:00")
        d = meta.to_dict()
        assert d['agent_id'] == "test-agent"
        assert d['status'] == "active"
        assert d['created_at'] == "2026-01-15T12:00:00"

    def test_default_values(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        d = meta.to_dict()
        assert d['total_updates'] == 0
        assert d['version'] == "v1.0"
        assert d['tags'] == []
        assert d['lifecycle_events'] == []


# ============================================================================
# AgentMetadata.add_lifecycle_event
# ============================================================================

class TestAddLifecycleEvent:

    def test_event_added(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        meta.add_lifecycle_event("created")
        assert len(meta.lifecycle_events) == 1
        assert meta.lifecycle_events[0]['event'] == "created"

    def test_event_has_timestamp(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        meta.add_lifecycle_event("paused")
        assert 'timestamp' in meta.lifecycle_events[0]
        # Verify it's valid ISO format
        datetime.fromisoformat(meta.lifecycle_events[0]['timestamp'])

    def test_reason_optional(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        meta.add_lifecycle_event("resumed")
        assert meta.lifecycle_events[0]['reason'] is None

    def test_reason_provided(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        meta.add_lifecycle_event("paused", reason="User requested")
        assert meta.lifecycle_events[0]['reason'] == "User requested"

    def test_multiple_events_accumulate(self):
        meta = AgentMetadata(agent_id="test", status="active",
                            created_at="2026-01-15", last_update="2026-01-15")
        meta.add_lifecycle_event("created")
        meta.add_lifecycle_event("paused")
        meta.add_lifecycle_event("resumed")
        assert len(meta.lifecycle_events) == 3


# ============================================================================
# AgentMetadata.validate_consistency
# ============================================================================

class TestValidateConsistency:

    def _make_meta(self, **kwargs):
        defaults = dict(
            agent_id="test",
            status="active",
            created_at="2026-01-15T12:00:00",
            last_update="2026-01-15T12:00:00",
            total_updates=0,
        )
        defaults.update(kwargs)
        return AgentMetadata(**defaults)

    def test_valid_empty_metadata(self):
        meta = self._make_meta()
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True
        assert errors == []

    def test_matching_arrays(self):
        meta = self._make_meta(
            total_updates=3,
            recent_update_timestamps=["2026-01-15T12:00:00", "2026-01-15T12:01:00", "2026-01-15T12:02:00"],
            recent_decisions=["proceed", "proceed", "reflect"],
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True

    def test_mismatched_array_lengths(self):
        meta = self._make_meta(
            total_updates=3,
            recent_update_timestamps=["2026-01-15T12:00:00", "2026-01-15T12:01:00"],
            recent_decisions=["proceed", "proceed", "reflect"],
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("mismatched lengths" in e for e in errors)

    def test_total_updates_mismatch(self):
        meta = self._make_meta(
            total_updates=5,
            recent_update_timestamps=["t1", "t2", "t3"],
            recent_decisions=["p", "p", "p"],
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("total_updates" in e for e in errors)

    def test_capped_arrays_valid(self):
        """total_updates > 10, arrays capped at 10 → valid"""
        meta = self._make_meta(
            total_updates=50,
            recent_update_timestamps=[f"2026-01-15T12:{i:02d}:00" for i in range(10)],
            recent_decisions=["proceed"] * 10,
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True

    def test_arrays_exceed_cap(self):
        """total_updates > 10 but arrays > 10 → invalid"""
        meta = self._make_meta(
            total_updates=15,
            recent_update_timestamps=["t"] * 12,
            recent_decisions=["p"] * 12,
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("exceeds cap" in e for e in errors)

    def test_paused_without_paused_at(self):
        meta = self._make_meta(status="paused", paused_at=None)
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("paused_at is None" in e for e in errors)

    def test_paused_with_paused_at(self):
        meta = self._make_meta(status="paused", paused_at="2026-01-15T12:00:00")
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True

    def test_invalid_timestamp_format(self):
        meta = self._make_meta(created_at="not-a-timestamp")
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert any("timestamp format" in e.lower() for e in errors)

    def test_valid_z_timestamp(self):
        meta = self._make_meta(created_at="2026-01-15T12:00:00Z")
        is_valid, errors = meta.validate_consistency()
        assert is_valid is True

    def test_multiple_errors(self):
        meta = self._make_meta(
            status="paused",
            paused_at=None,
            total_updates=3,
            recent_update_timestamps=["t1"],
            recent_decisions=["p", "p"],
        )
        is_valid, errors = meta.validate_consistency()
        assert is_valid is False
        assert len(errors) >= 2
