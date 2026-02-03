#!/usr/bin/env python3
"""
Central Operator Agent - Phase 1 & 2

Runs as a background service to observe system state, detect stuck agents,
and optionally recover them. 

Phases:
- Phase 1 (read-only): Observe + report only (operator_readonly mode)
- Phase 2 (recovery): Detect + auto-recover stuck agents (operator_recovery mode)

Usage:
    # Run once in read-only mode (for testing)
    python3 scripts/operator_agent.py --once

    # Run once with recovery enabled
    python3 scripts/operator_agent.py --once --enable-recovery

    # Run as daemon with recovery
    python3 scripts/operator_agent.py --daemon --enable-recovery

    # Run with custom intervals
    python3 scripts/operator_agent.py --stuck-interval 300 --health-interval 3600

Environment Variables:
    GOVERNANCE_TOOL_MODE=operator_recovery  # Set automatically when --enable-recovery
    MCP_SERVER_URL=http://127.0.0.1:8765/sse  # Override default
    OPERATOR_LABEL=Operator  # Override operator label
"""

import asyncio
import json
import os
import sys
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set operator mode BEFORE importing tool_modes
# Will be overridden to operator_recovery if --enable-recovery is passed
os.environ["GOVERNANCE_TOOL_MODE"] = "operator_readonly"

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession


class OperatorAgent:
    """Central Operator Agent - Phase 1 & 2: Observability + Recovery"""

    def __init__(
        self,
        mcp_url: str = "http://127.0.0.1:8765/sse",
        operator_label: str = "Operator",
        stuck_interval: int = 300,  # 5 minutes
        health_interval: int = 3600,  # 1 hour
        kg_interval: int = 86400,  # 24 hours
        enable_recovery: bool = False,  # Phase 2: auto-recovery
    ):
        self.mcp_url = mcp_url
        self.operator_label = operator_label
        self.stuck_interval = stuck_interval
        self.health_interval = health_interval
        self.kg_interval = kg_interval
        self.enable_recovery = enable_recovery
        self.force_new_identity = os.getenv("OPERATOR_FORCE_NEW", "1").lower() in ("1", "true", "yes")
        self.running = True
        self.operator_session_id: Optional[str] = None
        self.last_stuck_check = 0
        self.last_health_check = 0
        self.last_kg_check = 0
        
        # Track recovery attempts to avoid loops
        self.recovery_attempts: Dict[str, int] = {}  # agent_id -> attempt count
        self.max_recovery_attempts = 3  # Max attempts per agent per hour

    def _with_session(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Inject client_session_id when available to keep identity stable."""
        if tool_name == "onboard":
            return arguments
        if self.operator_session_id and "client_session_id" not in arguments:
            arguments = dict(arguments)
            arguments["client_session_id"] = self.operator_session_id
        return arguments

    async def call_tool(self, session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool and parse JSON response"""
        try:
            result = await session.call_tool(tool_name, self._with_session(tool_name, arguments))
            final_result: Dict[str, Any] = {}
            json_parsed = False
            raw_texts: list[str] = []

            # Parse JSON from all TextContent items (some tools stream multiple parts)
            for content in result.content:
                if hasattr(content, 'text'):
                    text = content.text
                    raw_texts.append(text)
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            final_result.update(data)
                            json_parsed = True
                    except json.JSONDecodeError:
                        continue

            if json_parsed:
                return final_result

            if raw_texts:
                return {"text": "\n".join(raw_texts), "raw": True}

            return {"success": False, "error": "No content in response"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def ensure_operator_identity(self, session: ClientSession) -> bool:
        """Ensure operator identity exists and is configured"""
        try:
            def extract_session_id(result: Dict[str, Any]) -> Optional[str]:
                return (
                    result.get("client_session_id")
                    or result.get("session_continuity", {}).get("client_session_id")
                    or result.get("identity_summary", {}).get("client_session_id", {}).get("value")
                )

            # Prefer identity() first: auto-creates identity and returns client_session_id
            identity_args = {"name": self.operator_label}
            identity_result = await self.call_tool(session, "identity", identity_args)

            # If server asks to resume/new, retry with explicit choice
            if identity_result.get("options"):
                if self.force_new_identity:
                    identity_result = await self.call_tool(session, "identity", {"force_new": True, "name": self.operator_label})
                else:
                    identity_result = await self.call_tool(session, "identity", {"resume": True, "name": self.operator_label})

            if identity_result.get("success"):
                client_session_id = extract_session_id(identity_result)
                if client_session_id:
                    self.operator_session_id = client_session_id
                    configured_name = identity_result.get("agent_id") or identity_result.get("name") or self.operator_label
                    print(f"✅ Operator identity configured: {configured_name}")
                    return True
                # If resume path didn't return a session id, fall back to force_new
                if not self.force_new_identity:
                    identity_force_new = await self.call_tool(
                        session,
                        "identity",
                        {"force_new": True, "name": self.operator_label}
                    )
                    client_session_id = extract_session_id(identity_force_new)
                    if client_session_id:
                        self.operator_session_id = client_session_id
                        configured_name = identity_force_new.get("agent_id") or identity_force_new.get("name") or self.operator_label
                        print("⚠️  Resume did not return session id; created new identity for continuity.")
                        print(f"✅ Operator identity configured: {configured_name}")
                        return True
                print(f"❌ identity() missing client_session_id: {identity_result}", file=sys.stderr)

            # Fallback: onboard (resume existing or create new)
            onboard_args = {"force_new": True} if self.force_new_identity else {"resume": True}
            result = await self.call_tool(session, "onboard", onboard_args)
            if result.get("options"):
                if self.force_new_identity:
                    result = await self.call_tool(session, "onboard", {"force_new": True})
                else:
                    result = await self.call_tool(session, "onboard", {"resume": True})
            if not result.get("success"):
                print(f"❌ Onboard failed: {result}", file=sys.stderr)
                return False

            client_session_id = extract_session_id(result)
            if not client_session_id and not self.force_new_identity:
                # If resume path didn't return session id, fall back to force_new
                result = await self.call_tool(session, "onboard", {"force_new": True})
                client_session_id = extract_session_id(result)

            if client_session_id:
                self.operator_session_id = client_session_id
                # Ensure name is set
                identity_result = await self.call_tool(
                    session,
                    "identity",
                    {"name": self.operator_label, "client_session_id": self.operator_session_id}
                )
                if identity_result.get("success"):
                    configured_name = identity_result.get("agent_id") or identity_result.get("name") or self.operator_label
                    print(f"✅ Operator identity configured: {configured_name}")
                    return True
                print(f"❌ Operator identity update failed: {identity_result}", file=sys.stderr)
                return False

            print(f"❌ Onboard response missing client_session_id: {result}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"❌ Failed to ensure operator identity: {e}", file=sys.stderr)
            return False

    async def detect_stuck_agents(self, session: ClientSession) -> List[Dict[str, Any]]:
        """Detect stuck agents and return list"""
        try:
            result = await self.call_tool(
                session,
                "detect_stuck_agents",
                {
                    "max_age_minutes": 30.0,
                    "critical_margin_timeout_minutes": 5.0,
                    "tight_margin_timeout_minutes": 15.0,
                }
            )
            
            if result.get("success") and "stuck_agents" in result:
                return result["stuck_agents"]
            return []
        except Exception as e:
            print(f"❌ Failed to detect stuck agents: {e}", file=sys.stderr)
            return []

    async def log_to_knowledge_graph(
        self,
        session: ClientSession,
        content: str,
        tags: List[str],
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Log observation to knowledge graph"""
        try:
            # Build details with metadata if provided
            details = content
            if metadata:
                details = f"{content}\n\nMetadata:\n{json.dumps(metadata, indent=2)}"
            
            result = await self.call_tool(
                session,
                "store_knowledge_graph",
                {
                    "discovery_type": "observation",
                    "summary": content,
                    "details": details,
                    "tags": tags,
                    "severity": severity,
                }
            )
            return result.get("success", False)
        except Exception as e:
            print(f"❌ Failed to log to knowledge graph: {e}", file=sys.stderr)
            return False

    async def check_stuck_agents(self, session: ClientSession):
        """Check for stuck agents and log findings"""
        print(f"[{datetime.now().isoformat()}] Checking for stuck agents...")
        
        stuck_agents = await self.detect_stuck_agents(session)
        
        if stuck_agents:
            count = len(stuck_agents)
            print(f"⚠️  Detected {count} stuck agent(s)")
            
            # Log summary
            summary = f"Operator detected {count} stuck agent(s): "
            agent_ids = [a.get("agent_id", "unknown") for a in stuck_agents]
            reasons = [a.get("reason", "unknown") for a in stuck_agents]
            
            await self.log_to_knowledge_graph(
                session,
                f"{summary}{', '.join(agent_ids)}. Reasons: {', '.join(set(reasons))}",
                tags=["operator", "observation", "stuck-detection"],
                severity="warning" if count > 0 else "info",
                metadata={
                    "stuck_count": count,
                    "agents": stuck_agents,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            
            # Log individual agents (for detailed tracking)
            for agent in stuck_agents:
                await self.log_to_knowledge_graph(
                    session,
                    f"Stuck agent detected: {agent.get('agent_id', 'unknown')} - {agent.get('reason', 'unknown')}",
                    tags=["operator", "stuck-agent", agent.get("reason", "unknown")],
                    severity="warning",
                    metadata=agent,
                )
            
            # Phase 2: Attempt recovery if enabled
            if self.enable_recovery:
                await self.attempt_recovery(session, stuck_agents)
        else:
            print("✅ No stuck agents detected")

    async def attempt_recovery(self, session: ClientSession, stuck_agents: List[Dict[str, Any]]):
        """Attempt to recover stuck agents (Phase 2)"""
        print(f"[{datetime.now().isoformat()}] Attempting recovery for {len(stuck_agents)} agent(s)...")
        
        recovered = 0
        failed = 0
        skipped = 0
        
        for agent in stuck_agents:
            agent_id = agent.get("agent_id", "unknown")
            reason = agent.get("reason", "unknown")
            
            # Check recovery attempt limit
            attempts = self.recovery_attempts.get(agent_id, 0)
            if attempts >= self.max_recovery_attempts:
                print(f"  ⏭️  Skipping {agent_id}: max recovery attempts reached ({attempts})")
                skipped += 1
                continue
            
            # Check eligibility first
            eligibility = await self.call_tool(
                session,
                "check_recovery_options",
                {"agent_id": agent_id}
            )
            
            if not eligibility.get("eligible", False):
                blockers = eligibility.get("blockers", [])
                blocker_msgs = [b.get("message", "unknown") for b in blockers]
                print(f"  ❌ {agent_id}: Not eligible - {'; '.join(blocker_msgs)}")
                failed += 1
                continue
            
            # Attempt recovery
            recovery_result = await self.call_tool(
                session,
                "operator_resume_agent",
                {
                    "target_agent_id": agent_id,
                    "reason": f"Auto-recovery by operator: {reason}",
                }
            )
            
            if recovery_result.get("success"):
                print(f"  ✅ {agent_id}: Recovered successfully")
                recovered += 1
                # Reset attempt counter on success
                self.recovery_attempts[agent_id] = 0
            else:
                error = recovery_result.get("error", "Unknown error")
                print(f"  ❌ {agent_id}: Recovery failed - {error}")
                failed += 1
                # Increment attempt counter
                self.recovery_attempts[agent_id] = attempts + 1
        
        # Log recovery summary
        await self.log_to_knowledge_graph(
            session,
            f"Operator recovery: {recovered} recovered, {failed} failed, {skipped} skipped",
            tags=["operator", "recovery", "summary"],
            severity="info" if failed == 0 else "warning",
            metadata={
                "recovered": recovered,
                "failed": failed,
                "skipped": skipped,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        
        print(f"  📊 Recovery summary: {recovered} recovered, {failed} failed, {skipped} skipped")

    async def check_system_health(self, session: ClientSession):
        """Check system health and log findings"""
        print(f"[{datetime.now().isoformat()}] Checking system health...")
        
        try:
            # Health check
            health_result = await self.call_tool(session, "health_check", {})
            
            # Workspace health
            workspace_result = await self.call_tool(session, "get_workspace_health", {})
            
            # Telemetry metrics
            telemetry_result = await self.call_tool(session, "get_telemetry_metrics", {})
            
            # Aggregate findings
            health_status = "unknown"
            if health_result.get("success"):
                health_status = (
                    health_result.get("status")
                    or health_result.get("health", {}).get("status")
                    or "unknown"
                )
            
            summary = f"System health check: {health_status}"
            
            await self.log_to_knowledge_graph(
                session,
                summary,
                tags=["operator", "health-check", health_status],
                severity="info" if health_status == "healthy" else "warning",
                metadata={
                    "health": health_result,
                    "workspace": workspace_result,
                    "telemetry": telemetry_result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            
            print(f"✅ Health check complete: {health_status}")
        except Exception as e:
            print(f"❌ Health check failed: {e}", file=sys.stderr)

    async def check_knowledge_graph(self, session: ClientSession):
        """Check knowledge graph lifecycle stats"""
        print(f"[{datetime.now().isoformat()}] Checking knowledge graph lifecycle...")
        
        try:
            # Get lifecycle stats
            stats_result = await self.call_tool(session, "get_lifecycle_stats", {})
            
            if stats_result.get("success"):
                stats = stats_result.get("stats", {})
                by_status = stats.get("by_status", {})
                total = stats.get("total_discoveries", 0)
                summary = (
                    f"KG lifecycle stats: "
                    f"{by_status.get('open', 0)} open, "
                    f"{by_status.get('resolved', 0)} resolved, "
                    f"{by_status.get('archived', 0)} archived "
                    f"(total {total})"
                )
                
                await self.log_to_knowledge_graph(
                    session,
                    summary,
                    tags=["operator", "kg-report", "lifecycle"],
                    severity="info",
                    metadata={
                        "stats": stats,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                
                print(f"✅ KG check complete: {summary}")
        except Exception as e:
            print(f"❌ KG check failed: {e}", file=sys.stderr)

    async def run_once(self):
        """Run all checks once (for testing)"""
        phase_label = "Phase 2 (Recovery Enabled)" if self.enable_recovery else "Phase 1 (Read-Only)"
        print(f"🚀 Central Operator Agent - {phase_label}")
        print(f"   MCP Server: {self.mcp_url}")
        print(f"   Tool Mode: {'operator_recovery' if self.enable_recovery else 'operator_readonly'}")
        print()
        
        async with sse_client(self.mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Ensure operator identity
                if not await self.ensure_operator_identity(session):
                    print("❌ Failed to configure operator identity", file=sys.stderr)
                    return
                
                # Run all checks
                await self.check_stuck_agents(session)
                await self.check_system_health(session)
                await self.check_knowledge_graph(session)
                
                print("\n✅ Operator checks complete")

    async def run_daemon(self):
        """Run operator as daemon with periodic checks"""
        phase_label = "Phase 2 (Recovery Enabled)" if self.enable_recovery else "Phase 1 (Read-Only)"
        print(f"🚀 Central Operator Agent - {phase_label} - Daemon Mode")
        print(f"   MCP Server: {self.mcp_url}")
        print(f"   Tool Mode: {'operator_recovery' if self.enable_recovery else 'operator_readonly'}")
        print(f"   Stuck check interval: {self.stuck_interval}s")
        print(f"   Health check interval: {self.health_interval}s")
        print(f"   KG check interval: {self.kg_interval}s")
        print()
        
        # Setup signal handlers
        def signal_handler(signum, frame):
            print(f"\n[{datetime.now().isoformat()}] Received signal {signum}, shutting down...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        while self.running:
            try:
                async with sse_client(self.mcp_url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        
                        # Ensure operator identity (first time only)
                        if not self.operator_session_id:
                            if not await self.ensure_operator_identity(session):
                                print("❌ Failed to configure operator identity", file=sys.stderr)
                                await asyncio.sleep(60)  # Wait before retry
                                continue
                        
                        current_time = time.time()
                        
                        # Check stuck agents (every stuck_interval)
                        if current_time - self.last_stuck_check >= self.stuck_interval:
                            await self.check_stuck_agents(session)
                            self.last_stuck_check = current_time
                        
                        # Check system health (every health_interval)
                        if current_time - self.last_health_check >= self.health_interval:
                            await self.check_system_health(session)
                            self.last_health_check = current_time
                        
                        # Check KG lifecycle (every kg_interval)
                        if current_time - self.last_kg_check >= self.kg_interval:
                            await self.check_knowledge_graph(session)
                            self.last_kg_check = current_time
                        
                        # Sleep briefly before next iteration
                        await asyncio.sleep(30)  # Check every 30 seconds
                        
            except KeyboardInterrupt:
                print("\n[{datetime.now().isoformat()}] Interrupted, shutting down...")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Operator loop error: {e}", file=sys.stderr)
                await asyncio.sleep(60)  # Wait before retry
        
        print("✅ Operator daemon stopped")


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Central Operator Agent - Phase 1 (Read-Only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run checks once and exit (for testing)"
    )
    
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon with periodic checks"
    )
    
    parser.add_argument(
        "--url",
        default=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8765/sse"),
        help="MCP server URL (default: http://127.0.0.1:8765/sse)"
    )
    
    parser.add_argument(
        "--label",
        default=os.getenv("OPERATOR_LABEL", "Operator"),
        help="Operator label (default: Operator)"
    )
    
    parser.add_argument(
        "--stuck-interval",
        type=int,
        default=int(os.getenv("OPERATOR_STUCK_INTERVAL", "300")),
        help="Stuck agent check interval in seconds (default: 300)"
    )
    
    parser.add_argument(
        "--health-interval",
        type=int,
        default=int(os.getenv("OPERATOR_HEALTH_INTERVAL", "3600")),
        help="Health check interval in seconds (default: 3600)"
    )
    
    parser.add_argument(
        "--kg-interval",
        type=int,
        default=int(os.getenv("OPERATOR_KG_INTERVAL", "86400")),
        help="Knowledge graph check interval in seconds (default: 86400)"
    )

    parser.add_argument(
        "--enable-recovery",
        action="store_true",
        default=os.getenv("OPERATOR_ENABLE_RECOVERY", "0").lower() in ("1", "true", "yes"),
        help="Enable Phase 2 recovery actions (operator_resume_agent)"
    )
    
    args = parser.parse_args()
    
    if args.enable_recovery:
        os.environ["GOVERNANCE_TOOL_MODE"] = "operator_recovery"

    operator = OperatorAgent(
        mcp_url=args.url,
        operator_label=args.label,
        stuck_interval=args.stuck_interval,
        health_interval=args.health_interval,
        kg_interval=args.kg_interval,
        enable_recovery=args.enable_recovery,
    )
    
    if args.once:
        await operator.run_once()
    elif args.daemon:
        await operator.run_daemon()
    else:
        # Default to once if neither flag specified
        await operator.run_once()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Operator stopped")
        sys.exit(0)
