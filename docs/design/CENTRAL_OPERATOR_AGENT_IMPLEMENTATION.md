# Central Operator Agent - Implementation Checklist

**Created:** January 26, 2026  
**Status:** Implementation Guide  
**Related:** [CENTRAL_OPERATOR_AGENT.md](./CENTRAL_OPERATOR_AGENT.md), [CENTRAL_OPERATOR_AGENT_REVIEW.md](./CENTRAL_OPERATOR_AGENT_REVIEW.md)

---

## Overview

This checklist tracks implementation of the central operator agent across four phases. Each phase builds on the previous one, allowing incremental rollout and validation.

---

## Phase 1: Read-Only Operator (Foundation)

**Goal:** Operator can observe system state and detect issues, but cannot take action.

**Timeline:** 1-2 weeks  
**Risk Level:** Low (read-only, no state changes)

### Identity & Configuration

- [ ] Create operator identity schema
  - [ ] Label: "Operator" (or configurable)
  - [ ] Structured ID: `operator-{timestamp}` or `operator-main`
  - [ ] Session binding: standard agent session binding
  - [ ] Display metadata: `{"role": "operator", "mode": "readonly"}`

- [ ] Configure tool mode: `operator_readonly`
  - [ ] Add `OPERATOR_READONLY_MODE_TOOLS` to `tool_modes.py` ✅ (done)
  - [ ] Wire mode via `GOVERNANCE_TOOL_MODE=operator_readonly`
  - [ ] Verify tool filtering in `list_tools` handler

- [ ] Operator onboarding script
  - [ ] Script: `scripts/setup_operator_agent.sh`
  - [ ] Creates operator identity via `onboard` tool
  - [ ] Sets environment: `GOVERNANCE_TOOL_MODE=operator_readonly`
  - [ ] Validates tool access

### Observability & Detection

- [ ] Periodic stuck agent detection
  - [ ] Background task: call `detect_stuck_agents` every 5 minutes
  - [ ] Log findings to knowledge graph
  - [ ] Tag: `["operator", "observation", "stuck-detection"]`
  - [ ] Store metrics: count, reasons, agent IDs

- [ ] System health monitoring
  - [ ] Hourly: `health_check`, `get_workspace_health`
  - [ ] Daily: `get_telemetry_metrics`, `get_tool_usage_stats`
  - [ ] Store summaries in knowledge graph

- [ ] Knowledge graph observation
  - [ ] Daily: `get_lifecycle_stats` for KG metrics
  - [ ] Track: open/resolved ratio, stale items, tag distribution
  - [ ] Store reports with tag `["operator", "kg-report"]`

### Reporting & Logging

- [ ] Operator dashboard/reporting
  - [ ] Daily summary: stuck agents, system health, KG stats
  - [ ] Format: JSON or markdown digest
  - [ ] Store via `store_knowledge_graph` with tag `["operator", "daily-report"]`

- [ ] Audit logging
  - [ ] All operator actions logged to knowledge graph
  - [ ] Include: timestamp, action type, target agent (if any), result
  - [ ] Tag: `["operator", "audit"]`

### Testing

- [ ] Unit tests: operator identity creation
- [ ] Integration tests: tool mode filtering
- [ ] Manual test: run operator in read-only mode, verify no write access
- [ ] Validation: operator can detect stuck agents but cannot recover them

---

## Phase 2: Lifecycle Light

**Goal:** Operator can mark responses complete and request dialectic reviews, but cannot auto-resume.

**Timeline:** 1 week  
**Risk Level:** Low-Medium (limited write access)

### Permissions Expansion

- [ ] Add `mark_response_complete` to operator permissions
  - [ ] Update `OPERATOR_READONLY_MODE_TOOLS` → rename to `OPERATOR_MODE_TOOLS`
  - [ ] Add `mark_response_complete` to tool set
  - [ ] Document: operator can mark responses complete for any agent

- [ ] Add `request_dialectic_review` to operator permissions
  - [ ] Add to tool set
  - [ ] Document: operator can trigger dialectic for stuck/unsafe agents
  - [ ] Default `reviewer_mode="auto"` (peer selection)

### Recovery Workflow (Manual)

- [ ] Implement operator-initiated dialectic requests
  - [ ] When stuck agent detected and unsafe: call `request_dialectic_review`
  - [ ] Include reason: `f"Operator detected stuck agent: {stuck_reason}"`
  - [ ] Log action to knowledge graph

- [ ] Implement response completion
  - [ ] When agent appears stuck but is `waiting_input`: mark complete
  - [ ] Use `mark_response_complete` with reason
  - [ ] Log action

### Rate Limiting

- [ ] Implement rate limits
  - [ ] Max 10 interventions per hour (operator-wide)
  - [ ] Cooldown: 15 minutes between actions on same agent
  - [ ] Track in operator metadata or separate rate limit store

### Testing

- [ ] Test: operator can request dialectic review
- [ ] Test: operator can mark response complete
- [ ] Test: rate limiting prevents over-intervention
- [ ] Test: operator cannot call `direct_resume_if_safe` (should fail)

---

## Phase 3: Safe Recovery

**Goal:** Operator can auto-resume safe agents using `direct_resume_if_safe`.

**Timeline:** 2-3 weeks  
**Risk Level:** Medium (requires session binding bypass)

### Critical: Session Binding Resolution

- [ ] **Option A: Operator bypass in `direct_resume_if_safe`**
  - [ ] Add operator identity check in `handle_direct_resume_if_safe`
  - [ ] Bypass `verify_agent_ownership` if caller is operator
  - [ ] Log operator actions separately

- [ ] **Option B: New operator-specific tool** (Recommended)
  - [ ] Create `operator_resume_if_safe(agent_id, reason, conditions)`
  - [ ] Wrapper around `direct_resume_if_safe` with operator bypass
  - [ ] Same safety checks (coherence > 0.40, risk < 0.60, void_active == false)
  - [ ] Add to `OPERATOR_MODE_TOOLS`

- [ ] **Option C: Dialectic-only** (Safest, but slower)
  - [ ] Operator can only trigger `request_dialectic_review`
  - [ ] No direct resume capability
  - [ ] Skip Phase 3, proceed to Phase 4

**Recommendation:** Implement Option B for Phase 3.

### Permissions Expansion

- [ ] Add `direct_resume_if_safe` or `operator_resume_if_safe` to operator permissions
- [ ] Update tool mode definition
- [ ] Document safety checks and thresholds

### Auto-Recovery Logic

- [ ] Implement safe recovery workflow
  - [ ] For each stuck agent: get metrics via `get_governance_metrics`
  - [ ] Check safety: coherence > 0.40, risk < 0.60, void_active == false
  - [ ] If safe: call `operator_resume_if_safe`
  - [ ] If unsafe: call `request_dialectic_review`
  - [ ] Log all actions

- [ ] Implement cooldown period
  - [ ] Track last recovery time per agent
  - [ ] Skip if recovered within last 15 minutes
  - [ ] Store in operator metadata or separate tracking

### Metrics & Monitoring

- [ ] Track recovery metrics
  - [ ] Success rate: recoveries attempted vs successful
  - [ ] False positive rate: agents recovered but immediately stuck again
  - [ ] Average recovery time: detection to recovery
  - [ ] Store in knowledge graph with tag `["operator", "metrics"]`

### Testing

- [ ] Test: operator can resume safe agents
- [ ] Test: operator cannot resume unsafe agents (safety checks enforced)
- [ ] Test: cooldown prevents repeated recoveries
- [ ] Test: rate limiting still applies
- [ ] Integration test: end-to-end stuck detection → recovery

---

## Phase 4: Knowledge Graph Maintenance

**Goal:** Operator automates KG hygiene: tagging, summarization, archival.

**Timeline:** 2-3 weeks  
**Risk Level:** Low-Medium (KG operations are reversible)

### Permissions Expansion

- [ ] Add KG write tools to operator permissions
  - [ ] `store_knowledge_graph` (already in read-only, expand to write)
  - [ ] `update_discovery_status_graph` (for archival)
  - [ ] `leave_note` (for summaries)

### Maintenance Loop

- [ ] Implement hourly maintenance loop
  - [ ] Schedule: every hour (configurable)
  - [ ] Operations: aggregation, tagging, summarization
  - [ ] Store results in knowledge graph

- [ ] Aggregation logic
  - [ ] Call `get_lifecycle_stats` for metrics
  - [ ] Group discoveries by tags and severity
  - [ ] Identify stale items (>7 days open, no updates)
  - [ ] Store summary via `store_knowledge_graph`

- [ ] Auto-tagging logic
  - [ ] Rule-based: infer tags from content (e.g., "bug", "improvement")
  - [ ] Semantic analysis: use `call_model` via ngrok.ai for content analysis
  - [ ] Duplicate detection: semantic similarity check
  - [ ] Update via `update_discovery_status_graph`

- [ ] Summarization
  - [ ] Daily digest: top 10 open items by severity
  - [ ] Weekly summary: trends and patterns
  - [ ] Store via `store_knowledge_graph` with tag `["operator", "digest"]`

- [ ] Archival automation
  - [ ] Resolved items >30 days old → archive
  - [ ] Test agent discoveries >90 days old → archive
  - [ ] Duplicate discoveries → merge and archive
  - [ ] Use `update_discovery_status_graph` with status="archived"

### Configuration

- [ ] Configurable thresholds
  - [ ] Stale threshold: days since last update (default: 7)
  - [ ] Archive threshold: days since resolved (default: 30)
  - [ ] Test agent archive threshold: days (default: 90)
  - [ ] Store in operator config or environment variables

### Testing

- [ ] Test: aggregation produces correct summaries
- [ ] Test: auto-tagging assigns appropriate tags
- [ ] Test: archival respects thresholds
- [ ] Test: maintenance loop runs on schedule
- [ ] Integration test: end-to-end KG maintenance

---

## Cross-Phase Requirements

### Infrastructure

- [ ] ngrok.ai integration (optional)
  - [ ] Configure `NGROK_AI_ENDPOINT` for operator
  - [ ] Use `call_model` tool for semantic analysis
  - [ ] Privacy mode for sensitive operations

- [ ] Monitoring & Alerting
  - [ ] Operator health checks
  - [ ] Alert if operator fails to run (e.g., no reports in 24h)
  - [ ] Metrics dashboard (optional)

### Documentation

- [ ] Operator runbook (see [CENTRAL_OPERATOR_AGENT_RUNBOOK.md](./CENTRAL_OPERATOR_AGENT_RUNBOOK.md))
- [ ] API documentation: operator tool modes
- [ ] Troubleshooting guide: common operator issues

### Security & Compliance

- [ ] Audit logging: all operator actions
- [ ] Rate limiting: prevent abuse
- [ ] Access control: operator identity verification
- [ ] Data retention: operator logs retention policy

---

## Success Criteria

**Phase 1:**
- ✅ Operator can detect stuck agents
- ✅ Operator reports are generated daily
- ✅ No false positives in stuck detection

**Phase 2:**
- ✅ Operator can trigger dialectic reviews
- ✅ Operator can mark responses complete
- ✅ Rate limiting prevents over-intervention

**Phase 3:**
- ✅ Operator can auto-recover safe agents
- ✅ Recovery success rate >80%
- ✅ False positive rate <10%

**Phase 4:**
- ✅ KG maintenance runs automatically
- ✅ KG freshness improves (open/resolved ratio decreases)
- ✅ Manual triage load decreases

---

## Rollback Plan

Each phase can be rolled back independently:

- **Phase 1:** Disable operator agent (no state changes)
- **Phase 2:** Remove write permissions, revert to read-only
- **Phase 3:** Disable auto-recovery, revert to Phase 2
- **Phase 4:** Disable maintenance loop, manual KG operations

---

## Next Steps

1. Review and approve implementation plan
2. Start Phase 1: Read-only operator
3. Validate Phase 1 before proceeding to Phase 2
4. Iterate based on feedback and metrics
