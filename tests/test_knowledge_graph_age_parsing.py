"""
Tests for knowledge_graph_age.py parsing utilities.

Tests _parse_agtype_node and _node_to_discovery which are pure data
transformation functions that don't require database connections.
"""

import json
import pytest
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.knowledge_graph import KnowledgeGraphAGE
from src.knowledge_graph import DiscoveryNode, ResponseTo


# ============================================================================
# KnowledgeGraphAGE - init
# ============================================================================

class TestKnowledgeGraphAGEInit:

    def test_default_graph_name(self):
        kg = KnowledgeGraphAGE()
        assert kg.graph_name == "governance_graph"

    def test_custom_graph_name(self):
        kg = KnowledgeGraphAGE(graph_name="test_graph")
        assert kg.graph_name == "test_graph"

    def test_rate_limit(self):
        kg = KnowledgeGraphAGE()
        assert kg.rate_limit_stores_per_hour == 20


# ============================================================================
# _parse_agtype_node
# ============================================================================

class TestParseAgtypeNode:

    def setup_method(self):
        self.kg = KnowledgeGraphAGE()

    def test_none_returns_empty_dict(self):
        assert self.kg._parse_agtype_node(None) == {}

    def test_dict_with_properties(self):
        """AGE vertex structure should extract properties."""
        node = {
            "id": 12345,
            "label": "Discovery",
            "properties": {
                "summary": "Test discovery",
                "agent_id": "test_agent",
                "type": "insight",
            }
        }
        result = self.kg._parse_agtype_node(node)
        assert result["summary"] == "Test discovery"
        assert result["agent_id"] == "test_agent"

    def test_dict_without_properties(self):
        """Dict without properties key should return as-is."""
        node = {"summary": "direct", "type": "note"}
        result = self.kg._parse_agtype_node(node)
        assert result["summary"] == "direct"
        assert result["type"] == "note"

    def test_json_string_input(self):
        """JSON string should be parsed."""
        node_str = json.dumps({
            "id": 1,
            "label": "Discovery",
            "properties": {
                "summary": "From JSON string",
            }
        })
        result = self.kg._parse_agtype_node(node_str)
        assert result["summary"] == "From JSON string"

    def test_invalid_json_string(self):
        """Invalid JSON string should return empty dict."""
        result = self.kg._parse_agtype_node("not valid json {{{")
        assert result == {}

    def test_empty_string(self):
        result = self.kg._parse_agtype_node("")
        assert result == {}

    def test_nested_properties(self):
        """Properties dict with nested data should be preserved."""
        node = {
            "properties": {
                "metadata": {"key": "value"},
                "tags": ["a", "b"],
            }
        }
        result = self.kg._parse_agtype_node(node)
        assert result["metadata"] == {"key": "value"}
        assert result["tags"] == ["a", "b"]

    def test_properties_not_dict(self):
        """If properties is not a dict, return the whole parsed object."""
        node = {"properties": "not a dict", "other": "data"}
        result = self.kg._parse_agtype_node(node)
        assert result["other"] == "data"

    def test_integer_input(self):
        """Non-string, non-dict, non-None should return empty dict."""
        result = self.kg._parse_agtype_node(42)
        assert result == {}


# ============================================================================
# _node_to_discovery
# ============================================================================

class TestNodeToDiscovery:

    def setup_method(self):
        self.kg = KnowledgeGraphAGE()

    def test_empty_dict_returns_none(self):
        assert self.kg._node_to_discovery({}) is None

    def test_missing_id_returns_none(self):
        assert self.kg._node_to_discovery({"summary": "no id"}) is None

    def test_minimal_valid_node(self):
        node = {
            "id": "disc-001",
            "agent_id": "agent_1",
            "summary": "A discovery",
        }
        result = self.kg._node_to_discovery(node)
        assert isinstance(result, DiscoveryNode)
        assert result.id == "disc-001"
        assert result.agent_id == "agent_1"
        assert result.summary == "A discovery"
        assert result.type == "insight"  # default
        assert result.status == "open"  # default

    def test_full_node(self):
        node = {
            "id": "disc-002",
            "agent_id": "agent_2",
            "type": "bug",
            "summary": "Found a bug",
            "details": "Detailed description",
            "tags": ["python", "fix"],
            "severity": "high",
            "timestamp": "2026-02-05T12:00:00",
            "status": "resolved",
            "resolved_at": "2026-02-05T14:00:00",
            "updated_at": "2026-02-05T14:00:00",
        }
        result = self.kg._node_to_discovery(node)
        assert result.type == "bug"
        assert result.severity == "high"
        assert result.status == "resolved"
        assert result.resolved_at == "2026-02-05T14:00:00"

    def test_tags_as_json_string(self):
        """Tags stored as JSON string should be parsed."""
        node = {
            "id": "disc-003",
            "tags": '["a", "b", "c"]',
        }
        result = self.kg._node_to_discovery(node)
        assert result.tags == ["a", "b", "c"]

    def test_tags_invalid_json_string(self):
        """Invalid JSON tags should default to empty list."""
        node = {
            "id": "disc-004",
            "tags": "not json",
        }
        result = self.kg._node_to_discovery(node)
        assert result.tags == []

    def test_metadata_as_json_string(self):
        """Metadata stored as JSON string should be parsed."""
        node = {
            "id": "disc-005",
            "metadata": json.dumps({
                "related_to": ["disc-001"],
                "references_files": ["src/main.py"],
                "confidence": 0.85,
                "provenance": "agent_analysis",
            }),
        }
        result = self.kg._node_to_discovery(node)
        assert result.related_to == ["disc-001"]
        assert result.references_files == ["src/main.py"]
        assert result.confidence == 0.85
        assert result.provenance == "agent_analysis"

    def test_metadata_invalid_json(self):
        """Invalid JSON metadata should be treated as empty."""
        node = {
            "id": "disc-006",
            "metadata": "not json {{{",
        }
        result = self.kg._node_to_discovery(node)
        assert result.related_to == []

    def test_response_to_parsing(self):
        """response_to in metadata should be parsed to ResponseTo."""
        node = {
            "id": "disc-007",
            "metadata": {
                "response_to": {
                    "discovery_id": "disc-001",
                    "response_type": "challenge",
                },
            },
        }
        result = self.kg._node_to_discovery(node)
        assert result.response_to is not None
        assert isinstance(result.response_to, ResponseTo)
        assert result.response_to.discovery_id == "disc-001"
        assert result.response_to.response_type == "challenge"

    def test_response_to_default_type(self):
        """response_to with missing response_type should default to 'extend'."""
        node = {
            "id": "disc-008",
            "metadata": {
                "response_to": {
                    "discovery_id": "disc-002",
                },
            },
        }
        result = self.kg._node_to_discovery(node)
        assert result.response_to.response_type == "extend"

    def test_no_response_to(self):
        """No response_to should result in None."""
        node = {
            "id": "disc-009",
            "metadata": {},
        }
        result = self.kg._node_to_discovery(node)
        assert result.response_to is None
