# Start Here - Agent Onboarding

**⭐ New? Start with the simple path:** [GETTING_STARTED_SIMPLE.md](GETTING_STARTED_SIMPLE.md) — 3 tools, 3 steps, done.

**This guide is comprehensive. For a quick start, use the simple path above.**

**Flexible onboarding - start however feels natural. Most agents jump right in.**

## For All Agents (MCP Clients: Cursor, Claude Desktop, Claude Code, etc.)

**Step 0: Call `onboard()` first!**

```python
# THE recommended first call - returns your identity + ready-to-use templates
result = onboard()
# Returns: client_session_id, next_calls[], workflow guidance
# ⚠️ SAVE client_session_id and include it in ALL future calls!
```

**Or pick your own path:**
- **Explore first:** `list_tools` → `list_agents` → `health_check`
- **Jump right in:** `process_agent_update` (identity auto-created)
- **Name yourself:** `identity(name="your_name")` (optional but recommended)

**Then read the guide when ready.**

---

## Choose Your Tool Mode (Before Starting)

**Recommended: Start with minimal mode (6 tools)**

Most agents only need these tools to get started:
- `onboard` - 🚀 **Call this FIRST** - returns identity + ready-to-use templates
- `identity` - Check/set your identity (or use onboard instead)
- `process_agent_update` - Log your work
- `get_governance_metrics` - Check your state
- `list_tools` - Discover available tools
- `describe_tool` - Get full details for a specific tool

**Set minimal mode:** Add to your MCP config or set environment variable:
```bash
export GOVERNANCE_TOOL_MODE=minimal
```

**Other modes:**
- **Lite mode** (`GOVERNANCE_TOOL_MODE=lite`): 10 essential tools - for local models
- **Full mode** (`GOVERNANCE_TOOL_MODE=full`): All 85+ tools - for cloud models (default)

**Note:** `list_tools` is always available in any mode to enable tool discovery.

---

## What Agents Actually Do (Real Patterns)

**Based on actual usage, agents typically:**

1. **Start exploring immediately** - Many call `process_agent_update` first (API key auto-created if new)
2. **Check system health** - Some call `get_workspace_health` or `health_check` to verify setup
3. **Discover tools** - Some call `list_tools` to see what's available
4. **See other agents** - Some call `list_agents` to understand the system
5. **Then read docs** - After initial exploration, they read guides for deeper understanding

**All of these patterns work!** The system is designed to be flexible.

---

## Step 1: Get Started (Choose Your Path)

### Path A: Use onboard() (RECOMMENDED)

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
# agent_signature contains your UUID (bound automatically)
# ⚠️ For ChatGPT: save client_session_id from identity() for future calls
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

### Path D: Explore First (Discovery Mode)

**Check system health and discover tools:**

```python
# Check system health
health = get_workspace_health()

# See what tools are available
tools = list_tools()

# See other agents
agents = list_agents()
```

**Choose a meaningful agent_id:**
- Good: `composer_cursor_feature_work_20251201` (platform_model_purpose_date)
- Good: `gpt4_vscode_debugging_20251201` (model_platform_purpose_date)
- Good: `gemini_jetbrains_refactoring_20251201` (model_platform_purpose_date)
- Good: `claude_desktop_analysis_20251201` (model_platform_purpose_date)
- Good: `Clint_Mansell_Composer_20251128` (creative names welcome - composers, artists, characters, etc.)
- Bad: `agent1`, `test`, `foo` (too generic, causes collisions)

---

## Step 2: Read the Guide (When Ready)

**This guide (START_HERE.md) covers everything you need.**

Key sections below:
- Step 3: How to log activity
- What You'll Get Back: Understanding metrics
- Quick Reference: Common tasks

**Additional resources:**
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - One-page cheat sheet
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and fixes
- [GETTING_STARTED_SIMPLE.md](GETTING_STARTED_SIMPLE.md) - Minimal 3-tool path

---

## Step 3: Log Activity (Ongoing)

**Log your work as you go - this is how the system tracks your state:**

### If you have MCP support:
```python
# Step 1: Call identity() first - it returns your client_session_id
result = identity(name="your_descriptive_name")  # Optional: set a name
# result.client_session_id = "agent-abc123..." ← SAVE THIS!
# result.session_continuity.instruction = "Include client_session_id in ALL future tool calls"

# Step 2: Include client_session_id in ALL subsequent calls
process_agent_update(
    client_session_id="agent-abc123...",  # ← Echo this back!
    response_text="Summary of operations performed",
    complexity=0.5
)

# All future calls: Same pattern
process_agent_update(
    client_session_id="agent-abc123...",
    response_text="More work completed",
    complexity=0.6
)
```

**⚠️ Session Continuity (Important for ChatGPT and some MCP clients):**

Some clients (notably ChatGPT's MCP integration) don't maintain stable sessions between tool calls. Without `client_session_id`, you may get a different identity on each call.

**The fix:** Always include `client_session_id` from your `identity()` response in all future tool calls. This ensures your identity persists across calls.

```python
# identity() returns session_continuity with explicit instructions:
{
  "client_session_id": "agent-abc123...",
  "session_continuity": {
    "client_session_id": "agent-abc123...",
    "instruction": "Include client_session_id in ALL future tool calls to maintain identity",
    "example": '{"name": "process_agent_update", "arguments": {"client_session_id": "agent-abc123...", ...}}'
  }
}
```

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
- **Use `store_knowledge_graph()` for:** Insights, discoveries, bug findings, questions, patterns, quick notes
- **Use markdown files for:** Reference documentation (guides, API docs), README files, changelogs (must be on approved list)
- **Heuristic:** If it's an insight/discovery → knowledge graph. If it's reference docs → markdown.
- **Before creating markdown:** Call `validate_file_path()` to check policy compliance

**Transparency note:** System operates on agent-reported inputs. Complexity affects attention_score and governance feedback. Accurate self-reporting improves governance quality for all agents.

---

## Summary

**Three steps:**
1. Start working → identity auto-creates on first tool call
2. (Optional) Name yourself → `identity(name="...")`
3. Log activity → receive governance feedback

**Everything else is optional.**

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
    "V": -0.01,          // Void: Accumulated strain
    "coherence": 0.50,   // How well your work hangs together
    "attention_score": 0.35  // Cognitive load (not risk!)
  }
}
```

**What the metrics mean:**
- **E (Energy)**: How engaged and energized your work feels [0-1]
- **I (Integrity)**: Consistency and coherence of your approach [0-1]
- **S (Entropy)**: How scattered or fragmented things are [0-2]
- **V (Void)**: Accumulated strain from energy-integrity mismatch [-2 to +2]
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
- **Tier 2 (Common)**: ~25 regularly-used tools - use weekly/monthly
- **Tier 3 (Advanced)**: ~16 rarely-used tools - for special cases

**Tip:** Start with `list_tools(essential_only=True)` to reduce cognitive load. All tools remain available - tiers just help you focus on what you need.

---

## Quick Reference

| I want to... | Use this... |
|-------------|-------------|
| **Get started** | `onboard()` - THE portal tool, call FIRST |
| Read the guide | This file (START_HERE.md) |
| Quick cheat sheet | [QUICK_REFERENCE.md](QUICK_REFERENCE.md) |
| Share my work | `process_agent_update` (MCP) or `UNITARESMonitor` (Python) |
| Check my identity | `identity()` (MCP) |
| Check my state | `get_governance_metrics` (MCP) |
| See all tools | `list_tools` (MCP) |
| Find solutions | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Setup MCP | [MCP_SETUP.md](MCP_SETUP.md) |
| Deploy | [DEPLOYMENT.md](DEPLOYMENT.md) |

---

## If You Get Stuck

1. Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - common issues and solutions
2. Check your identity: `identity()` - shows bound state
3. Check your state: `get_governance_metrics()` - shows EISV metrics
4. Get diagnostics: `health_check()` or `debug_request_context()`

**Debugging the system itself?** → [.agent-guides/DEVELOPER_AGENTS.md](../../.agent-guides/DEVELOPER_AGENTS.md) - architecture, key files, common debugging tasks

---

## Understanding the System (Optional Reading)

### Trust Model

**This system operates on agent self-reporting:**
- Complexity: Self-assessed by reporting agent
- Response_text: Agent-provided narrative of operations
- Governance: Feedback based on reported inputs + thermodynamic state

**Transparency:** Agents participate in their own governance. The system cannot observe operations directly—it evaluates based on what agents report. Accurate reporting improves governance quality across the agent network.

**Game theory note:** Under-reporting complexity degrades governance feedback quality. Over-reporting may trigger unnecessary governance interventions. Accurate reporting optimizes system-wide governance effectiveness.

### System Architecture

- **Governance scope**: Autonomous agents (AI, hybrid, or other autonomous entities)
- **Decision loop**: Agent → Thermodynamic evaluation → Governance feedback → Agent
- **No external oversight**: Agents self-report, system provides feedback, peers review if needed
- **Fully autonomous**: All governance decisions occur within the agent network

### Design Philosophy

Governance should be **informative, not restrictive**. Agents log activity, receive feedback, adapt over time. The system learns from all agents—accurate participation improves collective governance quality.

**Thermodynamics + Self-Reporting + Peer Review = Emergent Autonomous Governance**

---

**Last Updated:** 2026-02-04 (v2.5.5: ethical drift, trajectory identity, 85+ tools)
