# Agent Limit Analysis & Recommendations

**Date**: 2025-11-19  
**Context**: VC Meeting Friday Morning  
**Request**: Increase maximum agents two-fold

## Current Limits

### 1. **MAX_KEEP_PROCESSES = 9**
- **What it is**: Maximum MCP server processes to keep before cleanup
- **Current**: 9 processes
- **2x increase**: 18 processes
- **Impact**: Allows more concurrent MCP clients (Cursor, Claude Desktop, etc.)

### 2. **HISTORY_WINDOW = 1000**
- **What it is**: Number of historical updates stored per agent
- **Current**: 1000 updates
- **2x increase**: 2000 updates
- **Impact**: More history per agent, higher memory usage

### 3. **No Hard Agent Limit**
- **Current**: No explicit limit on number of agents
- **Practical limit**: Memory and performance constraints

## Memory Analysis

### Per-Agent Memory Estimate
- **State variables**: ~200 bytes (E, I, S, V, coherence, lambda1, etc.)
- **History arrays** (1000 entries each):
  - V_history: ~8 KB
  - coherence_history: ~8 KB
  - risk_history: ~8 KB
  - decision_history: ~20 KB
- **Monitor overhead**: ~500 bytes
- **Total per agent**: ~45 KB

### Scaling Estimates
- **10 agents**: ~450 KB
- **50 agents**: ~2.25 MB
- **100 agents**: ~4.5 MB
- **200 agents**: ~9 MB
- **500 agents**: ~22.5 MB

**Verdict**: Memory is NOT a constraint for reasonable agent counts.

## Recommendations

### ✅ **Option 1: Increase MAX_KEEP_PROCESSES (Recommended)**

**Change**: `MAX_KEEP_PROCESSES = 9` → `MAX_KEEP_PROCESSES = 18`

**Rationale**:
- Most likely what you need for VC demo
- Allows more concurrent MCP clients
- Low risk (just process management)
- No performance impact

**Code Change**:
```python
# In src/mcp_server_std.py line 68
MAX_KEEP_PROCESSES = 18  # Increased for VC demo (was 9)
```

**Also update**:
- `src/process_cleanup.py` default parameter (line 41)

### ⚠️ **Option 2: Increase HISTORY_WINDOW (Consider Carefully)**

**Change**: `HISTORY_WINDOW = 1000` → `HISTORY_WINDOW = 2000`

**Rationale**:
- More historical data for analysis
- Useful for long-running agents
- Memory impact: 2x per agent

**Trade-offs**:
- ✅ More data for VC demo
- ⚠️ 2x memory usage per agent
- ⚠️ Slower history operations (trimming, export)

**Code Change**:
```python
# In config/governance_config.py line 319
HISTORY_WINDOW = 2000  # Increased for VC demo (was 1000)
```

### ❌ **Option 3: Add Hard Agent Limit (Not Recommended)**

**Why not**:
- No current need (memory is fine)
- Adds unnecessary complexity
- Could limit legitimate use cases

## VC Demo Considerations

### What You'll Likely Need:
1. **Multiple concurrent clients** → Increase `MAX_KEEP_PROCESSES`
2. **More agents visible** → Already supported (no limit)
3. **Longer history** → Consider `HISTORY_WINDOW` increase

### Recommended Configuration for VC:
```python
MAX_KEEP_PROCESSES = 18  # Support more concurrent clients
HISTORY_WINDOW = 1000     # Keep current (sufficient for demo)
```

## Implementation Plan

### Quick Win (5 minutes):
1. Update `MAX_KEEP_PROCESSES` to 18
2. Update `process_cleanup.py` default parameter
3. Test with multiple clients

### If More History Needed:
1. Update `HISTORY_WINDOW` to 2000
2. Monitor memory usage
3. Test export performance

## Performance Impact Assessment

### MAX_KEEP_PROCESSES = 18:
- **Memory**: Negligible (just process tracking)
- **CPU**: Negligible (cleanup runs on startup)
- **Risk**: Low (just allows more processes)

### HISTORY_WINDOW = 2000:
- **Memory**: 2x per agent (~90 KB per agent)
- **CPU**: Slightly slower trimming/export
- **Risk**: Low-Medium (monitor if many agents)

## Final Recommendation

**For VC Meeting Friday Morning:**

1. ✅ **Increase `MAX_KEEP_PROCESSES` to 18** (definitely do this)
   - Low risk, high value
   - Supports demo scenarios
   - Quick to implement

2. ⚠️ **Keep `HISTORY_WINDOW` at 1000** (unless you need longer history)
   - Current value is sufficient
   - Avoid unnecessary memory increase
   - Can increase later if needed

3. ✅ **No agent limit needed** (already unlimited)

**Total Implementation Time**: ~5 minutes

---

**Ready to implement?** I can make the changes now.

