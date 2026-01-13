# Server Stability Guide

**Created:** January 1, 2026  
**Status:** Server running, tools loading correctly ✅

---

## Current Status

**Server Health:**
- ✅ Server running (PID: 96840)
- ✅ Health endpoint responding
- ✅ 51 tools registered
- ✅ `call_model` tool registered
- ✅ All imports working
- ✅ No syntax errors

---

## Feature Addition Checklist

**Before adding new features:**

1. ✅ **Test imports** - Verify module imports cleanly
2. ✅ **Test registration** - Verify tool appears in registry
3. ✅ **Test server startup** - Verify server starts without errors
4. ✅ **Test health endpoint** - Verify `/health` responds
5. ✅ **Test tool listing** - Verify `/v1/tools` includes new tool
6. ⏳ **Test tool execution** - Verify tool works end-to-end
7. ⏳ **Restart server** - After changes, restart to load new code

---

## Safe Feature Addition Pattern

**Step 1: Create handler module**

```python
# src/mcp_handlers/new_feature.py
from mcp.types import TextContent
from typing import Dict, Any, Sequence
from .decorators import mcp_tool
from .utils import require_argument, error_response, success_response

@mcp_tool("new_tool", timeout=30.0)
async def handle_new_tool(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    # Implementation
    pass
```

**Step 2: Register in `__init__.py`**

```python
# src/mcp_handlers/__init__.py
from .new_feature import handle_new_tool
# Tool auto-registers via @mcp_tool decorator
```

**Step 3: Add schema**

```python
# src/tool_schemas.py
"new_tool": {
    "name": "new_tool",
    "description": "...",
    "inputSchema": {...}
}
```

**Step 4: Test before restart**

```bash
# Test imports
python3 -c "from src.mcp_handlers.new_feature import handle_new_tool"

# Test registration
python3 -c "from src.mcp_handlers import TOOL_HANDLERS; print('new_tool' in TOOL_HANDLERS)"
```

**Step 5: Restart server**

```bash
# Stop
pkill -f mcp_server_sse.py

# Start
cd /Users/cirwel/projects/governance-mcp-v1
python3 src/mcp_server_sse.py --port 8765 &
```

---

## Common Issues

### Issue: Server won't start

**Symptoms:**
- Server exits immediately
- Import errors in logs
- Syntax errors

**Fix:**
1. Check syntax: `python3 -m py_compile src/mcp_server_sse.py`
2. Check imports: `python3 -c "from src.mcp_handlers import *"`
3. Check for missing dependencies: `pip install -r requirements.txt`
4. Check logs: Look for error messages

---

### Issue: Tools not loading in Cursor

**Symptoms:**
- Server running but Cursor shows no tools
- MCP connection error

**Fix:**
1. Verify server running: `curl http://127.0.0.1:8765/health`
2. Check Cursor config: `~/Library/Application Support/Cursor/User/globalStorage/mcp.json`
3. Verify endpoint: Should be `http://127.0.0.1:8765/sse`
4. Restart Cursor: Quit completely (Cmd+Q), wait 5s, reopen

---

### Issue: New tool not appearing

**Symptoms:**
- Tool handler exists but not in tool list
- Tool call returns "not found"

**Fix:**
1. Verify registration: `python3 -c "from src.mcp_handlers import TOOL_HANDLERS; print('tool_name' in TOOL_HANDLERS)"`
2. Check decorator: Ensure `@mcp_tool("tool_name")` is present
3. Check import: Ensure handler imported in `__init__.py`
4. Restart server: Changes require restart

---

## Dependency Management

**Required dependencies:**
- `openai` - For model inference (optional, graceful fallback)
- `redis` - For session storage (optional, graceful fallback)
- `psycopg2` - For PostgreSQL (required)

**Optional dependencies:**
- `ollama` - For local model inference
- `huggingface` - For HF Inference Providers

**Graceful degradation:**
- Missing `openai` → `call_model` returns error with install instructions
- Missing `redis` → Falls back to PostgreSQL-only
- Missing optional deps → Features disabled, server still runs

---

## Testing Workflow

**Before committing:**

```bash
# 1. Syntax check
python3 -m py_compile src/mcp_server_sse.py

# 2. Import check
python3 -c "from src.mcp_handlers import *"

# 3. Tool registration check
python3 -c "from src.mcp_handlers import TOOL_HANDLERS; print(len(TOOL_HANDLERS))"

# 4. Start server
python3 src/mcp_server_sse.py --port 8765 &

# 5. Health check
curl http://127.0.0.1:8765/health

# 6. Tool list check
curl http://127.0.0.1:8765/v1/tools | python3 -m json.tool | grep -i "new_tool"

# 7. Test tool call
curl -X POST http://127.0.0.1:8765/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "new_tool", "arguments": {}}'
```

---

## Server Restart Procedure

**Quick restart:**

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Stop
pkill -f mcp_server_sse.py

# Wait for cleanup
sleep 2

# Start
python3 src/mcp_server_sse.py --port 8765 &

# Verify
sleep 1
curl http://127.0.0.1:8765/health
```

**With environment variables:**

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Load env vars
source .env 2>/dev/null || true

# Stop
pkill -f mcp_server_sse.py

# Start
python3 src/mcp_server_sse.py --port 8765 &
```

---

## Monitoring

**Check server status:**

```bash
# Process check
ps aux | grep mcp_server_sse.py | grep -v grep

# Health check
curl http://127.0.0.1:8765/health

# Tool count
curl http://127.0.0.1:8765/v1/tools | python3 -m json.tool | grep -c '"name"'
```

---

## Best Practices

1. **Test before restart** - Verify imports/registration work
2. **One feature at a time** - Easier to debug issues
3. **Graceful degradation** - Missing deps shouldn't break server
4. **Clear error messages** - Help users self-diagnose
5. **Document changes** - Update guides when adding features

---

## Current Feature Status

**Recently added:**
- ✅ `call_model` - Model inference tool (Jan 2026)
- ✅ Error taxonomy - Standardized error responses
- ✅ Identity v2 - Simplified identity management

**All features:**
- ✅ 51 tools registered
- ✅ Server stable
- ✅ Health checks passing

---

**Status:** Server stable, all features working  
**Action:** Continue adding features with testing checklist

