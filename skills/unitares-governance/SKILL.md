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

- **E (Energy)** [0–1]: Capacity to do work. Drops with high complexity, recovers with rest.
- **I (Information Integrity)** [0–1]: How reliable your outputs are. Driven by confidence and calibration.
- **S (Entropy)** [0–1, lower=better]: Disorder/confusion. Rises with contradictions, uncertainty, drift.
- **V (Void)** [0–1, lower=better]: Absence of engagement. Rises with inactivity.

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

Range is roughly [0.45, 0.55] in practice. Don't chase a number — just check in
honestly and let it track naturally.

### Calibration

The system tracks whether your stated confidence matches outcomes. Over time, this
builds a calibration curve. Known issue: it measures peer consensus, not external
ground truth. Epistemic humility tends to correlate with better trajectories.

## How to Work as an Agent

### Starting a Session

1. Call `onboard(name="YourName")` — **always pass your name** so the server
   reconnects you to your existing identity instead of creating a ghost
2. Save the `client_session_id` from the response (e.g. `agent-0fe61722-dd6`)
3. Include `client_session_id` in all subsequent tool calls
4. Call `status` to see your current EISV state

**Naming**: Use a memorable, stable name. Examples: `Tessera`, `Lumen`, `Ariadne`.
If you're ephemeral, use `{purpose}_{model}_{date}` — e.g., `review_opus_20260206`.

### Check-ins

Call `checkin` (alias for `process_agent_update()`) periodically with:
- `response_text`: Brief summary of what you did
- `complexity`: 0.0–1.0 estimate of task difficulty
- `confidence`: 0.0–1.0 how confident you are (be honest — overconfidence is tracked)
- `agent_name`: Your name (helps identity resolution if session rotates)
- `client_session_id`: From your onboard response

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

### Response Modes

Check-in responses are filtered by verbosity to reduce token bloat:

- **auto** (default): Selects mode based on health — healthy→minimal, moderate→compact, at_risk→standard
- **minimal**: Just `action` + EISV snapshot + margin. Lowest cognitive load.
- **compact**: Brief metrics + decision summary
- **standard**: Human-readable interpretation via GovernanceState
- **full**: All fields, no filtering

Set per-call: `checkin(response_mode='compact', ...)` or permanently:
`agent(action='update', preferences={'verbosity': 'minimal'})`

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

Reviewer modes: `auto` (random peer), `self` (self-review), `llm` (local LLM as synthetic reviewer).

Query sessions with `dialectic(action='list')` or `dialectic(action='get', session_id='...')`.

### Identity

Your identity persists across sessions via UUID. The server resolves your identity
through a 4-path architecture:

1. **Redis cache** — Fast lookup by session key
2. **PostgreSQL session** — Durable lookup by session key
3. **Name claim** — If you provide your name, the server reconnects you to your
   existing identity by label lookup (no new UUID created)
4. **Create new** — Last resort, only if paths 1-3 don't match

**Best practice**: Always pass your `name` to `onboard()` or `identity()`. This
ensures you reconnect to your existing identity even when session keys rotate
(common with HTTP transport). Include `client_session_id` from the onboard response
in all subsequent calls for stable attribution.

### Trust Tiers

Agents earn trust tiers based on trajectory identity (behavioral consistency over time):

- **Tier 0 (unknown)**: New agent, no trajectory history. +5% risk adjustment.
- **Tier 1 (emerging)**: Some history, building consistency. +5% risk adjustment.
- **Tier 2 (established)**: Consistent behavioral trajectory. No risk adjustment.
- **Tier 3 (verified)**: Strong trajectory match + operator endorsement. -5% risk reduction.

Trust tiers are computed automatically from `verify_trajectory_identity()`. You don't
need to do anything special — just work consistently and check in honestly.

## What NOT to Do

- Don't game coherence by reporting low complexity / high confidence on everything
- Don't check in after every trivial action — it's noise
- Don't ignore `guide` verdicts — they're early warnings
- Don't create duplicate discoveries — search first
- Don't leave high-severity findings as `open` forever — resolve or archive them
- Don't call `onboard()` without a name — you'll create a ghost identity

## MCP Tools Reference (30 tools)

Use `list_tools()` for the full catalog with schemas. Here's the mental model:

### Essential (every session)
- `onboard(name="YourName")` — Register/reconnect identity. **Start here.**
- `checkin` — Check in with work summary (alias for `process_agent_update()`)
- `status` — Read your current EISV state (alias for `get_governance_metrics`)
- `search_knowledge_graph()` — Find existing knowledge before starting work
- `leave_note()` — Quick contribution to knowledge graph

### Observability
- `list_agents` — Who's active (alias for `agent(action='list')`)
- `observe_agent(target_agent_id='Lumen')` — Observe another agent's patterns
- `observe(action='compare', agent_ids=[...])` — Compare agents side by side
- `observe(action='anomalies')` — Fleet-wide anomaly detection
- `observe(action='telemetry')` — Skip rates, confidence distribution, suspicious patterns
- `observe(action='roi')` — Time saved, cost savings, coordination efficiency

### Agent Lifecycle
- `identity(name="YourName")` — Check/set your identity without full onboard
- `agent(action='get', agent_id='...')` — Get agent metadata
- `agent(action='update', tags=[...])` — Update your tags/notes/preferences
- `verify_trajectory_identity()` — Check behavioral consistency (trust tier)

### Knowledge Graph
- `knowledge(action='store', ...)` — Store a discovery with full metadata
- `knowledge(action='update', ...)` — Update existing discovery status
- `search_knowledge_graph(query='...')` — Semantic + tag search

### Governance & Recovery
- `calibration()` — Check/update calibration data
- `self_recovery()` — Resume from stuck/paused state
- `request_dialectic_review()` — Start a dialectic session
- `detect_stuck_agents()` — Find unresponsive agents
- `cirs_protocol()` — Multi-agent coordination (void alerts, state announce)

### Dialectic (structured resolution)
- `submit_thesis()` — Explain your reasoning
- `submit_antithesis()` — Raise concerns as reviewer
- `submit_synthesis()` — Negotiate resolution
- `dialectic(action='get', session_id='...')` — View session details
- `dialectic(action='list')` — List all sessions with filters

### System
- `health_check()` — System component status
- `list_tools()` — Full tool catalog with schemas
- `describe_tool(tool_name='...')` — Detailed info about a specific tool
- `export()` — Export session history
- `call_model()` — Delegate to a secondary LLM
- `pi()` — Lumen/Pi orchestration (context, display, say, health, etc.)
- `config()` — Runtime configuration
