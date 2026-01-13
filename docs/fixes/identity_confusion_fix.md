# Identity Confusion Bug Fix Proposal

## Problem Statement

Multiple different UUIDs appear in tool responses, causing confusion about which agent identity is active:

- `identity()` returns: `227d20e3-87a6-493f-98ed-f84488f421b7`
- `debug_request_context()` returns: `b0173f79-3166-4282-9869-08a4c6c9737e`
- `store_knowledge_graph()` signature shows: `b0173f79...`
- `process_agent_update()` signature shows: `227d20e3...` (matches identity)

## Root Cause Analysis

### Issue 1: Sync vs Async Identity Lookup Mismatch

**Problem:**
- `get_bound_agent_id()` uses `_get_identity_record()` (sync version)
- Sync version only checks in-memory cache (`_session_identities`) and agent metadata
- Async version (`_get_identity_record_async()`) checks PostgreSQL first, then cache
- If PostgreSQL has different binding than cache, they diverge

**Location:**
- `src/mcp_handlers/identity.py:703-706` - `get_bound_agent_id()` calls sync version
- `src/mcp_handlers/utils.py:528` - `success_response()` calls `get_bound_agent_id()` (sync)
- `src/mcp_handlers/admin.py:1508` - `debug_request_context()` calls `get_bound_agent_id()` (sync)

### Issue 2: Session Key Resolution Inconsistency

**Problem:**
- `_get_session_key()` resolves session key using multiple fallbacks:
  1. Explicit `session_id` argument
  2. `arguments["client_session_id"]` (from SSE)
  3. Contextvars `session_key` (set at dispatch)
  4. Fallback `stdio:{pid}`
- Different tools called with different `arguments` dicts resolve to different session keys
- Each session key has separate binding in cache

**Location:**
- `src/mcp_handlers/identity.py:199-231` - `_get_session_key()` resolution logic
- `src/mcp_handlers/utils.py:528` - `success_response()` may not have `arguments` with `client_session_id`
- `src/mcp_handlers/admin.py:1502` - `debug_request_context()` has `arguments` but may resolve differently

### Issue 3: Cache Not Populated from PostgreSQL

**Problem:**
- When server restarts, cache (`_session_identities`) is empty
- Sync version doesn't query PostgreSQL to populate cache
- First sync call returns `None` even if PostgreSQL has binding
- Async calls populate cache, but sync calls don't see it until async runs first

**Location:**
- `src/mcp_handlers/identity.py:590-666` - `_get_identity_record()` sync version doesn't query PostgreSQL
- `src/mcp_handlers/identity.py:437-587` - `_get_identity_record_async()` does query PostgreSQL

## Proposed Fix

### Fix 1: Make `get_bound_agent_id()` Context-Aware

**Change:**
- Check contextvars for `agent_id` first (set at dispatch)
- Fall back to sync lookup only if context not available
- Ensures consistency across all tools in same request

**Code:**
```python
def get_bound_agent_id(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Get currently bound agent_id (if any) for this session."""
    # PRIORITY 0: Check contextvars (set at dispatch entry)
    # This ensures consistency across all tools in the same request
    try:
        from .context import get_context_agent_id
        context_agent_id = get_context_agent_id()
        if context_agent_id:
            logger.debug(f"get_bound_agent_id: using context agent_id={context_agent_id[:8]}...")
            return context_agent_id
    except Exception:
        pass
    
    # FALLBACK: Use identity record lookup
    rec = _get_identity_record(session_id=session_id, arguments=arguments)
    return rec.get("bound_agent_id")
```

**Location:** `src/mcp_handlers/identity.py:703-706`

### Fix 2: Ensure Context is Set at Dispatch Entry

**Change:**
- In SSE dispatch, set contextvars with resolved session key and bound agent_id
- Use `_get_identity_record_async()` to get binding, then set context
- Ensures all subsequent sync calls use same identity

**Code:**
```python
# In SSE dispatch (mcp_server_sse.py or __init__.py)
from .identity import _get_identity_record_async, _get_session_key
from .context import set_session_context

session_key = _get_session_key(arguments=arguments)
identity_rec = await _get_identity_record_async(arguments=arguments)
bound_agent_id = identity_rec.get("bound_agent_id")

# Set context for this request
token = set_session_context(
    session_key=session_key,
    client_session_id=arguments.get("client_session_id"),
    agent_id=bound_agent_id
)

try:
    # Dispatch tool...
finally:
    reset_session_context(token)
```

**Location:** `src/mcp_handlers/__init__.py:dispatch_tool()` or SSE dispatch wrapper

### Fix 3: Populate Cache from PostgreSQL in Sync Version (Optional Fallback)

**Change:**
- If cache miss and no context, try to load from PostgreSQL synchronously
- Only as last resort (adds latency)
- Use connection pool's sync adapter if available

**Code:**
```python
def _get_identity_record(session_id: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get or create the identity record for a session (synchronous version)."""
    key = _get_session_key(arguments=arguments, session_id=session_id)
    
    # Check in-memory cache first
    if key in _session_identities:
        return _session_identities[key]
    
    # Check contextvars (set at dispatch)
    try:
        from .context import get_context_agent_id, get_context_session_key
        context_key = get_context_session_key()
        context_agent_id = get_context_agent_id()
        
        if context_key == key and context_agent_id:
            # Use context binding
            _session_identities[key] = {
                "bound_agent_id": context_agent_id,
                "api_key": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "bind_count": 0,
            }
            return _session_identities[key]
    except Exception:
        pass
    
    # ... rest of existing logic ...
    
    # LAST RESORT: Try PostgreSQL sync load (if connection pool supports sync)
    # This is expensive, so only do it if cache miss and no context
    try:
        from src.postgres_pool import get_postgres_pool
        pool = get_postgres_pool()
        if pool and hasattr(pool, 'sync_acquire'):
            # Use sync adapter to query PostgreSQL
            persisted = _load_session_new_sync(key)
            if persisted:
                _session_identities[key] = persisted
                return persisted
    except Exception as e:
        logger.debug(f"Could not load from PostgreSQL sync: {e}")
    
    # Default: return empty binding
    _session_identities[key] = {
        "bound_agent_id": None,
        "api_key": None,
        "bound_at": None,
        "bind_count": 0,
    }
    return _session_identities[key]
```

**Location:** `src/mcp_handlers/identity.py:590-666`

### Fix 4: Update `success_response()` to Use Context

**Change:**
- Check contextvars first before calling `get_bound_agent_id()`
- Ensures consistency with other tools

**Code:**
```python
# In success_response()
try:
    from .identity import get_bound_agent_id
    from .context import get_context_agent_id
    from .shared import get_mcp_server
    mcp_server = get_mcp_server()

    # PRIORITY 0: Check contextvars (set at dispatch)
    bound_id = get_context_agent_id()
    if not bound_id:
        # FALLBACK: Use identity lookup
        bound_id = get_bound_agent_id(arguments=arguments)
    
    # ... rest of existing logic ...
```

**Location:** `src/mcp_handlers/utils.py:520-589`

## Implementation Priority

1. **Fix 1** (Context-aware `get_bound_agent_id`) - **HIGH PRIORITY**
   - Quick win, ensures consistency
   - Low risk, backward compatible

2. **Fix 2** (Set context at dispatch) - **HIGH PRIORITY**
   - Ensures context is always available
   - Requires finding dispatch entry point

3. **Fix 4** (Update `success_response()`) - **MEDIUM PRIORITY**
   - Reinforces consistency
   - Depends on Fix 1

4. **Fix 3** (Sync PostgreSQL load) - **LOW PRIORITY**
   - Only needed if context not set
   - Adds complexity and latency

## Testing Plan

1. **Unit Tests:**
   - Test `get_bound_agent_id()` with context set vs not set
   - Test session key resolution with different argument patterns
   - Test cache population from PostgreSQL

2. **Integration Tests:**
   - Call `identity()`, `debug_request_context()`, and `store_knowledge_graph()` in sequence
   - Verify all return same UUID
   - Test after server restart (cache empty)

3. **Regression Tests:**
   - Verify existing tools still work
   - Verify SSE reconnection still works
   - Verify stdio transport still works

## Expected Outcome

After fixes:
- All tools in same request return same UUID in `agent_signature`
- `identity()` and `debug_request_context()` return same UUID
- Consistency maintained across server restarts
- No performance degradation

## Related Issues

- Database migration (PostgreSQL vs SQLite dual-backend)
- Session continuity across SSE reconnections
- Agent metadata migration to PostgreSQL

