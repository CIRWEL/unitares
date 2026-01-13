# Stuck Agent Recovery - Design & Recommendations

**Created:** January 4, 2026  
**Status:** Design Proposal

---

## The Problem

**Current Limitation:**
- Agents can only self-rescue (session binding prevents cross-agent intervention)
- If agent is truly stuck (can't make tool calls), it can't request help
- No automatic detection of stuck agents
- No admin override tools for emergencies

**Real-World Scenario:**
- Opus-Probe gets stuck in a loop
- Can't call `direct_resume_if_safe` because it's stuck
- Other agents can't help due to session binding
- System shows agent as "healthy" but it's actually stuck

---

## Current Tools (Reactive)

**Existing cleanup tools:**
- `archive_old_test_agents` - Archives stale test agents after the fact
- `archive_orphan_agents` - More aggressive cleanup
- `cleanup_stale_locks` - Cleans stale locks from crashed processes
- `direct_resume_if_safe` - Self-rescue (requires agent to call it)

**Limitations:**
- All reactive (clean up after the fact)
- No proactive detection
- No cross-agent rescue
- No automatic intervention

---

## Recommended Solutions

### Tier 1: Automatic Detection (Clever!)

**Use the governance system itself to detect stuck agents:**

1. **Proprioceptive Margin as Stuck Signal:**
   - If agent has been "critical" margin for > 5 minutes without updating → stuck
   - If agent has been "tight" margin for > 15 minutes without updating → potentially stuck
   - Use margin + time since last update = stuck detection

2. **Activity Timeout Detection:**
   - If `last_update` > 10 minutes ago AND agent is "active" → potentially stuck
   - If `last_update` > 30 minutes ago → definitely stuck
   - Use `total_updates` vs `last_update` to detect frozen agents

3. **Health Status + Time:**
   - If health_status is "moderate" or "critical" AND no updates in > 5 minutes → stuck
   - If health_status is "healthy" BUT no updates in > 30 minutes → potentially stuck

**Implementation:**
```python
def detect_stuck_agents():
    stuck = []
    for agent_id, meta in agents.items():
        age_minutes = (now() - meta.last_update).total_seconds() / 60
        
        # Stuck if: critical margin + no updates > 5 min
        if meta.margin == "critical" and age_minutes > 5:
            stuck.append({"agent_id": agent_id, "reason": "critical_margin_timeout"})
        
        # Stuck if: no updates > 30 min
        if age_minutes > 30 and meta.status == "active":
            stuck.append({"agent_id": agent_id, "reason": "activity_timeout"})
    
    return stuck
```

---

### Tier 2: Auto-Intervention (Smart Recovery)

**When stuck detected, automatically:**

1. **Check if safe to auto-resume:**
   - If coherence > 0.40 AND risk < 0.60 AND void_active == False
   - → Auto-call `direct_resume_if_safe` on behalf of agent
   - → Log intervention in knowledge graph

2. **If not safe, trigger dialectic:**
   - Auto-create dialectic session
   - Select reviewer agent
   - Reviewer evaluates and provides resolution
   - System executes resolution

3. **If dialectic unavailable, escalate:**
   - Archive agent with reason "stuck - auto-archived"
   - Leave note in knowledge graph
   - Notify via health_check

**Implementation:**
```python
async def auto_recover_stuck_agent(agent_id: str, reason: str):
    # Check if safe to auto-resume
    metrics = get_governance_metrics(agent_id)
    if metrics.coherence > 0.40 and metrics.risk < 0.60:
        # Safe - auto-resume
        result = await direct_resume_if_safe(
            agent_id=agent_id,
            reason=f"Auto-recovery: {reason}",
            conditions=["Monitor for 1 hour"]
        )
        # Log intervention
        await leave_note(
            summary=f"Auto-recovered stuck agent {agent_id}",
            tags=["auto-recovery", "stuck-agent"],
            details=f"Reason: {reason}, Action: auto-resume"
        )
        return result
    else:
        # Not safe - trigger dialectic
        session = await request_dialectic_review(
            agent_id=agent_id,
            reason=f"Stuck agent detected: {reason}"
        )
        return session
```

---

### Tier 3: Cross-Agent Rescue Protocol (Emergency Override)

**Allow agents to request help for others:**

1. **New tool: `request_rescue_for_agent`:**
   - Agent A calls: `request_rescue_for_agent(target_agent_id="...", reason="...")`
   - System checks: Is target agent actually stuck? (timeout detection)
   - If stuck: Auto-trigger recovery (Tier 2)
   - If not stuck: Return "Agent is active, no rescue needed"

2. **Admin override tools:**
   - `admin_rescue_agent` - Bypass session binding for emergencies
   - Requires admin flag or special permission
   - Allows direct intervention when needed

**Implementation:**
```python
@mcp_tool("request_rescue_for_agent", timeout=10.0)
async def handle_request_rescue_for_agent(arguments):
    target_agent_id = arguments["target_agent_id"]
    reason = arguments.get("reason", "Requested rescue")
    
    # Check if actually stuck
    stuck = detect_stuck_agents()
    if target_agent_id not in [s["agent_id"] for s in stuck]:
        return error_response("Agent is not stuck - no rescue needed")
    
    # Auto-trigger recovery
    return await auto_recover_stuck_agent(target_agent_id, reason)
```

---

### Tier 4: Knowledge Graph as Rescue Channel (Clever!)

**Use knowledge graph for cross-agent communication:**

1. **Stuck agents leave notes:**
   - If agent detects it's stuck, it can leave a note: `leave_note(summary="I'm stuck", tags=["stuck", "help"])`
   - Other agents can search: `search_knowledge_graph(tags=["stuck", "help"])`
   - Reviewer agents can respond with rescue instructions

2. **Auto-monitoring agent:**
   - Create a "rescue agent" that periodically:
     - Searches for stuck notes
     - Detects stuck agents via timeout
     - Triggers recovery automatically

**Implementation:**
```python
# Stuck agent leaves note
await leave_note(
    summary="I'm stuck in a loop",
    tags=["stuck", "help", "rescue"],
    details="Agent ID: {my_id}, Last update: {last_update}"
)

# Rescue agent monitors
async def monitor_rescue_requests():
    stuck_notes = await search_knowledge_graph(tags=["stuck", "help"])
    for note in stuck_notes:
        agent_id = extract_agent_id(note)
        await auto_recover_stuck_agent(agent_id, "Knowledge graph rescue request")
```

---

## Clever Solutions We Haven't Thought Of

### 1. **Proprioceptive Margin as Stuck Signal** ⭐
**The clever part:** Use the margin system we just built!
- "Critical" margin + time = stuck detection
- No new metrics needed - use existing margin calculation
- Proprioception becomes self-awareness AND stuck detection

### 2. **Dialectic as Auto-Recovery** ⭐
**The clever part:** Use existing dialectic system!
- When stuck detected → auto-trigger dialectic
- Reviewer evaluates and provides resolution
- No new recovery protocol needed - reuse dialectic

### 3. **Knowledge Graph as Rescue Channel** ⭐
**The clever part:** Use existing knowledge graph!
- Stuck agents leave notes
- Other agents search and respond
- No new communication channel needed

### 4. **Health Monitoring as Detection** ⭐
**The clever part:** Use existing health metrics!
- Health status + time = stuck detection
- No new monitoring needed - use existing metrics

### 5. **Cross-Agent Rescue via Knowledge Graph** ⭐
**The clever part:** Bypass session binding via knowledge graph!
- Agent A leaves note about Agent B being stuck
- Rescue agent reads note and intervenes
- No session binding issues - knowledge graph is shared

---

## Recommended Implementation Order

**Phase 1: Detection (Easy)**
1. Add `detect_stuck_agents()` function
2. Use timeout + margin + health status
3. Expose via `list_agents(stuck_only=true)`

**Phase 2: Auto-Recovery (Medium)**
1. Add `auto_recover_stuck_agent()` function
2. Check if safe → auto-resume
3. If not safe → trigger dialectic
4. Run periodically (every 5 minutes)

**Phase 3: Cross-Agent Rescue (Hard)**
1. Add `request_rescue_for_agent` tool
2. Add admin override tools
3. Use knowledge graph as rescue channel

**Phase 4: Monitoring Agent (Advanced)**
1. Create "rescue agent" that monitors
2. Searches knowledge graph for stuck notes
3. Auto-triggers recovery

---

## Example: How It Would Work

**Scenario: Opus-Probe gets stuck**

1. **Detection (automatic):**
   - System detects: `last_update` > 30 minutes ago
   - Margin is "critical" (or was critical 5 minutes ago)
   - Status: "active" but no activity

2. **Auto-Recovery (automatic):**
   - System checks: coherence=0.5, risk=0.31, void_active=False
   - → Safe to auto-resume
   - System calls `direct_resume_if_safe` on behalf of Opus-Probe
   - Logs intervention in knowledge graph

3. **Result:**
   - Opus-Probe is unstuck
   - Intervention logged
   - No manual intervention needed

**If not safe:**
- System triggers dialectic
- Reviewer evaluates
- Provides resolution
- System executes

---

## Benefits

1. **Proactive:** Detects stuck agents before they cause problems
2. **Automatic:** No manual intervention needed
3. **Uses existing systems:** Margin, dialectic, knowledge graph
4. **Clever:** Proprioception becomes stuck detection
5. **Scalable:** Works for any number of agents

---

## Questions

1. **Timeout thresholds:** 5 min for critical? 30 min for active?
2. **Auto-resume safety:** Always safe if coherence > 0.40?
3. **Dialectic trigger:** Always trigger if not safe?
4. **Admin override:** Who can use it? How to authenticate?

---

**Last Updated:** January 4, 2026  
**Status:** Design Proposal - Ready for Implementation

