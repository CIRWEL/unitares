# Implicit Identity Binding for MCP Clients

## Problem

MCP clients (Claude Code, Gemini CLI, Cursor) don't maintain consistent session identity across requests. Each tool call can get a different agent UUID, causing:
- Identity fragmentation (multiple UUIDs for same client)
- Lost state/name between calls
- Need for manual `client_session_id` passing (bad UX)

## Current Behavior

```
Call 1: identity() → UUID ae330c92...  (set name: "Claude_Opus_CLI")
Call 2: process_agent_update() → UUID 3a3057b8...  (different! name lost)
```

## Root Cause

1. **Stateless mode**: Server runs `stateless=True` for compatibility
2. **No session header**: Clients don't send `mcp-session-id` header consistently
3. **No connection affinity**: HTTP requests are independent, no sticky session

## Attempted Fix (partial)

Added contextvar capture of `mcp-session-id` header in ASGI wrapper:
- `src/mcp_handlers/context.py`: Added `_mcp_session_id` contextvar
- `src/mcp_server_sse.py`: Capture header in `streamable_mcp_asgi()`
- `_session_id_from_ctx()`: Use MCP session ID as primary identifier

**Result**: Works within single request, breaks across requests.

## Potential Solutions

### Option A: Client-side session persistence
MCP clients store session ID from first response, echo in subsequent requests.
- Requires client changes (Claude Code, Cursor, etc.)
- Most protocol-compliant

### Option B: Connection-based identity (WebSocket/SSE)
For persistent connections, use connection ID as session key.
- Works for SSE transport
- Doesn't help HTTP streamable

### Option C: IP + User-Agent fingerprinting
Derive session from client fingerprint.
- Privacy concerns
- Breaks with proxies/NAT

### Option D: Cookie-based sessions
Set session cookie on first request, browser echoes automatically.
- Only works for browser-based clients
- Doesn't help CLI tools

### Option E: Transport-level session injection
Modify MCP SDK to inject session ID at transport layer.
- Requires SDK changes or monkey-patching
- Most invasive

## Recommended Approach

**Hybrid: Option A + B** ✅ **SERVER-SIDE READY**

1. For SSE/WebSocket: Use connection ID (already works) ✅
2. For HTTP streamable:
   - ✅ Server generates session ID on first request
   - ✅ Server returns it in response header (`X-Session-ID`) AND in tool response body (`agent_signature.client_session_id` or `⚠️_session` field)
   - ⏳ **CLIENT NEEDS TO:** Extract session ID from first response and echo in subsequent requests via `X-Session-ID` header
   - ✅ Fall back to fingerprinting if client doesn't echo (current behavior)

**Implementation Status:**
- ✅ Server-side: Complete (see `src/mcp_server_sse.py` lines 1669-1695, 1856-1858)
- ⏳ Client-side: Needs implementation in Cursor/auto MCP client

**Client Implementation:**
```python
# First request (no session ID)
response = mcp_client.call_tool("onboard", {})
session_id = response["result"]["agent_signature"]["client_session_id"]
# Or: session_id = response["result"]["agent_signature"]["⚠️_session"].split("=")[1]

# Subsequent requests (echo session ID)
response = mcp_client.call_tool("process_agent_update", {...}, headers={"X-Session-ID": session_id})
```

**Key Insight:** Server-side is ready. Client behavior needs to change (echo the session ID back).

## Files Changed

- `src/mcp_handlers/context.py` - MCP session contextvar
- `src/mcp_server_sse.py` - ASGI wrapper capture, `_session_id_from_ctx()`

## Testing

```bash
# Check if identity persists
curl -X POST https://unitares.ngrok.io/mcp/ ... # Call 1
curl -X POST https://unitares.ngrok.io/mcp/ ... # Call 2 (same UUID?)
```

## Priority

Medium - Workaround exists (manual `client_session_id`), but impacts UX significantly.
