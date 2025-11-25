# CLI Logging Architecture - Ephemeral vs Persistent

**Date:** November 24, 2025  
**Issue:** CLI scripts spawn ephemeral MCP processes, losing state  
**Status:** ⚠️ By Design (with limitations)

---

## 🎯 Discovery

**Observation:**
- `agent_self_log.py` (or similar CLI script) spawns new MCP server process each call
- Each call starts fresh (no state loading)
- Metadata updates happen in memory but aren't persisted
- Governance history isn't maintained across calls

**Evidence:**
- Same coherence (ρ=0.649) every time
- `total_updates` counter shows 0 (should be 3)
- Governance history not persisted

---

## 📐 Current Architecture

### Ephemeral CLI Script Pattern

```python
# agent_self_log.py (hypothetical)
def log_update(agent_id, parameters, drift, text):
    # Spawn new MCP server process
    result = subprocess.run([
        "python", "src/mcp_server_std.py",
        "--tool", "process_agent_update",
        "--agent_id", agent_id,
        ...
    ])
    
    # Process exits → state lost
    # Metadata update counter NOT saved
```

**What happens:**
1. Spawn new MCP server process
2. Create NEW monitor (no state loading)
3. Process update → returns decision
4. Update `metadata.total_updates++` in memory
5. Exit → state & history lost
6. Metadata update counter NOT saved to disk

**Result:**
- ✅ Decision returned correctly
- ✅ Metadata tags/notes saved (if saved before exit)
- ❌ `total_updates` counter not persisted
- ❌ Governance history not maintained
- ❌ Same coherence every time (starts fresh)

---

## 🔍 Root Cause Analysis

### Why Metadata Updates Aren't Saved

**In `process_agent_update` handler:**
```python
# Line 1748-1752
meta = agent_metadata[agent_id]
meta.last_update = datetime.now().isoformat()
meta.total_updates += 1
await save_metadata_async()  # Async save
```

**Problem:**
- `save_metadata_async()` runs in thread pool
- Process may exit before async save completes
- No guarantee metadata is written before exit

### Why State Isn't Persisted

**In `process_agent_update` handler:**
```python
# Line 1754-1755
await save_monitor_state_async(agent_id, monitor)
```

**Problem:**
- Async save may not complete before process exits
- Even if saved, next call starts fresh (doesn't load)

---

## ✅ Proper Workflow (Persistent MCP Server)

**Use persistent MCP server (via Cursor/Claude Desktop):**

1. MCP server runs continuously
2. Loads existing state on startup (`load_state=True`)
3. Maintains history across updates
4. Persists state to disk after each update
5. Export works properly

**Example:**
```python
# In persistent MCP server
monitor = UNITARESMonitor(agent_id, load_state=True)  # Loads from disk
result = monitor.process_update(agent_state)
# State persisted, history maintained
```

---

## 🎯 Recommendations

### Option 1: Add State Persistence to CLI Script ⭐ RECOMMENDED

**Modify CLI script to:**
- Load existing state before processing
- Save state after processing
- Wait for async saves to complete

**Implementation:**
```python
# agent_self_log.py
def log_update(agent_id, parameters, drift, text):
    # Use MCP client library (not subprocess)
    from mcp import Client
    
    client = Client("governance-monitor-v1")
    
    # Process update (server loads state automatically)
    result = client.call_tool("process_agent_update", {
        "agent_id": agent_id,
        "parameters": parameters,
        ...
    })
    
    # Server persists state automatically
    return result
```

**Pros:**
- Full state persistence
- History maintained
- Proper governance tracking

**Cons:**
- Requires MCP client library
- More complex than subprocess

### Option 2: Document as Ephemeral (Current Behavior)

**Document that CLI logging is lightweight:**
- Metadata only (tags/notes)
- No state persistence
- No history tracking
- Ephemeral by design

**Pros:**
- Simple, fast
- No state management overhead
- Good for lightweight logging

**Cons:**
- Loses governance history
- Metrics don't evolve
- Same coherence every time

### Option 3: Create Persistent CLI Server Wrapper

**Create wrapper that maintains persistent server:**
```python
# persistent_cli_server.py
class PersistentCLIServer:
    def __init__(self):
        self.server = start_mcp_server()  # Keep running
        self.client = connect_to_server()
    
    def log_update(self, agent_id, ...):
        # Uses persistent server
        return self.client.call_tool(...)
```

**Pros:**
- Full persistence
- Reuses server process
- Efficient

**Cons:**
- More complex
- Requires server management

---

## 💡 Recommendation

**For this session:** Option 2 (Document as Ephemeral)

**Rationale:**
- CLI logging is lightweight by design
- Metadata (tags/notes) is persisted
- Governance metrics are ephemeral (acceptable for logging)
- Full persistence requires persistent server

**For production:** Option 1 (Add State Persistence)

**Rationale:**
- Proper governance tracking requires state
- History enables pattern analysis
- Metrics should evolve over time

---

## 📊 Current Behavior Summary

| Feature | Ephemeral CLI | Persistent Server |
|---------|---------------|-------------------|
| Decision returned | ✅ | ✅ |
| Metadata tags/notes | ✅ Saved | ✅ Saved |
| Metadata `total_updates` | ❌ Not saved | ✅ Saved |
| Governance history | ❌ Not maintained | ✅ Maintained |
| State evolution | ❌ Always fresh | ✅ Evolves |
| Coherence tracking | ❌ Same every time | ✅ Changes |

---

## 🎯 Is This a Bug?

**Answer: It depends on the use case.**

**If CLI logging is meant to be lightweight:**
- ✅ By design (ephemeral logging)
- Document behavior clearly

**If CLI logging should track governance:**
- ❌ Bug (needs state persistence)
- Implement Option 1

**For this session:**
- Metadata is documented (tags/notes)
- Governance metrics are ephemeral
- This is a legitimate use case for lightweight logging

---

**Status:** Documented - Behavior is by design for ephemeral CLI, but can be enhanced for full persistence

