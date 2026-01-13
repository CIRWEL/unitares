# Force Server Module Reload

**Created:** January 1, 2026  
**Status:** 🔧 Server needs to reload modules to see SEE ALSO enhancements

---

## Problem

**Server process:**
- Started: 17:31:55
- File modified: 18:32:54
- **Server using stale cached modules**

**Evidence:**
- ✅ Local Python test: SEE ALSO present (3275 chars)
- ❌ Server HTTP response: SEE ALSO missing (2706 chars)
- ✅ Code is correct
- ❌ Server process has old code cached

---

## Solution: Force Module Reload

### Option 1: Full Server Restart (Recommended)

```bash
# Stop server
kill 96840  # or use your process manager

# Clear Python cache
find . -name "*.pyc" -path "*/__pycache__/*" -delete
find . -name "__pycache__" -type d -exec rm -r {} + 2>/dev/null

# Restart server
python3 src/mcp_server_sse.py --port 8765
```

### Option 2: Hot Reload (If Supported)

Some servers support hot reload. Check if your server has this feature.

### Option 3: Add Reload Endpoint

Add a debug endpoint to force module reload:

```python
@app.post("/debug/reload_modules")
async def reload_modules():
    import importlib
    import sys
    
    if 'src.tool_schemas' in sys.modules:
        importlib.reload(sys.modules['src.tool_schemas'])
    
    return {"status": "reloaded"}
```

---

## Verification

After restart, test:

```bash
curl -X POST http://127.0.0.1:8765/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "describe_tool",
    "arguments": {
      "tool_name": "get_governance_metrics",
      "include_full_description": true,
      "lite": false
    }
  }' | jq '.result.tool.description' | grep -c "SEE ALSO"
```

Should return: `1` (SEE ALSO found)

---

## Why This Happens

Python caches imported modules in `sys.modules`. When a file is modified:
1. File on disk updates ✅
2. `.pyc` file updates ✅  
3. **But `sys.modules` still has old code** ❌

Server restart forces Python to reload from disk.

---

**Status:** 🔧 Server restart required  
**Action:** Restart server to load SEE ALSO enhancements

