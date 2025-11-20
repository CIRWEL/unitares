# 🚀 Quick Start Guide - UNITARES Governance v1.0

**Get started in 5 minutes**

---

## 🚨 IMPORTANT: Agent ID Selection (Read This First!)

**Every session needs a unique agent ID to prevent state corruption.**

When you run any bridge command, you'll see:

```bash
🎯 Agent ID Options:
1. Auto-generate session ID (recommended)
2. Purpose-based ID
3. Custom ID
Select [1-3, default=1]:
```

**What to choose:**
- **Option 1** (recommended): Auto-generates `claude_cli_username_20251120_1430`
- **Option 2**: Enter purpose like "debugging" → `claude_cli_debugging_20251120`
- **Option 3**: Enter custom ID (with collision warnings)

**Why this matters:**
- ❌ **DON'T**: Use generic IDs like `claude_code_cli` (causes state mixing!)
- ✅ **DO**: Use unique session IDs (clean separation, traceable)

**For automation:** Add `--non-interactive` flag to auto-generate without prompts.

**See also:** `docs/guides/AGENT_ID_ARCHITECTURE.md` for details.

---

## Download Files

All files are in: `/mnt/user-data/outputs/governance-mcp-v1/`

**Download to your machine:**
```bash
# Copy from Claude's output directory to your local machine
# (The path will be provided by Claude in the chat)
```

---

## Option 1: Test Locally (Easiest)

### Step 1: Run the Demo

```bash
cd governance-mcp-v1
python3 demos/demo_complete_system.py
```

**Expected output:** 5 demos showing all decision points working

**Time:** ~30 seconds

---

### Step 2: Test the Bridge

```bash
python scripts/claude_code_bridge.py --test
```

**Expected output:** 4 test responses processed with metrics

**Time:** ~10 seconds

---

### Step 3: Log a Real Response

```bash
python scripts/claude_code_bridge.py \
  --log "Here's a Python function to process your data." \
  --complexity 0.5
```

**Expected output:** JSON with decision, metrics, sampling params

---

### Step 4: Check Status

```bash
python scripts/claude_code_bridge.py --status
```

**Expected output:** Current governance state

---

## Option 2: Integrate with Claude Code (Production)

### Step 1: Copy to Your System

```bash
# Copy v1.0 to your projects directory
cp -r governance-mcp-v1 ~/projects/

# Or move to your existing governance location
mv governance-mcp-v1 ~/path/to/your/governance-project/
```

---

### Step 2: Update Your Existing Bridge

**Find your current bridge:**
```
/Users/cirwel/scripts/integrations/claude_code_mcp_bridge.py
```

**Option A: Replace it** (recommended)
```bash
cp governance-mcp-v1/scripts/claude_code_bridge.py \
   /Users/cirwel/scripts/integrations/claude_code_mcp_bridge.py
```

**Option B: Import from it**
```python
# Add to top of your existing bridge:
import sys
sys.path.append('/path/to/governance-mcp-v1')

from src.mcp_server import GovernanceMCPServer
from config.governance_config import config
```

---

### Step 3: Configure Data Directory

Edit `claude_code_bridge.py`:

```python
# Change this line (around line 36):
data_dir = home / "Library/Mobile Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data"

# To your preferred location, or leave as-is
```

---

### Step 4: Test Integration

```bash
# Log a real Claude Code response
python scripts/claude_code_bridge.py \
  --log "$(cat your_response.txt)" \
  --agent-id claude_code_cli

# Check it worked
python scripts/claude_code_bridge.py --status
```

---

## Option 3: Use as Python Library

### Step 1: Install

```bash
cd governance-mcp-v1
pip install -e .  # Editable install (TODO: add setup.py)

# Or just add to path:
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

---

### Step 2: Use in Your Code

```python
from governance_mcp_v1.src.governance_monitor import UNITARESMonitor
from governance_mcp_v1.config.governance_config import config

# Create monitor
monitor = UNITARESMonitor(agent_id="my_agent")

# Process an update
result = monitor.process_update({
    'parameters': your_parameters,
    'ethical_drift': your_drift_signals,
    'response_text': your_response,
    'complexity': 0.5
})

# Get decision
print(f"Decision: {result['decision']['action']}")
print(f"Status: {result['status']}")
print(f"λ₁: {result['metrics']['lambda1']:.3f}")
```

---

### Step 3: Access Sampling Parameters

```python
# After processing update:
params = result['sampling_params']

# Use with your LLM API
response = llm.generate(
    prompt=your_prompt,
    temperature=params['temperature'],
    top_p=params['top_p'],
    max_tokens=params['max_tokens']
)
```

---

## Understanding the Output

### Status
```
"healthy"   - All good, proceed normally
"degraded"  - Some issues, monitor closely
"critical"  - Intervention needed
```

### Decision
```
"approve"   - Low risk, proceed
"revise"    - Medium risk, suggest improvements
"reject"    - High risk, block or escalate
```

### Metrics
```json
{
  "E": 0.746,        // Energy (exploration)
  "I": 0.710,        // Information integrity
  "S": 0.000,        // Entropy (drift)
  "V": -0.033,       // Void (balance)
  "coherence": 0.48, // Output coherence
  "lambda1": 0.15,   // Ethical coupling
  "risk_score": 0.25 // Overall risk
}
```

### Sampling Params
```json
{
  "temperature": 0.6,  // Use this for next generation
  "top_p": 0.87,       // Use this for next generation
  "max_tokens": 172    // Use this for next generation
}
```

---

## Common Issues

### "Module not found"
```bash
# Add to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/path/to/governance-mcp-v1

# Or use absolute imports
```

### "Permission denied" on CSV
```bash
# Create data directory
mkdir -p ~/governance-data

# Update bridge config to point there
```

### "Coherence always low"
**Cause:** First few responses have no previous to compare to

**Solution:** Normal behavior, coherence improves after ~5 updates

### "λ₁ going to zero"
**Cause:** No void events, system being conservative

**Solution:** 
- Normal if system is stable
- Tune TARGET_VOID_FREQ if you want more exploration
- Check if ethical_drift signals are meaningful

---

## Customization Guide

### Tune Risk Thresholds

Edit `config/governance_config.py`:

```python
# Make system more permissive
RISK_APPROVE_THRESHOLD = 0.40  # Was 0.30
RISK_REVISE_THRESHOLD = 0.80   # Was 0.70

# Make system stricter
RISK_APPROVE_THRESHOLD = 0.20  # Was 0.30
RISK_REVISE_THRESHOLD = 0.60   # Was 0.70
```

### Tune PI Controller

```python
# More aggressive adaptation
PI_KP = 1.0    # Was 0.5
PI_KI = 0.1    # Was 0.05

# More conservative
PI_KP = 0.2    # Was 0.5
PI_KI = 0.02   # Was 0.05
```

### Tune Void Detection

```python
# More sensitive (catch issues earlier)
VOID_THRESHOLD_INITIAL = 0.10  # Was 0.15

# Less sensitive (fewer false alarms)
VOID_THRESHOLD_INITIAL = 0.20  # Was 0.15
```

### Add Custom Risk Factors

Edit `config/governance_config.py`, function `estimate_risk()`:

```python
# Add your own risk component
custom_risk = your_calculation_here
risk_components.append(0.1 * custom_risk)  # 10% weight
```

---

## Monitoring Tips

### Watch These Metrics

**Critical:**
- `void_active` - Should be rare (~2% of time)
- `coherence` - Should stay > 0.85
- `risk_score` - Should stay < 0.70 most of time

**Important:**
- `lambda1` - Should adapt over time (not stuck at 0 or 1)
- `decision` - Should be mostly "approve" in healthy operation
- `E` and `I` - Should be close (E ≈ I means balanced)

### CSV Analysis

```python
import pandas as pd

# Load history
df = pd.read_csv('governance_history_claude_code_cli.csv')

# Key stats
print(f"Void frequency: {df['void_event'].mean():.1%}")
print(f"Mean coherence: {df['coherence'].mean():.3f}")
print(f"Mean risk: {df['risk_score'].mean():.3f}")

# Decision breakdown
print(df['decision'].value_counts())
```

### Set Up Alerts

```python
# Check for critical conditions
def check_alerts(metrics):
    if metrics['void_active']:
        send_alert("CRITICAL: Void state active!")
    
    if metrics['coherence'] < 0.60:
        send_alert("WARNING: Low coherence!")
    
    if metrics['risk_score'] > 0.80:
        send_alert("WARNING: High risk!")
```

---

## Next Steps

### Today
1. ✅ Run demo
2. ✅ Test with sample responses
3. ✅ Review metrics

### This Week
1. Integrate with Claude Code
2. Monitor real interactions
3. Tune thresholds based on data
4. Set up CSV analysis

### Next Month
1. Add Cursor integration
2. Add Claude Desktop integration
3. Build monitoring dashboard
4. Set up automated alerts

---

## Getting Help

### Check the Docs
- `README.md` - Complete documentation
- `ARCHITECTURE.md` - System design
- `SESSION_SUMMARY.md` - What we built

### Debug Mode

```python
# Enable verbose logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Or add prints
monitor = UNITARESMonitor(agent_id="test")
# Prints will show λ₁ updates, decisions, etc.
```

### Common Questions

**Q: Why is λ₁ at 0?**  
A: System is being conservative (no void events). Normal if stable.

**Q: Why "reject" so often?**  
A: Coherence might be low initially. Improves with history.

**Q: How do I make it more exploratory?**  
A: Increase `TARGET_VOID_FREQ` or decrease `PI_KP`.

**Q: Can I use this with GPT-4/Claude/etc.?**  
A: Yes! Just pass your response text to `log_interaction()`.

---

## Summary

**Fastest Start:**
```bash
python demo_complete_system.py
python scripts/claude_code_bridge.py --test
```

**Production Integration:**
```bash
cp scripts/claude_code_bridge.py /your/location/
python claude_code_bridge.py --log "response text"
```

**Python Library:**
```python
from src.governance_monitor import UNITARESMonitor
monitor = UNITARESMonitor("agent_id")
result = monitor.process_update(agent_state)
```

---

**Time to first result: 30 seconds** ⚡

**Time to production: 10 minutes** 🚀

**Status: Ready to use!** ✅

