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

All calls are audited via audit_log.py cross-device events.
"""

import json
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
PI_MCP_URL = "http://localhost:8766/mcp/"  # Via SSH tunnel
PI_MCP_TIMEOUT = 30.0  # Default timeout for Pi calls


async def call_pi_tool(tool_name: str, arguments: Dict[str, Any],
                       agent_id: str = "mac-orchestrator",
                       timeout: float = PI_MCP_TIMEOUT) -> Dict[str, Any]:
    """
    Call a tool on Pi's anima-mcp and return the result.

    Handles:
    - HTTP transport to Pi via SSH tunnel
    - Timeout protection
    - Audit logging of cross-device calls
    - Error handling with meaningful messages

    Args:
        tool_name: Name of the anima-mcp tool to call
        arguments: Tool arguments
        agent_id: Agent making the call (for audit)
        timeout: Request timeout in seconds

    Returns:
        Dict with tool result or error
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

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # MCP-over-HTTP: POST to tools/call endpoint (Streamable HTTP transport)
            response = await client.post(
                PI_MCP_URL,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    },
                    "id": f"mac-{int(time.time()*1000)}"
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )

            latency_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                audit_logger.log_cross_device_call(
                    agent_id=agent_id,
                    source_device="mac",
                    target_device="pi",
                    tool_name=tool_name,
                    arguments=arguments,
                    status="error",
                    latency_ms=latency_ms,
                    error=f"HTTP {response.status_code}"
                )
                return {"error": f"Pi MCP returned HTTP {response.status_code}"}

            # Parse SSE response format: "event: message\ndata: {json}\n\n"
            text = response.text
            if text.startswith("event:"):
                # Extract JSON from SSE data line
                for line in text.split("\n"):
                    if line.startswith("data:"):
                        result = json.loads(line[5:].strip())
                        break
                else:
                    return {"error": "No data in SSE response"}
            else:
                result = response.json()

            # Extract result from MCP response
            if "error" in result:
                audit_logger.log_cross_device_call(
                    agent_id=agent_id,
                    source_device="mac",
                    target_device="pi",
                    tool_name=tool_name,
                    arguments=arguments,
                    status="error",
                    latency_ms=latency_ms,
                    error=str(result["error"])
                )
                return {"error": result["error"]}

            # Success - extract content from MCP result
            mcp_result = result.get("result", {})
            content = mcp_result.get("content", [])

            # Parse text content
            if content and isinstance(content, list) and len(content) > 0:
                text_content = content[0].get("text", "{}")
                try:
                    parsed = json.loads(text_content)
                except json.JSONDecodeError:
                    parsed = {"text": text_content}
            else:
                parsed = mcp_result

            audit_logger.log_cross_device_call(
                agent_id=agent_id,
                source_device="mac",
                target_device="pi",
                tool_name=tool_name,
                arguments=arguments,
                status="success",
                latency_ms=latency_ms
            )

            return parsed

    except httpx.TimeoutException:
        latency_ms = (time.time() - start_time) * 1000
        audit_logger.log_cross_device_call(
            agent_id=agent_id,
            source_device="mac",
            target_device="pi",
            tool_name=tool_name,
            arguments=arguments,
            status="timeout",
            latency_ms=latency_ms,
            error=f"Timeout after {timeout}s"
        )
        return {"error": f"Pi MCP timeout after {timeout}s"}

    except httpx.ConnectError as e:
        latency_ms = (time.time() - start_time) * 1000
        audit_logger.log_cross_device_call(
            agent_id=agent_id,
            source_device="mac",
            target_device="pi",
            tool_name=tool_name,
            arguments=arguments,
            status="error",
            latency_ms=latency_ms,
            error=f"Connection failed: {e}"
        )
        return {"error": f"Cannot connect to Pi MCP (is SSH tunnel running?): {e}"}

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        audit_logger.log_cross_device_call(
            agent_id=agent_id,
            source_device="mac",
            target_device="pi",
            tool_name=tool_name,
            arguments=arguments,
            status="error",
            latency_ms=latency_ms,
            error=str(e)
        )
        return {"error": f"Pi MCP call failed: {e}"}


def map_anima_to_eisv(anima: Dict[str, float]) -> Dict[str, float]:
    """
    Map Anima state (Pi) to EISV governance metrics (Mac).

    Mapping:
    - Warmth → Energy (E): Engagement/activity level
    - Clarity → Integrity (I): Information coherence
    - Stability → 1-Entropy (S): Low stability = high scatter
    - Presence → 1-Void (V): Low presence = high void/disconnection

    Args:
        anima: Dict with warmth, clarity, stability, presence (0-1 each)

    Returns:
        Dict with E, I, S, V values (0-1 each)
    """
    return {
        "E": anima.get("warmth", 0.5),
        "I": anima.get("clarity", 0.5),
        "S": 1.0 - anima.get("stability", 0.5),  # Stability inverts to entropy
        "V": 1.0 - anima.get("presence", 0.5),   # Presence inverts to void
    }


# ============================================================
# MCP Tool Handlers
# ============================================================

@mcp_tool("pi_get_context", timeout=30.0, description="Get Lumen's complete context from Pi (identity, anima, sensors, mood)")
async def handle_pi_get_context(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get Lumen's complete context from Pi via orchestrated call to get_lumen_context."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    include = arguments.get("include", ["identity", "anima", "sensors", "mood"])

    result = await call_pi_tool("get_lumen_context", {"include": include}, agent_id=agent_id)

    if "error" in result:
        return error_response(f"Failed to get Pi context: {result['error']}")

    return success_response({
        "source": "pi",
        "context": result
    })


@mcp_tool("pi_health", timeout=15.0, description="Check Pi anima-mcp health and connectivity")
async def handle_pi_health(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Check Pi's anima-mcp health and connectivity via orchestrated call."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    start_time = time.time()

    # Call diagnostics tool on Pi
    result = await call_pi_tool("diagnostics", {}, agent_id=agent_id, timeout=10.0)
    latency_ms = (time.time() - start_time) * 1000

    if "error" in result:
        status = "unreachable" if "connect" in str(result["error"]).lower() else "error"
        audit_logger.log_device_health_check(
            agent_id=agent_id,
            device="pi",
            status=status,
            latency_ms=latency_ms,
            details={"error": result["error"]}
        )
        return error_response(f"Pi health check failed: {result['error']}")

    # Parse component status
    components = {}
    if "led" in result:
        components["leds"] = "ok" if result.get("led", {}).get("initialized") else "unavailable"
    if "display" in result:
        components["display"] = "ok" if result.get("display", {}).get("available") else "unavailable"
    if "update_loop" in result:
        components["update_loop"] = "ok" if result.get("update_loop", {}).get("running") else "stopped"

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


@mcp_tool("pi_sync_eisv", timeout=30.0, description="Sync Lumen's anima state to EISV governance metrics")
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

    if "error" in context:
        return error_response(f"Failed to get anima state: {context['error']}")

    anima = context.get("anima", {})
    if "error" in anima:
        return error_response(f"Anima state unavailable: {anima['error']}")

    # Map to EISV
    eisv = map_anima_to_eisv(anima)

    # Log the sync
    audit_logger.log_eisv_sync(
        agent_id=agent_id,
        source_device="pi",
        target_device="mac",
        anima_state=anima,
        eisv_mapped=eisv,
        sync_direction="pi_to_mac"
    )

    result = {
        "anima": anima,
        "eisv": eisv,
        "mapping": {
            "warmth → E (Energy)": f"{anima.get('warmth', 0):.3f} → {eisv['E']:.3f}",
            "clarity → I (Integrity)": f"{anima.get('clarity', 0):.3f} → {eisv['I']:.3f}",
            "stability → S (Entropy)": f"{anima.get('stability', 0):.3f} → {eisv['S']:.3f} (inverted)",
            "presence → V (Void)": f"{anima.get('presence', 0):.3f} → {eisv['V']:.3f} (inverted)",
        }
    }

    # Optionally update governance state
    if update_governance:
        # TODO: Call process_agent_update with derived EISV
        result["governance_updated"] = False
        result["governance_note"] = "Governance update not yet implemented"

    return success_response(result)


@mcp_tool("pi_display", timeout=15.0, description="Control Pi's display (switch screens, show face)")
async def handle_pi_display(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Control Pi's display via orchestrated call to manage_display."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    action = arguments.get("action", "next")
    screen = arguments.get("screen")

    tool_args = {"action": action}
    if screen:
        tool_args["screen"] = screen

    result = await call_pi_tool("manage_display", tool_args, agent_id=agent_id)

    if "error" in result:
        return error_response(f"Display control failed: {result['error']}")

    return success_response({
        "device": "pi",
        "action": action,
        "result": result
    })


@mcp_tool("pi_say", timeout=30.0, description="Have Lumen speak via Pi's voice system")
async def handle_pi_say(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Have Lumen speak via orchestrated call to Pi's say tool."""
    agent_id = arguments.get("agent_id", "mac-orchestrator")
    text = arguments.get("text", "")
    blocking = arguments.get("blocking", True)

    if not text:
        return error_response("text parameter required")

    result = await call_pi_tool("say", {"text": text, "blocking": blocking}, agent_id=agent_id)

    if "error" in result:
        return error_response(f"Speech failed: {result['error']}")

    return success_response({
        "device": "pi",
        "spoken": text,
        "result": result
    })


@mcp_tool("pi_post_message", timeout=15.0, description="Post a message to Lumen's message board on Pi")
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

    if "error" in result:
        return error_response(f"Message post failed: {result['error']}")

    return success_response({
        "device": "pi",
        "message_posted": True,
        "result": result
    })


@mcp_tool("pi_query", timeout=45.0, description="Query Lumen's knowledge systems on Pi")
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

    if "error" in result:
        return error_response(f"Query failed: {result['error']}")

    return success_response({
        "device": "pi",
        "query_type": query_type,
        "result": result
    })


@mcp_tool("pi_workflow", timeout=120.0, description="Execute a multi-step workflow on Pi with audit trail")
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

        if "error" in result:
            errors.append(f"{tool_name}: {result['error']}")
            results.append({"tool": tool_name, "error": result["error"]})
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
        # Get anima state from Pi
        result = await call_pi_tool("get_state", {}, agent_id="eisv-sync-task")

        if "error" in result:
            return {"success": False, "error": result["error"]}

        # Extract anima values
        anima = result.get("anima", {})
        if not anima:
            return {"success": False, "error": "No anima state in Pi response"}

        # Map to EISV
        eisv = map_anima_to_eisv(anima)

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
                    f"[EISV_SYNC] Synced: E={eisv.get('E', 0):.2f} "
                    f"I={eisv.get('I', 0):.2f} S={eisv.get('S', 0):.2f} V={eisv.get('V', 0):.2f}"
                )
            else:
                logger.warning(f"[EISV_SYNC] Sync failed: {result.get('error')}")

        except asyncio.CancelledError:
            logger.info("[EISV_SYNC] Periodic sync task cancelled")
            break
        except Exception as e:
            logger.warning(f"[EISV_SYNC] Task error: {e}")
