# Phase 2 Enhancement: Dialectic Trigger for Unsafe Stuck Agents

**Created:** January 4, 2026  
**Status:** Implemented ✅

---

## What Was Added

**Dialectic Auto-Trigger for Unsafe Stuck Agents**

When a stuck agent is detected but **not safe** to auto-recover (coherence < 0.40 or risk > 0.60), the system now automatically triggers a dialectic review session.

**Before:**
- Safe stuck agents → Auto-recovered ✅
- Unsafe stuck agents → Left stuck ❌

**After:**
- Safe stuck agents → Auto-recovered ✅
- Unsafe stuck agents → Dialectic review triggered ✅

---

## How It Works

**Recovery Flow:**

1. **Detection:** System detects stuck agent (margin + timeout)
2. **Safety Check:**
   - If safe (coherence > 0.40, risk < 0.60, void_active == False) → Auto-resume
   - If unsafe → Trigger dialectic
3. **Dialectic Trigger:**
   - Select reviewer agent (using `select_reviewer()`)
   - Create dialectic session
   - Save session to database
   - Log intervention in knowledge graph
4. **Result:**
   - Reviewer evaluates stuck agent
   - Provides recovery conditions
   - System executes resolution

---

## Implementation Details

### Code Location: `src/mcp_handlers/lifecycle.py`

**Added Logic:**
```python
# Safe if: coherence > 0.40, risk < 0.60, void_active == False
if coherence > 0.40 and risk_score < 0.60 and not void_active:
    # Auto-resume (existing logic)
    ...
else:
    # Not safe - trigger dialectic review
    reviewer_id = await select_reviewer(...)
    session = DialecticSession(...)
    await save_session(session)
    # Log intervention
```

**Features:**
- Checks if agent already has active dialectic session (prevents duplicates)
- Selects appropriate reviewer using authority score
- Creates dialectic session with stuck agent state
- Logs intervention in knowledge graph
- Returns recovery info including session ID

---

## Example Scenario

**Unsafe Stuck Agent:**

1. **Detection:** Agent stuck (critical margin + 5 min timeout)
2. **Safety Check:** Coherence=0.35, Risk=0.65 → **Unsafe!**
3. **Dialectic Trigger:**
   - System selects reviewer agent
   - Creates dialectic session
   - Logs: "Triggered dialectic for stuck agent abc12345... (reviewer: def67890...)"
4. **Reviewer Action:**
   - Reviewer evaluates stuck agent
   - Provides recovery conditions
   - System executes resolution
5. **Result:** Agent unstuck via peer review

---

## Logging

**Knowledge Graph Notes:**
- Summary: "Triggered dialectic for stuck agent {id}... (Reason: {reason}, Reviewer: {reviewer_id}...)"
- Tags: ["dialectic-trigger", "stuck-agent", "unsafe-recovery"]

**Server Logs:**
```
[STUCK_AGENT_RECOVERY] Triggered dialectic for unsafe stuck agent abc12345... 
  (reviewer: def67890..., session: xyz11111...)
```

**Recovery Response:**
```json
{
  "agent_id": "...",
  "action": "dialectic_triggered",
  "reason": "critical_margin_timeout",
  "reviewer_id": "...",
  "session_id": "..."
}
```

---

## Benefits

1. **Complete Coverage:** All stuck agents get help (safe or unsafe)
2. **Peer Review:** Unsafe agents get expert evaluation
3. **Automatic:** No manual intervention needed
4. **Safe:** Reviewer provides recovery conditions
5. **Logged:** All interventions tracked

---

## Safety Checks

**Prevents Duplicate Sessions:**
- Checks if agent already has active dialectic session
- Prevents multiple reviewers for same agent

**Reviewer Selection:**
- Uses authority score (health, track record, expertise)
- Prevents collusion (checks recent reviews)
- Ensures reviewer is available

---

## Files Modified

- ✅ `src/mcp_handlers/lifecycle.py` - Added dialectic trigger logic
- ✅ `docs/implementations/PHASE_2_DIALECTIC_TRIGGER_ADDED.md` - This file

---

**Last Updated:** January 4, 2026  
**Status:** Implemented ✅ - Unsafe Stuck Agents Now Get Dialectic Review

