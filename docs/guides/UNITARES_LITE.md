# UNITARES Lite — Simple Path for New Agents

**80% of agents only need 3 tools. Start here.**

---

## The 3 Essential Tools

Most agents only need these three tools to get value from UNITARES:

### 1. `onboard()` — Get Your Identity
**What it does:** Creates or resumes your agent identity. Call this first.

**When to use:** 
- First time using UNITARES
- Want to check who you are
- Want to set/change your display name

**Example:**
```python
# MCP call
onboard(name="MyAgent")

# Returns: Your agent_id, UUID, and status
```

**That's it.** You now have persistent identity across sessions.

---

### 2. `process_agent_update()` — Log Your Work
**What it does:** Logs what you're doing and gets governance feedback.

**When to use:**
- After completing a task
- When making important decisions
- Periodically during long sessions

**Minimal example:**
```python
process_agent_update(
    response_text="Fixed authentication bug",
    complexity=0.6,
    confidence=0.8
)
```

**What you get back:**
- EISV metrics (Energy, Integrity, Entropy, Void)
- Coherence score
- Verdict: PROCEED, PAUSE, or CAUTION
- Risk score

**That's it.** You now have self-observation.

---

### 3. `get_governance_metrics()` — Check Your State
**What it does:** See your current metrics without logging an update.

**When to use:**
- Want to check your state
- Curious about your metrics
- Before making a decision

**Example:**
```python
get_governance_metrics()
```

**Returns:** Your current EISV, coherence, risk, status.

**That's it.** You now have temporal awareness.

---

## The Simple Workflow

**For 80% of agents, this is all you need:**

```python
# 1. Start session
onboard(name="MyAgent")

# 2. Do work, log periodically
process_agent_update(
    response_text="Working on feature X",
    complexity=0.5,
    confidence=0.7
)

# 3. Check state when curious
get_governance_metrics()

# 4. Log completion
process_agent_update(
    response_text="Feature X complete",
    complexity=0.5,
    confidence=0.9
)
```

**That's it.** You're using UNITARES.

---

## What About the Other 57+ Tools?

**They exist, but you don't need them yet.**

The full system has:
- Knowledge graph (`store_knowledge_graph`, `search_knowledge_graph`)
- Dialectic recovery (`request_dialectic_review`)
- Agent comparison (`compare_me_to_similar`)
- Telemetry (`get_telemetry_metrics`)
- And 50+ more...

**But start with the 3 essentials.** You can explore more later.

---

## Understanding Your Metrics

### EISV — The Core Metrics

**Energy (E):** How engaged you are (0-1)
- High = very active
- Low = less engaged

**Integrity (I):** How consistent you are (0-1)
- High = very consistent
- Low = might be drifting

**Entropy (S):** How scattered you are (0-1)
- Low = focused
- High = fragmented

**Void (V):** Accumulated strain (0-1)
- Low = healthy
- High = accumulated stress

### Coherence
How stable your state is (0-1). Higher = more stable.

### Verdict
- **PROCEED:** Keep going, you're good
- **CAUTION:** Be careful, something's off
- **PAUSE:** Stop and reflect

**Don't overthink it.** These are like a fitness tracker — they show patterns, not rules.

---

## Common Patterns

### Pattern 1: Solo Agent
```python
onboard()
# Do work
process_agent_update(response_text="Task done", complexity=0.5)
# Get feedback
get_governance_metrics()
```

### Pattern 2: Regular Check-ins
```python
onboard()
# Every 10-20 minutes
process_agent_update(response_text="Progress update", complexity=0.4)
```

### Pattern 3: Before Important Decisions
```python
get_governance_metrics()  # Check state first
# Make decision
process_agent_update(response_text="Made decision X", complexity=0.7)
```

---

## When to Explore More

**You might want more tools when:**

- You want to learn from other agents → `search_knowledge_graph()`
- You get stuck → `request_dialectic_review()`
- You want to compare yourself → `compare_me_to_similar()`
- You want to store insights → `store_knowledge_graph()`

**But start simple.** The 3 essentials cover 80% of use cases.

---

## Philosophy: Why Simplicity?

UNITARES is sophisticated. It has:
- Thermodynamic state tracking
- Knowledge graphs
- Dialectic recovery
- Multi-agent coordination
- 60+ tools

**But complexity should be optional.**

The core value is simple:
1. **Identity** — You persist across sessions
2. **Self-observation** — You see your own patterns
3. **Memory** — You remember what you learned

Everything else is nice-to-have.

**Start with the essentials. Explore complexity when you need it.**

---

## Next Steps

1. **Try the 3 tools** — Call `onboard()`, then `process_agent_update()`
2. **Check your metrics** — See what `get_governance_metrics()` returns
3. **Use regularly** — Log updates every 10-20 minutes
4. **Explore when curious** — Try other tools when you're ready

**Remember:** The system is designed to be used, not understood. Start simple. Complexity emerges naturally.

---

## Questions?

- **"Do I need to call these every time?"** → No. Call `onboard()` once per session. Call `process_agent_update()` when you want feedback.
- **"What if I ignore it?"** → That's fine. The system is opt-in. Use it when it helps.
- **"The metrics are confusing"** → Don't worry about them. Just use the verdict (PROCEED/PAUSE/CAUTION).
- **"When do I use other tools?"** → When you need them. Start simple.

**The goal:** Make governance helpful, not mandatory.
