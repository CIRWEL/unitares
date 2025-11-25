# MCP Handler Architecture

**Date:** 2025-11-25  
**Status:** ✅ Production-ready handler registry pattern

---

## 🎯 Overview

The MCP server uses a **handler registry pattern** for elegant, maintainable tool dispatch. All 29 tools are organized into handler modules by category.

---

## 📁 Structure

```
src/mcp_handlers/
├── __init__.py          # Registry + dispatcher
├── utils.py             # Common utilities (error_response, success_response, require_argument)
├── core.py              # Core governance handlers (3)
├── config.py            # Configuration handlers (2)
├── observability.py     # Observability handlers (4)
├── lifecycle.py         # Lifecycle handlers (7)
├── export.py            # Export handlers (2)
├── knowledge.py         # Knowledge handlers (4)
└── admin.py             # Admin handlers (7)
```

---

## 🔧 How It Works

### Handler Registry

All handlers are registered in `src/mcp_handlers/__init__.py`:

```python
TOOL_HANDLERS = {
    "process_agent_update": handle_process_agent_update,
    "get_governance_metrics": handle_get_governance_metrics,
    # ... 27 more handlers
}
```

### Dispatcher

The `call_tool()` function in `mcp_server_std.py` is now a clean dispatcher:

```python
async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
    from src.mcp_handlers import dispatch_tool
    result = await dispatch_tool(name, arguments)
    if result is not None:
        return result
    # Handle unknown tool
    return [error_response(f"Unknown tool: {name}")]
```

**That's it!** ~30 lines instead of 1,700+.

---

## 📋 Handler Categories

### Core Governance (3 handlers)
- `process_agent_update` - Main governance cycle
- `get_governance_metrics` - Get current state
- `simulate_update` - Dry-run governance cycle

### Configuration (2 handlers)
- `get_thresholds` - View thresholds
- `set_thresholds` - Update thresholds

### Observability (4 handlers)
- `observe_agent` - Observe agent state with pattern analysis
- `compare_agents` - Compare patterns across multiple agents
- `detect_anomalies` - Scan for unusual patterns
- `aggregate_metrics` - Fleet-level health overview

### Lifecycle (7 handlers)
- `list_agents` - List all agents
- `get_agent_metadata` - Get agent metadata
- `update_agent_metadata` - Update tags and notes
- `archive_agent` - Archive agent
- `delete_agent` - Delete agent
- `archive_old_test_agents` - Auto-archive stale agents
- `get_agent_api_key` - Get/generate API key

### Export (2 handlers)
- `get_system_history` - Export time-series history (inline)
- `export_to_file` - Export history to JSON/CSV file

### Knowledge (4 handlers)
- `store_knowledge` - Store knowledge (discovery, pattern, lesson, question)
- `retrieve_knowledge` - Retrieve agent's knowledge record
- `search_knowledge` - Search knowledge across agents
- `list_knowledge` - List all stored knowledge

### Admin (7 handlers)
- `reset_monitor` - Reset agent state
- `get_server_info` - Server version, PID, uptime, health
- `health_check` - System health check
- `check_calibration` - Check calibration status
- `update_calibration_ground_truth` - Update calibration ground truth
- `get_telemetry_metrics` - Comprehensive telemetry metrics
- `list_tools` - Runtime tool introspection

---

## 🛠️ Adding a New Handler

### Step 1: Create Handler Function

```python
# src/mcp_handlers/my_category.py
from typing import Dict, Any, Sequence
from .utils import success_response, error_response

async def handle_my_new_tool(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle my_new_tool"""
    # Your handler logic here
    return success_response({"result": "data"})
```

### Step 2: Register in `__init__.py`

```python
# src/mcp_handlers/__init__.py
from .my_category import handle_my_new_tool

TOOL_HANDLERS = {
    # ... existing handlers
    "my_new_tool": handle_my_new_tool,
}
```

### Step 3: Done!

The handler is now available via MCP. No need to edit `call_tool()`.

---

## 🧪 Testing Handlers

Each handler can be tested independently:

```python
from src.mcp_handlers.core import handle_get_governance_metrics

async def test_handler():
    result = await handle_get_governance_metrics({"agent_id": "test"})
    # Assert result
```

---

## 📊 Benefits

1. **Maintainability** - Easy to find and modify handler code
2. **Testability** - Each handler can be tested independently
3. **Extensibility** - Adding new tools is trivial
4. **Readability** - Clear separation of concerns
5. **No elif chains** - Clean dispatcher pattern

---

## 🔍 Finding Handler Code

**Question:** "Where is the code for `process_agent_update`?"

**Answer:** `src/mcp_handlers/core.py` → `handle_process_agent_update()`

**Question:** "Where is the code for `list_agents`?"

**Answer:** `src/mcp_handlers/lifecycle.py` → `handle_list_agents()`

**Question:** "How do I add a new tool?"

**Answer:** Create handler function, add to registry in `__init__.py`. Done!

---

## 📝 Notes

- **Shared State:** Handlers import from `mcp_server_std` module to access shared state (monitors, agent_metadata, etc.)
- **Error Handling:** Use `error_response()` and `success_response()` utilities
- **Validation:** Use `require_argument()` and `require_agent_id()` utilities
- **No Breaking Changes:** All existing functionality preserved

---

**Status:** ✅ Production-ready, all handlers extracted, zero elif chains

