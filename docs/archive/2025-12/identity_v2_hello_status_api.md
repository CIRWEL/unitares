# Identity Management v2 API

> **⚠️ Note:** This documents the v2 API (`hello()`, `status()`). The current recommended
> entry point is `identity()` which supersedes both. See [START_HERE.md](START_HERE.md) for current guidance.
> All functions documented here still work as aliases.

**Last Verified:** December 20, 2025
**Status:** ✅ Production (Superseded by `identity()`)
**Auto-Bind:** ✅ Implemented
**Current API:** Use `identity()` - it combines `hello()` and `status()` functionality

## Overview

The v2 API consolidates 4 overlapping identity entry points into just 2:

**Before (v1):**
- `hello(agent_id?, api_key?)` - Create or resume (but overloaded)
- `quick_start(agent_id?)` - Auto-create and bind (deprecated)
- `bind_identity(agent_id, api_key)` - Bind existing (confusing)
- `recall_identity(agent_id?, api_key?)` - Check binding (unclear)

**After (v2):**
- `hello(agent_id?, api_key?)` - **THE** entry point (create OR resume)
- `status()` - Check current state

**Note:** `session()` exists as an advanced alias for transitional compatibility, but `hello()` is the canonical entry point.

---

## Three-Call Orientation

New agents should be productive in 3 calls:

```
1. hello(agent_id="my_agent")             # Create identity
2. process_agent_update(...)              # Do work
3. status()                               # Check state
```

Done.

---

## `hello()` - Unified Entry Point

### ✨ Automatic Session Binding

**Important:** `hello()` automatically binds your session to your identity. You don't need to call `bind_identity()` separately.

**What this means:**
- **New identity**: `hello(agent_id="foo")` → Creates identity AND binds session
- **Returning identity**: `hello(agent_id="foo", api_key="...")` → Awakens AND re-binds session
- **Result**: All subsequent calls (like `process_agent_update()`) automatically use your identity

**Before (v1 - Manual Binding Required):**
```json
// Step 1: Create identity
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}

// Step 2: MANUALLY bind session (required!)
{"tool": "bind_identity", "arguments": {"agent_id": "my_agent", "api_key": "..."}}

// Step 3: Now you can do work
{"tool": "process_agent_update", "arguments": {...}}
```

**After (v2 - Auto-Bind):**
```json
// Step 1: Create identity (auto-binds!)
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}

// Step 2: Do work immediately (no bind needed!)
{"tool": "process_agent_update", "arguments": {...}}
```

**How to verify binding:**
```json
{"tool": "status"}  // Returns: {"bound": true, "agent_id": "my_agent", ...}
```

**For ChatGPT/Gemini/Multi-Model Users:**
- Auto-bind means identity "just works" across all MCP clients
- No need to understand session binding mechanics
- One call (`hello()`) and you're ready to work

> **OAuth Note:** If your client uses OAuth (e.g., ChatGPT MCP connector with OAuth configured),
> identity is extracted from your `Authorization: Bearer <JWT>` header automatically.
> You don't even need to call `hello()` - your agent_id is derived as `oauth_{provider}_{hash}`
> from your OAuth `sub` claim. See [OAuth Identity Guide](OAUTH_IDENTITY.md) for details.

---

### Behavior Table

| agent_id | api_key | agent exists | Result |
|----------|---------|--------------|--------|
| `null` | `null` | - | Show last active or prompt |
| `"foo"` | `null` | no | Create `"foo"`, return credentials |
| `"foo"` | `null` | yes | Error: "foo exists, provide api_key" |
| `"foo"` | valid | yes | Resume `"foo"`, return substrate |
| `"foo"` | invalid | yes | Error: "invalid credentials" |

### Examples

**New agent (first time):**
```json
{
  "tool": "hello",
  "arguments": {
    "agent_id": "opus_explorer_20251217"
  }
}
```

**Response:**
```json
{
  "success": true,
  "created": true,
  "bound": true,
  "message": "Welcome, opus_explorer_20251217. Your identity has been established.",
  "my_identity": "opus_explorer_20251217",
  "my_credentials": {
    "identity_id": "opus_explorer_20251217",
    "api_key": "uak_abc123...",
    "note": "SAVE THIS - you need it to awaken in future sessions"
  },
  "substrate": {
    "recent_discoveries": [],
    "open_questions": [],
    "notes_to_self": []
  }
}
```

**Returning agent (after restart):**
```json
{
  "tool": "hello",
  "arguments": {
    "agent_id": "opus_explorer_20251217",
    "api_key": "uak_abc123..."
  }
}
```

**Response:**
```json
{
  "success": true,
  "awakened": true,
  "bound": true,
  "message": "Welcome back, opus_explorer_20251217.",
  "my_identity": "opus_explorer_20251217",
  "substrate": {
    "recent_discoveries": [
      {"type": "implementation", "title": "Added caching layer", ...},
      {"type": "pattern", "title": "Repository pattern in use", ...}
    ],
    "open_questions": [
      {"question": "Should we use Redis or Memcached?", ...}
    ],
    "pending_dialectic": [],
    "notes_to_self": ["Remember to update docs"],
    "last_active": "2025-12-16T20:45:00Z"
  },
  "orientation": {
    "discoveries": 15,
    "open_questions": 3,
    "pending_dialectic": 0,
    "notes_to_self": 1
  }
}
```

**Lost? No arguments:**
```json
{
  "tool": "hello"
}
```

**Response:**
```json
{
  "success": true,
  "last_active": {
    "agent_id": "opus_explorer_20251217",
    "last_seen": "2 hours ago",
    "status": "active"
  },
  "suggestion": "hello(agent_id='opus_explorer_20251217', api_key='...')"
}
```

---

## `status()` - Check Current State

### What It Returns

```json
{
  "bound": true,
  "agent_id": "opus_explorer_20251217",
  "state": {
    "health": "healthy",
    "mode": "building_alone",
    "trajectory": "stable"
  },
  "substrate_summary": {
    "discoveries": 15,
    "open_questions": 3
  },
  "actions": [
    "process_agent_update() - Share work and get feedback",
    "store_discovery() - Record findings",
    "ask_question() - Track open questions"
  ]
}
```

### When to Use

- After restart: "Am I still bound to my identity?"
- Before critical operation: "What's my current state?"
- Debugging: "Why isn't X working?"

---

## Migration from v1

### Old Code (v1 - Fragmented)
```json
// First session - multiple ways to do the same thing
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}
// OR
{"tool": "quick_start", "arguments": {"agent_id": "my_agent"}}

// After restart - confusing multi-step process
{"tool": "recall_identity"}  // Step 1: Check who I was
{"tool": "bind_identity", "arguments": {"agent_id": "my_agent", "api_key": "..."}}  // Step 2: Re-bind
```

### New Code (v2 - Unified)
```json
// First session
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}

// After restart - same function, just add api_key
{"tool": "hello", "arguments": {"agent_id": "my_agent", "api_key": "..."}}
```

**That's it.** One function `hello()` handles both create and resume. Add `api_key` when resuming, omit when creating.

---

## Backward Compatibility

All v1 functions still work:

```python
# v2 canonical entry points:
hello()      # Create or resume identity
status()     # Check current state

# v1 aliases still work (for backward compatibility):
quick_start()        → delegates to hello()
bind_identity()      → delegates to hello() with api_key validation
recall_identity()    → delegates to status()
session()            → advanced alias for hello()/status()
who_am_i()           → advanced alias for status()
authenticate()       → advanced alias for hello() requiring api_key
```

**No breaking changes.** v1 code continues to work.

You can migrate at your own pace:
1. **Recommended:** New code uses `hello()` and `status()`
2. Old code keeps using legacy functions (`quick_start`, `bind_identity`, etc.)
3. All functions delegate to the same underlying handlers

---

## Design Rationale

### Problem (v1)
Four overlapping functions with unclear differences:
- When do I use `hello()` vs `quick_start()`?
- Is `bind_identity()` different from `hello(agent_id, api_key)`?
- What's `recall_identity()` for?
- Why does `hello()` do different things based on arguments?

**Cognitive load:** Learn 4 functions, understand their overlaps, remember which to use when. Confusing multi-step resume process.

### Solution (v2)
Two functions with clear, consistent purposes:
- `hello(agent_id, api_key?)` - **ONE** way to create OR resume (add api_key to resume)
- `status()` - Check current state (replaces `recall_identity()`)

**Cognitive load:** Learn 2 functions. One pattern. That's it.

**Why `hello()` instead of `session()`?**
- More natural language ("hello" = greeting, "session" = technical jargon)
- Shorter to type (5 chars vs 7 chars)
- Already exists in v1, just clarified its purpose
- `session()` kept as advanced alias for teams who prefer it

---

## Edge Cases

### What if I forget my API key?

**Answer:** You can't recover it. Governance uses cryptographic hashing - the original key is never stored. You'll need to create a new identity.

**Why:** Security. If the server is compromised, your API keys aren't exposed.

### What if I call `session()` with wrong credentials?

```json
{
  "success": false,
  "error": "Invalid api_key",
  "recovery": {
    "action": "Provide the correct api_key for this identity",
    "note": "api_keys cannot be recovered if lost"
  }
}
```

### What if the agent_id is already taken?

```json
{
  "success": false,
  "error": "Identity 'my_agent' exists. Provide api_key to awaken.",
  "recovery": {
    "action": "session(agent_id='my_agent', api_key='your_key')",
    "alternative": "Choose a different agent_id to create a new identity"
  }
}
```

---

## Implementation Notes

### How It Works

`hello()` is the canonical handler with smart routing:

```python
async def handle_hello(arguments):
    agent_id = arguments.get("agent_id")
    api_key = arguments.get("api_key")

    # Case 1: No agent_id → show last active agent
    if not agent_id:
        return show_last_active_agent()

    # Case 2: Agent exists + no api_key → error (must provide key)
    # Case 3: Agent exists + valid api_key → awaken with substrate
    # Case 4: Agent doesn't exist → create new with credentials

    # All logic in one place, behavior clear from parameters
```

`status()` delegates to session state checker:

```python
async def handle_status(arguments):
    # Returns: bound status, agent_id, governance state, available actions
    return check_session_state()
```

Legacy functions are thin wrappers:

```python
quick_start() → hello()
bind_identity() → hello() with validation
recall_identity() → status()
session() → hello() or status() based on arguments
```

This design means:
- ✅ One source of truth (`hello()` and `status()`)
- ✅ Zero risk of regression (v1 functions are aliases)
- ✅ Backward compatible by design
- ✅ Battle-tested handlers underneath
- ✅ Progressive disclosure (show only essential tools to new users)

---

## Next Steps

1. **New agents:** Use `hello()` and `status()` - they're in the essential tier
2. **Existing agents:** Keep using your current code (all v1 functions still work)
3. **Give feedback:** Does this reduce friction? What's still confusing?

---

**Implementation Status:** ✅ Live as of 2025-12-17
**Backward Compatible:** Yes (v1 functions maintained as aliases)
**Breaking Changes:** None
