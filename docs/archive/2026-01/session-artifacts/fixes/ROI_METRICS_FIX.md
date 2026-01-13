# ROI Metrics Tool - Server Load Fix

**Created:** December 30, 2025  
**Last Updated:** December 30, 2025  
**Status:** Fixed

---

## Issue

Server wouldn't load after adding ROI metrics tool.

## Root Cause

The `SimpleDiscovery` class was defined multiple times inside try blocks, causing potential scoping issues and code duplication.

## Fix

Moved `SimpleDiscovery` class definition to module level (top of file) so it's defined once and reused.

**Before:**
```python
try:
    # ...
    class SimpleDiscovery:
        def __init__(self, node):
            # ...
    all_discoveries = [SimpleDiscovery(node) for node in all_discoveries_raw]
```

**After:**
```python
class SimpleDiscovery:
    """Simple wrapper for discovery nodes"""
    def __init__(self, node):
        # ...

@mcp_tool("get_roi_metrics", timeout=15.0)
async def handle_get_roi_metrics(...):
    # ...
    all_discoveries = [SimpleDiscovery(node) for node in all_discoveries_raw]
```

## Verification

✅ Tool imports successfully
✅ Server loads correctly
✅ Tool registered (51 tools total)

## Status

**Fixed** - Server should load correctly now. Restart required to pick up changes.

---

**Next Steps:** Restart server to apply fix.

