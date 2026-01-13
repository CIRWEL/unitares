# Phase 2: Automatic Stuck Agent Recovery - Implementation Complete

**Created:** January 4, 2026  
**Status:** Phase 2 Implemented ✅

---

## What Was Built

**Background Task: Automatic Stuck Agent Recovery**

Runs every 5 minutes, automatically detects and recovers stuck agents without manual intervention.

**How It Works:**
1. Background task starts 10 seconds after server startup
2. Runs every 5 minutes
3. Calls `detect_stuck_agents(auto_recover=True)`
4. Automatically recovers safe stuck agents
5. Logs interventions

---

## Implementation Details

### Background Task: `stuck_agent_recovery_task()`

**Location:** `src/mcp_server_sse.py`

**Features:**
- Runs every 5 minutes
- Non-blocking (doesn't affect server performance)
- Error handling (continues even if one iteration fails)
- Logs recovery actions

**Recovery Logic:**
- Detects stuck agents using margin + timeout
- Checks if safe to recover (coherence > 0.40, risk < 0.60, void_active == False)
- Auto-resumes safe agents
- Logs interventions in knowledge graph

**Code:**
```python
async def stuck_agent_recovery_task():
    await asyncio.sleep(10.0)  # Wait for server initialization
    
    interval_minutes = 5.0
    while True:
        await asyncio.sleep(interval_minutes * 60)
        
        # Detect and auto-recover
        result = await handle_detect_stuck_agents({
            "max_age_minutes": 30.0,
            "critical_margin_timeout_minutes": 5.0,
            "tight_margin_timeout_minutes": 15.0,
            "auto_recover": True
        })
        
        # Log results
        # ...
```

---

## Configuration

**Default Settings:**
- **Interval:** 5 minutes
- **Max age:** 30 minutes (before considered stuck)
- **Critical margin timeout:** 5 minutes
- **Tight margin timeout:** 15 minutes
- **Auto-recover:** Enabled

**Recovery Safety Checks:**
- Coherence > 0.40
- Risk < 0.60
- Void active == False

---

## How It Works

**Example Scenario:**

1. **Agent gets stuck** (can't call tools, stuck in loop)
2. **5 minutes pass** → Background task runs
3. **Detection:** System detects agent is stuck (critical margin + timeout)
4. **Safety check:** Coherence=0.5, Risk=0.31, Void=False → Safe!
5. **Auto-recovery:** System calls `direct_resume_if_safe` on behalf of agent
6. **Logging:** Intervention logged in knowledge graph
7. **Result:** Agent is unstuck, no manual intervention needed

**If Not Safe:**
- System logs stuck agent but doesn't auto-recover
- Can trigger dialectic review (future enhancement)
- Human/admin can intervene manually

---

## Logging

**Log Messages:**
```
[STUCK_AGENT_RECOVERY] Starting automatic recovery (runs every 5 minutes)
[STUCK_AGENT_RECOVERY] Detected 2 stuck agent(s), recovered 1 safe agent(s)
[STUCK_AGENT_RECOVERY] Recovered agent abc12345... (reason: critical_margin_timeout)
```

**Knowledge Graph:**
- Auto-recovery interventions logged as notes
- Tags: ["auto-recovery", "stuck-agent"]
- Summary includes agent ID and reason

---

## Benefits

1. **Automatic:** No manual intervention needed
2. **Proactive:** Detects and recovers before problems escalate
3. **Safe:** Only recovers agents with safe metrics
4. **Non-blocking:** Doesn't affect server performance
5. **Resilient:** Continues even if one iteration fails

---

## Testing

**Manual Test:**
```bash
# Start server
python3 src/mcp_server_sse.py

# Check logs for:
# [STUCK_AGENT_RECOVERY] Starting automatic recovery
# [STUCK_AGENT_RECOVERY] Detected X stuck agent(s), recovered Y safe agent(s)
```

**Verify Recovery:**
- Create stuck agent (set status to "paused", wait 5+ minutes)
- Check logs for recovery message
- Verify agent status changed to "active"

---

## Future Enhancements

**Phase 3 (If Needed):**
- Cross-agent rescue (`request_rescue_for_agent`)
- Admin override tools
- Dialectic auto-trigger for unsafe agents

**Phase 4 (If Needed):**
- Monitoring agent (dedicated rescue agent)
- Knowledge graph rescue channel
- More sophisticated recovery strategies

---

## Files Modified

- ✅ `src/mcp_server_sse.py` - Added background recovery task
- ✅ `docs/implementations/PHASE_2_AUTO_RECOVERY_IMPLEMENTED.md` - This file

---

**Last Updated:** January 4, 2026  
**Status:** Phase 2 Complete ✅ - Automatic Recovery Active

