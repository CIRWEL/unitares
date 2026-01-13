# simulate_update Lite Mode Fix

**Created:** January 4, 2026  
**Status:** ✅ Fixed (requires server restart)  
**Priority:** Low (nice-to-have improvement)

---

## Problem

`simulate_update` lite mode wasn't working - even with `lite=true`, it returned the full verbose response (~15KB) instead of the simplified version (~2KB).

## Root Cause

The `lite` parameter was missing from the `simulate_update` tool schema in `tool_schemas.py`. FastMCP's wrapper generator only passes through parameters that are defined in the schema, so `lite` was being stripped before reaching the handler.

## Solution

1. **Added `lite` parameter to schema** (`src/tool_schemas.py`):
   ```python
   "lite": {
       "type": ["boolean", "string"],
       "description": "If true, return simplified response with key metrics only (status, decision, E/I/S/V, coherence, risk_score, guidance). Default false (full response with all diagnostics).",
       "default": False
   }
   ```

2. **Handler already had lite mode logic** (`src/mcp_handlers/core.py`):
   - Coerces `lite` parameter using `_apply_generic_coercion()`
   - Returns simplified response when `lite_mode=True`

## Files Modified

- `src/tool_schemas.py` - Added `lite` parameter to `simulate_update` schema
- `src/mcp_handlers/core.py` - Already had lite mode logic (no changes needed)

## Testing

**After server restart**, test:

```python
# Lite mode (simplified)
simulate_update(complexity=0.5, confidence=0.8, lite=true)
# Expected: ~2KB response with status, decision, key metrics, guidance

# Full mode (default)
simulate_update(complexity=0.5, confidence=0.8)
# Expected: ~15KB response with all diagnostics
```

## Impact

- **Before:** Always returned full response (~15KB), even with `lite=true`
- **After:** Returns simplified response (~2KB) when `lite=true`
- **Benefit:** Faster for quick checks, better for smaller models/local agents

---

**Status:** ✅ Fixed. Schema updated. Requires server restart to take effect.

