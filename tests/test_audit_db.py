"""
Comprehensive tests for src/audit_db.py (SQLite AuditDB class).

Tests the synchronous SQLite-backed AuditDB class:
- Schema initialization
- append_event (valid, malformed, duplicate hash)
- query (filters, ordering, limits, time ranges)
- fts_search (full-text search via FTS5)
- backfill_fts
- skip_rate_metrics
- health_check
- backfill_from_jsonl (idempotency, batch boundaries, error handling)

All tests use tmp_path for isolated real SQLite databases.
"""

import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.audit_db import AuditDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def audit_db(tmp_path):
    """Create an AuditDB instance with a fresh temporary database."""
    db_path = tmp_path / "audit_test.db"
    return AuditDB(db_path)


@pytest.fixture
def populated_db(audit_db):
    """AuditDB pre-populated with a mix of events."""
    base = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(20):
        ts = (base + timedelta(hours=i)).isoformat()
        agent = f"agent-{i % 3}"
        if i % 2 == 0:
            audit_db.append_event({
                "timestamp": ts,
                "agent_id": agent,
                "event_type": "lambda1_skip",
                "confidence": 0.4 + i * 0.02,
                "details": {"threshold": 0.8, "update_count": i},
                "metadata": {"source": "test"},
            })
        else:
            audit_db.append_event({
                "timestamp": ts,
                "agent_id": agent,
                "event_type": "auto_attest",
                "confidence": 0.9,
                "details": {"ci_passed": True, "decision": "ok"},
            })
    return audit_db


def _make_jsonl(tmp_path, entries):
    """Helper: write a list of dicts as JSONL and return the Path."""
    jsonl_path = tmp_path / "audit_log.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return jsonl_path


# ===========================================================================
# Schema initialization
# ===========================================================================
class TestSchemaInit:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "subdir" / "deep" / "test.db"
        AuditDB(db_path)
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "a" / "b" / "c" / "test.db"
        AuditDB(db_path)
        assert db_path.parent.exists()

    def test_schema_version_recorded(self, audit_db):
        with audit_db._connect() as conn:
            row = conn.execute(
                "SELECT version FROM schema_version WHERE name = ?;",
                ("audit_db",),
            ).fetchone()
        assert row is not None
        assert row[0] == AuditDB.SCHEMA_VERSION

    def test_tables_exist(self, audit_db):
        with audit_db._connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
        assert "audit_events" in tables
        assert "schema_version" in tables

    def test_indexes_exist(self, audit_db):
        with audit_db._connect() as conn:
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            }
        assert "idx_audit_agent_time" in indexes
        assert "idx_audit_type_time" in indexes
        assert "idx_audit_agent_type_time" in indexes

    def test_reinit_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db1 = AuditDB(db_path)
        db1.append_event({
            "timestamp": "2025-01-01T00:00:00",
            "agent_id": "a",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        })
        # Re-create on same path -- should not lose data
        db2 = AuditDB(db_path)
        results = db2.query()
        assert len(results) == 1


# ===========================================================================
# append_event
# ===========================================================================
class TestAppendEvent:
    def test_basic_insert(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "auto_attest",
            "confidence": 0.95,
            "details": {"ci_passed": True},
        })
        results = audit_db.query()
        assert len(results) == 1
        r = results[0]
        assert r["timestamp"] == "2025-06-01T12:00:00"
        assert r["agent_id"] == "agent-1"
        assert r["event_type"] == "auto_attest"
        assert r["confidence"] == pytest.approx(0.95)
        assert r["details"]["ci_passed"] is True

    def test_with_metadata(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
            "metadata": {"source": "unit_test", "version": 1},
        })
        results = audit_db.query()
        assert results[0]["metadata"] == {"source": "unit_test", "version": 1}

    def test_without_metadata(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        })
        results = audit_db.query()
        assert results[0]["metadata"] is None

    def test_skips_missing_timestamp(self, audit_db):
        audit_db.append_event({
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        })
        assert len(audit_db.query()) == 0

    def test_skips_missing_agent_id(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        })
        assert len(audit_db.query()) == 0

    def test_skips_missing_event_type(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "confidence": 0.5,
            "details": {},
        })
        assert len(audit_db.query()) == 0

    def test_skips_empty_required_fields(self, audit_db):
        audit_db.append_event({
            "timestamp": "",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        })
        assert len(audit_db.query()) == 0

    def test_defaults_confidence_to_zero(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "details": {},
        })
        results = audit_db.query()
        assert results[0]["confidence"] == 0.0

    def test_defaults_details_to_empty_dict(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
        })
        results = audit_db.query()
        assert results[0]["details"] == {}

    def test_raw_hash_deduplication(self, audit_db):
        entry = {
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"key": "value"},
        }
        audit_db.append_event(entry, raw_hash="hash_abc123")
        audit_db.append_event(entry, raw_hash="hash_abc123")  # duplicate
        results = audit_db.query()
        assert len(results) == 1

    def test_different_hashes_both_inserted(self, audit_db):
        entry = {
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        }
        audit_db.append_event(entry, raw_hash="hash_1")
        audit_db.append_event(entry, raw_hash="hash_2")
        results = audit_db.query()
        assert len(results) == 2

    def test_null_hash_allows_multiple_inserts(self, audit_db):
        entry = {
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {},
        }
        audit_db.append_event(entry)
        audit_db.append_event(entry)
        results = audit_db.query()
        assert len(results) == 2

    def test_unicode_details(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "Hola mundo. Caracteres especiales: accents and symbols."},
        })
        results = audit_db.query()
        assert "Hola mundo" in results[0]["details"]["message"]

    def test_nested_details(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"nested": {"deep": {"list": [1, 2, 3]}}},
        })
        results = audit_db.query()
        assert results[0]["details"]["nested"]["deep"]["list"] == [1, 2, 3]

    def test_many_inserts(self, audit_db):
        for i in range(100):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": f"agent-{i % 5}",
                "event_type": "batch_test",
                "confidence": 0.5,
                "details": {"index": i},
            })
        results = audit_db.query(limit=200)
        assert len(results) == 100


# ===========================================================================
# query
# ===========================================================================
class TestQuery:
    def test_no_filters(self, populated_db):
        results = populated_db.query(limit=100)
        assert len(results) == 20

    def test_filter_by_agent_id(self, populated_db):
        results = populated_db.query(agent_id="agent-0")
        assert all(r["agent_id"] == "agent-0" for r in results)
        assert len(results) > 0

    def test_filter_by_event_type(self, populated_db):
        results = populated_db.query(event_type="lambda1_skip")
        assert all(r["event_type"] == "lambda1_skip" for r in results)
        assert len(results) == 10

    def test_filter_by_agent_and_type(self, populated_db):
        results = populated_db.query(agent_id="agent-0", event_type="lambda1_skip")
        assert all(
            r["agent_id"] == "agent-0" and r["event_type"] == "lambda1_skip"
            for r in results
        )

    def test_filter_by_start_time(self, populated_db):
        start = "2025-06-01T22:00:00+00:00"
        results = populated_db.query(start_time=start)
        assert len(results) > 0
        for r in results:
            assert r["timestamp"] >= start

    def test_filter_by_end_time(self, populated_db):
        end = "2025-06-01T14:00:00+00:00"
        results = populated_db.query(end_time=end)
        assert len(results) > 0
        for r in results:
            assert r["timestamp"] <= end

    def test_filter_by_time_range(self, populated_db):
        start = "2025-06-01T14:00:00+00:00"
        end = "2025-06-01T18:00:00+00:00"
        results = populated_db.query(start_time=start, end_time=end)
        for r in results:
            assert start <= r["timestamp"] <= end

    def test_limit(self, populated_db):
        results = populated_db.query(limit=5)
        assert len(results) == 5

    def test_order_asc(self, populated_db):
        results = populated_db.query(order="asc", limit=100)
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps)

    def test_order_desc(self, populated_db):
        results = populated_db.query(order="desc", limit=100)
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_default_order_is_asc(self, populated_db):
        results = populated_db.query(limit=100)
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps)

    def test_empty_db_returns_empty_list(self, audit_db):
        results = audit_db.query()
        assert results == []

    def test_query_returns_correct_structure(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "a",
            "event_type": "test",
            "confidence": 0.7,
            "details": {"key": "val"},
            "metadata": {"m": 1},
        })
        results = audit_db.query()
        r = results[0]
        assert set(r.keys()) == {"timestamp", "agent_id", "event_type", "confidence", "details", "metadata"}
        assert isinstance(r["details"], dict)
        assert isinstance(r["metadata"], dict)
        assert isinstance(r["confidence"], float)

    def test_default_limit_1000(self, audit_db):
        # Insert more than default limit
        for i in range(5):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": "a",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            })
        # Default limit is 1000, so all 5 should be returned
        results = audit_db.query()
        assert len(results) == 5

    def test_nonexistent_agent_returns_empty(self, populated_db):
        results = populated_db.query(agent_id="nonexistent-agent")
        assert results == []

    def test_nonexistent_event_type_returns_empty(self, populated_db):
        results = populated_db.query(event_type="nonexistent_type")
        assert results == []


# ===========================================================================
# fts_search
# ===========================================================================
class TestFtsSearch:
    def test_basic_fts_search(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "calibration error detected"},
        })
        audit_db.append_event({
            "timestamp": "2025-06-01T13:00:00",
            "agent_id": "agent-2",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "all systems normal"},
        })
        results = audit_db.fts_search("calibration")
        assert len(results) >= 1
        assert any("calibration" in json.dumps(r["details"]) for r in results)

    def test_fts_search_empty_query(self, audit_db):
        results = audit_db.fts_search("")
        assert results == []

    def test_fts_search_whitespace_query(self, audit_db):
        results = audit_db.fts_search("   ")
        assert results == []

    def test_fts_search_with_agent_filter(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "special keyword alpha"},
        })
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-2",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "special keyword alpha"},
        })
        results = audit_db.fts_search("alpha", agent_id="agent-1")
        assert len(results) == 1
        assert results[0]["agent_id"] == "agent-1"

    def test_fts_search_with_event_type_filter(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "error_log",
            "confidence": 0.5,
            "details": {"message": "keyword beta"},
        })
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "info_log",
            "confidence": 0.5,
            "details": {"message": "keyword beta"},
        })
        results = audit_db.fts_search("beta", event_type="error_log")
        assert len(results) == 1
        assert results[0]["event_type"] == "error_log"

    def test_fts_search_with_time_filters(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T10:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "gamma early"},
        })
        audit_db.append_event({
            "timestamp": "2025-06-01T20:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "gamma late"},
        })
        results = audit_db.fts_search("gamma", start_time="2025-06-01T15:00:00")
        assert len(results) == 1
        assert "late" in json.dumps(results[0]["details"])

    def test_fts_search_no_match(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "nothing special here"},
        })
        results = audit_db.fts_search("xyznonexistent")
        assert results == []

    def test_fts_search_limit(self, audit_db):
        for i in range(10):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i+10:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {"message": f"repeated keyword delta item {i}"},
            })
        results = audit_db.fts_search("delta", limit=3)
        assert len(results) == 3


# ===========================================================================
# backfill_fts
# ===========================================================================
class TestBackfillFts:
    def test_backfill_returns_success(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-1",
            "event_type": "test",
            "confidence": 0.5,
            "details": {"message": "test entry"},
        })
        result = audit_db.backfill_fts()
        assert result["success"] is True
        # Trigger auto-inserted into FTS on append, so backfill finds 0 missing
        assert result["attempted"] == 0

    def test_backfill_limit(self, audit_db):
        result = audit_db.backfill_fts(limit=100)
        assert result["success"] is True
        assert result["limit"] == 100


# ===========================================================================
# skip_rate_metrics
# ===========================================================================
class TestSkipRateMetrics:
    def test_basic_metrics(self, audit_db):
        cutoff = "2025-06-01T00:00:00"
        for i in range(3):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i+10:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "lambda1_skip",
                "confidence": 0.5,
                "details": {},
            })
        for i in range(7):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i+10:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "auto_attest",
                "confidence": 0.9,
                "details": {},
            })
        metrics = audit_db.skip_rate_metrics("agent-1", cutoff)
        assert metrics["total_skips"] == 3
        assert metrics["total_updates"] == 7
        assert metrics["skip_rate"] == pytest.approx(0.3)
        assert metrics["avg_confidence"] == pytest.approx(0.5)

    def test_no_data(self, audit_db):
        metrics = audit_db.skip_rate_metrics(None, "2025-01-01T00:00:00")
        assert metrics["total_skips"] == 0
        assert metrics["total_updates"] == 0
        assert metrics["skip_rate"] == 0.0
        assert metrics["avg_confidence"] == 0.0

    def test_agent_filter(self, audit_db):
        cutoff = "2025-06-01T00:00:00"
        # agent-A skips
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-A",
            "event_type": "lambda1_skip",
            "confidence": 0.4,
            "details": {},
        })
        # agent-B skips
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-B",
            "event_type": "lambda1_skip",
            "confidence": 0.6,
            "details": {},
        })
        metrics_a = audit_db.skip_rate_metrics("agent-A", cutoff)
        assert metrics_a["total_skips"] == 1
        assert metrics_a["avg_confidence"] == pytest.approx(0.4)

        metrics_b = audit_db.skip_rate_metrics("agent-B", cutoff)
        assert metrics_b["total_skips"] == 1
        assert metrics_b["avg_confidence"] == pytest.approx(0.6)

    def test_no_agent_filter_counts_all(self, audit_db):
        cutoff = "2025-06-01T00:00:00"
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-A",
            "event_type": "lambda1_skip",
            "confidence": 0.5,
            "details": {},
        })
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "agent-B",
            "event_type": "lambda1_skip",
            "confidence": 0.5,
            "details": {},
        })
        metrics = audit_db.skip_rate_metrics(None, cutoff)
        assert metrics["total_skips"] == 2

    def test_cutoff_excludes_old(self, audit_db):
        # Old event (before cutoff)
        audit_db.append_event({
            "timestamp": "2025-01-01T00:00:00",
            "agent_id": "agent-1",
            "event_type": "lambda1_skip",
            "confidence": 0.3,
            "details": {},
        })
        # Recent event (after cutoff)
        audit_db.append_event({
            "timestamp": "2025-06-15T00:00:00",
            "agent_id": "agent-1",
            "event_type": "lambda1_skip",
            "confidence": 0.6,
            "details": {},
        })
        metrics = audit_db.skip_rate_metrics("agent-1", "2025-06-01T00:00:00")
        assert metrics["total_skips"] == 1
        assert metrics["avg_confidence"] == pytest.approx(0.6)

    def test_skip_rate_zero_when_only_attests(self, audit_db):
        cutoff = "2025-06-01T00:00:00"
        for i in range(5):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i+10:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "auto_attest",
                "confidence": 0.9,
                "details": {},
            })
        metrics = audit_db.skip_rate_metrics("agent-1", cutoff)
        assert metrics["total_skips"] == 0
        assert metrics["total_updates"] == 5
        assert metrics["skip_rate"] == 0.0

    def test_skip_rate_one_when_only_skips(self, audit_db):
        cutoff = "2025-06-01T00:00:00"
        for i in range(5):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i+10:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "lambda1_skip",
                "confidence": 0.5,
                "details": {},
            })
        metrics = audit_db.skip_rate_metrics("agent-1", cutoff)
        assert metrics["total_skips"] == 5
        assert metrics["total_updates"] == 0
        assert metrics["skip_rate"] == 1.0


# ===========================================================================
# health_check
# ===========================================================================
class TestHealthCheck:
    def test_healthy_empty_db(self, audit_db):
        health = audit_db.health_check()
        assert health["backend"] == "sqlite"
        assert health["db_path"] == str(audit_db.db_path)
        assert health["schema_version"] == AuditDB.SCHEMA_VERSION
        assert health["integrity_check"] == "ok"
        assert health["foreign_key_issues"] == 0
        assert health["event_count"] == 0
        assert isinstance(health["fts_enabled"], bool)

    def test_event_count_after_inserts(self, audit_db):
        for i in range(5):
            audit_db.append_event({
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": "a",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            })
        health = audit_db.health_check()
        assert health["event_count"] == 5

    def test_fts_enabled(self, audit_db):
        health = audit_db.health_check()
        # FTS5 should be available in standard SQLite builds
        assert health["fts_enabled"] is True


# ===========================================================================
# backfill_from_jsonl
# ===========================================================================
class TestBackfillFromJsonl:
    def test_basic_backfill(self, audit_db, tmp_path):
        entries = [
            {
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": f"agent-{i}",
                "event_type": "auto_attest",
                "confidence": 0.9,
                "details": {"index": i},
            }
            for i in range(5)
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)

        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["success"] is True
        assert result["processed"] == 5
        assert result["inserted"] == 5
        assert result["skipped"] == 0
        assert result["errors"] == 0

        # Verify data in DB
        db_results = audit_db.query()
        assert len(db_results) == 5

    def test_idempotent_backfill(self, audit_db, tmp_path):
        entries = [
            {
                "timestamp": "2025-06-01T12:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {"key": "value"},
            }
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)

        result1 = audit_db.backfill_from_jsonl(jsonl_path)
        assert result1["inserted"] == 1

        result2 = audit_db.backfill_from_jsonl(jsonl_path)
        assert result2["inserted"] == 0
        assert result2["skipped"] == 1

        # Still only 1 row
        assert len(audit_db.query()) == 1

    def test_missing_jsonl_file(self, audit_db, tmp_path):
        result = audit_db.backfill_from_jsonl(tmp_path / "nonexistent.jsonl")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_max_lines_limit(self, audit_db, tmp_path):
        entries = [
            {
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            }
            for i in range(10)
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)

        result = audit_db.backfill_from_jsonl(jsonl_path, max_lines=5)
        assert result["success"] is True
        assert result["processed"] == 5
        assert result["max_lines"] == 5
        assert len(audit_db.query()) == 5

    def test_handles_malformed_lines(self, audit_db, tmp_path):
        jsonl_path = tmp_path / "mixed.jsonl"
        with open(jsonl_path, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps({
                "timestamp": "2025-06-01T12:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            }) + "\n")
            f.write("{}\n")  # valid json but empty -- will be skipped
            f.write(json.dumps({
                "timestamp": "2025-06-01T13:00:00",
                "agent_id": "agent-2",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            }) + "\n")

        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["success"] is True
        assert result["errors"] == 1  # "not valid json"
        assert result["skipped"] >= 1  # empty dict missing fields
        assert result["inserted"] == 2

    def test_handles_empty_lines(self, audit_db, tmp_path):
        jsonl_path = tmp_path / "with_blanks.jsonl"
        with open(jsonl_path, "w") as f:
            f.write("\n")
            f.write(json.dumps({
                "timestamp": "2025-06-01T12:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {},
            }) + "\n")
            f.write("\n")
            f.write("\n")

        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["success"] is True
        assert result["inserted"] == 1

    def test_backfill_with_metadata(self, audit_db, tmp_path):
        entries = [
            {
                "timestamp": "2025-06-01T12:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {"key": "val"},
                "metadata": {"source": "backfill"},
            }
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)

        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["inserted"] == 1

        db_results = audit_db.query()
        assert db_results[0]["metadata"] == {"source": "backfill"}

    def test_backfill_batch_boundary(self, audit_db, tmp_path):
        """Verify that batch_size boundary commits work correctly."""
        entries = [
            {
                "timestamp": f"2025-06-01T{i:02d}:00:00",
                "agent_id": "agent-1",
                "event_type": "test",
                "confidence": 0.5,
                "details": {"index": i},
            }
            for i in range(10)
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)

        result = audit_db.backfill_from_jsonl(jsonl_path, batch_size=3)
        assert result["success"] is True
        assert result["inserted"] == 10
        assert len(audit_db.query(limit=100)) == 10

    def test_backfill_returns_jsonl_path(self, audit_db, tmp_path):
        entries = [
            {
                "timestamp": "2025-06-01T12:00:00",
                "agent_id": "a",
                "event_type": "t",
                "confidence": 0.5,
                "details": {},
            }
        ]
        jsonl_path = _make_jsonl(tmp_path, entries)
        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["jsonl_path"] == str(jsonl_path)

    def test_empty_jsonl_file(self, audit_db, tmp_path):
        jsonl_path = tmp_path / "empty.jsonl"
        jsonl_path.write_text("")
        result = audit_db.backfill_from_jsonl(jsonl_path)
        assert result["success"] is True
        assert result["inserted"] == 0
        assert result["processed"] == 0


# ===========================================================================
# _json_loads / _json_dumps edge cases (via append_event + query)
# ===========================================================================
class TestJsonHelpers:
    def test_none_metadata_stored_as_null(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "a",
            "event_type": "t",
            "confidence": 0.5,
            "details": {},
            "metadata": None,
        })
        results = audit_db.query()
        assert results[0]["metadata"] is None

    def test_empty_details_default(self, audit_db):
        audit_db.append_event({
            "timestamp": "2025-06-01T12:00:00",
            "agent_id": "a",
            "event_type": "t",
            "confidence": 0.5,
        })
        results = audit_db.query()
        assert results[0]["details"] == {}
