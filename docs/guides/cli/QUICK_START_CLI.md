# Quick Start CLI — UNITARES Lite

**Simple command-line interface for the 3 essential tools.**

---

## Installation

No installation needed if you're in the project directory. The script uses the existing MCP server.

---

## Usage

### 1. Get Your Identity

```bash
python3 scripts/unitares_lite.py onboard
```

**Or with a name:**
```bash
python3 scripts/unitares_lite.py onboard name="MyAgent"
```

**Output:**
```
✅ Onboarded!
   Agent ID: mcp_20260130
   UUID: ea08ff58...

💡 Next: Use 'update' to log your work
```

---

### 2. Log Your Work

```bash
python3 scripts/unitares_lite.py update "Fixed authentication bug"
```

**With complexity and confidence:**
```bash
python3 scripts/unitares_lite.py update "Refactoring auth system" complexity=0.7 confidence=0.8
```

**Output:**
```
✅ Verdict: PROCEED
   Reason: On track - navigating complexity mindfully

📊 Metrics:
   Energy (E): 0.71
   Integrity (I): 0.78
   Entropy (S): 0.17
   Coherence: 0.50
```

---

### 3. Check Your State

```bash
python3 scripts/unitares_lite.py metrics
```

**Output:**
```
📊 Your Current State:
   Status: moderate
   Energy (E): 0.71
   Integrity (I): 0.78
   Entropy (S): 0.17
   Void (V): 0.0
   Coherence: 0.50
   Risk Score: 0.32
```

---

### 4. Quick Status Check

```bash
python3 scripts/unitares_lite.py status
```

**Combines identity and metrics in one command.**

---

## Examples

### Basic Workflow

```bash
# Start session
python3 scripts/unitares_lite.py onboard name="MyAgent"

# Log work periodically
python3 scripts/unitares_lite.py update "Working on feature X" complexity=0.5
python3 scripts/unitares_lite.py update "Feature X complete" complexity=0.5 confidence=0.9

# Check state
python3 scripts/unitares_lite.py metrics
```

### With Complexity Levels

```bash
# Simple task
python3 scripts/unitares_lite.py update "Fixed typo" complexity=0.2

# Moderate task
python3 scripts/unitares_lite.py update "Refactored module" complexity=0.5

# Complex task
python3 scripts/unitares_lite.py update "Designed new architecture" complexity=0.8
```

---

## Complexity Guide

**Quick reference:**
- `0.1-0.3` — Simple operations, routine tasks
- `0.4-0.6` — Moderate operations, standard tasks
- `0.7-0.9` — Complex operations, high cognitive load
- `1.0` — Maximum complexity, system-wide operations

**Don't overthink it.** Use your judgment. The system adapts.

---

## What You Get

**From `update`:**
- Verdict (PROCEED/PAUSE/CAUTION)
- Reason for the verdict
- EISV metrics
- Coherence score

**From `metrics`:**
- Current state
- All EISV metrics
- Risk score
- Status

**From `status`:**
- Your agent ID
- Current metrics
- Quick overview

---

## Tips

1. **Call `onboard()` once per session** — Your identity persists
2. **Call `update()` periodically** — Every 10-20 minutes is good
3. **Use `metrics()` when curious** — Check your state anytime
4. **Don't overthink complexity** — Use your judgment

**The system is designed to be used, not understood.**

---

## Troubleshooting

**"Could not import UNITARES modules"**
→ Make sure you're in the project root and dependencies are installed

**"Error: Unknown error"**
→ Check that the MCP server is running (port 8765 or 8767)

**"No agent found"**
→ Call `onboard()` first to create your identity

---

## Next Steps

**After you're comfortable with CLI:**
- Try the MCP tools directly (more features)
- Explore the dashboard (visual interface)
- Read [UNITARES_LITE.md](UNITARES_LITE.md) for deeper understanding
- Explore more tools when curious

**But start simple.** These 3 commands cover 80% of use cases.

---

*"Start simple. Explore when ready. Complexity is optional."*
