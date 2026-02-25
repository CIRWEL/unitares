"""
Pi Orchestration Handlers

Mac→Pi orchestration tools for coordinating with anima-mcp on Raspberry Pi.
Provides unified interface for:
- Querying Lumen's state (sensors, anima, identity)
- Mapping anima state to EISV governance metrics
- Coordinating cross-device workflows
- Health checks and monitoring

Architecture:
- Mac (unitares-governance) = Brain, planning, governance
- Pi (anima-mcp) = Embodiment, sensors, actuators

Why Orchestration Layer Instead of Direct anima-mcp Calls?

1. **Separation of Concerns:**
   - Governance system (Mac) handles planning, decision-making, audit trails
   - Embodied system (Pi) handles sensors, actuators, real-time state
   - Clear boundary: Mac orchestrates, Pi executes

2. **Audit & Governance:**
   - All cross-device calls are logged via audit_log.py
   - Enables governance oversight of embodied actions
   - Tracks who (agent_id) did what (tool) when (timestamp)

3. **EISV Mapping:**
   - Bridges embodied state (anima: warmth, clarity, stability, presence)
   - To governance metrics (EISV: Energy, Integrity, Entropy, Void)
   - Enables governance system to understand embodied state

4. **Error Handling & Resilience:**
   - Automatic retry with exponential backoff
   - Standardized error format across all tools
   - Network failure handling (LAN → Tailscale fallback)

5. **Unified Interface:**
   - Single `pi` tool with `action` parameter reduces cognitive load
   - Consistent parameter patterns across all operations
   - Easier for AI agents to discover and use

6. **Security & Isolation:**
   - Governance system doesn't need direct access to Pi hardware
   - Can enforce policies, rate limits, access control
   - Pi can operate autonomously even if Mac is unreachable

Transport:
- Uses Streamable HTTP (MCP 1.24.0+) - SSE is deprecated
- Automatic retry with exponential backoff for transient failures
- Standardized error format across all tools

Tool Name Mapping:
The pi_* tools are wrappers that call underlying anima-mcp tools:
- pi_get_context → get_lumen_context
- pi_display → manage_display
- pi_say → say
- pi_post_message → post_message
- pi_query → query
- pi_lumen_qa → lumen_qa
- pi_health → diagnostics
- pi_git_pull → git_pull
- pi_system_power → system_power

Use pi(action='tools') to discover available tools on the Pi.

All calls are audited via audit_log.py cross-device events.
"""

import json
import os
import time
import asyncio
from typing import Dict, Any, Optional, Sequence, List
from mcp.types import TextContent

import httpx

from .decorators import mcp_tool
from .utils import success_response, error_response
from src.audit_log import audit_logger
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Pi MCP endpoint configuration
# DEFINITIVE: anima-mcp runs on port 8766 (see /etc/systemd/system/anima.service on Pi)
# See docs/operations/DEFINITIVE_PORTS.md - DO NOT CHANGE WITHOUT UPDATING ALL REFERENCES
#
# Primary: LAN connection (faster when on same network)
# Fallback: Tailscale connection (works when LAN unreachable)
PI_MCP_URL_LAN = os.environ.get("PI_MCP_URL", "http://192.168.1.165:8766/mcp/")
PI_MCP_URL_TAILSCALE = os.environ.get("PI_MCP_URL_TAILSCALE", "http://unitares-anima.tail76aee6.ts.net:8766/mcp/")
PI_MCP_URLS = [PI_MCP_URL_LAN, PI_MCP_URL_TAILSCALE]  # Try in order
PI_MCP_URL = PI_MCP_URL_LAN  # Default for backwards compat
PI_MCP_TIMEOUT = 30.0  # Default timeout for Pi calls

# Stable session ID for Mac→Pi calls.
# Without this, each call_pi_tool() creates a fresh MCP ClientSession and Pi
# sees each as a new anonymous client, minting a fresh UUID every time (Bug #1).
# This header lets Pi's identity resolution map all Mac orchestration calls to
# a single persistent session (Lumen's known identity: 69a1a4f7).
PI_STABLE_SESSION_ID = "mac-governance-orchestrator"

# Tool name mapping: pi_orchestration tool → anima_mcp tool
# This documents the mapping between pi_* wrapper tools and underlying anima tools
PI_TOOL_MAPPING = {
    "get_lumen_context": "get_lumen_context",  # Direct mapping
    "manage_display": "manage_display",  # Direct mapping
    "say": "say",  # Direct mapping
    "post_message": "post_message",  # Direct mapping
    "query": "query",  # Direct mapping
    "lumen_qa": "lumen_qa",  # Direct mapping
    "diagnostics": "diagnostics",  # Direct mapping
    "git_pull": "git_pull",  # Direct mapping
    "system_power": "system_power",  # Direct mapping
}

# Retry configuration for connection failures
PI_RETRY_MAX_ATTEMPTS = 3
PI_RETRY_BASE_DELAY = 0.5  # Base delay in seconds for exponential backoff


def _extract_error_message(result: Dict[str, Any]) -> Optional[str]:
    """
    Extract error message from standardized error format.
    
    Returns None if no error, otherwise returns the error message string.
    """
    if "error" not in result:
        return None
    return result.get("error", "Unknown error")


def _standardize_error(error: Any) -> Dict[str, Any]:
    """
    Standardize error format across all pi tool calls.
    
    Returns a consistent error dict structure:
    {
        "error": str,  # Error message
        "error_type": str,  # Type of error (connection, timeout, tool_error, etc.)
        "error_details": Optional[dict]  # Additional context
    }
    """
    if isinstance(error, dict):
        # Already a dict - standardize structure
        error_msg = error.get("error", str(error))
        error_type = error.get("error_type", "tool_error")
        return {
            "error": str(error_msg),
            "error_type": error_type,
            "error_details": error.get("error_details")
        }
    elif isinstance(error, Exception):
        # Exception object - classify by type
        error_msg = str(error)
        if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError)):
            error_type = "timeout"
        elif isinstance(error, (httpx.ConnectError, httpx.NetworkError)):
            error_type = "connection"
        else:
            error_type = "unknown"
        
        return {
            "error": error_msg,
            "error_type": error_type,
            "error_details": {"exception_type": type(error).__name__}
        }
    else:
        # String or other - wrap it
        return {
            "error": str(error),
            "error_type": "unknown",
            "error_details": None
        }


async def call_pi_tool(tool_name: str, arguments: Dict[str, Any],
                       agent_id: str = "mac-orchestrator",
                       timeout: float = PI_MCP_TIMEOUT,
                       retry_attempt: int = 0) -> Dict[str, Any]:
    """
    Call a tool on Pi's anima-mcp and return the result.

    Uses Streamable HTTP transport (MCP 1.24.0+) - SSE is deprecated.
    Handles:
    - Streamable HTTP transport to Pi (LAN first, then Tailscale fallback)
    - Proper MCP client session handling
    - Timeout protection (full timeout per URL attempt, not divided)
    - Retry logic with exponential backoff for transient failures
    - Audit logging of cross-device calls
    - Standardized error format

    Args:
        tool_name: Name of the anima-mcp tool to call
        arguments: Tool arguments
        agent_id: Agent making the call (for audit)
        timeout: Request timeout in seconds (applied per URL attempt, not divided)
        retry_attempt: Internal retry counter (for recursive retries)

    Returns:
        Dict with tool result or standardized error format:
        {
            "error": str,  # Error message
            "error_type": str,  # Type of error
            "error_details": Optional[dict]
        }
    """
    start_time = time.time()

    # Log call initiation
    audit_logger.log_cross_device_call(
        agent_id=agent_id,
        source_device="mac",
        target_device="pi",
        tool_name=tool_name,
        arguments={k: v for k, v in arguments.items() if k not in ["api_key", "secret"]},  # Sanitize
        status="initiated"
    )

    # Try each URL (LAN first, then Tailscale)
    last_error = None
    for url_index, pi_url in enumerate(PI_MCP_URLS):
        try:
            # Use MCP client library for proper Streamable HTTP transport
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
            
            # Use full timeout per URL attempt (not divided)
            # This ensures each attempt gets the full timeout budget
            # Include stable session headers so Pi resolves all Mac calls
            # to the same identity instead of minting a new UUID each time
            http_client = httpx.AsyncClient(
                http2=True,
                timeout=timeout,
                headers={
                    "X-Session-ID": PI_STABLE_SESSION_ID,
                    "X-Agent-Name": "mac-governance",
                },
            )
            
            async with streamable_http_client(pi_url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # Call the tool
                    result = await session.call_tool(tool_name, arguments)
                    
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Parse MCP TextContent response
                    parsed_content = []
                    for content in result.content:
                        if hasattr(content, 'text'):
                            text = content.text
                            parsed_content.append(text)
                            try:
                                # Try to parse as JSON
                                data = json.loads(text)
                                if isinstance(data, dict):
                                    # Check if it's an error response
                                    if "error" in data:
                                        # Standardize error format
                                        standardized_error = _standardize_error(data)
                                        audit_logger.log_cross_device_call(
                                            agent_id=agent_id,
                                            source_device="mac",
                                            target_device="pi",
                                            tool_name=tool_name,
                                            arguments=arguments,
                                            status="error",
                                            latency_ms=latency_ms,
                                            error=standardized_error["error"]
                                        )
                                        return standardized_error
                                    
                                    # Success - log and return
                                    audit_logger.log_cross_device_call(
                                        agent_id=agent_id,
                                        source_device="mac",
                                        target_device="pi",
                                        tool_name=tool_name,
                                        arguments=arguments,
                                        status="success",
                                        latency_ms=latency_ms
                                    )
                                    return data
                            except json.JSONDecodeError:
                                # Not JSON, keep as text
                                pass
                    
                    # If we got here, either no content or non-JSON content
                    if parsed_content:
                        # Return as text if not JSON
                        result_dict = {"text": "\n".join(parsed_content)}
                        audit_logger.log_cross_device_call(
                            agent_id=agent_id,
                            source_device="mac",
                            target_device="pi",
                            tool_name=tool_name,
                            arguments=arguments,
                            status="success",
                            latency_ms=latency_ms
                        )
                        return result_dict
                    else:
                        # Empty response
                        standardized_error = _standardize_error("Empty response from Pi MCP")
                        audit_logger.log_cross_device_call(
                            agent_id=agent_id,
                            source_device="mac",
                            target_device="pi",
                            tool_name=tool_name,
                            arguments=arguments,
                            status="error",
                            latency_ms=latency_ms,
                            error=standardized_error["error"]
                        )
                        return standardized_error

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            # Connection/network error - try next URL or retry
            last_error = e
            logger.debug(f"Pi connection failed via {pi_url} (attempt {url_index + 1}/{len(PI_MCP_URLS)}): {e}")
            
            # If this was the last URL and we haven't exhausted retries, retry with backoff
            if url_index == len(PI_MCP_URLS) - 1 and retry_attempt < PI_RETRY_MAX_ATTEMPTS:
                delay = PI_RETRY_BASE_DELAY * (2 ** retry_attempt)
                logger.debug(f"Retrying Pi call after {delay}s (attempt {retry_attempt + 1}/{PI_RETRY_MAX_ATTEMPTS})")
                await asyncio.sleep(delay)
                return await call_pi_tool(tool_name, arguments, agent_id, timeout, retry_attempt + 1)
            
            continue  # Try next URL

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            standardized_error = _standardize_error(e)
            audit_logger.log_cross_device_call(
                agent_id=agent_id,
                source_device="mac",
                target_device="pi",
                tool_name=tool_name,
                arguments=arguments,
                status="error",
                latency_ms=latency_ms,
                error=standardized_error["error"]
            )
            # Continue to next URL instead of returning immediately
            last_error = e
            logger.debug(f"Pi MCP call failed via {pi_url}: {e}")
            continue

    # All URLs failed
    latency_ms = (time.time() - start_time) * 1000
    standardized_error = _standardize_error(last_error or "All connection attempts failed")
    standardized_error["error"] = f"Cannot connect to Pi: {standardized_error['error']}"
    
    audit_logger.log_cross_device_call(
        agent_id=agent_id,
        source_device="mac",
        target_device="pi",
        tool_name=tool_name,
        arguments=arguments,
        status="error",
        latency_ms=latency_ms,
        error=standardized_error["error"]
    )
    return standardized_error


def map_anima_to_eisv(
    anima: Dict[str, float],
    pre_computed_eisv: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Map Anima state (Pi) to EISV governance metrics (Mac).

    If ``pre_computed_eisv`` is supplied (e.g. from Pi's neural-weighted
    ``eisv_mapper``), those values are used directly — they incorporate
    neural band signals that this simple fallback cannot replicate.

    Fallback mapping:
    - Warmth → Energy (E): Engagement/activity level
    - Clarity → Integrity (I): Information coherence
    - Stability → 1-Entropy (S): Low stability = high scatter
    - Presence → (1-Presence)*0.3 → Void (V): Scaled to match Pi

    Args:
        anima: Dict with warmth, clarity, stability, presence (0-1 each)
        pre_computed_eisv: Optional Pi-side EISV dict with E, I, S, V keys

    Returns:
        Dict with E, I, S, V values (0-1 each)
    """
    if pre_computed_eisv and all(k in pre_computed_eisv for k in ("E", "I", "S", "V")):
        return dict(pre_computed_eisv)  # Pi's neural-weighted EISV

    return {
        "E": anima.get("warmth", 0.5),
        "I": anima.get("clarity", 0.5),
        "S": 1.0 - anima.get("stability", 0.5),  # Stability inverts to entropy
        "V": (1.0 - anima.get("presence", 0.5)) * 0.3,  # Match Pi's scaling
    }


# ============================================================
# MCP Tool Handlers
# ============================================================

@mcp_tool("pi_list_tools", timeout=15.0, register=False, description="List available tools on Pi's anima-mcp server. Use pi(action='tools') instead.")
async def handle_pi_list_tools(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    List all available tools on Pi's anima-mcp server.
    
    This is useful for:
    - Discovering what tools are available
    - Checking tool availability before calling
    - Understanding tool capabilities
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    
    try:
        # Use MCP client library to list tools
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        
        # Try each URL (LAN first, then Tailscale)
        last_error = None
        for pi_url in PI_MCP_URLS:
            try:
                http_client = httpx.AsyncClient(
                    http2=True, timeout=15.0,
                    headers={"X-Session-ID": PI_STABLE_SESSION_ID, "X-Agent-Name": "mac-governance"},
                )
                async with streamable_http_client(pi_url, http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        
                        # List tools
                        tools_result = await session.list_tools()
                        
                        tools_list = []
                        for tool in tools_result.tools:
                            tools_list.append({
                                "name": tool.name,
                                "description": getattr(tool, 'description', ''),
                                "inputSchema": getattr(tool, 'inputSchema', {})
                            })
                        
                        return success_response({
                            "device": "pi",
                            "tools": tools_list,
                            "count": len(tools_list),
                            "tool_mapping": {
                                "note": "pi_* tools are wrappers that call anima-mcp tools",
                                "mappings": {
                                    "pi_get_context": "get_lumen_context",
                                    "pi_display": "manage_display",
                                    "pi_say": "say",
                                    "pi_post_message": "post_message",
                                    "pi_query": "query",
                                    "pi_lumen_qa": "lumen_qa",
                                    "pi_health": "diagnostics",
                                    "pi_git_pull": "git_pull",
                                    "pi_system_power": "system_power",
                                }
                            }
                        })
            except Exception as e:
                last_error = e
                logger.debug(f"Failed to list tools via {pi_url}: {e}")
                continue
        
        # All URLs failed
        return error_response(f"Failed to list Pi tools: {last_error or 'All connection attempts failed'}")
    
    except Exception as e:
        return error_response(f"Error listing Pi tools: {e}")


@mcp_tool("pi_get_context", timeout=30.0, register=False, description="Get Lumen's complete context. Use pi(action='context') instead.")
async def handle_pi_get_context(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get Lumen's complete context from Pi via orchestrated call to get_lumen_context."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    include = arguments.get("include", ["identity", "anima", "sensors", "mood"])

    result = await call_pi_tool("get_lumen_context", {"include": include}, agent_id=agent_id)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Failed to get Pi context: {error_msg}")

    return success_response({
        "source": "pi",
        "context": result
    })


@mcp_tool("pi_health", timeout=15.0, register=False, description="Check Pi health. Use pi(action='health') instead.")
async def handle_pi_health(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Check Pi's anima-mcp health and connectivity via orchestrated call."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    start_time = time.time()

    # Call diagnostics tool on Pi
    result = await call_pi_tool("diagnostics", {}, agent_id=agent_id, timeout=10.0)
    latency_ms = (time.time() - start_time) * 1000

    error_msg = _extract_error_message(result)
    if error_msg:
        status = "unreachable" if "connect" in error_msg.lower() else "error"
        audit_logger.log_device_health_check(
            agent_id=agent_id,
            device="pi",
            status=status,
            latency_ms=latency_ms,
            details={"error": error_msg}
        )
        return error_response(f"Pi health check failed: {error_msg}")

    # Parse component status
    components = {}
    if "led" in result:
        components["leds"] = "ok" if result.get("led", {}).get("initialized") else "unavailable"
    if "display" in result:
        components["display"] = "ok" if result.get("display", {}).get("available") else "unavailable"
    if "update_loop" in result:
        loop_info = result.get("update_loop", {})
        # Check if task exists and is not done/cancelled (i.e., actively running)
        loop_running = (
            loop_info.get("running", False) or  # Direct "running" flag if present
            (loop_info.get("task_exists", False) and
             not loop_info.get("task_done", True) and
             not loop_info.get("task_cancelled", True))
        )
        components["update_loop"] = "ok" if loop_running else "stopped"

    status = "healthy" if all(v == "ok" for v in components.values()) else "degraded"

    audit_logger.log_device_health_check(
        agent_id=agent_id,
        device="pi",
        status=status,
        latency_ms=latency_ms,
        components=components
    )

    return success_response({
        "device": "pi",
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "components": components,
        "raw_diagnostics": result
    })


@mcp_tool("pi_sync_eisv", timeout=30.0, register=False, description="Sync anima to EISV. Use pi(action='sync_eisv') instead.")
async def handle_pi_sync_eisv(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Sync Pi's anima state to Mac's EISV governance metrics.

    This bridges the embodied (Pi) and governance (Mac) systems:
    1. Reads current anima state from Pi
    2. Maps anima → EISV
    3. Optionally updates governance state
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    update_governance = arguments.get("update_governance", False)

    # Get anima state from Pi
    context = await call_pi_tool("get_lumen_context", {"include": ["anima"]}, agent_id=agent_id)

    error_msg = _extract_error_message(context)
    if error_msg:
        return error_response(f"Failed to get anima state: {error_msg}")

    anima = context.get("anima", {})
    anima_error = _extract_error_message(anima) if isinstance(anima, dict) else None
    if anima_error:
        return error_response(f"Anima state unavailable: {anima_error}")

    # Map to EISV — prefer Pi's pre-computed EISV when available
    eisv = map_anima_to_eisv(anima, pre_computed_eisv=context.get("eisv"))

    # Log the sync
    audit_logger.log_eisv_sync(
        agent_id=agent_id,
        source_device="pi",
        target_device="mac",
        anima_state=anima,
        eisv_mapped=eisv,
        sync_direction="pi_to_mac"
    )

    eisv_source = "pi (neural-weighted)" if context.get("eisv") else "mac (fallback)"
    result = {
        "operation": "sync_to_governance" if update_governance else "read_mapping",
        "note": (
            "Synced: anima→EISV pushed to governance state."
            if update_governance else
            "Read-only: computed EISV from anima state but did NOT update governance. "
            "Pass update_governance=true to push to governance."
        ),
        "anima": anima,
        "eisv": eisv,
        "eisv_source": eisv_source,
        "mapping": {
            "warmth → E (Energy)": f"{anima.get('warmth', 0):.6f} → {eisv['E']:.6f}",
            "clarity → I (Integrity)": f"{anima.get('clarity', 0):.6f} → {eisv['I']:.6f}",
            "stability → S (Entropy)": f"{anima.get('stability', 0):.6f} → {eisv['S']:.6f} (inverted)",
            "presence → V (Void)": f"{anima.get('presence', 0):.6f} → {eisv['V']:.6f} (scaled)",
        }
    }

    # Optionally update governance state with sensor-derived check-in
    if update_governance:
        try:
            import numpy as np
            from src import mcp_server

            # Derive complexity and confidence from anima readings:
            # - Low stability → high complexity (turbulent state is harder to work in)
            # - Clarity maps directly to confidence (clear sensors = reliable reading)
            stability = anima.get("stability", 0.5)
            clarity = anima.get("clarity", 0.5)
            sensor_complexity = round(1.0 - stability, 3)
            sensor_confidence = round(clarity, 3)

            sensor_state = {
                "parameters": np.array([]),
                "ethical_drift": np.array([0.0]),
                "response_text": (
                    f"EISV sync from Pi anima sensors — "
                    f"warmth={anima.get('warmth', 0):.2f}, "
                    f"clarity={clarity:.2f}, "
                    f"stability={stability:.2f}, "
                    f"presence={anima.get('presence', 0):.2f}"
                ),
                "complexity": sensor_complexity,
            }

            gov_result = await mcp_server.process_update_authenticated_async(
                agent_id=agent_id,
                api_key=None,
                agent_state=sensor_state,
                auto_save=True,
                confidence=sensor_confidence,
                session_bound=True,
            )

            result["governance_updated"] = True
            result["governance_verdict"] = gov_result.get("decision", {}).get("action", "unknown")
            result["governance_risk"] = gov_result.get("metrics", {}).get("risk_score")
            result["governance_coherence"] = gov_result.get("metrics", {}).get("coherence")
        except Exception as e:
            logger.warning(f"[pi_sync_eisv] Governance update failed: {e}", exc_info=True)
            result["governance_updated"] = False
            result["governance_error"] = str(e)

    return success_response(result)


@mcp_tool("pi_display", timeout=15.0, register=False, description="Control Pi display. Use pi(action='display') instead.")
async def handle_pi_display(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Control Pi's display via orchestrated call to manage_display.

    Translates pi(action='display') parameters to manage_display's action vocabulary:
    - screen param present → action='switch', screen=<value>
    - display_action param → use directly (face, next, previous, list_eras, etc.)
    - neither → action='next' (default: cycle to next screen)

    manage_display valid actions: switch, face, next, previous, list_eras, get_era, set_era
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    screen = arguments.get("screen")

    # Derive the correct manage_display action.
    # The outer 'action' key is 'display' (consumed by the pi router) —
    # we must NOT pass it through to manage_display which has its own action vocabulary.
    display_action = arguments.get("display_action")
    if display_action:
        # Explicit display sub-action (face, next, previous, list_eras, get_era, set_era)
        md_action = display_action
    elif screen:
        # Screen name provided → switch to that screen
        md_action = "switch"
    else:
        # Default: cycle to next screen
        md_action = "next"

    tool_args = {"action": md_action}
    if screen:
        tool_args["screen"] = screen

    result = await call_pi_tool("manage_display", tool_args, agent_id=agent_id)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Display control failed: {error_msg}")

    return success_response({
        "device": "pi",
        "action": md_action,
        "result": result
    })


@mcp_tool("pi_say", timeout=30.0, register=False, description="Lumen speak. Use pi(action='say') instead.")
async def handle_pi_say(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Have Lumen speak via orchestrated call to Pi's say tool."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    text = arguments.get("text", "")
    blocking = arguments.get("blocking", True)

    if not text:
        return error_response("text parameter required")

    result = await call_pi_tool("say", {"text": text, "blocking": blocking}, agent_id=agent_id)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Speech failed: {error_msg}")

    return success_response({
        "device": "pi",
        "spoken": text,
        "result": result
    })


@mcp_tool("pi_post_message", timeout=15.0, register=False, description="Post message. Use pi(action='message') instead.")
async def handle_pi_post_message(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Post a message to Lumen's message board via orchestrated call."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    message = arguments.get("message", "")
    source = arguments.get("source", "agent")
    agent_name = arguments.get("agent_name", "mac-governance")
    responds_to = arguments.get("responds_to")

    if not message:
        return error_response("message parameter required")

    tool_args = {
        "message": message,
        "source": source,
        "agent_name": agent_name
    }
    if responds_to:
        tool_args["responds_to"] = responds_to

    result = await call_pi_tool("post_message", tool_args, agent_id=agent_id)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Message post failed: {error_msg}")

    return success_response({
        "device": "pi",
        "message_posted": True,
        "result": result
    })


@mcp_tool("pi_lumen_qa", timeout=15.0, register=False, description="Lumen Q&A. Use pi(action='qa') instead.")
async def handle_pi_lumen_qa(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Unified Q&A tool for Lumen via Pi.
    
    Usage:
    - pi_lumen_qa() -> list unanswered questions
    - pi_lumen_qa(question_id="abc123", answer="...") -> answer question
    
    This is the preferred method for answering questions as it validates
    question IDs and ensures proper linking to the Q&A screen.
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    question_id = arguments.get("question_id")
    answer = arguments.get("answer")
    limit = arguments.get("limit", 5)
    agent_name = arguments.get("agent_name", "agent")
    
    tool_args = {
        "limit": limit,
        "agent_name": agent_name
    }
    
    if question_id and answer:
        # Answer mode
        tool_args["question_id"] = question_id
        tool_args["answer"] = answer
    
    result = await call_pi_tool("lumen_qa", tool_args, agent_id=agent_id)
    
    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Q&A operation failed: {error_msg}")
    
    return success_response({
        "device": "pi",
        "action": "answered" if (question_id and answer) else "list",
        "result": result
    })


@mcp_tool("pi_query", timeout=45.0, register=False, description="Query Lumen knowledge. Use pi(action='query') instead.")
async def handle_pi_query(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Query Lumen's knowledge via orchestrated call to Pi's query tool."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    text = arguments.get("text", "")
    query_type = arguments.get("type", "cognitive")
    limit = arguments.get("limit", 10)

    if not text:
        return error_response("text parameter required")

    result = await call_pi_tool("query", {
        "text": text,
        "type": query_type,
        "limit": limit
    }, agent_id=agent_id, timeout=40.0)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Query failed: {error_msg}")

    return success_response({
        "device": "pi",
        "query_type": query_type,
        "result": result
    })


@mcp_tool("pi_workflow", timeout=120.0, register=False, description="Pi workflow. Use pi(action='workflow') instead.")
async def handle_pi_workflow(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Execute a coordinated workflow across Pi tools.

    Supported workflows:
    - "full_status": Get context + health + display current screen
    - "morning_check": Read sensors, get mood, post greeting
    - "custom": Execute arbitrary sequence of tools
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    workflow = arguments.get("workflow", "full_status")
    custom_steps = arguments.get("steps", [])

    start_time = time.time()
    results = []
    errors = []
    tools_executed = []

    # Define workflow steps
    if workflow == "full_status":
        steps = [
            ("get_lumen_context", {"include": ["identity", "anima", "sensors", "mood"]}),
            ("diagnostics", {}),
        ]
    elif workflow == "morning_check":
        steps = [
            ("get_lumen_context", {"include": ["sensors", "mood"]}),
            ("post_message", {"message": "Good morning from Mac governance!", "source": "agent", "agent_name": "mac-governance"}),
        ]
    elif workflow == "custom" and custom_steps:
        steps = [(s.get("tool"), s.get("args", {})) for s in custom_steps]
    else:
        return error_response(f"Unknown workflow: {workflow}. Use 'full_status', 'morning_check', or 'custom' with steps.")

    # Log orchestration request
    audit_logger.log_orchestration_request(
        agent_id=agent_id,
        workflow=workflow,
        target_device="pi",
        tools_planned=[s[0] for s in steps],
        context={"custom": workflow == "custom"}
    )

    # Execute steps
    for tool_name, tool_args in steps:
        result = await call_pi_tool(tool_name, tool_args, agent_id=agent_id)
        tools_executed.append(tool_name)

        error_msg = _extract_error_message(result)
        if error_msg:
            errors.append(f"{tool_name}: {error_msg}")
            results.append({"tool": tool_name, "error": error_msg})
        else:
            results.append({"tool": tool_name, "result": result})

    total_latency_ms = (time.time() - start_time) * 1000
    success = len(errors) == 0

    # Log completion
    audit_logger.log_orchestration_complete(
        agent_id=agent_id,
        workflow=workflow,
        target_device="pi",
        tools_executed=tools_executed,
        success=success,
        total_latency_ms=total_latency_ms,
        errors=errors if errors else None,
        results_summary={"steps_completed": len(results), "steps_failed": len(errors)}
    )

    return success_response({
        "workflow": workflow,
        "success": success,
        "total_latency_ms": round(total_latency_ms, 2),
        "steps": results,
        "errors": errors if errors else None
    })


@mcp_tool("pi_git_pull", timeout=120.0, register=False, description="Pi git pull. Use pi(action='git_pull') instead.")
async def handle_pi_git_pull(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Pull latest code from GitHub on Pi and optionally restart the server.
    Proxies to Pi's git_pull MCP tool via Streamable HTTP transport.
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    stash = arguments.get("stash", False)
    force = arguments.get("force", False)
    restart = arguments.get("restart", False)

    tool_args = {}
    if stash:
        tool_args["stash"] = True
    if force:
        tool_args["force"] = True
    if restart:
        tool_args["restart"] = True

    result = await call_pi_tool("git_pull", tool_args, agent_id=agent_id, timeout=90.0)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Git pull failed: {error_msg}")

    return success_response({
        "device": "pi",
        "operation": "git_pull",
        "stash": stash,
        "force": force,
        "restart": restart,
        "result": result
    })


@mcp_tool("pi_system_power", timeout=30.0, register=False, description="Pi power control. Use pi(action='power') instead.")
async def handle_pi_system_power(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Reboot or shutdown the Pi remotely.
    Proxies to Pi's system_power MCP tool.
    """
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    action = arguments.get("action", "status")
    confirm = arguments.get("confirm", False)

    tool_args = {"action": action}
    if confirm:
        tool_args["confirm"] = True

    result = await call_pi_tool("system_power", tool_args, agent_id=agent_id, timeout=30.0)

    error_msg = _extract_error_message(result)
    if error_msg:
        return error_response(f"Power command failed: {error_msg}")

    return success_response({
        "device": "pi",
        "operation": "system_power",
        "action": action,
        "confirm": confirm,
        "result": result
    })


# ============================================================
# SSH-Based Pi Service Control (Fallback when MCP is down)
# ============================================================

# SSH configuration for Pi access
PI_SSH_USER = "unitares-anima"
PI_SSH_HOST_TAILSCALE = "100.89.201.36"
PI_SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519_pi")


@mcp_tool("pi_restart_service", timeout=60.0, register=True, description="Restart anima service on Pi via SSH. Works even when MCP is down.")
async def handle_pi_restart_service(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Restart the anima service on Pi via SSH.

    This is a FALLBACK tool for when the anima MCP service is down and
    pi(action='git_pull', restart=True) or other MCP-based tools can't work.

    Uses SSH to directly run systemctl commands on the Pi.
    Requires SSH key at ~/.ssh/id_ed25519_pi
    """
    import subprocess

    agent_id = arguments.get("agent_id", "mac-orchestrator")
    service = arguments.get("service", "anima")
    action = arguments.get("action", "restart")  # restart, start, stop, status

    # Whitelist allowed services
    ALLOWED_SERVICES = ["anima", "anima-broker", "ngrok"]
    if service not in ALLOWED_SERVICES:
        return error_response(f"Service '{service}' not in allowed list: {ALLOWED_SERVICES}")

    # Whitelist allowed actions
    ALLOWED_ACTIONS = ["restart", "start", "stop", "status"]
    if action not in ALLOWED_ACTIONS:
        return error_response(f"Action '{action}' not in allowed list: {ALLOWED_ACTIONS}")

    # Build SSH command
    ssh_cmd = [
        "ssh",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
        "-i", PI_SSH_KEY,
        f"{PI_SSH_USER}@{PI_SSH_HOST_TAILSCALE}",
        f"sudo systemctl {action} {service} && sleep 2 && systemctl is-active {service}"
    ]

    logger.info(f"[pi_restart_service] Running: {' '.join(ssh_cmd[:6])}... {action} {service}")

    # Audit the action
    audit_logger.log_cross_device_call(
        agent_id=agent_id,
        source_device="mac",
        target_device="pi",
        tool_name=f"ssh_systemctl_{action}",
        arguments={"service": service, "action": action},
        status="initiated"
    )

    start_time = time.time()
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        latency_ms = (time.time() - start_time) * 1000

        success = result.returncode == 0
        output = result.stdout.strip()
        error = result.stderr.strip() if result.stderr else None

        # Update audit with actual result
        audit_logger.log_cross_device_call(
            agent_id=agent_id,
            source_device="mac",
            target_device="pi",
            tool_name=f"ssh_systemctl_{action}",
            arguments={"service": service, "action": action},
            status="success" if success else "error",
            latency_ms=latency_ms,
            error=error if not success else None
        )

        return success_response({
            "device": "pi",
            "operation": f"ssh_systemctl_{action}",
            "service": service,
            "success": success,
            "status": output,
            "error": error,
            "latency_ms": round(latency_ms, 2)
        })

    except subprocess.TimeoutExpired:
        return error_response("SSH command timed out after 30s")
    except FileNotFoundError:
        return error_response(f"SSH key not found at {PI_SSH_KEY}")
    except Exception as e:
        return error_response(f"SSH command failed: {e}")


# ============================================================
# Periodic EISV Sync Task (Background)
# ============================================================

async def sync_eisv_once(update_governance: bool = False) -> Dict[str, Any]:
    """
    Perform a single EISV sync from Pi to Mac.

    Args:
        update_governance: Whether to update governance state with synced values

    Returns:
        Dict with sync results or error
    """
    try:
        # Get anima state from Pi (includes pre-computed EISV when available)
        result = await call_pi_tool("get_lumen_context", {"include": ["anima"]}, agent_id="eisv-sync-task")

        error_msg = _extract_error_message(result)
        if error_msg:
            return {"success": False, "error": error_msg}

        # Extract anima values
        anima = result.get("anima", {})
        if not anima:
            return {"success": False, "error": "No anima state in Pi response"}

        # Map to EISV — prefer Pi's pre-computed EISV when available
        eisv = map_anima_to_eisv(anima, pre_computed_eisv=result.get("eisv"))

        # Log the sync
        audit_logger.log_eisv_sync(
            agent_id="eisv-sync-task",
            source_device="pi",
            target_device="mac",
            anima_state=anima,
            eisv_mapped=eisv,
            sync_direction="pi_to_mac",
            details={"periodic": True, "update_governance": update_governance}
        )

        return {
            "success": True,
            "anima": anima,
            "eisv": eisv,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }

    except Exception as e:
        logger.warning(f"[EISV_SYNC] Sync failed: {e}")
        return {"success": False, "error": str(e)}


async def eisv_sync_task(interval_minutes: float = 5.0):
    """
    Background task that periodically syncs EISV from Pi to Mac.

    Runs every interval_minutes and logs anima→EISV mappings.
    This creates an audit trail of Lumen's embodied state over time.

    Args:
        interval_minutes: Sync interval (default: 5 minutes)
    """
    logger.info(f"[EISV_SYNC] Starting periodic sync (interval: {interval_minutes} minutes)")

    while True:
        try:
            await asyncio.sleep(interval_minutes * 60)

            result = await sync_eisv_once(update_governance=False)

            if result.get("success"):
                eisv = result.get("eisv", {})
                logger.info(
                    f"[EISV_SYNC] Synced: E={eisv.get('E', 0):.6f} "
                    f"I={eisv.get('I', 0):.6f} S={eisv.get('S', 0):.6f} V={eisv.get('V', 0):.6f}"
                )
            else:
                logger.warning(f"[EISV_SYNC] Sync failed: {result.get('error')}")

        except asyncio.CancelledError:
            logger.info("[EISV_SYNC] Periodic sync task cancelled")
            break
        except Exception as e:
            logger.warning(f"[EISV_SYNC] Task error: {e}")
