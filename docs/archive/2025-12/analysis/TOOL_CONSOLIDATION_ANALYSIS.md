# Tool Consolidation Incoherence Analysis

**Date:** December 20, 2025  
**Issue:** Tool consolidation appears incomplete/incoherent  
**Status:** Analysis & Recommendations

---

## Current State

### Tool Count
- **Total tools in registry:** 37 (from `list_tools`)
- **Deprecated tools:** ~15+ (marked but still visible)
- **Essential tools:** 6
- **Common tools:** 13
- **Advanced tools:** 18

### Consolidation Attempts

#### 1. Dialectic Tools (5+ → 2)
**Consolidated to:**
- `start_interactive_dialectic` (replaces 5 tools)
- `resolve_interactive_dialectic` (replaces 1 tool)

**Deprecated:**
- `request_dialectic_review` → `start_interactive_dialectic`
- `request_exploration_session` → `start_interactive_dialectic`
- `submit_thesis` → `start_interactive_dialectic`
- `submit_antithesis` → `start_interactive_dialectic`
- `submit_synthesis` → `resolve_interactive_dialectic`
- `nudge_dialectic_session` → `get_dialectic_session`

**Problem:** All 6 deprecated tools still appear in `list_tools` output.

#### 2. Knowledge Graph Tools (6 → 2)
**Consolidated to:**
- `search_knowledge_graph` (replaces 3 tools)
- `get_discovery_details` (replaces 2 tools)

**Deprecated:**
- `get_knowledge_graph` → `search_knowledge_graph`
- `list_knowledge_graph` → `search_knowledge_graph`
- `find_similar_discoveries_graph` → `search_knowledge_graph`
- `get_related_discoveries_graph` → `get_discovery_details`
- `get_response_chain_graph` → `get_discovery_details`
- `reply_to_question` → `store_knowledge_graph`

**Problem:** All 6 deprecated tools still appear in `list_tools` output.

#### 3. Identity Tools (3 → 2)
**Consolidated to:**
- `hello` (replaces 2 tools)
- `recall_identity` (replaces 1 tool)

**Deprecated:**
- `authenticate` → `hello`
- `session` → `hello`
- `who_am_i` → `recall_identity`
- `quick_start` → `hello`

**Problem:** Some deprecated tools still appear.

---

## Incoherence Issues

### Issue 1: Deprecated Tools Still Visible

**Expected Behavior:**
- Deprecated tools should be hidden by default in `list_tools`
- Only shown if `include_deprecated=true`

**Actual Behavior:**
- Deprecated tools appear in `list_tools` output
- Code has filtering (line 1608 in `admin.py`), but it's not working correctly

**Root Cause:**
```python
# Line 1608 in admin.py
if is_deprecated and not include_deprecated:
    continue
```

But `include_deprecated` defaults to `False` (line 1595), so deprecated tools should be filtered. However, they're still showing up, suggesting:
1. The deprecation check isn't working correctly
2. Tools are marked deprecated in decorators but not in TOOL_TIERS
3. Tools are in TOOL_TIERS["deprecated"] but decorator check fails

### Issue 2: Inconsistent Deprecation Markers

**Two Systems:**
1. **Decorator-based:** `@mcp_tool(..., deprecated=True, superseded_by="...")`
2. **Tier-based:** `TOOL_TIERS["deprecated"]` set

**Problem:**
- Some tools marked deprecated in decorators but NOT in TOOL_TIERS
- Some tools in TOOL_TIERS["deprecated"] but NOT marked in decorators
- Check uses OR logic (line 1599-1602), so either can mark as deprecated

**Example:**
- `get_knowledge_graph` - marked deprecated in decorator, but NOT in TOOL_TIERS["deprecated"]
- `get_agent_api_key` - in TOOL_TIERS["deprecated"], but NOT marked in decorator

### Issue 3: Unclear Consolidation Relationships

**Dialectic Consolidation:**
- `start_interactive_dialectic` claims to replace 5 tools
- But those 5 tools have different purposes:
  - `request_dialectic_review` - manual peer review
  - `request_exploration_session` - collaborative exploration
  - `submit_thesis` - paused agent submits thesis
  - `submit_antithesis` - reviewer submits antithesis
  - `submit_synthesis` - either agent submits synthesis

**Problem:** One tool can't replace all these - they're different workflow steps.

**Knowledge Graph Consolidation:**
- `search_knowledge_graph` claims to replace:
  - `get_knowledge_graph` - Get all knowledge for an agent
  - `list_knowledge_graph` - List statistics
  - `find_similar_discoveries_graph` - Find similar by tags

**Problem:** These are different query patterns:
- Agent-centric view vs. statistics vs. similarity search

### Issue 4: Categories vs Tiers Confusion

**Two Classification Systems:**
1. **Categories:** `core`, `knowledge`, `dialectic`, `lifecycle`, etc.
2. **Tiers:** `essential`, `common`, `advanced`, `deprecated`

**Problem:**
- Tools can be in multiple categories
- Tools can only be in one tier
- No clear mapping between categories and tiers
- `list_tools` uses tiers, but relationships use categories

### Issue 5: Superseded_by Not Clear

**Current:**
- `superseded_by` is stored in metadata
- But not shown in `list_tools` output clearly
- Users don't know what to use instead

**Example:**
- User sees `get_knowledge_graph` in list
- Doesn't know it's deprecated
- Doesn't know to use `search_knowledge_graph` instead

---

## Recommendations

### 1. Fix Deprecation Filtering

**Problem:** Deprecated tools still showing in `list_tools`

**Solution:**
```python
# In handle_list_tools, ensure deprecated tools are filtered
include_deprecated = arguments.get("include_deprecated", False)  # Default: False

# Check BOTH sources for deprecation
is_deprecated = (
    tool_name in TOOL_TIERS.get("deprecated", set()) or
    is_tool_deprecated(tool_name)
)

# Filter out deprecated unless explicitly requested
if is_deprecated and not include_deprecated:
    continue
```

**Action:** Verify this logic is working correctly.

### 2. Unify Deprecation Markers

**Problem:** Two systems (decorator + tier) can conflict

**Solution:**
- **Single source of truth:** Use decorator `deprecated=True` as primary
- **TOOL_TIERS["deprecated"]** should be auto-generated from decorators
- Or: Remove decorator deprecation, use only TOOL_TIERS

**Action:** Choose one system and make it consistent.

### 3. Clarify Consolidation Relationships

**Problem:** One tool can't replace multiple tools with different purposes

**Solution A: Keep Separate Tools**
- Don't consolidate - keep tools separate
- Mark as "related" not "superseded"
- Use categories to group them

**Solution B: True Consolidation**
- If consolidating, the new tool must handle ALL use cases
- Document migration path clearly
- Provide examples for each old tool → new tool

**Recommendation:** **Solution A** - Dialectic tools serve different purposes, shouldn't be consolidated.

### 4. Improve Superseded_by Visibility

**Problem:** Users don't know what to use instead

**Solution:**
```python
# In list_tools output, show superseded_by clearly
if is_deprecated:
    tool_info["deprecated"] = True
    if meta.get("superseded_by"):
        tool_info["superseded_by"] = meta["superseded_by"]
        tool_info["deprecation_message"] = f"Use {meta['superseded_by']} instead"
```

**Action:** Add deprecation messages to tool descriptions.

### 5. Simplify Classification

**Problem:** Categories + Tiers is confusing

**Solution:**
- **Use Tiers for visibility** (essential/common/advanced/deprecated)
- **Use Categories for grouping** (core/knowledge/dialectic)
- **Show both** in `list_tools` output
- **Filter by tier, group by category**

**Action:** Update `list_tools` to show both clearly.

---

## Specific Fixes Needed

### Fix 1: Filter Deprecated Tools
```python
# In handle_list_tools (admin.py line ~1608)
# Ensure deprecated tools are filtered by default
include_deprecated = arguments.get("include_deprecated", False)  # Default: False

# Check deprecation from both sources
is_deprecated = (
    tool_name in TOOL_TIERS.get("deprecated", set()) or
    is_tool_deprecated(tool_name)
)

# Filter unless explicitly requested
if is_deprecated and not include_deprecated:
    continue  # Skip deprecated tools
```

### Fix 2: Show Superseded_by in Output
```python
# When building tool_info, include deprecation info
if is_deprecated:
    tool_info["deprecated"] = True
    meta = get_tool_metadata(tool_name)
    if meta and meta.get("superseded_by"):
        tool_info["superseded_by"] = meta["superseded_by"]
        tool_info["migration_guide"] = f"Use {meta['superseded_by']} instead"
```

### Fix 3: Revisit Dialectic Consolidation
**Current:** 5 tools → 1 tool (`start_interactive_dialectic`)

**Problem:** These are different workflow steps, not redundant:
- `request_dialectic_review` - Initiate review
- `submit_thesis` - Paused agent submits
- `submit_antithesis` - Reviewer submits
- `submit_synthesis` - Either agent submits
- `nudge_dialectic_session` - Admin action

**Recommendation:** 
- Keep `start_interactive_dialectic` for new interactive flow
- Keep old tools for programmatic/manual flow
- Mark old tools as "legacy" not "deprecated"
- Document when to use which

### Fix 4: Revisit Knowledge Graph Consolidation
**Current:** 6 tools → 2 tools

**Problem:** Different query patterns:
- `get_knowledge_graph(agent_id)` - Agent-centric view
- `list_knowledge_graph()` - Statistics
- `find_similar_discoveries_graph(discovery_id)` - Similarity search
- `search_knowledge_graph(...)` - General search

**Recommendation:**
- Keep `search_knowledge_graph` as primary search
- Keep `get_knowledge_graph` for agent-centric view (common use case)
- Keep `list_knowledge_graph` for statistics (different purpose)
- Deprecate only truly redundant ones:
  - `find_similar_discoveries_graph` → `search_knowledge_graph(semantic=true)`
  - `get_related_discoveries_graph` → `get_discovery_details` (includes related)
  - `get_response_chain_graph` → `get_discovery_details` (includes chain)

---

## Summary

**Incoherence Sources:**
1. ✅ Deprecated tools still visible (filtering not working)
2. ✅ Inconsistent deprecation markers (two systems)
3. ✅ Unclear consolidation (one tool can't replace multiple different tools)
4. ✅ Superseded_by not visible (users don't know what to use)
5. ✅ Categories vs Tiers confusion (two classification systems)

**Priority Fixes:**
1. **High:** Fix deprecated tool filtering (line 1608)
2. **High:** Show superseded_by in output
3. **Medium:** Revisit dialectic consolidation (keep separate tools)
4. **Medium:** Revisit knowledge graph consolidation (keep agent-centric view)
5. **Low:** Unify deprecation markers (choose one system)

---

**Document Version:** 1.0  
**Last Updated:** December 20, 2025

