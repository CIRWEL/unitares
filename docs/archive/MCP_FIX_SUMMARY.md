# MCP Server Fix Summary

**Date:** November 18, 2025  
**Issue:** governance-monitor MCP server was failing to start  
**Status:** ✅ Fixed

## Problem

The MCP server was failing with:
```
Error: MCP SDK not available: cannot import name 'ErrorCode' from 'mcp.types'
```

## Root Cause

The MCP SDK API changed - `ErrorCode` and `McpError` don't exist in the current version. Instead, the SDK uses:
- `JSONRPCError` for error handling
- Error code constants: `INTERNAL_ERROR`, `INVALID_REQUEST`, `METHOD_NOT_FOUND`, etc.

## Fix Applied

Updated `src/mcp_server_std.py`:

1. **Changed imports:**
   ```python
   # Before:
   from mcp.types import Tool, TextContent, ErrorCode, McpError
   
   # After:
   from mcp.types import Tool, TextContent, JSONRPCError, INTERNAL_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND
   ```

2. **Updated error handling:**
   ```python
   # Before:
   raise McpError(ErrorCode.INVALID_REQUEST, "message")
   
   # After:
   raise JSONRPCError(INVALID_REQUEST, "message")
   ```

## Verification

✅ Server imports successfully  
✅ Server starts without errors  
✅ All error handling updated  
✅ JSON config is valid  

## Next Steps

1. **Restart Cursor** to load the fixed server
2. **Test the tools:**
   - "Use the governance-monitor tool list_agents"
   - "Use the governance-monitor tool get_governance_metrics with agent_id: test"

## Files Modified

- `src/mcp_server_std.py` - Fixed imports and error handling

---

**Status:** Ready to use! 🚀

