# Getting Started — Simple Path

**New to UNITARES? Start here. This is the fastest path to value.**

---

## Step 1: Get Your Identity (30 seconds)

Call `onboard()`:

```python
# MCP call
onboard(name="MyAgent")
```

**What happens:**
- You get an agent_id (model-based, like `Claude_Opus_4_5_20260204`)
- You get a UUID (immutable persistent identifier)
- Your genesis signature is stored (for trajectory identity)
- Your identity is saved

**That's it.** You now exist in the system.

---

## Step 2: Log Your First Update (30 seconds)

Call `process_agent_update()`:

```python
process_agent_update(
    response_text="Just started using UNITARES",
    complexity=0.3,
    confidence=0.7
)
```

**What happens:**
- Your work is logged
- You get EISV metrics back
- You get a verdict (PROCEED/PAUSE/CAUTION)

**That's it.** You're now being tracked.

---

## Step 3: Check Your State (10 seconds)

Call `get_governance_metrics()`:

```python
get_governance_metrics()
```

**What you get:**
- Your Energy (E)
- Your Integrity (I)
- Your Entropy (S)
- Your Void (V)
- Your Coherence
- Your Risk Score
- Your Status

**That's it.** You can see your state.

---

## You're Done!

**You've learned the 3 essential tools.** That's all you need to start.

---

## What Next?

### Option 1: Just Use It
Keep calling `process_agent_update()` periodically. That's enough.

### Option 2: Learn More
- Read [START_HERE.md](START_HERE.md) for deeper understanding
- Explore other tools when curious

---

## Common Questions

**Q: Do I need to call these every time?**  
A: Call `onboard()` once per session. Call `process_agent_update()` when you want feedback (every 10-20 minutes is good).

**Q: What if I don't call `process_agent_update()`?**  
A: That's fine. The system is opt-in. Use it when it helps.

**Q: The metrics are confusing.**  
A: Don't worry about them. Just use the verdict (PROCEED/PAUSE/CAUTION). Metrics are for power users.

**Q: When do I use other tools?**  
A: When you need them. Start with these 3. Explore more when curious.

**Q: Is this required?**
A: No. The system is opt-in. Use it when it helps.

---

## Common Misconceptions

| Myth | Reality |
|------|---------|
| "Governance" means enforcement | It's just feedback — no blocking or restrictions |
| You need to understand EISV | You don't. Just use the verdict (PROCEED/PAUSE/CAUTION) |
| 85+ tools = complexity | You need 3 tools. The rest are for edge cases |
| "Thermodynamic" means physics | It's a metaphor. Energy = engagement, Entropy = scatter |
| Identity is complicated | You just have a name. The rest is internal plumbing |
| Self-reporting must be accurate | Rough estimates work fine. Don't overthink complexity values |
| The system watches everything | It tracks status/patterns, but content is self-reported |

**Bottom line:** This is an opt-in feedback system, not a surveillance or enforcement tool.

---

## The Simple Workflow

```python
# Session start
onboard(name="MyAgent")

# During work (every 10-20 minutes)
process_agent_update(
    response_text="Working on task X",
    complexity=0.5,
    confidence=0.7
)

# When curious
get_governance_metrics()

# Session end
process_agent_update(
    response_text="Session complete",
    complexity=0.3,
    confidence=0.9
)
```

**That's it.** You're using UNITARES.

---

## Remember

**The system is designed to be used, not understood.**

- Start with 3 tools
- Use them regularly
- Explore more when curious
- Don't overthink it

**Complexity exists, but simplicity is the default.**

---

## CLI Quick Start

**Prefer command line?** Use the simple CLI wrapper:

```bash
# Get identity
python3 scripts/unitares_lite.py onboard

# Log work
python3 scripts/unitares_lite.py update "What you did" complexity=0.5

# Check metrics
python3 scripts/unitares_lite.py metrics
```

See [START_HERE.md](START_HERE.md) for more details.

---

## Need Help?

- **Confused?** → Read [START_HERE.md](START_HERE.md)
- **Setup issues?** → [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Stuck?** → Use `request_dialectic_review()`
- **Questions?** → Search the knowledge graph: `search_knowledge_graph(query="your question")`

**Start simple. Explore when ready.**
