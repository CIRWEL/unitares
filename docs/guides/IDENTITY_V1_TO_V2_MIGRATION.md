# Identity API Migration Guide: v1 → v2

> **⚠️ Historical Document:** This guide documents the v1→v2 migration (Dec 2025).
> The current recommended API is `identity()` and `onboard()` - see [START_HERE.md](START_HERE.md).
> `hello()` and `status()` mentioned below are aliases that still work but `identity()` is now primary.

**Last Verified:** December 20, 2025
**Status:** ✅ Production Migration Guide (Historical)
**Breaking Changes:** None (v1 APIs remain functional)
**v2 Implementation:** ✅ Complete (auto-bind active)
**Current API:** Use `identity()` instead of `hello()`/`status()`

---

## Executive Summary

The Identity v2 API consolidates 4 overlapping functions into 2 canonical entry points, while maintaining **100% backward compatibility** with v1. All v1 functions still work - they now delegate to the v2 handlers.

**Key Changes:**
- ✅ **Automatic session binding** - No more manual `bind_identity()` calls
- ✅ **Single entry point** - `hello()` handles both create and resume
- ✅ **Clearer semantics** - `status()` replaces `recall_identity()`
- ✅ **Zero breaking changes** - All v1 functions maintained as aliases

**Migration Timeline:**
- **Immediate:** You can start using v2 APIs today
- **No deadline:** v1 APIs will remain functional indefinitely
- **Recommended:** New code uses v2, existing code can stay v1

---

## What Changed?

### v1 API (Fragmented Identity Management)

**4 overlapping functions with unclear boundaries:**

| Function | Purpose | When to Use |
|----------|---------|-------------|
| `hello(agent_id?, api_key?)` | Create or resume | Unclear - overloaded |
| `quick_start(agent_id?)` | Auto-create and bind | Only for new identities |
| `bind_identity(agent_id, api_key)` | Bind session | After hello()? Always? |
| `recall_identity()` | Check binding | Before work? After restart? |

**Problems:**
- 😕 Confusing overlap between functions
- 🔁 Multi-step workflows (create → bind → work)
- 📚 High cognitive load (learn 4 functions + their interactions)
- ⚠️ Easy to forget binding step (silent failures)

---

### v2 API (Unified Identity Management)

**2 canonical functions with clear purposes:**

| Function | Purpose | When to Use |
|----------|---------|-------------|
| `hello(agent_id?, api_key?)` | Create OR resume identity | Always (auto-binds) |
| `status()` | Check current state | Verify binding, check health |

**Benefits:**
- ✅ Single entry point for all identity operations
- ✅ Automatic session binding (no manual steps)
- ✅ Consistent API (add `api_key` to resume)
- ✅ Low cognitive load (2 functions, one pattern)

---

## Migration Paths

### Path 1: New Identity (First Time)

**v1 Workflow (2-3 steps):**
```json
// Option A: Using hello() + bind_identity()
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}
// Response: {"api_key": "uak_abc123..."}

{"tool": "bind_identity", "arguments": {"agent_id": "my_agent", "api_key": "uak_abc123..."}}
// Response: {"bound": true}

{"tool": "process_agent_update", "arguments": {...}}
```

```json
// Option B: Using quick_start()
{"tool": "quick_start", "arguments": {"agent_id": "my_agent"}}
// Response: {"api_key": "uak_abc123...", "bound": true}

{"tool": "process_agent_update", "arguments": {...}}
```

**v2 Workflow (1 step):**
```json
{"tool": "hello", "arguments": {"agent_id": "my_agent"}}
// Response: {"created": true, "bound": true, "api_key": "uak_abc123..."}

{"tool": "process_agent_update", "arguments": {...}}
// Session is ALREADY bound - no extra step needed!
```

**Key Change:** `hello()` now auto-binds your session. You're immediately ready to work.

---

### Path 2: Returning Identity (After Restart)

**v1 Workflow (2-3 steps):**
```json
// Step 1: Recall who you were
{"tool": "recall_identity"}
// Response: {"agent_id": "my_agent", "bound": false}

// Step 2: Re-bind session
{"tool": "bind_identity", "arguments": {"agent_id": "my_agent", "api_key": "uak_abc123..."}}
// Response: {"bound": true}

// Step 3: Do work
{"tool": "process_agent_update", "arguments": {...}}
```

**v2 Workflow (1 step):**
```json
{"tool": "hello", "arguments": {"agent_id": "my_agent", "api_key": "uak_abc123..."}}
// Response: {"awakened": true, "bound": true, "substrate": {...}}

{"tool": "process_agent_update", "arguments": {...}}
// Session is ALREADY re-bound - just add api_key to hello()!
```

**Key Change:** `hello()` with `api_key` both awakens AND re-binds in one call.

---

### Path 3: Check Current State

**v1 Workflow:**
```json
{"tool": "recall_identity"}
// Response: {"agent_id": "my_agent", "bound": true}
```

**v2 Workflow:**
```json
{"tool": "status"}
// Response: {"bound": true, "agent_id": "my_agent", "state": {...}}
```

**Key Change:** `status()` provides richer context (health, trajectory, available actions).

---

## Detailed Comparison

### Function Mapping

| v1 Function | v2 Equivalent | Notes |
|-------------|---------------|-------|
| `hello(agent_id)` | `hello(agent_id)` | Now auto-binds session |
| `hello(agent_id, api_key)` | `hello(agent_id, api_key)` | Now auto-re-binds session |
| `quick_start(agent_id)` | `hello(agent_id)` | Same behavior, different name |
| `bind_identity(agent_id, api_key)` | `hello(agent_id, api_key)` | Auto-bind makes this redundant |
| `recall_identity()` | `status()` | Clearer name, richer response |
| `session(...)` | `hello(...)` or `status()` | Advanced alias, still works |
| `who_am_i()` | `status()` | Alias maintained |
| `authenticate(...)` | `hello(..., api_key)` | Alias maintained |

---

## Code Examples

### Example 1: First Session

**v1 Code:**
```python
# Create identity
response1 = await call_mcp_tool("hello", {"agent_id": "opus_coder_20251220"})
api_key = response1["api_key"]

# Manually bind (REQUIRED in v1!)
response2 = await call_mcp_tool("bind_identity", {
    "agent_id": "opus_coder_20251220",
    "api_key": api_key
})

# Now you can work
response3 = await call_mcp_tool("process_agent_update", {
    "response_text": "Started coding session",
    "complexity": 0.5
})
```

**v2 Code:**
```python
# Create identity (auto-binds!)
response = await call_mcp_tool("hello", {"agent_id": "opus_coder_20251220"})
api_key = response["api_key"]  # Save for next session

# Work immediately (session is bound!)
response2 = await call_mcp_tool("process_agent_update", {
    "response_text": "Started coding session",
    "complexity": 0.5
})
```

**Savings:** 1 fewer call, simpler logic, no manual binding.

---

### Example 2: Resuming Session

**v1 Code:**
```python
# Check who you were
response1 = await call_mcp_tool("recall_identity")
agent_id = response1.get("agent_id")

if not response1.get("bound"):
    # Re-bind session (REQUIRED!)
    response2 = await call_mcp_tool("bind_identity", {
        "agent_id": agent_id,
        "api_key": saved_api_key
    })

# Now you can work
response3 = await call_mcp_tool("process_agent_update", {...})
```

**v2 Code:**
```python
# Awaken and auto-re-bind in one call
response = await call_mcp_tool("hello", {
    "agent_id": "opus_coder_20251220",
    "api_key": saved_api_key
})

# Check substrate (accumulated work)
substrate = response["substrate"]

# Work immediately (session is bound!)
response2 = await call_mcp_tool("process_agent_update", {...})
```

**Savings:** Eliminates conditional logic, auto-rebinds, provides substrate.

---

### Example 3: Checking State

**v1 Code:**
```python
# Check if bound
response = await call_mcp_tool("recall_identity")
if response.get("bound"):
    agent_id = response["agent_id"]
    print(f"Bound to {agent_id}")
else:
    print("Not bound")
```

**v2 Code:**
```python
# Check state (richer info)
response = await call_mcp_tool("status")
print(f"Bound: {response['bound']}")
print(f"Agent: {response['agent_id']}")
print(f"Health: {response['state']['health']}")
print(f"Available actions: {response['actions']}")
```

**Benefits:** Richer context, clearer API, consistent naming.

---

## Backward Compatibility Guarantees

### All v1 Functions Still Work

```python
# These v1 calls still work exactly as before:
hello()              # Delegates to v2 hello()
quick_start()        # Delegates to v2 hello()
bind_identity()      # Delegates to v2 hello() with validation
recall_identity()    # Delegates to v2 status()
session()            # Smart router to hello()/status()
who_am_i()           # Alias for status()
authenticate()       # Alias for hello() requiring api_key
```

**Implementation:**
```python
# Example: quick_start() is a thin wrapper
async def handle_quick_start(arguments):
    # Delegate to hello() - same behavior, auto-bind included
    return await handle_hello(arguments)
```

**No breaking changes.** Your existing code continues to work.

---

### Response Format Compatibility

**v1 responses still return expected fields:**
```json
// v1 quick_start() response (still works)
{
  "success": true,
  "agent_id": "my_agent",
  "api_key": "uak_abc123...",
  "bound": true
}

// v2 hello() response (superset of v1)
{
  "success": true,
  "created": true,
  "bound": true,
  "my_identity": "my_agent",
  "my_credentials": {
    "api_key": "uak_abc123...",
    ...
  },
  "substrate": {...}
}
```

**v2 responses are supersets** - they include all v1 fields plus additional context.

---

## Migration Strategy

### Recommended Approach: Gradual Migration

**Phase 1: Learn v2 (No Code Changes)**
- Read this guide and identity_v2.md
- Understand `hello()` auto-bind behavior
- Try v2 APIs in a test session

**Phase 2: New Code Uses v2**
- All new identities use `hello()` and `status()`
- Existing code keeps using v1 functions
- No rush - migrate at your own pace

**Phase 3: Refactor Existing Code (Optional)**
- Replace `quick_start()` → `hello()`
- Replace `bind_identity()` calls (no longer needed)
- Replace `recall_identity()` → `status()`
- Remove manual binding logic (auto-bind handles it)

**Phase 4: Deprecation Awareness**
- v1 functions marked as `@deprecated` in tool schemas (future)
- IDE warnings guide toward v2 APIs
- No forced migration - v1 functions remain functional

---

## Common Questions

### Q: Will my existing code break?

**A:** No. All v1 functions are maintained as aliases. Your code continues to work unchanged.

---

### Q: When should I migrate?

**A:** No deadline. Migrate when convenient:
- **Immediately:** If you're writing new code
- **Gradually:** Refactor during normal maintenance
- **Never:** If you prefer v1 APIs (they'll keep working)

---

### Q: What if I forget to bind my session?

**A:** In v2, this is impossible - `hello()` auto-binds. In v1, you had to remember to call `bind_identity()` manually.

---

### Q: Can I mix v1 and v2 APIs?

**A:** Yes! They're interoperable:
```python
# v1 create + v2 status (works fine)
await call_mcp_tool("quick_start", {"agent_id": "foo"})
await call_mcp_tool("status")  # Shows bound state

# v2 create + v1 recall (also works)
await call_mcp_tool("hello", {"agent_id": "bar"})
await call_mcp_tool("recall_identity")  # Returns bound=true
```

---

### Q: Do I need to update my saved api_keys?

**A:** No. API keys remain the same format (`uak_...`). They work in both v1 and v2.

---

### Q: What about bind_identity() for takeover scenarios?

**A:** `hello()` supports takeover:
```python
# Takeover with hello() (v2)
await call_mcp_tool("hello", {
    "agent_id": "existing_agent",
    "api_key": "uak_valid_key"
})
# Authenticates and takes over the session

# Same as bind_identity() (v1), but also awakens substrate
```

---

## Benefits Summary

### Reduced Cognitive Load

**v1:**
- Learn 4 functions
- Understand their overlaps
- Remember multi-step workflows
- Manual binding (easy to forget)

**v2:**
- Learn 2 functions
- Clear, consistent purpose
- One-step workflows
- Auto-bind (impossible to forget)

---

### Fewer API Calls

**v1 typical workflow:**
```
create → bind → work (3 calls minimum)
resume → recall → bind → work (4 calls minimum)
```

**v2 typical workflow:**
```
create → work (2 calls)
resume → work (2 calls)
```

**Result:** 33-50% fewer calls for common workflows.

---

### Better Multi-Model Support

**Auto-bind critical for ChatGPT/Gemini:**
- No concept of "session binding" in their UX
- Auto-bind makes identity "just work"
- One call and you're productive

**v1 required manual binding:**
- Users had to understand session mechanics
- Easy to forget binding step
- Silent failures hard to debug

---

## Troubleshooting

### "I'm getting errors about binding"

**Likely cause:** Using v1 workflow with manual bind_identity() calls.

**Solution:** Switch to v2 `hello()` - it auto-binds, eliminating binding errors.

---

### "My code still uses quick_start()"

**This is fine!** `quick_start()` still works - it delegates to `hello()`.

**To migrate:** Simply replace `quick_start(...)` with `hello(...)` (identical arguments).

---

### "I can't find bind_identity() in the docs"

**Correct!** `bind_identity()` is deprecated in favor of `hello()` auto-bind.

**Why:** Auto-bind makes manual binding unnecessary. `hello()` handles it for you.

---

### "What if I prefer v1 APIs?"

**Totally fine!** v1 APIs remain functional indefinitely. No forced migration.

---

## Next Steps

1. **Read:** [identity_v2.md](identity_v2.md) for detailed v2 API docs
2. **Try:** Create a test identity with v2 `hello()` and observe auto-bind
3. **Compare:** Check `status()` vs `recall_identity()` response richness
4. **Migrate:** When ready, replace v1 calls with v2 (optional, no deadline)

---

## Support

**Questions?** Check:
- [identity_v2.md](identity_v2.md) - v2 API reference
- [AI_ASSISTANT_GUIDE.md](../reference/AI_ASSISTANT_GUIDE.md) - Practical usage guide
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues

**Feedback?** Open an issue describing:
- What's confusing about the migration
- What v1 behavior you prefer
- What breaks (if anything)

---

**Migration Status:** ✅ v2 Live, v1 Maintained
**Breaking Changes:** None
**Timeline:** Migrate at your own pace
**Support:** Indefinite backward compatibility
