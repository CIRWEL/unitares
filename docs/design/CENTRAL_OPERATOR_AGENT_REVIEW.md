# Central Operator Agent - Design Review

**Review Date:** January 26, 2026  
**Reviewer:** AI Assistant  
**Status:** ✅ Strong Foundation, Minor Enhancements Suggested

---

## Overall Assessment

**Strengths:**
- ✅ Clear separation of concerns: orchestrator vs arbiter
- ✅ Well-defined guardrails and non-goals
- ✅ Aligns with existing implementation (`direct_resume_if_safe` thresholds match code)
- ✅ Phased rollout approach is sensible
- ✅ ngrok.ai integration appropriately scoped as optional infrastructure

**Areas for Enhancement:**
- Stuck detection thresholds could reference existing implementation
- Missing a few useful read-only tools
- Recovery workflow could clarify cross-agent session binding constraints
- Knowledge graph maintenance needs more specific thresholds

---

## Detailed Feedback

### 1. Recovery Workflow - Stuck Detection Thresholds

**Current Spec (lines 64-67):**
- Mentions `last_update` older than threshold but doesn't specify values
- Doesn't mention proprioceptive margin detection (which is already implemented)

**Recommendation:** Reference the existing `_detect_stuck_agents()` implementation:

```markdown
1. **Detect stuck conditions**  
   Use `detect_stuck_agents` tool or equivalent logic:
   - **Critical margin + no updates > 5 min** → stuck (immediate recovery)
   - **Tight margin + no updates > 15 min** → potentially stuck (monitor)
   - **No updates > 30 min** → stuck (activity timeout)
   - `status == paused` AND no recovery event logged → recovery candidate
   - `waiting_input` is *not* considered stuck (explicit exclusion)
```

**Rationale:** The codebase already has sophisticated margin-based detection (`src/mcp_handlers/lifecycle.py:1386`). The operator should leverage this rather than reimplementing.

---

### 2. Permissions - Missing Read-Only Tools

**Current Spec (lines 44-48):** Good coverage, but missing a few useful observability tools.

**Suggested Additions:**
- `detect_stuck_agents` - Essential for the operator's primary function
- `get_lifecycle_stats` - For KG maintenance metrics
- `get_workspace_health` - System-level health checks
- `health_check` - Quick system status
- `list_knowledge_graph` - Overview before detailed search

**Rationale:** These are all read-only and directly support operator functions.

---

### 3. Recovery Workflow - Session Binding Constraint

**Current Spec (lines 69-75):** Doesn't address how operator can act on behalf of other agents.

**Clarification Needed:**
The operator needs to call `direct_resume_if_safe` for *other* agents, but the current implementation requires session binding (`verify_agent_ownership`). 

**Options:**
1. **Operator bypass:** Add operator identity check in `direct_resume_if_safe` handler
2. **Proxy pattern:** Operator calls a new `operator_resume_if_safe` tool that bypasses ownership
3. **Dialectic only:** Operator can only trigger `request_dialectic_review` (safer, but slower)

**Recommendation:** Document this constraint and recommend Option 2 (new operator-specific tool) for Phase 3.

---

### 4. Knowledge Graph Maintenance - Specific Thresholds

**Current Spec (lines 84-89):** Vague on "lifecycle policy" and cadence.

**Suggested Enhancement:**
```markdown
## Knowledge Graph Maintenance Loop

**Cadence:** Hourly (production) or daily (development)

**Operations:**
1. **Aggregation** (via `get_lifecycle_stats`)
   - Count open vs resolved discoveries
   - Group by tags and severity
   - Identify stale items (>7 days open, no updates)

2. **Auto-tagging** (via `update_discovery_status_graph`)
   - Missing tags: infer from content (e.g., "bug", "improvement", "analysis")
   - Duplicate detection: semantic similarity check
   - Status updates: mark resolved if linked to closed agents

3. **Summarization** (via `store_knowledge_graph`)
   - Daily digest: top 10 open items by severity
   - Weekly summary: trends and patterns
   - Store as operator notes with tag `["operator", "kg-maintenance"]`

4. **Archival** (via `update_discovery_status_graph`)
   - Resolved items >30 days old → archive
   - Test agent discoveries >90 days old → archive
   - Duplicate discoveries → merge and archive
```

---

### 5. Open Questions - Answers from Codebase

**Q1: What are acceptable thresholds for "stuck" detection?**
**Answer:** Already implemented:
- Critical margin timeout: **5 minutes** (default)
- Tight margin timeout: **15 minutes** (default)
- Activity timeout: **30 minutes** (default)

These are configurable via `detect_stuck_agents` parameters. Recommend operator uses defaults initially, adjusts based on false positive rate.

**Q2: Should operator be allowed to archive stale test agents?**
**Answer:** **No** (per current spec line 57). However, consider:
- Operator could *identify* stale test agents via `list_agents` + metadata filtering
- Operator could *request* archival via `request_dialectic_review` with human approval
- Or add `archive_old_test_agents` to restricted write permissions (with rate limiting)

**Recommendation:** Keep prohibition for Phase 1-3, revisit in Phase 4 if manual triage becomes bottleneck.

**Q3: Do we want a human approval step for any recovery action?**
**Answer:** **Not required** for safe auto-resume (coherence > 0.40, risk < 0.60, void_active == false). However:
- Unsafe recovery already requires `request_dialectic_review` (which can include human reviewer)
- Consider adding `require_human_approval` flag for operator-initiated recoveries in Phase 3+

---

## Implementation Checklist Suggestions

### Phase 1: Read-Only Operator (Foundation)
- [ ] Create operator identity with label "Operator"
- [ ] Configure tool mode: `operator_readonly` (subset of read-only tools)
- [ ] Implement periodic `detect_stuck_agents` calls (every 5 min)
- [ ] Log findings to knowledge graph with tag `["operator", "observation"]`
- [ ] Create operator dashboard/reporting tool

### Phase 2: Lifecycle Light
- [ ] Add `mark_response_complete` to operator permissions
- [ ] Add `request_dialectic_review` to operator permissions
- [ ] Implement operator-initiated dialectic requests
- [ ] Audit logging for all operator actions
- [ ] Rate limiting: max 10 interventions per hour

### Phase 3: Safe Recovery
- [ ] **Critical:** Resolve session binding constraint (see Section 3 above)
- [ ] Add `direct_resume_if_safe` to operator permissions (with ownership bypass)
- [ ] Implement safety check wrapper: `operator_resume_if_safe(agent_id, reason)`
- [ ] Cooldown period: 15 min between recoveries for same agent
- [ ] Metrics tracking: recovery success rate, false positive rate

### Phase 4: KG Maintenance
- [ ] Implement hourly maintenance loop
- [ ] Auto-tagging logic (semantic analysis or rule-based)
- [ ] Digest generation (daily summaries)
- [ ] Archival automation (with configurable thresholds)
- [ ] Monitoring: KG freshness metrics, cleanup stats

---

## Read-Only Operator Tool Mode

**Suggested tool set for `operator_readonly` mode:**

```python
OPERATOR_READONLY_TOOLS: Set[str] = {
    # Core observability
    "list_agents",
    "get_agent_metadata",
    "observe_agent",
    "detect_stuck_agents",  # Essential!
    
    # Governance metrics
    "get_governance_metrics",
    "detect_anomalies",
    "get_telemetry_metrics",
    
    # Knowledge graph (read)
    "search_knowledge_graph",
    "get_discovery_details",
    "list_knowledge_graph",
    "get_lifecycle_stats",
    
    # System health
    "health_check",
    "get_workspace_health",
    "get_tool_usage_stats",
    
    # Identity (for operator itself)
    "identity",
    "onboard",
}
```

**Integration:** Add to `tool_modes.py` and wire via `GOVERNANCE_TOOL_MODE=operator_readonly`.

---

## Sample Runbook

### Operator Runbook: Stuck Agent Recovery

**Trigger:** `detect_stuck_agents` returns non-empty list

**Workflow:**

1. **For each stuck agent:**
   ```python
   # Get current metrics
   metrics = get_governance_metrics(agent_id=stuck_agent_id)
   
   # Check safety conditions
   if (metrics.coherence > 0.40 and 
       metrics.risk_score < 0.60 and 
       not metrics.void_active):
       
       # Safe recovery
       result = direct_resume_if_safe(
           agent_id=stuck_agent_id,
           reason=f"Operator auto-recovery: {stuck_reason}",
           conditions=["Monitor for 1 hour", "Check metrics every 5 min"]
       )
       
       # Audit log
       store_knowledge_graph(
           content=f"Operator recovered agent {stuck_agent_id}: {stuck_reason}",
           tags=["operator", "auto-recovery", "safe"],
           severity="info"
       )
   else:
       # Unsafe - trigger dialectic
       request_dialectic_review(
           agent_id=stuck_agent_id,
           reason=f"Stuck agent recovery needed: {stuck_reason}",
           reviewer_mode="auto"
       )
   ```

2. **Cooldown:** Wait 15 minutes before checking same agent again

3. **Metrics:** Track recovery rate, false positives, average recovery time

**Thresholds:**
- **Stuck detection:** 5 min (critical), 15 min (tight), 30 min (activity)
- **Safety checks:** coherence > 0.40, risk < 0.60, void_active == false
- **Cooldown:** 15 min between recoveries per agent
- **Rate limit:** Max 10 recoveries per hour (operator-wide)

---

## ngrok.ai Integration - Clarification

**Current Spec (lines 93-95):** Brief but appropriate.

**Additional Context:**
- ngrok.ai provides AI Gateway (model routing), not just ingress
- Operator can use `call_model` tool via ngrok.ai gateway for:
  - Semantic analysis (KG auto-tagging)
  - Digest generation (summaries)
  - Anomaly detection (pattern recognition)
- All model calls still tracked in EISV (energy consumption)
- Privacy mode available for sensitive operations

**Recommendation:** Add note that operator can leverage `call_model` for KG maintenance tasks.

---

## Conclusion

The spec is **production-ready** with minor enhancements. Key recommendations:

1. ✅ **Reference existing stuck detection implementation** (Section 1)
2. ✅ **Add missing read-only tools** (Section 2)
3. ⚠️ **Clarify session binding constraint** (Section 3) - **Critical for Phase 3**
4. ✅ **Specify KG maintenance thresholds** (Section 4)
5. ✅ **Answer open questions** (Section 5)

**Next Steps:**
- Implement Phase 1 (read-only operator) as proof of concept
- Resolve session binding constraint before Phase 3
- Create runbook and thresholds document for operations team
