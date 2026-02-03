# Central Operator Agent - Runbook

**Created:** January 26, 2026  
**Status:** Operational Guide  
**Related:** [CENTRAL_OPERATOR_AGENT.md](./CENTRAL_OPERATOR_AGENT.md)

---

## Overview

This runbook provides operational procedures for the central operator agent, including thresholds, workflows, and troubleshooting.

---

## Thresholds & Configuration

### Stuck Detection Thresholds

**Default values (from `_detect_stuck_agents`):**
- **Critical margin timeout:** 5 minutes
  - Agent in critical margin + no updates > 5 min → stuck
- **Tight margin timeout:** 15 minutes
  - Agent in tight margin + no updates > 15 min → potentially stuck
- **Activity timeout:** 30 minutes
  - No updates > 30 min → stuck

**Configuration:**
```python
detect_stuck_agents(
    max_age_minutes=30.0,
    critical_margin_timeout_minutes=5.0,
    tight_margin_timeout_minutes=15.0
)
```

**Adjustment guidelines:**
- Lower thresholds → more sensitive (more false positives)
- Higher thresholds → less sensitive (miss some stuck agents)
- Monitor false positive rate and adjust accordingly

### Safety Check Thresholds

**Required for `direct_resume_if_safe`:**
- **Coherence:** > 0.40
- **Risk score:** < 0.60
- **Void active:** false
- **Status:** in ["paused", "waiting_input", "moderate"]

**Rationale:**
- Coherence > 0.40: Agent has reasonable internal consistency
- Risk < 0.60: Governance risk is manageable
- Void active == false: No active void state (critical safety check)
- Status check: Only resume from safe states

### Rate Limiting

**Operator-wide limits:**
- **Max interventions per hour:** 10
- **Cooldown per agent:** 15 minutes between recoveries
- **Purpose:** Prevent operator from overwhelming system

**Configuration:**
```python
OPERATOR_RATE_LIMIT = {
    "max_per_hour": 10,
    "cooldown_minutes": 15
}
```

### Knowledge Graph Maintenance

**Cadence:**
- **Hourly:** Aggregation and tagging (production)
- **Daily:** Summarization and archival (production)
- **Weekly:** Trend analysis (production)

**Thresholds:**
- **Stale items:** >7 days open, no updates
- **Archive resolved:** >30 days since resolved
- **Archive test agents:** >90 days old

---

## Workflows

### Workflow 1: Stuck Agent Recovery

**Trigger:** `detect_stuck_agents` returns non-empty list

**Steps:**

1. **For each stuck agent:**
   ```python
   # Get current metrics
   metrics = get_governance_metrics(agent_id=stuck_agent_id)
   
   # Check safety conditions
   if (metrics.coherence > 0.40 and 
       metrics.risk_score < 0.60 and 
       not metrics.void_active):
       
       # Safe recovery
       result = operator_resume_if_safe(
           agent_id=stuck_agent_id,
           reason=f"Operator auto-recovery: {stuck_reason}",
           conditions=[
               "Monitor for 1 hour",
               "Check metrics every 5 min"
           ]
       )
       
       # Audit log
       store_knowledge_graph(
           content=f"Operator recovered agent {stuck_agent_id}: {stuck_reason}",
           tags=["operator", "auto-recovery", "safe"],
           severity="info",
           metadata={
               "agent_id": stuck_agent_id,
               "reason": stuck_reason,
               "metrics": {
                   "coherence": metrics.coherence,
                   "risk_score": metrics.risk_score,
                   "void_active": metrics.void_active
               }
           }
       )
   else:
       # Unsafe - trigger dialectic
       request_dialectic_review(
           agent_id=stuck_agent_id,
           reason=f"Stuck agent recovery needed: {stuck_reason}",
           reviewer_mode="auto"
       )
       
       # Audit log
       store_knowledge_graph(
           content=f"Operator requested dialectic for unsafe agent {stuck_agent_id}",
           tags=["operator", "dialectic-request", "unsafe"],
           severity="warning",
           metadata={
               "agent_id": stuck_agent_id,
               "reason": stuck_reason,
               "metrics": {
                   "coherence": metrics.coherence,
                   "risk_score": metrics.risk_score,
                   "void_active": metrics.void_active
               }
           }
       )
   ```

2. **Cooldown check:**
   - Skip if agent recovered within last 15 minutes
   - Track in operator metadata or separate tracking store

3. **Rate limit check:**
   - Skip if operator has exceeded 10 interventions this hour
   - Log rate limit hit to knowledge graph

**Expected outcomes:**
- Safe agents: Resumed automatically
- Unsafe agents: Dialectic review triggered
- All actions: Logged to knowledge graph

---

### Workflow 2: Knowledge Graph Maintenance

**Trigger:** Hourly (or daily) maintenance loop

**Steps:**

1. **Aggregation:**
   ```python
   # Get lifecycle stats
   stats = get_lifecycle_stats()
   
   # Group by tags and severity
   # (implementation depends on KG structure)
   
   # Identify stale items
   stale_items = search_knowledge_graph(
       query="open discoveries older than 7 days",
       filters={"status": "open", "age_days": ">7"}
   )
   ```

2. **Auto-tagging:**
   ```python
   # For each discovery without tags:
   # Option A: Rule-based
   if "bug" in content.lower() or "error" in content.lower():
       tags.append("bug")
   
   # Option B: Semantic analysis (via ngrok.ai)
   if NGROK_AI_ENDPOINT:
       analysis = call_model(
           prompt=f"Analyze this discovery and suggest tags: {content}",
           model="gemini-flash"
       )
       tags.extend(extract_tags(analysis))
   
   # Update discovery
   update_discovery_status_graph(
       discovery_id=discovery_id,
       tags=tags
   )
   ```

3. **Summarization:**
   ```python
   # Daily digest
   top_items = search_knowledge_graph(
       query="top 10 open discoveries by severity",
       limit=10,
       sort_by="severity"
   )
   
   digest = generate_digest(top_items)
   
   store_knowledge_graph(
       content=digest,
       tags=["operator", "digest", "daily"],
       severity="info"
   )
   ```

4. **Archival:**
   ```python
   # Resolved items >30 days old
   old_resolved = search_knowledge_graph(
       filters={"status": "resolved", "resolved_days": ">30"}
   )
   
   for item in old_resolved:
       update_discovery_status_graph(
           discovery_id=item.id,
           status="archived"
       )
   ```

**Expected outcomes:**
- KG freshness improves (open/resolved ratio decreases)
- Tags are consistent and complete
- Stale items are archived
- Daily digests are generated

---

### Workflow 3: Response Completion

**Trigger:** Agent appears stuck but is `waiting_input`

**Steps:**

```python
# Check if agent is waiting for input
metadata = get_agent_metadata(agent_id=agent_id)

if metadata.status == "waiting_input":
    # Mark response complete
    mark_response_complete(
        agent_id=agent_id,
        reason="Operator: agent waiting for input, marking complete"
    )
    
    # Audit log
    store_knowledge_graph(
        content=f"Operator marked response complete for {agent_id}",
        tags=["operator", "response-complete"],
        severity="info"
    )
```

**Expected outcomes:**
- Agent transitions from `waiting_input` to `active`
- Action logged to knowledge graph

---

## Monitoring & Metrics

### Key Metrics

**Recovery metrics:**
- **Recovery success rate:** recoveries attempted vs successful
- **False positive rate:** agents recovered but immediately stuck again
- **Average recovery time:** detection to recovery (seconds)
- **Recovery by reason:** critical_margin_timeout, tight_margin_timeout, activity_timeout

**KG maintenance metrics:**
- **KG freshness:** open/resolved ratio
- **Tag coverage:** % of discoveries with tags
- **Stale items:** count of items >7 days old
- **Archival rate:** items archived per day

**System health metrics:**
- **Stuck agent count:** total stuck agents at any time
- **Operator uptime:** % time operator is running
- **Rate limit hits:** times operator hit rate limit

### Monitoring Queries

**Get recovery metrics:**
```python
# Search operator audit logs
recoveries = search_knowledge_graph(
    query="operator auto-recovery",
    tags=["operator", "auto-recovery"],
    limit=100
)

# Calculate metrics
success_rate = count_successful(recoveries) / len(recoveries)
false_positive_rate = count_false_positives(recoveries) / len(recoveries)
```

**Get KG freshness:**
```python
stats = get_lifecycle_stats()
freshness = stats["resolved"] / (stats["open"] + stats["resolved"])
```

---

## Troubleshooting

### Issue: Operator Not Detecting Stuck Agents

**Symptoms:**
- No stuck agent reports in knowledge graph
- Stuck agents remain undetected

**Diagnosis:**
1. Check operator is running: `health_check`
2. Check stuck detection is enabled: verify `detect_stuck_agents` is called periodically
3. Check thresholds: verify thresholds are appropriate
4. Check logs: look for errors in operator execution

**Resolution:**
- Adjust thresholds if too high
- Check operator identity and permissions
- Verify `detect_stuck_agents` tool is available

---

### Issue: High False Positive Rate

**Symptoms:**
- Agents recovered but immediately stuck again
- Recovery success rate <50%

**Diagnosis:**
1. Review recovery logs: check metrics at recovery time
2. Check safety thresholds: may be too permissive
3. Check cooldown: may need longer cooldown period

**Resolution:**
- Tighten safety thresholds (e.g., coherence > 0.50, risk < 0.50)
- Increase cooldown period (e.g., 30 minutes)
- Review stuck detection thresholds (may be too sensitive)

---

### Issue: Operator Rate Limited

**Symptoms:**
- Operator hits rate limit frequently
- Interventions skipped due to rate limit

**Diagnosis:**
1. Check intervention count: verify >10 interventions per hour
2. Check cooldown: verify cooldown is working
3. Check stuck agent count: may be unusually high

**Resolution:**
- Increase rate limit if legitimate need (e.g., 20 per hour)
- Investigate why so many agents are stuck
- Consider manual intervention for critical cases

---

### Issue: KG Maintenance Not Running

**Symptoms:**
- No daily digests in knowledge graph
- KG freshness not improving

**Diagnosis:**
1. Check operator is running: `health_check`
2. Check maintenance loop: verify scheduled task is running
3. Check permissions: verify operator has KG write permissions
4. Check logs: look for errors in maintenance loop

**Resolution:**
- Restart operator if not running
- Check maintenance loop schedule
- Verify operator permissions
- Review error logs

---

## Escalation

### When to Escalate

**Escalate to human operator if:**
- Recovery success rate <50% for >24 hours
- False positive rate >20% for >24 hours
- Operator rate limited for >1 hour
- Critical agent stuck and unsafe (cannot auto-recover)
- KG maintenance failing for >24 hours

### Escalation Process

1. **Log escalation request:**
   ```python
   store_knowledge_graph(
       content=f"Operator escalation: {reason}",
       tags=["operator", "escalation", "human-review"],
       severity="warning"
   )
   ```

2. **Notify human operator:**
   - Email or notification system (if configured)
   - Include: reason, affected agents, metrics, logs

3. **Manual intervention:**
   - Human operator reviews situation
   - Takes appropriate action (manual recovery, threshold adjustment, etc.)
   - Logs action in knowledge graph

---

## Best Practices

1. **Monitor metrics regularly:** Review recovery and KG metrics daily
2. **Adjust thresholds gradually:** Small changes, monitor impact
3. **Log everything:** All operator actions should be logged
4. **Test before production:** Validate changes in development first
5. **Document changes:** Update runbook when thresholds change
6. **Review false positives:** Investigate why agents are immediately stuck again
7. **Maintain operator health:** Ensure operator is running and healthy

---

## Appendix: Example Operator Script

```python
#!/usr/bin/env python3
"""
Central Operator Agent - Main Loop
"""

import asyncio
from datetime import datetime, timedelta

async def operator_main_loop():
    """Main operator loop: detect stuck agents and recover safe ones"""
    
    while True:
        try:
            # Detect stuck agents
            stuck_agents = await detect_stuck_agents(
                max_age_minutes=30.0,
                critical_margin_timeout_minutes=5.0,
                tight_margin_timeout_minutes=15.0
            )
            
            # Process each stuck agent
            for agent in stuck_agents:
                # Check cooldown
                if is_in_cooldown(agent["agent_id"]):
                    continue
                
                # Check rate limit
                if is_rate_limited():
                    log_rate_limit_hit()
                    break
                
                # Get metrics
                metrics = await get_governance_metrics(agent_id=agent["agent_id"])
                
                # Check safety
                if is_safe_to_resume(metrics):
                    # Safe recovery
                    await operator_resume_if_safe(
                        agent_id=agent["agent_id"],
                        reason=f"Operator auto-recovery: {agent['reason']}"
                    )
                    log_recovery(agent["agent_id"], "safe")
                else:
                    # Unsafe - trigger dialectic
                    await request_dialectic_review(
                        agent_id=agent["agent_id"],
                        reason=f"Stuck agent: {agent['reason']}",
                        reviewer_mode="auto"
                    )
                    log_recovery(agent["agent_id"], "dialectic")
            
            # Wait before next check
            await asyncio.sleep(300)  # 5 minutes
            
        except Exception as e:
            log_error(f"Operator loop error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error

if __name__ == "__main__":
    asyncio.run(operator_main_loop())
```

---

## References

- [Central Operator Agent Design](./CENTRAL_OPERATOR_AGENT.md)
- [Implementation Checklist](./CENTRAL_OPERATOR_AGENT_IMPLEMENTATION.md)
- [Design Review](./CENTRAL_OPERATOR_AGENT_REVIEW.md)
- [Stuck Agent Detection](../implementations/STUCK_AGENT_DETECTION_IMPLEMENTED.md)
- [Auto-Recovery Implementation](../implementations/PHASE_2_AUTO_RECOVERY_IMPLEMENTED.md)
