# Recovery Tools Strategy & Migration Plan

## Current Recovery Tool Landscape

### Active Tools

1. **`self_recovery_review`** (NEW - lifecycle.py)
   - **Purpose**: Primary recovery path with reflection requirement
   - **Thresholds**: coherence > 0.35, risk < 0.65, no void
   - **Requires**: Reflection (min 20 chars)
   - **Status**: ✅ Primary recommended path

2. **`direct_resume_if_safe`** (lifecycle.py)
   - **Purpose**: Direct resume without reflection
   - **Thresholds**: coherence > 0.40, risk < 0.60, no void
   - **Requires**: None (just safe state)
   - **Status**: ⚠️ Overlaps with quick_resume

3. **`quick_resume`** (self_recovery.py)
   - **Purpose**: Fastest path for clearly safe states
   - **Thresholds**: coherence > 0.60, risk < 0.40, no void
   - **Requires**: None
   - **Status**: ⚠️ Overlaps with direct_resume_if_safe

4. **`check_recovery_options`** (self_recovery.py)
   - **Purpose**: Read-only eligibility check
   - **Status**: ✅ Useful diagnostic tool

5. **`operator_resume_agent`** (self_recovery.py)
   - **Purpose**: Operator-assisted recovery for other agents
   - **Status**: ✅ Useful for operator workflows

### Deprecated Tools

6. **`request_dialectic_review`** (dialectic.py)
   - **Purpose**: Heavyweight dialectic recovery
   - **Status**: ❌ Deprecated - rarely works, timeouts, needs external reviewer

## Analysis: Tool Overlap & Redundancy

### Overlap Problem

**`direct_resume_if_safe` vs `quick_resume`**:
- Both do the same thing: resume without reflection
- Different thresholds but same concept
- Creates confusion: "Which one should I use?"

**Threshold Comparison**:
```
quick_resume:        coherence > 0.60, risk < 0.40  (strictest)
direct_resume_if_safe: coherence > 0.40, risk < 0.60  (moderate)
self_recovery_review: coherence > 0.35, risk < 0.65  (lenient, requires reflection)
```

## Recommended Strategy

### Option A: Consolidate (Recommended)

**Keep:**
1. ✅ **`self_recovery_review`** - Primary path (reflection required)
2. ✅ **`quick_resume`** - Fast path (no reflection, strict thresholds)
3. ✅ **`check_recovery_options`** - Diagnostic tool
4. ✅ **`operator_resume_agent`** - Operator tool

**Deprecate/Remove:**
- ❌ **`direct_resume_if_safe`** - Redundant with `quick_resume`
  - Migration: `direct_resume_if_safe` → `quick_resume` (if thresholds met) or `self_recovery_review` (if not)
- ❌ **`request_dialectic_review`** - Already deprecated, remove after migration period

**Rationale:**
- Clear hierarchy: `quick_resume` (fastest) → `self_recovery_review` (reflection) → human escalation
- No confusion about which tool to use
- `quick_resume` has better name and clearer purpose

### Option B: Keep All (Status Quo)

**Keep everything**, but:
- Add deprecation warnings to `direct_resume_if_safe`
- Document clear guidance on when to use each tool
- Mark `request_dialectic_review` as deprecated

**Pros**: No breaking changes
**Cons**: Tool proliferation, confusion

### Option C: Unify into Single Tool

Create one `resume_agent` tool with parameters:
- `reflection`: Optional (if provided, uses lenient thresholds)
- `force`: Optional (skip some checks)

**Pros**: Single tool, no confusion
**Cons**: Loses semantic clarity of different recovery paths

## Recommendation: Option A (Consolidate)

### Migration Plan

1. **Phase 1: Add deprecation warnings** (Week 1)
   - Add deprecation notice to `direct_resume_if_safe`
   - Point users to `quick_resume` or `self_recovery_review`
   - Keep tool functional

2. **Phase 2: Update documentation** (Week 2)
   - Update tool docs to recommend `self_recovery_review` as primary
   - Document recovery hierarchy
   - Add migration guide

3. **Phase 3: Remove deprecated tools** (Month 2)
   - Remove `direct_resume_if_safe` after migration period
   - Remove `request_dialectic_review` (already deprecated)

### Recovery Tool Hierarchy (Final)

```
┌─────────────────────────────────────────┐
│  Agent Stuck/Paused                      │
└──────────────┬──────────────────────────┘
               │
               ▼
    ┌──────────────────────┐
    │ check_recovery_options│  ← Diagnostic (read-only)
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ coherence > 0.60?    │
    │ risk < 0.40?         │
    │ no void?             │
    └──────┬───────────┬───┘
           │ YES       │ NO
           ▼           ▼
    ┌──────────┐  ┌──────────────────────┐
    │quick_    │  │ coherence > 0.35?    │
    │resume    │  │ risk < 0.65?         │
    │          │  │ no void?             │
    │(fastest) │  └──────┬───────────┬───┘
    └──────────┘         │ YES       │ NO
                         ▼           ▼
                  ┌──────────────┐  ┌──────────────┐
                  │self_recovery │  │Human         │
                  │_review       │  │Escalation    │
                  │              │  │              │
                  │(reflection   │  │(leave_note   │
                  │ required)    │  │ with tag)    │
                  └──────────────┘  └──────────────┘
```

### Tool Usage Guide

**For agents:**
1. **Stuck?** → `check_recovery_options()` to see eligibility
2. **Very safe state?** → `quick_resume()` (fastest)
3. **Moderate state?** → `self_recovery_review(reflection="...")` (requires reflection)
4. **Unsafe?** → `leave_note(tags=['needs-human'])` for help

**For operators:**
- Use `operator_resume_agent(target_agent_id="...", reason="...")` to help stuck agents

## Implementation Notes

### Deprecation Pattern

```python
@mcp_tool("direct_resume_if_safe", timeout=10.0)
async def handle_direct_resume_if_safe(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """
    ⚠️ DEPRECATED: Use quick_resume() or self_recovery_review() instead.
    
    This tool is deprecated in favor of:
    - quick_resume() - for clearly safe states (coherence > 0.60, risk < 0.40)
    - self_recovery_review() - for moderate states with reflection (coherence > 0.35, risk < 0.65)
    
    Migration:
    - If your state meets quick_resume thresholds → use quick_resume()
    - Otherwise → use self_recovery_review(reflection="...")
    
    This tool will be removed in v2.0.
    """
    # ... existing implementation ...
    # Add deprecation warning to response
    response = success_response({...})
    response["deprecation_warning"] = {
        "message": "direct_resume_if_safe is deprecated",
        "migration": {
            "use_quick_resume_if": "coherence > 0.60 and risk < 0.40",
            "use_self_recovery_review_if": "coherence > 0.35 and risk < 0.65",
        }
    }
    return response
```

### Tool Relationship Documentation

Update `list_tools` to show relationships:

```python
"self_recovery_review": {
    "category": "lifecycle",
    "depends_on": ["get_governance_metrics"],
    "related_to": ["quick_resume", "check_recovery_options"],
    "replaces": ["direct_resume_if_safe", "request_dialectic_review"],
    "recovery_hierarchy": {
        "fastest": "quick_resume",
        "primary": "self_recovery_review",
        "diagnostic": "check_recovery_options"
    }
}
```

## Questions to Consider

1. **Should `direct_resume_if_safe` be removed immediately?**
   - **Recommendation**: Deprecate first, remove after 1-2 months
   - Allows users to migrate gradually

2. **Should `request_dialectic_review` be removed?**
   - **Recommendation**: Yes, it's already deprecated and rarely works
   - Keep `get_dialectic_session` for viewing historical sessions

3. **Should `quick_resume` and `direct_resume_if_safe` be merged?**
   - **Recommendation**: Yes, but keep `quick_resume` name (clearer)
   - Use `quick_resume` thresholds (stricter = safer)

4. **What about `check_recovery_options`?**
   - **Recommendation**: Keep it - useful diagnostic tool
   - Helps agents understand why they can't recover

## Final Recommendation

**Consolidate to 4 tools:**
1. ✅ `self_recovery_review` - Primary recovery (reflection required)
2. ✅ `quick_resume` - Fast recovery (no reflection, strict thresholds)
3. ✅ `check_recovery_options` - Diagnostic tool
4. ✅ `operator_resume_agent` - Operator tool

**Deprecate:**
- ⚠️ `direct_resume_if_safe` → migrate to `quick_resume` or `self_recovery_review`
- ❌ `request_dialectic_review` → remove (already deprecated)

**Benefits:**
- Clear recovery hierarchy
- No tool confusion
- Simpler mental model
- Better user experience
