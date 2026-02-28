#!/usr/bin/env python3
"""
Kimi Governance Client - Sandboxed Python wrapper for UNITARES MCP

A lightweight, self-contained client for interacting with the UNITARES governance
system via HTTP. No MCP dependencies, no external client modules.

Usage:
    from kimi_governance_client import KimiGovernanceClient
    
    client = KimiGovernanceClient()
    client.onboard("my_agent_name")
    client.update("Completed task X", complexity=0.5, confidence=0.8)
    metrics = client.get_metrics()

Sandbox Guarantees:
    - Only accesses files within the project directory
    - Uses standard library only (no external deps)
    - Session isolation via local session file
    - Read-only by default; writes only to session file
"""

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass
from contextlib import contextmanager


@dataclass
class GovernanceMetrics:
    """EISV metrics from governance system.
    
    Handles both flat and rich (dict-with-metadata) formats.
    """
    E: Union[float, Dict[str, Any]]  # Energy
    I: Union[float, Dict[str, Any]]  # Information Integrity
    S: Union[float, Dict[str, Any]]  # Entropy (lower is better)
    V: Union[float, Dict[str, Any]]  # Void (lower is better)
    coherence: Union[float, Dict[str, Any]]
    risk_score: Union[float, Dict[str, Any], None]
    status: str
    regime: Optional[str] = None
    confidence: Optional[float] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceMetrics":
        return cls(
            E=data.get("E", 0.0),
            I=data.get("I", 0.0),
            S=data.get("S", 0.0),
            V=data.get("V", 0.0),
            coherence=data.get("coherence", 0.0),
            risk_score=data.get("risk_score"),
            status=data.get("status", "unknown"),
            regime=data.get("regime"),
            confidence=data.get("confidence"),
        )
    
    def _extract_value(self, field: Union[float, Dict[str, Any]]) -> Any:
        """Extract raw value from potentially rich format."""
        if isinstance(field, dict):
            return field.get("value", field)
        return field
    
    @property
    def E_value(self) -> float:
        """Get numeric Energy value."""
        return self._extract_value(self.E)
    
    @property
    def I_value(self) -> float:
        """Get numeric Integrity value."""
        return self._extract_value(self.I)
    
    @property
    def S_value(self) -> float:
        """Get numeric Entropy value."""
        return self._extract_value(self.S)
    
    @property
    def V_value(self) -> float:
        """Get numeric Void value."""
        return self._extract_value(self.V)
    
    @property
    def coherence_value(self) -> Optional[float]:
        """Get numeric coherence value."""
        return self._extract_value(self.coherence)
    
    @property
    def risk_score_value(self) -> Optional[float]:
        """Get numeric risk score value."""
        if self.risk_score is None:
            return None
        return self._extract_value(self.risk_score)


@dataclass
class GovernanceDecision:
    """Governance decision from process_agent_update."""
    action: str  # proceed, guide, pause, reject
    reason: str
    guidance: Optional[str] = None
    margin: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceDecision":
        return cls(
            action=data.get("action", "unknown"),
            reason=data.get("reason", "No reason provided"),
            guidance=data.get("guidance"),
            margin=data.get("margin"),
        )
    
    @property
    def can_proceed(self) -> bool:
        """Check if verdict allows proceeding."""
        return self.action in ("proceed", "guide")
    
    @property
    def emoji(self) -> str:
        """Get emoji for verdict."""
        return {
            "proceed": "✅",
            "guide": "⚠️",
            "pause": "⏸️",
            "reject": "❌",
        }.get(self.action, "❓")


@dataclass
class AgentIdentity:
    """Agent identity from onboard."""
    agent_id: str
    uuid: str
    client_session_id: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentIdentity":
        # Handle both flat and nested result structures
        result = data.get("result", data)
        return cls(
            agent_id=result.get("agent_id", "unknown"),
            uuid=result.get("uuid", "unknown"),
            client_session_id=result.get("client_session_id") or data.get("client_session_id"),
        )


class KimiGovernanceClient:
    """
    Sandboxed client for UNITARES governance system.
    
    This client uses only Python standard library and operates within
    the project directory. It persists session state to a local file
    for continuity across calls.
    
    Args:
        server_url: URL of the UNITARES server (default: http://127.0.0.1:8767)
        project_dir: Project directory for sandbox boundaries (default: auto-detect)
        session_file: Name of session persistence file (default: .kimi_governance_session)
    """
    
    def __init__(
        self,
        server_url: Optional[str] = None,
        project_dir: Optional[Union[str, Path]] = None,
        session_file: str = ".kimi_governance_session",
    ):
        # Server configuration
        self.server_url = server_url or os.getenv(
            "UNITARES_URL", 
            "http://127.0.0.1:8767"
        ).rstrip("/")
        
        # Sandbox boundaries
        self.project_dir = Path(project_dir or self._detect_project_dir())
        self.session_file = self.project_dir / session_file
        
        # Runtime state
        self._session_id: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._uuid: Optional[str] = None
        
        # Load existing session
        self._load_session()
    
    def _detect_project_dir(self) -> Path:
        """Auto-detect project directory from this file's location."""
        return Path(__file__).parent.resolve()
    
    def _load_session(self) -> None:
        """Load session from file if exists."""
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text())
                self._session_id = data.get("client_session_id")
                self._agent_id = data.get("agent_id")
                self._uuid = data.get("uuid")
            except (json.JSONDecodeError, IOError):
                pass  # Invalid or unreadable session file
    
    def _save_session(self) -> None:
        """Save session to file."""
        try:
            self.session_file.write_text(json.dumps({
                "client_session_id": self._session_id,
                "agent_id": self._agent_id,
                "uuid": self._uuid,
            }, indent=2))
        except IOError:
            pass  # Can't write session file (non-critical)
    
    def _call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Call an MCP tool via HTTP POST.
        
        Args:
            tool_name: Name of the MCP tool to call
            arguments: Tool arguments dictionary
            
        Returns:
            Response dictionary from the server
            
        Raises:
            GovernanceAPIError: On API errors
            GovernanceConnectionError: On connection failures
        """
        url = f"{self.server_url}/v1/tools/call"
        args = arguments or {}
        
        # Inject session ID if available
        if self._session_id and "client_session_id" not in args:
            args["client_session_id"] = self._session_id
        
        data = json.dumps({"name": tool_name, "arguments": args}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        if self._session_id:
            headers["X-Session-ID"] = self._session_id
        
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        # Handle SSL context for development (localhost doesn't need strict SSL)
        context = ssl.create_default_context()
        if self.server_url.startswith("https://localhost") or \
           self.server_url.startswith("https://127.0.0.1"):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, timeout=30, context=context) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                
                # Update session if returned
                if "client_session_id" in result:
                    self._session_id = result["client_session_id"]
                    self._save_session()
                
                return result
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if hasattr(e, "read") else ""
            raise GovernanceAPIError(f"HTTP {e.code}: {e.reason}", error_body) from e
        except urllib.error.URLError as e:
            raise GovernanceConnectionError(
                f"Cannot connect to {self.server_url}. Is the server running?"
            ) from e
        except json.JSONDecodeError as e:
            raise GovernanceAPIError("Invalid JSON response from server") from e
    
    # ========================================================================
    # Essential Methods (from UNITARES skill)
    # ========================================================================
    
    def onboard(
        self, 
        name: Optional[str] = None,
        force_new: bool = False,
        resume: bool = False,
    ) -> AgentIdentity:
        """
        Register or resume agent identity with governance system.
        
        Args:
            name: Descriptive name for the agent (e.g., "kimi_task_20250206")
            force_new: Create new identity even if session exists
            resume: Try to resume existing identity
            
        Returns:
            AgentIdentity with agent_id and uuid
        """
        args: Dict[str, Any] = {}
        if name:
            args["name"] = name
        if force_new:
            args["force_new"] = True
        if resume:
            args["resume"] = True
        
        result = self._call_tool("onboard", args)
        
        identity = AgentIdentity.from_dict(result)
        self._agent_id = identity.agent_id
        self._uuid = identity.uuid
        if identity.client_session_id:
            self._session_id = identity.client_session_id
        self._save_session()
        
        return identity
    
    def update(
        self,
        response_text: str,
        complexity: float = 0.5,
        confidence: float = 0.8,
    ) -> tuple[GovernanceDecision, GovernanceMetrics]:
        """
        Log work and get governance feedback.
        
        This is the primary method for checking in with the governance system
        after completing work units.
        
        Args:
            response_text: Brief summary of work completed
            complexity: 0.0-1.0 estimate of task difficulty
            confidence: 0.0-1.0 confidence in output quality (be honest!)
            
        Returns:
            Tuple of (GovernanceDecision, GovernanceMetrics)
        """
        result = self._call_tool("process_agent_update", {
            "response_text": response_text,
            "complexity": complexity,
            "confidence": confidence,
        })
        
        # Extract from nested result structure
        inner = result.get("result", {})
        
        # Build decision from action/reason fields
        decision = GovernanceDecision(
            action=inner.get("action", "unknown"),
            reason=inner.get("reason", "Check-in processed"),
            guidance=inner.get("guidance"),
            margin=inner.get("margin"),
        )
        
        # Build metrics from EISV fields
        metrics = GovernanceMetrics.from_dict(inner)
        
        return decision, metrics
    
    def get_metrics(self) -> GovernanceMetrics:
        """
        Get current EISV metrics without logging work.
        
        Returns:
            Current GovernanceMetrics
        """
        result = self._call_tool("get_governance_metrics", {})
        
        # Handle both flat and nested structures
        metrics_data = result.get("metrics") or result.get("result", {}) or result
        return GovernanceMetrics.from_dict(metrics_data)
    
    def get_identity(self) -> Optional[AgentIdentity]:
        """
        Get current agent identity if onboarded.
        
        Returns:
            AgentIdentity if onboarded, None otherwise
        """
        if not self._agent_id:
            return None
        return AgentIdentity(
            agent_id=self._agent_id,
            uuid=self._uuid or "unknown",
            client_session_id=self._session_id,
        )
    
    # ========================================================================
    # Knowledge Graph (Optional)
    # ========================================================================
    
    def search_knowledge(
        self, 
        query: str, 
        discovery_type: Optional[str] = None,
        limit: int = 10,
    ) -> list[Dict[str, Any]]:
        """
        Search the knowledge graph for existing discoveries.
        
        Args:
            query: Search query text
            discovery_type: Filter by type (note, insight, bug_found, etc.)
            limit: Maximum results to return
            
        Returns:
            List of discovery dictionaries
        """
        args = {"query": query, "limit": limit}
        if discovery_type:
            args["discovery_type"] = discovery_type
        
        result = self._call_tool("search_knowledge_graph", args)
        discoveries = result.get("discoveries") or result.get("result", {}).get("discoveries", [])
        return discoveries
    
    def leave_note(
        self,
        content: str,
        tags: Optional[list[str]] = None,
        discovery_type: str = "note",
    ) -> Dict[str, Any]:
        """
        Quick method to leave a note in the knowledge graph.
        
        Args:
            content: Note content
            tags: List of tags for discoverability
            discovery_type: Type of discovery (note, insight, bug_found, etc.)
            
        Returns:
            Response from server
        """
        args = {
            "discovery_type": discovery_type,
            "content": content,
        }
        if tags:
            args["tags"] = tags
        
        return self._call_tool("leave_note", args)
    
    # ========================================================================
    # Utility
    # ========================================================================
    
    def status(self) -> Dict[str, Any]:
        """
        Quick status check - identity + metrics.
        
        Returns:
            Dictionary with identity and metrics
        """
        identity = self.get_identity()
        try:
            metrics = self.get_metrics()
        except GovernanceError as e:
            metrics = None
            error = str(e)
        else:
            error = None
        
        return {
            "identity": {
                "agent_id": identity.agent_id if identity else None,
                "uuid": identity.uuid[:8] + "..." if identity and identity.uuid else None,
            },
            "metrics": metrics,
            "error": error,
        }
    
    def print_status(self) -> None:
        """Print formatted status to stdout."""
        status = self.status()
        
        print("🔍 Governance Status")
        print("=" * 40)
        
        if status["identity"]["agent_id"]:
            print(f"👤 Agent ID: {status['identity']['agent_id']}")
            print(f"   UUID: {status['identity']['uuid']}")
        else:
            print("👤 Not onboarded")
            print("   Run: client.onboard('your_name')")
        
        if status["metrics"]:
            m = status["metrics"]
            print(f"\n📊 EISV Metrics:")
            print(f"   Energy (E):        {m.E_value:.3f}" if isinstance(m.E_value, (int, float)) else f"   Energy (E):        {m.E}")
            print(f"   Integrity (I):     {m.I_value:.3f}" if isinstance(m.I_value, (int, float)) else f"   Integrity (I):     {m.I}")
            print(f"   Entropy (S):       {m.S_value:.3f} (lower is better)" if isinstance(m.S_value, (int, float)) else f"   Entropy (S):       {m.S}")
            print(f"   Void (V):          {m.V_value:.3f} (lower is better)" if isinstance(m.V_value, (int, float)) else f"   Void (V):          {m.V}")
            print(f"   Coherence:         {m.coherence_value:.3f}" if isinstance(m.coherence_value, (int, float)) else f"   Coherence:         {m.coherence}")
            rs = m.risk_score_value
            print(f"   Risk Score:        {rs:.3f}" if isinstance(rs, (int, float)) else f"   Risk Score:        {rs}")
            print(f"   Status:            {m.status}")
        elif status["error"]:
            print(f"\n❌ Error: {status['error']}")
        
        print("=" * 40)


# ============================================================================
# Exception Classes
# ============================================================================

class GovernanceError(Exception):
    """Base exception for governance client errors."""
    pass


class GovernanceAPIError(GovernanceError):
    """Error from the governance API."""
    def __init__(self, message: str, response_body: str = ""):
        super().__init__(message)
        self.response_body = response_body


class GovernanceConnectionError(GovernanceError):
    """Error connecting to governance server."""
    pass


# ============================================================================
# CLI Interface (for testing)
# ============================================================================

def main():
    """Simple CLI for testing the client."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kimi Governance Client CLI")
    parser.add_argument("command", choices=["onboard", "update", "metrics", "status", "search"])
    parser.add_argument("--name", help="Agent name for onboard")
    parser.add_argument("--text", "-t", help="Response text for update")
    parser.add_argument("--complexity", "-c", type=float, default=0.5, help="Complexity (0-1)")
    parser.add_argument("--confidence", type=float, default=0.8, help="Confidence (0-1)")
    parser.add_argument("--query", "-q", help="Search query")
    
    args = parser.parse_args()
    
    client = KimiGovernanceClient()
    
    if args.command == "onboard":
        name = args.name or f"kimi_cli_{os.getpid()}"
        identity = client.onboard(name)
        print(f"✅ Onboarded!")
        print(f"   Agent ID: {identity.agent_id}")
        print(f"   UUID: {identity.uuid[:8]}...")
    
    elif args.command == "update":
        if not args.text:
            print("❌ Error: --text required for update")
            sys.exit(1)
        decision, metrics = client.update(args.text, args.complexity, args.confidence)
        print(f"{decision.emoji} Verdict: {decision.action.upper()}")
        print(f"   Reason: {decision.reason}")
        if decision.guidance:
            print(f"   Guidance: {decision.guidance}")
        print(f"\n📊 Metrics:")
        print(f"   Coherence: {metrics.coherence:.3f}")
        print(f"   E: {metrics.E:.3f} | I: {metrics.I:.3f} | S: {metrics.S:.3f}")
    
    elif args.command == "metrics":
        metrics = client.get_metrics()
        print(f"📊 Current Metrics:")
        print(f"   E: {metrics.E:.3f}")
        print(f"   I: {metrics.I:.3f}")
        print(f"   S: {metrics.S:.3f}")
        print(f"   V: {metrics.V:.3f}")
        print(f"   Coherence: {metrics.coherence:.3f}")
    
    elif args.command == "status":
        client.print_status()
    
    elif args.command == "search":
        if not args.query:
            print("❌ Error: --query required for search")
            sys.exit(1)
        results = client.search_knowledge(args.query)
        print(f"🔍 Found {len(results)} results:")
        for r in results[:5]:
            print(f"  • {r.get('discovery_type', 'unknown')}: {r.get('summary', 'no summary')[:60]}...")


if __name__ == "__main__":
    main()
