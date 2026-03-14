"""Tests for the enrichment pipeline registry and runner."""

import asyncio
from unittest.mock import MagicMock

import pytest

# Import enrichments to trigger registration
import src.mcp_handlers.updates.enrichments  # noqa: F401

from src.mcp_handlers.updates.pipeline import (
    get_enrichment_count,
    get_enrichment_names,
    run_enrichment_pipeline,
    _ENRICHMENTS,
)


class TestEnrichmentRegistration:
    def test_all_enrichments_registered(self):
        assert get_enrichment_count() == 26

    def test_enrichment_order_is_unique(self):
        orders = [e.order for e in _ENRICHMENTS]
        assert len(orders) == len(set(orders)), f"Duplicate orders: {orders}"

    def test_ordering_constraints(self):
        names = get_enrichment_names()
        idx = {n: i for i, n in enumerate(names)}
        # state_interpretation before actionable_feedback before llm_coaching
        assert idx["enrich_state_interpretation"] < idx["enrich_actionable_feedback"]
        assert idx["enrich_actionable_feedback"] < idx["enrich_llm_coaching"]
        # mirror_signals runs late
        assert idx["enrich_mirror_signals"] > idx["enrich_websocket_broadcast"]

    def test_enrichments_sorted_by_order(self):
        orders = [e.order for e in _ENRICHMENTS]
        assert orders == sorted(orders)


class TestPipelineRunner:
    @pytest.mark.asyncio
    async def test_pipeline_runner_isolates_failures(self):
        """A failing enrichment must not prevent subsequent ones from running."""
        from src.mcp_handlers.updates.pipeline import (
            _EnrichmentEntry,
            _ENRICHMENTS,
        )

        call_log = []

        def good_before(ctx):
            call_log.append("before")

        def bad(ctx):
            call_log.append("bad")
            raise RuntimeError("boom")

        def good_after(ctx):
            call_log.append("after")

        # Temporarily replace the registry
        original = list(_ENRICHMENTS)
        _ENRICHMENTS.clear()
        _ENRICHMENTS.extend([
            _EnrichmentEntry(fn=good_before, order=1, name="good_before", is_async=False),
            _EnrichmentEntry(fn=bad, order=2, name="bad", is_async=False),
            _EnrichmentEntry(fn=good_after, order=3, name="good_after", is_async=False),
        ])

        try:
            ctx = MagicMock()
            await run_enrichment_pipeline(ctx)
            assert call_log == ["before", "bad", "after"]
        finally:
            _ENRICHMENTS.clear()
            _ENRICHMENTS.extend(original)

    @pytest.mark.asyncio
    async def test_pipeline_runner_handles_async(self):
        from src.mcp_handlers.updates.pipeline import (
            _EnrichmentEntry,
            _ENRICHMENTS,
        )

        call_log = []

        async def async_fn(ctx):
            call_log.append("async")

        def sync_fn(ctx):
            call_log.append("sync")

        original = list(_ENRICHMENTS)
        _ENRICHMENTS.clear()
        _ENRICHMENTS.extend([
            _EnrichmentEntry(fn=sync_fn, order=1, name="sync_fn", is_async=False),
            _EnrichmentEntry(fn=async_fn, order=2, name="async_fn", is_async=True),
        ])

        try:
            ctx = MagicMock()
            await run_enrichment_pipeline(ctx)
            assert call_log == ["sync", "async"]
        finally:
            _ENRICHMENTS.clear()
            _ENRICHMENTS.extend(original)
