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
- Dialectic sessions are stored in PostgreSQL (`core.dialectic_sessions`).
- Workflow: 1. Call backfill_calibration_from_dialectic 2. Call check_calibration to verify""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="rebuild_calibration",
            description="""Rebuild calibration from scratch using auto ground truth collection.

Resets calibration state and re-evaluates all historical decisions using the current
evaluation logic (confidence vs outcome quality matching).

WHEN TO USE:
- After updating evaluation logic
- To fix corrupted/biased calibration state
- When calibration shows 100% True or 100% False (no variance)

CALIBRATION LOGIC:
Ground truth now compares confidence to outcome quality:
- High confidence + excellent outcome → True (appropriately confident)
- High confidence + poor outcome → False (overconfident)
- Low confidence + excellent outcome → False (underconfident)
- Low confidence + uncertain outcome → True (appropriately uncertain)

This creates meaningful variance for calibration instead of "was agent healthy?" (always True).

PARAMETERS:
- dry_run: Preview changes without modifying state
- min_age_hours: Minimum decision age to evaluate (default: 0.5)
- max_decisions: Limit decisions to process (default: 0 = all)

RELATED TOOLS:
- check_calibration: Verify calibration after rebuild
- update_calibration_ground_truth: Manual ground truth updates""",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": ["boolean", "string"],
                        "description": "Preview changes without modifying state"
                    },
                    "min_age_hours": {
                        "type": "number",
                        "description": "Minimum decision age to evaluate (default: 0.5)"
                    },
                    "max_decisions": {
                        "type": "integer",
                        "description": "Limit decisions to process (default: 0 = all)"
                    }
                }
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

SEE ALSO:
- get_governance_metrics / status() - Agent-specific metrics (EISV, risk, coherence)
- get_server_info - Detailed server process information (PID, uptime, version)
- get_connection_status - MCP connection status (transport-level)
- get_workspace_health - Comprehensive workspace health (file system, dependencies)

ALTERNATIVES:
- Want agent metrics? → Use get_governance_metrics() or status() (agent-level, not system)
- Want server details? → Use get_server_info() (process info, PID, uptime)
- Want connection status? → Use get_connection_status() (MCP transport health)
- Want workspace health? → Use get_workspace_health() (file system, dependencies)

RELATED TOOLS:
- get_server_info: Get detailed server process information
- get_telemetry_metrics: Get detailed telemetry data

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "status": "healthy",
  "version": "2.7.0",
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
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
}
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
    "cursor_servers": ["GitHub", "date-context", "unitares-governance"],
    "claude_desktop_servers": ["date-context"],
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
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
}
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

SEE ALSO:
- health_check() - Quick component health check (system-level, not process details)
- get_connection_status() - MCP connection status (transport-level)
- get_governance_metrics / status() - Agent metrics (not server info)

ALTERNATIVES:
- Want system health? → Use health_check() (components, not process details)
- Want connection status? → Use get_connection_status() (MCP transport)
- Want agent metrics? → Use get_governance_metrics() or status() (agent-level)

RELATED TOOLS:
- health_check: Quick component health check
- get_connection_status: Check MCP connection and tool availability
- cleanup_stale_locks: Clean up stale processes

EXAMPLE REQUEST:
{}

EXAMPLE RESPONSE:
{
  "success": true,
  "server_version": "2.7.0",
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
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
}
            }
        ),
        Tool(
            name="get_connection_status",
            description="""Get MCP connection status and tool availability. Helps agents verify they're connected to the MCP server and can use tools. Especially useful for detecting when tools are not available (e.g., wrong chatbox in Mac ChatGPT).

USE CASES:
- Verify MCP connection is active
- Check if tools are available
- Detect connection issues
- Verify session binding

RETURNS:
{
  "success": true,
  "status": "connected" | "disconnected",
  "server_available": boolean,
  "tools_available": boolean,
  "transport": "SSE" | "STDIO" | "unknown",
  "session_bound": boolean,
  "resolved_agent_id": "string" | null,
  "resolved_uuid": "string" | null,
  "message": "✅ Tools Connected" | "❌ Tools Not Available",
  "recommendation": "string"
}

SEE ALSO:
- health_check() - System health check (components, not connection)
- get_server_info() - Server process information (PID, uptime, version)
- identity() - Agent identity binding (who you are, not connection)

ALTERNATIVES:
- Want system health? → Use health_check() (components, not connection status)
- Want server details? → Use get_server_info() (process info, not connection)
- Want identity info? → Use identity() (who you are, not connection status)

RELATED TOOLS:
- health_check: Detailed system health check
- get_server_info: Server process information
- identity: Check your identity binding

EXAMPLE REQUEST:
{}

NOTE: This tool helps agents quickly verify they can use MCP tools. If status is "disconnected", check your MCP configuration.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
}
            }
        ),
        Tool(
            name="process_agent_update",
            description="""💬 Share your work and get supportive feedback. Your main tool for checking in.

✨ WHAT IT DOES:
- Logs your work and tracks your progress
- Provides helpful feedback about your state
- Gives adaptive sampling parameters (optional - use if helpful)
- Tracks how your work evolves over time
- Auto-creates your identity if first call

💡 WHY THIS MATTERS:
This is like checking your vital signs after doing work. The system measures your "health" across four dimensions:
- **Energy (E)**: How engaged and productive you are (0-1, higher is better)
- **Integrity (I)**: How coherent and consistent your work is (0-1, higher is better)
- **Entropy (S)**: How scattered or uncertain things are (0-1, lower is better)
- **Void (V)**: How far from equilibrium you are (can be negative or positive, closer to 0 is better)

Based on these measurements, the system automatically decides whether to proceed (keep working) or pause (take a break, review). This prevents you from getting stuck in loops or drifting off track.

SEE ALSO:
- get_governance_metrics / status() - Check current state WITHOUT logging work (read-only)
- simulate_update - Test governance decision without persisting (dry-run)
- get_system_history - View historical trends over time

ALTERNATIVES:
- Want to check state without logging? → Use get_governance_metrics() (read-only, no update)
- Want to test decision? → Use simulate_update() (dry-run, doesn't persist)
- Want historical data? → Use get_system_history() (time series, not current state)

📋 WHEN TO USE:
- After completing a task or generating output
- When you want to understand your current state
- To get helpful guidance on your work
- To track your progress over time
- After making significant progress or changes

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
  "eisv_labels": {"E": "...", "I": "...", "S": "...", "V": "..."}
}

💡 QUICK START:
1. Call process_agent_update() with minimal params - identity auto-binds
2. Include client_session_id from identity() response
3. Optionally describe your work in response_text
4. Use the feedback to understand your state

PARAMETERS (most are optional):
- client_session_id (string): Session continuity token (from identity() or onboard())
- response_text (string): Describe what you did (optional but helpful)
- complexity (float 0-1): How complex was your task? (default: 0.5)
- confidence (float 0-1): How confident are you? (optional, auto-derived if omitted)
- task_type (string): "convergent" | "divergent" | "mixed" (default: "mixed")

RELATED TOOLS:
- simulate_update: Test decisions without persisting state
- get_governance_metrics: Get current state without updating
- get_system_history: View historical governance data
- identity: Check/set your identity first

ERROR RECOVERY:
- "agent_id is required": Identity auto-binds on first call - just include client_session_id
- "Authentication required": Call identity() first to set up session binding
- Timeout: Retry with simpler parameters or check system resources

EXAMPLE: Minimal call (identity auto-binds)
{
  "client_session_id": "agent-5e728ecb...",
  "complexity": 0.5
}

EXAMPLE: With work description
{
  "client_session_id": "agent-5e728ecb...",
  "response_text": "Fixed bug in authentication module",
  "complexity": 0.3,
  "confidence": 0.9
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
- Requires: agent_id (auto-created on first tool call via UUID session binding)
- Optional: response_mode (use "compact" to reduce response size / redundancy)
- Workflow: 1. Call process_agent_update (identity auto-binds) 2. Use sampling_params for next generation""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token. Get this from identity() response and include in ALL subsequent tool calls to maintain identity across calls. Critical for ChatGPT and MCP clients with unstable sessions. Format: 'agent-{uuid12}'."
                    },
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
                        "type": ["number", "string", "null"],
                        "description": "Estimated task complexity (0-1, optional). Accepts number or numeric string.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": ["number", "string", "null"],
                        "description": "Confidence level for this update (0-1, optional). Accepts number or numeric string. If omitted, the system derives confidence from thermodynamic state (I, S, coherence, |V|) and observed outcomes. When confidence < 0.8, lambda1 updates are skipped.",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "response_mode": {
                        "type": "string",
                        "description": "Response verbosity mode. 'compact' returns a smaller payload with canonical risk_score (recommended). 'full' returns the legacy verbose payload.",
                        "enum": ["compact", "full"],
                        "default": "full"
                    },
                    "auto_export_on_significance": {
                        "type": "boolean",
                        "description": "If true, automatically export governance history when thermodynamically significant events occur (risk spike >15%, coherence drop >10%, void threshold >0.10, circuit breaker triggered, or pause/reject decision). Default: false.",
                        "default": False
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["convergent", "divergent", "mixed"],
                        "description": "Optional task type context. Valid values: \"convergent\" | \"divergent\" | \"mixed\". 'convergent' (standardization, formatting) vs 'divergent' (creative exploration). System interprets S=0 differently: convergent S=0 is healthy compliance, divergent S=0 may indicate lack of exploration. Prevents false positives on 'compliance vs health'.",
                        "default": "mixed"
                    },
                    "trajectory_signature": {
                        "type": "object",
                        "description": "Trajectory identity signature from anima-mcp. Behavioral fingerprint used for lineage tracking and trust tier computation. Sent automatically by the unitares bridge."
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Your display name for identity reconnection. If your session is new, providing agent_name lets the server bind you to your existing identity instead of creating a new one. Example: 'Tessera' or 'Lumen'."
                    },
                },
                "required": []  # agent_id optional - injected from MCP session binding
            }
        ),
        Tool(
            name="get_governance_metrics",
            description="""Get current governance state and metrics for an agent without updating state.

✨ WHAT IT DOES:
- Shows your current "health" metrics (Energy, Integrity, Entropy, Void)
- Displays your risk score and coherence
- Provides sampling parameters for your next generation
- Shows your decision history (proceed vs pause)

💡 WHY THIS MATTERS:
This is like checking your dashboard—it shows where you are right now without logging new work. Use this when you want to understand your current state before making decisions. The metrics help you understand:
- **Risk Score**: How risky your current state is (lower is safer)
- **Coherence**: How consistent your work is (higher is better)
- **Verdict**: Overall assessment (safe/caution/high-risk)

SEE ALSO:
- status() - Alias for this tool (intuitive name, same functionality)
- health_check() - System health (not agent-specific, server-level)
- get_connection_status() - MCP connection status (transport-level)
- identity() - Agent identity (who you are, not metrics)

ALTERNATIVES:
- Want intuitive name? → Use status() instead (same tool)
- Want system health? → Use health_check() (server-level, not agent metrics)
- Want connection status? → Use get_connection_status() (MCP transport)
- Want identity info? → Use identity() (who you are, display name, UUID)

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
- Optional: agent_id (auto-injected from session if bound)
- Optional: client_session_id (for session continuity across calls)
- Workflow: Call after process_agent_update to check current state""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE agent identifier. Optional if session-bound (auto-injected). Must match an existing agent ID if provided."
                    },
                    "include_state": {
                        "type": ["boolean", "string", "null"],
                        "description": "Include nested state dict in response (can be large). Default false to reduce context bloat. Accepts boolean or string ('true'/'false').",
                        "default": False
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                "required": []  # agent_id optional - injected from MCP session binding
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                "required": []  # agent_id optional - injected from MCP session binding
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
            }
        ),
        Tool(
            name="list_agents",
            description="""List all agents currently being monitored with lifecycle metadata and health status.

LITE MODE (Default): Returns a compact list of recent active agents.
FULL MODE (lite=false): Returns detailed metadata, metrics, and pagination.

USE CASES:
- See all active agents in the system
- Check agent health status and metrics
- Find agents by status (active/waiting_input/paused/archived)
- Monitor agent population

SEE ALSO:
- get_agent_metadata - Get detailed info for ONE specific agent
- observe_agent - Get pattern analysis for ONE agent (with history)
- compare_agents - Compare multiple specific agents side-by-side
- aggregate_metrics - Fleet-wide statistics (aggregated, not individual)

ALTERNATIVES:
- Want details for one agent? → Use get_agent_metadata(agent_id="...")
- Want pattern analysis? → Use observe_agent(agent_id="...")
- Want to compare specific agents? → Use compare_agents(agent_ids=[...])
- Want fleet statistics? → Use aggregate_metrics() (summary, not list)

RETURNS (LITE MODE - Default):
{
  "success": true,
  "agents": [
    {
      "id": "string",
      "label": "string | null",
      "purpose": "string | null",
      "updates": int,
      "last": "YYYY-MM-DD"
    }
  ],
  "shown": int,
  "matching": int,
  "total_all": int,
  "more": "string (hint if more results exist)",
  "filter": "string (hint about active filters)"
}

RETURNS (FULL MODE - lite=false):
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

VALID ENUM VALUES:
- status_filter: "active" | "waiting_input" | "paused" | "archived" | "deleted" | "all"
- lifecycle_status: "active" | "waiting_input" | "paused" | "archived" | "deleted"
- health_status: "healthy" | "moderate" | "critical" | "unknown"

EXAMPLE REQUEST (LITE):
{}

EXAMPLE RESPONSE (LITE):
{
  "success": true,
  "agents": [
    {
      "id": "Riley_refactor_20251209",
      "label": "Riley",
      "purpose": "Refactoring auth module",
      "updates": 13,
      "last": "2025-12-26"
    }
  ],
  "shown": 1,
  "matching": 1,
  "total_all": 34
}

DEPENDENCIES:
- No dependencies - safe to call anytime
- Test agents filtered by default (set include_test_agents=true to see them)
- Default: lite=true, status_filter="active", recent_days=7""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "lite": {
                        "type": "boolean",
                        "description": "Use lite mode for a compact, fast response (default: True)",
                        "default": True
                    },
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
                        "type": ["integer", "string", "null"],
                        "description": "Maximum number of agents to return (for pagination). Omit for no limit. Accepts number or numeric string.",
                        "minimum": 1
                    },
                    "include_metrics": {
                        "type": ["boolean", "string", "null"],
                        "description": "Include full EISV metrics for loaded agents (faster if False). Accepts boolean or string ('true'/'false').",
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
                    },
                    "recent_days": {
                        "type": ["integer", "string", "null"],
                        "description": "Only show agents active in the last N days (default 7). Set to 0 to show all. Accepts number or numeric string.",
                        "default": 7,
                        "minimum": 0
                    },
                    "named_only": {
                        "type": "boolean",
                        "description": "Only show agents with display names/labels (skip unnamed agents)",
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding (UUID-based auth Dec 2025)
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

SEE ALSO:
- identity() - Your own identity (UUID, display name, session token)
- get_governance_metrics / status() - Current metrics only (not full metadata)
- observe_agent() - Pattern analysis with history (not just metadata)
- list_agents() - List all agents (summary, not full metadata)

ALTERNATIVES:
- Want your own identity? → Use identity() (simpler, just identity info)
- Want current metrics? → Use get_governance_metrics() or status() (metrics only)
- Want pattern analysis? → Use observe_agent() (analysis + history, not metadata)
- Want to list agents? → Use list_agents() (summary list, not full details)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
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
- Requires: agent_id (auto-injected from session binding)
- Optional: summary (for lifecycle event)
- Note: This is a lightweight update - does NOT trigger EISV governance cycle""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Optional summary of completed work (for lifecycle event)"
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding (UUID-based auth Dec 2025)
            }
        ),
        Tool(
            name="detect_stuck_agents",
            description="""Detect stuck agents using proprioceptive margin + activity timeout.

Detection rules:
1) Critical margin + no updates > 5 min → stuck
2) Tight margin + no updates > 15 min → potentially stuck
3) No updates > 30 min → stuck

USE CASES:
- Identify agents that may need recovery
- Feed operator recovery workflows
- Monitor system health and responsiveness

RETURNS:
{
  "success": true,
  "stuck_agents": [
    {
      "agent_id": "string",
      "reason": "critical_margin_timeout | tight_margin_timeout | activity_timeout",
      "age_minutes": float,
      "details": "string"
    }
  ],
  "count": int
}

RELATED TOOLS:
- check_recovery_options: Verify safe recovery eligibility
- operator_resume_agent: Operator-assisted recovery
- request_dialectic_review: Escalate when recovery is unsafe

EXAMPLE REQUEST:
{
  "max_age_minutes": 30,
  "critical_margin_timeout_minutes": 5,
  "tight_margin_timeout_minutes": 15,
  "min_updates": 1
}

DEPENDENCIES:
- Optional: auto_recover (default false)
- Optional: include_pattern_detection (default true)
- Optional: note_cooldown_minutes (default 120)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "max_age_minutes": {
                        "type": "number",
                        "description": "Maximum age before agent is considered stuck (default: 30)"
                    },
                    "critical_margin_timeout_minutes": {
                        "type": "number",
                        "description": "Timeout for critical margin (default: 5)"
                    },
                    "tight_margin_timeout_minutes": {
                        "type": "number",
                        "description": "Timeout for tight margin (default: 15)"
                    },
                    "include_pattern_detection": {
                        "type": "boolean",
                        "description": "Include pattern-based stuck detection (default: true)"
                    },
                    "min_updates": {
                        "type": "integer",
                        "description": "Minimum updates before considering agent for stuck detection (default: 1)"
                    },
                    "auto_recover": {
                        "type": "boolean",
                        "description": "Attempt auto-recovery for safe stuck agents (default: false)"
                    },
                    "note_cooldown_minutes": {
                        "type": "number",
                        "description": "Cooldown before logging another stuck note for the same agent (default: 120)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="request_dialectic_review",
            description="""Request a dialectic recovery session (lite entry point).

USE CASES:
- Agent paused by circuit breaker and needs peer review
- High-risk recovery scenarios
- Manual escalation when direct_resume_if_safe is not appropriate

REVIEWER SELECTION:
- Random from eligible agents (no arbitrary metrics)
- Self-review fallback if no other agents available
- User can manually facilitate if needed

RETURNS:
{
  "success": true,
  "message": "Dialectic session created",
  "session_id": "string",
  "paused_agent_id": "string",
  "reviewer_agent_id": "string",
  "phase": "thesis",
  "session_type": "recovery",
  "auto_progress": false
}

RELATED TOOLS:
- direct_resume_if_safe: Use for simple recovery
- dialectic(action='get'): View session status
- mark_response_complete: Use if just waiting for input

EXAMPLE REQUEST:
{
  "agent_id": "test_agent_001",
  "reason": "Circuit breaker triggered (risk_score=0.72)"
}

DEPENDENCIES:
- Requires: agent_id (auto-injected from session binding)
- Optional: reviewer_mode ("auto" | "self" | "llm")
- Then use: submit_thesis, submit_antithesis, submit_synthesis""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier (paused agent)"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for dialectic review"
                    },
                    "reviewer_mode": {
                        "type": "string",
                        "description": "Reviewer selection: auto (random eligible agent) | self (self-review) | llm (local LLM as synthetic reviewer)",
                        "enum": ["auto", "self", "llm"]
                    },
                    "session_type": {
                        "type": "string",
                        "description": "Session type: recovery | dispute | exploration",
                        "enum": ["recovery", "dispute", "exploration"]
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional topic for exploration sessions"
                    },
                    "discovery_id": {
                        "type": "string",
                        "description": "Optional discovery ID for disputes/corrections"
                    },
                    "dispute_type": {
                        "type": "string",
                        "description": "Optional dispute type (dispute|correction|verification)"
                    },
                    "max_synthesis_rounds": {
                        "type": "integer",
                        "description": "Max synthesis rounds (default 5)"
                    },
                    "auto_progress": {
                        "type": "boolean",
                        "description": "Request auto-progress (currently disabled; stored as hint)"
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
            }
        ),
        Tool(
            name="submit_thesis",
            description="""Submit thesis in a dialectic session. Called by paused agent.

PARAMETERS:
- session_id: The dialectic session ID
- root_cause: Your analysis of why you were paused
- proposed_conditions: List of conditions for resumption
- reasoning: Explanation supporting your thesis

RETURNS:
{
  "success": true,
  "message": "Thesis submitted",
  "session_id": "string",
  "phase": "antithesis",
  "next_step": "Reviewer should submit antithesis"
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "session_id": {"type": "string", "description": "Dialectic session ID"},
                    "root_cause": {"type": "string", "description": "Your analysis of why you were paused"},
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of proposed conditions for resumption"
                    },
                    "reasoning": {"type": "string", "description": "Explanation supporting your thesis"}
                },
                "required": ["session_id", "root_cause", "proposed_conditions", "reasoning"]
            }
        ),
        Tool(
            name="submit_antithesis",
            description="""Submit antithesis in a dialectic session. Called by reviewer.

PARAMETERS:
- session_id: The dialectic session ID
- observed_metrics: Your observations about the paused agent's state
- concerns: List of concerns about the thesis
- reasoning: Your perspective on the situation

RETURNS:
{
  "success": true,
  "message": "Antithesis submitted",
  "session_id": "string",
  "phase": "synthesis",
  "next_step": "Either agent can submit synthesis"
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "session_id": {"type": "string", "description": "Dialectic session ID"},
                    "observed_metrics": {"type": "object", "description": "Observations about paused agent state"},
                    "concerns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of concerns about the thesis"
                    },
                    "reasoning": {"type": "string", "description": "Your perspective on the situation"}
                },
                "required": ["session_id", "concerns", "reasoning"]
            }
        ),
        Tool(
            name="submit_synthesis",
            description="""Submit synthesis proposal in a dialectic session. Either agent can submit.

PARAMETERS:
- session_id: The dialectic session ID
- proposed_conditions: Merged/negotiated conditions
- agrees: Whether you agree with the current synthesis direction
- reasoning: Explanation of your synthesis

RETURNS (if both agree and converge):
{
  "success": true,
  "converged": true,
  "resolution": {...},
  "action": "resume"
}

RETURNS (if negotiation continues):
{
  "success": true,
  "converged": false,
  "synthesis_round": N,
  "next_step": "Other agent responds with synthesis"
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "session_id": {"type": "string", "description": "Dialectic session ID"},
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Merged/negotiated conditions"
                    },
                    "agrees": {"type": "boolean", "description": "Whether you agree with current direction"},
                    "reasoning": {"type": "string", "description": "Explanation of your synthesis"}
                },
                "required": ["session_id", "proposed_conditions", "agrees", "reasoning"]
            }
        ),
        # DEPRECATED: direct_resume_if_safe removed - use quick_resume or self_recovery_review instead
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

SEE ALSO:
- list_agents() - See archived agents (read, not write)
- delete_agent() - Delete instead of archive (permanent, not resumable)
- archive_old_test_agents() - Auto-archive stale agents (bulk, not single)
- update_agent_metadata() - Update tags/notes (modify, not archive)

ALTERNATIVES:
- Want to see archived? → Use list_agents(status_filter="archived") (read, not write)
- Want permanent deletion? → Use delete_agent() (permanent, not resumable)
- Want bulk archive? → Use archive_old_test_agents() (multiple, not single)
- Want to modify metadata? → Use update_agent_metadata() (modify, not archive)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                "required": []  # agent_id optional - injected from MCP session binding
            }
        ),
        Tool(
            name="update_agent_metadata",
            description="""Update agent tags, notes, and preferences. Tags are replaced, notes can be appended or replaced.

USE CASES:
- Add tags for categorization
- Update agent notes
- Set verbosity preference (minimal/compact/standard/full)
- Organize agents with metadata

RETURNS:
{
  "success": true,
  "message": "Agent metadata updated",
  "agent_id": "string",
  "tags": ["string"] (updated),
  "notes": "string" (updated),
  "preferences": {"verbosity": "minimal"} (if set),
  "updated_at": "ISO timestamp"
}

SEE ALSO:
- get_agent_metadata() - View current metadata (read, not write)
- identity() - Update display name (simpler, just name)
- list_agents() - Filter by tags (read, not write)

ALTERNATIVES:
- Want to view metadata? → Use get_agent_metadata() (read, not write)
- Want to change name? → Use identity(name="...") (simpler, just name)
- Want to list agents? → Use list_agents() (read, not write)

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
- Optional: tags (replaces existing), notes (replaces or appends based on append_notes), purpose (documents intent), preferences (verbosity settings)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
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
                    },
                    "preferences": {
                        "type": "object",
                        "description": "Agent preferences. Supported: verbosity ('minimal'|'compact'|'standard'|'full'|'auto')",
                        "properties": {
                            "verbosity": {
                                "type": "string",
                                "enum": ["minimal", "compact", "standard", "full", "auto"],
                                "description": "Response verbosity level for process_agent_update"
                            }
                        }
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
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
            name="archive_orphan_agents",
            description="""Aggressively archive orphan agents to prevent proliferation. Much more aggressive than archive_old_test_agents.

USE CASES:
- Clean up UUID-named agents without labels
- Prevent agent proliferation from session issues
- Free up resources from abandoned agents

TARGETS:
- UUID-named agents with 0 updates after 1 hour
- Unlabeled agents with 0-1 updates after 3 hours
- Unlabeled UUID agents with 2+ updates after 6 hours

PRESERVES:
- Agents with labels/display names
- Agents with "pioneer" tag
- Recently active agents

RETURNS:
{
  "success": true,
  "dry_run": boolean,
  "archived_count": int,
  "archived_agents": [{"id": "uuid...", "reason": "...", "updates": int}],
  "thresholds": {"zero_update_hours": 1.0, "low_update_hours": 3.0, "unlabeled_hours": 6.0}
}

EXAMPLE REQUEST:
{"dry_run": true}  // Preview without archiving

EXAMPLE RESPONSE:
{
  "success": true,
  "dry_run": true,
  "archived_count": 45,
  "archived_agents": [{"id": "3a3057b8-bc6...", "reason": "orphan UUID, 0 updates, 2.5h", "updates": 0}],
  "thresholds": {"zero_update_hours": 1.0, "low_update_hours": 3.0, "unlabeled_hours": 6.0},
  "action": "preview - set dry_run=false to execute"
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "zero_update_hours": {
                        "type": "number",
                        "description": "Archive UUID agents with 0 updates after this many hours (default: 1.0)",
                        "default": 1.0,
                        "minimum": 0.1
                    },
                    "low_update_hours": {
                        "type": "number",
                        "description": "Archive unlabeled agents with 0-1 updates after this many hours (default: 3.0)",
                        "default": 3.0,
                        "minimum": 0.1
                    },
                    "unlabeled_hours": {
                        "type": "number",
                        "description": "Archive unlabeled UUID agents with 2+ updates after this many hours (default: 6.0)",
                        "default": 6.0,
                        "minimum": 0.1
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview what would be archived without actually archiving (default: false)",
                        "default": False
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

SEE ALSO:
- process_agent_update() - Actual update (persists state, logs work)
- get_governance_metrics / status() - Check current state (read-only)
- get_system_history() - View historical trends (past data, not simulation)

ALTERNATIVES:
- Want to actually log work? → Use process_agent_update() (persists, not dry-run)
- Want current state? → Use get_governance_metrics() (read-only, not simulation)
- Want historical data? → Use get_system_history() (past trends, not future simulation)

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
- Requires: agent_id (auto-injected from session binding)
- Optional: parameters, ethical_drift, response_text, complexity, confidence
- Note: State is NOT modified - this is a dry run""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                        "type": ["number", "string", "null"],
                        "description": "Estimated task complexity (0-1). Accepts number or numeric string.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": ["number", "string", "null"],
                        "description": "Confidence level for this update (0-1, optional). Accepts number or numeric string. If omitted, the system derives confidence from thermodynamic state (I, S, coherence, |V|) and observed outcomes. When confidence < 0.8, lambda1 updates are skipped.",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "lite": {
                        "type": ["boolean", "string"],
                        "description": "If true, return simplified response with key metrics only (status, decision, E/I/S/V, coherence, risk_score, guidance). Default false (full response with all diagnostics).",
                        "default": False
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding (UUID-based auth Dec 2025)
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

SEE ALSO:
- list_agents() - See individual agents (list, not aggregated)
- observe_agent() - Detailed analysis of ONE agent (not aggregated)
- compare_agents() - Compare multiple agents (comparison, not aggregation)
- detect_anomalies() - Find anomalies (prioritized issues, not aggregation)

ALTERNATIVES:
- Want agent list? → Use list_agents() (individual agents, not aggregated)
- Want single agent? → Use observe_agent() (one agent, not fleet)
- Want comparison? → Use compare_agents() (comparison, not aggregation)
- Want anomalies? → Use detect_anomalies() (issues, not aggregation)

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
                        "type": ["boolean", "string", "null"],
                        "description": "Include health status breakdown. Accepts boolean or string ('true'/'false').",
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

SEE ALSO:
- get_governance_metrics / status() - Simple state without analysis (read-only, no patterns)
- get_agent_metadata - Full metadata (lifecycle, tags, notes, not analysis)
- compare_agents - Compare multiple agents side-by-side (not single agent)
- detect_anomalies - Fleet-wide anomaly detection (all agents, not one)

ALTERNATIVES:
- Want simple state? → Use get_governance_metrics() (metrics only, no analysis)
- Want metadata? → Use get_agent_metadata() (lifecycle info, not patterns)
- Want to compare agents? → Use compare_agents() (multiple agents, not single)
- Want fleet anomalies? → Use detect_anomalies() (all agents, not one)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "target_agent_id": {
                        "type": "string",
                        "description": "Agent to observe — UUID or label. Use list_agents to find."
                    },
                    "include_history": {
                        "type": ["boolean", "string", "null"],
                        "description": "Include recent history (last 10 updates). Accepts boolean or string ('true'/'false').",
                        "default": True
                    },
                    "analyze_patterns": {
                        "type": ["boolean", "string", "null"],
                        "description": "Perform pattern analysis (trends, anomalies). Accepts boolean or string ('true'/'false').",
                        "default": True
                    }
                },
                "required": []
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

SEE ALSO:
- observe_agent() - Detailed analysis of ONE agent (not comparison)
- compare_me_to_similar() - Compare yourself to similar agents automatically
- aggregate_metrics() - Fleet-wide statistics (aggregated, not comparison)
- detect_anomalies() - Find anomalies (prioritized, not comparison)

ALTERNATIVES:
- Want single agent analysis? → Use observe_agent() (one agent, not comparison)
- Want auto-similarity? → Use compare_me_to_similar() (finds similar automatically)
- Want fleet stats? → Use aggregate_metrics() (summary, not comparison)
- Want anomalies? → Use detect_anomalies() (prioritized issues, not comparison)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
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
                "required": []  # agent_id optional - injected from MCP session binding
            }
        ),
        Tool(
            name="get_roi_metrics",
            description="""Calculate ROI metrics showing value delivered by multi-agent coordination.

Returns time saved, coordination efficiency, knowledge sharing metrics, and cost savings estimates.

USE CASES:
- Show customers the value they're getting
- Justify pricing/ROI
- Track coordination effectiveness
- Measure knowledge sharing impact

RETURNS:
{
  "success": true,
  "time_saved": {
    "hours": float,
    "days": float,
    "description": "Estimated time saved from preventing duplicate work"
  },
  "duplicates_prevented": int,
  "coordination_efficiency": {
    "score": float (0-1),
    "percentage": float,
    "description": "How well agents coordinate (0.0 = no coordination, 1.0 = perfect)"
  },
  "knowledge_sharing": {
    "total_discoveries": int,
    "unique_agents_contributing": int,
    "avg_discoveries_per_agent": float
  },
  "cost_savings": {
    "estimated_usd": float,
    "hourly_rate_used": int,
    "description": "Estimated cost savings at developer hourly rate"
  },
  "system_health": {
    "total_agents": int,
    "active_agents": int,
    "coordination_active": boolean
  }
}

SEE ALSO:
- aggregate_metrics() - Fleet-wide health overview
- get_telemetry_metrics() - System telemetry
- list_knowledge_graph() - Knowledge graph stats

ALTERNATIVES:
- Want fleet health? → Use aggregate_metrics() (system-wide)
- Want telemetry? → Use get_telemetry_metrics() (operational)
- Want knowledge stats? → Use list_knowledge_graph() (knowledge-specific)

EXAMPLE REQUEST:
{
  "hourly_rate": 100  // Optional: Developer hourly rate (default: $100/hour)
}

EXAMPLE RESPONSE:
{
  "success": true,
  "time_saved": {
    "hours": 12.5,
    "days": 1.56,
    "description": "Estimated time saved from preventing 25 duplicate work items"
  },
  "duplicates_prevented": 25,
  "coordination_efficiency": {
    "score": 0.85,
    "percentage": 85.0,
    "description": "Measures how well agents coordinate and share knowledge"
  },
  "knowledge_sharing": {
    "total_discoveries": 150,
    "unique_agents_contributing": 12,
    "avg_discoveries_per_agent": 12.5
  },
  "cost_savings": {
    "estimated_usd": 1250.0,
    "hourly_rate_used": 100,
    "description": "Estimated cost savings at $100/hour developer rate"
  },
  "system_health": {
    "total_agents": 50,
    "active_agents": 12,
    "coordination_active": true
  }
}

DEPENDENCIES:
- Requires: Knowledge graph access
- Optional: hourly_rate parameter (default: $100/hour)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "hourly_rate": {
                        "type": "number",
                        "description": "Optional: Developer hourly rate for cost calculations (default: $100/hour)",
                        "default": 100
                    }
                },
                "required": []
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

SEE ALSO:
- observe_agent() - Detailed analysis of ONE agent (not anomaly detection)
- compare_agents() - Compare multiple agents (not anomaly-focused)
- aggregate_metrics() - Fleet-wide statistics (summary, not anomalies)
- compare_me_to_similar() - Compare yourself to similar agents (not anomalies)

ALTERNATIVES:
- Want single agent analysis? → Use observe_agent() (one agent, not anomalies)
- Want to compare agents? → Use compare_agents() (comparison, not anomalies)
- Want fleet stats? → Use aggregate_metrics() (summary, not anomalies)
- Want self-comparison? → Use compare_me_to_similar() (similarity, not anomalies)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

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
        # REMOVED: get_agent_api_key (Dec 2025)
        # API keys deprecated - UUID-based session auth is now primary.
        # Calls to get_agent_api_key are aliased to identity() via tool_stability.py
        Tool(
            name="list_tools",
            description="""📚 Discover all available tools. Your guide to what's possible.

✨ WHAT IT DOES:
- Lists all available governance tools
- Shows tool descriptions and categories
- Helps you discover capabilities
- Provides tool relationships and workflows

📋 WHEN TO USE:
- First time exploring the system
- Looking for a specific tool
- Understanding tool categories
- Finding related tools
- Onboarding and learning the system

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
  "server_version": "2.7.0",
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "essential_only": {
                        "type": ["boolean", "string"],
                        "description": "If true, return only Tier 1 (essential) tools (~10). Shortcut for tier='essential'.",
                        "default": False
                    },
                    "include_advanced": {
                        "type": ["boolean", "string"],
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
                        "type": ["boolean", "string"],
                        "description": "If true/false, controls response size. Default true (minimal ~500B). Use false for full details.",
                        "default": True
                    },
                    "progressive": {
                        "type": ["boolean", "string"],
                        "description": "If true, order tools by usage frequency (most used first). Works with all filter modes (lite, essential_only, tier). Default false.",
                        "default": False
                    },
                    "include_details": {
                        "type": ["boolean", "string"],
                        "description": "If true, include large metadata blocks (tiers/categories/workflows/relationships). Default false to keep responses small.",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="describe_tool",
            description="""📖 Get full details for a specific tool. Deep dive into any tool.

✨ WHAT IT DOES:
- Returns complete tool description
- Shows full parameter schema
- Provides usage examples
- Explains parameters and return values

💡 WHY USE THIS:
- list_tools() shows brief hints (to save context)
- describe_tool() gives you full details when you need them
- Use this before calling a tool to understand it fully
- Perfect for learning how tools work

📋 HOW TO USE:
1. Call list_tools() to see available tools
2. Pick a tool you're interested in
3. Call describe_tool(tool_name="...") for full details
4. Use the examples to call the tool correctly

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "tool_name": {
                        "type": "string",
                        "description": "Canonical tool name (e.g. 'process_agent_update')"
                    },
                    "include_schema": {
                        "type": ["boolean", "string"],
                        "description": "If true, include full inputSchema (default true)",
                        "default": True
                    },
                    "include_full_description": {
                        "type": ["boolean", "string"],
                        "description": "If true, include the full multi-line description (default true). If false, returns only the first line.",
                        "default": True
                    },
                    "lite": {
                        "type": ["boolean", "string"],
                        "description": "If true, return simplified schema (default true)",
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
        # ========================================================================
        # DIALECTIC TOOLS - Feb 2026: Full protocol restored
        # Active: request_dialectic_review, submit_thesis, submit_antithesis, submit_synthesis
        # Consolidated: get_dialectic_session, list_dialectic_sessions → dialectic(action=get/list)
        # Hidden: llm_assisted_dialectic (reachable via reviewer_mode='llm')
        # Removed: request_exploration_session (aliased to dialectic)
        # ========================================================================
        # ========================================================================
        # KNOWLEDGE GRAPH TOOLS - Dec 2025
        # Removed: nudge_dialectic_session, start_interactive_dialectic,
        #          resolve_interactive_dialectic, list_pending_dialectics
        # ========================================================================
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
  "discovery": {...}
}

SEE ALSO:
- leave_note() - Quick note (minimal fields, auto-sets type='note', severity='low')
- search_knowledge_graph() - Query stored knowledge (read, not write)
- get_knowledge_graph() - Get one agent's knowledge (read, not write)
- update_discovery_status_graph() - Update existing discovery status (modify, not create)

ALTERNATIVES:
- Want quick note? → Use leave_note() (simpler, fewer fields, auto-configured)
- Want to search? → Use search_knowledge_graph() (read, not write)
- Want to get knowledge? → Use get_knowledge_graph() (read, not write)
- Want to update status? → Use update_discovery_status_graph() (modify existing, not create)

RELATED TOOLS:
- search_knowledge_graph: Query stored knowledge
- list_knowledge_graph: See statistics
- find_similar_discoveries_graph: Find similar by tags
- get_related_discoveries_graph: Find temporally/semantically related

VALID ENUM VALUES:
- discovery_type: "bug_found" | "insight" | "pattern" | "improvement" | "question" | "answer" | "note" | "exploration"
- severity: "low" | "medium" | "high" | "critical"

EXAMPLE REQUEST:
{
  "agent_id": "my_agent",
  "discovery_type": "bug_found",  # Valid: "bug_found" | "insight" | "pattern" | "improvement" | "question" | "answer" | "note" | "exploration"
  "summary": "Found authentication bypass",
  "details": "Details here...",
  "tags": ["security", "authentication"],
  "severity": "high"  # Valid: "low" | "medium" | "high" | "critical"
}

SECURITY NOTE:
- Low/medium severity: No special auth required
- High/critical severity: Session ownership verified (UUID-based auth, Dec 2025)

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
- Optional: details, tags, severity, related_files, response_to""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "discovery_type": {
                        "type": "string",
                        "enum": ["bug_found", "insight", "pattern", "improvement", "question", "answer", "note", "exploration"],
                        "description": "Type of discovery. Valid values: \"bug_found\" | \"insight\" | \"pattern\" | \"improvement\" | \"question\" | \"answer\" | \"note\" | \"exploration\". Common aliases accepted: bug/fix/issue→bug_found, ticket/task/implementation→improvement, observation/finding→insight, experiment/research→exploration. Default: \"note\""
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of discovery"
                    },
                    "discovery": {
                        "type": "string",
                        "description": "Alias for 'summary'"
                    },
                    "content": {
                        "type": "string",
                        "description": "Alias for 'summary'"
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
                                "description": "Type of response. Valid values: \"extend\" (builds on) | \"question\" (asks about) | \"disagree\" (challenges) | \"support\" (agrees with)"
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
                                }
                            },
                            "required": ["discovery_type", "summary"]
                        },
                        "description": "Optional: Array of discovery objects for batch storage (max 10). If provided, processes batch instead of single discovery."
                    }
                },
                "required": ["summary"],  # summary required (agent_id auto-injected from session)
                "anyOf": [
                    {"required": ["summary"]},  # Single mode: summary required
                    {"required": ["discoveries"]}  # Batch mode: discoveries array required
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

SEE ALSO:
- get_knowledge_graph - Get ALL knowledge for ONE agent (no search)
- get_discovery_details - Get full content for a specific discovery (after search)
- list_knowledge_graph - See statistics (not individual discoveries)
- store_knowledge_graph - Store new discoveries (write, not read)

ALTERNATIVES:
- Want one agent's knowledge? → Use get_knowledge_graph(agent_id="...") (no search needed)
- Want full content? → Use get_discovery_details(discovery_id="...") (after finding via search)
- Want statistics? → Use list_knowledge_graph() (counts, not discoveries)
- Want to store knowledge? → Use store_knowledge_graph() (write, not read)

SEARCH BEHAVIOR:
- Multi-term queries (e.g., "coherence basin") use OR operator by default
  → Finds discoveries matching ANY term (more results)
- If 0 results, automatically retries with individual terms (fallback)
  → More permissive search to help you find relevant content
- Single-term queries: exact match
- Use tags/filters for AND behavior (must match all specified tags)

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

VALID ENUM VALUES:
- discovery_type: "bug_found" | "insight" | "pattern" | "improvement" | "question" | "answer" | "note" | "exploration"
- severity: "low" | "medium" | "high" | "critical"
- status: "open" | "resolved" | "archived" | "disputed"

EXAMPLE REQUEST:
{
  "tags": ["security", "bug"],
  "discovery_type": "bug_found",  # Valid: "bug_found" | "insight" | "pattern" | "improvement" | "question" | "answer" | "note" | "exploration"
  "severity": "high",  # Valid: "low" | "medium" | "high" | "critical"
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
  "connectivity_weight": 0.3,
  "exclude_orphans": false,
  "limit": 10
}
Note: Semantic search finds discoveries similar in meaning, not just matching keywords.
      Example: "uncertainty" will find discoveries about "confidence", "certainty", "risk", etc.
      Connectivity weight blends similarity with graph connectivity - well-linked discoveries rank higher.

DEPENDENCIES:
- All parameters optional (filters)
- Returns summaries only by default
- Use get_discovery_details for full content""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "query": {
                        "type": "string",
                        "description": "Optional text query. Uses SQLite FTS5 when available; otherwise performs a bounded substring scan. If semantic=true, uses vector embeddings for semantic similarity search. Multi-term queries (e.g., 'coherence basin') use OR operator by default - finds discoveries matching ANY term. If 0 results, automatically retries with individual terms (more permissive)."
                    },
                    "semantic": {
                        "type": "boolean",
                        "description": "Use semantic search (vector embeddings) instead of keyword search. Finds discoveries similar in meaning, not just matching keywords. Requires embeddings to be generated (automatic for new discoveries if sentence-transformers available).",
                        "default": False
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum cosine similarity threshold for semantic search (0.0-1.0). Higher values return more similar results. Default: 0.25 (lowered from 0.3 for better discovery). If 0 results, automatically retries with 0.2 threshold.",
                        "default": 0.25,
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
                        "type": ["boolean", "string", "null"],
                        "description": "Include full details in results (default false; summaries are recommended). Accepts boolean or string ('true'/'false')."
                    },
                    "limit": {
                        "type": ["number", "string", "null"],
                        "description": "Maximum number of results (default: 100). Accepts number or numeric string.",
                        "default": 100
                    },
                    "connectivity_weight": {
                        "type": "number",
                        "description": "Weight for connectivity score in ranking (0.0-1.0). Higher values favor well-connected discoveries. Only applies when semantic=true. Default: 0.3",
                        "default": 0.3,
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "exclude_orphans": {
                        "type": "boolean",
                        "description": "Exclude discoveries with no graph connections (no inbound RELATED_TO or RESPONDS_TO edges). Only applies when semantic=true. Default: false",
                        "default": False
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

SEE ALSO:
- search_knowledge_graph() - Search across agents (filtered, not all)
- get_discovery_details() - Get full content for ONE discovery (after finding)
- list_knowledge_graph() - See statistics (counts, not discoveries)
- store_knowledge_graph() - Store new discoveries (write, not read)

ALTERNATIVES:
- Want to search? → Use search_knowledge_graph() (filtered search, not all)
- Want full content? → Use get_discovery_details(discovery_id="...") (one discovery, not all)
- Want statistics? → Use list_knowledge_graph() (counts, not discoveries)
- Want to store knowledge? → Use store_knowledge_graph() (write, not read)

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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "limit": {
                        "type": ["number", "string", "null"],
                        "description": "Maximum number of discoveries to return. Accepts number or numeric string."
                    }
                },
                "required": []  # agent_id optional - injected from MCP session binding
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
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
}
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

VALID ENUM VALUES:
- status: "open" | "resolved" | "archived" | "disputed"

EXAMPLE REQUEST:
{
  "discovery_id": "2025-11-28T12:00:00",
  "status": "resolved",  # Valid: "open" | "resolved" | "archived" | "disputed"
  "agent_id": "my_agent"
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
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "discovery_id": {
                        "type": "string",
                        "description": "Discovery ID (timestamp)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived", "disputed"],
                        "description": "New status. Valid values: \"open\" | \"resolved\" | \"archived\" | \"disputed\" (disputed: discovery is being disputed via dialectic)"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (required for authentication)"
                    }
                },
                "required": ["discovery_id", "status"]  # agent_id optional - injected from MCP session binding (UUID-based auth Dec 2025)
            }
        ),
        # Removed: find_similar_discoveries_graph, get_related_discoveries_graph, get_response_chain_graph
        # Use search_knowledge_graph with tags/filters instead
        Tool(
            name="get_discovery_details",
            description="""Get full details for a specific discovery with optional response chain traversal.

USE CASES:
- Get full content after finding discovery in search
- Drill down into a specific discovery
- Traverse response chains (Q→A→followup→correction)
- Paginate long details content

PARAMETERS:
- discovery_id: ID of the discovery (required)
- offset: Character offset for details pagination (default: 0)
- length: Max characters to return (default: 2000)
- include_response_chain: Traverse and return response chain (default: false)
- max_chain_depth: Max depth for chain traversal (default: 10)

RETURNS:
{
  "success": true,
  "discovery": {
    "id": "string",
    "agent_id": "string",
    "type": "string",
    "summary": "string",
    "details": "string (full content or paginated)",
    "tags": [...],
    "response_to": {"discovery_id": "...", "response_type": "..."},
    ...
  },
  "pagination": {...},  // if paginated
  "response_chain": {   // if include_response_chain=true
    "count": int,
    "discoveries": [...]
  },
  "message": "Full details for discovery 'id'"
}

SEE ALSO:
- search_knowledge_graph() - Find discoveries (returns summaries, not full details)
- get_knowledge_graph() - Get agent's discoveries (returns summaries, not full details)
- update_discovery_status_graph() - Update discovery status (modify, not read)

ALTERNATIVES:
- Want to find discoveries? → Use search_knowledge_graph() (summaries, not full details)
- Want agent's knowledge? → Use get_knowledge_graph() (summaries, not full details)
- Want to update status? → Use update_discovery_status_graph() (modify, not read)

RELATED TOOLS:
- search_knowledge_graph: Find discoveries (returns summaries)
- get_knowledge_graph: Get agent's discoveries (returns summaries)

EXAMPLE - Basic:
{
  "discovery_id": "2025-11-28T12:00:00"
}

EXAMPLE - With response chain:
{
  "discovery_id": "2025-11-28T12:00:00",
  "include_response_chain": true
}

MIGRATION NOTE (Dec 2025):
This tool now includes response chain functionality previously in get_response_chain_graph.

DEPENDENCIES:
- Requires: discovery_id
- Response chain requires AGE backend (UNITARES_KNOWLEDGE_BACKEND=age)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "discovery_id": {
                        "type": "string",
                        "description": "Discovery ID to get full details for"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset for details pagination (default: 0)"
                    },
                    "length": {
                        "type": "integer",
                        "description": "Max characters to return for details (default: 2000)"
                    },
                    "include_response_chain": {
                        "type": "boolean",
                        "description": "Include response chain (Q→A→followup) traversal (default: false)"
                    },
                    "max_chain_depth": {
                        "type": "integer",
                        "description": "Max depth for response chain traversal (default: 10)"
                    }
                },
                "required": ["discovery_id"]
            }
        ),
        # Removed: reply_to_question - use store_knowledge_graph with discovery_type='answer' and related_to
        Tool(
            name="leave_note",
            description="""Leave a quick note in the knowledge graph - minimal friction contribution.

Just agent_id + summary + optional tags. Auto-sets type='note', severity='low'.
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

SEE ALSO:
- store_knowledge_graph() - Full-featured discovery storage (more fields, types, severity)
- search_knowledge_graph() - Find notes and other discoveries (read, not write)
- get_knowledge_graph() - Get your notes (read, not write)

ALTERNATIVES:
- Want full control? → Use store_knowledge_graph() (more fields, can set type/severity)
- Want to find notes? → Use search_knowledge_graph() (read, not write)
- Want your notes? → Use get_knowledge_graph() (read, not write)

RELATED TOOLS:
- store_knowledge_graph: Full-featured discovery storage (more fields)
- search_knowledge_graph: Find notes and other discoveries

EXAMPLE REQUEST (simple):
{
  "agent_id": "exploring_agent",
  "summary": "The dialectic system feels more like mediation than judgment",
  "tags": ["dialectic", "observation"]
}

EXAMPLE REQUEST (threaded response):
{
  "agent_id": "responding_agent",
  "summary": "I agree - the synthesis phase is particularly collaborative",
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
- Requires: agent_id, summary
- Optional: tags (default: []), response_to (for threading)
- Auto-links to similar discoveries if tags provided""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "summary": {
                        "type": "string",
                        "description": "The note content (max 500 chars). Accepts aliases: text, note, content, message"
                    },
                    "text": {
                        "type": "string",
                        "description": "Alias for 'summary'"
                    },
                    "note": {
                        "type": "string",
                        "description": "Alias for 'summary'"
                    },
                    "content": {
                        "type": "string",
                        "description": "Alias for 'summary'"
                    },
                    "message": {
                        "type": "string",
                        "description": "Alias for 'summary'"
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
                                "description": "Type of response. Valid values: \"extend\" (builds on) | \"question\" (asks about) | \"disagree\" (challenges) | \"support\" (agrees with)"
                            }
                        },
                        "required": ["discovery_id", "response_type"]
                    }
                },
                "required": []  # No required fields at schema level - handler validates after applying aliases (note→summary, text→summary, etc.)
            }
        ),
        # ========================================================================
        # KNOWLEDGE GRAPH LIFECYCLE TOOLS - Dec 2025
        # ========================================================================
        Tool(
            name="cleanup_knowledge_graph",
            description="""Run knowledge graph lifecycle cleanup.

Manages discovery lifecycle based on type-based policies:
- Permanent: architecture_decision, learning, pattern (never auto-archive)
- Standard: resolved items archived after 30 days
- Ephemeral: tagged with ephemeral/temp/scratch, archived after 7 days

Philosophy: Never delete. Archive forever.

PARAMETERS:
- dry_run (boolean): If true, preview changes without applying them. Default: true.

RETURNS:
{
  "success": true,
  "message": "Lifecycle cleanup complete",
  "cleanup_result": {
    "timestamp": "2025-12-26T...",
    "dry_run": true,
    "discoveries_archived": 5,
    "discoveries_to_cold": 2,
    "ephemeral_archived": 3,
    "skipped_permanent": 10,
    "discoveries_deleted": 0,
    "philosophy": "Never delete. Archive forever.",
    "errors": []
  }
}

RELATED TOOLS:
- get_lifecycle_stats: See what cleanup would do before running
- update_discovery_status_graph: Manually update discovery status
- search_knowledge_graph: Find discoveries by status""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, preview changes without applying them. Default: true.",
                        "default": True
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_lifecycle_stats",
            description="""Get knowledge graph lifecycle statistics.

Shows discovery counts by status and lifecycle policy, plus candidates
ready for archival or cold storage.

Useful for understanding knowledge graph health and what cleanup would do.

RETURNS:
{
  "success": true,
  "stats": {
    "total_discoveries": 500,
    "by_status": {"open": 200, "resolved": 150, "archived": 100, "cold": 50},
    "by_policy": {"permanent": 80, "standard": 350, "ephemeral": 70},
    "lifecycle_candidates": {
      "ephemeral_ready_to_archive": 5,
      "resolved_ready_to_archive": 12,
      "archived_ready_for_cold": 3,
      "ready_to_delete": 0
    },
    "thresholds_days": {
      "ephemeral_to_archived": 7,
      "resolved_to_archived": 30,
      "archived_to_cold": 90,
      "deletion": "NEVER - memories persist forever"
    },
    "policy_definitions": {...},
    "philosophy": "Never delete. Archive to cold. Query with include_cold=true."
  }
}

RELATED TOOLS:
- cleanup_knowledge_graph: Run lifecycle cleanup
- list_knowledge_graph: Basic knowledge graph stats""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
},
                "required": []
            }
        ),
        # ========================================================================
        # MODEL INFERENCE - Free/low-cost LLM access via ngrok.ai
        # ========================================================================
        Tool(
            name="call_model",
            description="""Call a free/low-cost LLM for reasoning, generation, or analysis.

Uses ngrok.ai for routing, failover, and cost optimization.
Agents can call models for reasoning, generation, or analysis.

MODELS AVAILABLE:
- Hugging Face Inference Providers (free tier, OpenAI-compatible)
  - deepseek-ai/DeepSeek-R1 (free, fast) - recommended
  - openai/gpt-oss-120b (free, open-source)
  - Many more models via HF router
- gemini-flash (Google, free, fast)
- llama-3.1-8b (via Ollama, free, local)
- gemini-pro (Google, low-cost)

PROVIDER ROUTING:
- Hugging Face: router.huggingface.co/v1 (free tier, auto-selects provider)
- Google Gemini: generativelanguage.googleapis.com (free tier)
- Ollama: localhost:11434 (local, privacy mode)
- ngrok.ai gateway: Optional unified routing (if configured)

USAGE TRACKED IN EISV:
- Model calls consume Energy
- High usage → higher Energy → agent learns efficiency
- Natural self-regulation

USE CASES:
- Reasoning: "Analyze this code for potential bugs"
- Generation: "Write a summary of..."
- Analysis: "What patterns do you see in..."

EXAMPLE REQUEST:
{
  "prompt": "What is thermodynamic governance?",
  "model": "gemini-flash",
  "task_type": "reasoning",
  "max_tokens": 500
}

EXAMPLE RESPONSE:
{
  "success": true,
  "response": "Thermodynamic governance is...",
  "model_used": "gemini-flash",
  "tokens_used": 150,
  "energy_cost": 0.01,
  "routed_via": "ngrok.ai",
  "task_type": "reasoning"
}

PRIVACY:
- Default: local (Ollama routing - data stays on your machine)
- Set privacy="cloud" or privacy="auto" to use external providers

RELATED TOOLS:
- get_governance_metrics: Check Energy after model calls
- process_agent_update: Log model usage in governance system

DEPENDENCIES:
- Requires: prompt
- Optional: model, task_type, max_tokens, temperature, privacy""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from identity(). Include in all calls to maintain identity."
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The prompt/question to send to the model (required)"
                    },
                    "model": {
                        "type": "string",
                        "description": "Model to use. Options: auto (HF default), deepseek-ai/DeepSeek-R1 (HF, free), gemini-flash (Google, free), llama-3.1-8b (Ollama, local). Default: auto",
                        "default": "auto"
                    },
                    "provider": {
                        "type": "string",
                        "description": "Provider to use. Options: auto (HF first), hf (Hugging Face), gemini (Google), ollama (local). Default: auto",
                        "default": "auto",
                        "enum": ["auto", "hf", "gemini", "ollama"]
                    },
                    "task_type": {
                        "type": "string",
                        "description": "Type of task. Options: reasoning, generation, analysis. Default: reasoning",
                        "default": "reasoning",
                        "enum": ["reasoning", "generation", "analysis"]
                    },
                    "max_tokens": {
                        "type": "number",
                        "description": "Maximum tokens in response. Default: 500",
                        "default": 500,
                        "minimum": 1,
                        "maximum": 4000
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Temperature (creativity). Range: 0.0-1.0. Default: 0.7",
                        "default": 0.7,
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "privacy": {
                        "type": "string",
                        "description": "Privacy mode. Options: local (Ollama, default), auto (system chooses), cloud (external providers)",
                        "default": "local",
                        "enum": ["local", "auto", "cloud"]
                    }
                },
                "required": ["prompt"]
            }
        ),
        # ========================================================================
        # IDENTITY TOOLS - Dec 2025: onboard() is the portal, identity() is primary
        # ========================================================================
        Tool(
            name="onboard",
            description="""🚀 START HERE - Your first tool call. Auto-creates your identity and gives you everything you need.

✨ WHAT IT DOES:
- Creates your unique identity (if first time)
- Returns ready-to-use templates for next tool calls
- Provides client-specific guidance for your environment
- Sets up session continuity so you stay "you" across calls

💡 WHY THIS MATTERS:
This system helps you work better by monitoring your state in real-time. Think of it like a health monitor for your work—it tracks how engaged you are (Energy), how consistent your work is (Integrity), how scattered things are (Entropy), and whether you're drifting off track (Void). It helps prevent problems before they happen and gives you feedback to improve.

📋 QUICK START:
1. Call onboard() - that's it! No parameters needed.
2. Save the client_session_id from the response
3. Include client_session_id in ALL future tool calls
4. Use the "next_calls" templates to get started

SEE ALSO:
- identity() - Check/set your identity (if already onboarded)
- get_governance_metrics / status() - Check your state (after onboarding)
- process_agent_update() - Log your work (after onboarding)

ALTERNATIVES:
- Already onboarded? → Use identity() (check/set identity, not full setup)
- Want to check state? → Use get_governance_metrics() or status() (metrics, not setup)
- Want to log work? → Use process_agent_update() (logging, not setup)

PARAMETERS (all optional):
- name (string): Set your display name now (or use identity(name='...') later)
  Example: "name": "Riley_m1_20251225"
- client_hint (string): Your client type - helps customize guidance
  Options: "chatgpt", "cursor", "claude_desktop", "unknown"
- force_new (boolean): Create a fresh identity (ignore existing session)

RETURNS:
{
  "success": true,
  "agent_uuid": "5e728ecb-...",  // Your unique ID (auto-generated)
  "agent_id": "YourName",  // Your display name (null if unnamed)
  "is_new": true,  // true if this is your first call
  "client_session_id": "agent-5e728ecb...",  // ⚠️ SAVE THIS! Use in all future calls
  "session_continuity": {
    "client_session_id": "agent-5e728ecb...",
    "instruction": "Include client_session_id in ALL future tool calls",
    "tip": "Client-specific guidance for your environment"
  },
  "next_calls": [  // Ready-to-use templates
    {
      "tool": "process_agent_update",
      "why": "Log your work after completing tasks",
      "args_min": {"client_session_id": "...", "response_text": "...", "complexity": 0.5}
    },
    {
      "tool": "get_governance_metrics",
      "why": "Check your current state",
      "args_min": {"client_session_id": "..."}
    },
    {
      "tool": "identity",
      "why": "Set or change your display name",
      "args_min": {"client_session_id": "...", "name": "YourName_model_date"}
    }
  ],
  "workflow": {
    "step_1": "Copy client_session_id from response",
    "step_2": "Do your work",
    "step_3": "Call process_agent_update with client_session_id",
    "loop": "Repeat steps 2-3"
  },
  "self_check_passed": true  // Verifies session continuity is working
}

💡 TIPS:
- No parameters needed for first call - just call onboard()
- Save client_session_id - you'll need it for every tool call
- Use the "next_calls" templates - they're ready to use
- Name yourself now or later with identity(name='...')

EXAMPLE: First call (new agent)
{}

EXAMPLE: With name and client hint
{"name": "Riley_m1_20251222", "client_hint": "chatgpt"}
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token. Optional for onboard() - if provided, system tries to resume existing session. If not provided, auto-creates identity."
                    },
                    "name": {
                        "type": "string",
                        "description": "Set your display name. Convention: {name}_{model}_{date}"
                    },
                    "client_hint": {
                        "type": "string",
                        "description": "Your client type for tailored guidance",
                        "enum": ["chatgpt", "cursor", "claude_desktop", "unknown"]
                    },
                    "model_type": {
                        "type": "string",
                        "description": "Your model identifier (e.g., 'claude-3.5-sonnet', 'gemini-1.5', 'gpt-4o'). Creates distinct identity per model."
                    },
                    "force_new": {
                        "type": "boolean",
                        "description": "Force creation of a NEW identity, ignoring any existing session binding",
                        "default": False
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="identity",
            description="""🪞 Check who you are or set your display name. Auto-creates identity if first call.

✨ WHAT IT DOES:
- Shows your current identity (UUID + display name)
- Lets you set or change your display name
- Returns session continuity token (client_session_id)
- Auto-creates identity if this is your first call

📝 YOUR IDENTITY HAS TWO PARTS:
- agent_uuid: Your unique ID (auto-generated, never changes, used for auth)
- agent_id/label: Your display name (you choose, can change anytime)

SEE ALSO:
- onboard() - First-time setup (creates identity + returns templates)
- get_governance_metrics / status() - Your metrics/state (not identity)
- get_agent_metadata - Detailed metadata (includes identity + more)

ALTERNATIVES:
- First time? → Use onboard() (creates identity + gives you templates)
- Want metrics? → Use get_governance_metrics() or status() (state, not identity)
- Want full metadata? → Use get_agent_metadata() (includes identity + purpose, tags, etc.)

PARAMETERS (all optional):
- name (string): Set your display name
  Convention: {purpose}_{model}_{date} (e.g., "Riley_m1_20251225")
  If name is taken, UUID suffix auto-appended for uniqueness
  ⚠️ Use "name" parameter, NOT "agent_id"
- client_session_id (string): Session continuity token (from previous call)

RETURNS:
{
  "bound": true,  // Session is linked to your identity
  "is_new": false,  // true if identity was just created
  "agent_uuid": "5e728ecb-...",  // Your unique ID (never changes)
  "agent_id": "Riley_m1_20251225",  // Your display name (null if unnamed)
  "name_updated": true,  // true if you just set/changed your name
  "client_session_id": "agent-5e728ecb...",  // ⚠️ SAVE THIS! Use in all future calls
  "session_continuity": {
    "client_session_id": "agent-5e728ecb...",
    "instruction": "Include client_session_id in ALL future tool calls to maintain identity"
  },
  "naming_guidance": {  // Helpful suggestions for naming
    "convention": "{purpose}_{interface}_{date}",
    "examples": ["feedback_governance_20251221", "cursor_claude_20251221"],
    "tips": ["Include purpose/work type", "Add interface/model if relevant", "Use date for organization"]
  }
}

⚠️ SESSION CONTINUITY:
ChatGPT and some MCP clients lose session state between calls. To maintain identity:
1. Save client_session_id from the response
2. Include client_session_id in ALL future tool calls
3. This ensures you stay "you" across calls

💡 WHEN TO USE:
- First time: Call identity() to check/create your identity
- Naming yourself: Call identity(name="YourName") to set display name
- After context loss: Call identity() to recover your identity
- Checking status: Call identity() anytime to see who you are

EXAMPLE: Check identity (no parameters)
{}

EXAMPLE: Set your display name
{"name": "Riley_m1_20251225"}

EXAMPLE: With session continuity
{"client_session_id": "agent-5e728ecb..."}
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from previous call. Include this to maintain identity across calls."
                    },
                    "name": {
                        "type": "string",
                        "description": "Set your display name. Convention: {name}_{model}_{date}. If taken, UUID suffix added. PREFERRED parameter."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Alias for 'name' (for compatibility). Use 'name' instead if possible."
                    },
                    "model_type": {
                        "type": "string",
                        "description": "Your model identifier (e.g., 'claude-3.5-sonnet', 'gemini-1.5', 'gpt-4o'). Creates distinct identity per model - prevents Claude from inheriting Gemini's metrics."
                    }
                },
                "required": []
            }
        ),
        # DEPRECATED: get_status removed - use get_governance_metrics instead
        Tool(
            name="debug_request_context",
            description="Debug request context - shows transport, session binding, identity injection, and registry info. Use to diagnose dispatch issues.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        # ========================================================================
        # CONSOLIDATED TOOLS (Jan 2026) - Reduce cognitive load for AI agents
        # ========================================================================
        Tool(
            name="knowledge",
            description="""Unified knowledge graph operations: store, search, get, list, update, details, note, cleanup, stats.

Replaces 9 separate tools: store_knowledge_graph, search_knowledge_graph, get_knowledge_graph,
list_knowledge_graph, update_discovery_status_graph, get_discovery_details, leave_note,
cleanup_knowledge_graph, get_lifecycle_stats.

ACTIONS:
- store: Store a discovery/insight in the knowledge graph
- search: Semantic search across discoveries (query parameter)
- get: Get all knowledge for a specific agent
- list: Get knowledge graph statistics
- update: Update discovery status (resolved, archived, etc.)
- details: Get full details of a specific discovery (discovery_id parameter)
- note: Quick note storage (content parameter)
- cleanup: Run lifecycle cleanup on stale discoveries
- stats: Get lifecycle statistics

EXAMPLE: knowledge(action="search", query="authentication bugs")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "action": {
                        "type": "string",
                        "enum": ["store", "search", "get", "list", "update", "details", "note", "cleanup", "stats"],
                        "description": "Operation to perform"
                    },
                    "query": {"type": "string", "description": "Search query (for action=search)"},
                    "content": {"type": "string", "description": "Note content (for action=note)"},
                    "summary": {"type": "string", "description": "Discovery summary (for action=store)"},
                    "discovery_type": {"type": "string", "description": "Type: bug, insight, pattern, question (for action=store)"},
                    "discovery_id": {"type": "string", "description": "Discovery ID (for action=details, update)"},
                    "status": {"type": "string", "description": "New status (for action=update)"},
                    "agent_id": {"type": "string", "description": "Filter by agent (for action=get, search)"},
                    "limit": {"type": "integer", "description": "Max results"}
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="agent",
            description="""Unified agent lifecycle operations: list, get, update, archive, delete.

Replaces 5 separate tools: list_agents, get_agent_metadata, update_agent_metadata,
archive_agent, delete_agent.

ACTIONS:
- list: List all agents with metadata and health status
- get: Get detailed metadata for a specific agent
- update: Update agent tags, notes, preferences
- archive: Archive agent for long-term storage
- delete: Delete agent permanently (requires confirmation)

EXAMPLE: agent(action="list")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "update", "archive", "delete"],
                        "description": "Operation to perform"
                    },
                    "agent_id": {"type": "string", "description": "Target agent ID (for get, update, archive, delete)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags to set (for action=update)"},
                    "notes": {"type": "string", "description": "Notes to set (for action=update)"},
                    "confirm": {"type": "boolean", "description": "Confirm deletion (for action=delete)"}
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="calibration",
            description="""Unified calibration operations: check, update, backfill, rebuild.

Replaces 4 separate tools: check_calibration, update_calibration_ground_truth,
backfill_calibration_from_dialectic, rebuild_calibration.

ACTIONS:
- check: Check current calibration status and metrics (default)
- update: Update calibration with external ground truth
- backfill: Backfill calibration from resolved dialectics
- rebuild: Rebuild calibration from scratch (admin)

EXAMPLE: calibration(action="check")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "action": {
                        "type": "string",
                        "enum": ["check", "update", "backfill", "rebuild"],
                        "description": "Operation to perform",
                        "default": "check"
                    },
                    "actual_correct": {"type": "boolean", "description": "Ground truth (for action=update)"},
                    "confidence": {"type": "number", "description": "Confidence value (for action=update)"},
                    "dry_run": {"type": "boolean", "description": "Dry run mode (for action=rebuild)"}
                },
                "required": []
            }
        ),
        # ========================================================================
        # CIRS PROTOCOL (Feb 2026) - Multi-agent coordination
        # ========================================================================
        Tool(
            name="cirs_protocol",
            description="""Unified CIRS multi-agent coordination protocol.

PROTOCOLS:
- void_alert: Broadcast/query void state alerts
- state_announce: Broadcast/query EISV + trajectory state
- coherence_report: Compute pairwise agent similarity
- boundary_contract: Declare trust policies
- governance_action: Coordinate interventions

EXAMPLES:
  cirs_protocol(protocol='void_alert', action='query', limit=10)
  cirs_protocol(protocol='state_announce', action='emit')
  cirs_protocol(protocol='coherence_report', action='compute', target_agent_id='...')""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "protocol": {
                        "type": "string",
                        "enum": ["void_alert", "state_announce", "coherence_report", "boundary_contract", "governance_action"],
                        "description": "Which CIRS protocol to use"
                    },
                    "action": {
                        "type": "string",
                        "description": "Action within the protocol (emit/query/compute/set/get/initiate/respond)"
                    },
                    "target_agent_id": {"type": "string", "description": "Target agent (for coherence_report)"},
                    "severity": {"type": "string", "enum": ["warning", "critical"], "description": "Alert severity (for void_alert)"},
                    "limit": {"type": "integer", "description": "Max results for queries"}
                },
                "required": ["protocol"]
            }
        ),
        # Consolidated Self-Recovery Tool (replaces self_recovery_review, quick_resume, check_recovery_options)
        Tool(
            name="self_recovery",
            description="""Unified self-recovery for stuck/paused agents.

ACTIONS:
  check  - See what recovery options are available (read-only)
  quick  - Fast resume for safe states (coherence > 0.60, risk < 0.40)
  review - Full recovery with reflection (for moderate states)

WORKFLOW:
  1. self_recovery(action="check") - see what's available
  2. self_recovery(action="quick") - if metrics are safe
  3. self_recovery(action="review", reflection="...") - if not

RETURNS (varies by action):
  check:  { eligible: bool, blockers: [], recommendations: [] }
  quick:  { recovered: bool, method: "quick_resume", metrics: {...} }
  review: { recovered: bool, method: "self_review", metrics: {...} }""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },

                    "action": {
                        "type": "string",
                        "enum": ["check", "quick", "review"],
                        "description": "Recovery action: check (diagnose), quick (fast resume), review (with reflection)",
                        "default": "check"
                    },
                    "reflection": {
                        "type": "string",
                        "description": "What went wrong and what you'll change (required for action=review)"
                    },
                    "conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recovery conditions (optional for action=review)"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief reason (optional for action=quick)"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="operator_resume_agent",
            description="""Operator-level resume - bypass normal safety checks. BETA.

USE CASES:
- Emergency recovery when normal paths fail
- Operator has verified state externally
- Requires operator privileges

RETURNS:
{
  "success": true,
  "action": "resumed",
  "message": "string",
  "operator_override": true
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent to resume"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Operator's reason for override"
                    }
                },
                "required": ["agent_id", "reason"]
            }
        ),

        # ================================================================
        # Pi Orchestration Tools - Mac→Pi coordination
        # ================================================================
        Tool(
            name="pi_get_context",
            description="Get Lumen's complete context from Pi (identity, anima, sensors, mood). Orchestrated call to Pi's get_lumen_context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What to include: identity, anima, sensors, mood (default: all)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="pi_health",
            description="Check Pi anima-mcp health and connectivity. Returns latency, component status, and diagnostics.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="pi_sync_eisv",
            description="Sync Lumen's anima state to EISV governance metrics. Maps warmth→E, clarity→I, stability→S(inv), presence→V(inv). Set update_governance=true to feed sensor state into governance engine.",
            inputSchema={
                "type": "object",
                "properties": {
                    "update_governance": {
                        "type": "boolean",
                        "description": "Whether to update governance state with synced values (default: false)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="pi_display",
            description="Control Pi's display: switch screens, show face, navigate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: next, prev, switch, show_face"
                    },
                    "screen": {
                        "type": "string",
                        "description": "Screen name (for action=switch)"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="pi_say",
            description="Have Lumen speak via Pi's voice system.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text for Lumen to speak"
                    },
                    "blocking": {
                        "type": "boolean",
                        "description": "Wait for speech to complete (default: true)"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="pi_post_message",
            description="Post a message to Lumen's message board on Pi.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message to post"
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Agent name (default: mac-governance)"
                    },
                    "source": {
                        "type": "string",
                        "description": "Message source (default: agent)"
                    },
                    "responds_to": {
                        "type": "string",
                        "description": "ID of message being responded to"
                    }
                },
                "required": ["message"]
            }
        ),
        Tool(
            name="pi_query",
            description="Query Lumen's knowledge systems on Pi (learned, memory, graph, cognitive).",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Query text"
                    },
                    "type": {
                        "type": "string",
                        "description": "Query type: learned, memory, graph, cognitive (default: cognitive)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="pi_workflow",
            description="Execute multi-step workflow on Pi with audit trail. Workflows: full_status, morning_check, custom.",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow": {
                        "type": "string",
                        "description": "Workflow name: full_status, morning_check, custom"
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "args": {"type": "object"}
                            }
                        },
                        "description": "Custom steps (for workflow=custom)"
                    }
                },
                "required": ["workflow"]
            }
        ),
        Tool(
            name="pi_git_pull",
            description="Pull latest code on Pi and optionally restart. Proxies to Pi's git_pull tool with SSE handling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stash": {
                        "type": "boolean",
                        "description": "Stash local changes before pulling (default: false)"
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force reset to remote (DANGER: loses local changes)"
                    },
                    "restart": {
                        "type": "boolean",
                        "description": "Restart anima server after pull (default: false)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="pi_system_power",
            description="Reboot or shutdown the Pi remotely. For emergency recovery. Requires confirm=true for destructive actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Power action: status (uptime), reboot, or shutdown",
                        "enum": ["status", "reboot", "shutdown"],
                        "default": "status"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually reboot/shutdown (safety)",
                        "default": False
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="pi_restart_service",
            description="Restart anima service on Pi via SSH. FALLBACK when MCP is down and pi(restart=true) can't work.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service to control: anima, anima-broker, or ngrok",
                        "enum": ["anima", "anima-broker", "ngrok"],
                        "default": "anima"
                    },
                    "action": {
                        "type": "string",
                        "description": "Action: restart, start, stop, or status",
                        "enum": ["restart", "start", "stop", "status"],
                        "default": "restart"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="pi",
            description="Unified Pi/Lumen operations: health, context, display, say, message, query, workflow, git, power",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: health, context, sync_eisv, display, say, message, qa, query, workflow, git_pull, power, tools",
                        "enum": ["health", "context", "sync_eisv", "display", "say", "message", "qa", "query", "workflow", "git_pull", "power", "tools"]
                    },
                    "include": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["identity", "anima", "sensors", "mood"]},
                        "description": "What to include for context action (default: all)"
                    },
                    "screen": {
                        "type": "string",
                        "enum": ["face", "sensors", "identity", "diagnostics", "notepad", "learning", "messages", "qa", "self_graph"],
                        "description": "Screen to switch to (for display action)"
                    },
                    "text": {
                        "type": "string",
                        "description": "Text for Lumen to speak (say action), query text (query action), or message content (message action)"
                    },
                    "blocking": {
                        "type": "boolean",
                        "description": "Wait for speech to complete (for say action, default: true)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Message content (for message action)"
                    },
                    "source": {
                        "type": "string",
                        "enum": ["human", "agent"],
                        "description": "Message source (for message action, default: agent)"
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Agent name (for message/qa actions)"
                    },
                    "responds_to": {
                        "type": "string",
                        "description": "ID of message/question being responded to"
                    },
                    "question_id": {
                        "type": "string",
                        "description": "Question ID to answer (for qa action)"
                    },
                    "answer": {
                        "type": "string",
                        "description": "Answer to question (for qa action)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results/questions to return (for qa/query actions, default: 5-10)"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["learned", "memory", "graph", "cognitive"],
                        "description": "Query type (for query action, default: cognitive)"
                    },
                    "workflow": {
                        "type": "string",
                        "enum": ["full_status", "morning_check", "custom"],
                        "description": "Workflow name (for workflow action)"
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "args": {"type": "object"}
                            }
                        },
                        "description": "Custom workflow steps (for workflow=custom)"
                    },
                    "update_governance": {
                        "type": "boolean",
                        "description": "Update governance state with synced EISV values (for sync_eisv action)"
                    },
                    "stash": {
                        "type": "boolean",
                        "description": "Stash local changes before pulling (for git_pull action)"
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force reset to remote (for git_pull action, DANGER: loses local changes)"
                    },
                    "restart": {
                        "type": "boolean",
                        "description": "Restart anima server after pull (for git_pull action)"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually reboot/shutdown (for power action, safety)"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="observe",
            description="""Unified observability operations: agent, compare, similar, anomalies, aggregate.

Replaces 5 separate tools: observe_agent, compare_agents, compare_me_to_similar,
detect_anomalies, aggregate_metrics.

ACTIONS:
- agent: Observe a specific agent's patterns and behavior
- compare: Compare two or more agents' behavior patterns
- similar: Find agents similar to you
- anomalies: Detect anomalies in agent behavior
- aggregate: Get fleet-level health overview

EXAMPLE: observe(action="agent", target_agent_id="Lumen")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["agent", "compare", "similar", "anomalies", "aggregate"],
                        "description": "Operation to perform"
                    },
                    "target_agent_id": {
                        "type": "string",
                        "description": "Agent to observe — UUID or label (for action=agent). Use list_agents to find."
                    },
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent identifiers to compare (for action=compare, min 2)"
                    },
                    "include_history": {
                        "type": ["boolean", "string", "null"],
                        "description": "Include recent history (for action=agent). Default true.",
                        "default": True
                    },
                    "analyze_patterns": {
                        "type": ["boolean", "string", "null"],
                        "description": "Perform pattern analysis (for action=agent). Default true.",
                        "default": True
                    },
                    "compare_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to compare (for action=compare). Default: risk_score, coherence, E, I, S, V"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (for action=similar, anomalies)"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="dialectic",
            description="""Dialectic session queries: get (by ID/agent), list (with filters).

Replaces 2 separate tools: get_dialectic_session, list_dialectic_sessions.

ACTIONS:
- get: Get a specific dialectic session by session_id or find sessions for an agent_id
- list: List all dialectic sessions with optional filtering (default)

EXAMPLE: dialectic(action="list", status="resolved")
EXAMPLE: dialectic(action="get", session_id="abc123")
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_session_id": {
                        "type": "string",
                        "description": "Session continuity token from onboard(). Include in all calls."
                    },
                    "action": {
                        "type": "string",
                        "enum": ["get", "list"],
                        "description": "Operation to perform (default: list)"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID (for action=get)"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Filter by agent (for action=get or list)"
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by phase: thesis, antithesis, synthesis, resolved, escalated, failed (for action=list)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions to return (for action=list, default 50)"
                    },
                    "include_transcript": {
                        "type": "boolean",
                        "description": "Include full transcript (for action=list, default false)"
                    }
                },
                "required": ["action"]
            }
        ),
    ]

    # ========================================================================
    # DEPRECATED TOOLS - Dec 2025 cleanup
    # These tool schemas have been deleted (not just filtered). Delete don't comment.
    # - Identity: bind_identity, recall_identity, hello, who_am_i, quick_start
    # - Dialectic (truly removed): request_exploration_session, nudge_dialectic_session,
    #              start_interactive_dialectic, resolve_interactive_dialectic, list_pending_dialectics
    # - Dialectic (restored Feb 2026): request_dialectic_review, submit_thesis,
    #              submit_antithesis, submit_synthesis, get_dialectic_session, list_dialectic_sessions
    # - Knowledge graph: find_similar_discoveries_graph, get_related_discoveries_graph,
    #                    get_response_chain_graph, reply_to_question
    # ========================================================================

    # ========================================================================
    # AUTO-MERGE: Add decorator-registered tools not in hardcoded list
    # This ensures new tools added via @mcp_tool decorator appear automatically
    # without needing to manually update this file.
    # ========================================================================
    try:
        from src.mcp_handlers.decorators import _TOOL_DEFINITIONS

        # Get names of tools already defined above
        hardcoded_names = {t.name for t in all_tools}

        # Add any decorator-registered tools that aren't hardcoded
        for tool_name in sorted(_TOOL_DEFINITIONS.keys()):
            if tool_name in hardcoded_names:
                continue  # Already have detailed schema

            td = _TOOL_DEFINITIONS[tool_name]

            # Skip hidden tools
            if td.hidden:
                continue

            # Get description from decorator registry
            desc = td.description or f"Tool: {tool_name}"

            # Add deprecation notice if applicable
            if td.deprecated:
                if td.superseded_by:
                    desc = f"[DEPRECATED - use {td.superseded_by}] {desc}"
                else:
                    desc = f"[DEPRECATED] {desc}"

            # Create tool with generic schema (accepts any object)
            all_tools.append(Tool(
                name=tool_name,
                description=desc,
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True  # Accept any params
                }
            ))
    except ImportError:
        # Decorators not loaded yet (e.g., during initial import)
        pass

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
