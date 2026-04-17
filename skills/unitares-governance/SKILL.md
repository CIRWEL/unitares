---
name: unitares-governance
description: >
  Compatibility umbrella skill for the UNITARES governance framework. Use this
  as the entrypoint when you need the overall model and route into the split
  governance skills.
last_verified: "2026-04-14"
freshness_days: 14
source_files:
  - unitares/src/mcp_handlers/core.py
  - unitares/src/mcp_handlers/identity/handlers.py
  - unitares/skills/governance-lifecycle/SKILL.md
  - unitares/skills/governance-fundamentals/SKILL.md
  - unitares/skills/knowledge-graph/SKILL.md
---

# UNITARES Governance

This umbrella skill exists for backward compatibility and as a stable top-level
entrypoint into the UNITARES framework.

## Core Model

UNITARES evaluates agent state with the **EISV** model:

- `E`: effective energy / execution drive
- `I`: integrity / coherence of alignment
- `S`: entropy / disorder / instability
- `V`: valence (signed E-I imbalance)

Agents typically start with `onboard()` and continue with
`process_agent_update()` as their main check-in loop.

## Session Continuity

Use `onboard()` to register or reconnect identity. The returned
`client_session_id` should be echoed back on later calls when continuity tokens
are not available. This prevents attribution fragmentation across sessions.

Use `process_agent_update()` after meaningful work to record progress,
complexity, and confidence, then read the returned governance verdict.

## Knowledge Layer

The governance system is coupled to the **knowledge graph**. Agents should
search existing knowledge before duplicating work, and contribute discoveries,
questions, and answers as they learn.

## Split Skills

The old monolithic skill was split into focused skills:

- `skills/governance-lifecycle/SKILL.md` for onboarding, check-ins, and recovery
- `skills/governance-fundamentals/SKILL.md` for EISV, basins, coherence, and verdicts
- `skills/knowledge-graph/SKILL.md` for knowledge graph search and contribution
- `skills/dialectic-reasoning/SKILL.md` for thesis/antithesis/synthesis workflows
- `skills/discord-bridge/SKILL.md` for the Discord governance bridge

If you need the full mental model, start here. If you know the task shape,
prefer the focused skill directly.
