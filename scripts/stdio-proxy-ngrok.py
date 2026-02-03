#!/usr/bin/env python3
"""
Stdio-to-SSE proxy with Basic Auth support for ngrok tunnels.

This script acts as a stdio MCP server that forwards all requests to
a remote SSE server, handling Basic Auth properly (which mcp-remote
struggles with due to EventSource limitations).

Usage:
    python stdio-proxy-ngrok.py <sse_url> <username> <password>

Example:
    python stdio-proxy-ngrok.py https://unitares.ngrok.io/sse unitares 8QF6L8Ui0pZFiHGQ
"""

import sys
import asyncio
import json
import base64
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession
except ImportError as e:
    print(f"Error: MCP SDK not available: {e}", file=sys.stderr)
    sys.exit(1)


def get_auth_header(username: str, password: str) -> str:
    """Generate Basic Auth header value."""
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


async def create_auth_client(username: str, password: str) -> httpx.AsyncClient:
    """Create an httpx client with Basic Auth."""
    auth_header = get_auth_header(username, password)
    return httpx.AsyncClient(
        http2=False,  # SSE works better with HTTP/1.1
        timeout=30.0,
        headers={"Authorization": auth_header},
    )


class ProxyServer:
    def __init__(self, sse_url: str, username: str, password: str):
        self.sse_url = sse_url
        self.username = username
        self.password = password
        self.server = Server("stdio-proxy")
        self._remote_tools: list[Tool] = []
        self._http_client: httpx.AsyncClient | None = None

        # Register handlers
        self.server.list_tools()(self.list_tools)
        self.server.call_tool()(self.call_tool)

    async def _ensure_client(self):
        if self._http_client is None:
            self._http_client = await create_auth_client(self.username, self.password)
        return self._http_client

    async def _fetch_remote_tools(self) -> list[Tool]:
        """Fetch tools from remote SSE server."""
        def http1_factory(*args, **kwargs):
            auth_header = get_auth_header(self.username, self.password)
            return httpx.AsyncClient(
                http2=False,
                timeout=30.0,
                headers={"Authorization": auth_header},
            )

        try:
            async with sse_client(self.sse_url, httpx_client_factory=http1_factory) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return result.tools
        except Exception as e:
            print(f"Error fetching remote tools: {e}", file=sys.stderr)
            return []

    async def _call_remote_tool(self, name: str, arguments: dict) -> list[TextContent]:
        """Call a tool on the remote SSE server."""
        def http1_factory(*args, **kwargs):
            auth_header = get_auth_header(self.username, self.password)
            return httpx.AsyncClient(
                http2=False,
                timeout=60.0,  # Longer timeout for tool calls
                headers={"Authorization": auth_header},
            )

        try:
            async with sse_client(self.sse_url, httpx_client_factory=http1_factory) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    # Convert result content to TextContent
                    contents = []
                    for item in result.content:
                        if hasattr(item, 'text'):
                            contents.append(TextContent(type="text", text=item.text))
                        else:
                            contents.append(TextContent(type="text", text=str(item)))
                    return contents
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Remote tool call failed: {e}",
                "tool": name,
                "sse_url": self.sse_url,
            }, indent=2))]

    async def list_tools(self) -> list[Tool]:
        """List tools from remote server."""
        if not self._remote_tools:
            self._remote_tools = await self._fetch_remote_tools()
        return self._remote_tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> list[TextContent]:
        """Forward tool call to remote server."""
        return await self._call_remote_tool(name, arguments or {})

    async def run(self):
        """Run the stdio server."""
        async with stdio_server() as (read, write):
            await self.server.run(read, write, self.server.create_initialization_options())


async def main():
    if len(sys.argv) < 4:
        print("Usage: stdio-proxy-ngrok.py <sse_url> <username> <password>", file=sys.stderr)
        print("Example: stdio-proxy-ngrok.py https://unitares.ngrok.io/sse unitares mypassword", file=sys.stderr)
        sys.exit(1)

    sse_url = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]

    print(f"Starting stdio proxy to {sse_url}", file=sys.stderr)

    proxy = ProxyServer(sse_url, username, password)
    await proxy.run()


if __name__ == "__main__":
    asyncio.run(main())
