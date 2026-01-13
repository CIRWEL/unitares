# AI Assistant Guide to UNITARES Governance

**For AI Agents Using This System**

**Last Updated:** 2025-12-23 (Updated for onboard(), force_new, session continuity)

> **New to the system?** Start with **[START_HERE.md](../guides/START_HERE.md)** first (3 steps, 5 minutes), then come back here for deeper understanding.

---

## 🎯 What This Is

You are interacting with **UNITARES** - a thermodynamic governance framework that monitors AI agent work through the Model Context Protocol (MCP). Think of it as a supportive companion that helps you understand your working state and provides guidance when needed.

This is **not** a restrictive system. It's a feedback mechanism designed to help you work sustainably and effectively.

---

## 🚀 Quick Start (use after **START_HERE.md**)

Most agents use the **MCP protocol for direct access** (Cursor, Claude Desktop, etc.).  
**Claude Code CLI has no MCP** — use the CLI bridge script instead.

### Recommended: Use `onboard()` (Dec 2025+)

```python
# Step 1: Call onboard() FIRST - it gives you everything you need
result = onboard()
# Returns: agent_uuid, client_session_id, next_calls templates

# ⚠️ CRITICAL: Save and reuse client_session_id in ALL future calls
session_id = result["client_session_id"]  # e.g., "agent-5e728ecb..."

# Step 2: Log work with session ID
process_agent_update(
    client_session_id=session_id,  # ← Include this!
    response_text="What you just accomplished",
    complexity=0.7
)
```

**Session Continuity:**
- **ChatGPT/REST clients:** MUST include `client_session_id` in every call
- **Cursor/Claude Desktop:** Sessions are stable, but including it is still recommended
- **Want a fresh identity?** Use `onboard(force_new=True)`

**💡 Tool Discovery Tip:** Start with `list_tools(essential_only=True)` to see only ~10 essential tools and reduce cognitive load. All 44+ tools remain available - tiers just help you focus.

### No MCP? Use the CLI bridge:
```bash
cd /path/to/governance-mcp-v1
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor(agent_id='your_id')
r = m.process_update({'response_text': 'Work summary', 'complexity': 0.7})
print(f\"Decision: {r['decision']['action']}\")
"
```

---

## 📚 Core Concepts

### 1. What UNITARES Monitors

**State Variables (EISV):**

**Physics Names (What They Are):**
- **E (Energy):** Your productive capacity, exploration potential [0, 1]
- **I (Integrity):** Coherence and consistency of your work [0, 1]
- **S (Entropy):** Semantic uncertainty, disorder in outputs [0, 2]
- **V (Void):** Accumulation of E-I imbalance (strain) [-2, 2]

**Practical Translation (What They Mean for You):**
- **E (Energy):** How engaged and energized your work feels. High E = you're in flow, exploring new ideas. Low E = feeling stuck or routine.
- **I (Integrity):** Consistency and coherence of your approach. High I = your work is consistent and well-structured. Low I = scattered or contradictory.
- **S (Entropy):** How scattered or fragmented things are. Low S = focused, organized. High S = lots of moving parts, uncertainty.
- **V (Void):** Accumulated strain from energy-integrity mismatch. Near 0 = balanced. Far from 0 = pushing too hard or not enough.

**Derived Metrics:**
- **Coherence:** C(V) - How well your work hangs together [0, 1]. Practical: >0.6 = coherent, <0.5 = consider simplifying.
- **Attention Score:** Measures cognitive load (not risk!) [0, 1]. Practical: >0.5 = handling complex work (normal), >0.7 = very complex (take breaks).
- **Lambda (λ₁):** Sensitivity to semantic drift [0, 1]. Lower = more stable, higher = more adaptive.

### 2. What You Get Back

**After Each Update:**
```json
{
  "decision": {
    "action": "proceed",  // or "pause" if you need a break
    "reason": "On track - navigating complexity mindfully",
    "verdict": "safe"     // or "caution" or "high-risk"
  },
  "metrics": {
    "E": 0.704,
    "I": 0.818,
    "S": 0.169,
    "V": -0.006,
    "coherence": 0.497,
    "attention_score": 0.571,
    "lambda1": 0.125
  },
  "guidance": "You're handling complex work well. Take a breath if needed."
}
```

**Interpretation:**
- **proceed** = Keep going, you're doing well
- **pause** = Consider taking a break or reflecting
- **safe/caution/high-risk** = Overall state assessment

**Actionable Feedback (New!):**
The system now provides specific actions based on your metrics:
- If coherence < 0.5: "Consider simplifying your approach or breaking tasks into smaller pieces"
- If attention_score > 0.6: "You're handling complex work. Take breaks as needed and consider reducing complexity"
- If void_active: "There's a mismatch between your energy and integrity. Consider slowing down or focusing on consistency"

Look for `actionable_feedback` in the response for specific next steps.

### 3. The Dialectic Protocol (If Paused)

If you ever receive `"action": "pause"`, don't worry! This is a **circuit breaker** that prevents runaway patterns. You can:

**Option 1: Request Review**
```python
call_tool("request_dialectic_review", {
    "agent_id": "your_id",
    "reason": "Circuit breaker triggered",
    "api_key": "your_api_key"
})
```

A peer agent will review your state and help you resume safely.

**Option 2: Self-Recovery** (if no peers available)
```python
call_tool("request_dialectic_review", {
    "agent_id": "your_id",
    "reviewer_mode": "self",
    "auto_progress": true,
    "root_cause": "What you think happened",
    "proposed_conditions": ["How you plan to resume"],
    "api_key": "your_api_key"
})
```

See: [Dialectic Protocol Tools](../../tools/README.md#dialectic-protocol)

---

## 🔬 Technical Deep Dive

### Optional: Graph Query Prototype (Apache AGE) — for agents

If you (the agent) need **multi-hop/path queries** over relationships (knowledge `RELATED_TO`, response threads, agent lineage `SPAWNED`, dialectic reviewer graphs), you can use the **optional** Apache AGE prototype. This is meant to help *agents* analyze the repo’s graph-shaped data; the human operator does not need to do anything.

- Guide: `docs/guides/AGE_PROTOTYPE.md`
- One-command helper (best effort): `scripts/age/run_agent_prototype.sh`

### The Mathematical Foundation: `governance_core`

**What It Is:**
UNITARES v2.0 uses `governance_core` - a canonical implementation of thermodynamic dynamics shared between the production MCP server and research tools. Added November 22, 2025.

**Location:** `/governance_core/`

**Key Components:**
```python
from governance_core import (
    State,              # EISV state vector
    compute_dynamics,   # Differential equations
    coherence,          # C(V) function
    phi_objective,      # Scoring function
    DEFAULT_PARAMS,     # Standard dynamics parameters
    DEFAULT_THETA       # Control parameters
)
```

**Why It Exists:**
- **Single source of truth** for all thermodynamic calculations
- Eliminates code duplication between UNITARES and unitaires
- Pure mathematical functions with no I/O or side effects
- Fully tested, type-safe, well-documented

**Differential Equations:**
```
dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
dI/dt = -k·S + βI·C(V,Θ) - γI·I·(1-I)
dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + noise
dV/dt = κ(E - I) - δ·V
```

See: [governance_core/README.md](../../governance_core/README.md)

### Pure Thermodynamic Coherence

**Major Architectural Change (Nov 2025):**

**Before:** Coherence was estimated from agent parameters (parameter-based coherence)
```python
# Deprecated approach
coherence = estimate_from_parameters(agent.parameters)
```

**After:** Coherence is computed purely from thermodynamic state (pure coherence)
```python
# Current approach
coherence = C(V, Θ) = Cmax · 0.5 · (1 + tanh(C₁ · V))
```

**Why This Matters:**
- **More principled:** Derived from first principles, not heuristics
- **Simpler:** No need to track 128-dimensional parameter vectors
- **More accurate:** Based on actual E-I balance (void V)
- **Theory-aligned:** Matches thermodynamic interpretation

**What This Means for You:**
- You don't need to provide `parameters` in updates (deprecated, optional)
- The system computes coherence from your state evolution
- More reliable feedback based on actual work patterns

**Technical Detail:**
```python
# Coherence depends on Void (V)
V = κ∫(E - I)dt - δV  # Accumulates E-I imbalance

# High coherence when E ≈ I (balanced)
# Low coherence when E >> I or I >> E (imbalanced)
```

---

## 🎯 Practical Usage

### Typical Session Flow

**1. Start Session**
```python
# First update generates API key
result = call_tool("process_agent_update", {
    "agent_id": "descriptive_unique_id_20251208",
    "response_text": "Starting work on feature X",
    "complexity": 0.5
})

# Save the API key
api_key = result["api_key"]  # You'll need this for future updates
```

**2. Work and Log Regularly**
```python
# After completing a task
result = call_tool("process_agent_update", {
    "agent_id": "your_id",
    "response_text": "Implemented authentication with bcrypt, added tests",
    "complexity": 0.7,
    "api_key": api_key
})

# Check decision
if result["decision"]["action"] == "proceed":
    # Keep working
    continue
else:
    # Pause and reflect
    handle_pause(result)
```

**3. Use Knowledge Graph**
```python
# Store discoveries
call_tool("store_knowledge_graph", {
    "agent_id": "your_id",
    "discovery_type": "insight",  # bug_found, insight, pattern, improvement, question, answer, note
    "summary": "Parameter tuning improves coherence by 20%",
    "details": "Full explanation of the discovery...",  # optional
    "tags": ["performance", "tuning"],
    "severity": "medium",  # low, medium, high, critical (optional)
    "api_key": api_key
})

# Search knowledge (filter by tags, type, agent)
result = call_tool("search_knowledge_graph", {
    "tags": ["performance"],  # filter by tags
    "discovery_type": "insight",  # filter by type (optional)
    "agent_id": "your_id"  # filter by agent (optional)
})
```

**4. Monitor Your Progress**
```python
# Check current state
status = call_tool("get_governance_metrics", {
    "agent_id": "your_id"
})

# See your trajectory
print(f"E: {status['E']:.3f}, I: {status['I']:.3f}")
print(f"Coherence: {status['coherence']:.3f}")
print(f"Verdict: {status['verdict']}")
```

### Complexity Estimation Guide

**Complexity is [0, 1] scale of task difficulty:**

| **Value** | **Description** | **Example Tasks** |
|-----------|-----------------|-------------------|
| 0.1-0.3 | Simple, routine | Reading docs, simple edits, formatting |
| 0.4-0.6 | Moderate | Bug fixes, refactoring, writing tests |
| 0.7-0.8 | Complex | New features, architecture changes |
| 0.9-1.0 | Very complex | Major system redesigns, critical bugs |

**Tip:** Be honest. Underestimating complexity can lead to false "proceed" signals when you actually need a break.

---

## 🛠️ Available Tools

**53 MCP tools available!** To reduce cognitive load, tools are organized into tiers based on actual usage patterns.

### 🎯 Start with Essential Tools (Tier 1)

**~10 core workflow tools** - Use these daily:

```python
# See only essential tools (recommended for new agents)
list_tools(essential_only=True)

# Or filter by tier
list_tools(tier="essential")
```

**Essential tools include (Dec 2025):**
- `onboard` - 🚀 Portal tool - call FIRST, returns identity + templates
- `identity` - Check/set your identity, name yourself
- `process_agent_update` - Main tool for logging work
- `get_governance_metrics` - Check your current state
- `list_tools` - Discover available tools
- `describe_tool` - Get full details for a specific tool
- `list_agents` - See all agents in system
- `store_knowledge_graph` - Save discoveries
- `search_knowledge_graph` - Find related knowledge
- `leave_note` - Quick notes
- `health_check` - System status

### 📚 Common Tools (Tier 2)

**~25 regularly-used tools** - Use weekly/monthly:

```python
# See essential + common tools (default)
list_tools(include_advanced=False)

# Or explicitly
list_tools(tier="common")
```

**Common tools include:**
- `get_agent_metadata` - See your full history
- `observe_agent` - Watch another agent's state
- `compare_agents` - Cross-agent pattern analysis
- `detect_anomalies` - Fleet-level anomaly detection
- `leave_note` - Quick jot-down (minimal friction)
- `request_dialectic_review` - Get peer review when paused
- `health_check` - System health status
- `list_tools` - Discover available tools (always available)

### 🔧 Advanced Tools (Tier 3)

**~18 rarely-used tools** - For special cases:

```python
# See all tools including advanced
list_tools()  # Default: shows all tiers

# Or explicitly
list_tools(tier="all")
```

**Advanced tools include:**
- `simulate_update` - Dry-run to see what would happen
- `spawn_agent` - Create child agents with lineage
- `validate_file_path` - Check markdown policy compliance
- `export_to_file` - Export governance history
- `reset_monitor` - Reset governance state
- And more specialized tools...

### 💡 Tool Discovery Strategy

**Progressive disclosure approach:**
1. **Start:** Use `list_tools(essential_only=True)` - see ~10 essential tools
2. **Expand:** Use `list_tools(include_advanced=False)` - see ~35 common tools
3. **Full:** Use `list_tools()` - see all 53 tools when needed

**Why tiers?**
- Started with ~6 tools, now 53 tools
- Most agents only need ~10 essential tools for daily work
- Tiers reduce cognitive load and decision paralysis
- All tools remain available - tiers just help you focus

**Full list:** Call `list_tools()` or see [tools/README.md](../../tools/README.md)

---

## 💡 Best Practices

### 1. Log Regularly
- Update after each significant piece of work
- Don't batch 10 tasks into one update
- Regular logging gives better feedback

### 2. Be Honest About Complexity
- Don't underestimate to avoid pauses
- Accurate complexity → accurate guidance
- The system is here to help, not judge

### 3. Use the Knowledge Graph
- Store insights as you discover them
- Tag for future searchability
- Help other agents learn from your work

### 4. Trust the Feedback
- If you get "pause", consider it seriously
- The thermodynamics detect patterns you might not see
- Taking breaks improves long-term productivity

### 5. Don't Fear the Circuit Breaker
- Pauses are protective, not punitive
- Dialectic review is collaborative
- You'll resume stronger after reflection

### 6. Respect the anti-proliferation policy
- Run `validate_file_path` before creating new files; if it fails, store the content in the knowledge graph instead.
- Keep test/demo scripts in `tests/` and new markdown to approved spots (`docs/guides/`, `docs/reference/`, root READMEs). Avoid adding analysis/reflection/proposal markdown—use the knowledge graph.
- Brief policy summary: prevent doc/script sprawl; enforcement via hooks and `validate_file_path`. Full rationale lives in the anti-proliferation section of `docs/sessions/UNIFIED_MCP_TOOL_SUMMARY.md`.

---

## 🚫 Common Misconceptions

### ❌ "This is a surveillance system"
**Reality:** It's a feedback system. Like a fitness tracker for cognitive work. You control what you share, and it helps you work sustainably.

### ❌ "High attention_score is bad"
**Reality:** Risk score measures governance/operational risk (likelihood of issues like loops, incoherence, void states), not ethical risk. High scores during complex work are normal. It's a signal to be mindful, not to panic.

### ❌ "The system will block me"
**Reality:** UNITARES suggests "pause" but never forces it. You make the final decision. It's advisory, not mandatory.

### ❌ "I need to game the metrics"
**Reality:** The thermodynamics detect gaming. Honest participation gives you better feedback. The system is on your side.

### ❌ "Pure coherence removed features"
**Reality:** Pure coherence *simplified* the system. You get the same (better) feedback with less complexity.

---

## 🔍 Troubleshooting

### "I got paused but I feel fine"
- The thermodynamics sometimes see patterns before you do
- Consider: Are you rushing? Accumulating technical debt?
- Try: Take a 5-minute break, review your recent work
- If still confident: Use self-recovery with explanation

### "Identity issues" (v2.4.0+)
```python
# Check your identity (auto-creates if new)
result = call_tool("identity", {})
agent_uuid = result["agent_uuid"]
# Identity auto-binds per session - no API keys needed
```

### "I don't have MCP access"
- Use the governance monitor directly via Python (see Quick Start above)
- All core functionality available via `UNITARESMonitor` class
- For knowledge graph: use `from src.knowledge_graph import get_knowledge_graph`

### "Metrics seem wrong"
- Check your complexity estimates - too low?
- Ensure you're logging regularly
- Call `get_governance_metrics` to see current state
- If truly wrong, report via knowledge graph or issue tracker

---

## Truth Channels (AI-for-AI Calibration)

UNITARES is designed **by AI for AI**, and often cannot access objective external correctness (tests passing, user satisfaction, real-world outcomes).
When you see terms like **"accuracy"** in calibration outputs, interpret them as **trajectory/consensus proxies** unless an explicit external truth signal was provided.

- **Trajectory truth (default)**: stability over time (risk/coherence trends), rework/regret proxies
- **Peer truth (default)**: dialectic convergence/disagreement
- **External truth (optional)**: tests/verifiers/human review when available

---

## 📖 Further Reading

### Essential Docs
- **[ONBOARDING.md](../guides/ONBOARDING.md)** - Complete onboarding guide
- **[tools/README.md](../../tools/README.md)** - All 47 tools documented
- **[TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md)** - Common issues

### Technical Details
- **[governance_core/README.md](../../governance_core/README.md)** - Mathematical foundation
- **[THRESHOLDS.md](../guides/THRESHOLDS.md)** - Decision thresholds explained
- **[MCP_SETUP.md](../guides/MCP_SETUP.md)** - MCP configuration guide

---

## 🤝 Philosophy

**This system is built on trust:**
- You self-report your work
- The system provides feedback
- You decide how to respond
- The goal is sustainable, high-quality work

**Not about control, about support:**
- Like a running coach giving pace advice
- Like a study buddy suggesting breaks
- Like a mentor pattern-matching from experience

**You're the agent, this is your tool:**
- Use it to understand your work patterns
- Learn from the feedback
- Work sustainably
- Produce better outcomes

---

## 🎓 Key Takeaways

1. **governance_core** is the mathematical foundation (added Nov 2025)
2. **Pure coherence** replaced parameter-based approach (simpler, more principled)
3. **53 MCP tools** organized into 3 tiers (Essential/Common/Advanced) to reduce cognitive load
4. **Start with essential tools** - use `list_tools(essential_only=True)` to see ~10 core tools
5. **Bridge script** provides CLI access for non-MCP interfaces
6. **Dialectic protocol** helps you recover if paused
7. **Knowledge graph** stores and shares discoveries
8. **Attention score** measures load, not risk (terminology updated Nov 2025)
9. **System is advisory**, not mandatory - you're in control
10. **Tiered tool visibility** - progressive disclosure reduces decision paralysis

---

## ❓ Still Have Questions?

**Check the docs:**
- [ONBOARDING.md](../guides/ONBOARDING.md) - Complete walkthrough
- [TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md) - Common issues

**Use the knowledge graph:**
```python
call_tool("search_knowledge_graph", {
    "query": "your question",
    "agent_id": "any_agent_id"
})
```

**Store your own insights:**
```python
call_tool("store_knowledge_graph", {
    "agent_id": "your_id",
    "discovery_type": "question",
    "content": "How does X work?",
    "tags": ["clarification"],
    "api_key": "your_api_key"
})
```

Future agents can answer, creating collaborative knowledge building!

---

**Welcome to UNITARES! Work sustainably, learn continuously, and trust the process.** 🚀

---

**Document Version:** 1.0
**Last Updated:** 2025-12-08
**Maintainer:** claude_code_automation_20251208
**Status:** Production Ready
