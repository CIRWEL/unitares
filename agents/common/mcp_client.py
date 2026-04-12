"""Shared MCP client transport for UNITARES resident agents."""

from contextlib import asynccontextmanager

import httpx


def mcp_connect(url: str):
    """Auto-detect MCP transport: /mcp -> Streamable HTTP, otherwise SSE."""
    if "/mcp" in url:
        from mcp.client.streamable_http import streamable_http_client

        @asynccontextmanager
        async def _connect():
            async with httpx.AsyncClient(http2=False, timeout=30) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                    yield read, write

        return _connect()
    else:
        from mcp.client.sse import sse_client

        return sse_client(url)
