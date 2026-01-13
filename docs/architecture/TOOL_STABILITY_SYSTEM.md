# Tool Stability & Migration System

**Date:** December 20, 2025  
**Purpose:** Reduce friction from constant tool churn (WIP, adding/deleting/consolidation)

---

## Problem

Tools are constantly changing (WIP), causing friction:
- Tools get renamed → old code breaks
- Tools get consolidated → unclear what to use
- Tools get deprecated → no clear migration path
- Inconsistent deprecation markers → confusion

## Solution

A **Tool Stability & Migration System** that:

1. **Stability Tiers** - Mark tools as stable/beta/experimental
2. **Automatic Aliases** - Old tool names still work transparently
3. **Migration Helpers** - Clear guidance on what to use instead
4. **Single Source of Truth** - Unified deprecation workflow

---

## Components

### 1. Tool Stability Tiers

**Location:** `src/mcp_handlers/tool_stability.py`

```python
class ToolStability(Enum):
    STABLE = "stable"      # Production-ready, won't change
    BETA = "beta"          # Mostly stable, minor changes possible
    EXPERIMENTAL = "experimental"  # WIP, may change/break
```

**Usage:**
- `get_tool_stability(tool_name)` → Returns stability tier
- Shown in `list_tools` output as `"stability": "stable"`

**Benefits:**
- Users know what to expect
- Experimental tools clearly marked
- Stable tools = safe to use in production

### 2. Automatic Tool Aliases

**Location:** `src/mcp_handlers/tool_stability.py` → `_TOOL_ALIASES`

**How it works:**
- When tools are renamed/consolidated, add alias mapping
- Old tool names automatically resolve to new names
- **No breaking changes** - old code still works

**Example:**
```python
"who_am_i": ToolAlias(
    old_name="who_am_i",
    new_name="recall_identity",
    reason="consolidated",
    migration_note="Use recall_identity() instead"
)
```

**Benefits:**
- Backward compatibility
- Gradual migration (old names work, new names preferred)
- Zero friction for users

### 3. Migration Helper Tool

**Tool:** `migrate_tool(tool_name="old_tool")`

**Returns:**
- Status (alias/deprecated/active)
- Recommended replacement
- Migration note
- Usage examples

**Example:**
```json
{
  "old_tool": "who_am_i",
  "status": "alias",
  "actual_tool": "recall_identity",
  "migration_note": "Use recall_identity() instead - same functionality",
  "recommendation": "Use 'recall_identity' instead - Use recall_identity() instead - same functionality"
}
```

**Benefits:**
- Clear migration path
- No guessing what to use
- Self-service migration

### 4. Unified Deprecation Workflow

**Single Source of Truth:**
1. **Decorator:** `@mcp_tool(..., deprecated=True, superseded_by="new_tool")`
2. **Alias Registry:** `tool_stability.py` → `_TOOL_ALIASES`
3. **Tier Registry:** `admin.py` → `TOOL_TIERS["deprecated"]`

**All three are checked:**
- Alias resolution (highest priority - transparent redirect)
- Decorator deprecation (tool-level metadata)
- Tier deprecation (categorization)

**Benefits:**
- Consistent behavior
- No conflicts
- Clear migration paths

---

## Usage Examples

### For Users

**1. Check if tool is deprecated:**
```python
migrate_tool(tool_name="who_am_i")
# Returns: Use 'recall_identity' instead
```

**2. See tool stability:**
```python
list_tools()
# Shows: "stability": "stable" for each tool
```

**3. Old tool names still work:**
```python
who_am_i()  # Automatically redirects to recall_identity()
# Logs: "Tool alias used: 'who_am_i' → 'recall_identity'"
```

### For Developers

**1. Add new alias:**
```python
# In tool_stability.py
_TOOL_ALIASES["old_name"] = ToolAlias(
    old_name="old_name",
    new_name="new_name",
    reason="consolidated",
    migration_note="Use new_name() instead"
)
```

**2. Mark tool stability:**
```python
# In tool_stability.py
_TOOL_STABILITY["new_tool"] = ToolStability.STABLE
```

**3. Deprecate tool:**
```python
# In handler file
@mcp_tool("old_tool", deprecated=True, superseded_by="new_tool")
async def handle_old_tool(...):
    ...
```

---

## Current Aliases

### Identity Tools
- `who_am_i` → `recall_identity`
- `authenticate` → `hello`
- `session` → `hello`
- `quick_start` → `hello`
- `get_agent_api_key` → `hello`

### Dialectic Tools
- `request_dialectic_review` → `start_interactive_dialectic`
- `request_exploration_session` → `start_interactive_dialectic`
- `submit_thesis` → `start_interactive_dialectic`
- `submit_antithesis` → `start_interactive_dialectic`
- `submit_synthesis` → `resolve_interactive_dialectic`

### Knowledge Graph Tools
- `find_similar_discoveries_graph` → `search_knowledge_graph`
- `get_related_discoveries_graph` → `get_discovery_details`
- `get_response_chain_graph` → `get_discovery_details`
- `reply_to_question` → `store_knowledge_graph`

---

## Benefits

✅ **Zero Breaking Changes** - Old tool names still work  
✅ **Clear Migration Paths** - `migrate_tool()` shows what to use  
✅ **Stability Transparency** - Users know what to expect  
✅ **Reduced Friction** - No need to update code immediately  
✅ **Single Source of Truth** - Unified deprecation workflow  

---

## Future Improvements

1. **Automatic Migration Suggestions** - In error messages
2. **Tool Versioning** - Track tool changes over time
3. **Deprecation Timeline** - "Will be removed in version X"
4. **Usage Analytics** - Track which aliases are still used
5. **Auto-Update Scripts** - Help users migrate code

---

## Files Modified

- `src/mcp_handlers/tool_stability.py` - **NEW** - Stability tiers & aliases
- `src/mcp_handlers/__init__.py` - Alias resolution in dispatch
- `src/mcp_handlers/admin.py` - Stability info in list_tools, migrate_tool handler

---

## Status

✅ **Implemented:**
- Tool stability tiers
- Automatic alias resolution
- Migration helper tool
- Stability info in list_tools

🔄 **In Progress:**
- Alias logging (currently logs, could add to response)
- Usage analytics

📋 **Planned:**
- Tool versioning
- Deprecation timeline
- Auto-update scripts

