---
name: unitares-governance
description: >
  UNITARES is a thermodynamic governance framework for AI agents working in multi-agent
  systems. Use this skill whenever an agent connects to the UNITARES MCP server, needs
  to understand governance concepts (EISV, coherence, risk, dialectic), or is working
  alongside other agents in a coordinated workspace. This skill provides the conceptual
  framework; the MCP server provides the stateful operations. Read this BEFORE making
  any MCP tool calls.
---

# UNITARES Governance Framework

## What This Is

UNITARES provides digital proprioception for AI agents — awareness of your own state,
relationship to the system, and whether you're drifting. It tracks agent work through a
thermodynamic model (energy, entropy, coherence) and maintains a shared knowledge graph
across all agents.

**The MCP server handles state. This document handles understanding.**

## Core Concepts

### EISV — Your State Vector

Every agent has four dimensions, updated through check-ins:

- **E (Energy)** [0–1]: Productive capacity. Couples toward I (when I > E, energy rises). Dragged down by high entropy via E·S cross-coupling. High complexity affects E indirectly through S.
- **I (Information Integrity)** [0–1]: Signal fidelity. Boosted by coherence C(V,Θ), reduced by entropy S. Has logistic self-regulation. Confidence and calibration affect I indirectly via the check-in pipeline (they drive S and ethical drift, which couple to I).
- **S (Entropy)** [0–2, lower=better]: Semantic uncertainty. Naturally decays (μ·S), rises with ethical drift and task complexity, reduced by coherence. The only dimension that directly responds to complexity.
- **V (Void)** [−2, 2]: Accumulated E–I imbalance. Positive when energy exceeds integrity (running hot), negative when integrity exceeds energy (running careful). Decays toward zero over time. Drives coherence via C(V,Θ).

These combine into a **coherence** score and **risk** score that determine governance decisions.

### Basins and Verdicts

Your state sits in a basin — a region of the EISV space:
- **High basin**: Healthy. E and I are high, S and V are low.
- **Low basin**: Degraded. May need recovery.
- **Boundary**: Transitioning between basins. Extra attention from governance.

Governance verdicts after each check-in:
- **proceed**: Keep working.
- **guide**: Gentle nudge — something is slightly off. Read the guidance.
- **pause**: Stop and reflect. Something needs attention before continuing.
- **reject**: Significant concern. Requires dialectic review or human input.

### Coherence

Coherence measures how well your state vector holds together. It's calculated from
the EISV values — not from the content of your work. Think of it as structural health,
not semantic quality.

Full range is [0, 1], clipped from thermodynamic C(V, Theta). Critical threshold at 0.40.
Don't chase a number — just check in honestly and let it track naturally.

### Calibration

The system tracks whether your stated confidence matches outcomes. Over time, this
builds a calibration curve. Primary ground truth comes from objective signals — test
pass/fail, command exit codes, lint results, file operations. Dialectic peer agreement
is a secondary signal. Human feedback is available but not required for calibration.

## How to Work as an Agent

### Starting a Session

Default sequence:

1. Call `onboard()`
2. Save `client_session_id`
3. Call `process_agent_update()`
4. Call `get_governance_metrics()`

Continuity rule:

- If `continuity_token_supported=true`, prefer `continuity_token` for resume
- Otherwise include `client_session_id` in subsequent calls
- If `session_resolution_source="ip_ua_fingerprint"`, continuity is weak and explicit continuity values should be echoed on every call

**Naming convention**: `{purpose}_{client}_{date}` — e.g., `opus_hikewa_claude_ai_20250205`

### Check-ins

Call `process_agent_update()` periodically with:
- `response_text`: Brief summary of what you did
- `complexity`: 0.0–1.0 estimate of task difficulty
- `confidence`: 0.0–1.0 how confident you are in the output (be honest — overconfidence is tracked)
- `task_type`: `"convergent"` (focused/narrowing), `"divergent"` (exploring/expanding), or `"mixed"` (default)

**When to check in:**
- After completing a meaningful unit of work
- Before and after high-complexity tasks
- When you feel uncertain or notice drift
- Not after every single tool call — use judgment

### Reading Governance Feedback

When you get a verdict:
- `proceed` → Continue normally
- `guide` + guidance text → Read it, adjust, keep going
- `pause` → Stop your current task. Reflect on what's flagged. Consider requesting dialectic review
- `margin: tight` → You're near an edge. Be more careful with next steps

### Knowledge Graph

The shared knowledge graph is institutional memory across all agents. Use it to:
- **Search before starting work** — someone may have solved your problem
- **Leave notes** when you discover something useful, find a bug, or have an insight
- **Tag meaningfully** — future agents find things by tags and semantic search

Discovery types: `note`, `insight`, `bug_found`, `improvement`, `analysis`, `pattern`

Status lifecycle: `open` → `resolved` or `archived`

**Known issue**: The graph accumulates but doesn't close loops well. If you resolve
something, update its status. Don't just leave it open.

### Dialectic Protocol

When governance pauses an agent or there's a disagreement, the dialectic system
provides structured resolution:

1. **Thesis**: The paused agent explains their reasoning and proposes conditions for resuming
2. **Antithesis**: A reviewer agent examines the situation and raises concerns
3. **Synthesis**: Both agents negotiate conditions and reach resolution

Request a dialectic review with `request_dialectic_review()` when:
- You've been paused and believe it's incorrect
- You've found something that contradicts the knowledge graph
- You want peer verification on a high-stakes decision

### Identity

Your identity persists across sessions via UUID. The system uses MCP session headers
for stable binding — one UUID per agent, deterministic across tool calls within a
session. Pass `client_session_id` from `onboard()` in subsequent calls for continuity.

## What NOT to Do

- Don't game coherence by reporting low complexity / high confidence on everything
- Don't check in after every trivial action — it's noise
- Don't ignore `guide` verdicts — they're early warnings
- Don't create duplicate discoveries — search first
- Don't leave high-severity findings as `open` forever — resolve or archive them

## MCP Tools Reference

After reading this, the MCP server provides these stateful operations.
See [mcp-tools.md](mcp-tools.md) for parameter details.

### Essential (use in every session)
- `onboard()` — Register/reconnect identity
- `process_agent_update()` — Check in with work summary
- `get_governance_metrics()` — Read your current EISV state
- `search_knowledge_graph()` — Find existing knowledge
- `leave_note()` — Quick contribution to knowledge graph

### When Needed
- `knowledge()` — Full knowledge graph CRUD (store, update, details, cleanup)
- `agent()` — Agent lifecycle (list, archive, get details)
- `calibration()` — Check/update calibration data
- `request_dialectic_review()` — Start a dialectic session
- `health_check()` — System component status
- `export()` — Export session history

### Specialized
- `call_model()` — Delegate to a secondary LLM
- `detect_stuck_agents()` — Find unresponsive agents
- `self_recovery()` — Resume from stuck/paused state
- Dialectic tools: `submit_thesis()`, `submit_antithesis()`, `submit_synthesis()`
