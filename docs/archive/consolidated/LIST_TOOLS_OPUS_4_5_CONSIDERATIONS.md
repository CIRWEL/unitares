# list_tools Considerations for Opus 4.5

**Date:** November 24, 2025  
**Context:** Opus 4.5 may have changed how it handles MCP `list_tools()`

---

## 🎯 Current Implementation

### MCP Protocol `@server.list_tools()`
- Returns `list[Tool]` objects
- Used by Claude to discover available tools
- Each Tool has: `name`, `description`, `inputSchema`

### Custom `list_tools` Tool
- Runtime introspection for agents
- Returns JSON with tool list + categories
- Useful for autonomous discovery

---

## 🤔 Potential Opus 4.5 Changes

### Possibility 1: Richer Metadata Expected
Opus 4.5 might expect more structured metadata:
- Tool categories/tags
- Usage examples
- Related tools
- Complexity indicators

### Possibility 2: Better Descriptions
- More detailed descriptions
- Parameter explanations
- Return value descriptions
- Error handling info

### Possibility 3: Tool Grouping
- Tools organized by category
- Priority/importance indicators
- Dependency relationships

### Possibility 4: Schema Enhancements
- Better parameter descriptions
- Example values
- Validation rules
- Default value explanations

---

## 💡 Potential Improvements

### Option A: Enhance Tool Descriptions
Add more context to each tool:

```python
Tool(
    name="process_agent_update",
    description="Run one complete governance cycle for an agent. Processes agent state and returns governance decision, metrics, and sampling parameters. This is the PRIMARY tool for logging agent behavior.",
    inputSchema={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "UNIQUE identifier for the agent. Must be unique across all agents to prevent state mixing.",
                "examples": ["cursor_ide_session_001", "claude_code_cli_20251124"]
            },
            # ... more detailed descriptions
        }
    }
)
```

### Option B: Add Tool Metadata
Include categories/tags in Tool objects (if MCP SDK supports):

```python
Tool(
    name="process_agent_update",
    description="...",
    # If MCP SDK supports metadata:
    metadata={
        "category": "core",
        "priority": "high",
        "requires_auth": True,
        "related_tools": ["simulate_update", "get_governance_metrics"]
    }
)
```

### Option C: Improve Schema Descriptions
More detailed parameter descriptions:

```python
"parameters": {
    "type": "array",
    "items": {"type": "number"},
    "description": "Agent parameters vector (128 dimensions). First 6 are core metrics: [length_score, complexity, info_score, coherence_score, placeholder, ethical_drift]. Remaining 122 dimensions are optional extensions.",
    "examples": [[0.5] * 128, [0.7, 0.6, 0.8, ...]],
    "minItems": 0,
    "maxItems": 128
}
```

---

## 🔍 What to Check

1. **Does Opus 4.5 show tools differently?**
   - Grouped by category?
   - With metadata?
   - With examples?

2. **Are there any errors/warnings?**
   - Schema validation issues?
   - Missing required fields?
   - Format mismatches?

3. **Does it discover all 21 tools?**
   - Are any missing?
   - Are any duplicated?
   - Order matters?

---

## 🎯 Recommendations

### If Opus 4.5 Groups Tools:
- Consider adding category metadata (if MCP SDK supports)
- Or ensure descriptions include category hints

### If Opus 4.5 Needs Richer Descriptions:
- Add usage examples to descriptions
- Include parameter explanations
- Add return value descriptions

### If Opus 4.5 Validates More Strictly:
- Ensure all schemas are valid JSON Schema
- Add proper type constraints
- Include default values where appropriate

---

## 📝 Questions for User

1. **What specifically changed?**
   - How tools are displayed?
   - Which tools are discovered?
   - Any errors or warnings?

2. **What behavior do you see?**
   - Tools grouped differently?
   - Missing tools?
   - Different descriptions?

3. **What would you like improved?**
   - Better descriptions?
   - More metadata?
   - Different organization?

---

**Status:** Awaiting clarification on Opus 4.5 changes

