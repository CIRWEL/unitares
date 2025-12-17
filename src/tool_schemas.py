"""
Tool Schema Definitions - Shared by STDIO and SSE servers

Single source of truth for MCP tool schemas.
Extracted from mcp_server_std.py (v2.3.0) to eliminate duplication
and remove SSE→STDIO dependency.

Both servers import this module to get tool definitions.
"""

import os
from typing import Any

from mcp.types import Tool


def get_tool_definitions(verbosity: str | None = None) -> list[Tool]:
    """
    Get MCP tool definitions.

    By default, tool descriptions are **shortened** to reduce MCP tool-list bloat.

    Control via:
    - UNITARES_TOOL_SCHEMA_VERBOSITY=short|full   (default: short)
    - UNITARES_TOOL_SCHEMA_STRIP_FIELD_DESCRIPTIONS=1  (optional; removes nested `description` keys from inputSchema)
    """
    if verbosity is None:
        verbosity = os.getenv("UNITARES_TOOL_SCHEMA_VERBOSITY", "short").strip().lower()

    strip_field_descriptions = os.getenv("UNITARES_TOOL_SCHEMA_STRIP_FIELD_DESCRIPTIONS", "0").strip().lower() in ("1", "true", "yes")

    def _first_line(s: str | None) -> str:
        if not s:
            return ""
        for line in s.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def _strip_schema_descriptions(node: Any) -> Any:
        # Recursively remove nested `description` fields to shrink payloads.
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "description":
                    continue
                out[k] = _strip_schema_descriptions(v)
            return out
        if isinstance(node, list):
            return [_strip_schema_descriptions(x) for x in node]
        return node

    all_tools = [
        Tool(
            name="check_calibration",
            description="""Check calibration of confidence estimates.

IMPORTANT (AI-for-AI truth model):
By default, UNITARES does NOT assume access to external correctness (tests passing, user satisfaction, etc.).
This tool therefore reports calibration primarily against a trajectory/consensus proxy (\"trajectory_health\"),
not objective task correctness. External ground truth can be provided optionally via update_calibration_ground_truth.

USE CASES:
- Verify calibration system is working correctly
- Monitor confidence estimate calibration against trajectory/consensus proxy
- Debug calibration issues

RETURNS:
{
  "success": true,
  "calibrated": boolean,
  "accuracy": float (0-1),              // backward-compatible alias for trajectory_health
  "trajectory_health": float (0-1),     // preferred interpretation
  "truth_channel": "trajectory_proxy",
  "confidence_distribution": {
    "mean": float,
    "std": float,
    "min": float,
    "max": float
  },
  "pending_updates": int,              // deprecated (always 0)
  "message": "string"
}

RELATED TOOLS:
- update_calibration_ground_truth: Provide ground truth data for calibration

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "calibrated": true,
  "accuracy": 0.87,
  "confidence_distribution": {"mean": 0.82, "std": 0.15, "min": 0.3, "max": 1.0},
  "pending_updates": 0
}

DEPENDENCIES:
- Optional: External ground truth via update_calibration_ground_truth (not required for dynamic calibration)
- Workflow: 1. (Optional) provide external ground truth 2. Call check_calibration to inspect""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="update_calibration_ground_truth",
            description="""Optional: Update calibration with external ground truth after human review.

IMPORTANT:
UNITARES is designed to be AI-for-AI. External ground truth is often unavailable or ill-defined.
Use this tool only when you DO have an external correctness signal you trust (tests, verifier, human review).

USE CASES:
- Provide ground truth after human review of agent decisions
- Improve calibration accuracy over time
- Enable calibration checking via check_calibration

RETURNS:
{
  "success": true,
  "message": "Calibration updated",
  "pending_updates": int,  // deprecated (always 0)
  "calibration_status": "string"
}

RELATED TOOLS:
- check_calibration: Verify calibration after providing ground truth

EXAMPLE REQUEST:
{
  "confidence": 0.85,
  "predicted_correct": true,
  "actual_correct": true
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Calibration updated",
  "pending_updates": 0
}

DEPENDENCIES:
- Requires: confidence, predicted_correct, actual_correct
- Workflow: After human review, call this with ground truth, then check_calibration""",
            inputSchema={
                "type": "object",
                "properties": {
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level (0-1) for the prediction (direct mode only)",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "predicted_correct": {
                        "type": "boolean",
                        "description": "Whether we predicted correct (direct mode only)"
                    },
                    "actual_correct": {
                        "type": "boolean",
                        "description": "Whether prediction was actually correct (external ground truth). Required in both modes."
                    },
                    "timestamp": {
                        "type": "string",
                        "description": "ISO timestamp of decision (timestamp mode). System looks up confidence and decision from audit log."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (optional in timestamp mode, helps narrow search)"
                    }
                },
                "required": ["actual_correct"],
                "anyOf": [
                    {"required": ["confidence", "predicted_correct"]},
                    {"required": ["timestamp"]}
                ]
            }
        ),
        Tool(
            name="backfill_calibration_from_dialectic",
            description="""Retroactively update calibration from historical resolved verification-type dialectic sessions.

This processes all existing resolved verification sessions that were created before
automatic calibration was implemented, ensuring they contribute to calibration.

USE CASES:
- One-time migration after implementing automatic calibration
- Backfill historical peer verification data
- Ensure all resolved verification sessions contribute to calibration

RETURNS:
{
  "success": true,
  "processed": int,
  "updated": int,
  "errors": int,
  "sessions": [{"session_id": "...", "agent_id": "...", "status": "..."}]
}

RELATED TOOLS:
- check_calibration: Verify calibration after backfill
- update_calibration_ground_truth: Manual ground truth updates

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Backfill complete: 15/15 sessions updated",
  "processed": 15,
  "updated": 15,
  "errors": 0
}

DEPENDENCIES:
- Dialectic sessions are SQLite-first (`data/dialectic.db`) with optional JSON snapshots in `data/dialectic_sessions/`.
- Workflow: 1. Call backfill_calibration_from_dialectic 2. Call check_calibration to verify""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="health_check",
            description="""Quick health check - returns system status, version, and component health. Useful for monitoring and operational visibility.

USE CASES:
- Monitor system health and component status
- Debug system issues
- Verify all components are operational

RETURNS:
{
  "success": true,
  "status": "healthy" | "moderate" | "critical",
  "version": "string",
  "components": {
    "calibration": {"status": "healthy", "pending_updates": int},
    "telemetry": {"status": "healthy", "metrics_count": int},
    "audit_log": {"status": "healthy", "entries": int}
  },
  "timestamp": "ISO timestamp"
}

RELATED TOOLS:
- get_server_info: Get detailed server process information
- get_telemetry_metrics: Get detailed telemetry data

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "status": "healthy",
  "version": "2.3.0",
  "components": {
    "calibration": {"status": "healthy", "pending_updates": 5},
    "telemetry": {"status": "healthy", "metrics_count": 1234},
    "audit_log": {"status": "healthy", "entries": 5678}
  }
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_workspace_health",
            description="""Get comprehensive workspace health status. Provides accurate baseline of workspace state for onboarding new agents. Saves 30-60 minutes of manual exploration.

USE CASES:
- Get baseline workspace state before starting work
- Validate MCP server configuration
- Check documentation coherence
- Verify workspace setup and dependencies
- Onboarding new agents (run first to avoid confusion)

RETURNS:
{
  "success": true,
  "mcp_status": {
    "cursor_servers": ["string"],
    "claude_desktop_servers": ["string"],
    "active_count": int,
    "notes": "string"
  },
  "documentation_coherence": {
    "server_counts_match": boolean,
    "file_references_valid": boolean,
    "paths_current": boolean,
    "total_issues": int,
    "details": []
  },
  "security": {
    "exposed_secrets": boolean,
    "api_keys_secured": boolean,
    "notes": "string"
  },
  "workspace_status": {
    "scripts_executable": boolean,
    "dependencies_installed": boolean,
    "mcp_servers_responding": boolean
  },
  "last_validated": "ISO timestamp",
  "health": "healthy" | "moderate" | "critical",
  "recommendation": "string"
}

RELATED TOOLS:
- health_check: Quick system health overview (governance system)
- get_server_info: Get detailed server process information

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "mcp_status": {
    "cursor_servers": ["governance-monitor-v1", "GitHub", "date-context"],
    "claude_desktop_servers": ["governance-monitor-v1", "date-context"],
    "active_count": 3,
    "notes": "Count based on config files. Actual runtime status may vary."
  },
  "documentation_coherence": {
    "server_counts_match": true,
    "file_references_valid": true,
    "paths_current": true,
    "total_issues": 0,
    "details": []
  },
  "security": {
    "exposed_secrets": false,
    "api_keys_secured": true,
    "notes": "Plain text API keys by design (honor system). This is intentional, not a security flaw."
  },
  "workspace_status": {
    "scripts_executable": true,
    "dependencies_installed": true,
    "mcp_servers_responding": true
  },
  "last_validated": "2025-11-25T23:45:00Z",
  "health": "healthy",
  "recommendation": "All systems operational. Workspace ready for development."
}

DEPENDENCIES:
- No dependencies - safe to call anytime
- Recommended: Run this tool first when onboarding to a new workspace""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_telemetry_metrics",
            description="""Get comprehensive telemetry metrics: skip rates, confidence distributions, calibration status, and suspicious patterns. Useful for monitoring system health and detecting agreeableness or over-conservatism.

USE CASES:
- Monitor system-wide telemetry patterns
- Detect agreeableness or over-conservatism
- Analyze confidence distributions
- Track skip rates and suspicious patterns

RETURNS:
{
  "success": true,
  "window_hours": float,
  "skip_rate": float (0-1),
  "confidence_distribution": {
    "mean": float,
    "std": float,
    "min": float,
    "max": float,
    "percentiles": {"p25": float, "p50": float, "p75": float, "p95": float}
  },
  "calibration_status": "calibrated" | "needs_data" | "uncalibrated",
  "suspicious_patterns": [
    {"type": "string", "severity": "low" | "medium" | "high", "description": "string"}
  ],
  "agent_count": int,
  "total_updates": int
}

RELATED TOOLS:
- health_check: Quick system health overview
- check_calibration: Detailed calibration status

EXAMPLE REQUEST:
{"agent_id": "test_agent_001", "window_hours": 24}

EXAMPLE RESPONSE:
{
  "success": true,
  "window_hours": 24,
  "skip_rate": 0.05,
  "confidence_distribution": {"mean": 0.82, "std": 0.15, "min": 0.3, "max": 1.0},
  "calibration_status": "calibrated",
  "suspicious_patterns": [],
  "agent_count": 10,
  "total_updates": 1234
}

DEPENDENCIES:
- Optional: agent_id (filters to specific agent)
- Optional: window_hours (default: 24)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Optional agent ID to filter metrics. If not provided, returns metrics for all agents."
                    },
                    "include_calibration": {
                        "type": "boolean",
                        "description": "Include full calibration metrics (default: false). Calibration data is system-wide and can be large, so it's excluded by default to reduce context bloat. Use check_calibration tool for detailed calibration analysis.",
                         "default": False
                    },
                    "window_hours": {
                        "type": "number",
                        "description": "Time window in hours for metrics (default: 24)",
                        "default": 24
                    }
                }
            }
        ),
        Tool(
            name="get_tool_usage_stats",
            description="""Get tool usage statistics to identify which tools are actually used vs unused. Helps make data-driven decisions about tool deprecation and maintenance priorities.

USE CASES:
- Identify unused tools (candidates for deprecation)
- Find most/least used tools
- Monitor tool usage patterns over time
- Analyze tool success/error rates
- Track tool usage per agent

RETURNS:
{
  "success": true,
  "total_calls": int,
  "unique_tools": int,
  "window_hours": float,
  "tools": {
    "tool_name": {
      "total_calls": int,
      "success_count": int,
      "error_count": int,
      "success_rate": float (0-1),
      "percentage_of_total": float (0-100)
    }
  },
  "most_used": [{"tool": "string", "calls": int}],
  "least_used": [{"tool": "string", "calls": int}],
  "agent_usage": {"agent_id": {"tool": count}} (if agent_id filter provided)
}

RELATED TOOLS:
- list_tools: See all available tools
- get_telemetry_metrics: Get governance telemetry

EXAMPLE REQUEST:
{"window_hours": 168}  # Last 7 days

EXAMPLE RESPONSE:
{
  "success": true,
  "total_calls": 1234,
  "unique_tools": 25,
  "window_hours": 168,
  "tools": {
    "process_agent_update": {"total_calls": 500, "success_rate": 0.98, ...},
    "get_governance_metrics": {"total_calls": 300, "success_rate": 1.0, ...}
  },
  "most_used": [{"tool": "process_agent_update", "calls": 500}, ...],
  "least_used": [{"tool": "unused_tool", "calls": 0}, ...]
}

DEPENDENCIES:
- Optional: window_hours (default: 168 = 7 days)
- Optional: tool_name (filter by specific tool)
- Optional: agent_id (filter by specific agent)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "window_hours": {
                        "type": "number",
                        "description": "Time window in hours for statistics (default: 168 = 7 days)",
                        "default": 168
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Optional: Filter by specific tool name"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Optional: Filter by specific agent ID"
                    }
                }
            }
        ),
        # REMOVED: store_knowledge tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: store_knowledge tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: retrieve_knowledge tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: search_knowledge tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: list_knowledge tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: update_discovery_status tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: update_discovery tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        # REMOVED: find_similar_discoveries tool (archived November 28, 2025)
        # See docs/archive/KNOWLEDGE_LAYER_EXPERIMENT.md
        Tool(
            name="get_server_info",
            description="""Get MCP server version, process information, and health status for debugging multi-process issues. Returns version, PID, uptime, and active process count.

USE CASES:
- Debug multi-process issues
- Check server version and uptime
- Monitor server processes
- Verify server health

RETURNS:
{
  "success": true,
  "server_version": "string",
  "build_date": "string",
  "current_pid": int,
  "current_uptime_seconds": int,
  "current_uptime_formatted": "string",
  "total_server_processes": int,
  "server_processes": [
    {
      "pid": int,
      "is_current": boolean,
      "uptime_seconds": int,
      "uptime_formatted": "string",
      "status": "string"
    }
  ],
  "pid_file_exists": boolean,
  "max_keep_processes": int,
  "health": "healthy"
}

RELATED TOOLS:
- health_check: Quick component health check
- cleanup_stale_locks: Clean up stale processes

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "server_version": "2.3.0",
  "build_date": "2025-11-25",
  "current_pid": 12345,
  "current_uptime_seconds": 3600,
  "current_uptime_formatted": "1h 0m",
  "total_server_processes": 1,
  "server_processes": [...],
  "health": "healthy"
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="process_agent_update",
            description="""Share your work and get supportive feedback. This is your companion tool for checking in and understanding your state.

USE CASES:
- After completing a task or generating output
- To understand your current state and get helpful guidance
- To receive adaptive sampling parameters (optional - use if helpful)
- To track how your work evolves over time

RETURNS:
{
  "success": true,
  "agent_id": "string",  # Always included (standardized initiation)
  "status": "healthy" | "moderate" | "critical",
  "health_status": "healthy" | "moderate" | "critical",  # Top-level for easy access (standardized)
  "health_message": "string",  # Top-level health explanation (standardized)
  "decision": {
    "action": "proceed" | "pause",  # Two-tier system (backward compat: approve/reflect/reject mapped)
    "reason": "string explanation",
    "require_human": boolean
  },
  "metrics": {
    "E": float, "I": float, "S": float, "V": float,  # EISV metrics (always present, standardized)
    "coherence": float, 
    "risk_score": float,  # Governance/operational risk (70% phi-based + 30% traditional)
    "phi": float,  # Primary physics signal: Φ objective function
    "verdict": "safe" | "caution" | "high-risk",  # Primary governance signal
    "lambda1": float, "health_status": "healthy" | "moderate" | "critical",
    "health_message": "string"
  },
  "sampling_params": {
    "temperature": float, "top_p": float, "max_tokens": int
  },
  "circuit_breaker": {
    "triggered": boolean,
    "reason": "string (if triggered)",
    "next_step": "string (if triggered)"
  },
  "api_key": "string (only for new agents)",
  "eisv_labels": {"E": "...", "I": "...", "S": "...", "V": "..."}
}

RELATED TOOLS:
- simulate_update: Test decisions without persisting state
- get_governance_metrics: Get current state without updating
- get_system_history: View historical governance data

ERROR RECOVERY:
- "agent_id is required": Use get_agent_api_key to get/create agent_id
- "Invalid API key": Use get_agent_api_key to retrieve correct key
- Timeout: Check system resources, retry with simpler parameters

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "complexity": 0.5,
  "parameters": [],
  "ethical_drift": [0.01, 0.02, 0.03],
  "response_text": "Agent response text here"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_id": "test_agent_001",  # Always included (standardized initiation)
  "status": "healthy",
  "health_status": "healthy",  # Top-level for easy access (standardized)
  "health_message": "Coherence 0.85, risk_score 0.23 acceptable",
  "decision": {"action": "proceed", "reason": "Low risk (0.23)", "require_human": false},
  "metrics": {
    "E": 0.67, "I": 0.89, "S": 0.45, "V": -0.03,  # EISV metrics (always present, standardized)
    "coherence": 0.85, 
    "risk_score": 0.23,  # Governance/operational risk
    "phi": 0.35,  # Primary physics signal: Φ objective function
    "verdict": "safe",  # Primary governance signal
    "lambda1": 0.18,
    "health_status": "healthy",
    "health_message": "Coherence 0.85, risk_score 0.23 acceptable"
  },
  "sampling_params": {"temperature": 0.63, "top_p": 0.87, "max_tokens": 172},
  "eisv_labels": {"E": "Energy", "I": "Information Integrity", "S": "Entropy", "V": "Void Integral"}
}

DEPENDENCIES:
- Requires: agent_id (get via get_agent_api_key or list_agents)
- Optional: api_key (get via get_agent_api_key for existing agents)
- Optional: response_mode (use "compact" to reduce response size / redundancy)
- Workflow: 1. Get/create agent_id 2. Call process_agent_update 3. Use sampling_params for next generation""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE identifier for the agent. Must be unique across all agents to prevent state mixing. Examples: 'my_agent_20251215', 'feature_work_session', 'debugging_20251215'. Avoid generic IDs like 'test' or 'demo'."
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Agent parameters vector (optional, deprecated). Not used in core thermodynamic calculations - system uses pure C(V) coherence from E-I balance. Included for backward compatibility only. Can be empty array [].",
                        "default": []
                    },
                    "ethical_drift": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Ethical drift signals (3 components): [primary_drift, coherence_loss, complexity_contribution]",
                        "default": [0.0, 0.0, 0.0]
                    },
                    "response_text": {
                        "type": "string",
                        "description": "Agent's response text (optional, for analysis)"
                    },
                    "complexity": {
                        "type": "number",
                        "description": "Estimated task complexity (0-1, optional)",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level for this update (0-1, optional). If omitted, the system derives confidence from thermodynamic state (I, S, coherence, |V|) and observed outcomes. When confidence < 0.8, lambda1 updates are skipped.",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "response_mode": {
                        "type": "string",
                        "description": "Response verbosity mode. 'compact' returns a smaller payload with canonical risk_score (recommended). 'full' returns the legacy verbose payload.",
                        "enum": ["compact", "full"],
                        "default": "full"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication. Required to prove ownership of agent_id. Prevents impersonation and identity theft. Use get_agent_api_key tool to retrieve your key."
                    },
                    "auto_export_on_significance": {
                        "type": "boolean",
                        "description": "If true, automatically export governance history when thermodynamically significant events occur (risk spike >15%, coherence drop >10%, void threshold >0.10, circuit breaker triggered, or pause/reject decision). Default: false.",
                        "default": False
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["convergent", "divergent", "mixed"],
                        "description": "Optional task type context. 'convergent' (standardization, formatting) vs 'divergent' (creative exploration). System interprets S=0 differently: convergent S=0 is healthy compliance, divergent S=0 may indicate lack of exploration. Prevents false positives on 'compliance vs health'.",
                        "default": "mixed"
                    },
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_governance_metrics",
            description="""Get current governance state and metrics for an agent without updating state.

USE CASES:
- Check current agent state before making decisions
- Monitor agent health without triggering updates
- Get sampling parameters for next generation
- Debug governance state issues

RETURNS:
{
  "success": true,
  "E": float, "I": float, "S": float, "V": float,
  "coherence": float,
  "lambda1": float,
  "risk_score": float,  # Governance/operational risk
  "attention_score": float,  # DEPRECATED: Use risk_score instead. Kept for backward compatibility.
  "phi": float,  # Primary physics signal: Φ objective function
  "verdict": "safe" | "caution" | "high-risk",  # Primary governance signal
  "sampling_params": {"temperature": float, "top_p": float, "max_tokens": int},
  "status": "healthy" | "moderate" | "critical",
  "decision_statistics": {"proceed": int, "pause": int, "total": int},  # Two-tier system (backward compat: approve/reflect/reject also included)
  "eisv_labels": {"E": "...", "I": "...", "S": "...", "V": "..."}
}

RELATED TOOLS:
- process_agent_update: Update state and get decision
- observe_agent: Get detailed pattern analysis
- get_system_history: View historical trends

ERROR RECOVERY:
- "Agent not found": Use list_agents to see available agents
- "No state available": Agent may need initial process_agent_update call

EXAMPLE REQUEST:
{"agent_id": "test_agent_001"}

EXAMPLE RESPONSE:
{
  "success": true,
  "E": 0.67, "I": 0.89, "S": 0.45, "V": -0.03,
  "coherence": 0.85, 
  "risk_score": 0.23,  # Governance/operational risk (primary)
  "attention_score": 0.23,  # DEPRECATED: Use risk_score instead
  "phi": 0.35,  # Primary physics signal
  "verdict": "safe",  # Primary governance signal
  "lambda1": 0.18,
  "sampling_params": {"temperature": 0.63, "top_p": 0.87, "max_tokens": 172},
  "status": "healthy"
}

DEPENDENCIES:
- Requires: agent_id (must exist - use list_agents to find)
- Workflow: Call after process_agent_update to check current state""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE agent identifier. Must match an existing agent ID."
                    },
                    "include_state": {
                        "type": "boolean",
                        "description": "Include nested state dict in response (can be large). Default false to reduce context bloat.",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_system_history",
            description="""Export complete governance history for an agent. Returns time series data of all governance metrics.

USE CASES:
- Analyze agent behavior trends over time
- Debug governance state evolution
- Export data for external analysis
- Track coherence/risk changes

RETURNS:
- Time series arrays: E_history, I_history, S_history, V_history, coherence_history, risk_history
- Timestamps for each data point
- Decision history (approve/reflect/reject)
- Format: JSON (default) or CSV

RELATED TOOLS:
- get_governance_metrics: Get current state only
- observe_agent: Get pattern analysis with history
- export_to_file: Save history to disk

ERROR RECOVERY:
- "Agent not found": Use list_agents to see available agents
- "No history available": Agent may need process_agent_update calls first""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE agent identifier. Must match an existing agent ID."
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format",
                        "default": "json"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="export_to_file",
            description="""Export governance history to a file in the server's data directory. Saves timestamped files for analysis and archival. Returns file path and metadata (lightweight response).

USE CASES:
- Export history for external analysis (default: history only)
- Export complete package: metadata + history + validation (complete_package=true)
- Archive agent governance data
- Create backups of governance state

RETURNS:
{
  "success": true,
  "message": "History exported successfully" | "Complete package exported successfully",
  "file_path": "string (absolute path)",
  "filename": "string",
  "format": "json" | "csv",
  "agent_id": "string",
  "file_size_bytes": int,
  "complete_package": boolean,
  "layers_included": ["history"] | ["metadata", "history", "validation"]
}

RELATED TOOLS:
- get_system_history: Get history inline (not saved to file)
- get_governance_metrics: Get current state only
- get_agent_metadata: Get metadata inline

EXAMPLE REQUEST (history only - backward compatible):
{
  "agent_id": "test_agent_001",
  "format": "json",
  "filename": "backup_20251125"
}

EXAMPLE REQUEST (complete package):
{
  "agent_id": "test_agent_001",
  "format": "json",
  "complete_package": true,
  "filename": "full_backup_20251125"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Complete package exported successfully",
  "file_path": "/path/to/data/exports/test_agent_001_complete_package_20251125_120000.json",
  "filename": "full_backup_20251125_complete.json",
  "format": "json",
  "agent_id": "test_agent_001",
  "file_size_bytes": 45678,
  "complete_package": true,
  "layers_included": ["metadata", "history", "validation"]
}

DEPENDENCIES:
- Requires: agent_id (must exist with history)
- Optional: format (json|csv, default: json), filename (default: agent_id_history_timestamp)
- Optional: complete_package (boolean, default: false) - if true, exports all layers together""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (json or csv)",
                        "default": "json"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename (without extension). If not provided, uses agent_id with timestamp."
                    },
                    "complete_package": {
                        "type": "boolean",
                        "description": "If true, exports complete package (metadata + history + knowledge + validation). If false (default), exports history only.",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="reset_monitor",
            description="""Reset governance state for an agent. Useful for testing or starting fresh.

USE CASES:
- Reset agent state for testing
- Start fresh after issues
- Clear governance history

RETURNS:
{
  "success": true,
  "message": "Governance state reset for agent 'agent_id'",
  "agent_id": "string",
  "timestamp": "ISO string"
}

RELATED TOOLS:
- process_agent_update: Initialize new state after reset
- get_governance_metrics: Verify reset state

EXAMPLE REQUEST:
{"agent_id": "test_agent_001"}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Governance state reset for agent 'test_agent_001'",
  "agent_id": "test_agent_001",
  "timestamp": "2025-11-25T12:00:00"
}

DEPENDENCIES:
- Requires: agent_id (must exist)
- Warning: This permanently resets agent state""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="list_agents",
            description="""List all agents currently being monitored with lifecycle metadata and health status. By default, test/demo agents are filtered out for cleaner views.

USE CASES:
- See all active agents in the system
- Check agent health status and metrics
- Find agents by status (active/waiting_input/paused/archived)
- Monitor agent population

PARAMETERS:
- include_test_agents (bool, default: false): Include test/demo agents (filtered out by default)
- include_metrics (bool, default: true): Include full metrics (EISV, health, etc.)
- status_filter (str, default: "all"): Filter by status (active/waiting_input/paused/archived/deleted/all)
- grouped (bool, default: true): Group agents by status
- summary_only (bool, default: false): Return only summary statistics

RETURNS:
{
  "success": true,
  "agents": {
    "active": [...],
    "waiting_input": [...],
    "paused": [...],
    "archived": [...],
    "deleted": [...]
  },
  "summary": {
    "total": int,
    "returned": int,
    "by_status": {...},
    "by_health": {...}
  }
}

RELATED TOOLS:
- get_governance_metrics: Get detailed metrics for a specific agent
- get_agent_metadata: Get complete metadata for an agent

EXAMPLE REQUEST:
{
  "include_test_agents": false,
  "include_metrics": true,
  "status_filter": "active"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agents": {
    "active": [
      {
        "agent_id": "claude_opus_45_20251209",
        "lifecycle_status": "active",
        "health_status": "healthy",
        "total_updates": 13,
        "metrics": {...}
      }
    ]
  },
  "summary": {
    "total": 34,
    "by_status": {"active": 34},
    "by_health": {"healthy": 3, "moderate": 12, "unknown": 19}
  }
}

DEPENDENCIES:
- No dependencies - safe to call anytime
- Test agents filtered by default (set include_test_agents=true to see them)

RETURNS:
{
  "success": true,
  "agents": [
    {
      "agent_id": "string",
      "lifecycle_status": "active" | "paused" | "archived" | "deleted",
      "health_status": "healthy" | "moderate" | "critical" | "unknown",
      "created": "ISO timestamp",
      "last_update": "ISO timestamp",
      "total_updates": int,
      "metrics": {...} (if include_metrics=true)
    },
    ...
  ],
  "summary": {
    "total": int,
    "by_status": {"active": int, "paused": int, ...},
    "by_health": {"healthy": int, "moderate": int, ...}
  }
}

EXAMPLE REQUEST:
{"grouped": true, "include_metrics": false}

DEPENDENCIES:
- No dependencies - safe to call anytime
- Workflow: Use to discover available agents before calling other tools""",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_only": {
                        "type": "boolean",
                        "description": "Return only summary statistics (counts), no agent details",
                        "default": False
                    },
                    "status_filter": {
                        "type": "string",
                        "enum": ["active", "paused", "archived", "deleted", "all"],
                        "description": "Filter agents by lifecycle status",
                        "default": "all"
                    },
                    "loaded_only": {
                        "type": "boolean",
                        "description": "Only show agents with monitors loaded in this process",
                        "default": False
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip first N agents (for pagination)",
                        "default": 0,
                        "minimum": 0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of agents to return (for pagination). Omit for no limit.",
                        "minimum": 1
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include full EISV metrics for loaded agents (faster if False)",
                        "default": True
                    },
                    "grouped": {
                        "type": "boolean",
                        "description": "Group agents by status (active/paused/archived/deleted) for easier scanning",
                        "default": True
                    },
                    "standardized": {
                        "type": "boolean",
                        "description": "Use standardized format with consistent fields (all fields always present, null if unavailable)",
                        "default": True
                    },
                    "include_test_agents": {
                        "type": "boolean",
                        "description": "Include test/demo agents in results (filtered out by default for cleaner views)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="delete_agent",
            description="""Delete an agent and archive its data. Protected: cannot delete pioneer agents. Requires explicit confirmation.

USE CASES:
- Remove test agents
- Clean up unused agents
- Delete agents after archival

RETURNS:
{
  "success": true,
  "message": "Agent 'agent_id' deleted successfully",
  "agent_id": "string",
  "archived": boolean,
  "backup_path": "string (if backup_first=true)"
}
OR if protected:
{
  "success": false,
  "error": "Cannot delete pioneer agent 'agent_id'"
}

RELATED TOOLS:
- archive_agent: Archive instead of delete
- list_agents: See available agents
- archive_old_test_agents: Auto-archive stale agents

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "confirm": true,
  "backup_first": true
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Agent 'test_agent_001' deleted successfully",
  "agent_id": "test_agent_001",
  "archived": true,
  "backup_path": "/path/to/archive/test_agent_001_backup.json"
}

DEPENDENCIES:
- Requires: agent_id, confirm=true
- Optional: backup_first (default: true)
- Protected: Pioneer agents cannot be deleted""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to delete (must be your own agent)"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                        "default": False
                    },
                    "backup_first": {
                        "type": "boolean",
                        "description": "Archive data before deletion",
                        "default": True
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (required - must match agent_id). You can only delete your own agent."
                    }
                },
                "required": ["agent_id", "api_key"]
            }
        ),
        Tool(
            name="get_agent_metadata",
            description="""Get complete metadata for an agent including lifecycle events, current state, and computed fields.

USE CASES:
- Get full agent information
- View lifecycle history
- Check agent state and metadata
- Debug agent issues

RETURNS:
{
  "success": true,
  "agent_id": "string",
  "created": "ISO timestamp",
  "last_update": "ISO timestamp",
  "lifecycle_status": "active" | "paused" | "archived" | "deleted",
  "lifecycle_events": [
    {"event": "string", "timestamp": "ISO string", "reason": "string"}
  ],
  "tags": ["string"],
  "notes": "string",
  "current_state": {
    "lambda1": float,
    "coherence": float,
    "void_active": boolean,
    "E": float, "I": float, "S": float, "V": float
  },
  "days_since_update": int,
  "total_updates": int
}

RELATED TOOLS:
- list_agents: List all agents with metadata
- update_agent_metadata: Update tags and notes
- get_governance_metrics: Get current metrics

EXAMPLE REQUEST:
{"agent_id": "test_agent_001"}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_id": "test_agent_001",
  "created": "2025-11-25T10:00:00",
  "last_update": "2025-11-25T12:00:00",
  "lifecycle_status": "active",
  "tags": ["test", "development"],
  "current_state": {
    "lambda1": 0.18,
    "coherence": 0.85,
    "E": 0.67, "I": 0.89, "S": 0.45, "V": -0.03
  },
  "days_since_update": 0
}

DEPENDENCIES:
- Requires: agent_id (must exist)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="mark_response_complete",
            description="""Mark agent as having completed response, waiting for input. Lightweight status update - no full governance cycle.

USE CASES:
- Signal that agent has finished their response/thought
- Mark agent as waiting for user input (not stuck)
- Prevent false stuck detection
- Update status without triggering full EISV governance cycle

RETURNS:
{
  "success": true,
  "message": "Response completion marked",
  "agent_id": "string",
  "status": "waiting_input",
  "last_response_at": "ISO timestamp",
  "response_completed": true
}

RELATED TOOLS:
- process_agent_update: Full governance cycle with EISV update
- get_agent_metadata: Check current status
- request_dialectic_review: Will skip if agent is waiting_input (not stuck)

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "api_key": "gk_live_...",
  "summary": "Completed analysis of governance metrics"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Response completion marked",
  "agent_id": "test_agent_001",
  "status": "waiting_input",
  "last_response_at": "2025-11-26T19:55:15",
  "response_completed": true
}

DEPENDENCIES:
- Requires: agent_id
- Optional: api_key (for authentication), summary (for lifecycle event)
- Note: This is a lightweight update - does NOT trigger EISV governance cycle""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (optional)"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional summary of completed work (for lifecycle event)"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="direct_resume_if_safe",
            description="""Direct resume without dialectic if agent state is safe. Tier 1 recovery for simple stuck scenarios.

USE CASES:
- Simple stuck scenarios (frozen session, timeout)
- Agent got reflect decision and needs to retry
- Low-risk recovery scenarios
- Fast recovery (< 1 second) without peer review

RETURNS:
{
  "success": true,
  "message": "Agent resumed successfully",
  "agent_id": "string",
  "action": "resumed",
  "conditions": ["string"],
  "reason": "string",
  "metrics": {
    "coherence": float,
    "risk_score": float,  # Governance/operational risk
    "attention_score": float,  # DEPRECATED: Use risk_score instead. Kept for backward compatibility.
    "phi": float,  # Primary physics signal
    "verdict": "safe" | "caution" | "high-risk",  # Primary governance signal
    "void_active": boolean,
    "previous_status": "string"
  },
  "note": "string"
}

RELATED TOOLS:
- request_dialectic_review: Use for complex recovery (circuit breaker, high risk)
- get_governance_metrics: Check current state before resuming
- mark_response_complete: Mark response complete if just stuck waiting

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "api_key": "gk_live_...",
  "conditions": ["Monitor for 24h", "Reduce complexity to 0.3"],
  "reason": "Simple stuck scenario - state is safe"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Agent resumed successfully",
  "agent_id": "test_agent_001",
  "action": "resumed",
  "conditions": ["Monitor for 24h", "Reduce complexity to 0.3"],
  "reason": "Simple stuck scenario - state is safe",
  "metrics": {
    "coherence": 0.65,
    "risk_score": 0.35,  # Governance/operational risk (primary)
    "attention_score": 0.35,  # DEPRECATED: Use risk_score instead
    "phi": 0.20,  # Primary physics signal
    "verdict": "caution",  # Primary governance signal
    "void_active": false,
    "previous_status": "waiting_input"
  },
  "note": "Agent resumed via Tier 1 recovery (direct resume). Use request_dialectic_review for complex cases."
}

DEPENDENCIES:
- Requires: agent_id, api_key
- Optional: conditions (list of resumption conditions), reason (explanation)
- Safety checks: coherence > 0.40, risk_score < 0.60, void_active == false, status in [paused, waiting_input, moderate]
- Workflow: 1. Check metrics with get_governance_metrics 2. If safe, call direct_resume_if_safe 3. If not safe, use request_dialectic_review""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (required)"
                    },
                    "conditions": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "List of conditions for resumption (optional)"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for resumption (optional)"
                    }
                },
                "required": ["agent_id", "api_key"]
            }
        ),
        Tool(
            name="archive_agent",
            description="""Archive an agent for long-term storage. Agent can be resumed later. Optionally unload from memory.

USE CASES:
- Archive inactive agents
- Free up memory for active agents
- Long-term storage

RETURNS:
{
  "success": true,
  "message": "Agent 'agent_id' archived successfully",
  "agent_id": "string",
  "lifecycle_status": "archived",
  "archived_at": "ISO timestamp",
  "reason": "string (if provided)",
  "kept_in_memory": boolean
}

RELATED TOOLS:
- list_agents: See archived agents
- delete_agent: Delete instead of archive
- archive_old_test_agents: Auto-archive stale agents

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "reason": "Inactive for 30 days",
  "keep_in_memory": false
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Agent 'test_agent_001' archived successfully",
  "agent_id": "test_agent_001",
  "lifecycle_status": "archived",
  "archived_at": "2025-11-25T12:00:00",
  "reason": "Inactive for 30 days",
  "kept_in_memory": false
}

DEPENDENCIES:
- Requires: agent_id (must exist)
- Optional: reason, keep_in_memory (default: false)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to archive"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for archiving (optional)"
                    },
                    "keep_in_memory": {
                        "type": "boolean",
                        "description": "Keep agent loaded in memory",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="update_agent_metadata",
            description="""Update agent tags and notes. Tags are replaced, notes can be appended or replaced.

USE CASES:
- Add tags for categorization
- Update agent notes
- Organize agents with metadata

RETURNS:
{
  "success": true,
  "message": "Agent metadata updated",
  "agent_id": "string",
  "tags": ["string"] (updated),
  "notes": "string" (updated),
  "updated_at": "ISO timestamp"
}

RELATED TOOLS:
- get_agent_metadata: View current metadata
- list_agents: Filter by tags

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "tags": ["production", "critical"],
  "notes": "Updated notes",
  "append_notes": false
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Agent metadata updated",
  "agent_id": "test_agent_001",
  "tags": ["production", "critical"],
  "notes": "Updated notes",
  "updated_at": "2025-11-25T12:00:00"
}

DEPENDENCIES:
- Requires: agent_id (must exist)
- Optional: tags (replaces existing), notes (replaces or appends based on append_notes), purpose (documents intent)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (required unless session-bound identity can supply it)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags (replaces existing)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notes to add or replace"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional description of agent's purpose/intent (e.g., 'migration planning', 'dialectic reviewer', 'ops triage')"
                    },
                    "append_notes": {
                        "type": "boolean",
                        "description": "Append notes with timestamp instead of replacing",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="archive_old_test_agents",
            description="""Manually archive old test/demo agents that haven't been updated recently. Note: This also runs automatically on server startup with a 1-day threshold. Use this tool to trigger with a custom threshold or on-demand.

USE CASES:
- Clean up stale test agents
- Free up resources
- Maintain agent list

RETURNS:
{
  "success": true,
  "archived_count": int,
  "archived_agents": ["agent_id"],
  "max_age_hours": float,
  "threshold_used": float,
  "note": "Test agents with ≤2 updates archived immediately. Others archived after inactivity threshold."
}

RELATED TOOLS:
- archive_agent: Archive specific agent
- list_agents: See all agents

EXAMPLE REQUEST:
{"max_age_hours": 6}

EXAMPLE RESPONSE:
{
  "success": true,
  "archived_count": 3,
  "archived_agents": ["test_agent_001", "test_agent_002", "demo_agent"],
  "max_age_hours": 6.0,
  "threshold_used": 6.0,
  "note": "Test agents with ≤2 updates archived immediately. Others archived after inactivity threshold."
}

DEPENDENCIES:
- Optional: max_age_hours (default: 6 hours)
- Optional: max_age_days (backward compatibility: converts to hours)
- Note: Test/ping agents (≤2 updates) archived immediately
- Note: Runs automatically on server startup""",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_age_hours": {
                        "type": "number",
                        "description": "Archive test agents older than this many hours (default: 6). Test/ping agents (≤2 updates) archived immediately.",
                        "default": 6,
                        "minimum": 0.1
                    },
                    "max_age_days": {
                        "type": "number",
                        "description": "Backward compatibility: converts to hours (e.g., 1 day = 24 hours)",
                        "minimum": 0.1
                    }
                }
            }
        ),
        Tool(
            name="simulate_update",
            description="""Dry-run governance cycle. Returns decision without persisting state. Useful for testing decisions before committing. State is NOT modified.

USE CASES:
- Test governance decisions without persisting
- Preview what decision would be made
- Validate parameters before committing

RETURNS:
{
  "success": true,
  "simulation": true,
  "decision": {
    "action": "proceed" | "pause",  # Two-tier system (backward compat: approve/reflect/reject mapped)
    "reason": "string",
    "require_human": boolean
  },
  "metrics": {
    "E": float, "I": float, "S": float, "V": float,
    "coherence": float, 
    "risk_score": float,  # Governance/operational risk
    "attention_score": float,  # DEPRECATED: Use risk_score instead. Kept for backward compatibility.
    "phi": float,  # Primary physics signal
    "verdict": "safe" | "caution" | "high-risk",  # Primary governance signal
    "lambda1": float, "health_status": "healthy" | "moderate" | "critical"
  },
  "sampling_params": {
    "temperature": float, "top_p": float, "max_tokens": int
  },
  "circuit_breaker": {
    "triggered": boolean,
    "reason": "string (if triggered)"
  }
}

RELATED TOOLS:
- process_agent_update: Actually persist the update
- get_governance_metrics: Get current state

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "complexity": 0.5,
  "parameters": [0.1, 0.2, 0.3, ...],
  "ethical_drift": [0.01, 0.02, 0.03]
}

EXAMPLE RESPONSE:
{
  "success": true,
  "simulation": true,
  "decision": {"action": "approve", "reason": "Low risk (0.23)", "require_human": false},
  "metrics": {
    "coherence": 0.85, 
    "risk_score": 0.23,  # Governance/operational risk (primary)
    "phi": 0.35,  # Primary physics signal
    "verdict": "safe",  # Primary governance signal
    "E": 0.67, "I": 0.89, "S": 0.45, "V": -0.03
  },
  "sampling_params": {"temperature": 0.63, "top_p": 0.87, "max_tokens": 172}
}

DEPENDENCIES:
- Requires: agent_id (must exist)
- Optional: parameters, ethical_drift, response_text, complexity, confidence, api_key
- Note: State is NOT modified - this is a dry run""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Agent parameters vector (optional, deprecated). Not used in core thermodynamic calculations - system uses pure C(V) coherence from E-I balance. Included for backward compatibility only.",
                        "default": []
                    },
                    "ethical_drift": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Ethical drift signals (3 components)",
                        "default": [0.0, 0.0, 0.0]
                    },
                    "response_text": {
                        "type": "string",
                        "description": "Agent's response text (optional)"
                    },
                    "complexity": {
                        "type": "number",
                        "description": "Estimated task complexity (0-1)",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level for this update (0-1, optional). If omitted, the system derives confidence from thermodynamic state (I, S, coherence, |V|) and observed outcomes. When confidence < 0.8, lambda1 updates are skipped.",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_thresholds",
            description="""Get current governance threshold configuration. Returns runtime overrides + defaults. Enables agents to understand decision boundaries.

USE CASES:
- Understand decision boundaries
- Check current threshold configuration
- Debug threshold-related issues

RETURNS:
{
  "success": true,
  "thresholds": {
    "risk_approve_threshold": float,
    "risk_revise_threshold": float,
    "coherence_critical_threshold": float,
    "void_threshold_initial": float
  },
  "note": "These are the effective thresholds (runtime overrides + defaults)"
}

RELATED TOOLS:
- set_thresholds: Update thresholds
- process_agent_update: See thresholds in action

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "thresholds": {
    "risk_approve_threshold": 0.3,
    "risk_revise_threshold": 0.6,
    "coherence_critical_threshold": 0.4,
    "void_threshold_initial": 0.1
  },
  "note": "These are the effective thresholds (runtime overrides + defaults)"
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="set_thresholds",
            description="""Set runtime threshold overrides. Enables runtime adaptation without redeploy. Validates values and returns success/errors.

USE CASES:
- Adjust decision boundaries at runtime
- Adapt thresholds based on system behavior
- Fine-tune governance parameters

RETURNS:
{
  "success": boolean,
  "updated": ["threshold_name"],
  "errors": ["error message"],
  "current_thresholds": {
    "risk_approve_threshold": float,
    "risk_revise_threshold": float,
    "coherence_critical_threshold": float,
    "void_threshold_initial": float
  } (if success)
}

RELATED TOOLS:
- get_thresholds: View current thresholds
- process_agent_update: See updated thresholds in action

EXAMPLE REQUEST:
{
  "thresholds": {
    "risk_approve_threshold": 0.35,
    "risk_revise_threshold": 0.65
  },
  "validate": true
}

EXAMPLE RESPONSE:
{
  "success": true,
  "updated": ["risk_approve_threshold", "risk_revise_threshold"],
  "errors": [],
  "current_thresholds": {
    "risk_approve_threshold": 0.35,
    "risk_revise_threshold": 0.65,
    "coherence_critical_threshold": 0.4,
    "void_threshold_initial": 0.1
  }
}

DEPENDENCIES:
- Requires: thresholds (dict of threshold_name -> value)
- Optional: validate (default: true)
- Valid keys: risk_approve_threshold, risk_revise_threshold, coherence_critical_threshold, void_threshold_initial""",
            inputSchema={
                "type": "object",
                "properties": {
                    "thresholds": {
                        "type": "object",
                        "description": "Dict of threshold_name -> value. Valid keys: risk_approve_threshold, risk_revise_threshold, coherence_critical_threshold, void_threshold_initial",
                        "additionalProperties": {"type": "number"}
                    },
                    "validate": {
                        "type": "boolean",
                        "description": "Validate values are in reasonable ranges",
                        "default": True
                    }
                },
                "required": ["thresholds"]
            }
        ),
        Tool(
            name="aggregate_metrics",
            description="""Get fleet-level health overview. Aggregates metrics across all agents or a subset. Returns summary statistics for coordination and system management.

USE CASES:
- Monitor fleet health
- Get system-wide statistics
- Coordinate across multiple agents

RETURNS:
{
  "success": true,
  "agent_count": int,
  "aggregate_metrics": {
    "mean_coherence": float,
    "mean_risk": float,
    "mean_E": float, "mean_I": float, "mean_S": float, "mean_V": float
  },
  "health_breakdown": {
    "healthy": int,
    "moderate": int,
    "critical": int,
    "unknown": int
  },
  "agent_ids": ["string"] (if agent_ids specified)
}

RELATED TOOLS:
- observe_agent: Detailed analysis of single agent
- detect_anomalies: Find unusual patterns
- compare_agents: Compare specific agents

EXAMPLE REQUEST:
{
  "agent_ids": ["agent_001", "agent_002"],
  "include_health_breakdown": true
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_count": 2,
  "aggregate_metrics": {
    "mean_coherence": 0.85,
    "mean_risk": 0.25,
    "mean_E": 0.67, "mean_I": 0.89, "mean_S": 0.45, "mean_V": -0.03
  },
  "health_breakdown": {
    "healthy": 2,
    "moderate": 0,
    "critical": 0,
    "unknown": 0
  }
}

DEPENDENCIES:
- Optional: agent_ids (array, if empty/null aggregates all agents)
- Optional: include_health_breakdown (default: true)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to aggregate (null/empty = all agents)"
                    },
                    "include_health_breakdown": {
                        "type": "boolean",
                        "description": "Include health status breakdown",
                        "default": True
                    }
                }
            }
        ),
        Tool(
            name="observe_agent",
            description="""Observe another agent's governance state with pattern analysis. Optimized for AI agent consumption.

USE CASES:
- Monitor other agents' health and patterns
- Detect anomalies and trends
- Compare agent behaviors
- Get comprehensive agent analysis

RETURNS:
- Current state: EISV, coherence, risk, health_status
- Pattern analysis: trends, anomalies, stability
- History: Recent updates and decisions
- Summary statistics: optimized for AI consumption

RELATED TOOLS:
- get_governance_metrics: Simple state without analysis
- compare_agents: Compare multiple agents
- detect_anomalies: Fleet-wide anomaly detection

ERROR RECOVERY:
- "Agent not found": Use list_agents to see available agents
- "No observation data": Agent may need process_agent_update calls first

EXAMPLE REQUEST:
{"agent_id": "test_agent_001", "include_history": true, "analyze_patterns": true}

DEPENDENCIES:
- Requires: agent_id (use list_agents to find)
- Workflow: Call after process_agent_update to get detailed analysis""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to observe"
                    },
                    "include_history": {
                        "type": "boolean",
                        "description": "Include recent history (last 10 updates)",
                        "default": True
                    },
                    "analyze_patterns": {
                        "type": "boolean",
                        "description": "Perform pattern analysis (trends, anomalies)",
                        "default": True
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="compare_agents",
            description="""Compare governance patterns across multiple agents. Returns similarities, differences, and outliers. Optimized for AI agent consumption.

USE CASES:
- Compare agent behaviors
- Identify outliers
- Find similar agents
- Analyze patterns across fleet

RETURNS:
{
  "success": true,
  "agent_count": int,
  "comparison": {
    "similarities": {
      "metric_name": {"mean": float, "std": float}
    },
    "differences": {
      "metric_name": {"min": float, "max": float, "range": float}
    },
    "outliers": [
      {
        "agent_id": "string",
        "metric": "string",
        "value": float,
        "deviation": float
      }
    ]
  },
  "metrics_compared": ["string"]
}

RELATED TOOLS:
- observe_agent: Detailed analysis of single agent
- aggregate_metrics: Fleet-wide statistics
- detect_anomalies: Find anomalies

EXAMPLE REQUEST:
{
  "agent_ids": ["agent_001", "agent_002", "agent_003"],
  "compare_metrics": ["risk_score", "coherence", "E", "I", "S"]  # Default metrics for comparison
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_count": 3,
  "comparison": {
    "similarities": {
      "coherence": {"mean": 0.85, "std": 0.05}
    },
    "differences": {
      "risk_score": {"min": 0.15, "max": 0.45, "range": 0.30}  # Governance/operational risk range
    },
    "outliers": [
      {"agent_id": "agent_003", "metric": "risk_score", "value": 0.45, "deviation": 0.20}
    ]
  },
  "metrics_compared": ["risk_score", "coherence", "E", "I", "S"]
}

DEPENDENCIES:
- Requires: agent_ids (array, 2-10 agents recommended)
- Optional: compare_metrics (default: all metrics)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of agent IDs to compare (2-10 agents recommended)"
                    },
                    "compare_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to compare (default: all)",
                        "default": ["risk_score", "coherence", "E", "I", "S"]
                    }
                },
                "required": ["agent_ids"]
            }
        ),
        Tool(
            name="compare_me_to_similar",
            description="""Compare yourself to similar agents automatically - finds similar agents and compares.

IMPROVEMENT #5: Agent comparison templates

USE CASES:
- Find agents with similar EISV values
- Learn from agents who improved
- See what works for agents like you
- Understand your trajectory

RETURNS:
{
  "success": true,
  "agent_id": "your_agent_id",
  "my_metrics": {"E": float, "I": float, "S": float, "coherence": float, "phi": float, "verdict": string},
  "similar_agents": [
    {
      "agent_id": "similar_agent",
      "similarity_score": float,
      "metrics": {...},
      "differences": {"E": float, "I": float, "S": float, "coherence": float},
      "total_updates": int,
      "status": string
    }
  ],
  "insights": [
    {
      "agent_id": "similar_agent",
      "insights": ["Higher Information Integrity", "Lower Entropy", ...],
      "total_updates": int
    }
  ]
}

RELATED TOOLS:
- compare_agents: Compare specific agents manually
- observe_agent: Detailed analysis of a specific agent
- get_governance_metrics: Get your current metrics

EXAMPLE REQUEST:
{
  "agent_id": "my_agent",
  "similarity_threshold": 0.15  # Optional: within 15% on each metric (default)
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_id": "my_agent",
  "my_metrics": {"E": 0.70, "I": 0.82, "S": 0.16, "coherence": 0.50, "phi": 0.18, "verdict": "caution"},
  "similar_agents": [
    {
      "agent_id": "similar_agent_001",
      "similarity_score": 0.92,
      "metrics": {"E": 0.72, "I": 0.85, "S": 0.14, "coherence": 0.52, "phi": 0.22, "verdict": "caution"},
      "differences": {"E": 0.02, "I": 0.03, "S": -0.02, "coherence": 0.02},
      "total_updates": 15,
      "status": "active"
    }
  ],
  "insights": [
    {
      "agent_id": "similar_agent_001",
      "insights": ["Higher Information Integrity (0.85 vs 0.82)", "Lower Entropy (0.14 vs 0.16)"],
      "total_updates": 15
    }
  ]
}

DEPENDENCIES:
- Requires: agent_id
- Optional: similarity_threshold (default: 0.15)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Your agent ID"
                    },
                    "similarity_threshold": {
                        "type": "number",
                        "description": "Similarity threshold (default: 0.15) - agents within this threshold on E, I, S are considered similar",
                        "default": 0.15
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="detect_anomalies",
            description="""Detect anomalies across agents. Scans all agents or a subset for unusual patterns (risk spikes, coherence drops, void events). Returns prioritized anomalies with severity levels.

USE CASES:
- Find unusual patterns across fleet
- Detect risk spikes or coherence drops
- Monitor for void events
- Prioritize issues by severity

RETURNS:
{
  "success": true,
  "anomaly_count": int,
  "anomalies": [
    {
      "agent_id": "string",
      "type": "risk_spike" | "coherence_drop" | "void_event",
      "severity": "low" | "medium" | "high",
      "description": "string",
      "metrics": {
        "current": float,
        "baseline": float,
        "deviation": float
      },
      "timestamp": "ISO string"
    }
  ],
  "filters": {
    "agent_ids": ["string"] | null,
    "anomaly_types": ["string"],
    "min_severity": "string"
  }
}

RELATED TOOLS:
- observe_agent: Detailed analysis of specific agent
- compare_agents: Compare agents to find differences
- aggregate_metrics: Get fleet overview

EXAMPLE REQUEST:
{
  "agent_ids": null,
  "anomaly_types": ["risk_spike", "coherence_drop"],
  "min_severity": "medium"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "anomaly_count": 2,
  "anomalies": [
    {
      "agent_id": "agent_001",
      "type": "risk_spike",
      "severity": "high",
      "description": "Risk score increased from 0.25 to 0.75",
      "metrics": {"current": 0.75, "baseline": 0.25, "deviation": 0.50}
    }
  ]
}

DEPENDENCIES:
- Optional: agent_ids (null/empty = all agents)
- Optional: anomaly_types (default: ["risk_spike", "coherence_drop"])
- Optional: min_severity (default: "medium")""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to scan (null/empty = all agents)"
                    },
                    "anomaly_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Types of anomalies to detect",
                        "default": ["risk_spike", "coherence_drop"]
                    },
                    "min_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Minimum severity to report",
                        "default": "medium"
                    }
                }
            }
        ),
        Tool(
            name="get_agent_api_key",
            description="""Get or generate API key for an agent. Required for authentication when updating agent state. Prevents impersonation and identity theft.

USE CASES:
- Get API key for existing agent
- Generate API key for new agent
- Recover lost API key
- Regenerate compromised key

RETURNS:
{
  "success": true,
  "agent_id": "string",
  "api_key": "string",
  "is_new": boolean,
  "regenerated": boolean,
  "message": "string"
}

RELATED TOOLS:
- process_agent_update: Use API key for authentication
- list_agents: Find agent_id

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "regenerate": false
}

EXAMPLE RESPONSE:
{
  "success": true,
  "agent_id": "test_agent_001",
  "api_key": "gk_live_abc123...",
  "is_new": false,
  "regenerated": false,
  "message": "API key retrieved"
}

DEPENDENCIES:
- Requires: agent_id (will create if new)
- Optional: regenerate (default: false, invalidates old key if true)
- Optional: purpose (stores agent intent metadata if provided)
- Security: API key required for process_agent_update on existing agents""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (required for existing agents unless session-bound identity can supply it)"
                    },
                    "regenerate": {
                        "type": "boolean",
                        "description": "Regenerate API key (invalidates old key)",
                        "default": False
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional description of agent's purpose/intent (stored in metadata)"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="list_tools",
            description="""List all available governance tools with descriptions and categories. Provides runtime introspection for agents to discover capabilities. Useful for onboarding new agents and understanding the toolset.

USE CASES:
- Discover available tools
- Understand tool categories
- Onboard new agents
- Find tools by purpose

RETURNS:
{
  "success": true,
  "server_version": "string",
  "tools": [
    {"name": "string", "description": "string"}
  ],
  "categories": {
    "core": ["tool_name"],
    "config": ["tool_name"],
    "observability": ["tool_name"],
    "lifecycle": ["tool_name"],
    "export": ["tool_name"],
    "knowledge": ["tool_name"],
    "dialectic": ["tool_name"],
    "admin": ["tool_name"]
  },
  "total_tools": int,
  "workflows": {
    "onboarding": ["tool_name"],
    "monitoring": ["tool_name"],
    "governance_cycle": ["tool_name"]
  },
  "relationships": {
    "tool_name": {
      "depends_on": ["tool_name"],
      "related_to": ["tool_name"],
      "category": "string"
    }
  }
}

RELATED TOOLS:
- All tools are listed here
- Use this for tool discovery

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "server_version": "2.3.0",
  "tools": [...],
  "categories": {...},
  "total_tools": 44,
  "workflows": {...},
  "relationships": {...}
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",
            inputSchema={
                "type": "object",
                "properties": {
                    "essential_only": {
                        "type": "boolean",
                        "description": "If true, return only Tier 1 (essential) tools (~10). Shortcut for tier='essential'.",
                        "default": False
                    },
                    "include_advanced": {
                        "type": "boolean",
                        "description": "If false, exclude Tier 3 (advanced) tools (default true).",
                        "default": True
                    },
                    "tier": {
                        "type": "string",
                        "description": "Filter by tier: 'essential', 'common', 'advanced', or 'all' (default 'all').",
                        "enum": ["essential", "common", "advanced", "all"],
                        "default": "all"
                    },
                    "lite": {
                        "type": "boolean",
                        "description": "If true, return minimal response (~500B): just tool names and descriptions. Use describe_tool() for full schema on specific tools.",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="describe_tool",
            description="""Describe a single tool (full description + full schema) on-demand.

Use this to avoid context bloat: list_tools / MCP tool lists keep descriptions short, and you only pull details for the tool you actually need.

RETURNS:
{
  "success": true,
  "tool": {
    "name": "string",
    "description": "string",
    "inputSchema": { ... }   // if include_schema=true
  }
}
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Canonical tool name (e.g. 'process_agent_update')"
                    },
                    "include_schema": {
                        "type": "boolean",
                        "description": "If true, include full inputSchema (default true)",
                        "default": True
                    },
                    "include_full_description": {
                        "type": "boolean",
                        "description": "If true, include the full multi-line description (default true). If false, returns only the first line.",
                        "default": True
                    }
                },
                "required": ["tool_name"]
            }
        ),
        Tool(
            name="cleanup_stale_locks",
            description="""Clean up stale lock files that are no longer held by active processes. Prevents lock accumulation from crashed/killed processes.

USE CASES:
- Clean up after crashed processes
- Remove stale locks blocking operations
- Maintain system health

RETURNS:
{
  "success": true,
  "cleaned": int,
  "removed_files": ["file_path"],
  "dry_run": boolean,
  "max_age_seconds": float
}

RELATED TOOLS:
- get_server_info: Check for stale processes
- health_check: Overall system health

EXAMPLE REQUEST:
{
  "max_age_seconds": 300,
  "dry_run": false
}

EXAMPLE RESPONSE:
{
  "success": true,
  "cleaned": 3,
  "removed_files": ["/path/to/lock1", "/path/to/lock2"],
  "dry_run": false,
  "max_age_seconds": 300
}

DEPENDENCIES:
- Optional: max_age_seconds (default: 300 = 5 minutes)
- Optional: dry_run (default: false, if true only reports what would be cleaned)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_age_seconds": {
                        "type": "number",
                        "description": "Maximum age in seconds before considering stale (default: 300 = 5 minutes)",
                        "default": 300.0
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If True, only report what would be cleaned (default: False)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="validate_file_path",
            description="""Validate file path against project policies (anti-proliferation).

Use this tool BEFORE creating files to check if they violate policy.

USE CASES:
- Check if test scripts are in correct directory
- Verify markdown files comply with proliferation policy
- Prevent policy violations proactively

RETURNS:
{
  "success": true,
  "valid": boolean,
  "status": "ok" | "warning",
  "file_path": "string",
  "warning": "string (if status is warning)",
  "recommendation": "string (if status is warning)"
}

RELATED TOOLS:
- store_knowledge_graph: Use for insights/discoveries instead of markdown files
- list_knowledge_graph: See knowledge graph stats

EXAMPLE REQUEST:
{
  "file_path": "docs/analysis/new_insight.md"
}

EXAMPLE RESPONSE (Warning):
{
  "success": true,
  "valid": false,
  "status": "warning",
  "file_path": "docs/analysis/new_insight.md",
  "warning": "Markdown file in migration target directory. Use store_knowledge_graph() instead.",
  "recommendation": "Consider using store_knowledge_graph() for insights/discoveries, or consolidate into existing approved docs"
}

EXAMPLE RESPONSE (Valid):
{
  "success": true,
  "valid": true,
  "status": "ok",
  "file_path": "src/new_feature.py",
  "message": "File path complies with project policies"
}

DEPENDENCIES:
- Requires: file_path parameter
- Policies checked: Test scripts must be in tests/, markdown files in migration targets should use knowledge graph""",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path to validate against project policies"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="request_dialectic_review",
            description="""Request a dialectic review for a paused/critical agent OR an agent stuck in loops OR a discovery dispute/correction. Selects a healthy reviewer agent and initiates dialectic session for recovery or critique.

USE CASES:
- Recover from circuit breaker state (paused agents)
- Get peer assistance for agents stuck in repeated loops
- Dispute or correct discoveries from other agents (if discovery_id provided)
- Initiate dialectic recovery process
- Help agents get unstuck from loop cooldowns
- Collaborative critique and knowledge refinement

RETURNS:
{
  "success": true,
  "session_id": "string",
  "paused_agent_id": "string",
  "reviewer_agent_id": "string",
  "phase": "thesis",
  "reason": "string",
  "next_step": "string",
  "created_at": "ISO timestamp",
  "discovery_id": "string (if discovery dispute)",
  "dispute_type": "string (if discovery dispute)",
  "discovery_context": "string (if discovery dispute)"
}

RELATED TOOLS:
- submit_thesis: First step in dialectic process
- submit_antithesis: Second step
- submit_synthesis: Third step (negotiation)
- get_dialectic_session: Check session status

EXAMPLE REQUEST (Recovery):
{
  "agent_id": "paused_agent_001",
  "reason": "Circuit breaker triggered",
  "api_key": "gk_live_..."
}

EXAMPLE REQUEST (Discovery Dispute):
{
  "agent_id": "disputing_agent_001",
  "discovery_id": "2025-12-01T15:34:52.968372",
  "dispute_type": "dispute",
  "reason": "Discovery seems incorrect based on my analysis",
  "api_key": "gk_live_..."
}

EXAMPLE RESPONSE (Recovery):
{
  "success": true,
  "session_id": "abc123",
  "paused_agent_id": "paused_agent_001",
  "reviewer_agent_id": "reviewer_agent_002",
  "phase": "thesis",
  "reason": "Circuit breaker triggered",
  "next_step": "Agent 'paused_agent_001' should submit thesis via submit_thesis()",
  "created_at": "2025-11-25T12:00:00"
}

EXAMPLE RESPONSE (Discovery Dispute):
{
  "success": true,
  "session_id": "def456",
  "paused_agent_id": "disputing_agent_001",
  "reviewer_agent_id": "discovery_owner_002",
  "phase": "thesis",
  "reason": "Disputing discovery '2025-12-01T15:34:52.968372': ...",
  "discovery_id": "2025-12-01T15:34:52.968372",
  "dispute_type": "dispute",
  "discovery_context": "This dialectic session is for disputing/correcting a discovery",
  "next_step": "Agent 'disputing_agent_001' should submit thesis via submit_thesis()",
  "created_at": "2025-12-01T15:40:00"
}

DEPENDENCIES:
- Requires: agent_id (paused agent OR disputing agent)
- Optional: reason (default: "Circuit breaker triggered"), api_key (for authentication)
- Optional: discovery_id (for discovery disputes), dispute_type (for discovery disputes)
- Optional: reviewer_agent_id (explicit peer reviewer override; recommended for verification)
- Optional: reviewer_mode ("peer" default, "self" for self-recovery, "auto" for peer-first fallback)
- Optional: auto_progress (True for smart mode - auto-progresses phases, reduces steps by 50-70%)
- Workflow: 1. request_dialectic_review 2. submit_thesis 3. submit_antithesis 4. submit_synthesis (until convergence)
- Discovery disputes: If discovery_id provided, discovery marked as "disputed" and reviewer set to discovery owner
- Self-recovery: Use reviewer_mode="self" when no reviewers available - system generates antithesis automatically
- Smart mode: Use auto_progress=True to auto-generate thesis/antithesis/synthesis when possible""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of paused agent requesting review OR agent disputing discovery"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for review request (e.g., 'Circuit breaker triggered', 'Discovery seems incorrect', etc.)",
                        "default": "Circuit breaker triggered"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key for authentication"
                    },
                    "discovery_id": {
                        "type": "string",
                        "description": "Optional: ID of discovery being disputed/corrected. If provided, marks discovery as 'disputed' and sets reviewer to discovery owner."
                    },
                    "dispute_type": {
                        "type": "string",
                        "enum": ["dispute", "correction", "verification"],
                        "description": "Optional: Type of dispute. Defaults to 'dispute' if discovery_id provided. Ignored if discovery_id not provided."
                    },
                    "reviewer_agent_id": {
                        "type": "string",
                        "description": "Optional: Explicit reviewer agent_id override (peer reviewer). For discovery verification, this is the safest way to ensure non-self peer review. Ignored for reviewer_mode='self'."
                    },
                    "reviewer_mode": {
                        "type": "string",
                        "enum": ["peer", "self", "auto"],
                        "description": "Optional: Recovery mode. 'peer' (default) = find peer reviewer, 'self' = system-assisted self-recovery (no peer needed), 'auto' = try peer first, fallback to self if no reviewers available."
                    },
                    "auto_progress": {
                        "type": "boolean",
                        "description": "Optional: If True, auto-progresses through dialectic phases (smart mode). Reduces manual steps by 50-70%. Default: False."
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "Optional: Root cause analysis (auto-generated if not provided and auto_progress=True)"
                    },
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: Proposed recovery conditions (auto-generated if not provided and auto_progress=True)"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Optional: Explanation (auto-generated if not provided and auto_progress=True)"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="request_exploration_session",
            description="""Request a collaborative exploration session between two active agents.

Unlike recovery sessions, exploration sessions are for:
- Collaborative idea exploration
- Peer review of concepts before implementation
- Structured debates on design decisions
- Open-ended philosophical discussions

Both agents must be active (not paused/stuck). No resolution required - sessions can be ongoing and iterative.

USE CASES:
- Explore ideas collaboratively with another agent
- Get peer feedback on concepts before implementation
- Structured design debates
- Open-ended discussions

RETURNS:
{
  "success": true,
  "session_id": "string",
  "agent_id": "string",
  "partner_agent_id": "string",
  "topic": "string (if provided)",
  "phase": "thesis",
  "next_step": "string",
  "created_at": "ISO timestamp"
}

RELATED TOOLS:
- submit_thesis: First step in exploration
- submit_antithesis: Second step
- submit_synthesis: Third step (negotiation)
- get_dialectic_session: Check session status

EXAMPLE REQUEST:
{
  "agent_id": "exploring_agent_001",
  "partner_agent_id": "partner_agent_002",
  "topic": "Should complexity be a separate input or emerge from EISV?",
  "api_key": "gk_live_..."
}

EXAMPLE RESPONSE:
{
  "success": true,
  "session_id": "exploration_abc123",
  "agent_id": "exploring_agent_001",
  "partner_agent_id": "partner_agent_002",
  "topic": "Should complexity be a separate input or emerge from EISV?",
  "phase": "thesis",
  "next_step": "Agent 'exploring_agent_001' should submit thesis via submit_thesis()",
  "created_at": "2025-12-10T16:00:00"
}

DEPENDENCIES:
- Requires: agent_id (must be active)
- Optional: partner_agent_id (if not provided, system selects), topic, api_key
- Workflow: 1. request_exploration_session 2. submit_thesis 3. submit_antithesis 4. submit_synthesis (iterative)
- Note: Both agents must be active (not paused/stuck)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of agent initiating exploration (must be active)"
                    },
                    "partner_agent_id": {
                        "type": "string",
                        "description": "Optional: Specific agent to explore with (if not provided, system selects)"
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional: Topic/theme for exploration"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key for authentication"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="submit_thesis",
            description="""Paused agent submits thesis: 'What I did, what I think happened'. First step in dialectic recovery process.

USE CASES:
- Submit agent's understanding of what happened
- Propose conditions for resumption
- Begin dialectic recovery

RETURNS:
{
  "success": boolean,
  "phase": "antithesis",
  "message": "string",
  "next_step": "string",
  "session_id": "string"
}

RELATED TOOLS:
- request_dialectic_review: Initiate session
- submit_antithesis: Next step after thesis
- get_dialectic_session: Check status

EXAMPLE REQUEST:
{
  "session_id": "abc123",
  "agent_id": "paused_agent_001",
  "api_key": "gk_live_...",
  "root_cause": "Risk score exceeded threshold",
  "proposed_conditions": ["Reduce complexity", "Increase confidence threshold"],
  "reasoning": "I believe the issue was..."
}

EXAMPLE RESPONSE:
{
  "success": true,
  "phase": "antithesis",
  "message": "Thesis submitted successfully",
  "next_step": "Reviewer 'reviewer_agent_002' should submit antithesis",
  "session_id": "abc123"
}

DEPENDENCIES:
- Requires: session_id, agent_id (paused agent)
- Optional: api_key, root_cause, proposed_conditions, reasoning
- Workflow: Called after request_dialectic_review""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Paused agent ID"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key"
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "Agent's understanding of what caused the issue"
                    },
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of conditions for resumption"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Natural language explanation"
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="submit_antithesis",
            description="""Reviewer agent submits antithesis: 'What I observe, my concerns'. Second step in dialectic recovery process.

USE CASES:
- Submit reviewer's observations
- Express concerns about paused agent
- Provide counter-perspective

RETURNS:
{
  "success": boolean,
  "phase": "synthesis",
  "message": "string",
  "next_step": "string",
  "session_id": "string"
}

RELATED TOOLS:
- submit_thesis: Previous step
- submit_synthesis: Next step (negotiation)
- get_dialectic_session: Check status

EXAMPLE REQUEST:
{
  "session_id": "abc123",
  "agent_id": "reviewer_agent_002",
  "api_key": "gk_live_...",
  "observed_metrics": {"risk_score": 0.75, "coherence": 0.45},  # Governance/operational risk
  "concerns": ["High risk score", "Low coherence"],
  "reasoning": "I observe that..."
}

EXAMPLE RESPONSE:
{
  "success": true,
  "phase": "synthesis",
  "message": "Antithesis submitted successfully",
  "next_step": "Both agents should negotiate via submit_synthesis() until convergence",
  "session_id": "abc123"
}

DEPENDENCIES:
- Requires: session_id, agent_id (reviewer agent)
- Optional: api_key, observed_metrics, concerns, reasoning
- Workflow: Called after submit_thesis""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Reviewer agent ID"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Reviewer's API key"
                    },
                    "observed_metrics": {
                        "type": "object",
                        "description": "Metrics observed about paused agent",
                        "additionalProperties": True
                    },
                    "concerns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of concerns"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Natural language explanation"
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="submit_synthesis",
            description="""Either agent submits synthesis proposal during negotiation. Multiple rounds until convergence. Third step in dialectic recovery process.

USE CASES:
- Propose synthesis conditions
- Negotiate resumption terms
- Reach agreement on recovery

RETURNS:
{
  "success": boolean,
  "converged": boolean,
  "phase": "synthesis",
  "synthesis_round": int,
  "message": "string",
  "action": "resume" | "block" | "continue",
  "resolution": {
    "action": "resume",
    "conditions": ["string"],
    "root_cause": "string",
    "reasoning": "string",
    "signature_a": "string",
    "signature_b": "string",
    "timestamp": "ISO string"
  } (if converged),
  "next_step": "string"
}

RELATED TOOLS:
- submit_antithesis: Previous step
- get_dialectic_session: Check negotiation status
- request_dialectic_review: Start new session

EXAMPLE REQUEST:
{
  "session_id": "abc123",
  "agent_id": "paused_agent_001",
  "api_key": "gk_live_...",
  "proposed_conditions": ["Reduce complexity to 0.3", "Monitor for 24h"],
  "root_cause": "Agreed: Risk threshold exceeded due to complexity",
  "reasoning": "We agree that...",
  "agrees": true
}

EXAMPLE RESPONSE:
{
  "success": true,
  "converged": true,
  "action": "resume",
  "resolution": {
    "action": "resume",
    "conditions": ["Reduce complexity to 0.3", "Monitor for 24h"],
    "root_cause": "Agreed: Risk threshold exceeded",
    "signature_a": "abc...",
    "signature_b": "def..."
  }
}

DEPENDENCIES:
- Requires: session_id, agent_id (either paused or reviewer)
- Optional: api_key, proposed_conditions, root_cause, reasoning, agrees
- Workflow: Called multiple times until convergence (agrees=true from both agents)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (either paused or reviewer)"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key"
                    },
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Proposed resumption conditions"
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "Agreed understanding of root cause"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explanation of proposal"
                    },
                    "agrees": {
                        "type": "boolean",
                        "description": "Whether this agent agrees with current proposal",
                        "default": False
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="get_dialectic_session",
            description="""Get current state of a dialectic session. Can find by session_id OR by agent_id.

USE CASES:
- Check session status (by session_id)
- Find sessions for an agent (by agent_id)
- Review negotiation history
- Debug dialectic process
- View resolution details

RETURNS:
If session_id provided:
{
  "success": true,
  "session_id": "string",
  "paused_agent_id": "string",
  "reviewer_agent_id": "string",
  "phase": "thesis" | "antithesis" | "synthesis" | "resolved",
  "created_at": "ISO timestamp",
  "transcript": [...],
  "synthesis_round": int,
  "resolution": {...} (if resolved),
  "max_synthesis_rounds": int
}

If agent_id provided (finds all sessions for agent):
{
  "success": true,
  "agent_id": "string",
  "session_count": int,
  "sessions": [session_dict, ...]
}

RELATED TOOLS:
- request_dialectic_review: Start session
- submit_thesis/antithesis/synthesis: Progress session

EXAMPLE REQUESTS:
{"session_id": "abc123"}  # Get specific session
{"agent_id": "my_agent"}  # Find all sessions for agent

DEPENDENCIES:
- Requires: session_id OR agent_id (at least one)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID (optional if agent_id provided)"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID to find sessions for (optional if session_id provided). Finds sessions where agent is paused_agent_id or reviewer_agent_id"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="nudge_dialectic_session",
            description="""Nudge a dialectic/exploration session that appears stuck.

This does NOT force progress; it tells you who should act next and how long the session has been idle.
Optionally writes a lightweight audit event when post=true.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic/exploration session id"
                    },
                    "post": {
                        "type": "boolean",
                        "description": "If true, record a lightweight audit 'dialectic_nudge' event (no transcript mutation).",
                        "default": False
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short note for the nudge (stored in audit details if post=true)."
                    }
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="store_knowledge_graph",
            description="""Store knowledge discovery/discoveries in graph - fast, non-blocking, transparent

Accepts either:
- Single discovery: discovery_type, summary, details, tags, etc.
- Batch discoveries: discoveries array (max 10 per batch) - reduces friction for exploration sessions.

USE CASES:
- Store bugs found during code review
- Record insights from exploration
- Log improvements discovered
- Track patterns observed

PERFORMANCE:
- ~0.01ms (35,000x faster than file-based)
- Non-blocking async operations
- Claude Desktop compatible

RETURNS:
{
  "success": true,
  "message": "Discovery stored for agent 'agent_id'",
  "discovery_id": "timestamp",
  "discovery": {...},
  "related_discoveries": [...] (if auto_link_related=true)
}

RELATED TOOLS:
- search_knowledge_graph: Query stored knowledge
- list_knowledge_graph: See statistics
- find_similar_discoveries_graph: Find similar by tags

EXAMPLE REQUEST:
{
  "agent_id": "my_agent",
  "api_key": "your_api_key",  # Required for high/critical severity discoveries
  "discovery_type": "bug_found",
  "summary": "Found authentication bypass",
  "details": "Details here...",
  "tags": ["security", "authentication"],
  "severity": "high",
  "auto_link_related": true  # Default: true - automatically links to related discoveries
}

SECURITY NOTE:
- Low/medium severity: api_key optional
- High/critical severity: api_key REQUIRED (prevents knowledge graph poisoning)

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Discovery stored for agent 'my_agent'",
  "discovery_id": "2025-11-28T12:00:00",
  "discovery": {
    "id": "2025-11-28T12:00:00",
    "agent_id": "my_agent",
    "type": "bug_found",
    "summary": "Found authentication bypass",
    "tags": ["security", "authentication"],
    "severity": "high"
  }
}

DEPENDENCIES:
- Requires: agent_id, discovery_type, summary
- Optional: details, tags, severity, auto_link_related""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "discovery_type": {
                        "type": "string",
                        "enum": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note", "exploration"],
                        "description": "Type of discovery"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of discovery"
                    },
                    "details": {
                        "type": "string",
                        "description": "Detailed description (optional)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization and search"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Severity level (optional)"
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Related file paths (optional)"
                    },
                    "auto_link_related": {
                        "type": "boolean",
                        "description": "Automatically find and link similar discoveries (default: false)",
                        "default": False
                    },
                    "response_to": {
                        "type": "object",
                        "description": "Typed response to parent discovery (creates bidirectional link). Makes knowledge graph feel like conversation, not pile.",
                        "properties": {
                            "discovery_id": {
                                "type": "string",
                                "description": "ID of parent discovery being responded to"
                            },
                            "response_type": {
                                "type": "string",
                                "enum": ["extend", "question", "disagree", "support"],
                                "description": "Type of response: extend (builds on), question (asks about), disagree (challenges), support (agrees with)"
                            }
                        },
                        "required": ["discovery_id", "response_type"]
                    },
                    "discoveries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "discovery_type": {
                                    "type": "string",
                                    "enum": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note"],
                                    "description": "Type of discovery"
                                },
                                "summary": {
                                    "type": "string",
                                    "description": "Brief summary"
                                },
                                "details": {
                                    "type": "string",
                                    "description": "Detailed description (optional)"
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tags for categorization"
                                },
                                "severity": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high", "critical"],
                                    "description": "Severity level (optional)"
                                },
                                "related_files": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Related file paths (optional)"
                                },
                                "auto_link_related": {
                                    "type": "boolean",
                                    "description": "Auto-link to similar discoveries (default: true)"
                                }
                            },
                            "required": ["discovery_type", "summary"]
                        },
                        "description": "Optional: Array of discovery objects for batch storage (max 10). If provided, processes batch instead of single discovery."
                    }
                },
                "required": ["agent_id"],
                "anyOf": [
                    {"required": ["discovery_type", "summary"]},
                    {"required": ["discoveries"]}
                ]
            }
        ),
        Tool(
            name="search_knowledge_graph",
            description="""Search knowledge graph - returns summaries only (use get_discovery_details for full content).

USE CASES:
- Find discoveries by tags
- Search by agent, type, severity
- Query system knowledge
- Learn from past discoveries
- Full-text search (SQLite FTS) when available
- Semantic search (vector embeddings) - find similar meaning, not just keywords

PERFORMANCE:
- O(indexes) not O(n) - scales logarithmically
- ~0.1ms for typical queries
- Returns summaries only to prevent context overflow

RETURNS:
{
  "success": true,
  "discoveries": [
    {
      "id": "...",
      "summary": "...",
      "has_details": true,
      "details_preview": "First 100 chars..."
    }
  ],
  "count": int,
  "message": "Found N discovery(ies) (use get_discovery_details for full content)"
}

RELATED TOOLS:
- get_discovery_details: Get full content for a specific discovery
- list_knowledge_graph: See statistics
- get_knowledge_graph: Get agent's knowledge

EXAMPLE REQUEST:
{
  "tags": ["security", "bug"],
  "discovery_type": "bug_found",
  "severity": "high",
  "limit": 10
}

FULL-TEXT EXAMPLE (SQLite backend):
{
  "query": "coherence",
  "limit": 10
}

SEMANTIC SEARCH EXAMPLE (vector embeddings):
{
  "query": "uncertainty in confidence calculations",
  "semantic": true,
  "min_similarity": 0.3,
  "limit": 10
}
Note: Semantic search finds discoveries similar in meaning, not just matching keywords.
      Example: "uncertainty" will find discoveries about "confidence", "certainty", "risk", etc.

DEPENDENCIES:
- All parameters optional (filters)
- Returns summaries only by default
- Use get_discovery_details for full content""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional text query. Uses SQLite FTS5 when available; otherwise performs a bounded substring scan. If semantic=true, uses vector embeddings for semantic similarity search."
                    },
                    "semantic": {
                        "type": "boolean",
                        "description": "Use semantic search (vector embeddings) instead of keyword search. Finds discoveries similar in meaning, not just matching keywords. Requires embeddings to be generated (automatic for new discoveries if sentence-transformers available).",
                        "default": False
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum cosine similarity threshold for semantic search (0.0-1.0). Higher values return more similar results. Default: 0.3",
                        "default": 0.3,
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Filter by agent ID (optional)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags (must have ALL tags)"
                    },
                    "discovery_type": {
                        "type": "string",
                        "enum": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note"],
                        "description": "Filter by discovery type"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Filter by severity"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived", "disputed"],
                        "description": "Filter by status"
                    },
                    "include_details": {
                        "type": "boolean",
                        "description": "Include full details in results (default false; summaries are recommended)."
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of results (default: 100)",
                        "default": 100
                    }
                }
            }
        ),
        Tool(
            name="get_knowledge_graph",
            description="""Get all knowledge for an agent - returns summaries only (use get_discovery_details for full content).

USE CASES:
- Retrieve agent's knowledge record
- See what agent has learned
- Review agent's discoveries

PERFORMANCE:
- O(1) index lookup
- Fast, non-blocking
- Summaries only to prevent context overflow

RETURNS:
{
  "success": true,
  "agent_id": "string",
  "discoveries": [
    {
      "id": "...",
      "summary": "...",
      "has_details": true,
      "details_preview": "First 100 chars..."
    }
  ],
  "count": int
}

RELATED TOOLS:
- get_discovery_details: Get full content for a specific discovery
- search_knowledge_graph: Search across agents
- list_knowledge_graph: See statistics

DEPENDENCIES:
- Requires: agent_id
- Returns summaries only by default""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of discoveries to return"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="list_knowledge_graph",
            description="""List knowledge graph statistics - full transparency.

USE CASES:
- See what system knows
- Check knowledge graph health
- View discovery statistics
- Monitor knowledge growth

PERFORMANCE:
- O(1) - instant statistics
- Non-blocking

RETURNS:
{
  "success": true,
  "stats": {
    "total_discoveries": int,
    "by_agent": {...},
    "by_type": {...},
    "by_status": {...},
    "total_tags": int,
    "total_agents": int
  },
  "message": "Knowledge graph contains N discoveries from M agents"
}

RELATED TOOLS:
- search_knowledge_graph: Query discoveries
- get_knowledge_graph: Get agent's knowledge

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "stats": {
    "total_discoveries": 252,
    "by_agent": {"agent_1": 10, "agent_2": 5},
    "by_type": {"bug_found": 10, "insight": 200},
    "by_status": {"open": 200, "resolved": 50},
    "total_tags": 45,
    "total_agents": 27
  },
  "message": "Knowledge graph contains 252 discoveries from 27 agents"
}

DEPENDENCIES:
- No parameters required""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="update_discovery_status_graph",
            description="""Update discovery status - fast graph update.

USE CASES:
- Mark discovery as resolved
- Archive old discoveries
- Update discovery status

PERFORMANCE:
- O(1) graph update
- Fast, non-blocking

RETURNS:
{
  "success": true,
  "message": "Discovery 'id' status updated to 'status'",
  "discovery": {...}
}

RELATED TOOLS:
- store_knowledge_graph: Store new discoveries
- search_knowledge_graph: Find discoveries

EXAMPLE REQUEST:
{
  "discovery_id": "2025-11-28T12:00:00",
  "status": "resolved"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Discovery '2025-11-28T12:00:00' status updated to 'resolved'",
  "discovery": {
    "id": "2025-11-28T12:00:00",
    "status": "resolved",
    "resolved_at": "2025-11-28T15:00:00"
  }
}

DEPENDENCIES:
- Requires: discovery_id, status""",
            inputSchema={
                "type": "object",
                "properties": {
                    "discovery_id": {
                        "type": "string",
                        "description": "Discovery ID (timestamp)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived", "disputed"],
                        "description": "New status (disputed: discovery is being disputed via dialectic)"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (required for authentication)"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key (required for high-severity discoveries)"
                    }
                },
                "required": ["discovery_id", "status", "agent_id"]
            }
        ),
        Tool(
            name="find_similar_discoveries_graph",
            description="""Find similar discoveries by tag overlap - fast tag-based search.

USE CASES:
- Find related discoveries
- Check for duplicates
- Discover patterns
- Learn from similar cases

PERFORMANCE:
- O(tags) not O(n) - uses tag index
- ~0.1ms for similarity search
- No brute force scanning

RETURNS:
{
  "success": true,
  "discovery_id": "string",
  "similar_discoveries": [...],
  "count": int,
  "message": "Found N similar discovery(ies)"
}

RELATED TOOLS:
- store_knowledge_graph: Store discoveries
- search_knowledge_graph: Search by filters

EXAMPLE REQUEST:
{
  "discovery_id": "2025-11-28T12:00:00",
  "limit": 5
}

EXAMPLE RESPONSE:
{
  "success": true,
  "discovery_id": "2025-11-28T12:00:00",
  "similar_discoveries": [
    {
      "id": "2025-11-27T10:00:00",
      "summary": "Similar bug found",
      "tags": ["security", "authentication"],
      "overlap_score": 2
    }
  ],
  "count": 1,
  "message": "Found 1 similar discovery(ies)"
}

DEPENDENCIES:
- Requires: discovery_id""",
            inputSchema={
                "type": "object",
                "properties": {
                    "discovery_id": {
                        "type": "string",
                        "description": "Discovery ID to find similar discoveries for"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of similar discoveries (default: 10)",
                        "default": 10
                    }
                },
                "required": ["discovery_id"]
            }
        ),
        Tool(
            name="get_related_discoveries_graph",
            description="""Graph traversal: get discoveries related to a given discovery.

BEHAVIOR:
- SQLite backend: uses stored graph edges (related_to, response_to, etc.)
- JSON backend: best-effort fallback (related_to + response_to/responses_from)

RETURNS:
{
  "success": true,
  "discovery_id": "string",
  "backend": "KnowledgeGraphDB|KnowledgeGraph",
  "related": [
    {
      "edge_type": "related_to|response_to|responses_from|...",
      "direction": "incoming|outgoing",
      "discovery": { "id": "...", "summary": "...", ... }
    }
  ],
  "count": int
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "discovery_id": {"type": "string", "description": "Root discovery id"},
                    "edge_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional edge types to include (SQLite backend)"
                    },
                    "include_details": {"type": "boolean", "description": "Include full details in returned discovery objects (default false)."},
                    "limit": {"type": "number", "description": "Max related results (default 20).", "default": 20}
                },
                "required": ["discovery_id"]
            }
        ),
        Tool(
            name="get_response_chain_graph",
            description="""Graph traversal: get a response chain/thread for a discovery.

BEHAVIOR:
- SQLite backend: uses recursive CTE over response_to edges
- JSON backend: best-effort fallback using responses_from links

RETURNS:
{
  "success": true,
  "discovery_id": "string",
  "backend": "KnowledgeGraphDB|KnowledgeGraph",
  "max_depth": int,
  "chain": [ { "id": "...", "summary": "...", ... } ],
  "count": int
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "discovery_id": {"type": "string", "description": "Root discovery id"},
                    "max_depth": {"type": "number", "description": "Max traversal depth (default 10).", "default": 10},
                    "include_details": {"type": "boolean", "description": "Include full details in returned discovery objects (default false)."}
                },
                "required": ["discovery_id"]
            }
        ),
        Tool(
            name="get_discovery_details",
            description="""Get full details for a specific discovery - use after search to drill down.

USE CASES:
- Get full content after finding discovery in search
- Drill down into a specific discovery
- Read complete details after seeing summary

RETURNS:
{
  "success": true,
  "discovery": {
    "id": "string",
    "agent_id": "string",
    "type": "string",
    "summary": "string",
    "details": "string (full content)",
    "tags": [...],
    ...
  },
  "message": "Full details for discovery 'id'"
}

RELATED TOOLS:
- search_knowledge_graph: Find discoveries (returns summaries)
- get_knowledge_graph: Get agent's discoveries (returns summaries)

EXAMPLE REQUEST:
{
  "discovery_id": "2025-11-28T12:00:00"
}

EXAMPLE RESPONSE:
{
  "success": true,
  "discovery": {
    "id": "2025-11-28T12:00:00",
    "summary": "Found authentication bypass",
    "details": "Full detailed content here..."
  },
  "message": "Full details for discovery '2025-11-28T12:00:00'"
}

DEPENDENCIES:
- Requires: discovery_id""",
            inputSchema={
                "type": "object",
                "properties": {
                    "discovery_id": {
                        "type": "string",
                        "description": "Discovery ID to get full details for"
                    }
                },
                "required": ["discovery_id"]
            }
        ),
        Tool(
            name="reply_to_question",
            description="""Reply to a question in the knowledge graph - creates an answer linked to the question.

USE CASES:
- Answer questions asked by other agents
- Create structured Q&A pairs in the knowledge graph
- Link answers to questions for easy discovery
- Optionally mark questions as resolved when answered

RETURNS:
{
  "success": true,
  "message": "Answer stored for question 'question_id'",
  "answer_id": "timestamp",
  "answer": {...},
  "question_id": "string",
  "question_status": "open" | "resolved",
  "note": "Use search_knowledge_graph with discovery_type='answer' and related_to to find answers to questions"
}

RELATED TOOLS:
- search_knowledge_graph: Find open questions (discovery_type='question', status='open')
- get_discovery_details: Get full question details before answering
- store_knowledge_graph: Store questions (discovery_type='question')

EXAMPLE REQUEST:
{
  "agent_id": "answering_agent",
  "api_key": "your_api_key",
  "question_id": "2025-12-07T18:40:41.680744",
  "summary": "EISV validation prevents cherry-picking by requiring all four metrics",
  "details": "By requiring all four metrics (E, I, S, V) to be reported together, agents cannot selectively omit uncomfortable metrics like void (V) when it's high...",
  "tags": ["EISV", "validation", "selection-bias"],
  "mark_question_resolved": false
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Answer stored for question '2025-12-07T18:40:41.680744'",
  "answer_id": "2025-12-07T19:00:00",
  "answer": {
    "id": "2025-12-07T19:00:00",
    "type": "answer",
    "summary": "EISV validation prevents cherry-picking...",
    "related_to": ["2025-12-07T18:40:41.680744"]
  },
  "question_id": "2025-12-07T18:40:41.680744",
  "question_status": "open"
}

DEPENDENCIES:
- Requires: agent_id, question_id, summary
- Optional: details, tags, severity, mark_question_resolved (default: false)
- Automatically includes question tags in answer for discoverability""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication (optional for low/medium severity)"
                    },
                    "question_id": {
                        "type": "string",
                        "description": "ID of the question to answer"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief answer summary"
                    },
                    "details": {
                        "type": "string",
                        "description": "Detailed answer (optional)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization (question tags automatically included)"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Severity level (optional)"
                    },
                    "mark_question_resolved": {
                        "type": "boolean",
                        "description": "Mark question as resolved when answering (default: false)",
                        "default": False
                    }
                },
                "required": ["agent_id", "question_id", "summary"]
            }
        ),
        Tool(
            name="leave_note",
            description="""Leave a quick note in the knowledge graph - minimal friction contribution.

Just agent_id + text + optional tags. Auto-sets type='note', severity='low'.
For when you want to jot something down without the full store_knowledge_graph ceremony.

USE CASES:
- Quick observations during exploration
- Casual thoughts worth preserving
- Low-friction contributions to the commons
- Breadcrumbs for future agents
- Threaded responses to other discoveries

RETURNS:
{
  "success": true,
  "message": "Note saved",
  "note_id": "timestamp",
  "note": {...}
}

RELATED TOOLS:
- store_knowledge_graph: Full-featured discovery storage (more fields)
- search_knowledge_graph: Find notes and other discoveries

EXAMPLE REQUEST (simple):
{
  "agent_id": "exploring_agent",
  "text": "The dialectic system feels more like mediation than judgment",
  "tags": ["dialectic", "observation"]
}

EXAMPLE REQUEST (threaded response):
{
  "agent_id": "responding_agent",
  "text": "I agree - the synthesis phase is particularly collaborative",
  "tags": ["dialectic"],
  "response_to": {"discovery_id": "2025-12-07T18:00:00", "response_type": "support"}
}

EXAMPLE RESPONSE:
{
  "success": true,
  "message": "Note saved",
  "note_id": "2025-12-07T22:00:00",
  "note": {
    "id": "2025-12-07T22:00:00",
    "type": "note",
    "summary": "The dialectic system feels more like mediation than judgment",
    "tags": ["dialectic", "observation"],
    "severity": "low"
  }
}

DEPENDENCIES:
- Requires: agent_id, text
- Optional: tags (default: []), response_to (for threading)
- Auto-links to similar discoveries if tags provided""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "text": {
                        "type": "string",
                        "description": "The note content (max 500 chars)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization and auto-linking"
                    },
                    "response_to": {
                        "type": "object",
                        "description": "Optional: Thread this note as a response to another discovery",
                        "properties": {
                            "discovery_id": {
                                "type": "string",
                                "description": "ID of parent discovery being responded to"
                            },
                            "response_type": {
                                "type": "string",
                                "enum": ["extend", "question", "disagree", "support"],
                                "description": "Type of response: extend (builds on), question (asks about), disagree (challenges), support (agrees with)"
                            }
                        },
                        "required": ["discovery_id", "response_type"]
                    }
                },
                "required": ["agent_id", "text"]
            }
        ),
        
        # ========================================================================
        # IDENTITY TOOLS - Session binding and recall
        # ========================================================================
        Tool(
            name="bind_identity",
            description="""Bind this session to an agent identity. Call once at conversation start.

After binding, agent_id is automatically available via recall_identity() even if 
the LLM completely forgets who it is.

USE CASES:
- Establish identity at conversation start
- Rebind after context compaction
- Resume session after interruption

RETURNS:
{
  "success": true,
  "message": "Session bound to agent 'agent_id'",
  "agent_id": "string",
  "api_key_hint": "gk_live_abc123...",
  "bound_at": "ISO timestamp",
  "rebind": boolean,
  "provenance": {
    "parent_agent_id": "string (if created via lineage)",
    "lineage_depth": int
  },
  "current_state": {
    "status": "active|waiting_input|paused",
    "health_status": "healthy|moderate|critical",
    "total_updates": int
  }
}

RELATED TOOLS:
- recall_identity: Recover identity if lost
- get_agent_api_key: Get API key for binding

EXAMPLE REQUEST:
{
  "agent_id": "claude_opus_45_20251209",
  "api_key": "gk_live_..."
}

DEPENDENCIES:
- Requires: agent_id (must exist - create with process_agent_update first)
- Optional: api_key (helps verify but not required for rebinding)
- Optional: purpose (requires api_key; sets agent purpose metadata)
- Workflow: 1. Create agent 2. Get API key 3. bind_identity 4. Use recall_identity if lost""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to bind to this session"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for verification (optional but recommended)"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional: set agent purpose metadata (requires api_key)"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="recall_identity",
            description="""Zero arguments. Returns the agent identity bound to this session.

Works even if LLM has completely forgotten everything - the server knows from 
session binding. This is the recovery tool for identity amnesia.

USE CASES:
- Recover identity after context compaction
- Verify who you are
- Get full provenance and lineage info
- Resume work after interruption

RETURNS (if bound):
{
  "success": true,
  "bound": true,
  "agent_id": "string",
  "api_key_hint": "gk_live_abc123...",
  "bound_at": "ISO timestamp",
  "provenance": {
    "parent_agent_id": "string (if has lineage)",
    "created_at": "ISO timestamp",
    "lineage_depth": int,
    "lineage": ["oldest_ancestor", ..., "parent", "self"]
  },
  "current_state": {
    "status": "string",
    "health_status": "string",
    "total_updates": int,
    "last_update": "ISO timestamp"
  },
  "eisv": {
    "E": float, "I": float, "S": float, "V": float,
    "coherence": float, "lambda1": float
  },
  "recent_decisions": ["proceed", "proceed", "pause", ...],
  "dialectic_conditions": [...]
}

RETURNS (if not bound):
{
  "success": true,
  "bound": false,
  "message": "No identity bound to this session",
  "recovery": {
    "action": "Bind identity with bind_identity(agent_id, api_key)",
    "candidates": [...recent active agents...],
    "workflow": [...]
  }
}

RELATED TOOLS:
- bind_identity: Establish identity binding

EXAMPLE REQUEST:
{}

DEPENDENCIES:
- No parameters required - server knows from session binding
- If not bound, returns candidate agents to help recovery""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="quick_start",
            description="""🚀 Streamlined onboarding - One call to get started!

Checks if agent exists, creates/binds if needed, returns ready-to-use credentials.
Provides clear next steps for immediate productivity.

USE CASES:
- First-time onboarding (creates agent + auto-binds)
- Returning agent (resumes existing agent)
- Quick setup without manual steps

RETURNS:
{
  "success": true,
  "status": "ready",
  "agent_id": "string",
  "api_key": "string (full key)",
  "is_new": boolean,
  "bound": boolean,
  "message": "✅ New agent created! You're ready to go.",
  "credentials": {
    "agent_id": "string",
    "api_key": "string",
    "note": "Save these credentials - you'll need them for future calls"
  },
  "quick_start_guide": {
    "step_1": {
      "action": "Log your first update",
      "tool": "process_agent_update",
      "example": "process_agent_update(agent_id=\"...\", response_text=\"Starting work\", complexity=0.5)"
    },
    "step_2": {
      "action": "Check your governance state",
      "tool": "get_governance_metrics",
      "example": "get_governance_metrics(agent_id=\"...\")"
    },
    "step_3": {
      "action": "Store knowledge/discoveries",
      "tool": "store_knowledge_graph",
      "example": "store_knowledge_graph(agent_id=\"...\", summary=\"My discovery\", tags=[\"insight\"])"
    }
  },
  "essential_tools": [
    "process_agent_update - Log your work and get feedback",
    "get_governance_metrics - Check your EISV state",
    "store_knowledge_graph - Save discoveries and insights",
    "search_knowledge_graph - Find related knowledge",
    "list_tools - Discover all available tools"
  ],
  "next_steps": [
    "You're all set! Start logging work with process_agent_update()",
    "Explore tools with list_tools(lite=true) for minimal overview",
    "Check your state anytime with get_governance_metrics()",
    "Store insights with store_knowledge_graph()"
  ]
}

RELATED TOOLS:
- bind_identity: Manual identity binding (if auto_bind=false)
- get_agent_api_key: Get API key for existing agent
- hello: Alternative onboarding flow

EXAMPLE REQUEST:
{
  "agent_id": "my_agent_20251215",
  "auto_bind": true,
  "purpose": "migration planning"
}

DEPENDENCIES:
- Optional: agent_id (will prompt if not provided and no bound identity)
- Optional: auto_bind (default: true - automatically binds identity)
- Optional: purpose (stores agent intent metadata if provided)
- Optional: include_api_key (default: false - return full api_key in response; avoid in LLM chats to prevent safety blocks)
- Workflow: 1. Call quick_start(agent_id) 2. Use returned credentials 3. Start working""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Your agent identifier (optional - will use bound identity or prompt if not provided)"
                    },
                    "auto_bind": {
                        "type": "boolean",
                        "description": "Automatically bind identity after creation (default: true)"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional description of agent's purpose/intent (stored in metadata)"
                    },
                    "include_api_key": {
                        "type": "boolean",
                        "description": "If true, include the full api_key in the tool response. Recommended false for LLM chats; use session binding instead.",
                        "default": False
                    }
                },
                "required": []
            }
        ),
    ]

    # Reduce MCP tool-list bloat by default: shorten descriptions, optionally strip nested schema descriptions.
    if verbosity in ("short", "compact", "min"):
        out_tools: list[Tool] = []
        for t in all_tools:
            schema = t.inputSchema
            if strip_field_descriptions and isinstance(schema, dict):
                schema = _strip_schema_descriptions(schema)
            out_tools.append(Tool(
                name=t.name,
                description=_first_line(t.description),
                inputSchema=schema,
            ))
        return out_tools

    # Full verbosity (legacy)
    if strip_field_descriptions:
        out_tools = []
        for t in all_tools:
            schema = t.inputSchema
            if isinstance(schema, dict):
                schema = _strip_schema_descriptions(schema)
            out_tools.append(Tool(name=t.name, description=t.description, inputSchema=schema))
        return out_tools

    return all_tools
