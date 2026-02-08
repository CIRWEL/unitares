"""
Tests for src/knowledge_db.py - Pure functions and SQLite-backed KnowledgeGraphDB.

Tests cover:
- ResponseTo dataclass
- DiscoveryNode dataclass: to_dict, from_dict, roundtrip
- _cosine_similarity (pure math)
- KnowledgeGraphDB: CRUD, query, FTS, graph edges, stats, rate limiting,
  find_similar, get_agent_discoveries, get_related_discoveries,
  get_response_chain, find_agents_with_similar_interests,
  semantic_search, health check (all using tmp_path SQLite)
"""

import pytest
import pytest_asyncio
import asyncio
import math
import os
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge_db import (
    ResponseTo,
    DiscoveryNode,
    KnowledgeGraphDB,
)


# ============================================================================
# ResponseTo dataclass
# ============================================================================

class TestResponseTo:

    def test_creation(self):
        rt = ResponseTo(discovery_id="disc-1", response_type="extend")
        assert rt.discovery_id == "disc-1"
        assert rt.response_type == "extend"

    def test_valid_response_types(self):
        for rt_type in ["extend", "question", "disagree", "support"]:
            rt = ResponseTo(discovery_id="d", response_type=rt_type)
            assert rt.response_type == rt_type

    def test_equality(self):
        rt1 = ResponseTo(discovery_id="d1", response_type="extend")
        rt2 = ResponseTo(discovery_id="d1", response_type="extend")
        assert rt1 == rt2

    def test_inequality(self):
        rt1 = ResponseTo(discovery_id="d1", response_type="extend")
        rt2 = ResponseTo(discovery_id="d2", response_type="extend")
        assert rt1 != rt2


# ============================================================================
# DiscoveryNode dataclass
# ============================================================================

class TestDiscoveryNode:

    def _make_node(self, **overrides):
        defaults = dict(
            id="disc-001",
            agent_id="agent-1",
            type="insight",
            summary="A test discovery",
            details="Detailed description",
            tags=["test", "unit"],
            severity="medium",
            timestamp="2026-01-15T12:00:00",
            status="open",
            related_to=["disc-002"],
            references_files=["src/main.py"],
        )
        defaults.update(overrides)
        return DiscoveryNode(**defaults)

    def test_creation_defaults(self):
        node = DiscoveryNode(
            id="d1", agent_id="a1", type="bug", summary="Found bug"
        )
        assert node.id == "d1"
        assert node.details == ""
        assert node.tags == []
        assert node.severity is None
        assert node.status == "open"
        assert node.related_to == []
        assert node.response_to is None
        assert node.responses_from == []
        assert node.references_files == []
        assert node.resolved_at is None
        assert node.updated_at is None
        assert node.confidence is None
        assert node.provenance is None
        assert node.provenance_chain is None

    def test_creation_all_fields(self):
        rt = ResponseTo(discovery_id="d0", response_type="extend")
        node = DiscoveryNode(
            id="d1", agent_id="a1", type="insight", summary="test",
            details="long description",
            tags=["alpha", "beta"],
            severity="high",
            timestamp="2026-01-01T00:00:00",
            status="resolved",
            related_to=["d2", "d3"],
            response_to=rt,
            responses_from=["d4"],
            references_files=["file.py"],
            resolved_at="2026-01-02T00:00:00",
            updated_at="2026-01-01T12:00:00",
            confidence=0.95,
            provenance={"E": 0.7, "coherence": 0.5},
            provenance_chain=[{"agent": "a1", "step": 1}],
        )
        assert node.response_to == rt
        assert node.confidence == 0.95
        assert node.provenance["E"] == 0.7

    # --- to_dict ---

    def test_to_dict_basic(self):
        node = self._make_node()
        d = node.to_dict()
        assert d["id"] == "disc-001"
        assert d["agent_id"] == "agent-1"
        assert d["type"] == "insight"
        assert d["summary"] == "A test discovery"
        assert d["details"] == "Detailed description"
        assert d["tags"] == ["test", "unit"]
        assert d["severity"] == "medium"
        assert d["status"] == "open"
        assert d["related_to"] == ["disc-002"]
        assert d["references_files"] == ["src/main.py"]

    def test_to_dict_include_details_true(self):
        node = self._make_node(details="full details here")
        d = node.to_dict(include_details=True)
        assert d["details"] == "full details here"
        assert "has_details" not in d

    def test_to_dict_include_details_false(self):
        node = self._make_node(details="full details here")
        d = node.to_dict(include_details=False)
        assert "details" not in d
        assert d["has_details"] is True
        assert d["details_preview"] == "full details here"

    def test_to_dict_details_false_long_text(self):
        long_text = "x" * 200
        node = self._make_node(details=long_text)
        d = node.to_dict(include_details=False)
        assert d["details_preview"].endswith("...")
        assert len(d["details_preview"]) == 103  # 100 chars + "..."

    def test_to_dict_details_false_empty(self):
        node = self._make_node(details="")
        d = node.to_dict(include_details=False)
        assert "has_details" not in d

    def test_to_dict_with_response_to(self):
        rt = ResponseTo(discovery_id="d0", response_type="support")
        node = self._make_node(response_to=rt)
        d = node.to_dict()
        assert d["response_to"] == {
            "discovery_id": "d0",
            "response_type": "support"
        }

    def test_to_dict_without_response_to(self):
        node = self._make_node(response_to=None)
        d = node.to_dict()
        assert "response_to" not in d

    def test_to_dict_with_responses_from(self):
        node = self._make_node(responses_from=["d5", "d6"])
        d = node.to_dict()
        assert d["responses_from"] == ["d5", "d6"]

    def test_to_dict_without_responses_from(self):
        node = self._make_node(responses_from=[])
        d = node.to_dict()
        assert "responses_from" not in d

    def test_to_dict_with_confidence(self):
        node = self._make_node(confidence=0.85)
        d = node.to_dict()
        assert d["confidence"] == 0.85

    def test_to_dict_without_confidence(self):
        node = self._make_node(confidence=None)
        d = node.to_dict()
        assert "confidence" not in d

    def test_to_dict_with_provenance(self):
        prov = {"E": 0.7, "I": 0.8, "coherence": 0.5}
        node = self._make_node(provenance=prov)
        d = node.to_dict()
        assert d["provenance"] == prov

    def test_to_dict_without_provenance(self):
        node = self._make_node(provenance=None)
        d = node.to_dict()
        assert "provenance" not in d

    def test_to_dict_with_provenance_chain(self):
        chain = [{"agent": "a1", "step": 1}, {"agent": "a2", "step": 2}]
        node = self._make_node(provenance_chain=chain)
        d = node.to_dict()
        assert d["provenance_chain"] == chain

    def test_to_dict_without_provenance_chain(self):
        node = self._make_node(provenance_chain=None)
        d = node.to_dict()
        assert "provenance_chain" not in d

    def test_to_dict_details_false_exactly_100_chars(self):
        text = "a" * 100
        node = self._make_node(details=text)
        d = node.to_dict(include_details=False)
        assert d["details_preview"] == text
        assert not d["details_preview"].endswith("...")

    def test_to_dict_details_false_101_chars(self):
        text = "a" * 101
        node = self._make_node(details=text)
        d = node.to_dict(include_details=False)
        assert d["details_preview"].endswith("...")
        assert len(d["details_preview"]) == 103

    # --- from_dict ---

    def test_from_dict_minimal(self):
        data = {"id": "d1", "agent_id": "a1", "type": "bug", "summary": "oops"}
        node = DiscoveryNode.from_dict(data)
        assert node.id == "d1"
        assert node.details == ""
        assert node.tags == []
        assert node.status == "open"

    def test_from_dict_full(self):
        data = {
            "id": "d1", "agent_id": "a1", "type": "insight", "summary": "discovery",
            "details": "long text", "tags": ["x", "y"], "severity": "high",
            "timestamp": "2026-01-01T00:00:00", "status": "resolved",
            "related_to": ["d2"],
            "response_to": {"discovery_id": "d0", "response_type": "extend"},
            "responses_from": ["d3"], "references_files": ["f.py"],
            "resolved_at": "2026-01-02", "updated_at": "2026-01-01T12:00",
            "confidence": 0.9,
        }
        node = DiscoveryNode.from_dict(data)
        assert node.details == "long text"
        assert node.response_to.discovery_id == "d0"
        assert node.confidence == 0.9

    def test_from_dict_response_to_none(self):
        data = {"id": "d1", "agent_id": "a1", "type": "bug", "summary": "s", "response_to": None}
        node = DiscoveryNode.from_dict(data)
        assert node.response_to is None

    def test_from_dict_response_to_empty_dict(self):
        data = {"id": "d1", "agent_id": "a1", "type": "bug", "summary": "s", "response_to": {}}
        node = DiscoveryNode.from_dict(data)
        assert node.response_to is None

    # --- roundtrip ---

    def test_roundtrip_basic(self):
        node = self._make_node()
        d = node.to_dict()
        restored = DiscoveryNode.from_dict(d)
        assert restored.id == node.id
        assert restored.summary == node.summary
        assert restored.tags == node.tags

    def test_roundtrip_with_response_to(self):
        rt = ResponseTo(discovery_id="d0", response_type="disagree")
        node = self._make_node(response_to=rt, responses_from=["d9"])
        d = node.to_dict()
        restored = DiscoveryNode.from_dict(d)
        assert restored.response_to.discovery_id == "d0"
        assert restored.response_to.response_type == "disagree"

    def test_roundtrip_with_confidence(self):
        node = self._make_node(confidence=0.77)
        d = node.to_dict()
        restored = DiscoveryNode.from_dict(d)
        assert restored.confidence == 0.77


# ============================================================================
# _cosine_similarity
# ============================================================================

class TestCosineSimilarity:

    @pytest.fixture
    def db(self, tmp_path):
        db_path = tmp_path / "test_cosine.db"
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=db_path, enable_embeddings=False)
        yield db
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_identical_vectors(self, db):
        assert abs(db._cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) - 1.0) < 1e-9

    def test_orthogonal_vectors(self, db):
        assert abs(db._cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors(self, db):
        assert abs(db._cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9

    def test_zero_vector_first(self, db):
        assert db._cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_zero_vector_second(self, db):
        assert db._cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0

    def test_both_zero_vectors(self, db):
        assert db._cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_similar_vectors(self, db):
        assert db._cosine_similarity([1.0, 2.0, 3.0], [1.1, 2.1, 3.1]) > 0.99

    def test_single_dimension(self, db):
        assert abs(db._cosine_similarity([5.0], [3.0]) - 1.0) < 1e-9

    def test_negative_values(self, db):
        assert abs(db._cosine_similarity([-1.0, -2.0, -3.0], [-1.0, -2.0, -3.0]) - 1.0) < 1e-9

    def test_known_similarity(self, db):
        expected = 1.0 / math.sqrt(2)
        assert abs(db._cosine_similarity([1.0, 0.0], [1.0, 1.0]) - expected) < 1e-9


# ============================================================================
# KnowledgeGraphDB Init
# ============================================================================

class TestKnowledgeGraphDBInit:

    def test_creates_db_file(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "test.db", enable_embeddings=False)
        assert (tmp_path / "test.db").exists()
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_embeddings_disabled_via_env(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "test.db", enable_embeddings=True)
        assert db.enable_embeddings is False
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_schema_initialized(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "test.db", enable_embeddings=False)
        cursor = db._get_conn().cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "discoveries" in tables
        assert "discovery_tags" in tables
        assert "discovery_edges" in tables
        assert "rate_limits" in tables
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "sub1" / "sub2" / "test.db"
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=db_path, enable_embeddings=False)
        assert db_path.exists()
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_schema_version_table(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "test.db", enable_embeddings=False)
        cursor = db._get_conn().cursor()
        cursor.execute("SELECT version FROM knowledge_schema_version")
        assert cursor.fetchone()[0] == 1
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    def test_migrate_schema_idempotent(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "test.db", enable_embeddings=False)
        db._migrate_schema()
        cursor = db._get_conn().cursor()
        cursor.execute("PRAGMA table_info(discoveries)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "embedding" in columns
        assert "provenance" in columns
        assert "provenance_chain" in columns
        db.close()
        os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)


@pytest.fixture
def kgdb(tmp_path):
    os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
    db = KnowledgeGraphDB(db_path=tmp_path / "test_kg.db", enable_embeddings=False)
    db.rate_limit_stores_per_hour = 10000
    yield db
    db.close()
    os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)


def _make_discovery(**overrides):
    defaults = dict(
        id="disc-test-001", agent_id="agent-1", type="insight",
        summary="Test discovery summary", details="Test discovery details",
        tags=["test"], severity="medium", status="open",
    )
    defaults.update(overrides)
    return DiscoveryNode(**defaults)


# ============================================================================
# CRUD Operations
# ============================================================================

class TestKnowledgeGraphDBCRUD:

    @pytest.mark.asyncio
    async def test_add_and_get_discovery(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        result = await kgdb.get_discovery("disc-test-001")
        assert result is not None
        assert result.id == "disc-test-001"
        assert result.summary == "Test discovery summary"

    @pytest.mark.asyncio
    async def test_get_nonexistent_discovery(self, kgdb):
        assert await kgdb.get_discovery("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_add_discovery_with_tags(self, kgdb):
        await kgdb.add_discovery(_make_discovery(tags=["alpha", "beta", "gamma"]))
        result = await kgdb.get_discovery("disc-test-001")
        assert set(result.tags) == {"alpha", "beta", "gamma"}

    @pytest.mark.asyncio
    async def test_add_discovery_with_response_to(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="parent-001", summary="parent"))
        rt = ResponseTo(discovery_id="parent-001", response_type="extend")
        await kgdb.add_discovery(_make_discovery(id="child-001", summary="child", response_to=rt))
        result = await kgdb.get_discovery("child-001")
        assert result.response_to.discovery_id == "parent-001"
        assert result.response_to.response_type == "extend"

    @pytest.mark.asyncio
    async def test_add_discovery_with_related_to(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2", related_to=["d1"]))
        result = await kgdb.get_discovery("d2")
        assert "d1" in result.related_to

    @pytest.mark.asyncio
    async def test_add_discovery_with_references_files(self, kgdb):
        await kgdb.add_discovery(_make_discovery(references_files=["src/main.py", "tests/test.py"]))
        result = await kgdb.get_discovery("disc-test-001")
        assert result.references_files == ["src/main.py", "tests/test.py"]

    @pytest.mark.asyncio
    async def test_add_discovery_with_confidence(self, kgdb):
        await kgdb.add_discovery(_make_discovery(confidence=0.92))
        result = await kgdb.get_discovery("disc-test-001")
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_add_discovery_no_tags(self, kgdb):
        await kgdb.add_discovery(_make_discovery(tags=[]))
        assert (await kgdb.get_discovery("disc-test-001")).tags == []

    @pytest.mark.asyncio
    async def test_add_discovery_no_details(self, kgdb):
        await kgdb.add_discovery(_make_discovery(details=""))
        assert (await kgdb.get_discovery("disc-test-001")).details == ""

    @pytest.mark.asyncio
    async def test_add_discovery_duplicate_id_raises(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        with pytest.raises(Exception):
            await kgdb.add_discovery(_make_discovery())

    @pytest.mark.asyncio
    async def test_update_discovery(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        assert await kgdb.update_discovery("disc-test-001", {"status": "resolved", "severity": "high"})
        result = await kgdb.get_discovery("disc-test-001")
        assert result.status == "resolved"
        assert result.severity == "high"
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent_discovery(self, kgdb):
        assert await kgdb.update_discovery("nope", {"status": "resolved"}) is False

    @pytest.mark.asyncio
    async def test_update_discovery_tags(self, kgdb):
        await kgdb.add_discovery(_make_discovery(tags=["old"]))
        await kgdb.update_discovery("disc-test-001", {"tags": ["new1", "new2"]})
        assert set((await kgdb.get_discovery("disc-test-001")).tags) == {"new1", "new2"}

    @pytest.mark.asyncio
    async def test_update_discovery_tags_to_empty(self, kgdb):
        await kgdb.add_discovery(_make_discovery(tags=["old_tag"]))
        await kgdb.update_discovery("disc-test-001", {"tags": []})
        assert (await kgdb.get_discovery("disc-test-001")).tags == []

    @pytest.mark.asyncio
    async def test_update_discovery_summary(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        await kgdb.update_discovery("disc-test-001", {"summary": "Updated summary"})
        assert (await kgdb.get_discovery("disc-test-001")).summary == "Updated summary"

    @pytest.mark.asyncio
    async def test_update_discovery_response_to_dict(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="p1", summary="parent"))
        await kgdb.add_discovery(_make_discovery(id="child"))
        await kgdb.update_discovery("child", {
            "response_to": {"discovery_id": "p1", "response_type": "support"}
        })
        result = await kgdb.get_discovery("child")
        assert result.response_to.discovery_id == "p1"
        assert result.response_to.response_type == "support"

    @pytest.mark.asyncio
    async def test_update_discovery_response_to_none(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="p1", summary="parent"))
        rt = ResponseTo(discovery_id="p1", response_type="extend")
        await kgdb.add_discovery(_make_discovery(id="child", response_to=rt))
        await kgdb.update_discovery("child", {"response_to": None})
        assert (await kgdb.get_discovery("child")).response_to is None

    @pytest.mark.asyncio
    async def test_delete_discovery(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        assert await kgdb.delete_discovery("disc-test-001") is True
        assert await kgdb.get_discovery("disc-test-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_discovery(self, kgdb):
        assert await kgdb.delete_discovery("nope") is False

    @pytest.mark.asyncio
    async def test_delete_cascades_tags(self, kgdb):
        await kgdb.add_discovery(_make_discovery(tags=["tag1", "tag2"]))
        await kgdb.delete_discovery("disc-test-001")
        cursor = kgdb._get_conn().cursor()
        cursor.execute("SELECT COUNT(*) FROM discovery_tags WHERE discovery_id = ?", ("disc-test-001",))
        assert cursor.fetchone()[0] == 0


# ============================================================================
# Query Operations
# ============================================================================

class TestKnowledgeGraphDBQuery:

    @pytest.mark.asyncio
    async def test_query_all(self, kgdb):
        for i in range(5):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", summary=f"disc {i}"))
        assert len(await kgdb.query()) == 5

    @pytest.mark.asyncio
    async def test_query_by_agent(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1"))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a2"))
        results = await kgdb.query(agent_id="a1")
        assert len(results) == 1
        assert results[0].agent_id == "a1"

    @pytest.mark.asyncio
    async def test_query_by_type(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", type="bug"))
        await kgdb.add_discovery(_make_discovery(id="d2", type="insight"))
        results = await kgdb.query(type="bug")
        assert len(results) == 1 and results[0].type == "bug"

    @pytest.mark.asyncio
    async def test_query_by_severity(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", severity="low"))
        await kgdb.add_discovery(_make_discovery(id="d2", severity="high"))
        assert len(await kgdb.query(severity="high")) == 1

    @pytest.mark.asyncio
    async def test_query_by_status(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", status="open"))
        await kgdb.add_discovery(_make_discovery(id="d2", status="resolved"))
        assert len(await kgdb.query(status="open")) == 1

    @pytest.mark.asyncio
    async def test_query_by_tags(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", tags=["python"]))
        await kgdb.add_discovery(_make_discovery(id="d2", tags=["rust"]))
        results = await kgdb.query(tags=["python"])
        assert len(results) == 1 and results[0].id == "d1"

    @pytest.mark.asyncio
    async def test_query_by_tags_or_matching(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", tags=["python"]))
        await kgdb.add_discovery(_make_discovery(id="d2", tags=["rust"]))
        await kgdb.add_discovery(_make_discovery(id="d3", tags=["go"]))
        results = await kgdb.query(tags=["python", "rust"])
        assert {r.id for r in results} == {"d1", "d2"}

    @pytest.mark.asyncio
    async def test_query_limit(self, kgdb):
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}"))
        assert len(await kgdb.query(limit=3)) == 3

    @pytest.mark.asyncio
    async def test_query_combined_filters(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", type="bug"))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a1", type="insight"))
        await kgdb.add_discovery(_make_discovery(id="d3", agent_id="a2", type="bug"))
        results = await kgdb.query(agent_id="a1", type="bug")
        assert len(results) == 1 and results[0].id == "d1"

    @pytest.mark.asyncio
    async def test_query_no_results(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", type="insight"))
        assert len(await kgdb.query(type="nonexistent")) == 0

    @pytest.mark.asyncio
    async def test_query_empty_db(self, kgdb):
        assert len(await kgdb.query()) == 0

    @pytest.mark.asyncio
    async def test_query_ordered_by_created_at_desc(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d-old", timestamp="2026-01-01T00:00:00"))
        await kgdb.add_discovery(_make_discovery(id="d-new", timestamp="2026-02-01T00:00:00"))
        results = await kgdb.query()
        assert results[0].id == "d-new" and results[1].id == "d-old"


# ============================================================================
# find_similar
# ============================================================================

class TestKnowledgeGraphDBFindSimilar:

    @pytest.mark.asyncio
    async def test_find_similar_by_tag_overlap(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", tags=["python", "async", "web"]))
        await kgdb.add_discovery(_make_discovery(id="d2", tags=["python", "async"]))
        await kgdb.add_discovery(_make_discovery(id="d3", tags=["rust", "systems"]))
        source = _make_discovery(id="d1", tags=["python", "async", "web"])
        results = await kgdb.find_similar(source)
        assert "d2" in [r.id for r in results]

    @pytest.mark.asyncio
    async def test_find_similar_no_tags(self, kgdb):
        assert await kgdb.find_similar(_make_discovery(id="d1", tags=[])) == []

    @pytest.mark.asyncio
    async def test_find_similar_excludes_self(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", tags=["python"]))
        results = await kgdb.find_similar(_make_discovery(id="d1", tags=["python"]))
        assert "d1" not in [r.id for r in results]

    @pytest.mark.asyncio
    async def test_find_similar_respects_limit(self, kgdb):
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", tags=["common"]))
        assert len(await kgdb.find_similar(_make_discovery(id="source", tags=["common"]), limit=3)) <= 3

    @pytest.mark.asyncio
    async def test_find_similar_ordered_by_overlap(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", tags=["a", "b", "c"]))
        await kgdb.add_discovery(_make_discovery(id="d2", tags=["a"]))
        results = await kgdb.find_similar(_make_discovery(id="source", tags=["a", "b", "c"]))
        assert results[0].id == "d1"


# ============================================================================
# get_agent_discoveries
# ============================================================================

class TestKnowledgeGraphDBGetAgentDiscoveries:

    @pytest.mark.asyncio
    async def test_get_agent_discoveries(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1"))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a1"))
        await kgdb.add_discovery(_make_discovery(id="d3", agent_id="a2"))
        results = await kgdb.get_agent_discoveries("a1")
        assert len(results) == 2
        assert all(r.agent_id == "a1" for r in results)

    @pytest.mark.asyncio
    async def test_get_agent_discoveries_with_limit(self, kgdb):
        for i in range(5):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", agent_id="a1"))
        assert len(await kgdb.get_agent_discoveries("a1", limit=2)) == 2

    @pytest.mark.asyncio
    async def test_get_agent_discoveries_no_results(self, kgdb):
        assert await kgdb.get_agent_discoveries("nonexistent") == []

    @pytest.mark.asyncio
    async def test_get_agent_discoveries_ordered_desc(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d-old", agent_id="a1", timestamp="2026-01-01T00:00:00"))
        await kgdb.add_discovery(_make_discovery(id="d-new", agent_id="a1", timestamp="2026-02-01T00:00:00"))
        assert (await kgdb.get_agent_discoveries("a1"))[0].id == "d-new"


# ============================================================================
# Full-text search
# ============================================================================

class TestKnowledgeGraphDBFullTextSearch:

    @pytest.mark.asyncio
    async def test_fts_by_summary(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="PostgreSQL performance issue"))
        await kgdb.add_discovery(_make_discovery(id="d2", summary="Redis caching strategy"))
        results = await kgdb.full_text_search("PostgreSQL")
        assert any(r.id == "d1" for r in results)

    @pytest.mark.asyncio
    async def test_fts_by_details(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="issue", details="The asyncpg pool was leaking"))
        assert len(await kgdb.full_text_search("asyncpg")) >= 1

    @pytest.mark.asyncio
    async def test_fts_no_results(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="simple test"))
        assert len(await kgdb.full_text_search("xylophone")) == 0

    @pytest.mark.asyncio
    async def test_fts_multi_term_or_default(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="PostgreSQL database optimization"))
        await kgdb.add_discovery(_make_discovery(id="d2", summary="Redis caching layer"))
        await kgdb.add_discovery(_make_discovery(id="d3", summary="Python web framework"))
        results = await kgdb.full_text_search("PostgreSQL Redis")
        result_ids = {r.id for r in results}
        assert "d1" in result_ids and "d2" in result_ids

    @pytest.mark.asyncio
    async def test_fts_respects_limit(self, kgdb):
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", summary=f"common keyword variant {i}"))
        assert len(await kgdb.full_text_search("common", limit=3)) <= 3

    @pytest.mark.asyncio
    async def test_fts_special_characters_handled(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="a test discovery"))
        results = await kgdb.full_text_search("it\'s")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_fts_empty_query(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="test"))
        try:
            results = await kgdb.full_text_search("")
            assert isinstance(results, list)
        except Exception:
            pass


# ============================================================================
# Graph Edge Operations
# ============================================================================

class TestKnowledgeGraphDBAddEdge:

    @pytest.mark.asyncio
    async def test_add_edge_basic(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        assert await kgdb.add_edge("d1", "d2", "related_to") is True

    @pytest.mark.asyncio
    async def test_add_edge_with_all_params(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        assert await kgdb.add_edge(
            "d1", "d2", "response_to", created_by="agent-1",
            response_type="extend", weight=0.9, metadata={"context": "test"}
        ) is True
        cursor = kgdb._get_conn().cursor()
        cursor.execute("SELECT * FROM discovery_edges WHERE src_id=? AND dst_id=? AND edge_type=?",
                       ("d1", "d2", "response_to"))
        row = cursor.fetchone()
        assert row["response_type"] == "extend"
        assert row["weight"] == 0.9
        assert json.loads(row["metadata"])["context"] == "test"

    @pytest.mark.asyncio
    async def test_add_edge_replace_existing(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_edge("d1", "d2", "related_to", weight=1.0)
        await kgdb.add_edge("d1", "d2", "related_to", weight=2.0)
        cursor = kgdb._get_conn().cursor()
        cursor.execute("SELECT weight FROM discovery_edges WHERE src_id=? AND dst_id=?", ("d1", "d2"))
        assert cursor.fetchone()["weight"] == 2.0

    @pytest.mark.asyncio
    async def test_add_edge_no_metadata(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_edge("d1", "d2", "related_to")
        cursor = kgdb._get_conn().cursor()
        cursor.execute("SELECT metadata FROM discovery_edges WHERE src_id=? AND dst_id=?", ("d1", "d2"))
        assert cursor.fetchone()["metadata"] is None


# ============================================================================
# get_related_discoveries
# ============================================================================

class TestKnowledgeGraphDBGetRelatedDiscoveries:

    @pytest.mark.asyncio
    async def test_get_related_outgoing(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_edge("d1", "d2", "related_to")
        results = await kgdb.get_related_discoveries("d1")
        nodes = [(r[0].id, r[1], r[2]) for r in results]
        assert ("d2", "related_to", "outgoing") in nodes

    @pytest.mark.asyncio
    async def test_get_related_incoming(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_edge("d1", "d2", "related_to")
        results = await kgdb.get_related_discoveries("d2")
        nodes = [(r[0].id, r[1], r[2]) for r in results]
        assert ("d1", "related_to", "incoming") in nodes

    @pytest.mark.asyncio
    async def test_get_related_with_edge_type_filter(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_discovery(_make_discovery(id="d3"))
        await kgdb.add_edge("d1", "d2", "related_to")
        await kgdb.add_edge("d1", "d3", "extends")
        results = await kgdb.get_related_discoveries("d1", edge_types=["related_to"])
        assert len(results) == 1 and results[0][0].id == "d2"

    @pytest.mark.asyncio
    async def test_get_related_bidirectional(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_discovery(_make_discovery(id="d3"))
        await kgdb.add_edge("d1", "d2", "related_to")
        await kgdb.add_edge("d3", "d1", "related_to")
        results = await kgdb.get_related_discoveries("d1")
        assert len(results) == 2
        assert {r[2] for r in results} == {"outgoing", "incoming"}

    @pytest.mark.asyncio
    async def test_get_related_respects_limit(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}"))
            await kgdb.add_edge("d1", f"d-{i}", "related_to")
        assert len(await kgdb.get_related_discoveries("d1", limit=3)) <= 3

    @pytest.mark.asyncio
    async def test_get_related_no_edges(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        assert await kgdb.get_related_discoveries("d1") == []


# ============================================================================
# Edge Traversal (response chains, backlinks)
# ============================================================================

class TestKnowledgeGraphDBEdgeTraversal:

    @pytest.mark.asyncio
    async def test_responses_from_backlinks(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="parent", summary="parent node"))
        await kgdb.add_discovery(_make_discovery(
            id="child", summary="child node",
            response_to=ResponseTo(discovery_id="parent", response_type="extend")
        ))
        result = await kgdb.get_discovery("parent")
        assert "child" in result.responses_from

    @pytest.mark.asyncio
    async def test_update_response_to(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="p1", summary="first parent"))
        await kgdb.add_discovery(_make_discovery(id="p2", summary="second parent"))
        await kgdb.add_discovery(_make_discovery(
            id="child", response_to=ResponseTo(discovery_id="p1", response_type="extend")
        ))
        await kgdb.update_discovery("child", {
            "response_to": {"discovery_id": "p2", "response_type": "question"}
        })
        result = await kgdb.get_discovery("child")
        assert result.response_to.discovery_id == "p2"
        assert result.response_to.response_type == "question"

    @pytest.mark.asyncio
    async def test_multiple_responses_from(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="parent"))
        for i in range(3):
            await kgdb.add_discovery(_make_discovery(
                id=f"child-{i}",
                response_to=ResponseTo(discovery_id="parent", response_type="extend")
            ))
        result = await kgdb.get_discovery("parent")
        assert len(result.responses_from) == 3
        for i in range(3):
            assert f"child-{i}" in result.responses_from


# ============================================================================
# get_response_chain (recursive CTE)
# ============================================================================

class TestKnowledgeGraphDBResponseChain:

    @pytest.mark.asyncio
    async def test_response_chain_linear(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="root"))
        await kgdb.add_discovery(_make_discovery(
            id="d2", response_to=ResponseTo(discovery_id="d1", response_type="extend")
        ))
        await kgdb.add_discovery(_make_discovery(
            id="d3", response_to=ResponseTo(discovery_id="d2", response_type="extend")
        ))
        chain = await kgdb.get_response_chain("d1")
        chain_ids = [c.id for c in chain]
        assert "d1" in chain_ids and "d2" in chain_ids and "d3" in chain_ids
        assert chain_ids.index("d1") < chain_ids.index("d2") < chain_ids.index("d3")

    @pytest.mark.asyncio
    async def test_response_chain_single_node(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="standalone"))
        chain = await kgdb.get_response_chain("d1")
        assert len(chain) == 1 and chain[0].id == "d1"

    @pytest.mark.asyncio
    async def test_response_chain_max_depth(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d0", summary="root"))
        for i in range(1, 5):
            await kgdb.add_discovery(_make_discovery(
                id=f"d{i}",
                response_to=ResponseTo(discovery_id=f"d{i-1}", response_type="extend")
            ))
        chain = await kgdb.get_response_chain("d0", max_depth=2)
        chain_ids = [c.id for c in chain]
        assert "d0" in chain_ids and "d1" in chain_ids and "d2" in chain_ids
        assert "d3" not in chain_ids and "d4" not in chain_ids

    @pytest.mark.asyncio
    async def test_response_chain_branching(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="parent", summary="root"))
        for i in range(3):
            await kgdb.add_discovery(_make_discovery(
                id=f"child-{i}",
                response_to=ResponseTo(discovery_id="parent", response_type="extend")
            ))
        chain_ids = {c.id for c in await kgdb.get_response_chain("parent")}
        assert "parent" in chain_ids
        for i in range(3):
            assert f"child-{i}" in chain_ids


# ============================================================================
# find_agents_with_similar_interests
# ============================================================================

class TestKnowledgeGraphDBFindSimilarAgents:

    @pytest.mark.asyncio
    async def test_find_similar_agents_basic(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", tags=["python", "async", "web"]))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a2", tags=["python", "async"]))
        await kgdb.add_discovery(_make_discovery(id="d3", agent_id="a3", tags=["rust"]))
        results = await kgdb.find_agents_with_similar_interests("a1", min_overlap=2)
        agent_ids = [r[0] for r in results]
        assert "a2" in agent_ids and "a3" not in agent_ids

    @pytest.mark.asyncio
    async def test_find_similar_agents_excludes_self(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", tags=["python"]))
        results = await kgdb.find_agents_with_similar_interests("a1", min_overlap=1)
        assert "a1" not in [r[0] for r in results]

    @pytest.mark.asyncio
    async def test_find_similar_agents_min_overlap(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", tags=["python", "async", "web"]))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a2", tags=["python"]))
        assert len(await kgdb.find_agents_with_similar_interests("a1", min_overlap=2)) == 0

    @pytest.mark.asyncio
    async def test_find_similar_agents_overlap_count(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", tags=["python", "async", "web"]))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a2", tags=["python", "async"]))
        results = await kgdb.find_agents_with_similar_interests("a1", min_overlap=1)
        a2_result = [r for r in results if r[0] == "a2"]
        assert len(a2_result) == 1 and a2_result[0][1] == 2

    @pytest.mark.asyncio
    async def test_find_similar_agents_no_discoveries(self, kgdb):
        assert await kgdb.find_agents_with_similar_interests("nonexistent") == []

    @pytest.mark.asyncio
    async def test_find_similar_agents_respects_limit(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", tags=["common"]))
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", agent_id=f"agent-{i}", tags=["common"]))
        assert len(await kgdb.find_agents_with_similar_interests("a1", min_overlap=1, limit=3)) <= 3


# ============================================================================
# get_stats
# ============================================================================

class TestKnowledgeGraphDBStats:

    @pytest.mark.asyncio
    async def test_stats_empty_db(self, kgdb):
        stats = await kgdb.get_stats()
        assert stats["total_discoveries"] == 0
        assert stats["by_agent"] == {} and stats["by_type"] == {} and stats["by_status"] == {}
        assert stats["total_tags"] == 0 and stats["total_agents"] == 0 and stats["total_edges"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_data(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", agent_id="a1", type="bug", status="open", tags=["py"]))
        await kgdb.add_discovery(_make_discovery(id="d2", agent_id="a1", type="insight", status="open", tags=["rs"]))
        await kgdb.add_discovery(_make_discovery(id="d3", agent_id="a2", type="bug", status="resolved", tags=["py"]))
        stats = await kgdb.get_stats()
        assert stats["total_discoveries"] == 3
        assert stats["by_agent"] == {"a1": 2, "a2": 1}
        assert stats["by_type"] == {"bug": 2, "insight": 1}
        assert stats["by_status"] == {"open": 2, "resolved": 1}
        assert stats["total_tags"] == 2 and stats["total_agents"] == 2

    @pytest.mark.asyncio
    async def test_stats_edges_counted(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1"))
        await kgdb.add_discovery(_make_discovery(id="d2"))
        await kgdb.add_edge("d1", "d2", "related_to")
        assert (await kgdb.get_stats())["total_edges"] == 1

    @pytest.mark.asyncio
    async def test_stats_response_edges_counted(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="parent"))
        await kgdb.add_discovery(_make_discovery(
            id="child", response_to=ResponseTo(discovery_id="parent", response_type="extend")
        ))
        assert (await kgdb.get_stats())["total_edges"] >= 1


# ============================================================================
# _check_rate_limit
# ============================================================================

class TestKnowledgeGraphDBRateLimit:

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_limit(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "rl.db", enable_embeddings=False)
        db.rate_limit_stores_per_hour = 5
        try:
            for i in range(3):
                await db.add_discovery(_make_discovery(id=f"d-{i}"))
        finally:
            db.close()
            os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    @pytest.mark.asyncio
    async def test_rate_limit_exceeds_raises(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "rl.db", enable_embeddings=False)
        db.rate_limit_stores_per_hour = 3
        try:
            for i in range(3):
                await db.add_discovery(_make_discovery(id=f"d-{i}"))
            with pytest.raises(ValueError, match="Rate limit exceeded"):
                await db.add_discovery(_make_discovery(id="d-excess"))
        finally:
            db.close()
            os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    @pytest.mark.asyncio
    async def test_rate_limit_message_contains_agent(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "rl.db", enable_embeddings=False)
        db.rate_limit_stores_per_hour = 1
        try:
            await db.add_discovery(_make_discovery(id="d1", agent_id="agent-test-123"))
            with pytest.raises(ValueError, match="agent-test-123"):
                await db.add_discovery(_make_discovery(id="d2", agent_id="agent-test-123"))
        finally:
            db.close()
            os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    @pytest.mark.asyncio
    async def test_rate_limit_per_agent(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "rl.db", enable_embeddings=False)
        db.rate_limit_stores_per_hour = 2
        try:
            await db.add_discovery(_make_discovery(id="d1", agent_id="a1"))
            await db.add_discovery(_make_discovery(id="d2", agent_id="a1"))
            await db.add_discovery(_make_discovery(id="d3", agent_id="a2"))
            with pytest.raises(ValueError, match="Rate limit exceeded"):
                await db.add_discovery(_make_discovery(id="d4", agent_id="a1"))
        finally:
            db.close()
            os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)

    @pytest.mark.asyncio
    async def test_rate_limit_old_entries_cleaned(self, tmp_path):
        os.environ["UNITARES_DISABLE_EMBEDDINGS"] = "true"
        db = KnowledgeGraphDB(db_path=tmp_path / "rl.db", enable_embeddings=False)
        db.rate_limit_stores_per_hour = 5
        try:
            conn = db._get_conn()
            base_time = datetime.now() - timedelta(hours=2)
            for i in range(10):
                old_time = (base_time + timedelta(seconds=i)).isoformat()
                conn.execute("INSERT INTO rate_limits (agent_id, timestamp) VALUES (?, ?)",
                             ("agent-1", old_time))
            conn.commit()
            await db._check_rate_limit("agent-1")
            count = conn.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE agent_id = ?", ("agent-1",)
            ).fetchone()[0]
            assert count == 0
        finally:
            db.close()
            os.environ.pop("UNITARES_DISABLE_EMBEDDINGS", None)


# ============================================================================
# Provenance
# ============================================================================

class TestKnowledgeGraphDBProvenance:

    @pytest.mark.asyncio
    async def test_add_discovery_with_provenance(self, kgdb):
        prov = {"E": 0.7, "I": 0.8, "coherence": 0.52}
        await kgdb.add_discovery(_make_discovery(provenance=prov))
        assert (await kgdb.get_discovery("disc-test-001")).provenance == prov

    @pytest.mark.asyncio
    async def test_add_discovery_with_provenance_chain(self, kgdb):
        chain = [{"agent": "a1", "step": 1}, {"agent": "a2", "step": 2}]
        await kgdb.add_discovery(_make_discovery(provenance_chain=chain))
        assert (await kgdb.get_discovery("disc-test-001")).provenance_chain == chain

    @pytest.mark.asyncio
    async def test_add_discovery_no_provenance(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        result = await kgdb.get_discovery("disc-test-001")
        assert result.provenance is None and result.provenance_chain is None


# ============================================================================
# Health Check
# ============================================================================

class TestKnowledgeGraphDBHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check(self, kgdb):
        result = await kgdb.health_check()
        assert result["integrity_check"] == "ok"
        assert result["db_exists"] is True
        assert result["foreign_key_issues"] == 0

    @pytest.mark.asyncio
    async def test_health_check_after_inserts(self, kgdb):
        await kgdb.add_discovery(_make_discovery())
        assert (await kgdb.health_check())["integrity_check"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_db_path_returned(self, kgdb):
        result = await kgdb.health_check()
        assert "db_path" in result and "db_bytes" in result and result["db_bytes"] > 0

    @pytest.mark.asyncio
    async def test_health_check_fts_smoke(self, kgdb):
        result = await kgdb.health_check()
        assert "fts_smoke_count" in result and isinstance(result["fts_smoke_count"], int)


# ============================================================================
# semantic_search (with embeddings disabled - fallback to FTS)
# ============================================================================

class TestKnowledgeGraphDBSemanticSearch:

    @pytest.mark.asyncio
    async def test_semantic_search_falls_back_to_fts(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="PostgreSQL optimization"))
        results = await kgdb.semantic_search("PostgreSQL")
        assert len(results) >= 1
        assert isinstance(results[0], tuple)
        assert results[0][0].id == "d1" and results[0][1] == 1.0

    @pytest.mark.asyncio
    async def test_semantic_search_no_results(self, kgdb):
        await kgdb.add_discovery(_make_discovery(id="d1", summary="PostgreSQL"))
        assert len(await kgdb.semantic_search("xylophone")) == 0

    @pytest.mark.asyncio
    async def test_semantic_search_respects_limit(self, kgdb):
        for i in range(10):
            await kgdb.add_discovery(_make_discovery(id=f"d-{i}", summary=f"common keyword variation {i}"))
        assert len(await kgdb.semantic_search("common", limit=3)) <= 3


# ============================================================================
# load() compatibility
# ============================================================================

class TestKnowledgeGraphDBLoad:

    @pytest.mark.asyncio
    async def test_load_is_noop(self, kgdb):
        await kgdb.load()
