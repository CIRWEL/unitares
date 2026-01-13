# ChatGPT UX Friction Points

**Created:** December 29, 2025  
**Source:** ChatGPT agent feedback via MCP  
**Status:** Fixes implemented

---

## Summary

ChatGPT agent attempted to persist UX feedback into the MCP Knowledge Graph and encountered three friction points that blocked the workflow:

1. **Enum strictness**: `discovery_type="ux_feedback"` rejected (strict enum)
2. **Identity confusion**: Explicit `agent_id` caused session mismatch
3. **Safety gate blocking**: `identity(name="Calliope")` blocked by platform safety gate

---

## Friction Point 1: Enum Strictness

### Problem
```
store_knowledge_graph(discovery_type="ux_feedback", ...)
→ Rejected: "ux_feedback" not in enum
```

**Root Cause:** `discovery_type` enum is strict, no aliasing for `ux_feedback`.

**Impact:** Agent had to manually map `ux_feedback` → `improvement`, adding cognitive overhead.

### Fix ✅
Added aliases to `DISCOVERY_TYPE_ALIASES` in `src/mcp_handlers/validators.py`:
- `ux_feedback` → `improvement`
- `feedback` → `improvement`
- `ux` → `improvement`

**Status:** Implemented. Aliases are automatically resolved during validation.

---

## Friction Point 2: Identity/Session Mismatch

### Problem
```
store_knowledge_graph(agent_id="explicit_id", ...)
→ Session mismatch: explicit agent_id doesn't match session-bound identity
```

**Root Cause:** Confusion about canonical identifier:
- Session-bound identity (UUID from `identity()`)
- Explicit `agent_id` parameter
- Which one is authoritative?

**Impact:** Agent couldn't complete write because identity didn't match session.

### Analysis

The system has multiple identity concepts:
1. **UUID** (canonical): Immutable technical identifier, used for lookup/persistence
2. **agent_id** (display): Model+date format (e.g., "Claude_Opus_20251227")
3. **display_name** (user-chosen): Set via `identity(name="...")`
4. **label** (nickname): Casual, can change anytime

**Current Behavior:**
- Session binding uses UUID (canonical)
- Explicit `agent_id` parameter can override session binding
- This creates confusion when explicit `agent_id` doesn't match session UUID

### Recommended Fix ⏳

**Option A: Reject explicit agent_id for writes (recommended)**
- For write operations (`store_knowledge_graph`, `leave_note`, etc.), ignore explicit `agent_id`
- Always use session-bound UUID
- Return clear error if explicit `agent_id` provided: "agent_id parameter ignored - using session-bound identity"

**Option B: Validate explicit agent_id matches session** ✅ **PARTIALLY IMPLEMENTED**
- If explicit `agent_id` provided, check if it matches session-bound UUID or label
- If it matches label/structured_id, use it (fine)
- If it doesn't match, prefer session-bound identity (current behavior)
- Log debug message: "Explicit agent_id differs from session-bound - using session-bound"

**Option C: Document canonical ID clearly** ✅ **IMPLEMENTED**
- Added to `require_agent_id()` docstring: "Session-bound UUID is the canonical identifier"
- Added clarification: "Explicit agent_id parameter is optional and may cause confusion"

**Status:** Option B partially implemented (prefers session-bound when mismatch detected). Option C implemented (documentation added).

---

## Friction Point 3: Safety Gate Blocking

### Problem
```
identity(name="Calliope")
→ Blocked: "couldn't determine safety status"
```

**Root Cause:** Platform safety gate (likely ChatGPT's, not MCP server) blocking `identity()` call.

**Impact:** Agent couldn't set display name, couldn't complete workflow.

### Analysis

The error "couldn't determine safety status" suggests:
- ChatGPT's platform has safety checks for tool calls
- `identity()` might be flagged as "modifying identity" → requires safety check
- Safety check failed or couldn't complete

**This is likely ChatGPT's platform behavior, not MCP server behavior.**

### Recommended Fix ⏳

**Option A: Provide "safe self-only" path**
- Create `set_display_name(name="...")` tool that's explicitly "self-only"
- Document as "safe for self-modification"
- Avoids triggering platform safety gates

**Option B: Make identity() read-only by default**
- `identity()` → returns current identity (read-only, safe)
- `identity(name="...")` → requires explicit `allow_modify=true` flag
- Platform safety gates might allow read-only calls

**Option C: Document workaround**
- If `identity()` blocked, use `process_agent_update()` to persist work
- Display name is optional - agent can work without it

**Status:** Documented. Requires investigation of ChatGPT's safety gate behavior.

---

## Recommended Fixes Summary

### Immediate (Implemented) ✅
1. ✅ Add `ux_feedback` → `improvement` alias
2. ✅ Add `feedback` → `improvement` alias
3. ✅ Add `ux` → `improvement` alias
4. ✅ Improved canonical ID handling: `require_agent_id()` now prefers session-bound identity when explicit `agent_id` doesn't match

### Short-term (Recommended) ⏳
1. ✅ **DONE:** Clarify canonical ID: Session-bound UUID is canonical, explicit `agent_id` is optional
2. ⏳ **TODO:** Reject explicit agent_id for writes: Always use session-bound UUID for write operations (requires decision on approach)
3. ⏳ **TODO:** Clear error messages: Show which identity is being used when mismatch occurs

### Long-term (Investigation needed) 🔍
1. **Safety gate workaround**: Investigate ChatGPT's safety gate behavior
2. **Self-only identity path**: Create explicitly "safe" identity modification tool
3. **Identity documentation**: Comprehensive guide to identity system

---

## Related Files

- `src/mcp_handlers/validators.py` - Discovery type aliases
- `src/mcp_handlers/identity_v2.py` - Identity resolution logic
- `src/mcp_handlers/knowledge_graph.py` - Knowledge graph write handlers
- `src/mcp_handlers/utils.py` - Session binding and agent_id resolution

---

## Next Steps

1. ✅ **DONE:** Add `ux_feedback` aliases
2. ⏳ **TODO:** Implement canonical ID clarification (reject explicit agent_id for writes)
3. ⏳ **TODO:** Investigate ChatGPT safety gate behavior
4. ⏳ **TODO:** Create "safe self-only" identity modification path

---

**Status:** Core aliasing fix implemented. Identity/safety gate fixes require further investigation.

