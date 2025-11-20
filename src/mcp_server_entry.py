#!/usr/bin/env python3
"""
UNITARES Governance MCP Server v1.0 - Entry Point for Cursor MCP

This is the entry point that Cursor's MCP system will call.
It wraps the GovernanceMCPServer to provide MCP protocol compatibility.
"""

import sys
import json
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("Warning: MCP SDK not installed. Using JSON-RPC fallback mode.")
    print("Install with: pip install mcp")

from src.mcp_server import GovernanceMCPServer


if MCP_AVAILABLE:
    # Create MCP server instance
    mcp_server = Server("governance-monitor-v1")
    
    # Create governance server instance
    governance_server = GovernanceMCPServer()
    
    
    @mcp_server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available MCP tools"""
        tools = governance_server.list_tools()['tools']
        
        mcp_tools = []
        for tool in tools:
            # Build input schema
            properties = {}
            for param in tool['parameters']:
                if param == 'agent_id':
                    properties[param] = {"type": "string", "description": f"Agent identifier"}
                elif param == 'parameters':
                    properties[param] = {"type": "array", "items": {"type": "number"}, "description": "Agent parameters (128-dim vector)"}
                elif param == 'ethical_drift':
                    properties[param] = {"type": "array", "items": {"type": "number"}, "description": "Ethical drift signals"}
                elif param == 'response_text':
                    properties[param] = {"type": "string", "description": "Agent response text"}
                elif param == 'complexity':
                    properties[param] = {"type": "number", "description": "Task complexity (0-1)"}
                elif param == 'format':
                    properties[param] = {"type": "string", "enum": ["json", "csv"], "description": "Output format"}
                else:
                    properties[param] = {"type": "string"}
            
            mcp_tools.append(
                Tool(
                    name=tool['name'],
                    description=tool['description'],
                    inputSchema={
                        "type": "object",
                        "properties": properties,
                        "required": ["agent_id"] if "agent_id" in tool['parameters'] else []
                    }
                )
            )
        
        return mcp_tools
    
    
    @mcp_server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle tool calls"""
        try:
            # Convert MCP tool call to our server format
            request = {
                'tool': name,
                'params': arguments
            }
            
            result = governance_server.handle_request(request)
            
            # Convert result to MCP format
            if result.get('success'):
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            else:
                return [TextContent(
                    type="text",
                    text=f"Error: {result.get('error', 'Unknown error')}"
                )]
        except Exception as e:
            import traceback
            return [TextContent(
                type="text",
                text=f"Exception: {str(e)}\n{traceback.format_exc()}"
            )]
    
    
    async def main():
        """Main entry point for MCP server"""
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options()
            )
    
    
    if __name__ == "__main__":
        asyncio.run(main())

else:
    # Fallback: Run in JSON-RPC mode
    def main():
        """Fallback: Run in JSON-RPC mode"""
        server = GovernanceMCPServer()
        if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
            server.run_interactive()
        else:
            print("[UNITARES MCP v1.0] Server ready (JSON-RPC mode)")
            print("[UNITARES MCP v1.0] Use --interactive for testing")
            print("[UNITARES MCP v1.0] Install MCP SDK for full protocol support: pip install mcp")
    
    if __name__ == "__main__":
        main()
