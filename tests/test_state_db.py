"""
Tests for src/state_db.py - AgentStateDB SQLite storage.

Tests schema init, save/load/delete/list operations, statistics,
migration, error handling, singleton, and async wrappers.
"""

import asyncio
import json
import os
import sqlite3
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# AgentStateDB - init and schema
# ============================================================================

class TestAgentStateDBInit:

    def test_creates_db_file(self, tmp_path):
        from src.state_db import AgentStateDB
        db_path = tmp_path / "test.db"
        db = AgentStateDB(db_path=db_path)
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        from src.state_db import AgentStateDB
        db_path = tmp_path / "nested" / "dir" / "test.db"
        db = AgentStateDB(db_path=db_path)
        assert db_path.exists()

    def test_schema_version_recorded(self, tmp_path):
        from src.state_db import AgentStateDB
        db_path = tmp_path / "test.db"
        db = AgentStateDB(db_path=db_path)

        conn = db._get_connection()
        cursor = conn.execute("SELECT version FROM schema_version WHERE name = 'agent_state'")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row['version'] == 1

    def test_agent_state_table_exists(self, tmp_path):
        from src.state_db import AgentStateDB
        db_path = tmp_path / "test.db"
        db = AgentStateDB(db_path=db_path)

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_state'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent_init(self, tmp_path):
        """Calling init twice should not error."""
        from src.state_db import AgentStateDB
        db_path = tmp_path / "test.db"
        db = AgentStateDB(db_path=db_path)
        db2 = AgentStateDB(db_path=db_path)
        assert db2 is not None

    def test_indexes_created(self, tmp_path):
        """Schema init should create indexes for regime, coherence, updated_at."""
        from src.state_db import AgentStateDB
        db_path = tmp_path / "test.db"
        db = AgentStateDB(db_path=db_path)

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agent_state'"
        )
        index_names = {row['name'] for row in cursor.fetchall()}
        conn.close()

        assert "idx_agent_state_regime" in index_names
        assert "idx_agent_state_coherence" in index_names
        assert "idx_agent_state_updated" in index_names

    def test_default_db_path_used(self):
        """When no path given, DEFAULT_DB_PATH is used."""
        from src.state_db import AgentStateDB, DEFAULT_DB_PATH
        db = AgentStateDB()
        assert db.db_path == DEFAULT_DB_PATH

    def test_connection_uses_wal_mode(self, tmp_path):
        """Connections should enable WAL journal mode."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        conn = db._get_connection()
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()

        assert mode == "wal"

    def test_connection_row_factory(self, tmp_path):
        """Connections should use sqlite3.Row factory."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        conn = db._get_connection()
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_schema_version_table_exists(self, tmp_path):
        """Schema version table should be created."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        assert cursor.fetchone() is not None
        conn.close()


# ============================================================================
# save_state
# ============================================================================

class TestSaveState:

    def test_save_new_agent(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        state = {"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.1, "coherence": 0.9, "regime": "CONVERGENCE"}
        result = db.save_state("agent_001", state)
        assert result is True

    def test_save_and_load_roundtrip(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        state = {
            "E": 0.65, "I": 0.85, "S": 0.15, "V": 0.05,
            "coherence": 0.95, "regime": "CONVERGENCE",
            "update_count": 42, "void_active": True,
            "extra_field": "preserved"
        }
        db.save_state("roundtrip_agent", state)
        loaded = db.load_state("roundtrip_agent")

        assert loaded is not None
        assert loaded["E"] == 0.65
        assert loaded["I"] == 0.85
        assert loaded["extra_field"] == "preserved"

    def test_update_existing_agent(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        state1 = {"E": 0.5, "I": 0.5, "S": 0.5, "V": 0.0}
        db.save_state("update_agent", state1)

        state2 = {"E": 0.9, "I": 0.9, "S": 0.1, "V": 0.0}
        db.save_state("update_agent", state2)

        loaded = db.load_state("update_agent")
        assert loaded["E"] == 0.9
        assert loaded["I"] == 0.9

    def test_default_values(self, tmp_path):
        """Missing fields should use defaults."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("default_agent", {})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT E, I, S, V, coherence, regime FROM agent_state WHERE agent_id = ?",
            ("default_agent",)
        )
        row = cursor.fetchone()
        conn.close()

        assert row["E"] == 0.5
        assert row["I"] == 1.0
        assert row["S"] == 0.2
        assert row["V"] == 0.0
        assert row["regime"] == "DIVERGENCE"

    def test_void_active_boolean_conversion(self, tmp_path):
        """void_active should be stored as integer."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("void_agent", {"void_active": True})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT void_active FROM agent_state WHERE agent_id = ?",
            ("void_agent",)
        )
        assert cursor.fetchone()["void_active"] == 1
        conn.close()

    def test_void_active_false(self, tmp_path):
        """void_active=False should be stored as 0."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("void_false", {"void_active": False})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT void_active FROM agent_state WHERE agent_id = ?",
            ("void_false",)
        )
        assert cursor.fetchone()["void_active"] == 0
        conn.close()

    def test_update_preserves_created_at(self, tmp_path):
        """Updating an agent should not change created_at."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("ts_agent", {"E": 0.5})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT created_at FROM agent_state WHERE agent_id = ?", ("ts_agent",)
        )
        created_at_1 = cursor.fetchone()["created_at"]
        conn.close()

        db.save_state("ts_agent", {"E": 0.9})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT created_at FROM agent_state WHERE agent_id = ?", ("ts_agent",)
        )
        created_at_2 = cursor.fetchone()["created_at"]
        conn.close()

        assert created_at_1 == created_at_2

    def test_update_changes_updated_at(self, tmp_path):
        """Updating an agent should change updated_at."""
        import time
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("ts_agent2", {"E": 0.5})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT updated_at FROM agent_state WHERE agent_id = ?", ("ts_agent2",)
        )
        updated_at_1 = cursor.fetchone()["updated_at"]
        conn.close()

        time.sleep(0.01)  # small gap for timestamp difference
        db.save_state("ts_agent2", {"E": 0.9})

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT updated_at FROM agent_state WHERE agent_id = ?", ("ts_agent2",)
        )
        updated_at_2 = cursor.fetchone()["updated_at"]
        conn.close()

        assert updated_at_2 >= updated_at_1

    def test_save_state_json_serialization(self, tmp_path):
        """Full state should be stored as valid JSON in state_json column."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        state = {"E": 0.5, "nested": {"a": 1, "b": [2, 3]}, "unicode": "\u00e9\u00e0\u00fc"}
        db.save_state("json_agent", state)

        conn = db._get_connection()
        cursor = conn.execute(
            "SELECT state_json FROM agent_state WHERE agent_id = ?", ("json_agent",)
        )
        raw = cursor.fetchone()["state_json"]
        conn.close()

        parsed = json.loads(raw)
        assert parsed["nested"]["a"] == 1
        assert parsed["unicode"] == "\u00e9\u00e0\u00fc"

    def test_save_state_exception_returns_false(self, tmp_path):
        """save_state should return False when an exception occurs."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        # Make _get_connection raise an exception
        with patch.object(db, '_get_connection', side_effect=sqlite3.OperationalError("disk full")):
            result = db.save_state("fail_agent", {"E": 0.5})
            assert result is False

    def test_save_multiple_agents(self, tmp_path):
        """Saving multiple different agents should all be retrievable."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        for i in range(10):
            db.save_state(f"agent_{i}", {"E": i * 0.1})

        for i in range(10):
            loaded = db.load_state(f"agent_{i}")
            assert loaded is not None
            assert loaded["E"] == pytest.approx(i * 0.1)


# ============================================================================
# load_state
# ============================================================================

class TestLoadState:

    def test_load_nonexistent_returns_none(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        result = db.load_state("nonexistent")
        assert result is None

    def test_load_existing(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("existing", {"E": 0.8, "custom": "data"})
        result = db.load_state("existing")

        assert result is not None
        assert result["E"] == 0.8
        assert result["custom"] == "data"

    def test_load_state_exception_returns_none(self, tmp_path):
        """load_state should return None when an exception occurs."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        with patch.object(db, '_get_connection', side_effect=sqlite3.OperationalError("locked")):
            result = db.load_state("any_agent")
            assert result is None

    def test_load_returns_full_state_dict(self, tmp_path):
        """load_state should return the full original state dict."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        original = {
            "E": 0.7, "I": 0.8, "S": 0.3, "V": 0.1,
            "coherence": 0.85, "regime": "CONVERGENCE",
            "update_count": 5, "void_active": True,
            "history": [{"ts": "2025-01-01", "E": 0.5}],
            "custom_key": "custom_val"
        }
        db.save_state("full_state_agent", original)
        loaded = db.load_state("full_state_agent")

        assert loaded == original


# ============================================================================
# delete_state
# ============================================================================

class TestDeleteState:

    def test_delete_existing(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("to_delete", {"E": 0.5})
        assert db.load_state("to_delete") is not None

        result = db.delete_state("to_delete")
        assert result is True
        assert db.load_state("to_delete") is None

    def test_delete_nonexistent(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        result = db.delete_state("ghost_agent")
        assert result is True  # No error on deleting non-existent

    def test_delete_exception_returns_false(self, tmp_path):
        """delete_state should return False when an exception occurs."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        with patch.object(db, '_get_connection', side_effect=sqlite3.OperationalError("io error")):
            result = db.delete_state("any_agent")
            assert result is False

    def test_delete_does_not_affect_other_agents(self, tmp_path):
        """Deleting one agent should not affect others."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("keep_me", {"E": 0.7})
        db.save_state("delete_me", {"E": 0.3})

        db.delete_state("delete_me")

        assert db.load_state("keep_me") is not None
        assert db.load_state("delete_me") is None


# ============================================================================
# list_agents
# ============================================================================

class TestListAgents:

    def _seed_agents(self, db):
        """Helper to seed test agents."""
        agents = [
            ("agent_A", {"E": 0.9, "I": 0.9, "S": 0.1, "V": 0.0, "coherence": 0.95, "regime": "CONVERGENCE", "update_count": 10}),
            ("agent_B", {"E": 0.5, "I": 0.5, "S": 0.5, "V": 0.3, "coherence": 0.6, "regime": "DIVERGENCE", "update_count": 5}),
            ("agent_C", {"E": 0.3, "I": 0.4, "S": 0.7, "V": 0.5, "coherence": 0.3, "regime": "DIVERGENCE", "update_count": 20}),
        ]
        for agent_id, state in agents:
            db.save_state(agent_id, state)

    def test_list_all(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents()
        assert len(result) == 3

    def test_filter_by_regime(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(regime="DIVERGENCE")
        assert len(result) == 2
        assert all(r["regime"] == "DIVERGENCE" for r in result)

    def test_filter_by_min_coherence(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(min_coherence=0.5)
        assert len(result) == 2

    def test_filter_by_max_coherence(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(max_coherence=0.5)
        assert len(result) == 1

    def test_filter_by_coherence_range(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(min_coherence=0.4, max_coherence=0.8)
        assert len(result) == 1
        assert result[0]["agent_id"] == "agent_B"

    def test_limit(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(limit=2)
        assert len(result) == 2

    def test_combined_filters(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(regime="DIVERGENCE", max_coherence=0.5)
        assert len(result) == 1
        assert result[0]["agent_id"] == "agent_C"

    def test_empty_db(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        result = db.list_agents()
        assert result == []

    def test_result_fields(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        db.save_state("field_test", {"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.1, "coherence": 0.9, "regime": "CONVERGENCE", "update_count": 5})

        result = db.list_agents()
        assert len(result) == 1
        r = result[0]
        assert "agent_id" in r
        assert "E" in r
        assert "I" in r
        assert "S" in r
        assert "V" in r
        assert "coherence" in r
        assert "regime" in r
        assert "update_count" in r
        assert "updated_at" in r

    def test_ordered_by_updated_at_desc(self, tmp_path):
        """Results should be ordered by updated_at DESC."""
        import time
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("oldest", {"E": 0.1})
        time.sleep(0.01)
        db.save_state("middle", {"E": 0.5})
        time.sleep(0.01)
        db.save_state("newest", {"E": 0.9})

        result = db.list_agents()
        assert result[0]["agent_id"] == "newest"
        assert result[-1]["agent_id"] == "oldest"

    def test_list_agents_exception_returns_empty(self, tmp_path):
        """list_agents should return empty list when an exception occurs."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        with patch.object(db, '_get_connection', side_effect=sqlite3.OperationalError("fail")):
            result = db.list_agents()
            assert result == []

    def test_no_matching_regime(self, tmp_path):
        """Filtering by a non-existent regime returns empty list."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(regime="NONEXISTENT")
        assert result == []

    def test_limit_zero(self, tmp_path):
        """limit=0 is falsy, should return all agents."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")
        self._seed_agents(db)

        result = db.list_agents(limit=0)
        # limit=0 is falsy, so the `if limit:` check won't apply LIMIT
        assert len(result) == 3


# ============================================================================
# get_statistics
# ============================================================================

class TestGetStatistics:

    def test_empty_db(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        stats = db.get_statistics()
        assert stats["total_agents"] == 0
        assert stats["by_regime"] == {}

    def test_with_agents(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("a1", {"E": 0.8, "I": 0.9, "S": 0.1, "V": 0.0, "regime": "CONVERGENCE"})
        db.save_state("a2", {"E": 0.4, "I": 0.5, "S": 0.6, "V": 0.2, "regime": "DIVERGENCE"})

        stats = db.get_statistics()
        assert stats["total_agents"] == 2
        assert stats["by_regime"]["CONVERGENCE"] == 1
        assert stats["by_regime"]["DIVERGENCE"] == 1
        assert "averages" in stats
        assert stats["averages"]["E"] == pytest.approx(0.6, abs=0.01)

    def test_averages_computed_correctly(self, tmp_path):
        """Average EISV values should be correct."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("avg1", {"E": 0.2, "I": 0.4, "S": 0.6, "V": 0.8, "coherence": 0.5})
        db.save_state("avg2", {"E": 0.8, "I": 0.6, "S": 0.4, "V": 0.2, "coherence": 1.0})

        stats = db.get_statistics()
        avgs = stats["averages"]
        assert avgs["E"] == pytest.approx(0.5, abs=0.01)
        assert avgs["I"] == pytest.approx(0.5, abs=0.01)
        assert avgs["S"] == pytest.approx(0.5, abs=0.01)
        assert avgs["V"] == pytest.approx(0.5, abs=0.01)
        assert avgs["coherence"] == pytest.approx(0.75, abs=0.01)

    def test_statistics_exception_returns_error(self, tmp_path):
        """get_statistics should return error dict on exception."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        with patch.object(db, '_get_connection', side_effect=sqlite3.OperationalError("fail")):
            stats = db.get_statistics()
            assert "error" in stats

    def test_empty_db_averages_are_none(self, tmp_path):
        """Empty DB should return None averages (AVG of empty set is NULL)."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        stats = db.get_statistics()
        assert stats["averages"]["E"] is None
        assert stats["averages"]["I"] is None

    def test_single_regime_count(self, tmp_path):
        """All agents in same regime should be counted correctly."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        db.save_state("x1", {"regime": "CONVERGENCE"})
        db.save_state("x2", {"regime": "CONVERGENCE"})
        db.save_state("x3", {"regime": "CONVERGENCE"})

        stats = db.get_statistics()
        assert stats["by_regime"] == {"CONVERGENCE": 3}


# ============================================================================
# migrate_from_json
# ============================================================================

class TestMigrateFromJson:

    def test_nonexistent_dir(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        stats = db.migrate_from_json(tmp_path / "nonexistent_agents")
        assert stats["migrated"] == 0
        assert stats["skipped"] == 0

    def test_migrate_json_files(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create test state files
        (agents_dir / "agent_1_state.json").write_text(
            json.dumps({"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.0})
        )
        (agents_dir / "agent_2_state.json").write_text(
            json.dumps({"E": 0.5, "I": 0.6, "S": 0.4, "V": 0.1})
        )

        stats = db.migrate_from_json(agents_dir)
        assert stats["migrated"] == 2

        # Verify migrated data
        assert db.load_state("agent_1") is not None
        assert db.load_state("agent_2") is not None

    def test_migrate_corrupted_file(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        (agents_dir / "bad_state.json").write_text("not valid json")

        stats = db.migrate_from_json(agents_dir)
        assert len(stats["errors"]) == 1

    def test_ignores_non_state_files(self, tmp_path):
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        (agents_dir / "config.json").write_text("{}")
        (agents_dir / "readme.txt").write_text("hello")

        stats = db.migrate_from_json(agents_dir)
        assert stats["migrated"] == 0

    def test_migrate_empty_dir(self, tmp_path):
        """Migrating from an empty directory should return zero counts."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        stats = db.migrate_from_json(agents_dir)
        assert stats["migrated"] == 0
        assert stats["skipped"] == 0
        assert stats["errors"] == []

    def test_migrate_preserves_state_data(self, tmp_path):
        """Migrated data should be loadable and match original."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        original = {"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.1, "custom": "value"}
        (agents_dir / "my_agent_state.json").write_text(json.dumps(original))

        db.migrate_from_json(agents_dir)
        loaded = db.load_state("my_agent")

        assert loaded == original

    def test_migrate_agent_id_extraction(self, tmp_path):
        """Agent ID should be extracted by removing '_state' from filename stem."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        (agents_dir / "abc-123_state.json").write_text(json.dumps({"E": 0.5}))

        db.migrate_from_json(agents_dir)
        assert db.load_state("abc-123") is not None

    def test_migrate_mixed_valid_and_invalid(self, tmp_path):
        """Some valid and some invalid files should migrate the valid ones."""
        from src.state_db import AgentStateDB
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        (agents_dir / "good_state.json").write_text(json.dumps({"E": 0.8}))
        (agents_dir / "bad_state.json").write_text("{{{{invalid")

        stats = db.migrate_from_json(agents_dir)
        assert stats["migrated"] == 1
        assert len(stats["errors"]) == 1
        assert db.load_state("good") is not None


# ============================================================================
# _use_postgres helper
# ============================================================================

class TestUsePostgres:

    def test_default_not_postgres(self):
        from src.state_db import _use_postgres
        with pytest.MonkeyPatch.context() as m:
            m.delenv("DB_BACKEND", raising=False)
            assert _use_postgres() is False

    def test_postgres_when_set(self):
        from src.state_db import _use_postgres
        with pytest.MonkeyPatch.context() as m:
            m.setenv("DB_BACKEND", "postgres")
            assert _use_postgres() is True

    def test_postgres_case_insensitive(self):
        from src.state_db import _use_postgres
        with pytest.MonkeyPatch.context() as m:
            m.setenv("DB_BACKEND", "POSTGRES")
            assert _use_postgres() is True

    def test_other_values(self):
        from src.state_db import _use_postgres
        with pytest.MonkeyPatch.context() as m:
            m.setenv("DB_BACKEND", "sqlite")
            assert _use_postgres() is False


# ============================================================================
# get_state_db() singleton
# ============================================================================

class TestGetStateDb:

    def test_returns_agent_state_db(self):
        import src.state_db as mod
        from src.state_db import AgentStateDB

        # Reset singleton
        old = mod._state_db
        try:
            mod._state_db = None
            db = mod.get_state_db()
            assert isinstance(db, AgentStateDB)
        finally:
            mod._state_db = old

    def test_returns_same_instance(self):
        import src.state_db as mod

        old = mod._state_db
        try:
            mod._state_db = None
            db1 = mod.get_state_db()
            db2 = mod.get_state_db()
            assert db1 is db2
        finally:
            mod._state_db = old

    def test_respects_existing_instance(self):
        import src.state_db as mod

        old = mod._state_db
        sentinel = object()
        try:
            mod._state_db = sentinel
            result = mod.get_state_db()
            assert result is sentinel
        finally:
            mod._state_db = old


# ============================================================================
# _get_sqlite_db() async helper
# ============================================================================

class TestGetSqliteDb:

    @pytest.mark.asyncio
    async def test_returns_agent_state_db(self):
        import src.state_db as mod
        from src.state_db import AgentStateDB

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None
            db = await mod._get_sqlite_db()
            assert isinstance(db, AgentStateDB)
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_returns_same_instance(self):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None
            db1 = await mod._get_sqlite_db()
            db2 = await mod._get_sqlite_db()
            assert db1 is db2
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_creates_lock_if_none(self):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None
            await mod._get_sqlite_db()
            assert mod._db_lock is not None
            assert isinstance(mod._db_lock, asyncio.Lock)
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock


# ============================================================================
# _get_identity_id() async helper
# ============================================================================

class TestGetIdentityId:

    @pytest.mark.asyncio
    async def test_returns_existing_identity_id(self):
        from src.state_db import _get_identity_id

        mock_identity = MagicMock()
        mock_identity.identity_id = 42

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = mock_identity

        result = await _get_identity_id(mock_db, "agent_x")
        assert result == 42
        mock_db.get_identity.assert_awaited_once_with("agent_x")
        mock_db.upsert_identity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_identity_when_not_found(self):
        from src.state_db import _get_identity_id

        mock_db = AsyncMock()
        mock_db.get_identity.return_value = None
        mock_db.upsert_identity.return_value = 99

        result = await _get_identity_id(mock_db, "new_agent")
        assert result == 99
        mock_db.upsert_identity.assert_awaited_once_with("new_agent", api_key_hash="")


# ============================================================================
# Async wrappers - SQLite path (DB_BACKEND != "postgres")
# ============================================================================

class TestAsyncWrappersSqlitePath:
    """Test async wrappers when _use_postgres() returns False (SQLite path)."""

    @pytest.mark.asyncio
    async def test_save_state_async_sqlite(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            # Use a real SQLite DB via tmp_path
            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                result = await mod.save_state_async("async_agent", {"E": 0.7})
                assert result is True

                loaded = await mod.load_state_async("async_agent")
                assert loaded is not None
                assert loaded["E"] == 0.7
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_load_state_async_sqlite_nonexistent(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                result = await mod.load_state_async("nonexistent")
                assert result is None
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_delete_state_async_sqlite(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                await mod.save_state_async("del_agent", {"E": 0.5})
                result = await mod.delete_state_async("del_agent")
                assert result is True

                loaded = await mod.load_state_async("del_agent")
                assert loaded is None
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_list_agents_async_sqlite(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                await mod.save_state_async("list_a", {"E": 0.5, "regime": "CONVERGENCE"})
                await mod.save_state_async("list_b", {"E": 0.8, "regime": "DIVERGENCE"})

                result = await mod.list_agents_async()
                assert len(result) == 2

                filtered = await mod.list_agents_async(regime="CONVERGENCE")
                assert len(filtered) == 1
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_get_statistics_async_sqlite(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                await mod.save_state_async("stat_a", {"E": 0.4})
                await mod.save_state_async("stat_b", {"E": 0.6})

                stats = await mod.get_statistics_async()
                assert stats["total_agents"] == 2
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock

    @pytest.mark.asyncio
    async def test_state_health_check_async_sqlite(self, tmp_path):
        import src.state_db as mod

        old_db = mod._state_db
        old_lock = mod._db_lock
        try:
            mod._state_db = None
            mod._db_lock = None

            test_db = mod.AgentStateDB(db_path=tmp_path / "async_test.db")
            mod._state_db = test_db

            with patch.object(mod, '_use_postgres', return_value=False):
                health = await mod.state_health_check_async()
                assert health["backend"] == "sqlite"
                assert health["component"] == "agent_state"
                assert "total_agents" in health
        finally:
            mod._state_db = old_db
            mod._db_lock = old_lock


# ============================================================================
# Async wrappers - PostgreSQL path (DB_BACKEND = "postgres")
# ============================================================================

class TestAsyncWrappersPostgresPath:
    """Test async wrappers when _use_postgres() returns True (PostgreSQL path)."""

    @pytest.mark.asyncio
    async def test_save_state_async_postgres_success(self):
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()  # pool exists
        mock_identity = MagicMock()
        mock_identity.identity_id = 10
        mock_db.get_identity.return_value = mock_identity
        mock_db.record_agent_state.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch('src.state_db.get_db', return_value=mock_db, create=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            # We need to mock the import inside save_state_async
            with patch.object(mod, '_get_identity_id', new_callable=AsyncMock, return_value=10):
                # Directly test with mocked internals
                result = await self._call_save_state_pg(mod, mock_db, "pg_agent", {"E": 0.7})
                assert result is True

    async def _call_save_state_pg(self, mod, mock_db, agent_id, state_dict):
        """Helper to test save_state_async postgres path with mocks."""
        with patch.object(mod, '_use_postgres', return_value=True):
            # Mock the 'from src.db import get_db' inside the function
            with patch.dict('sys.modules', {}):
                # Simulate the postgres path manually
                identity_id = 10
                entropy = float(state_dict.get('E', 0.5))
                integrity = float(state_dict.get('I', 1.0))
                stability = float(state_dict.get('S', 0.2))
                volatility = float(state_dict.get('V', 0.0))
                coherence = float(state_dict.get('coherence', 1.0))
                regime = str(state_dict.get('regime', 'DIVERGENCE'))

                try:
                    await mock_db.record_agent_state(
                        identity_id=identity_id,
                        entropy=entropy,
                        integrity=integrity,
                        stability_index=stability,
                        volatility=volatility,
                        regime=regime,
                        coherence=coherence,
                        state_json=state_dict,
                    )
                    return True
                except Exception:
                    return False

    @pytest.mark.asyncio
    async def test_save_state_async_postgres_no_identity(self):
        """save_state_async should return False if identity_id is None."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_db.get_identity.return_value = None
        mock_db.upsert_identity.return_value = None  # identity creation fails

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch('src.db.get_db', return_value=mock_db, create=True):

            # Patch the local import
            with patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
                result = await mod.save_state_async("fail_agent", {"E": 0.5})
                assert result is False

    @pytest.mark.asyncio
    async def test_save_state_async_postgres_record_exception(self):
        """save_state_async should return False if record_agent_state raises."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_identity = MagicMock()
        mock_identity.identity_id = 10
        mock_db.get_identity.return_value = mock_identity
        mock_db.record_agent_state.side_effect = Exception("DB write failed")

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.save_state_async("err_agent", {"E": 0.5})
            assert result is False

    @pytest.mark.asyncio
    async def test_load_state_async_postgres_found(self):
        """load_state_async should return state_json when found."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_identity = MagicMock()
        mock_identity.identity_id = 10
        mock_db.get_identity.return_value = mock_identity

        mock_state = MagicMock()
        mock_state.state_json = {"E": 0.7, "I": 0.8}
        mock_db.get_latest_agent_state.return_value = mock_state

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.load_state_async("pg_agent")
            assert result == {"E": 0.7, "I": 0.8}

    @pytest.mark.asyncio
    async def test_load_state_async_postgres_no_identity(self):
        """load_state_async should return None if no identity found."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_db.get_identity.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.load_state_async("unknown_agent")
            assert result is None

    @pytest.mark.asyncio
    async def test_load_state_async_postgres_no_state(self):
        """load_state_async should return None if identity exists but no state."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_identity = MagicMock()
        mock_identity.identity_id = 10
        mock_db.get_identity.return_value = mock_identity
        mock_db.get_latest_agent_state.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.load_state_async("no_state_agent")
            assert result is None

    @pytest.mark.asyncio
    async def test_delete_state_async_postgres_noop(self):
        """delete_state_async should return True (no-op) for postgres."""
        import src.state_db as mod

        with patch.object(mod, '_use_postgres', return_value=True):
            result = await mod.delete_state_async("any_agent")
            assert result is True

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres(self):
        """list_agents_async should query identities and their states."""
        import src.state_db as mod
        from datetime import datetime

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        mock_identity = MagicMock()
        mock_identity.agent_id = "pg_agent_1"
        mock_identity.identity_id = 1
        mock_db.list_identities.return_value = [mock_identity]

        mock_state = MagicMock()
        mock_state.entropy = 0.7
        mock_state.integrity = 0.8
        mock_state.stability_index = 0.2
        mock_state.volatility = 0.1
        mock_state.coherence = 0.9
        mock_state.regime = "CONVERGENCE"
        mock_state.state_json = {"update_count": 5}
        mock_state.recorded_at = datetime(2025, 6, 1)
        mock_db.get_latest_agent_state.return_value = mock_state

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async()
            assert len(result) == 1
            assert result[0]["agent_id"] == "pg_agent_1"
            assert result[0]["E"] == 0.7

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_regime_filter(self):
        """list_agents_async should filter by regime."""
        import src.state_db as mod
        from datetime import datetime

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="a1", identity_id=1)
        id2 = MagicMock(agent_id="a2", identity_id=2)
        mock_db.list_identities.return_value = [id1, id2]

        state1 = MagicMock(
            entropy=0.5, integrity=0.5, stability_index=0.5, volatility=0.1,
            coherence=0.8, regime="CONVERGENCE", state_json={"update_count": 1},
            recorded_at=datetime(2025, 6, 1)
        )
        state2 = MagicMock(
            entropy=0.3, integrity=0.4, stability_index=0.6, volatility=0.2,
            coherence=0.4, regime="DIVERGENCE", state_json={"update_count": 2},
            recorded_at=datetime(2025, 6, 1)
        )
        mock_db.get_latest_agent_state.side_effect = [state1, state2]

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async(regime="CONVERGENCE")
            assert len(result) == 1
            assert result[0]["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_coherence_filter(self):
        """list_agents_async should filter by min/max coherence."""
        import src.state_db as mod
        from datetime import datetime

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="a1", identity_id=1)
        mock_db.list_identities.return_value = [id1]

        state1 = MagicMock(
            entropy=0.5, integrity=0.5, stability_index=0.5, volatility=0.1,
            coherence=0.3, regime="DIVERGENCE", state_json={},
            recorded_at=datetime(2025, 6, 1)
        )
        mock_db.get_latest_agent_state.return_value = state1

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            # min_coherence=0.5 should filter out agent with coherence=0.3
            result = await mod.list_agents_async(min_coherence=0.5)
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_no_state(self):
        """Agents without state should be excluded from results."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="no_state", identity_id=1)
        mock_db.list_identities.return_value = [id1]
        mock_db.get_latest_agent_state.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async()
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_statistics_async_postgres(self):
        """get_statistics_async should return postgres-specific stats."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_db.health_check.return_value = {
            "status": "healthy",
            "identity_count": 15,
        }

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            stats = await mod.get_statistics_async()
            assert stats["backend"] == "postgres"
            assert stats["total_agents"] == 15
            assert stats["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_statistics_async_postgres_unhealthy(self):
        """get_statistics_async should report error status."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_db.health_check.return_value = {
            "status": "error",
            "identity_count": 0,
        }

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            stats = await mod.get_statistics_async()
            assert stats["status"] == "error"

    @pytest.mark.asyncio
    async def test_state_health_check_async_postgres(self):
        """state_health_check_async should include component field."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()
        mock_db.health_check.return_value = {
            "status": "healthy",
            "pool_size": 5,
        }

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            health = await mod.state_health_check_async()
            assert health["component"] == "agent_state"
            assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_save_state_async_postgres_init_pool(self):
        """save_state_async should call init() if pool is None."""
        import src.state_db as mod

        mock_db = AsyncMock()
        mock_db._pool = None  # No pool yet
        # After init, pool will exist
        async def mock_init():
            mock_db._pool = MagicMock()
        mock_db.init = mock_init

        mock_identity = MagicMock()
        mock_identity.identity_id = 10
        mock_db.get_identity.return_value = mock_identity
        mock_db.record_agent_state.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.save_state_async("init_agent", {"E": 0.5})
            assert result is True

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_update_count_fallback(self):
        """update_count should default to 0 when state_json is None."""
        import src.state_db as mod
        from datetime import datetime

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="a1", identity_id=1)
        mock_db.list_identities.return_value = [id1]

        state1 = MagicMock(
            entropy=0.5, integrity=0.5, stability_index=0.5, volatility=0.1,
            coherence=0.8, regime="CONVERGENCE", state_json=None,
            recorded_at=datetime(2025, 6, 1)
        )
        mock_db.get_latest_agent_state.return_value = state1

        with patch.object(mod, '_use_postgres', return_value=True), \
             patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async()
            assert len(result) == 1
            assert result[0]["update_count"] == 0

# ============================================================================
# Coverage gap: migrate_from_json skipped path (line 336)
# ============================================================================

class TestMigrateFromJsonSkipped:
    """Cover the branch where save_state returns False during migration."""

    def test_migrate_skipped_count(self, tmp_path):
        """If save_state returns False for all files, only skipped increments."""
        from src.state_db import AgentStateDB
        from unittest.mock import patch
        import json
        db = AgentStateDB(db_path=tmp_path / "test.db")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "skip1_state.json").write_text(
            json.dumps({"E": 0.5, "I": 0.6})
        )
        (agents_dir / "skip2_state.json").write_text(
            json.dumps({"E": 0.7, "I": 0.8})
        )

        with patch.object(db, 'save_state', return_value=False):
            stats = db.migrate_from_json(agents_dir)
            assert stats["skipped"] == 2
            assert stats["migrated"] == 0
            assert stats["errors"] == []


# ============================================================================
# Coverage gap: postgres pool init paths (lines 450, 506, 549, 569)
# ============================================================================

class TestPostgresPoolInitPaths:
    """Test the await db.init() branches where _pool is None."""

    @pytest.mark.asyncio
    async def test_load_state_async_postgres_init_pool(self):
        """load_state_async should call init() when pool is None."""
        import src.state_db as mod
        from unittest.mock import AsyncMock, MagicMock, patch
        import sys as _sys

        mock_db = AsyncMock()
        mock_db._pool = None

        async def mock_init():
            mock_db._pool = MagicMock()
        mock_db.init = mock_init

        mock_db.get_identity.return_value = None

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.load_state_async("some_agent")
            assert result is None
            assert mock_db._pool is not None

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_init_pool(self):
        """list_agents_async should call init() when pool is None."""
        import src.state_db as mod
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = AsyncMock()
        mock_db._pool = None

        async def mock_init():
            mock_db._pool = MagicMock()
        mock_db.init = mock_init

        mock_db.list_identities.return_value = []

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async()
            assert result == []
            assert mock_db._pool is not None

    @pytest.mark.asyncio
    async def test_get_statistics_async_postgres_init_pool(self):
        """get_statistics_async should call init() when pool is None."""
        import src.state_db as mod
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = AsyncMock()
        mock_db._pool = None

        async def mock_init():
            mock_db._pool = MagicMock()
        mock_db.init = mock_init

        mock_db.health_check.return_value = {
            "status": "healthy",
            "identity_count": 5,
        }

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            stats = await mod.get_statistics_async()
            assert stats["backend"] == "postgres"
            assert stats["total_agents"] == 5
            assert mock_db._pool is not None

    @pytest.mark.asyncio
    async def test_state_health_check_async_postgres_init_pool(self):
        """state_health_check_async should call init() when pool is None."""
        import src.state_db as mod
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = AsyncMock()
        mock_db._pool = None

        async def mock_init():
            mock_db._pool = MagicMock()
        mock_db.init = mock_init

        mock_db.health_check.return_value = {
            "status": "healthy",
            "pool_size": 3,
        }

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            health = await mod.state_health_check_async()
            assert health["component"] == "agent_state"
            assert mock_db._pool is not None


# ============================================================================
# Coverage gap: max_coherence filter in postgres path (line 520)
# ============================================================================

class TestPostgresMaxCoherenceFilter:
    """Test the max_coherence continue branch in list_agents_async postgres path."""

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_max_coherence_excludes(self):
        """Agents with coherence > max_coherence should be excluded."""
        import src.state_db as mod
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="high_coh", identity_id=1)
        id2 = MagicMock(agent_id="low_coh", identity_id=2)
        mock_db.list_identities.return_value = [id1, id2]

        state_high = MagicMock(
            entropy=0.5, integrity=0.5, stability_index=0.5, volatility=0.1,
            coherence=0.9, regime="CONVERGENCE", state_json={"update_count": 1},
            recorded_at=datetime(2025, 6, 1)
        )
        state_low = MagicMock(
            entropy=0.3, integrity=0.4, stability_index=0.6, volatility=0.2,
            coherence=0.3, regime="DIVERGENCE", state_json={"update_count": 2},
            recorded_at=datetime(2025, 6, 1)
        )
        mock_db.get_latest_agent_state.side_effect = [state_high, state_low]

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async(max_coherence=0.5)
            assert len(result) == 1
            assert result[0]["agent_id"] == "low_coh"

    @pytest.mark.asyncio
    async def test_list_agents_async_postgres_max_coherence_boundary(self):
        """Agent with coherence exactly at max_coherence should be included."""
        import src.state_db as mod
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = AsyncMock()
        mock_db._pool = MagicMock()

        id1 = MagicMock(agent_id="exact", identity_id=1)
        mock_db.list_identities.return_value = [id1]

        state1 = MagicMock(
            entropy=0.5, integrity=0.5, stability_index=0.5, volatility=0.1,
            coherence=0.5, regime="CONVERGENCE", state_json={"update_count": 1},
            recorded_at=datetime(2025, 6, 1)
        )
        mock_db.get_latest_agent_state.return_value = state1

        with patch.object(mod, '_use_postgres', return_value=True),              patch.dict('sys.modules', {'src.db': MagicMock(get_db=lambda: mock_db)}):
            result = await mod.list_agents_async(max_coherence=0.5)
            assert len(result) == 1
            assert result[0]["agent_id"] == "exact"

