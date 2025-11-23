# MCP Concurrency Architecture

**Date:** November 20, 2025  
**Issue:** Understanding how multiple agents can use MCP simultaneously  
**Status:** ✅ Documented

---

## 🎯 The Architecture

### How MCP Servers Work

**MCP uses stdio (standard input/output) for communication:**
- Each client (Cursor window, Claude Desktop instance) spawns **ONE process**
- That process communicates via `stdin`/`stdout` pipes
- **stdio is inherently sequential** - messages are serialized through the pipe

### Process Model

```
Client 1 (Cursor Window 1)
  └── Process PID 12345 ──┐
                          │
Client 2 (Cursor Window 2) │  All share the same
  └── Process PID 12346 ──┤  metadata file
                          │  (agent_metadata.json)
Client 3 (Claude Desktop)  │
  └── Process PID 12347 ──┘
```

**Key Point:** Each client gets its own process, but they all write to the same metadata file.

---

## 🔍 Concurrency Levels

### Level 1: Single Client, Multiple Agents

**Scenario:** One Cursor window, multiple agents (different agent_ids)

**Behavior:**
- ✅ **Different agent IDs** = Different locks = Can operate independently
- ⚠️ **Same stdio connection** = Requests serialized through single pipe
- ⚠️ **Async but sequential** = Server can handle async, but stdio serializes messages

**Example:**
```
Agent A: process_agent_update(agent_id="agent_1")
Agent B: process_agent_update(agent_id="agent_2")
```

**What happens:**
1. Request A arrives → processed → response sent
2. Request B arrives → processed → response sent
3. **Sequential through stdio**, but different agent locks prevent conflicts

**Result:** ✅ Works, but requests are serialized (one at a time through the pipe)

---

### Level 2: Multiple Clients, Multiple Agents

**Scenario:** Multiple Cursor windows, each with different agents

**Behavior:**
- ✅ **Different processes** = True parallelism
- ✅ **Different agent IDs** = Different locks
- ✅ **Different stdio connections** = Concurrent processing

**Example:**
```
Cursor Window 1 (PID 12345):
  Agent A: process_agent_update(agent_id="agent_1")

Cursor Window 2 (PID 12346):
  Agent B: process_agent_update(agent_id="agent_2")
```

**What happens:**
1. Process 12345 handles Agent A (lock_A, metadata lock)
2. Process 12346 handles Agent B (lock_B, metadata lock)
3. **True concurrency** - both can run simultaneously

**Result:** ✅ True simultaneous operation

---

## 🚨 The Bottleneck

### Single Client Limitation

**Problem:** Within one client (one Cursor window), requests are serialized:

```
Timeline for Single Client:
t0: Agent A request arrives
t1: Agent A processing (acquires lock_A)
t2: Agent A writes metadata (acquires metadata lock)
t3: Agent A completes, releases locks
t4: Agent B request arrives (waited for Agent A to finish)
t5: Agent B processing...
```

**Why:** stdio pipe is sequential - messages must be read/written in order.

### Multiple Client Advantage

**Solution:** Multiple clients = multiple processes = true concurrency:

```
Timeline for Multiple Clients:
t0: Client 1 - Agent A request arrives
t0: Client 2 - Agent B request arrives (simultaneous!)
t1: Both processing in parallel (different processes)
t2: Both write metadata (serialized by metadata lock, but processing is parallel)
```

---

## ✅ What We Fixed

### Metadata Lock Fix

**Before:**
- Multiple processes writing to metadata file simultaneously
- Race conditions, lost updates, corruption

**After:**
- Global metadata lock prevents concurrent writes
- Each process waits for lock, then writes
- Safe concurrent access from multiple processes

**Impact:**
- ✅ Multiple clients can use MCP simultaneously
- ✅ No metadata corruption
- ⚠️ Single client still serializes requests (stdio limitation)

---

## 📊 Concurrency Summary

| Scenario | Concurrency | Bottleneck |
|----------|-------------|------------|
| **Single client, single agent** | ❌ Sequential | stdio pipe |
| **Single client, multiple agents** | ⚠️ Serialized | stdio pipe |
| **Multiple clients, single agent** | ✅ Parallel | None (different processes) |
| **Multiple clients, multiple agents** | ✅ Parallel | None (different processes) |

---

## 🎯 Key Insights

1. **stdio = Sequential per client**
   - Each client gets one process
   - Requests from same client are serialized
   - This is an MCP protocol limitation, not our code

2. **Multiple clients = True parallelism**
   - Different processes = different stdio connections
   - Can process requests simultaneously
   - Metadata lock ensures safe writes

3. **Agent locks + Metadata lock = Safe concurrency**
   - Per-agent locks prevent agent state conflicts
   - Global metadata lock prevents file corruption
   - Works correctly for multiple clients

---

## 🔧 Recommendations

### For Maximum Concurrency

**Use multiple clients:**
- Open multiple Cursor windows
- Each window = separate process = parallel processing
- Each agent gets its own agent_id = no conflicts

### For Single Client

**Accept serialization:**
- Requests will be processed one at a time
- This is expected behavior for stdio-based MCP
- Agent locks prevent conflicts, but stdio serializes

### Future Enhancement (If Needed)

**Consider HTTP-based MCP:**
- HTTP allows true concurrent connections
- Would require different MCP transport
- Current stdio approach is standard and works well

---

## 📚 Related Documentation

- **Metadata Lock Fix**: `docs/analysis/METADATA_LOCK_FIX.md`
- **Too Many Cooks Incident**: `docs/analysis/TOO_MANY_COOKS_INCIDENT.md`
- **Process Management**: `docs/archive/PROCESS_MANAGEMENT_FIXES.md`

---

**Conclusion:** The system supports true simultaneous operation **across multiple clients**. Within a single client, requests are serialized due to stdio limitations, but this is expected MCP behavior and doesn't cause conflicts.

