"""Integration test: grounding enrichment swaps grounded into canonical slots."""
import pytest

from src.mcp_handlers.updates.context import UpdateContext
from src.mcp_handlers.updates.enrichments import enrich_grounding


@pytest.mark.asyncio
async def test_enrichment_swaps_grounded_into_canonical_slots():
    """After enrichment: E/I/S/coherence are grounded; *_legacy hold originals."""
    ctx = UpdateContext()
    ctx.arguments = {}
    ctx.response_text = "hello world"
    ctx.result = {
        "metrics": {
            "E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1,
            "coherence": 0.72,
        }
    }
    ctx.response_data = {}

    await enrich_grounding(ctx)

    m = ctx.result["metrics"]
    # Legacy preserved
    assert m["E_legacy"] == 0.6
    assert m["I_legacy"] == 0.7
    assert m["S_legacy"] == 0.3
    assert m["coherence_legacy"] == 0.72
    # V untouched
    assert "V_legacy" not in m
    assert m["V"] == -0.1
    # Canonical slots have grounded values (heuristic wraps legacy so same numbers here)
    assert m["E"] == 0.6
    assert m["I"] == 0.7
    assert m["S"] == 0.3
    # Coherence uses manifold form — different from legacy 0.72
    assert 0.0 <= m["coherence"] <= 1.0
    # Source annotations
    assert m["e_source"] == "heuristic"
    assert m["i_source"] == "heuristic"
    assert m["s_source"] == "heuristic"
    assert m["coherence_source"] == "manifold"


@pytest.mark.asyncio
async def test_enrichment_resource_form_when_tokens_provided():
    ctx = UpdateContext()
    ctx.arguments = {"response_tokens": 200, "response_seconds": 2.0}
    ctx.result = {"metrics": {"E": 0.5, "I": 0.5, "S": 0.5, "coherence": 0.6}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert ctx.result["metrics"]["e_source"] == "resource"
    assert ctx.result["metrics"]["E_legacy"] == 0.5


@pytest.mark.asyncio
async def test_enrichment_never_raises_on_missing_metrics():
    """Enrichment must be fail-safe — missing metrics dict must not break pipeline."""
    ctx = UpdateContext()
    ctx.result = {}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert isinstance(ctx.result, dict)


@pytest.mark.asyncio
async def test_enrichment_does_not_touch_v():
    """Invariant: V stays exactly as it was — Phase 1 does not ground V."""
    ctx = UpdateContext()
    ctx.result = {"metrics": {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1, "coherence": 0.72}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert ctx.result["metrics"]["V"] == -0.1
    assert "V_legacy" not in ctx.result["metrics"]


@pytest.mark.asyncio
async def test_enrichment_records_agent_class():
    """Agent class is classified and surfaced on the metrics block."""
    from types import SimpleNamespace
    ctx = UpdateContext()
    ctx.meta = SimpleNamespace(label="Lumen", tags=["embodied", "persistent"])
    ctx.result = {"metrics": {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1, "coherence": 0.72}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    # Class is set on ctx and surfaced on metrics
    assert ctx.agent_class == "Lumen"
    assert ctx.result["metrics"]["agent_class"] == "Lumen"


@pytest.mark.asyncio
async def test_enrichment_classifies_unrecognized_as_default():
    from types import SimpleNamespace
    ctx = UpdateContext()
    ctx.meta = SimpleNamespace(label="some_session_agent", tags=[])
    ctx.result = {"metrics": {"E": 0.5, "I": 0.5, "S": 0.5, "coherence": 0.6}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert ctx.agent_class == "default"
    assert ctx.result["metrics"]["agent_class"] == "default"


@pytest.mark.asyncio
async def test_enrichment_handles_missing_meta():
    """Enrichment must not crash when ctx has no meta attribute set."""
    ctx = UpdateContext()
    # ctx.meta defaults to None
    ctx.result = {"metrics": {"E": 0.5, "I": 0.5, "S": 0.5, "coherence": 0.6}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert ctx.agent_class == "default"


@pytest.mark.asyncio
async def test_enrichment_idempotent_on_double_run():
    """Running twice must not chain the swap — *_legacy stays the original legacy."""
    ctx = UpdateContext()
    ctx.result = {"metrics": {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1, "coherence": 0.72}}
    ctx.response_data = {}

    await enrich_grounding(ctx)
    legacy_after_first = {
        k: v for k, v in ctx.result["metrics"].items() if k.endswith("_legacy")
    }
    await enrich_grounding(ctx)
    legacy_after_second = {
        k: v for k, v in ctx.result["metrics"].items() if k.endswith("_legacy")
    }

    assert legacy_after_first == legacy_after_second, "second run must not re-wrap"
