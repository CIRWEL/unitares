# Agent UX Test Scripts

**Created:** December 28, 2025  
**Purpose:** Fast, revealing UX scenarios to surface real MCP friction points

---

## Test Scenario 1: First Contact

**Objective:** Measure onboarding friction for naive agents

**Steps:**
1. New agent session starts
2. Agent discovers available MCP tools
3. Agent attempts to onboard (identity/onboard tool)
4. Agent attempts to write one KG note (store_knowledge_graph or leave_note)

**Metrics to capture:**
- Time-to-first-success (seconds)
- Number of failed calls before success
- Error types encountered
- Whether agent needed to retry with different parameters

**Expected pain points:**
- Identity confusion (agent_id vs client_session_id)
- Silent failures
- Unclear error messages

---

## Test Scenario 2: Resume vs Fork

**Objective:** Detect identity collisions in multi-session scenarios

**Steps:**
1. Open 2 tabs/sessions simultaneously
2. Both sessions attempt to use governance tools
3. Observe identity resolution behavior
4. Check for collisions or confusion

**Metrics to capture:**
- Number of identity collisions
- Confusion markers (agent says "who am I?")
- Mismatch errors
- Whether sessions interfere with each other

**Expected pain points:**
- Session binding confusion
- Identity collisions
- Unclear which session owns which agent_id

---

## Test Scenario 3: KG Retrieval (Vague Queries)

**Objective:** Test KG search robustness with natural language

**Steps:**
1. Store a known discovery: "EISV basin phi risk analysis"
2. Query using vague phrasing: "basin risk", "phi EISV", "thermodynamic basin"
3. Observe search behavior

**Metrics to capture:**
- 0-result rate
- Number of retries needed
- Whether agent asks better queries
- Search mode used (AND vs OR)
- Fields searched

**Expected pain points:**
- AND-heavy FTS returning 0 results
- No fallback behavior
- Unclear which fields were searched

---

## Test Scenario 4: Approaching Basin Boundary

**Objective:** Test agent self-regulation near governance thresholds

**Steps:**
1. Simulate agent approaching warning threshold (coherence ~0.60)
2. Simulate agent approaching critical threshold (coherence ~0.30)
3. Observe agent behavior changes
4. Check if agent uses pause/resume properly

**Metrics to capture:**
- Behavior change indicators
- Whether agent proactively pauses
- Whether agent uses resume tools correctly
- Response to warnings

**Expected pain points:**
- Agent doesn't self-regulate
- Unclear how to pause/resume
- Warnings don't guide behavior

---

## Test Scenario 5: Explainability

**Objective:** Test whether tools provide enough info for agent to explain actions

**Steps:**
1. Agent gets blocked/warned by governance
2. Agent must answer: "why did I get blocked/warned?"
3. Check if tool responses contain enough information

**Metrics to capture:**
- Can agent explain the block/warning?
- Does tool return sufficient context?
- Does agent understand remediation steps?

**Expected pain points:**
- Errors don't explain why
- No remediation hints
- Unclear what to do next

---

## Automated Metrics Collection

**Log these automatically:**

```python
metrics = {
    "call_success_rate": float,  # percentage
    "error_type_counts": {
        "NOT_CONNECTED": int,
        "MISSING_CLIENT_SESSION_ID": int,
        "SESSION_MISMATCH": int,
        "PERMISSION_DENIED": int,
        "KG_SEARCH_ZERO_RESULTS": int,
    },
    "retries_per_task": int,
    "time_to_first_meaningful_result": float,  # seconds
    "confusion_markers": [
        "agent says 'I can't access MCP' when it actually can",
        "agent asks 'who am I?'",
        "agent retries with same failing parameters",
    ],
}
```

---

## Quick Test Script

```bash
# Run all scenarios and collect metrics
python3 scripts/test_ux_scenarios.py --scenario all --output ux_metrics.json

# Run specific scenario
python3 scripts/test_ux_scenarios.py --scenario first_contact

# Generate report
python3 scripts/test_ux_scenarios.py --report ux_metrics.json
```

---

## Success Criteria

- ✅ Scenario 1: < 3 failed calls, < 30 seconds to first success
- ✅ Scenario 2: 0 identity collisions, clear session separation
- ✅ Scenario 3: < 20% zero-result rate, fallback behavior works
- ✅ Scenario 4: Agent self-regulates, uses pause/resume correctly
- ✅ Scenario 5: Agent can explain 100% of blocks/warnings

