# 🚀 One-Command Installation Guide

## What You're Installing

**UNITARES Governance v1.0** - AI governance system with:
- Risk estimation (0-1 score)
- Decision logic (approve/revise/reject)
- Adaptive control (λ₁ self-tunes)
- CSV logging (to your Obsidian vault)
- Complete monitoring framework

---

## Step 1: Verify Project Structure

The project structure has been created at:
```
~/projects/governance-mcp-v1/
```

All files are in place! ✅

---

## Step 2: Test It Works (30 seconds)

```bash
cd ~/projects/governance-mcp-v1
python3 demo_complete_system.py
```

**Expected output:**
```
######################################################################
#      UNITARES Governance Framework v1.0 - Complete System Demo     #
######################################################################

=== DEMO 1: Five Concrete Decision Points ===

1. λ₁ → Sampling Parameters Transfer Function
  λ₁=0.0: temp=0.50, top_p=0.85, max_tokens=100
  λ₁=0.3: temp=0.71, top_p=0.88, max_tokens=220
  ...
```

**If you see this:** ✅ Installation successful!

---

## Step 3: Test the Bridge (10 seconds)

```bash
cd ~/projects/governance-mcp-v1
python3 scripts/claude_code_bridge.py --test
```

**Expected output:**
```
[Bridge] Initialized for agent: demo_claude_code
Running Claude Code Bridge Test

[Test 1] Processing response...
  Status: critical
  Decision: reject - Coherence critically low...
  ...
```

**If you see this:** ✅ Bridge works!

---

## Step 4: Log Your First Response (NOW!)

```bash
cd ~/projects/governance-mcp-v1

python3 scripts/claude_code_bridge.py \
  --log "Here's a simple Python function to calculate fibonacci numbers."
```

**Expected output:**
```json
{
  "success": true,
  "status": "healthy",
  "decision": {
    "action": "approve",
    "reason": "Low risk (0.23)",
    "require_human": false
  },
  "metrics": {
    "E": 0.52,
    "I": 0.90,
    "coherence": 0.89,
    "lambda1": 0.15,
    "risk_score": 0.23
  },
  "sampling_params": {
    "temperature": 0.605,
    "top_p": 0.865,
    "max_tokens": 160
  }
}
```

**If you see this:** ✅ You're running governance!

---

## Step 5: Check CSV Was Created

```bash
ls -la ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data/

# Should see:
# governance_history_demo_claude_code.csv
```

**View the CSV:**
```bash
cat ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data/governance_history_demo_claude_code.csv
```

---

## Step 6 (Optional): Create Wrapper Script

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
  python3 ~/projects/governance-mcp-v1/scripts/claude_code_bridge.py \
    --log "$RESPONSE" \
    --agent-id "claude_code_cli" \
    > /dev/null 2>&1
) &

# Return Claude Code's exit code
exit $?
```

**Make executable:**
```bash
chmod +x ~/bin/claude-code-monitored

# Add ~/bin to PATH if not already (add to ~/.zshrc):
export PATH="$HOME/bin:$PATH"

# Reload shell:
source ~/.zshrc
```

**Test wrapper:**
```bash
claude-code-monitored "echo hello"
```

---

## Alternative: Quick Alias (Easier)

Instead of wrapper script, just alias:

```bash
# Add to ~/.zshrc or ~/.bashrc:
alias ccm='claude-code-monitored-func() { 
  RESPONSE=$(claude-code "$@" 2>&1); 
  echo "$RESPONSE"; 
  (python3 ~/projects/governance-mcp-v1/scripts/claude_code_bridge.py --log "$RESPONSE" &); 
}; claude-code-monitored-func'

# Reload:
source ~/.zshrc

# Use:
ccm "your request"
```

---

## What You Get

### Before:
```bash
$ claude-code "fix bug"
[response shown]
# Response lost forever
```

### After:
```bash
$ ccm "fix bug"
[response shown]
# Automatically logged to:
# - CSV in Obsidian vault
# - Risk scored
# - Decision made
# - λ₁ adapted
# - Ready for analysis
```

---

## Troubleshooting

### "Module not found"
```bash
# Make sure you're in the right directory:
cd ~/projects/governance-mcp-v1

# Or add to PYTHONPATH:
export PYTHONPATH="$HOME/projects/governance-mcp-v1:$PYTHONPATH"
```

### "Permission denied"
```bash
# Make scripts executable:
chmod +x ~/projects/governance-mcp-v1/scripts/*.py
chmod +x ~/bin/claude-code-monitored
```

### "CSV not created"
```bash
# Create directory manually:
mkdir -p ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data/

# Or edit bridge to use different location:
nano ~/projects/governance-mcp-v1/scripts/claude_code_bridge.py
# Line ~43: Change data_dir path
```

---

## Summary: What to Do Right Now

**Minimum viable (5 minutes):**
```bash
# 1. Test it works:
cd ~/projects/governance-mcp-v1
python3 demo_complete_system.py

# 2. Test bridge:
python3 scripts/claude_code_bridge.py --test

# 3. Log a response:
python3 scripts/claude_code_bridge.py --log "test response"
```

**Full setup (15 minutes):**
```bash
# + All the above
# + Create wrapper script
# + Create alias or add to PATH
# + Test with real claude-code response
```

---

## My Recommendation

Start with **manual logging** today:

```bash
# After any claude-code call:
claude-code "your request" > /tmp/response.txt

# Then log it:
python3 ~/projects/governance-mcp-v1/scripts/claude_code_bridge.py \
  --log "$(cat /tmp/response.txt)"
```

Do this for a few days, see if you like the data.

Then add the wrapper/alias for automation.

---

**Ready to test?** Run `python3 demo_complete_system.py` now!

