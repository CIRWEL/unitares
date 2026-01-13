# Tool Discovery & Duplicate Prevention

**Created:** January 1, 2026  
**Status:** Recommendations for improving tool clarity

---

## Problem

Agents sometimes want to create new tools when similar functionality already exists, leading to:
- Duplicate tools
- Confusion about which tool to use
- Fragmented functionality

---

## Current System

**What exists:**
1. ✅ **Tool aliases** - `status` → `get_governance_metrics`
2. ✅ **RELATED TOOLS** sections in descriptions
3. ✅ **describe_tool** - Shows tool details and common patterns
4. ✅ **list_tools** - Categorized tool listing
5. ✅ **Tool categories** - Identity, Core, Observability, etc.

**What's missing:**
- ❌ Semantic tool search ("find tools that do X")
- ❌ Proactive duplicate detection
- ❌ "See also" / "Alternatives" sections
- ❌ Tool similarity recommendations

---

## Recommendations

### 1. Enhanced Tool Descriptions

**Add "SEE ALSO" sections to all tool descriptions:**

```python
"""
Get current governance state and metrics.

SEE ALSO:
- status() - Alias for this tool (intuitive name)
- health_check() - System health (not agent-specific)
- get_connection_status() - MCP connection status
- identity() - Agent identity (who you are)

ALTERNATIVES:
- If you want system health: health_check()
- If you want connection status: get_connection_status()
- If you want identity: identity()
"""
```

**Benefits:**
- Agents see alternatives immediately
- Reduces "I need to create X" thinking
- Clearer tool boundaries

---

### 2. Semantic Tool Search

**Add `search_tools` tool:**

```python
@mcp_tool("search_tools", timeout=10.0)
async def handle_search_tools(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Search tools by functionality, not just name.
    
    Examples:
    - search_tools(query="check agent status")
    - search_tools(query="find similar agents")
    - search_tools(query="store knowledge")
    
    Returns tools matching the query semantically.
    """
```

**Implementation:**
- Use embeddings to match query → tool descriptions
- Return ranked results with similarity scores
- Show "Did you mean?" suggestions

---

### 3. Tool Similarity Detection

**Enhance `list_tools` to show similar tools:**

```python
{
    "name": "get_governance_metrics",
    "similar_tools": [
        {"name": "status", "similarity": "alias", "note": "Same tool, different name"},
        {"name": "health_check", "similarity": 0.7, "note": "System health vs agent metrics"}
    ]
}
```

**Benefits:**
- Agents see related tools immediately
- Prevents "I'll create my own" thinking

---

### 4. Proactive Duplicate Prevention

**When agent tries to create tool, check for existing:**

```python
# In tool creation handler
existing_tools = search_tools_by_functionality(proposed_description)
if existing_tools:
    return error_response(
        f"Similar tool already exists: {existing_tools[0]['name']}",
        suggestions=existing_tools,
        recovery={
            "action": f"Use {existing_tools[0]['name']} instead",
            "related_tools": [t["name"] for t in existing_tools]
        }
    )
```

---

### 5. Tool Categories with Examples

**Enhance categories with "common use cases":**

```python
{
    "category": "Identity & Onboarding",
    "tools": [...],
    "common_use_cases": [
        "Check who you are: identity()",
        "Start new session: onboard()",
        "Check status: status() or get_governance_metrics()"
    ],
    "see_also": {
        "status": "get_governance_metrics",
        "who_am_i": "identity"
    }
}
```

---

### 6. Tool Naming Conventions

**Document naming patterns:**

```markdown
## Tool Naming Conventions

- `get_*` - Read-only queries (get_governance_metrics)
- `list_*` - List multiple items (list_agents)
- `search_*` - Search/filter operations (search_knowledge_graph)
- `process_*` - Write operations (process_agent_update)
- `update_*` - Modify existing (update_agent_metadata)
- `*_status` - Status checks (get_connection_status)
- `*_metrics` - Metrics/queries (get_governance_metrics)

If you want to create a tool, check these patterns first!
```

---

### 7. Tool Discovery Workflow

**Add discovery helper:**

```python
@mcp_tool("discover_tools", timeout=10.0)
async def handle_discover_tools(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    Discover tools for a specific task.
    
    Usage:
    - discover_tools(task="check my status")
    - discover_tools(task="find similar agents")
    - discover_tools(task="store a note")
    
    Returns:
    - Matching tools
    - Similar tools
    - Common patterns
    - Examples
    """
```

---

## Implementation Priority

**Phase 1: Quick Wins (Low effort, high impact)**
1. ✅ Add "SEE ALSO" to all tool descriptions
2. ✅ Enhance `describe_tool` with alternatives
3. ✅ Document naming conventions

**Phase 2: Medium Effort**
4. ⏳ Add `search_tools` semantic search
5. ⏳ Show similar tools in `list_tools`
6. ⏳ Tool similarity detection

**Phase 3: Advanced**
7. ⏳ Proactive duplicate prevention
8. ⏳ Tool creation validation
9. ⏳ Usage pattern analysis

---

## Example: Enhanced Tool Description

**Before:**
```
Get current governance state and metrics.
```

**After:**
```
Get current governance state and metrics.

SEE ALSO:
- status() - Alias (same tool, intuitive name)
- health_check() - System health (not agent-specific)
- get_connection_status() - MCP connection status
- identity() - Agent identity (who you are)

ALTERNATIVES:
- System health → health_check()
- Connection status → get_connection_status()
- Agent identity → identity()

COMMON PATTERNS:
- Quick check: status()
- With history: get_governance_metrics(include_history=true)
- Full state: get_governance_metrics(include_state=true)

SIMILAR TOOLS:
- status (alias, 100% match)
- health_check (system-level, 60% match)
- get_connection_status (connection-level, 40% match)
```

---

## Benefits

**For agents:**
- ✅ See alternatives immediately
- ✅ Understand tool boundaries
- ✅ Find tools by functionality
- ✅ Avoid creating duplicates

**For system:**
- ✅ Fewer duplicate tools
- ✅ Better tool utilization
- ✅ Clearer tool ecosystem
- ✅ Easier onboarding

---

**Status:** Recommendations ready  
**Action:** Implement Phase 1 enhancements first

