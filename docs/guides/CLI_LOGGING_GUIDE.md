# CLI Logging Guide - Ephemeral vs Persistent

**Date:** November 24, 2025  
**Status:** Guide for CLI Script Authors

---

## 🎯 Two Patterns for CLI Logging

### Pattern 1: Ephemeral CLI (Current - Lightweight)

**Use case:** Quick logging without full state tracking

**Architecture:**
- Spawn new MCP server process per call
- No state loading (starts fresh)
- Metadata updates saved (tags/notes)
- Governance metrics ephemeral (not persisted)

**Limitations:**
- `total_updates` counter may not persist (async save race condition)
- Governance history not maintained
- Same coherence every time (starts fresh)

**When to use:**
- Lightweight logging
- Metadata-only tracking
- Quick decision checks

---

### Pattern 2: Persistent CLI (Recommended - Full Tracking)

**Use case:** Full governance tracking with history

**Architecture:**
- Use persistent MCP server (via Cursor/Claude Desktop)
- Or create persistent CLI wrapper
- State loaded from disk
- History maintained across calls

**Benefits:**
- Full state persistence
- History tracking
- Metrics evolve over time
- Proper governance tracking

**When to use:**
- Production logging
- Governance tracking
- Pattern analysis

---

## 🔧 Fixing Ephemeral CLI Scripts

### Problem: Async Save Race Condition

**Current code:**
```python
meta.total_updates += 1
await save_metadata_async()  # May not complete before process exits
```

**Solution:** Ensure async saves complete

**Option A: Use synchronous save (for CLI)**
```python
meta.total_updates += 1
save_metadata()  # Synchronous - blocks until saved
```

**Option B: Await and verify (current - should work)**
```python
meta.total_updates += 1
await save_metadata_async()  # Already awaited - should complete
# Process should wait for async to complete before exiting
```

**Issue:** If CLI script spawns subprocess, subprocess may exit before async completes.

---

## 📊 Current Behavior

| Feature | Ephemeral CLI | Persistent Server |
|---------|---------------|-------------------|
| Decision returned | ✅ | ✅ |
| Metadata tags/notes | ✅ Usually saved | ✅ Saved |
| Metadata `total_updates` | ⚠️ May not persist | ✅ Saved |
| Governance history | ❌ Not maintained | ✅ Maintained |
| State evolution | ❌ Always fresh | ✅ Evolves |

---

## 🎯 Recommendation

**For CLI scripts:**

1. **If lightweight logging:** Accept ephemeral behavior, document it
2. **If full tracking needed:** Use persistent MCP server or wrapper
3. **If fixing ephemeral:** Ensure async saves complete before process exit

**For this session:**
- Metadata is documented (tags/notes)
- Governance metrics are ephemeral
- This is acceptable for lightweight logging

---

**Status:** Documented - Behavior is by design for ephemeral CLI

