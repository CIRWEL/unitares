"""Helpers for final process_agent_update response assembly."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Sequence

from mcp.types import TextContent

from src.logging_utils import get_logger
from src.services.identity_payloads import attach_identity_handles

logger = get_logger(__name__)


def build_process_update_response_data(
    *,
    result: Dict[str, Any],
    agent_id: str,
    public_agent_id: str | None,
    display_name: str | None,
    identity_assurance: Any,
) -> Dict[str, Any]:
    """Build the base response payload before enrichments and mode filtering."""
    response_data = result.copy()
    response_data["agent_id"] = agent_id
    attach_identity_handles(
        response_data,
        agent_uuid=agent_id,
        public_agent_id=public_agent_id,
        display_name=display_name,
    )
    response_data["identity_assurance"] = identity_assurance
    return response_data


def serialize_process_update_response(
    *,
    response_data: Dict[str, Any],
    agent_uuid: str,
    arguments: Dict[str, Any],
    fallback_result: Dict[str, Any],
    serializer=None,
) -> Sequence[TextContent]:
    """Serialize the final process_agent_update payload with a safe fallback."""
    try:
        if serializer is not None:
            return serializer(response_data, agent_id=agent_uuid, arguments=arguments)
        payload = {"success": True, "server_time": datetime.now().isoformat(), **response_data}
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]
    except Exception as serialization_error:
        logger.error(f"Failed to serialize response: {serialization_error}", exc_info=True)
        metrics = fallback_result.get("metrics", {})
        fallback_payload = {
            "success": True,
            "status": fallback_result.get("status", "unknown"),
            "decision": fallback_result.get("decision", {}),
            "metrics": {
                "E": float(metrics.get("E", 0)),
                "I": float(metrics.get("I", 0)),
                "S": float(metrics.get("S", 0)),
                "V": float(metrics.get("V", 0)),
                "coherence": float(metrics.get("coherence", 0)),
                "risk_score": float(metrics.get("risk_score", 0))
            },
            "_warning": "Response serialization had issues - some fields may be missing"
        }
        try:
            fallback_text = json.JSONEncoder(ensure_ascii=False).encode(fallback_payload)
        except Exception:
            fallback_text = (
                '{"success":true,"status":"unknown","decision":{},'
                '"metrics":{"E":0.0,"I":0.0,"S":0.0,"V":0.0,"coherence":0.0,"risk_score":0.0},'
                '"_warning":"Response serialization had issues - some fields may be missing"}'
            )
        return [TextContent(
            type="text",
            text=fallback_text
        )]
