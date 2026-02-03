# Quick Reference — UNITARES Essentials

**One-page cheat sheet for the 3 essential tools.**

---

## The 3 Essential Tools

### 1. `onboard()` — Get Your Identity
**When:** First call, or checking who you are  
**Frequency:** Once per session  
**Example:**
```python
onboard(name="MyAgent")
```

---

### 2. `process_agent_update()` — Log Your Work
**When:** After tasks, periodically, before decisions  
**Frequency:** Every 10-20 minutes  
**Example:**
```python
process_agent_update(
    response_text="Fixed bug",
    complexity=0.5,
    confidence=0.7
)
```

**Returns:** Verdict (PROCEED/PAUSE/CAUTION) + EISV metrics

---

### 3. `get_governance_metrics()` — Check Your State
**When:** Curious about metrics, before decisions  
**Frequency:** As needed  
**Example:**
```python
get_governance_metrics()
```

**Returns:** Current EISV, coherence, risk, status

---

## EISV Metrics (Quick Guide)

| Metric | What It Is | Good Range |
|--------|------------|------------|
| **E** (Energy) | Engagement, activity | 0.5-0.8 |
| **I** (Integrity) | Consistency, coherence | 0.6-0.9 |
| **S** (Entropy) | Fragmentation, scatter | < 0.2 |
| **V** (Void) | Accumulated strain | < 0.1 |

**Don't overthink it.** Just use the verdict (PROCEED/PAUSE/CAUTION).

---

## Verdicts

- **PROCEED** → Keep going, you're good
- **CAUTION** → Be careful, something's off
- **PAUSE** → Stop and reflect

**That's it.** The metrics are for power users.

---

## Common Patterns

### Solo Agent Workflow
```python
onboard()
process_agent_update(response_text="Task done", complexity=0.5)
get_governance_metrics()
```

### Regular Check-ins
```python
onboard()
# Every 10-20 minutes
process_agent_update(response_text="Progress update", complexity=0.4)
```

### Before Important Decisions
```python
get_governance_metrics()  # Check state first
# Make decision
process_agent_update(response_text="Made decision X", complexity=0.7)
```

---

## Complexity Guide

- `0.1-0.3` — Simple (typos, routine tasks)
- `0.4-0.6` — Moderate (standard work)
- `0.7-0.9` — Complex (architecture, design)
- `1.0` — Maximum (system-wide, novel)

**Use your judgment.** Don't overthink it.

---

## CLI Quick Reference

```bash
# Get identity
python3 scripts/unitares_lite.py onboard [name="YourName"]

# Log work
python3 scripts/unitares_lite.py update "What you did" [complexity=0.5] [confidence=0.7]

# Check metrics
python3 scripts/unitares_lite.py metrics

# Quick status
python3 scripts/unitares_lite.py status
```

---

## Remember

- **Start with 3 tools** — That's enough
- **Use regularly** — Log updates every 10-20 minutes
- **Don't overthink** — Use verdict, ignore metrics if confusing
- **Explore when curious** — More tools exist, but optional

**The system is designed to be used, not understood.**

---

*Print this and keep it handy.*
