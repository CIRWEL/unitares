# Threshold Adjustment Guide

**Created:** December 30, 2025  
**Status:** Reference guide

---

## Two Types of Thresholds

The system has two different types of thresholds that are adjusted differently:

### 1. Semantic Search Similarity Thresholds ✅ **MCP Parameter**

**What:** Controls how similar discoveries must be to your query in semantic search.

**How to Adjust:** Pass `min_similarity` parameter in `search_knowledge_graph()` call.

**Example:**
```python
# Default threshold (0.25)
search_knowledge_graph(query="void state", semantic=true)

# More permissive (0.15) - finds more loosely related concepts
search_knowledge_graph(query="void state", semantic=true, min_similarity=0.15)

# More strict (0.4) - finds only closely related concepts
search_knowledge_graph(query="void state", semantic=true, min_similarity=0.4)
```

**Range:** 0.0 to 1.0
- **0.0-0.2:** Very permissive - finds loosely related concepts
- **0.2-0.3:** Moderate - finds conceptually similar content (default: 0.25)
- **0.3-0.5:** Strict - finds closely related concepts
- **0.5+:** Very strict - finds highly similar content only

**No Code Changes Needed:** This is a per-query parameter - adjust it for each search call.

---

### 2. Governance Thresholds ⚙️ **MCP Tools (Admin)**

**What:** Controls governance decision boundaries (risk, coherence, void thresholds).

**How to Adjust:** Use `get_thresholds()` and `set_thresholds()` MCP tools.

**Requirements:**
- Admin tag OR 100+ updates (high reputation)
- Agent status must be healthy (not critical)
- Risk score must be < 0.60

**Example:**
```python
# View current thresholds
get_thresholds()

# Set threshold overrides (admin only)
set_thresholds(thresholds={
    "risk_approve_threshold": 0.3,
    "coherence_critical_threshold": 0.4
})
```

**Available Thresholds:**
- `risk_approve_threshold` - Risk level for automatic approval
- `risk_revise_threshold` - Risk level requiring revision
- `risk_reject_threshold` - Risk level triggering rejection
- `coherence_critical_threshold` - Coherence level considered critical
- `void_threshold_initial` - Initial void state threshold

**Note:** These are runtime overrides - they persist until changed or server restart.

---

## Summary

| Threshold Type | Adjustment Method | Code Changes? | Access Level |
|---------------|------------------|---------------|--------------|
| **Semantic Search** (`min_similarity`) | MCP parameter | ❌ No | All agents |
| **Governance** (risk, coherence, void) | MCP tools (`set_thresholds`) | ❌ No | Admin only |

---

## Quick Reference

**For semantic search:**
```python
# Adjust per query
search_knowledge_graph(query="...", semantic=true, min_similarity=0.3)
```

**For governance thresholds:**
```python
# View current
get_thresholds()

# Modify (admin only)
set_thresholds(thresholds={"risk_approve_threshold": 0.3})
```

---

**Last Updated:** December 30, 2025

