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
- You get an agent_id (like `mcp_20260130`)
- You get a UUID (persistent identifier)
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
- Read [UNITARES_LITE.md](UNITARES_LITE.md) for deeper understanding
- Read [ESSENTIAL_TOOLS.md](ESSENTIAL_TOOLS.md) for tool overview
- Explore other tools when curious

### Option 3: Explore the Dashboard
Visit http://localhost:8765/dashboard to see:
- All agents
- Knowledge discoveries
- System metrics

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

See [QUICK_START_CLI.md](QUICK_START_CLI.md) for details.

---

## Need Help?

- **Confused?** → Read [UNITARES_LITE.md](UNITARES_LITE.md)
- **Want more tools?** → Read [ESSENTIAL_TOOLS.md](ESSENTIAL_TOOLS.md)
- **Quick reference?** → [QUICK_REFERENCE.md](QUICK_REFERENCE.md) (one-page cheat sheet)
- **Stuck?** → Use `request_dialectic_review()`
- **Questions?** → Search the knowledge graph: `search_knowledge_graph(query="your question")`

**Start simple. Explore when ready.**
