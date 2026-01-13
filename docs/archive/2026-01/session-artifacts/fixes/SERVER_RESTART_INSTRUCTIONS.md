# Server Restart Instructions

**Created:** January 1, 2026  
**Status:** Server needs restart to load SEE ALSO enhancements

---

## Current Status

- ✅ Code has SEE ALSO sections (21 tools)
- ✅ File modified: 18:32:54
- ❌ Server process still using old code (PID 96840, started 17:31:55)

---

## Manual Restart Steps

1. **Stop the current server:**
   ```bash
   kill -9 96840
   # Or find the PID:
   ps aux | grep mcp_server_sse.py
   ```

2. **Clear Python cache (optional but recommended):**
   ```bash
   find . -name "*.pyc" -path "*/__pycache__/*tool_schemas*" -delete
   ```

3. **Start the server:**
   ```bash
   cd /Users/cirwel/projects/governance-mcp-v1
   python3 src/mcp_server_sse.py --port 8765
   ```

4. **Verify SEE ALSO sections are loaded:**
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
   
   Should return: `1`

---

## Why Restart is Needed

Python caches imported modules in `sys.modules`. When files are modified:
- ✅ File on disk updates
- ✅ `.pyc` file updates  
- ❌ **But `sys.modules` still has old code**

Server restart forces Python to reload from disk.

---

**Status:** ⚠️ Manual restart required  
**Action:** Stop server, clear cache, restart

