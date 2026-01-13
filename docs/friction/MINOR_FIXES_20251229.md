# Minor Friction Point Fixes

**Created:** December 29, 2025  
**Status:** ✅ Fixed  
**Priority:** Low (nice-to-have improvements)

---

## Fixes Implemented

### 1. ✅ Added `lite` Mode to `simulate_update`

**Problem:** `simulate_update` returns very comprehensive output (~15KB), which can be overwhelming for smaller models or quick checks.

**Solution:** Added `lite` parameter that returns minimal response with key metrics only.

**File:** `src/mcp_handlers/core.py`

**Changes:**
- Added `lite_mode = arguments.get("lite", False)` check
- When `lite=true`, returns simplified response:
  - Status, decision, key metrics (E, I, S, V, coherence, risk_score)
  - Guidance
  - Removes verbose details (sampling_params, continuity, restorative, hck, cirs, etc.)

**Usage:**
```python
# Full response (default)
simulate_update(complexity=0.5, confidence=0.8)

# Lite mode (simplified)
simulate_update(complexity=0.5, confidence=0.8, lite=true)
```

**Impact:** Reduces response size from ~15KB to ~2KB for quick checks.

---

### 2. ✅ Improved Search Fallback Explanation

**Problem:** Fallback messages were technical and didn't clearly explain WHY the fallback was needed.

**Solution:** Made fallback messages more user-friendly and explanatory.

**File:** `src/mcp_handlers/knowledge_graph.py`

**Changes:**

1. **FTS Fallback:**
   - Before: `"Original query 'ux_feedback alias' returned 0 results. Retried with individual terms using OR operator: ux_feedback, alias"`
   - After: `"No exact phrase matches found for 'ux_feedback alias'. Searching individual terms instead: ux_feedback, alias"`

2. **Semantic → FTS Fallback:**
   - Before: `"Semantic search returned 0 results. Fell back to keyword search (FTS)."`
   - After: `"Semantic search found no similar concepts. Using keyword search instead."`

3. **Semantic Lower Threshold Fallback:**
   - Before: `"Semantic search with default threshold returned 0 results. Retried with lower similarity threshold (0.3) for more permissive matching."`
   - After: `"No matches found with default similarity threshold. Retrying with lower threshold (0.3) for more permissive matching."`

4. **Generic Fallback:**
   - Before: `"Original query returned 0 results. Retried with individual terms (OR operator)."`
   - After: `"No exact matches found. Retried with individual terms (OR operator)."`

**Impact:** Clearer, more user-friendly explanations that explain what happened and why.

---

## Testing

After server restart, test:

```python
# Test lite mode
simulate_update(complexity=0.5, confidence=0.8, lite=true)  # Should return simplified response

# Test search fallback (use query that won't match exactly)
search_knowledge_graph(query="very specific phrase that doesn't exist")  # Should show improved fallback message
```

**Note:** Schema changes require server restart. The `lite` parameter was added to `simulate_update` schema in `tool_schemas.py`.

---

## Files Modified

- `src/mcp_handlers/core.py` - Added lite mode to simulate_update
- `src/mcp_handlers/knowledge_graph.py` - Improved fallback messages

---

**Status:** ✅ Fixed. Both minor friction points addressed!

