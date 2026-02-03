# Central Operator Agent - Design Proposal

**Created:** January 26, 2026  
**Status:** Draft Design Proposal

---

## Goal

Create a lightweight "central operator" agent that coordinates recovery, routing, and knowledge-graph hygiene without becoming a privileged governor or single point of failure.

This agent is an **orchestrator, not an arbiter**: it suggests, initiates safe recovery, and maintains system health, but does not bypass governance or modify thresholds.

---

## Why This Helps

- **Fewer stuck agents:** proactive detection and safe recovery.
- **Cleaner knowledge graph:** targeted cleanup, tagging, and summaries.
- **Better routing:** direct tasks to healthy, relevant agents.
- **Lower friction:** central handling of routine lifecycle tasks.

---

## Non-Goals

- No authority to bypass safety checks or modify thresholds.
- No unilateral pausing or resuming outside existing safety rules.
- No privileged cross-agent actions beyond existing lifecycle tools.
- No hidden automation that cannot be audited.

---

## Operating Model

### Identity

- Dedicated operator identity (stable label and structured_id).
- Session-bound; no multi-session impersonation.
- Explicit display label (e.g., "Operator").

### Permissions (Tool Scope)

**Read-only:**  
- `list_agents`, `get_agent_metadata`, `observe_agent`, `detect_stuck_agents`  
- `get_governance_metrics`, `detect_anomalies`  
- `get_tool_usage_stats`, `get_telemetry_metrics`, `get_lifecycle_stats`  
- `search_knowledge_graph`, `get_discovery_details`, `list_knowledge_graph`

**Write (restricted):**  
- `mark_response_complete`  
- `direct_resume_if_safe` (only after safety checks)  
- `request_dialectic_review` (for unsafe recovery)  
- `leave_note`, `store_knowledge_graph`, `update_discovery_status_graph`

**Explicitly prohibited:**  
- `set_thresholds`, `update_calibration_ground_truth`, `delete_agent`, `archive_agent`  
- Any tool that alters governance policy or erases data

---

## Recovery Workflow

1. **Detect stuck conditions**  
   - Use existing thresholds from `STUCK_AGENT_RECOVERY.md`  
     - critical margin + no updates > 5 min  
     - tight margin + no updates > 15 min  
     - active + no updates > 30 min  
   - `waiting_input` is *not* considered stuck

2. **Safe auto-resume check**  
   - Use `get_governance_metrics`  
   - Only call `direct_resume_if_safe` when coherence > 0.40 and risk_score < 0.60 and void_active == false

3. **Unsafe recovery**  
   - Call `request_dialectic_review`  
   - Prefer `reviewer_mode="auto"` (peer selection; self fallback only if none)

4. **Audit trail**  
   - `leave_note` or `store_knowledge_graph` with action summary and decision evidence

---

## Knowledge Graph Maintenance Loop

Suggested cadence and thresholds:

- **Hourly:** summarize new high-severity discoveries, tag missing metadata  
- **Daily:** produce open-items digest by severity and tag  
- **Weekly:** archive resolved items older than 30 days (respect lifecycle policy)

- Aggregate new discoveries by tags and severity
- Auto-tag missing metadata (e.g., `bug`, `improvement`, `analysis`)
- Summarize open items into a digest note
- Archive resolved items based on lifecycle policy (via `update_discovery_status_graph`)

---

## ngrok.ai Integration (Optional)

ngrok.ai can host the operator agent with stable ingress and low-latency model access. This improves reliability but does not replace governance constraints. All operator actions remain audited and limited by tool permissions.

---

## Failure Modes and Safeguards

- **Overreach risk:** tool scope limits + audit logging
- **False positives:** conservative stuck thresholds + `waiting_input` exclusion
- **Single point of failure:** operator is optional; system runs without it
- **Over-automation:** rate limits + cooldown for repeated interventions
- **Session binding constraints:** operator cannot act on other agents without an explicit override mechanism

---

## Metrics for Success

- Reduction in stuck agents and recovery time
- Fewer false "stuck" detections
- Knowledge graph freshness (open vs resolved ratio)
- Lower manual triage load

---

## Suggested Phased Rollout

1. **Read-only mode** (observe + report)
2. **Lifecycle light** (mark_response_complete, request_dialectic_review)
3. **Safe recovery** (direct_resume_if_safe with strict checks)
4. **KG maintenance** (summaries, tag cleanup)

---

## Open Questions

- What are acceptable thresholds for "stuck" detection?
- Should operator be allowed to archive stale test agents?
- Do we want a human approval step for any recovery action?
- If cross-agent recovery is required, do we introduce a scoped service account or admin override tool?