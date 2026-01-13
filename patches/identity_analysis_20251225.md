# Identity System Analysis & Fixes

**Date**: December 25, 2025  
**Author**: claude_opus_ux_fix_20251225

## Current Architecture

### Identity Flow
```
[Client Request]
       ↓
[SSE/REST Dispatch] → set_session_context(session_key, client_session_id, agent_id)
       ↓
[Tool Handler] → calls get_bound_agent_id() or require_registered_agent()
       ↓
[success_response()] → computes agent_signature from context + metadata
       ↓
[Response to Client]
```

### Three Session Key Formats
1. `agent-{uuid[:12]}` - **Stable**, recommended for session continuity
2. `IP:PORT:HASH` - Ephemeral SSE (changes per connection)
3. `stdio:{PID}` - Stable for Claude Desktop

### Identity Resolution Chain (5+ methods)
```python
# In identity() handler:
1. Check injected agent_id (X-Agent-Id header)
2. _get_identity_record_async() → PostgreSQL + Redis + metadata scan
3. get_bound_agent_id() → sync lookup
4. Metadata active_session_key match
5. _find_recent_binding_via_metadata()
```

## Problems Identified

### 1. Signature Computation Duplication
Both `success_response()` and `error_response()` independently compute agent_signature.
They can return different values if:
- Context is stale
- Metadata changed between calls
- Different lookup paths succeed

### 2. Debug Logging Noise
Many `[SESSION_DEBUG]` logs clutter production output:
```python
logger.info(f"[SESSION_DEBUG] ...")  # ~20 instances
```

### 3. Signature Always Present
Even for tools that don't need identity tracking, ~100 bytes added per response.

### 4. Complex Fallback Chain
5+ methods to find binding creates:
- Performance overhead
- Unpredictable behavior
- Hard to debug

## Fixes Implemented

### Fix 1: lite_response Option (Already Done)
```python
# Any tool can suppress signature
leave_note(summary="test", lite_response=True)
```

### Fix 2: Centralized Signature Computation (NEW)
Extract signature logic into a single function that both `success_response()` 
and `error_response()` call.

### Fix 3: Reduce Debug Logging (NEW)
Change `logger.info("[SESSION_DEBUG]...")` to `logger.debug(...)` for production.

### Fix 4: Document Session Key Strategy
Clear documentation of when to use which format.

---

## Implementation Details
