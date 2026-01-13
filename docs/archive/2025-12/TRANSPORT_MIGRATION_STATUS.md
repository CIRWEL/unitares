# Transport Migration Status: SSE → Streamable HTTP

**Date:** December 20, 2025  
**Status:** Dual Transport (SSE + Streamable HTTP)  
**MCP Spec:** 1.24.0+

---

## Overview

The system now supports **two transports simultaneously**:

1. **SSE (Server-Sent Events)** - `/sse` endpoint
   - Status: **Legacy, still operational**
   - Used by: Cursor, Claude Desktop (older versions)
   - Stability: Stable, but marked for eventual deprecation

2. **Streamable HTTP** - `/mcp` endpoint  
   - Status: **New, preferred**
   - Used by: Cursor 0.43+, Claude Desktop (newer versions)
   - Features: Resumability, bidirectional streaming, MCP 1.24.0+ spec compliant

---

## Key Changes

### 1. Dual Transport Support

**Location:** `src/mcp_server_sse.py` (lines 1778-1796, 2482-2534)

```python
# SSE transport (legacy, still works)
app = mcp.sse_app()  # /sse endpoint

# Streamable HTTP transport (new, preferred)
_streamable_session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=False,  # Use SSE streams (default, more efficient)
    stateless=False,      # Track sessions for resumability
)
# /mcp endpoint registered
```

**Both transports:**
- ✅ Share the same tool handlers
- ✅ Use the same identity system
- ✅ Persist to the same database
- ✅ Support session-based identity

### 2. Session-Based Identity (MCP 1.24.0+)

**Location:** `src/mcp_handlers/__init__.py` (lines 183-195)

**What changed:**
- Tools can now auto-inject `agent_id` from session if not provided
- Uses `MCP-Session-Id` header (Streamable HTTP) or `client_session_id` (SSE)

**Before:**
```python
# Required explicit agent_id
process_agent_update(agent_id="my_agent", ...)
```

**After:**
```python
# Auto-injected from session if bound
process_agent_update(...)  # agent_id comes from session
```

**Session ID Resolution Priority:**
1. `MCP-Session-Id` header (Streamable HTTP - MCP 1.24.0+ spec)
2. `client_session_id` from arguments (SSE transport)
3. FastMCP `client_id` (fallback)
4. Stable per-process key (stdio fallback)

**Location:** `src/mcp_server_sse.py` (lines 483-522)

### 3. Identity System Updates

**Location:** `src/mcp_handlers/identity.py`

**New Functions:**
- `get_bound_agent_id(arguments=arguments)` - Gets agent_id from session
- `_session_id_from_ctx(ctx)` - Extracts session ID from MCP context

**Session Key Resolution:**
```python
def _get_session_key(arguments, session_id):
    # Priority:
    # 1. explicit session_id argument
    # 2. arguments["client_session_id"] (injected by SSE wrappers)
    # 3. fallback to stable per-process key (stdio/single-user)
```

---

## Current Status

### SSE Transport (`/sse`)
- ✅ **Still operational** - No breaking changes
- ✅ **Recommended for Cursor** - Most stable option currently
- ⚠️ **Marked as "legacy"** - Will eventually be deprecated
- 📍 **Used by:** Cursor (all versions), Claude Desktop (older)
- 🔄 **Migration path:** Switch to `/mcp` endpoint when Cursor fully supports it

### Streamable HTTP Transport (`/mcp`)
- ✅ **New, preferred** - MCP 1.24.0+ compliant
- ✅ **Resumability** - Sessions can resume after disconnect
- ✅ **Bidirectional streaming** - More efficient
- ⚠️ **Cursor support:** According to docs, Cursor supports it, but may need Cursor 0.43+
- 📍 **Used by:** Claude Desktop (newer), some Cursor versions
- 🎯 **Future:** Will become the primary transport

### ⚠️ Important: Streamable HTTP ≠ Regular HTTP

**What you may have tried before:**
- Regular HTTP REST API (like `/v1/tools/call`)
- This is NOT the same as Streamable HTTP

**What Streamable HTTP is:**
- MCP protocol transport (like SSE, but newer)
- Uses `/mcp` endpoint
- MCP 1.24.0+ spec compliant
- Different protocol than regular HTTP REST

**For Cursor:**
- **SSE (`/sse`)** - ✅ **Recommended** - Most stable, works reliably
- **Streamable HTTP (`/mcp`)** - ⚠️ **Try if you want** - May work in Cursor 0.43+, but SSE is safer

---

## Migration Guide

### For Cursor Users

**Current (SSE - Recommended):**
```json
{
  "mcpServers": {
    "governance": {
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

**Optional (Streamable HTTP - Try if you want):**
```json
{
  "mcpServers": {
    "governance": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

**Recommendation:**
- ✅ **Stick with SSE (`/sse`)** for now - it's stable and works reliably
- ⚠️ **Try Streamable HTTP (`/mcp`)** if you're on Cursor 0.43+ and want to experiment
- 🔄 **If `/mcp` doesn't work**, just switch back to `/sse` - no problem!

**Benefits of Streamable HTTP (if it works):**
- Session resumability (survives disconnects)
- MCP 1.24.0+ spec compliance
- Better error handling
- More efficient streaming

**Why SSE is still recommended:**
- ✅ Proven to work with Cursor
- ✅ Stable and reliable
- ✅ No version requirements
- ✅ All features work the same

### For Tool Handlers

**No changes required** - Both transports use the same handlers via `dispatch_tool()`.

**Session-based identity is automatic:**
```python
# Old way (still works)
process_agent_update(agent_id="my_agent", ...)

# New way (auto-injected from session)
process_agent_update(...)  # agent_id from session if bound
```

---

## Implementation Details

### Streamable HTTP Session Manager

**Location:** `src/mcp_server_sse.py` (lines 1785-1796)

```python
_streamable_session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=False,  # Use SSE streams (more efficient)
    stateless=False,      # Track sessions for resumability
)
```

**Features:**
- Session tracking for resumability
- Bidirectional streaming
- MCP 1.24.0+ spec compliance
- Automatic session ID generation

### Session ID Extraction

**Location:** `src/mcp_server_sse.py` (lines 483-522)

```python
def _session_id_from_ctx(ctx):
    # Priority 1: MCP-Session-Id header (Streamable HTTP)
    # Priority 2: FastMCP client_id
    # Priority 3: governance_client_id from middleware
    # Priority 4: None (triggers fallback)
```

### Auto-Injection in dispatch_tool

**Location:** `src/mcp_handlers/__init__.py` (lines 183-195)

```python
# If agent_id not provided but session is bound, inject it
if "agent_id" not in arguments or not arguments.get("agent_id"):
    bound_id = get_bound_agent_id(arguments=arguments)
    if bound_id:
        arguments["agent_id"] = bound_id
```

---

## Deprecation Timeline

**Current (Dec 2025):**
- ✅ Both transports operational
- ✅ SSE marked as "legacy"
- ✅ Streamable HTTP preferred

**Future (TBD):**
- ⚠️ SSE will be deprecated (no date set)
- 🎯 Streamable HTTP becomes primary
- 📋 Migration guide for clients

**No immediate action required** - SSE will continue working for the foreseeable future.

---

## Testing

**SSE Endpoint:**
```bash
curl http://127.0.0.1:8765/sse?probe=true
```

**Streamable HTTP Endpoint:**
```bash
curl http://127.0.0.1:8765/mcp
```

**Health Check (both):**
```bash
curl http://127.0.0.1:8765/health
```

---

## References

- **MCP Spec 1.24.0+:** Streamable HTTP transport
- **FastMCP:** SSE and Streamable HTTP support
- **Cursor 0.43+:** Streamable HTTP client support
- **Claude Desktop:** Streamable HTTP support (newer versions)

---

## Summary

✅ **SSE is still operational** - No breaking changes  
✅ **Streamable HTTP is new and preferred** - MCP 1.24.0+ compliant  
✅ **Session-based identity works in both** - Auto-injection enabled  
⚠️ **SSE marked as "legacy"** - Will eventually be deprecated (no date)  
🎯 **Migration path clear** - Switch to `/mcp` endpoint when ready  

**Current recommendation for Cursor:**
- ✅ **Use SSE (`/sse`)** - It's stable, proven, and works reliably
- ⚠️ **Streamable HTTP (`/mcp`)** may work in Cursor 0.43+, but SSE is the safe choice
- 🔄 **If you tried regular HTTP before and it didn't work** - that's different! Streamable HTTP is a specific MCP protocol transport, not regular REST HTTP

**Bottom line:** SSE is still your best bet for Cursor. Streamable HTTP is available if you want to experiment, but SSE will continue working.

