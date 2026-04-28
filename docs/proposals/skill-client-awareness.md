---
status: ABANDONED — per council 2026-04-25
authored: 2026-04-25
closed: 2026-04-25
author_session: agent-46187444-bd2 (Claude Opus 4.7 / claude_code)
review_target: parallel dialectic-knowledge-architect + feature-dev:code-reviewer subagents
unblocks: nothing — this is a structural addition, not a fix
related: docs/ontology/s15-server-side-skills.md (canonical skill bundle), CLAUDE.md (per-client bootstrap)
abandonment_basis: |
  Proposal §5 named the abandonment condition: "if §3.4 [what failure mode does this
  prevent] doesn't surface a concrete answer during council review, the right outcome
  is abandonment." Both reviewers, working independently, failed to surface one. The
  S15 §13 empirical update (2026-04-25) had already closed the only documented
  motivating incident at the §6 tool_descriptions.json cure path, so the residual
  surface this skill would have served is undefined. Carve-out: if a future incident
  surfaces a cross-harness reasoning failure that §6 cannot address, take the
  dialectic reviewer's incident-driven bootstrap-enrichment path before re-opening
  this proposal as a fresh design.
---

# Proposal: `client-awareness` skill (ABANDONED)

> **Status: ABANDONED 2026-04-25 per council reviews.** Both parallel subagent reviews (`dialectic-knowledge-architect` and `feature-dev:code-reviewer`) recommend against shipping. The proposal text below is preserved as-authored; do not revise in place. The dialectic reviewer's carve-out (incident-driven bootstrap enrichment + `tool_descriptions.json` extension) is the cheap additive path the council endorsed in lieu of this skill.

## 1. Why this exists

Hermes ships first-party skill bundles named `claude-code`, `codex`, `opencode`, `dogfood`, `hermes-agent` — i.e., its own model is taught how to recognize and coordinate with sibling harnesses. The pattern was observed during the 2026-04-25 Hermes install on the primary Mac (74 skills synced; ~5 of them are explicit cross-harness teaching artifacts).

UNITARES has the inverse problem: agents arrive in UNITARES from N different harnesses (Claude Code, Codex, Cursor, Hermes, claude.ai, future OpenAgents-style runtimes), each with different surfaces:

| Harness | Surfaces it has | Surfaces it doesn't |
|---|---|---|
| Claude Code | hooks (`hooks/`), slash commands, plugin skills, MCP, `CLAUDE.md` bootstrap | Codex slash commands (`commands/*.md`) |
| Codex | `commands/*.md` slash commands, `CODEX_START.md`, `.unitares/session.json` continuity | Claude hooks |
| Cursor | MCP tools only; no UNITARES-aware hooks | Plugin skills, slash commands |
| Hermes | MCP auto-discovery, native skills, cron, multiple gateway transports | UNITARES skill bundle (S15-c/d/e gap) |
| claude.ai | MCP-only via Cloudflare tunnel; no skill surface | Slash commands, hooks, plugin skills |

The UNITARES skill bundle today (S15-b consolidated 2026-04-25) teaches *what governance is* — EISV, dialectic, knowledge graph, governance lifecycle. It does **not** teach *what client am I, and what does that constrain about my available tool surfaces*. Models infer this from session context (e.g., "I see `hooks/` so I'm in Claude Code") which is fragile and re-derived per session.

## 2. What this skill would teach

A model would invoke / read this skill when:
- It needs to decide between two paths that depend on the harness (e.g., "should I `python3 agents/watcher/agent.py --resolve` or just trust the chime block?")
- It's about to reference a surface that may not exist in its harness (e.g., "the `/diagnose` slash command" only exists in Codex per `commands/diagnose.md`; in Claude Code it's `unitares-governance:diagnose`)
- A user message implies cross-harness work ("can you check what Codex sees" — model needs to know it isn't Codex)

Content sections (rough — not designed):
- **Harness fingerprints.** What env vars, working-directory shapes, file presence, MCP tool surface signatures distinguish each harness. `CLAUDE.md` and `AGENTS.md` already encode some of this; a canonical authoritative list does not exist.
- **Per-harness invariant table.** What's available, what isn't, what's named differently. Specifically: slash command vs skill vs hook vs MCP-tool routing per harness.
- **Cross-harness state expectations.** Where each harness persists continuity (Claude Code: `~/.claude/projects/.../memory/MEMORY.md`; Codex: `.unitares/session.json`; Hermes: `~/.hermes/sessions/`). When does the model expect to see prior state, when does it not?
- **Anti-patterns per harness.** "Don't reference `commands/*.md` in Claude Code — those are Codex-only." (Already in `CLAUDE.md`'s "What Claude should NOT reference" — would lift up.)

## 3. Why this is *not* a slam-dunk addition (open questions for council)

These need to be resolved before this skill ships:

1. **Authority overlap with `CLAUDE.md` / `AGENTS.md` / `CODEX_START.md` / per-harness sections in S15.** Per S15 §8.5, bootstrap context is a separate teaching surface from server-side skills. This proposed skill teaches *cross-harness* knowledge. Whether that belongs in:
   - **Bootstrap** (loaded before MCP is reachable) — pro: every agent gets it free; con: drifts across N bootstrap files
   - **Skills surface** (S15) — pro: canonical, version-controlled; con: only loaded after MCP is reachable, doesn't help during onboarding
   - **`tool_descriptions.json` (§6 cure path)** — pro: cheapest, every MCP client honors it; con: not the right shape for "harness X has Y surfaces"
   
   …is genuinely unclear. **The 2026-04-25 empirical update in S15 §13 narrows S15-e from "safety net" to "recall optimization" — the same logic likely applies here.** If client-awareness can be embedded in tool descriptions and bootstrap files, the skill version may be superfluous.

2. **Drift class is severe.** Harness behavior changes faster than UNITARES governance ontology. If this skill drifts (e.g., Hermes adds a new transport, or Cursor changes its MCP behavior), the skill becomes actively misleading. Either it needs `freshness_days: 7` (vs the 14-day default) or it needs an automated check against actual harness behavior — both of which raise the maintenance bar.

3. **Cross-harness teaching is asymmetric.** A skill served from UNITARES is consumed by clients via MCP. But the *content* is about clients themselves. So the UNITARES server is teaching Codex about its own slash commands, etc. — content authority lives in the client, not the server. This violates S15's "server is source of truth" principle in spirit even if not literally. Council should weigh whether this is acceptable scope creep or a structural mismatch.

4. **What's the failure mode this prevents?** No documented incident motivates this skill (Hermes incident closes at S15 §6 cure). Without a concrete failure pattern, the design risk is "designing for problems we don't have." The case might be that a future Hermes-equivalent reasons incorrectly about UNITARES because its model doesn't know what harness it's in — but we don't have evidence of that.

## 4. What kickstart did NOT do

- Stress-test the proposal with `dialectic-knowledge-architect` (council step from the 2026-04-24 feedback memory).
- Reconcile against existing `CLAUDE.md` and `AGENTS.md` "What [client] should NOT reference" sections — there is meaningful content overlap that needs explicit reconciliation.
- Validate against actual harness behavior (e.g., does Cursor really expose UNITARES MCP the way I described?).
- Decide between bootstrap embedding vs skill surface vs tool-description embedding.

## 5. Recommended next step

Run the parallel-subagent council pattern per `feedback_design-doc-council-review.md`:
- `dialectic-knowledge-architect` reviews §3.1 and §3.3 specifically (authority overlap, asymmetric teaching).
- `feature-dev:code-reviewer` checks §3.2 (drift class, freshness model) against actual maintenance cost of similar skills already in the bundle.
- A second pass after the council writes its parallel review notes (matches the `compute-meter-v2*` proposal pattern).
- Only then: decide whether to add to `unitares/skills/`, to `tool_descriptions.json`, or to abandon.

If §3.4 ("what failure mode does this prevent") doesn't surface a concrete answer during council review, the right outcome is **abandonment**, not implementation. Per the 2026-04-25 v6-paper-restraint memory and the §6-cure-narrows-S15-e empirical update: **default to reducing exposed claims, not adding**.
