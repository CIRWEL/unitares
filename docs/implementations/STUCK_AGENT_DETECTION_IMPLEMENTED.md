# Stuck Agent Detection - Implementation Complete

**Created:** January 4, 2026  
**Status:** Phase 1 Implemented ✅

---

## What Was Built

**New Tool: `detect_stuck_agents`**

Detects stuck agents using **proprioceptive margin + timeout** - the clever solution we designed!

**Detection Rules:**
1. **Critical margin + no updates > 5 min** → stuck
2. **Tight margin + no updates > 15 min** → potentially stuck
3. **No updates > 30 min** → stuck

**Key Innovation:**
- Uses the margin system we just built
- Proprioception becomes stuck detection!
- No new metrics needed - reuses existing margin calculation

---

## Implementation Details

### Core Function: `_detect_stuck_agents()`

**Location:** `src/mcp_handlers/lifecycle.py`

**How it works:**
1. Iterates through all active agents
2. Calculates age since last update
3. Computes margin using `GovernanceConfig.compute_proprioceptive_margin()`
4. Applies detection rules based on margin + timeout
5. Returns list of stuck agents with reasons

**Detection Logic:**
```python
# Rule 1: Critical margin + timeout
if margin == "critical" and age_minutes > 5:
    stuck_agents.append({
        "agent_id": agent_id,
        "reason": "critical_margin_timeout",
        "margin": margin,
        "nearest_edge": margin_info.get('nearest_edge')
    })

# Rule 2: Tight margin + timeout
if margin == "tight" and age_minutes > 15:
    stuck_agents.append({
        "agent_id": agent_id,
        "reason": "tight_margin_timeout",
        "margin": margin,
        "nearest_edge": margin_info.get('nearest_edge')
    })

# Rule 3: Activity timeout
if age_minutes > 30:
    stuck_agents.append({
        "agent_id": agent_id,
        "reason": "activity_timeout"
    })
```

### MCP Tool: `handle_detect_stuck_agents()`

**Parameters:**
- `max_age_minutes` (default: 30) - Maximum age before considered stuck
- `critical_margin_timeout_minutes` (default: 5) - Timeout for critical margin
- `tight_margin_timeout_minutes` (default: 15) - Timeout for tight margin
- `auto_recover` (default: false) - Automatically recover safe stuck agents

**Returns:**
```json
{
  "stuck_agents": [
    {
      "agent_id": "...",
      "reason": "critical_margin_timeout",
      "age_minutes": 6.2,
      "margin": "critical",
      "nearest_edge": "coherence",
      "details": "Critical margin (coherence) for 6.2 minutes"
    }
  ],
  "recovered": [],  // If auto_recover=true
  "summary": {
    "total_stuck": 1,
    "total_recovered": 0,
    "by_reason": {
      "critical_margin_timeout": 1,
      "tight_margin_timeout": 0,
      "activity_timeout": 0
    }
  }
}
```

### Auto-Recovery (Optional)

If `auto_recover=true`:
- Checks if agent is safe (coherence > 0.40, risk < 0.60, void_active == False)
- If safe → auto-resumes agent
- Logs intervention in knowledge graph
- Returns list of recovered agents

---

## Usage Examples

### Basic Detection
```python
# Detect stuck agents
result = detect_stuck_agents()
# Returns: {"stuck_agents": [...], "summary": {...}}
```

### With Auto-Recovery
```python
# Detect and auto-recover safe stuck agents
result = detect_stuck_agents(auto_recover=True)
# Returns: {"stuck_agents": [...], "recovered": [...], "summary": {...}}
```

### Custom Timeouts
```python
# Custom detection thresholds
result = detect_stuck_agents(
    max_age_minutes=60,
    critical_margin_timeout_minutes=10,
    tight_margin_timeout_minutes=30
)
```

---

## Integration Points

**Uses Existing Systems:**
- ✅ Margin calculation (`GovernanceConfig.compute_proprioceptive_margin()`)
- ✅ Agent metadata (`mcp_server.agent_metadata`)
- ✅ Monitor state (`mcp_server.monitors`)
- ✅ Knowledge graph (for logging interventions)

**Exported:**
- ✅ Added to `src/mcp_handlers/__init__.py`
- ✅ Auto-registered via `@mcp_tool` decorator
- ✅ Available via MCP protocol

---

## Next Steps (Future Phases)

**Phase 2: Auto-Intervention (Planned)**
- Background task that runs every 5 minutes
- Automatically detects and recovers stuck agents
- No manual intervention needed

**Phase 3: Cross-Agent Rescue (Planned)**
- `request_rescue_for_agent` tool
- Allows agents to request help for others
- Bypasses session binding for rescue scenarios

**Phase 4: Monitoring Agent (Planned)**
- "Rescue agent" that monitors continuously
- Searches knowledge graph for stuck notes
- Auto-triggers recovery

---

## Testing

**Manual Test:**
```bash
# Import function
python3 -c "from src.mcp_handlers.lifecycle import _detect_stuck_agents; print('OK')"
# ✅ Success
```

**Via MCP:**
```python
# Call tool
detect_stuck_agents()
# Returns stuck agents list
```

---

## Benefits

1. **Proactive:** Detects stuck agents before they cause problems
2. **Uses Existing Systems:** Margin, metadata, monitors - no new infrastructure
3. **Clever:** Proprioception becomes stuck detection
4. **Actionable:** Returns specific reasons and recovery options
5. **Optional Auto-Recovery:** Can automatically recover safe agents

---

## Files Modified

- ✅ `src/mcp_handlers/lifecycle.py` - Added detection function and tool handler
- ✅ `src/mcp_handlers/__init__.py` - Exported new handler
- ✅ `docs/design/STUCK_AGENT_RECOVERY.md` - Design document
- ✅ `docs/implementations/STUCK_AGENT_DETECTION_IMPLEMENTED.md` - This file

---

**Last Updated:** January 4, 2026  
**Status:** Phase 1 Complete ✅ - Ready for Testing

