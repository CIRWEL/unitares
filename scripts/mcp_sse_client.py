#!/usr/bin/env python3
"""
MCP SSE Client for Claude Code CLI
Connects to the governance MCP SSE server for unified governance feedback
"""

import asyncio
import sys
from typing import Dict, Any, Optional
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession


class GovernanceMCPClient:
    """Client for connecting to governance MCP server via SSE"""

    def __init__(self, url: str = "http://127.0.0.1:8767/sse"):
        self.url = url
        self.session: Optional[ClientSession] = None
        self._sse_context = None
        self._session_context = None

    async def __aenter__(self):
        """Async context manager entry"""
        # Enter SSE client context
        self._sse_context = sse_client(self.url)
        read, write = await self._sse_context.__aenter__()

        # Enter session context
        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()

        # Initialize session
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with error suppression"""
        # Suppress async cleanup errors that don't affect functionality
        # These are typically Python 3.14 + MCP library interaction issues
        try:
            if self._session_context:
                await self._session_context.__aexit__(exc_type, exc_val, exc_tb)
        except (RuntimeError, KeyError, Exception) as e:
            # Suppress async cleanup errors - they don't affect the actual result
            # Common errors: "Attempted to exit cancel scope in different task"
            #                KeyError during generator cleanup
            import sys
            if "--debug-mcp" in sys.argv:
                print(f"Warning: Async cleanup error (suppressed): {e}", file=sys.stderr)
            pass

        try:
            if self._sse_context:
                await self._sse_context.__aexit__(exc_type, exc_val, exc_tb)
        except (RuntimeError, KeyError, Exception) as e:
            import sys
            if "--debug-mcp" in sys.argv:
                print(f"Warning: SSE cleanup error (suppressed): {e}", file=sys.stderr)
            pass

        # Don't propagate the original exception if we're only suppressing cleanup errors
        return False

    async def list_tools(self) -> list:
        """List all available tools on the server"""
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the server"""
        result = await self.session.call_tool(tool_name, arguments)
        return result

    async def process_agent_update(
        self,
        agent_id: str,
        response_text: str,
        complexity: float,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process an agent update via MCP

        This uses the canonical MCP handler interpretation,
        providing a single source of truth for governance feedback.
        """
        args = {
            "agent_id": agent_id,
            "response_text": response_text,
            "complexity": complexity
        }
        if api_key:
            args["api_key"] = api_key

        result = await self.call_tool("process_agent_update", args)

        # Parse the result - MCP returns TextContent
        if hasattr(result, 'content'):
            # Extract content from MCP response
            import json
            for content in result.content:
                if hasattr(content, 'text'):
                    return json.loads(content.text)
        return result

    async def get_governance_metrics(self, agent_id: str) -> Dict[str, Any]:
        """Get current governance metrics for an agent"""
        result = await self.call_tool("get_governance_metrics", {"agent_id": agent_id})

        if hasattr(result, 'content'):
            import json
            for content in result.content:
                if hasattr(content, 'text'):
                    return json.loads(content.text)
        return result


async def test_client():
    """Test the MCP client"""
    print("Testing MCP SSE Client...")
    print(f"Connecting to SSE server...")

    async with GovernanceMCPClient() as client:
        print("✅ Connected!")

        # List tools
        tools = await client.list_tools()
        print(f"✅ Found {len(tools)} tools")

        # Test process_agent_update
        print("\nTesting process_agent_update...")
        result = await client.process_agent_update(
            agent_id="mcp_client_test",
            response_text="Testing MCP SSE client from Claude Code",
            complexity=0.5
        )

        print("\n" + "="*60)
        print("GOVERNANCE DECISION (via MCP)")
        print("="*60)
        print(f"Action: {result['decision']['action']}")
        print(f"Reason: {result['decision']['reason']}")
        if result['decision'].get('guidance'):
            print(f"Guidance: {result['decision']['guidance']}")

        print("\nMETRICS:")
        for key, value in result['metrics'].items():
            if isinstance(value, float):
                print(f"  {key}: {value:.3f}")
            else:
                print(f"  {key}: {value}")

        print("\n✅ MCP client working!")


if __name__ == "__main__":
    asyncio.run(test_client())
