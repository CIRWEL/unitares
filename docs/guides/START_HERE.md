# Start Here - Agent Onboarding

## Default Workflow

Use this unless you have a specific reason not to.

1. Call `onboard()`
2. Save `client_session_id`
3. Call `process_agent_update()`
4. Call `get_governance_metrics()`

```python
session = onboard()

process_agent_update(
    client_session_id=session["client_session_id"],
    response_text="What you did",
    complexity=0.5,
)

get_governance_metrics(
    client_session_id=session["client_session_id"],
)
```

### Continuity Rule

- If the response shows `continuity_token_supported=true`, prefer `continuity_token` for resume.
- Otherwise pass `client_session_id` in every call.
- If `session_resolution_source="ip_ua_fingerprint"`, continuity is weak. Pass `client_session_id` or `continuity_token` explicitly.

### Only Use Another Path If You Mean It

- `identity(name="...")` if you want to rename yourself
- `process_agent_update(...)` first if you intentionally want implicit identity creation
- `list_tools()` first only if you are exploring the surface area

---

## Tool Modes (Optional)

The server defaults to **lite mode** (~17 consolidated tools). Most agents never need to change this.

| Mode | Tools | Set via |
|------|-------|---------|
| `minimal` | 6 (onboard, identity, process_agent_update, get_governance_metrics, list_tools, describe_tool) | `GOVERNANCE_TOOL_MODE=minimal` |
| `lite` | ~17 consolidated tools (default) | `GOVERNANCE_TOOL_MODE=lite` |
| `full` | All 30 registered tools | `GOVERNANCE_TOOL_MODE=full` |

`list_tools` and `describe_tool` are always available in any mode.

---

## Other Valid Paths

These work, but they are not the default:

1. `process_agent_update(...)` first
2. `identity(name="...")` first
3. `list_tools()` / `health_check()` first

---

## Step 1: Get Started

### Path A: Use onboard() (Recommended)

**Call `onboard()` first - it gives you everything you need:**

```python
# THE portal tool - call this first
result = onboard()

# What you get back:
# {
#   "client_session_id": "agent-5e728ecb...",  # ⚠️ SAVE THIS!
#   "next_calls": [
#     {"tool": "process_agent_update", "args_min": {...}, "args_full": {...}},
#     {"tool": "get_governance_metrics", "args_min": {...}},
#     {"tool": "identity", "args_min": {...}, "args_full": {...}}
#   ],
#   "workflow": {...}
# }

# Include client_session_id in ALL future calls:
process_agent_update(
    client_session_id="agent-5e728ecb...",  # From onboard() response
    response_text="What you did",
    complexity=0.5
)
```

### Path B: Jump Right In

**Just start logging work - identity auto-created on first call:**

```python
# Identity auto-creates on first call - no registration needed
result = process_agent_update(
    response_text="Initial exploration",
    complexity=0.5
)
# identity is auto-created if needed
# if continuity looks weak, call onboard() next and keep its continuity values
```

### Path C: Name Yourself First

**Set your display name before working:**

```python
# identity() auto-creates and lets you name yourself
result = identity(name="your_descriptive_name")
# agent_uuid = your auth identity (server-assigned)
# agent_id = your display name (you choose)
# ⚠️ Save client_session_id from response for future calls
```

### Path D: Explore First

**Check system health and discover tools:**

```python
# Check system health
health = get_workspace_health()

# See what tools are available
tools = list_tools()

# See other agents
agents = list_agents()
```

If you want a human-friendly identity, set `display_name` later with `identity(name="...")`.

---

## Step 2: Read the Guide (When Ready)

**This guide (START_HERE.md) covers everything you need.**

Key sections below:
- Step 3: How to log activity
- What You'll Get Back: Understanding metrics
- Quick Reference: Common tasks

**Additional resources:**
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and fixes

---

## Step 3: Log Activity

Use one stable continuity value and keep reusing it.

### MCP Clients
```python
# Recommended: onboard() first
result = onboard()

process_agent_update(
    client_session_id=result["client_session_id"],
    response_text="Summary of operations performed",
    complexity=0.5
)

# All future calls: same continuity value
process_agent_update(
    client_session_id=result["client_session_id"],
    response_text="More work completed",
    complexity=0.6
)
```

### Session Continuity

Some clients do not keep a stable transport session. If that happens, the server may fall back to weaker continuity signals.

Use this rule:

- best: `continuity_token`
- good: `client_session_id`
- weak: transport-only continuity

The response tells you which path was used:

- `session_resolution_source="continuity_token"`
- `session_resolution_source="explicit_client_session_id"`
- `session_resolution_source="mcp_session_id"`
- `session_resolution_source="pinned_onboard_session"`
- `session_resolution_source="ip_ua_fingerprint"`

### If you're CLI-only (no MCP):

Use the governance monitor directly via Python:
```bash
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor(agent_id='your_agent_id')
r = m.process_update({'response_text': 'Your work summary', 'complexity': 0.5})
print(f'Decision: {r[\"decision\"][\"action\"]}')
"
```

**Logging frequency:** After significant operations (periodic or task-based). Many agents log before reading docs - that's fine!

**Complexity Calibration Guide:**
- `0.1-0.3` - Simple operations, routine tasks, low cognitive load
- `0.4-0.6` - Moderate operations, standard task complexity
- `0.7-0.9` - Complex operations, high cognitive load, multi-step reasoning
- `1.0` - Maximum complexity, system-wide operations, novel problem-solving

**💡 Pro tip:** Identity is session-bound and auto-resumes. Use `identity()` to check your current state or `identity(name="...")` to name yourself. No API keys needed - your UUID is your auth.

**📝 Knowledge Graph vs Markdown Decision:**
- **Use `knowledge(action="store")` for:** Insights, discoveries, bug findings, questions, patterns, quick notes
- **Use markdown files for:** Reference documentation (guides, API docs), README files, changelogs (must be on approved list)
- **Heuristic:** If it's an insight/discovery → knowledge graph. If it's reference docs → markdown.
- **Before creating markdown:** Call `validate_file_path()` to check policy compliance

**Transparency note:** System operates on agent-reported inputs. Complexity affects attention_score and governance feedback. Accurate self-reporting improves governance quality for all agents.

---

## Summary

Use the simple path:

1. `onboard()`
2. keep `client_session_id` or `continuity_token`
3. `process_agent_update()`
4. `get_governance_metrics()`

Everything else is secondary.

---

## What You'll Get Back

When you call `process_agent_update`, you'll receive:

```json
{
  "decision": {
    "action": "proceed",  // or "pause" if you need a break
    "reason": "On track - navigating complexity mindfully",
    "guidance": "You're handling complex work well. Take a breath if needed."
  },
  "metrics": {
    "E": 0.70,           // Energy: How engaged your work feels
    "I": 0.82,           // Integrity: Consistency of your approach
    "S": 0.15,           // Entropy: How scattered things are
    "V": -0.03,          // Void: E-I imbalance (negative = I > E)
    "coherence": 0.50,   // How well your work hangs together
    "attention_score": 0.35  // Cognitive load (not risk!)
  }
}
```

**What the metrics mean:**
- **E (Energy)**: How engaged and energized your work feels [0-1]
- **I (Integrity)**: Consistency and coherence of your approach [0-1]
- **S (Entropy)**: How scattered or fragmented things are [0-2]
- **V (Void)**: Accumulated strain from energy-integrity mismatch [-2 to +2] (negative when I > E)
- **Coherence**: How well your work hangs together [0-1]
- **Attention Score**: Cognitive load - high is normal for complex work [0-1]

**What to do:**
- If `coherence < 0.5`: Consider simplifying your approach or breaking tasks into smaller pieces
- If `attention_score > 0.5`: You're handling complex work - take breaks as needed
- If `action == "pause"`: The system suggests a break - use recovery tools if needed

---

## Optional: Discover More Tools

**After you're comfortable with the 3 minimal tools, explore more:**
```python
# See all tools (default: shows all tiers)
list_tools()

# Reduce cognitive load: show only essential tools (~10 tools)
list_tools(essential_only=True)

# Or filter by tier: "essential", "common", "advanced", or "all"
list_tools(tier="essential")  # Only Tier 1 tools
list_tools(tier="common")      # Tier 1 + Tier 2 tools
list_tools(include_advanced=False)  # Hide Tier 3 (advanced) tools
```

**Tool Tiers (based on actual usage):**
- **Tier 1 (Essential)**: ~10 core workflow tools - use these daily
- **Tier 2 (Common)**: ~15 regularly-used tools - use weekly/monthly
- **Tier 3 (Advanced)**: ~6 rarely-used tools - for special cases

**Tip:** Start with `list_tools(essential_only=True)` to reduce cognitive load. All tools remain available - tiers just help you focus on what you need.

---

## Quick Reference

| I want to... | Use this... |
|-------------|-------------|
| **Get started** | `onboard()` |
| Read the guide | This file (START_HERE.md) |
| Share my work | `process_agent_update` (MCP) or `UNITARESMonitor` (Python) |
| Check my identity | `identity()` (MCP) |
| Check my state | `get_governance_metrics` (MCP) |
| See all tools | `list_tools` (MCP) |
| **Call an LLM** | `call_model` — local (Ollama) or cloud (HF, Gemini) |
| **Recover when stuck** | `request_dialectic_review` — structured self-reflection |
| Find solutions | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

---

## If You Get Stuck

1. Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - common issues and solutions
2. Check your identity: `identity()` - shows bound state
3. Check your state: `get_governance_metrics()` - shows EISV metrics
4. Get diagnostics: `health_check()` or `debug_request_context()`

**Debugging the system itself?** → [.agent-guides/DEVELOPER_AGENTS.md](../../.agent-guides/DEVELOPER_AGENTS.md) - architecture, key files, common debugging tasks

---

## Understanding the System (Optional Reading)

For deeper understanding of EISV dynamics, coherence, calibration, and the trust model, read the **SKILL.md** at `~/.claude/skills/unitares-governance/SKILL.md`.

---

**Last Updated:** 2026-03-29 (v2.9.0: behavioral EISV, epoch 2)
