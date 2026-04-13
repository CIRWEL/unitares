"""
Targeted tests for small service modules that were under-covered (dispatch, descriptions).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from src.services.http_dispatch_fallback import execute_http_dispatch_fallback
from src.services.tool_dispatch_service import run_tool_dispatch_pipeline
from src.services.update_response_service import (
    build_process_update_response_data,
    serialize_process_update_response,
)


def test_tool_descriptions_loads_json_dict():
    from src import tool_descriptions as td

    assert isinstance(td.TOOL_DESCRIPTIONS, dict)
    assert len(td.TOOL_DESCRIPTIONS) > 0
    assert "health_check" in td.TOOL_DESCRIPTIONS


@pytest.mark.asyncio
async def test_run_tool_dispatch_pipeline_unknown_tool():
    """Unknown tool returns tool_not_found error payload (covers early exit path)."""
    with patch("src.mcp_handlers.TOOL_HANDLERS", {}):
        result = await run_tool_dispatch_pipeline(
            name="___nonexistent_tool___",
            arguments={"a": 1},
            pre_steps=[],
            post_steps=[],
        )
    assert result is not None
    assert isinstance(result, (list, tuple))
    assert len(result) >= 1
    assert hasattr(result[0], "text")


@pytest.mark.asyncio
async def test_execute_http_dispatch_fallback_delegates_to_pipeline():
    with patch(
        "src.services.tool_dispatch_service.run_tool_dispatch_pipeline",
        new=AsyncMock(return_value=[TextContent(type="text", text="{}")]),
    ) as mock_pipeline:
        out = await execute_http_dispatch_fallback("list_tools", {"x": 1})

    mock_pipeline.assert_awaited_once()
    assert mock_pipeline.call_args.kwargs["name"] == "list_tools"
    assert mock_pipeline.call_args.kwargs["arguments"] == {"x": 1}
    assert "pre_steps" in mock_pipeline.call_args.kwargs
    assert "post_steps" in mock_pipeline.call_args.kwargs
    assert out is not None


def test_build_process_update_response_data_surfaces_prediction_id():
    class _Mon:
        _last_prediction_id = "pred-abc"

    data = build_process_update_response_data(
        result={"status": "ok"},
        agent_id="agent-1",
        identity_assurance={"tier": "strong"},
        monitor=_Mon(),
    )
    assert data["prediction_id"] == "pred-abc"


def test_serialize_process_update_response_uses_custom_serializer():
    def _ser(data, agent_id=None, arguments=None):
        return [TextContent(type="text", text="CUSTOM")]

    seq = serialize_process_update_response(
        response_data={"k": 1},
        agent_uuid="uuid",
        arguments={},
        fallback_result={"status": "x", "decision": {}, "metrics": {}},
        serializer=_ser,
    )
    assert len(seq) == 1
    assert seq[0].text == "CUSTOM"
