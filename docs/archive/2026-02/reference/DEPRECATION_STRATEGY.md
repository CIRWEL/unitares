# Tool Deprecation Strategy

**Date:** 2026-02-04  
**Status:** Active

## Summary

**Answer: Yes, we should deprecate tools, but not remove them yet.**

- ✅ **Deprecated:** `direct_resume_if_safe` (marked as deprecated)
- ✅ **Internal tools** (`register=False`): No deprecation needed - already hidden
- ⏳ **Removal:** Deferred to v2.0 (after deprecation period)

## Current Deprecated Tools

### 1. `direct_resume_if_safe` ✅ DEPRECATED

**Status:** Deprecated (2026-02-04)  
**Superseded by:** `quick_resume()` or `self_recovery_review()`  
**Removal:** v2.0

**Why deprecated:**
- Replaced by clearer recovery paths
- `quick_resume()` - Fast path for safe agents (coherence > 0.60, risk < 0.40)
- `self_recovery_review()` - Reflection-based recovery for lower thresholds

**Migration:**
```python
# Old (deprecated):
direct_resume_if_safe(conditions=["..."])

# New:
if coherence > 0.60 and risk < 0.40:
    quick_resume()  # Fast path
else:
    self_recovery_review(reflection="...")  # Reflection required
```

## Tools That Don't Need Deprecation

### Internal Tools (`register=False`)

These tools are **not exposed via MCP** and are only callable via aliases:

- `get_system_history` → `export(action='history')`
- `pi_health` → `pi(action='health')`
- `observe_agent` → `observe(action='agent')`
- `list_agents` → `agent(action='list')`
- etc. (33 total)

**Why no deprecation needed:**
- They're already hidden from users
- Only accessible via consolidated tools
- No direct MCP exposure = no user confusion

## Deprecation Process

### Step 1: Mark as Deprecated ✅

```python
@mcp_tool("old_tool", deprecated=True, superseded_by="new_tool")
async def handle_old_tool(...):
    # Still works, but warns users
    ...
```

**Effects:**
- Tool still works
- Shows deprecation warning in `list_tools`
- Auto-generated schema includes `[DEPRECATED]` prefix
- Response includes deprecation notice

### Step 2: Add Migration Guidance

```python
response_data["deprecation_warning"] = {
    "tool": "old_tool",
    "status": "deprecated",
    "message": "Use new_tool() instead",
    "migration": {
        "old_usage": "old_tool(param='value')",
        "new_usage": "new_tool(action='value')",
        "related_tools": ["new_tool", "alternative_tool"]
    },
    "removal_version": "v2.0"
}
```

### Step 3: Remove in Future Version

**Timeline:** v2.0 (after deprecation period)

**Process:**
1. Remove from `@mcp_tool` decorator
2. Remove from `tool_schemas.py`
3. Remove handler implementation (or keep as internal)
4. Update documentation

## When to Deprecate vs Remove

### Deprecate When:
- ✅ Tool has a better alternative
- ✅ Tool is confusing or misnamed
- ✅ Tool functionality is merged into consolidated tool
- ✅ Tool has security/performance issues

### Remove When:
- ✅ Deprecation period has passed (v2.0)
- ✅ No active users (check telemetry)
- ✅ Alternative is stable and well-adopted
- ✅ Breaking change is acceptable for major version

### Don't Deprecate When:
- ❌ Tool is internal (`register=False`) - already hidden
- ❌ Tool is experimental but actively used
- ❌ Tool has no clear alternative yet

## Deprecation Checklist

When deprecating a tool:

- [ ] Mark `deprecated=True` in `@mcp_tool` decorator
- [ ] Set `superseded_by` parameter
- [ ] Add deprecation warning to response
- [ ] Update `tool_stability.py` if needed
- [ ] Add migration guidance in docstring
- [ ] Update documentation
- [ ] Set removal version (e.g., "v2.0")

## Current Status

**Deprecated Tools:** 1
- `direct_resume_if_safe` → `quick_resume` or `self_recovery_review`

**Internal Tools (no deprecation needed):** 33
- All have `register=False` and are callable via aliases

**Removal Timeline:** v2.0

## Recommendations

1. ✅ **Keep deprecation warnings** - Help users migrate
2. ✅ **Don't remove yet** - Give users time to migrate
3. ✅ **Track usage** - Use telemetry to see if deprecated tools are still used
4. ✅ **Remove in v2.0** - Clean break for major version

## Future Considerations

- Consider adding deprecation period (e.g., 6 months)
- Track deprecated tool usage via telemetry
- Provide migration scripts/guides
- Announce deprecations in release notes
