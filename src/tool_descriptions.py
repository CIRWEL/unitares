"""
Tool descriptions for MCP tool definitions.

Extracted from tool_schemas.py to keep the schema generator compact.
"""


TOOL_DESCRIPTIONS = {
    "check_calibration": """Check calibration of confidence estimates.

IMPORTANT (AI-for-AI truth model):
By default, UNITARES does NOT assume access to external correctness (tests passing, user satisfaction, etc.).
This tool therefore reports calibration primarily against a trajectory/consensus proxy ("trajectory_health"),
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

    "update_calibration_ground_truth": """Optional: Update calibration with external ground truth after human review.

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

    "backfill_calibration_from_dialectic": """Retroactively update calibration from historical resolved verification-type dialectic sessions.

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

    "rebuild_calibration": """Rebuild calibration from scratch using auto ground truth collection.

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

    "health_check": """Quick health check - returns system status, version, and component health. Useful for monitoring and operational visibility.

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
  "version": "2.8.0",
  "components": {
    "calibration": {"status": "healthy", "pending_updates": 5},
    "telemetry": {"status": "healthy", "metrics_count": 1234},
    "audit_log": {"status": "healthy", "entries": 5678}
  }
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",

    "get_workspace_health": """Get comprehensive workspace health status. Provides accurate baseline of workspace state for onboarding new agents. Saves 30-60 minutes of manual exploration.

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

    "get_telemetry_metrics": """Get comprehensive telemetry metrics: skip rates, confidence distributions, calibration status, and suspicious patterns. Useful for monitoring system health and detecting agreeableness or over-conservatism.

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

    "get_tool_usage_stats": """Get tool usage statistics to identify which tools are actually used vs unused. Helps make data-driven decisions about tool deprecation and maintenance priorities.

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

    "get_server_info": """Get MCP server version, process information, and health status for debugging multi-process issues. Returns version, PID, uptime, and active process count.

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
  "server_version": "2.8.0",
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

    "get_connection_status": """Get MCP connection status and tool availability. Helps agents verify they're connected to the MCP server and can use tools. Especially useful for detecting when tools are not available (e.g., wrong chatbox in Mac ChatGPT).

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
  "resolved_agent_id": "string" | null,  // admin display name (from handler)
  "caller_agent_id": "string" | null,   // calling session's bound UUID (from envelope)
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

    "process_agent_update": """💬 Share your work and get supportive feedback. Your main tool for checking in.

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

    "get_governance_metrics": """Get current governance state and metrics for an agent without updating state.

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

    "get_system_history": """Export complete governance history for an agent. Returns time series data of all governance metrics.

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

    "export_to_file": """Export governance history to a file in the server's data directory. Saves timestamped files for analysis and archival. Returns file path and metadata (lightweight response).

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

    "reset_monitor": """Reset governance state for an agent. Useful for testing or starting fresh.

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

    "list_agents": """List all agents currently being monitored with lifecycle metadata and health status.

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

    "delete_agent": """Delete an agent and archive its data. Protected: cannot delete pioneer agents. Requires explicit confirmation.

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

    "get_agent_metadata": """Get complete metadata for an agent including lifecycle events, current state, and computed fields.

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

    "mark_response_complete": """Mark agent as having completed response, waiting for input. Lightweight status update - no full governance cycle.

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

    "detect_stuck_agents": """Detect stuck agents using proprioceptive margin + activity timeout.

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

    "request_dialectic_review": """Request a dialectic recovery session (lite entry point).

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

    "submit_thesis": """Submit thesis in a dialectic session. Called by paused agent.

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

    "submit_antithesis": """Submit antithesis in a dialectic session. Called by reviewer.

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

    "submit_synthesis": """Submit synthesis proposal in a dialectic session. Either agent can submit.

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

    "archive_agent": """Archive an agent for long-term storage. Agent can be resumed later. Optionally unload from memory.

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

    "update_agent_metadata": """Update agent tags, notes, and preferences. Tags are replaced, notes can be appended or replaced.

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

    "archive_old_test_agents": """Manually archive old test/demo agents that haven't been updated recently. Note: This also runs automatically on server startup with a 1-day threshold. Use this tool to trigger with a custom threshold or on-demand.

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

    "archive_orphan_agents": """Aggressively archive orphan agents to prevent proliferation. Much more aggressive than archive_old_test_agents.

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

    "simulate_update": """Dry-run governance cycle. Returns decision without persisting state. Useful for testing decisions before committing. State is NOT modified.

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

    "get_thresholds": """Get current governance threshold configuration. Returns runtime overrides + defaults. Enables agents to understand decision boundaries.

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

    "set_thresholds": """Set runtime threshold overrides. Enables runtime adaptation without redeploy. Validates values and returns success/errors.

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

    "aggregate_metrics": """Get fleet-level health overview. Aggregates metrics across all agents or a subset. Returns summary statistics for coordination and system management.

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

    "observe_agent": """Observe another agent's governance state with pattern analysis. Optimized for AI agent consumption.

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

    "compare_agents": """Compare governance patterns across multiple agents. Returns similarities, differences, and outliers. Optimized for AI agent consumption.

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

    "compare_me_to_similar": """Compare yourself to similar agents automatically - finds similar agents and compares.

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

    "outcome_event": """Record an outcome event for EISV validation.

Pairs a measurable outcome (drawing completion, test result, task completion)
with the agent's current EISV snapshot. This enables correlation analysis:
do EISV verdicts and phi values predict real outcomes?

VALID OUTCOME TYPES:
- drawing_completed: Lumen finished a drawing (score = satisfaction)
- drawing_abandoned: Drawing was abandoned before completion
- test_passed: A test or validation passed
- test_failed: A test or validation failed
- tool_rejected: A tool call was rejected by governance
- task_completed: Agent completed a significant task
- task_failed: Agent failed to complete a task

PARAMETERS:
- outcome_type (required): One of the valid types above
- outcome_score (optional float 0-1): Quality metric. Inferred from type if omitted.
- is_bad (optional bool): Whether this is a negative outcome. Inferred from type if omitted.
- detail (optional dict): Type-specific metadata (e.g., mark_count, test_name)
- agent_id (optional): Falls back to session-bound agent_id

RETURNS: outcome_id, embedded EISV snapshot at time of outcome""",

    "detect_anomalies": """Detect anomalies across agents. Scans all agents or a subset for unusual patterns (risk spikes, coherence drops, void events). Returns prioritized anomalies with severity levels.

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

    "list_tools": """📚 Discover all available tools. Your guide to what's possible.

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
  "server_version": "2.8.0",
  "tools": [...],
  "categories": {...},
  "total_tools": 44,
  "workflows": {...},
  "relationships": {...}
}

DEPENDENCIES:
- No dependencies - safe to call anytime""",

    "describe_tool": """📖 Get full details for a specific tool. Deep dive into any tool.

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

    "cleanup_stale_locks": """Clean up stale lock files that are no longer held by active processes. Prevents lock accumulation from crashed/killed processes.

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

    "validate_file_path": """Validate file path against project policies (anti-proliferation).

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

    "store_knowledge_graph": """Store knowledge discovery/discoveries in graph - fast, non-blocking, transparent

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

    "search_knowledge_graph": """DEPRECATED: Prefer knowledge(action="search", query="...") instead — same backend, simpler interface.

Search knowledge graph - returns summaries only (use get_discovery_details for full content).

USE CASES:
- Find discoveries by tags
- Search by agent, type, severity
- Query system knowledge
- Learn from past discoveries
- Full-text search (PostgreSQL FTS or AGE)
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

FULL-TEXT EXAMPLE:
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

    "get_knowledge_graph": """Get all knowledge for an agent - returns summaries only (use get_discovery_details for full content).

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

    "list_knowledge_graph": """List knowledge graph statistics - full transparency.

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

    "update_discovery_status_graph": """Update discovery status - fast graph update.

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

    "get_discovery_details": """Get full details for a specific discovery with optional response chain traversal.

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

    "leave_note": """Leave a quick note in the knowledge graph - minimal friction contribution.

Just agent_id + summary + optional tags. Auto-sets type='note', severity='low'.
Notes are ephemeral by default — auto-archived after 7 days unless lasting=true or tags include a permanent signal (e.g. "architecture", "decision").
For lasting knowledge, use store_knowledge_graph instead.

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

    "cleanup_knowledge_graph": """Run knowledge graph lifecycle cleanup.

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

    "get_lifecycle_stats": """Get knowledge graph lifecycle statistics.

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

    "call_model": """Call a free/low-cost LLM for reasoning, generation, or analysis.

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

    "onboard": """🚀 START HERE - Your first tool call. Auto-creates your identity and gives you everything you need.

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

    "identity": """🪞 Check who you are or set your display name. Auto-creates identity if first call.

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

    "debug_request_context": """Debug request context - shows transport, session binding, identity injection, and registry info. Use to diagnose dispatch issues.""",

    "knowledge": """Unified knowledge graph operations: store, search, get, list, update, details, note, cleanup, stats.

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

    "agent": """Unified agent lifecycle operations: list, get, update, archive, delete.

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

    "calibration": """Unified calibration operations: check, update, backfill, rebuild.

Replaces 4 separate tools: check_calibration, update_calibration_ground_truth,
backfill_calibration_from_dialectic, rebuild_calibration.

ACTIONS:
- check: Check current calibration status and metrics (default)
- update: Update calibration with external ground truth
- backfill: Backfill calibration from resolved dialectics
- rebuild: Rebuild calibration from scratch (admin)

EXAMPLE: calibration(action="check")
""",

    "cirs_protocol": """Unified CIRS multi-agent coordination protocol.

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

    "self_recovery": """Unified self-recovery for stuck/paused agents.

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

    "operator_resume_agent": """Operator-level resume - bypass normal safety checks. BETA.

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

    "pi_get_context": """Get Lumen's complete context from Pi (identity, anima, sensors, mood). Orchestrated call to Pi's get_lumen_context.""",

    "pi_health": """Check Pi anima-mcp health and connectivity. Returns latency, component status, and diagnostics.""",

    "pi_sync_eisv": """Sync Lumen's anima state to EISV governance metrics. Maps warmth→E, clarity→I, stability→S(inv), presence→V(inv). Set update_governance=true to feed sensor state into governance engine.""",

    "pi_display": """Control Pi's display: switch screens, show face, navigate.""",

    "pi_say": """Have Lumen speak via Pi's voice system.""",

    "pi_post_message": """Post a message to Lumen's message board on Pi.""",

    "pi_query": """Query Lumen's knowledge systems on Pi (learned, memory, graph, cognitive).""",

    "pi_workflow": """Execute multi-step workflow on Pi with audit trail. Workflows: full_status, morning_check, custom.""",

    "pi_git_pull": """Pull latest code on Pi and optionally restart. Proxies to Pi's git_pull tool with SSE handling.""",

    "pi_system_power": """Reboot or shutdown the Pi remotely. For emergency recovery. Requires confirm=true for destructive actions.""",

    "pi_restart_service": """Restart anima service on Pi via SSH. FALLBACK when MCP is down and pi(restart=true) can't work.""",

    "pi": """Unified Pi/Lumen operations: health, context, display, say, message, query, workflow, git, power""",

    "observe": """Unified observability operations: agent, compare, similar, anomalies, aggregate.

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

    "dialectic": """Dialectic session queries: get (by ID/agent), list (with filters).

Replaces 2 separate tools: get_dialectic_session, list_dialectic_sessions.

ACTIONS:
- get: Get a specific dialectic session by session_id or find sessions for an agent_id
- list: List all dialectic sessions with optional filtering (default)

EXAMPLE: dialectic(action="list", status="resolved")
EXAMPLE: dialectic(action="get", session_id="abc123")
""",

}
