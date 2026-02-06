"""
Tests for src/metadata_db.py - SQLite-backed agent metadata store.

Uses tmp_path for database isolation.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.metadata_db import AgentMetadataDB, _json_dumps, _json_loads


# ============================================================================
# _json_dumps / _json_loads helpers
# ============================================================================

class TestJsonHelpers:

    def test_json_dumps_basic(self):
        result = _json_dumps({"key": "value"})
        assert isinstance(result, str)
        assert '"key"' in result

    def test_json_dumps_list(self):
        result = _json_dumps(["a", "b"])
        assert result == '["a", "b"]'

    def test_json_loads_basic(self):
        result = _json_loads('{"key": "value"}', {})
        assert result == {"key": "value"}

    def test_json_loads_none(self):
        result = _json_loads(None, [])
        assert result == []

    def test_json_loads_empty_string(self):
        result = _json_loads("", {"default": True})
        assert result == {"default": True}

    def test_json_loads_corrupt(self):
        result = _json_loads("not valid json {{", [])
        assert result == []

    def test_json_loads_list(self):
        result = _json_loads('["a", "b"]', [])
        assert result == ["a", "b"]


# ============================================================================
# AgentMetadataDB - init
# ============================================================================

class TestAgentMetadataDBInit:

    def test_creates_db(self, tmp_path):
        db_path = tmp_path / "meta.db"
        db = AgentMetadataDB(db_path)
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "sub" / "dir" / "meta.db"
        db = AgentMetadataDB(db_path)
        assert db_path.parent.exists()

    def test_schema_version_set(self, tmp_path):
        db_path = tmp_path / "meta.db"
        db = AgentMetadataDB(db_path)
        health = db.health_check()
        assert health["schema_version"] == AgentMetadataDB.SCHEMA_VERSION


# ============================================================================
# AgentMetadataDB - upsert_many + load_all
# ============================================================================

class TestUpsertAndLoad:

    def test_empty_load(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        result = db.load_all()
        assert result == {}

    def test_upsert_dict(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({
            "agent-1": {
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
                "last_update": "2025-01-01T00:00:00",
                "total_updates": 5,
                "tags": ["test"],
            }
        })
        loaded = db.load_all()
        assert "agent-1" in loaded
        assert loaded["agent-1"]["status"] == "active"
        assert loaded["agent-1"]["total_updates"] == 5
        assert loaded["agent-1"]["tags"] == ["test"]

    def test_upsert_updates_existing(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({
            "agent-1": {
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
                "last_update": "2025-01-01T00:00:00",
                "total_updates": 1,
            }
        })
        db.upsert_many({
            "agent-1": {
                "status": "archived",
                "created_at": "2025-01-01T00:00:00",
                "last_update": "2025-01-02T00:00:00",
                "total_updates": 10,
            }
        })
        loaded = db.load_all()
        assert loaded["agent-1"]["status"] == "archived"
        assert loaded["agent-1"]["total_updates"] == 10

    def test_upsert_multiple(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({
            "agent-1": {
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
                "last_update": "2025-01-01T00:00:00",
            },
            "agent-2": {
                "status": "paused",
                "created_at": "2025-01-02T00:00:00",
                "last_update": "2025-01-02T00:00:00",
            },
        })
        loaded = db.load_all()
        assert len(loaded) == 2
        assert loaded["agent-1"]["status"] == "active"
        assert loaded["agent-2"]["status"] == "paused"

    def test_upsert_empty(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({})
        loaded = db.load_all()
        assert loaded == {}

    def test_default_values(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({
            "agent-1": {
                "status": "active",
                "created_at": "2025-01-01T00:00:00",
                "last_update": "2025-01-01T00:00:00",
            }
        })
        loaded = db.load_all()
        agent = loaded["agent-1"]
        assert agent["tags"] == []
        assert agent["lifecycle_events"] == []
        assert agent["notes"] == ""
        assert agent["health_status"] == "unknown"


# ============================================================================
# AgentMetadataDB - health_check
# ============================================================================

class TestHealthCheck:

    def test_health_check(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        health = db.health_check()
        assert health["backend"] == "sqlite"
        assert health["integrity_check"] == "ok"
        assert health["agent_count"] == 0
        assert health["foreign_key_issues"] == 0

    def test_health_check_with_data(self, tmp_path):
        db = AgentMetadataDB(tmp_path / "meta.db")
        db.upsert_many({
            "a1": {"status": "active", "created_at": "x", "last_update": "x"},
            "a2": {"status": "active", "created_at": "x", "last_update": "x"},
        })
        health = db.health_check()
        assert health["agent_count"] == 2
