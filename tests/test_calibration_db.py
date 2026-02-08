"""
Comprehensive tests for src/calibration_db.py (SQLite CalibrationDB class).

Tests all public methods of the synchronous CalibrationDB class:
- Schema initialization
- save_state
- load_state
- health_check
- Singleton row constraint (id=1)
- State overwrite behavior
- Edge cases (empty state, large state, unicode)

All tests use tmp_path for isolated real SQLite databases.
"""

import json
from pathlib import Path

import pytest

from src.calibration_db import CalibrationDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cal_db(tmp_path):
    """Create a CalibrationDB instance with a fresh temporary database."""
    db_path = tmp_path / "calibration_test.db"
    return CalibrationDB(db_path)


SAMPLE_STATE = {
    "bins": {
        "0.0-0.1": {"correct": 0, "total": 0},
        "0.1-0.2": {"correct": 1, "total": 3},
        "0.8-0.9": {"correct": 8, "total": 10},
        "0.9-1.0": {"correct": 19, "total": 20},
    },
    "complexity_bins": {
        "low": {"correct": 5, "total": 6},
        "medium": {"correct": 10, "total": 15},
        "high": {"correct": 3, "total": 10},
    },
    "tactical_bins": {
        "code_review": {"correct": 12, "total": 14},
        "refactor": {"correct": 8, "total": 10},
    },
}


# ===========================================================================
# Schema initialization
# ===========================================================================
class TestSchemaInit:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        CalibrationDB(db_path)
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "a" / "b" / "c" / "calibration.db"
        CalibrationDB(db_path)
        assert db_path.parent.exists()

    def test_schema_version_recorded(self, cal_db):
        with cal_db._connect() as conn:
            row = conn.execute(
                "SELECT version FROM schema_version WHERE name = ?;",
                ("calibration_db",),
            ).fetchone()
        assert row is not None
        assert row[0] == CalibrationDB.SCHEMA_VERSION

    def test_tables_exist(self, cal_db):
        with cal_db._connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        assert "calibration_state" in tables
        assert "schema_version" in tables

    def test_reinit_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db1 = CalibrationDB(db_path)
        db1.save_state(SAMPLE_STATE, "2025-06-01T12:00:00")
        # Re-create on same path -- should not lose data
        db2 = CalibrationDB(db_path)
        loaded = db2.load_state()
        assert loaded == SAMPLE_STATE


# ===========================================================================
# save_state
# ===========================================================================
class TestSaveState:
    def test_basic_save(self, cal_db):
        cal_db.save_state(SAMPLE_STATE, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == SAMPLE_STATE

    def test_save_overwrites_previous(self, cal_db):
        state1 = {"bins": {"0.0-0.1": {"correct": 0, "total": 0}}}
        state2 = {"bins": {"0.9-1.0": {"correct": 9, "total": 10}}}

        cal_db.save_state(state1, "2025-06-01T12:00:00")
        cal_db.save_state(state2, "2025-06-01T13:00:00")

        loaded = cal_db.load_state()
        assert loaded == state2

    def test_save_updates_timestamp(self, cal_db):
        cal_db.save_state({"bins": {}}, "2025-06-01T12:00:00")
        cal_db.save_state({"bins": {}}, "2025-06-01T18:00:00")

        with cal_db._connect() as conn:
            row = conn.execute(
                "SELECT updated_at FROM calibration_state WHERE id = 1;"
            ).fetchone()
        assert row[0] == "2025-06-01T18:00:00"

    def test_singleton_constraint(self, cal_db):
        """Only one row ever exists (id=1 CHECK constraint)."""
        cal_db.save_state({"a": 1}, "2025-01-01T00:00:00")
        cal_db.save_state({"b": 2}, "2025-01-02T00:00:00")
        cal_db.save_state({"c": 3}, "2025-01-03T00:00:00")

        with cal_db._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM calibration_state;"
            ).fetchone()[0]
        assert count == 1

    def test_save_empty_state(self, cal_db):
        cal_db.save_state({}, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == {}

    def test_save_nested_state(self, cal_db):
        nested = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": [1, 2, 3, {"key": "value"}],
                    }
                }
            }
        }
        cal_db.save_state(nested, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == nested
        assert loaded["level1"]["level2"]["level3"]["data"][3]["key"] == "value"

    def test_save_large_state(self, cal_db):
        large = {f"bin_{i}": {"correct": i, "total": i + 1} for i in range(500)}
        cal_db.save_state(large, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == large
        assert len(loaded) == 500

    def test_save_with_unicode(self, cal_db):
        state = {"description": "Calibration with special characters and accents"}
        cal_db.save_state(state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == state

    def test_save_with_numeric_values(self, cal_db):
        state = {
            "float_val": 0.123456789,
            "int_val": 42,
            "negative": -0.5,
            "zero": 0,
            "large": 999999999,
        }
        cal_db.save_state(state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded["float_val"] == pytest.approx(0.123456789)
        assert loaded["int_val"] == 42
        assert loaded["negative"] == -0.5

    def test_save_with_boolean_and_null(self, cal_db):
        state = {
            "flag_true": True,
            "flag_false": False,
            "nothing": None,
        }
        cal_db.save_state(state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded["flag_true"] is True
        assert loaded["flag_false"] is False
        assert loaded["nothing"] is None

    def test_save_with_lists(self, cal_db):
        state = {
            "bins": [0.1, 0.2, 0.3, 0.4],
            "labels": ["low", "medium", "high"],
        }
        cal_db.save_state(state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded["bins"] == [0.1, 0.2, 0.3, 0.4]
        assert loaded["labels"] == ["low", "medium", "high"]


# ===========================================================================
# load_state
# ===========================================================================
class TestLoadState:
    def test_load_empty_db_returns_none(self, cal_db):
        loaded = cal_db.load_state()
        assert loaded is None

    def test_load_after_save(self, cal_db):
        cal_db.save_state(SAMPLE_STATE, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded is not None
        assert loaded == SAMPLE_STATE

    def test_load_returns_dict(self, cal_db):
        cal_db.save_state({"key": "value"}, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert isinstance(loaded, dict)

    def test_load_handles_corrupted_json(self, cal_db):
        """If state_json is somehow corrupted, load_state returns None."""
        cal_db.save_state({"valid": True}, "2025-06-01T12:00:00")
        # Manually corrupt the stored JSON
        with cal_db._connect() as conn:
            conn.execute(
                "UPDATE calibration_state SET state_json = 'not valid json' WHERE id = 1;"
            )
        loaded = cal_db.load_state()
        assert loaded is None

    def test_load_multiple_times_same_result(self, cal_db):
        cal_db.save_state(SAMPLE_STATE, "2025-06-01T12:00:00")
        r1 = cal_db.load_state()
        r2 = cal_db.load_state()
        assert r1 == r2

    def test_load_reflects_latest_save(self, cal_db):
        cal_db.save_state({"version": 1}, "2025-06-01T12:00:00")
        assert cal_db.load_state()["version"] == 1

        cal_db.save_state({"version": 2}, "2025-06-01T13:00:00")
        assert cal_db.load_state()["version"] == 2

        cal_db.save_state({"version": 3}, "2025-06-01T14:00:00")
        assert cal_db.load_state()["version"] == 3


# ===========================================================================
# health_check
# ===========================================================================
class TestHealthCheck:
    def test_healthy_empty_db(self, cal_db):
        health = cal_db.health_check()
        assert health["backend"] == "sqlite"
        assert health["db_path"] == str(cal_db.db_path)
        assert health["schema_version"] == CalibrationDB.SCHEMA_VERSION
        assert health["integrity_check"] == "ok"
        assert health["foreign_key_issues"] == 0
        assert health["has_state_row"] is False

    def test_has_state_row_after_save(self, cal_db):
        cal_db.save_state({"test": True}, "2025-06-01T12:00:00")
        health = cal_db.health_check()
        assert health["has_state_row"] is True

    def test_integrity_on_fresh_db(self, cal_db):
        health = cal_db.health_check()
        assert health["integrity_check"] == "ok"

    def test_schema_version_present(self, cal_db):
        health = cal_db.health_check()
        assert health["schema_version"] == 1

    def test_no_fk_issues(self, cal_db):
        health = cal_db.health_check()
        assert health["foreign_key_issues"] == 0

    def test_health_check_returns_dict(self, cal_db):
        health = cal_db.health_check()
        assert isinstance(health, dict)
        expected_keys = {"backend", "db_path", "schema_version", "integrity_check", "foreign_key_issues", "has_state_row"}
        assert set(health.keys()) == expected_keys


# ===========================================================================
# Connection pragmas
# ===========================================================================
class TestConnectionPragmas:
    def test_wal_mode(self, cal_db):
        with cal_db._connect() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_on(self, cal_db):
        with cal_db._connect() as conn:
            fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk == 1


# ===========================================================================
# Cross-instance consistency
# ===========================================================================
class TestCrossInstance:
    def test_two_instances_same_db(self, tmp_path):
        """Two CalibrationDB instances on the same file should share state."""
        db_path = tmp_path / "shared.db"
        db1 = CalibrationDB(db_path)
        db2 = CalibrationDB(db_path)

        db1.save_state({"from": "db1"}, "2025-06-01T12:00:00")
        loaded = db2.load_state()
        assert loaded == {"from": "db1"}

    def test_write_from_second_instance(self, tmp_path):
        db_path = tmp_path / "shared.db"
        db1 = CalibrationDB(db_path)
        db2 = CalibrationDB(db_path)

        db1.save_state({"version": 1}, "2025-06-01T12:00:00")
        db2.save_state({"version": 2}, "2025-06-01T13:00:00")

        # Both should see the latest
        assert db1.load_state() == {"version": 2}
        assert db2.load_state() == {"version": 2}


# ===========================================================================
# Edge cases
# ===========================================================================
class TestEdgeCases:
    def test_save_and_load_empty_string_value(self, cal_db):
        state = {"key": ""}
        cal_db.save_state(state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded["key"] == ""

    def test_save_full_calibration_payload(self, cal_db):
        """Test with a realistic full calibration state payload."""
        full_state = {
            "bins": {
                f"{i/10:.1f}-{(i+1)/10:.1f}": {
                    "correct": i * 2,
                    "total": i * 2 + 1,
                }
                for i in range(10)
            },
            "complexity_bins": {
                "low": {"correct": 45, "total": 50},
                "medium": {"correct": 35, "total": 50},
                "high": {"correct": 25, "total": 50},
            },
            "tactical_bins": {
                "code_review": {"correct": 80, "total": 100},
                "refactor": {"correct": 60, "total": 100},
                "documentation": {"correct": 90, "total": 100},
            },
        }
        cal_db.save_state(full_state, "2025-06-01T12:00:00")
        loaded = cal_db.load_state()
        assert loaded == full_state
        assert loaded["bins"]["0.5-0.6"]["correct"] == 10
        assert loaded["complexity_bins"]["high"]["total"] == 50
        assert loaded["tactical_bins"]["documentation"]["correct"] == 90

    def test_rapid_save_load_cycles(self, cal_db):
        """Rapid save/load cycles should not corrupt data."""
        for i in range(50):
            state = {"iteration": i, "data": list(range(i))}
            cal_db.save_state(state, f"2025-06-01T{i:02d}:00:00")
            loaded = cal_db.load_state()
            assert loaded["iteration"] == i
            assert loaded["data"] == list(range(i))
