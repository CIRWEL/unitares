---
title: Dialectic Review — `client-awareness` skill
reviewer: dialectic-knowledge-architect
of: skill-client-awareness.md
date: 2026-04-25
posture: the proposal is unusually honest about its own weaknesses; the council's job is to take that honesty at face value rather than soften it
verdict: recommend_abandon (with a small carve-out — see §6)
---

# Dialectic Review

The proposal asks the council to evaluate two things: (§3.1) where cross-harness knowledge should live, and (§3.3) whether UNITARES teaching clients about their own surfaces violates "server is source of truth." It also names §3.4 — the absence of a documented failure mode — as the hardest question.

My read: §3.4 is not the *hardest* question. It is the *only* question, and the §3.1 / §3.3 analyses inherit their answer from it. The proposal already knows this — the closing line ("If §3.4 doesn't surface a concrete answer during council review, the right outcome is abandonment") is the correct verdict pre-loaded. This review's job is to confirm that the §3.1 and §3.3 analyses do not surface a reason to override that default.

They don't. Recommend abandon.

---

## 1. §3.4 first — the missing failure mode is decisive, not contributory

The proposal frames §3.4 as one of four open questions. It is not. It is the question on which the other three depend.

§3.1 (where should this live?) presupposes that "this" needs to live somewhere. §3.3 (is asymmetric teaching acceptable?) presupposes that the teaching is required at all. §3.2 (drift class) presupposes maintenance is worth incurring. All three collapse if §3.4 has no answer.

The S15 §13 empirical update (2026-04-25) is the load-bearing precedent. The originating Hermes incident — which *was* a documented motivation — closed at the §6 cure (tool-description embedding). The qwen3.6:27b test on 2026-04-25 evening showed a fresh-model client auto-discovering and correctly invoking UNITARES tools with **zero skill-bundle exposure**. That collapsed S15-e from "safety net" to "recall optimization." S15-e survived the collapse because there are still recall-shaped problems (teaching *when* to invoke dialectic) that tool descriptions can't carry.

This proposal does not have an analog of that residual. It does not name a recall-shaped problem either. The proposal's own §2 invocation triggers ("decide between two paths," "about to reference a surface that may not exist," "user message implies cross-harness work") are all *self-resolving* in practice:

- "Should I `python3 agents/watcher/agent.py --resolve` or just trust the chime block?" — the chime block IS the answer. The model already sees it. No skill needed.
- "The `/diagnose` slash command only exists in Codex." — `CLAUDE.md`'s "What Claude should NOT reference" already says this. It's bootstrap content, already canonical, already loaded.
- "Can you check what Codex sees" — the model handles this fine without a skill, because it can read the user's message and observe its own tool surface.

**No failure mode + no recall residual = no scope.** The proposal is asking the council to charter work whose deliverable solves no problem the field has surfaced.

---

## 2. §3.1 — Authority overlap collapses by elimination, not by analysis

The proposal poses §3.1 as a three-way: bootstrap vs S15 vs `tool_descriptions.json`. Treat each as a hypothesis under the §1 finding (no failure mode, no recall residual).

### Bootstrap (`CLAUDE.md` / `AGENTS.md` / `CODEX_START.md`)
Already contains the load-bearing pieces. `CLAUDE.md` "What Claude should NOT reference" is the exact pattern — Claude-side, two lines, byte-stable, lives where the model actually looks during onboarding. `AGENTS.md` mirrors via the SHARED CONTRACT block. `CODEX_START.md` does the symmetric job for Codex. The drift problem the proposal worries about (§3.2) is *already* mitigated by `scripts/dev/check-shared-contract.sh` for the Claude/Agents pair. The "drifts across N bootstrap files" objection is real but small: there are three bootstrap files, not N, and the parity check exists.

If a future cross-harness fact emerges that needs to land somewhere, it lands in the existing "What [client] should NOT reference" sections. That's the correct shape. Bootstrap wins by being *already deployed and load-bearing*.

### S15 skill surface
Loaded after MCP is reachable. The proposal acknowledges this means it can't help during onboarding — and onboarding is exactly when "what client am I" matters. This is a structural mismatch the proposal correctly identifies but then proposes to ship anyway. The S15 §13 update tightens this: skills are now framed as recall-speed optimization, not safety net, and the proposal doesn't name a recall-speed problem.

### `tool_descriptions.json` (§6 cure path)
The proposal correctly notes this is the wrong shape ("not the right shape for 'harness X has Y surfaces'"). Tool descriptions describe tools, not harnesses. Forcing harness-awareness into tool descriptions would inflate every tool's description with cross-harness boilerplate, which is the v6.7 surface-sprawl anti-pattern in a different costume.

### Verdict on §3.1
The bootstrap option wins, but it wins because the work is **already done** in `CLAUDE.md` / `AGENTS.md` / `CODEX_START.md`. There is no PR to write. The question dissolves. The §3.1 analysis is therefore not a reason to ship a new skill — it is a reason to confirm the existing bootstrap content is sufficient and add to it incrementally as concrete cross-harness facts surface.

---

## 3. §3.3 — Asymmetric teaching is a structural mismatch, not just spirit

The proposal's framing — "violates 'server is source of truth' in spirit even if not literally" — undersells the problem. The mismatch is literal, not spiritual.

The S15 doctrine is: UNITARES is the source of truth for **governance** ontology — EISV, dialectic, KG, lifecycle. That's content the *server* can authoritatively produce, version, and serve. Clients consume it because the server actually owns the truth.

A `client-awareness` skill inverts this. The content is "Claude Code has hooks/, Codex has commands/*.md, Cursor has X." UNITARES does not own that truth. **The clients own it.** The Claude Code surface is whatever Anthropic ships in claude-code; the Codex surface is whatever the Codex team ships; Cursor's MCP behavior is whatever Cursor's MCP client implements. UNITARES would be transcribing facts it doesn't control, into a skill bundle versioned on UNITARES's release cadence, served from UNITARES's MCP endpoint.

This is not a spirit violation. It's a category error. The relationship "server teaches client about itself" makes sense when the server owns the relationship (e.g., teaching a client which UNITARES tools exist — UNITARES owns that). It does not make sense when the server is transcribing client-internal facts that change on the client's release cadence, not the server's.

### Drift consequence
This is also why §3.2's drift concern is *worse* than the proposal frames. `freshness_days: 7` doesn't help when the upstream truth (Anthropic's claude-code, the Codex team's CLI) ships changes UNITARES doesn't see. The skill is freshness-stamped against UNITARES's clock, not the harness's. A skill that's "fresh" by UNITARES's clock can describe a harness state that's months stale. There's no observable signal UNITARES can use to detect this — the harness doesn't tell UNITARES when it changes its surface.

The S15 §6 path doesn't have this problem. Tool descriptions are about UNITARES tools, which UNITARES controls. The same self-ownership that makes §6 work makes `client-awareness` not work.

### Verdict on §3.3
The asymmetry is structural and not acceptable. UNITARES should not own facts whose authoritative source is upstream of UNITARES.

---

## 4. The one residual — and why it's not enough to save the proposal

Steel-manning: is there *any* cross-harness knowledge that UNITARES legitimately owns?

Yes — the **cross-harness invariants of the UNITARES surface itself**: which UNITARES MCP tools each harness can reach, which UNITARES skills each harness can render, which UNITARES bootstrap files exist per harness. These are facts about *UNITARES integration*, not about *the harness*, and UNITARES does own them.

But this residual is already covered:

- The plugin bundle (`unitares-governance-plugin`) is the canonical mirror of UNITARES content per harness. Adapter-level differences live there.
- `CLAUDE.md` / `AGENTS.md` / `CODEX_START.md` already cover the bootstrap-lifecycle differences.
- S15-a's `skills` MCP tool already exposes which skills each harness can pull.

There is nothing left over for a `client-awareness` skill to canonicalize that isn't already canonicalized somewhere appropriate. The proposal's §2 ("Per-harness invariant table") is a synthesis view, not a source-of-truth artifact — and synthesis views are exactly the kind of thing that goes stale when the underlying sources change without the synthesis being notified.

---

## 5. Position

**`recommend_abandon`.**

Specific rationale:

1. §3.4 has no answer and no plausible path to one. The Hermes-class motivation closed at the §6 cure (S15 §13 empirical update). No other failure mode is named.
2. §3.1's authority-overlap question dissolves: bootstrap files already carry the load-bearing content, the §6 cure carries server-tool authority, and no remaining content needs a new home.
3. §3.3's asymmetric-teaching concern is a structural category error, not a spirit violation. UNITARES would be transcribing facts it doesn't own from sources whose release cadence it can't observe.
4. The proposal's own §3.2 drift class makes maintenance cost > value when value is undefined.
5. Per `feedback_v6-paper-restraint.md` and the S15 §13 update: default to reducing exposed claims, not adding. This proposal adds a claim ("UNITARES teaches clients about themselves") with no offsetting evidence.

The proposal closes with "default to reducing exposed claims, not adding." The council should ratify that default.

---

## 6. Carve-out: what *should* happen instead

Abandonment of the skill does not mean the underlying observation was wrong. The observation — that cross-harness facts get re-derived per session, sometimes incorrectly — is real. Two cheap, additive responses preserve the value without taking on the structural risk:

### (a) Incremental bootstrap-file enrichment (not a new artifact)
When a concrete cross-harness fact surfaces that an agent got wrong in production, add a one-liner to the appropriate "What [client] should NOT reference" section in `CLAUDE.md` / `AGENTS.md` / `CODEX_START.md`. This is the existing pattern. No new file, no new skill, no drift surface beyond what already exists. Total cost: minutes per fact, only when a fact is paid for by an actual incident.

### (b) Tool-description enrichment when relevant
If a cross-harness fact is actually about *how to invoke a UNITARES tool from harness X*, that's `tool_descriptions.json` content per the §6 cure. This is already the path the S15 §13 update endorses.

Both responses share a property: they are **incident-driven**, not design-driven. They wait for evidence of a real failure mode before incurring surface area. This is the correct posture given §3.4 is empty.

### What NOT to do
Do not open a `unitares/skills/client-awareness/` directory in anticipation of future need. The same forcing-function shape called out in S15 §11.8 ("canonical-on-server is a one-way decision once any adapter consumes it") applies: shipping a skeleton skill creates a slot that future PRs will fill, and the slot itself is what entrenches the structural mismatch.

---

## 7. Outstanding questions worth carrying forward

- **Is there a recall-shaped cross-harness problem that would change this verdict?** I don't see one today. If a future incident shows a model in harness X reasoning incorrectly about its own surface in a way bootstrap can't catch and tool descriptions can't carry, re-open. Until then, no.
- **Should `CLAUDE.md` / `AGENTS.md` / `CODEX_START.md` be audited for completeness?** Yes, but as a small docs PR, not as a precursor to this skill. The audit's deliverable is "the existing bootstrap surface is sufficient" or "here are the three lines we should add" — not a new skill.
- **Does the §3.2 drift class apply to the existing bootstrap files?** Partly. `commands/*.md` references in `CLAUDE.md` will go stale if Codex renames a command. The mitigation is the same incremental pattern (incident-driven update), not a versioned skill bundle. The drift cost is bounded because the surface area is small.
- **Is there a Hermes-side or Cursor-side analog of `CLAUDE.md` that should exist?** That's a question for the *Hermes / Cursor* maintainers, not for UNITARES. UNITARES providing it would re-introduce the §3.3 asymmetry. If Hermes wants a UNITARES-aware bootstrap, the Hermes adapter (S15-e, optional and lower-priority per §13) is the right surface.

---

## Synthesis

The proposal is well-shaped: it kickstarts a question, names its own weaknesses honestly, asks for council review, and pre-loads the correct verdict in its closing paragraph. The council's contribution is to confirm that pre-loaded verdict and to articulate *why* — so the next time a similar proposal surfaces, the reasoning is in the audit trail.

The "why" is: UNITARES should own facts whose authoritative source is UNITARES. Cross-harness facts have authoritative sources upstream of UNITARES (the harness vendors). Transcribing those facts into a UNITARES-served skill creates a synthesis view whose freshness UNITARES cannot observe and whose drift UNITARES cannot detect. With no documented failure mode motivating that risk, and with the §6 cure + bootstrap files already covering the residual real cases, the structural cost outweighs the speculative benefit.

Abandon the skill. Keep the observation. Add to bootstrap incrementally when a real incident pays for it.
