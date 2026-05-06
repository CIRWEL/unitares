from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.identity.memory_integration import score_memory_integration
from src.knowledge_graph import DiscoveryNode, ResponseTo


NOW = datetime(2026, 5, 6, tzinfo=timezone.utc)


class FakeKnowledgeGraph:
    def __init__(self, rows_by_agent=None, exc: Exception | None = None):
        self.rows_by_agent = rows_by_agent or {}
        self.exc = exc

    async def get_agent_discoveries(self, agent_id: str, limit: int | None = None):
        if self.exc:
            raise self.exc
        rows = list(self.rows_by_agent.get(agent_id, []))
        if limit is not None:
            return rows[:limit]
        return rows


def _discovery(
    discovery_id: str,
    agent_id: str,
    *,
    response_to: ResponseTo | None = None,
    status: str = "open",
) -> DiscoveryNode:
    return DiscoveryNode(
        id=discovery_id,
        agent_id=agent_id,
        type="insight",
        summary=f"{discovery_id} summary",
        timestamp="2026-05-05T00:00:00+00:00",
        status=status,
        response_to=response_to,
    )


def _parent_rows(count: int = 3) -> list[DiscoveryNode]:
    return [_discovery(f"p-{idx}", "parent") for idx in range(1, count + 1)]


@pytest.mark.asyncio
async def test_score_memory_integration_integrated_candidate():
    graph = FakeKnowledgeGraph(
        {
            "parent": _parent_rows(),
            "successor": [
                _discovery(
                    "s-1",
                    "successor",
                    response_to=ResponseTo("p-1", "extend"),
                ),
                _discovery(
                    "s-2",
                    "successor",
                    response_to=ResponseTo("p-2", "correction"),
                ),
                _discovery("s-3", "successor"),
            ],
        }
    )

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "integrated_candidate"
    assert score.parent_discoveries_seen == 3
    assert score.successor_discoveries_seen == 3
    assert score.cited_parent_discoveries == 2
    assert score.strong_extensions == 2
    assert score.weak_extensions == 0
    assert score.cited_discovery_ids == ["p-1", "p-2"]
    assert score.generated_discovery_ids == ["s-1", "s-2"]
    assert score.calibration_status == "seeded"
    assert score.to_dict()["verdict"] == "integrated_candidate"


@pytest.mark.asyncio
async def test_score_memory_integration_weak_signal():
    graph = FakeKnowledgeGraph(
        {
            "parent": _parent_rows(),
            "successor": [
                _discovery(
                    "s-1",
                    "successor",
                    response_to=ResponseTo("p-1", "support"),
                )
            ],
        }
    )

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "weak_signal"
    assert score.cited_parent_discoveries == 1
    assert score.strong_extensions == 0
    assert score.weak_extensions == 1


@pytest.mark.asyncio
async def test_score_memory_integration_absent_when_parent_corpus_sufficient():
    graph = FakeKnowledgeGraph(
        {
            "parent": _parent_rows(),
            "successor": [
                _discovery("s-1", "successor"),
                _discovery(
                    "s-2",
                    "successor",
                    response_to=ResponseTo("non-parent-discovery", "extend"),
                ),
            ],
        }
    )

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "absent"
    assert score.cited_parent_discoveries == 0
    assert score.strong_extensions == 0
    assert score.generated_discovery_ids == []


@pytest.mark.asyncio
async def test_score_memory_integration_insufficient_parent_memory_takes_precedence():
    graph = FakeKnowledgeGraph(
        {
            "parent": _parent_rows(count=2),
            "successor": [
                _discovery(
                    "s-1",
                    "successor",
                    response_to=ResponseTo("p-1", "extend"),
                ),
                _discovery(
                    "s-2",
                    "successor",
                    response_to=ResponseTo("p-2", "answer"),
                ),
            ],
        }
    )

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "insufficient_parent_memory"
    assert score.parent_discoveries_seen == 2
    assert score.strong_extensions == 2
    assert "parent memory corpus below threshold" in " ".join(score.reasons)


@pytest.mark.asyncio
async def test_score_memory_integration_inconclusive_on_kg_read_failure():
    graph = FakeKnowledgeGraph(exc=RuntimeError("database unavailable"))

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "inconclusive"
    assert score.confidence == 0.0
    assert score.parent_discoveries_seen == 0
    assert "KG read failed" in score.reasons[0]


@pytest.mark.asyncio
async def test_score_memory_integration_excludes_archived_parent_memory():
    graph = FakeKnowledgeGraph(
        {
            "parent": _parent_rows() + [_discovery("p-archived", "parent", status="archived")],
            "successor": [
                _discovery(
                    "s-1",
                    "successor",
                    response_to=ResponseTo("p-archived", "extend"),
                )
            ],
        }
    )

    score = await score_memory_integration("parent", "successor", graph=graph, now=NOW)

    assert score.verdict == "absent"
    assert score.parent_discoveries_seen == 3
    assert score.cited_parent_discoveries == 0
