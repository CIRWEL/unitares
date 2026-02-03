# Recovery Tools Migration - Complete ✅

## Summary

Consolidated recovery tools for clearer agent experience. Future agents will have a simple, clear recovery hierarchy.

## Changes Made

### 1. Deprecated Tools
- ✅ `direct_resume_if_safe` - Added deprecation warning, will be removed in v2.0
- ✅ `request_dialectic_review` - Already deprecated, marked for removal

### 2. Tool Aliases
- ✅ Added alias: `direct_resume_if_safe` → `quick_resume` (with migration guidance)
- ✅ Aliases automatically route old tool names to new ones

### 3. Tool Stability Registry
- ✅ `self_recovery_review`: STABLE (primary recovery path)
- ✅ `quick_resume`: STABLE (fast recovery path)
- ✅ `check_recovery_options`: STABLE (diagnostic tool)
- ✅ `operator_resume_agent`: BETA (operator tool)
- ✅ `direct_resume_if_safe`: EXPERIMENTAL (deprecated)
- ✅ `request_dialectic_review`: EXPERIMENTAL (deprecated)

### 4. Tool Relationships
- ✅ Added recovery tool relationships to `list_tools`
- ✅ Documented recovery hierarchy
- ✅ Added `replaces` field for deprecated tools

### 5. Documentation
- ✅ Created `RECOVERY_TOOLS_STRATEGY.md` with full analysis
- ✅ Updated tool docstrings with deprecation notices
- ✅ Added migration guidance in responses

## Recovery Hierarchy (Final)

```
Agent Stuck/Paused
    ↓
check_recovery_options()  ← Check eligibility (read-only)
    ↓
┌─────────────────────────────────┐
│ Very Safe? (coherence > 0.60)   │
│          risk < 0.40             │
└──────┬──────────────────┬────────┘
       │ YES              │ NO
       ↓                  ↓
quick_resume()    self_recovery_review()
(no reflection)   (reflection required)
```

## For Future Agents

### When Stuck:
1. **Check eligibility**: `check_recovery_options()` - see what's blocking recovery
2. **Very safe state?**: `quick_resume()` - fastest path, no reflection needed
3. **Moderate state?**: `self_recovery_review(reflection="...")` - requires reflection but allows recovery
4. **Unsafe?**: `leave_note(tags=['needs-human'])` - request human help

### Migration from Old Tools:
- `direct_resume_if_safe()` → Use `quick_resume()` or `self_recovery_review()`
- `request_dialectic_review()` → Use `self_recovery_review()`

### Tool Stability:
- **STABLE**: `self_recovery_review`, `quick_resume`, `check_recovery_options`
- **BETA**: `operator_resume_agent`
- **EXPERIMENTAL**: `direct_resume_if_safe` (deprecated), `request_dialectic_review` (deprecated)

## Benefits

✅ **Clear mental model**: Two recovery paths (fast vs. reflection)
✅ **No confusion**: One tool per use case
✅ **Better UX**: Clear guidance on which tool to use
✅ **Less maintenance**: Fewer overlapping tools
✅ **Backward compatible**: Old tools still work via aliases

## Next Steps

1. Monitor usage of deprecated tools
2. Remove `direct_resume_if_safe` in v2.0 (after migration period)
3. Remove `request_dialectic_review` in v2.0
4. Update operator agent to use new recovery tools

## Files Modified

- `src/mcp_handlers/lifecycle.py` - Added deprecation warning to `direct_resume_if_safe`
- `src/mcp_handlers/tool_stability.py` - Added aliases and stability tiers
- `src/mcp_handlers/admin.py` - Added recovery tool relationships
- `docs/migrations/RECOVERY_TOOLS_STRATEGY.md` - Full strategy document
- `docs/migrations/RECOVERY_MIGRATION_COMPLETE.md` - This file
