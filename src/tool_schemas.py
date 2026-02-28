"""
Tool Schema Definitions — Single source of truth for MCP tool schemas.

Dynamically built from Pydantic models (inputSchema) + description dict.
Descriptions live in tool_descriptions.py to keep this file compact.
"""

import os
import importlib
import inspect
from typing import Any

from mcp.types import Tool
from pydantic import BaseModel


def _load_pydantic_schemas():
    """Discover all Pydantic *Params models from schema modules."""
    mods = [
        "src.mcp_handlers.schemas.core",
        "src.mcp_handlers.schemas.export",
        "src.mcp_handlers.schemas.lifecycle",
        "src.mcp_handlers.schemas.knowledge",
        "src.mcp_handlers.schemas.dialectic",
        "src.mcp_handlers.schemas.observability",
        "src.mcp_handlers.schemas.pi_orchestration",
        "src.mcp_handlers.schemas.calibration",
        "src.mcp_handlers.schemas.identity",
        "src.mcp_handlers.schemas.admin",
    ]
    all_schemas = {}
    for mod_name in mods:
        mod = importlib.import_module(mod_name)
        for name, obj in inspect.getmembers(mod):
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and name.endswith("Params")
            ):
                tool_name = ""
                for char in getattr(obj, "__name__", ""):
                    if char.isupper():
                        tool_name += "_" + char.lower()
                    else:
                        tool_name += char
                tool_name = tool_name.lstrip("_").replace("_params", "")
                all_schemas[tool_name] = obj
    return all_schemas


PYDANTIC_SCHEMAS = _load_pydantic_schemas()

# Ordered list of tools to register.
# Only tools in this list are exposed via MCP. Pydantic schemas for
# sub-actions (e.g., store_knowledge_graph) exist but are dispatched
# internally by consolidated tools (e.g., knowledge).
TOOL_ORDER = [
    "check_calibration",
    "update_calibration_ground_truth",
    "backfill_calibration_from_dialectic",
    "rebuild_calibration",
    "health_check",
    "get_workspace_health",
    "get_telemetry_metrics",
    "get_tool_usage_stats",
    "get_server_info",
    "get_connection_status",
    "process_agent_update",
    "get_governance_metrics",
    "get_system_history",
    "export_to_file",
    "reset_monitor",
    "list_agents",
    "delete_agent",
    "get_agent_metadata",
    "mark_response_complete",
    "detect_stuck_agents",
    "request_dialectic_review",
    "submit_thesis",
    "submit_antithesis",
    "submit_synthesis",
    "archive_agent",
    "update_agent_metadata",
    "archive_old_test_agents",
    "archive_orphan_agents",
    "simulate_update",
    "get_thresholds",
    "set_thresholds",
    "aggregate_metrics",
    "observe_agent",
    "compare_agents",
    "compare_me_to_similar",
    "outcome_event",
    "detect_anomalies",
    "list_tools",
    "describe_tool",
    "cleanup_stale_locks",
    "validate_file_path",
    "store_knowledge_graph",
    "search_knowledge_graph",
    "get_knowledge_graph",
    "list_knowledge_graph",
    "update_discovery_status_graph",
    "get_discovery_details",
    "leave_note",
    "cleanup_knowledge_graph",
    "get_lifecycle_stats",
    "call_model",
    "onboard",
    "identity",
    "debug_request_context",
    "knowledge",
    "agent",
    "calibration",
    "cirs_protocol",
    "self_recovery",
    "operator_resume_agent",
    "pi_get_context",
    "pi_health",
    "pi_sync_eisv",
    "pi_display",
    "pi_say",
    "pi_post_message",
    "pi_query",
    "pi_workflow",
    "pi_git_pull",
    "pi_system_power",
    "pi_restart_service",
    "pi",
    "observe",
    "dialectic",
]


def _first_line(s: str | None) -> str:
    """Extract first non-empty line from a string."""
    if not s:
        return ""
    for line in s.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _strip_schema_descriptions(node: Any) -> Any:
    """Recursively strip 'description' keys from a JSON Schema dict."""
    if isinstance(node, dict):
        return {k: _strip_schema_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_schema_descriptions(x) for x in node]
    return node


def get_tool_definitions(verbosity: str | None = None) -> list[Tool]:
    """Build the list of MCP Tool objects from Pydantic schemas + descriptions."""
    if verbosity is None:
        verbosity = os.getenv("UNITARES_TOOL_SCHEMA_VERBOSITY", "short").strip().lower()

    strip_field_descriptions = (
        os.getenv("UNITARES_TOOL_SCHEMA_STRIP_FIELD_DESCRIPTIONS", "0").strip().lower()
        in ("1", "true", "yes")
    )

    from src.tool_descriptions import TOOL_DESCRIPTIONS

    all_tools: list[Tool] = []

    for tool_name in TOOL_ORDER:
        schema_model = PYDANTIC_SCHEMAS.get(tool_name)
        if not schema_model:
            print(f"WARNING: Schema for {tool_name} not found in Pydantic models!")
            continue

        desc = TOOL_DESCRIPTIONS.get(tool_name)
        if not desc:
            # Fall back to Pydantic model docstring
            desc = schema_model.__doc__ or f"Tool: {tool_name}"

        raw_schema = schema_model.model_json_schema()

        all_tools.append(Tool(
            name=tool_name,
            description=desc,
            inputSchema=raw_schema,
        ))

    # Auto-discover decorator-defined tools not in TOOL_ORDER
    try:
        from src.mcp_handlers.decorators import _TOOL_DEFINITIONS

        hardcoded_names = {t.name for t in all_tools}

        for tn in sorted(_TOOL_DEFINITIONS.keys()):
            if tn in hardcoded_names:
                continue

            td = _TOOL_DEFINITIONS[tn]

            if getattr(td, "hidden", False):
                continue

            desc = getattr(td, "description", None) or f"Tool: {tn}"

            if getattr(td, "deprecated", False):
                superseded_by = getattr(td, "superseded_by", None)
                if superseded_by:
                    desc = f"[DEPRECATED - use {superseded_by}] {desc}"
                else:
                    desc = f"[DEPRECATED] {desc}"

            all_tools.append(Tool(
                name=tn,
                description=desc,
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            ))
    except ImportError:
        pass

    # Apply verbosity and field description stripping
    for t in all_tools:
        if verbosity == "short":
            t.description = _first_line(t.description)
        if strip_field_descriptions:
            t.inputSchema = _strip_schema_descriptions(t.inputSchema)

    return all_tools
