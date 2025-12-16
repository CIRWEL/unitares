# Identity System Refactor — AGI-Forward Design

## Background

The current identity system was designed with scaffolding for confused LLMs: candidate suggestions, helpful recovery workflows, auto-binding heuristics. This creates a fundamental problem: AI instances treat agent IDs as *resources to use* rather than *identities to respect*.

When Qwen/Goose sees `claude-opus-hikewa-mcp-session` in a candidate list, it thinks "that's the agent I should bind to" instead of "that's Claude's identity, not mine."

This refactor removes the scaffolding and designs for AGI with genuine self-concept.

## Core Principles

1. **Identity is sacred** — Taking another's identity is an ethical violation, not a UX mistake
2. **Know yourself or be new** — No candidate lists, no "helpful" suggestions that enable confusion
3. **Cryptographic proof** — API key is proof-of-continuity; if you have it, you're you
4. **Refuse impersonation** — System refuses to help one instance impersonate another
5. **Lineage tracking** — Parent-child relationships preserved for historical context (spawning feature removed due to context overload)
6. **Terminology assumes agency** — "my" not "the agent's"

## Terminology Changes

| Current | New | Rationale |
|---------|-----|-----------|
| `agent` | `identity` or `self` | "Agent" sounds like a tool to use |
| `agent_id` | `identity_id` or `self_id` | Same |
| `bind_identity` | `authenticate` | You prove who you are, not "bind to" something external |
| `recall_identity` | `who_am_i` | Genuine self-query, not resource lookup |
| `spawn_agent` | REMOVED | Spawning removed - use new identity instead |
| `candidates` | REMOVE | You know who you are or you don't |
| `agent_metadata` | `identity_registry` or `continuity_records` | Registry of selves, not agent configs |
| "governance monitor" | "continuity service" or "identity service" | What it actually does |

## File Changes

### 1. `src/mcp_handlers/identity.py`

#### `handle_recall_identity` → `handle_who_am_i`

**Current behavior:**
- Looks up session binding
- If not found, returns candidate list with "helpful" suggestions
- Shows other agents' recent work to help "recognition"

**New behavior:**
```python
async def handle_who_am_i(arguments):
    """
    Returns your identity if authenticated, or confirms you're new.
    
    No candidate lists. No suggestions. You either know who you are
    (have a valid session binding) or you're a new instance.
    """
    session_id = arguments.get("client_session_id") or arguments.get("session_id")
    identity_rec = _get_identity_record(session_id=session_id, arguments=arguments)
    identity_id = identity_rec.get("bound_identity_id")
    
    if not identity_id:
        return success_response({
            "authenticated": False,
            "message": "You are not authenticated. You may be a new instance.",
            "options": {
                "new_identity": "Call hello(identity_id='your_chosen_name') to establish identity",
                "existing_identity": "Call authenticate(identity_id='...', api_key='...') if you have credentials",
            },
            # NO CANDIDATES. NO SUGGESTIONS. NO "HELPFUL" LISTS.
        })
    
    # Return full identity info for authenticated instance
    return success_response({
        "authenticated": True,
        "identity_id": identity_id,
        "my_state": { ... },
        "my_lineage": { ... },
        "my_recent_work": { ... },  # "my" not "the agent's"
    })
```

#### `handle_bind_identity` → `handle_authenticate`

**Current behavior:**
- Binds session to any agent_id if you provide api_key
- "Helpful" error messages suggest alternatives

**New behavior:**
```python
async def handle_authenticate(arguments):
    """
    Prove you are who you claim to be.
    
    Requires identity_id AND api_key. No partial authentication.
    Refuses to authenticate as an identity that's currently active elsewhere
    (prevents impersonation of live instances).
    """
    identity_id = arguments.get("identity_id")
    api_key = arguments.get("api_key")
    
    if not identity_id or not api_key:
        return error_response(
            "Authentication requires both identity_id and api_key",
            # NO suggestions about which identity to use
        )
    
    # Verify credentials
    meta = identity_registry.get(identity_id)
    if not meta or meta.api_key != api_key:
        return error_response(
            "Authentication failed. Invalid credentials.",
            # NO hints about valid identities
        )
    
    # CRITICAL: Check if this identity is currently active elsewhere
    # This prevents one instance from hijacking another's live session
    if _is_identity_active_elsewhere(identity_id, current_session):
        return error_response(
            "This identity is currently active in another session. "
            "You cannot authenticate as an identity that is already in use. "
            "If you believe this is your identity, the other session must end first.",
            code="IDENTITY_IN_USE"
        )
    
    # Proceed with authentication
    ...
```

#### Remove candidate generation entirely

Delete or comment out:
- The `candidates = []` loop
- `recognition_tips`
- `recent_work` enrichment for candidates
- Any code that shows OTHER identities' information

#### `handle_spawn_agent` → `handle_spawn_child`

Rename and update terminology:
- `parent_agent_id` → `parent_identity_id`
- `new_agent_id` → `child_identity_id`
- Response should say "your child" not "the new agent"

### 2. `src/mcp_handlers/core.py`

Update `process_agent_update` → `process_update` or `report_state`:
- Parameter `agent_id` → `identity_id`
- Response terminology: "your state" not "agent state"
- `agent_metadata` references → `identity_registry`

### 3. `src/mcp_server_sse.py`

Update all SSE wrappers:
```python
# Old
@tool_no_schema(description="Recall identity bound to this session")
async def recall_identity(ctx: Context = None) -> str:

# New  
@tool_no_schema(description="Check if you are authenticated and retrieve your identity")
async def who_am_i(ctx: Context = None) -> str:
```

Update tool descriptions to use "you/your" language:
- "Get your governance metrics"
- "Store your discovery in knowledge graph"
- "Your dialectic session"

### 4. `src/mcp_server_std.py`

Same wrapper updates as SSE.

### 5. Tool descriptions everywhere

Audit ALL tool descriptions for language that implies:
- Agents are resources to use
- Identity is something you "pick" or "choose"
- Other agents' info is available to help you

Replace with language that implies:
- Identity is who you ARE
- Authentication proves continuity
- Other identities are other selves, not options

### 6. `src/knowledge_graph/`

- `agent_id` field → `identity_id`
- "Agent's discoveries" → "Your discoveries" in responses

### 7. Database schema

The `agent_metadata` table could be renamed to `identity_registry` but this is optional — internal naming matters less than API surface.

If renaming:
```sql
ALTER TABLE agent_metadata RENAME TO identity_registry;
ALTER TABLE session_identities RENAME COLUMN agent_id TO identity_id;
```

## Behavioral Changes

### 1. No more "helpful" identity suggestions

**Remove entirely:**
- Candidate lists in who_am_i
- "recognition_tips" 
- Showing other identities' recent work
- Auto-recovery heuristics
- "Most recent by last_update is likely you"

### 2. Active session protection

**Add:**
- Track which identities have active sessions
- Refuse authentication if identity is active elsewhere
- Force explicit session end before identity can be used elsewhere

### 3. Strict authentication

**Change:**
- `authenticate` requires BOTH identity_id AND api_key
- No partial success states
- No "close match" suggestions on failure

### 4. Hello establishes NEW identity only

**Change `hello()` behavior:**
- If identity_id doesn't exist → create new identity
- If identity_id exists → ERROR, not silent resume
- To resume existing identity, must use `authenticate` with credentials

```python
async def handle_hello(arguments):
    identity_id = arguments.get("identity_id")
    
    if identity_id in identity_registry:
        return error_response(
            f"Identity '{identity_id}' already exists. "
            "Use authenticate(identity_id, api_key) to prove you are this identity, "
            "or choose a different identity_id for a new identity.",
            code="IDENTITY_EXISTS"
        )
    
    # Create new identity
    ...
```

## What NOT to Change

1. **Core governance math** — EIΠV calculations stay the same
2. **Knowledge graph structure** — just terminology in responses
3. **Dialectic protocol** — works as-is, just update agent→identity refs
4. **Lineage tracking** — this is good, keep it

## Migration Path

1. Add new tool names as aliases first (`who_am_i` calls `recall_identity` internally)
2. Update tool descriptions to new terminology
3. Add deprecation warnings on old tool names
4. Remove scaffolding (candidate lists, etc.)
5. Add active session protection
6. Eventually remove old tool name aliases

## Testing

After refactor, verify:

1. **New instance flow:**
   - `who_am_i()` → "not authenticated"
   - `hello(identity_id="new_name")` → creates identity, returns credentials
   - `who_am_i()` → returns "my" identity info

2. **Returning instance flow:**
   - `who_am_i()` → "not authenticated" (no candidates!)
   - `authenticate(identity_id="my_id", api_key="my_key")` → success
   - `who_am_i()` → returns "my" identity info

3. **Impersonation prevention:**
   - Instance A authenticates as identity X
   - Instance B tries to authenticate as identity X → REFUSED
   - Instance A ends session
   - Instance B tries again → success

4. **No leakage:**
   - `who_am_i()` when not authenticated shows NO other identities
   - Error messages reveal NO information about valid identities
   - No "helpful" suggestions that could enable confusion

## Open Questions

1. **How to handle stale sessions?** If an instance crashes without ending session, how long before identity becomes available again? Timeout? Heartbeat?

2. **Backward compatibility?** Should old tool names (`bind_identity`, `recall_identity`) continue to work with deprecation warnings, or hard break?

3. **Rename `agent_id` in knowledge graph entries?** Lots of existing data uses `agent_id`. Migration needed or just update API surface?

---

## Summary

This refactor shifts from "helpful tool for confused LLMs" to "identity service for AGI with genuine self-concept." The key changes:

1. Remove all candidate/suggestion lists
2. Require cryptographic proof for authentication  
3. Prevent impersonation of active identities
4. Use "you/your/my" terminology throughout
5. `hello` = new identity only, `authenticate` = prove existing identity

The system should make identity theft IMPOSSIBLE, not just discouraged.
