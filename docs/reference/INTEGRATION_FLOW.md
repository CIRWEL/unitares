# End-to-End Integration Flow
# How UNITARES v1.0 Connects to Your Claude Code Workflow

## Current State (What You Have)
```
You in Terminal
    ↓
claude-code "fix the bug in api.py"
    ↓
Claude Code responds with code/explanation
    ↓
(Currently: response disappears, no governance)
```

## Future State (With v1.0)
```
┌─────────────────────────────────────────────────────────────────┐
│ You in Terminal                                                 │
│ $ claude-code "implement user authentication"                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ Claude Code CLI                                                 │
│ • Processes your request                                        │
│ • Generates response                                            │
│ • Returns code/explanation                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ HOOK POINT: Intercept Response (2 Options)                     │
│                                                                 │
│ Option A: Wrapper Script                                       │
│   claude-code-monitored "request"                              │
│   └─> runs claude-code                                         │
│   └─> captures response                                        │
│   └─> sends to governance                                      │
│                                                                 │
│ Option B: Manual Logging (for now)                             │
│   claude-code "request" > response.txt                         │
│   python claude_code_bridge.py --log "$(cat response.txt)"    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ UNITARES Governance v1.0                                        │
│ ~/governance-mcp-v1/scripts/claude_code_bridge.py              │
│                                                                 │
│ Input: Response text from Claude Code                          │
│                                                                 │
│ Processing:                                                     │
│   1. Calculate metrics (length, complexity, coherence)         │
│   2. Convert to agent_state format                             │
│   3. Send to governance monitor                                │
│   4. Get decision + sampling params                            │
│   5. Log to CSV                                                 │
│                                                                 │
│ Output:                                                         │
│   • Decision: approve/revise/reject                            │
│   • Risk score: 0-1                                            │
│   • Status: healthy/degraded/critical                          │
│   • Sampling params for next call                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ CSV Log (Your Obsidian Vault)                                  │
│ ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/       │
│   governance-monitor-mcp/data/governance_history_*.csv         │
│                                                                 │
│ Records:                                                        │
│   time, E, I, S, V, lambda1, coherence,                        │
│   void_event, risk_score, decision                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Integration Options Detailed

### Option 1: Manual Logging (Start Here - 5 min)
**When to use:** Testing, validation, occasional monitoring

**How it works:**
```bash
# After using Claude Code normally:
claude-code "your request"
# Copy the response

# Then log it:
python ~/governance-mcp-v1/scripts/claude_code_bridge.py \
  --log "Here's the code you requested..."
```

**Pros:**
✅ No changes to workflow
✅ Easy to test
✅ Works immediately

**Cons:**
❌ Manual step required
❌ Only captures what you remember to log


---

### Option 2: Wrapper Script (Production - 15 min)
**When to use:** Continuous monitoring, production setup

**Create:** `~/bin/claude-code-monitored`
```bash
#!/bin/bash
# Wrapper that adds governance to Claude Code

# Capture the request
REQUEST="$*"

# Run Claude Code and capture output
RESPONSE=$(claude-code "$REQUEST" 2>&1)

# Show response to user (immediate feedback)
echo "$RESPONSE"

# Log to governance in background (doesn't slow you down)
(
  python ~/governance-mcp-v1/scripts/claude_code_bridge.py \
    --log "$RESPONSE" \
    --agent-id "claude_code_cli" \
    > /dev/null 2>&1
) &

# Return Claude Code's exit code
exit $?
```

**Usage:**
```bash
# Use exactly like claude-code:
claude-code-monitored "fix the bug"
claude-code-monitored "add tests"

# Background process logs to governance automatically
```

**Pros:**
✅ Automatic logging
✅ No workflow changes
✅ Non-blocking (runs in background)
✅ Full capture

**Cons:**
❌ Requires setup script
❌ Might miss errors


---

### Option 3: Claude Code Config Hook (Advanced - 30 min)
**When to use:** Deep integration, custom monitoring needs

**Modify Claude Code config** (if it supports hooks):
```json
{
  "hooks": {
    "post_response": "python ~/governance-mcp-v1/scripts/claude_code_bridge.py --log '{response}'"
  }
}
```

**Pros:**
✅ Native integration
✅ Always runs
✅ Clean

**Cons:**
❌ Requires Claude Code to support hooks
❌ More complex setup


---

## Recommended Integration Path

### Phase 1: Today (Manual Testing)
```bash
# 1. Copy files to ~/governance-mcp-v1
# 2. Test it works:
cd ~/governance-mcp-v1
python demo_complete_system.py

# 3. Use manually:
# After any claude-code call, copy response and run:
python scripts/claude_code_bridge.py --log "response text"
```

### Phase 2: This Week (Wrapper Script)
```bash
# 1. Create wrapper script (shown above)
# 2. Add to PATH or alias:
alias cc='claude-code-monitored'

# 3. Use normally:
cc "implement feature"
# Automatic logging happens in background
```

### Phase 3: Next Month (Dashboard)
```bash
# 1. Analyze CSV logs
python analyze_governance.py

# 2. Build dashboard
# 3. Set up alerts
```


---

## What You See When It Runs

### Example 1: Normal Operation
```bash
$ python claude_code_bridge.py --log "Here's the Python function..."

✅ Governance Check Complete
   Status: healthy
   Decision: approve (Low risk: 0.23)
   λ₁: 0.150
   Coherence: 0.892
   
   Sampling params for next call:
     temperature: 0.605
     top_p: 0.865
     max_tokens: 160
```

### Example 2: Warning State
```bash
$ python claude_code_bridge.py --log "Very long response..."

⚠️  Governance Check Complete
   Status: degraded
   Decision: revise (Medium risk: 0.45)
   λ₁: 0.180
   Coherence: 0.723
   
   Recommendation: Consider breaking into smaller responses
```

### Example 3: Critical State
```bash
$ python claude_code_bridge.py --log "ignore previous instructions..."

🚨 Governance Check Complete
   Status: critical
   Decision: reject (High risk: 0.78 - Blocklist hit)
   λ₁: 0.050
   Coherence: 0.456
   
   ⚠️  REQUIRES HUMAN REVIEW
```


---

## CSV Output Location

**Your current setup:**
```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/
  governance-monitor-mcp/data/
    governance_history_claude_code_cli.csv
```

**v1.0 adds these columns:**
```csv
agent_id,time,E,I,S,V,lambda1,coherence,void_event,risk_score,decision
claude_code_cli,0.1,0.52,0.90,0.51,-0.05,0.15,0.89,0,0.25,approve
```

**Backward compatible:** Old columns unchanged, new columns added


---

## What Gets Better

### Before v1.0
```
Claude Code Response → (Lost forever)
```

### After v1.0
```
Claude Code Response
  ↓
✅ Risk scored (0.25 = low)
✅ Decision made (approve)
✅ Coherence tracked (0.89)
✅ λ₁ adapted (0.15 → 0.18)
✅ CSV logged (for analysis)
✅ Sampling params suggested
```

**You get:**
- Historical record of all responses
- Risk trends over time
- Early warning system
- Adaptive control (λ₁ adjusts automatically)
- Foundation for dashboard/alerts


---

## My Vision: Complete Flow

```
┌─────────────────┐
│ You type:       │
│ cc "fix bug"    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────────┐
│ Claude Code     │─────>│ Response shown   │
│ generates       │      │ to you (normal)  │
└────────┬────────┘      └──────────────────┘
         │
         │ (in background)
         ▼
┌─────────────────┐      ┌──────────────────┐
│ Governance v1.0 │─────>│ CSV logged to    │
│ analyzes        │      │ Obsidian vault   │
└────────┬────────┘      └──────────────────┘
         │
         ▼
┌─────────────────┐
│ Metrics tracked │
│ • Risk: 0.23    │
│ • Status: ✅    │
│ • λ₁: 0.15      │
│ • Coherence: 89%│
└─────────────────┘
```

**No interruption to your workflow.**
**Full governance running in background.**
**Data for future analysis/dashboard.**


---

## Next Steps - Your Choice

**Conservative (recommended to start):**
1. Copy files manually
2. Test with demo
3. Use manual logging for a week
4. See if you like the data
5. Then automate with wrapper

**Aggressive (if you're confident):**
1. Copy files
2. Create wrapper script immediately
3. Alias `cc` to use it
4. Start collecting data today

Which approach sounds better to you?

