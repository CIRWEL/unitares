"""End-to-end: full enrichment pipeline leaves metrics carrying grounded + legacy."""
import pytest

# Import enrichments to trigger registration
import src.mcp_handlers.updates.enrichments  # noqa: F401

from src.mcp_handlers.updates.context import UpdateContext
from src.mcp_handlers.updates.pipeline import run_enrichment_pipeline


@pytest.mark.asyncio
async def test_full_pipeline_metrics_carry_grounded_and_legacy():
    """After the full enrichment pipeline runs, metrics has {E,I,S,coherence} grounded + *_legacy."""
    ctx = UpdateContext()
    ctx.arguments = {}
    ctx.agent_id = "grounding-e2e"
    ctx.agent_uuid = "grounding-e2e-uuid"
    ctx.response_text = "end-to-end enrichment pipeline test"
    ctx.complexity = 0.4
    ctx.confidence = 0.7
    ctx.result = {
        "metrics": {
            "E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1,
            "coherence": 0.72,
            "health_status": "ok",
        }
    }
    ctx.response_data = {}

    # Run the full pipeline — every enrichment is fail-safe, so missing fixtures
    # (mcp_server wiring, etc.) will silently skip but grounding should still run.
    await run_enrichment_pipeline(ctx)

    m = ctx.result["metrics"]
    for key in ("E_legacy", "I_legacy", "S_legacy", "coherence_legacy"):
        assert key in m, f"metrics missing {key}"
    assert "V_legacy" not in m  # V is not dual-computed in Phase 1
    for key in ("e_source", "i_source", "s_source", "coherence_source"):
        assert key in m
        assert m[key] in {
            "heuristic", "resource", "manifold", "logprob",
            "multisample", "fep", "kl"
        }
    for key in ("E", "I", "S", "coherence"):
        assert isinstance(m[key], (int, float))
        assert 0.0 <= m[key] <= 1.0


@pytest.mark.asyncio
async def test_full_pipeline_preserves_legacy_values_exactly():
    """The *_legacy values must equal the originals before the pipeline ran."""
    ctx = UpdateContext()
    ctx.arguments = {}
    ctx.result = {
        "metrics": {
            "E": 0.55, "I": 0.66, "S": 0.33, "V": 0.05,
            "coherence": 0.77,
        }
    }
    ctx.response_data = {}

    await run_enrichment_pipeline(ctx)

    m = ctx.result["metrics"]
    assert m["E_legacy"] == 0.55
    assert m["I_legacy"] == 0.66
    assert m["S_legacy"] == 0.33
    assert m["coherence_legacy"] == 0.77
    # V unchanged
    assert m["V"] == 0.05
