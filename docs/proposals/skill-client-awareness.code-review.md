---
title: Code review — skill-client-awareness
reviewer: feature-dev:code-reviewer (subagent)
date: 2026-04-25
status: specification-gap — correct before council review
---

# Code Review: skill-client-awareness.md

Reviewing `/Users/cirwel/projects/unitares/docs/proposals/skill-client-awareness.md`
against `CLAUDE.md`, `AGENTS.md`, `commands/diagnose.md`, `hooks/hooks.json`,
`skills/*/SKILL.md` (governance-lifecycle, governance-fundamentals, dialectic-reasoning,
knowledge-graph), and `docs/ontology/s15-server-side-skills.md` §13.

## Verdict

Specification-gap. Do not forward to council in current form. Two factual errors in
the harness table (§1), one fabricated call-site identifier (§2), a structural
misdiagnosis in §3.2, and an understated S15 §13 implication in §3 item 1 would
all send the council working from wrong premises. Corrections are small; a revised
draft takes priority over the dialectic-knowledge-architect pass.

> **Editor's note (post-review, 2026-04-25):** Finding 2 below ("fabricated call-site")
> needs nuance — `unitares-governance:diagnose` is a real plugin-exposed slash command
> backed by `commands/diagnose.md`, which the plugin manifest installs into Claude Code's
> command surface. The reviewer did not have access to the plugin-installed-skills list
> at review time. However, the underlying inconsistency the reviewer flagged is real:
> `CLAUDE.md` states `commands/*.md` are "Codex slash commands, not Claude commands,"
> while the plugin actually exposes them as Claude slash commands via the
> `unitares-governance:` prefix. The proposal's §1 harness table needs a correction in
> a different shape — the row for Claude Code should acknowledge that some `commands/*.md`
> entries DO surface as Claude commands through the plugin, contradicting CLAUDE.md's
> blanket rejection. This is a meaningful discrepancy in the project that the council
> should weigh, not a fabrication by the proposal author.

---

## Critical — Correct Before Council

### 1. Harness table: Claude Code "slash commands" row is wrong (Confidence: 95)

**File:** `skill-client-awareness.md` §1 harness table, row 1

The "Surfaces it has" column for Claude Code includes "slash commands." This is
incorrect for UNITARES-specific slash commands. `CLAUDE.md` ("What Claude should NOT
reference") is explicit: "`commands/*.md` — those are **Codex** slash commands, not
Claude commands." The UNITARES harness table in a `client-awareness` skill would
teach exactly the misinformation it's meant to prevent.

Claude Code does have a general slash-command feature, but UNITARES has no slash
commands authored for Claude Code. The harness table should remove "slash commands"
from the Claude Code surfaces column, or qualify it as "no UNITARES slash commands —
Claude Code uses hooks and MCP tools."

The "Surfaces it doesn't" column correctly lists "Codex slash commands (`commands/*.md`)"
which is accurate — but the left column is contradictory.

**Correction:**

| Harness | Surfaces it has | Surfaces it doesn't |
|---|---|---|
| Claude Code | hooks (`hooks/`), plugin skills, MCP, `CLAUDE.md` bootstrap | UNITARES slash commands (`commands/*.md`) |

### 2. Fabricated call-site: `unitares-governance:diagnose` does not exist (Confidence: 92)

**File:** `skill-client-awareness.md` §2, second bullet

The proposal states: "the `/diagnose` slash command only exists in Codex per
`commands/diagnose.md`; in Claude Code it's `unitares-governance:diagnose`."

The Claude Code equivalent `unitares-governance:diagnose` is not documented anywhere
in this repo. `CLAUDE.md` documents hooks (SessionStart, PostToolUse via Edit/Write)
and has no slash-command section. `hooks/hooks.json` registers three hooks
(SessionStart, PostToolUse, SessionEnd) with no diagnose handler. There is no
`commands/diagnose.md`-equivalent for Claude Code.

In Claude Code, `/diagnose` functionality is delivered manually by calling MCP tools
directly (`identity()`, `get_governance_metrics()`, `health_check()`) — the same
raw tool flow AGENTS.md documents for "when slash commands are unavailable." There
is no named shortcut equivalent.

**Correction:** Remove or rewrite the example. The accurate phrasing is: "the
`/diagnose` slash command exists only in Codex (`commands/diagnose.md`). In Claude
Code there is no equivalent shortcut — the operator calls `identity()`,
`get_governance_metrics()`, and `health_check()` directly."

> **See editor's note above** — this finding is partially incorrect. The identifier
> `unitares-governance:diagnose` does exist via the plugin's command surface. The
> finding does correctly identify that the project's documentation is internally
> inconsistent on this point, which is a real issue for the proposal's §1 to address.

---

## Important — Structural Gaps

### 3. §3.2 drift diagnosis: `freshness_days: 7` does not address the actual failure mode (Confidence: 88)

**File:** `skill-client-awareness.md` §3 item 2

The proposal frames the drift risk as "harness behavior changes faster than UNITARES
governance ontology" and offers two mitigations: `freshness_days: 7` or "automated
check against actual harness behavior."

After reading three SKILL.md files (governance-lifecycle, governance-fundamentals,
dialectic-reasoning), all three use `freshness_days: 14` with `source_files` pointing
to UNITARES Python source files in `unitares/src/`. The server's `stale` flag (S15
§7) is computed from `git log` of those `source_files` against `last_verified`. This
mechanism is calibrated for governance ontology content, where a relevant source file
commit is a reliable proxy for skill drift.

Client harness behavior is different in kind: Cursor's MCP behavior, Hermes's gateway
transports, and Codex's slash commands live in external repos not tracked by
`source_files`. A `freshness_days: 7` setting would make the skill expire faster, but
the `git log`-based staleness mechanism cannot detect a Hermes transport change at all
— because no `source_files` entry covers external harness repos. The skill could go
stale the day after `last_verified` with no mechanism to detect it.

The "automated check against actual harness behavior" alternative is the real solution
to this drift class if any solution exists. But it is entirely undesigned. Council
should understand that `freshness_days: 7` addresses maintenance cadence, not the
structural undetectability of external-harness drift. This distinction changes the
cost-benefit calculus for §3.2 substantially.

**What the council needs to hear:** the maintenance bar for this skill is not
"refresh every 7 days" — it is "build an out-of-band check against harness behavior
or accept that drift is undetectable by the existing mechanism." Neither option is
cheap.

### 4. §3 item 1: S15 §13 implication is understated (Confidence: 85)

**File:** `skill-client-awareness.md` §3 item 1

The proposal notes the S15 §13 empirical update and says "the same logic likely
applies here" and "the skill version may be superfluous." This framing is too hedged
given what §13 actually shows.

S15 §13 records an empirical result: with §6 tool_descriptions.json guards in place,
a Hermes session correctly reasoned about UNITARES governance — harness-agnostic, no
skill content, no adapter work. The §13 conclusion is that S15-e becomes a
"recall-speed and procedural-knowledge optimization," not a safety net.

The `client-awareness` proposal is in exactly the S15-e scope class: cross-harness
knowledge for clients that lack a skill bundle. The §13 logic does not "likely" apply
— it applies directly. Combined with §3 item 4 (no documented incident motivating
this skill), the case for the skill does not reach the threshold the proposal itself
sets in its final paragraph ("if §3.4 doesn't surface a concrete answer, the right
outcome is abandonment").

The council should receive this as a near-abandonment starting posture, not a
"direction unclear" question. Framing it as "may be superfluous" risks the council
spending effort designing a skill that the empirical evidence already argues against.

**Suggested §3 item 1 closer:** "Given §13, the burden of proof for this skill is
demonstrating a failure mode that §6 tool_descriptions.json guards cannot address.
Without that, the S15 §13 logic argues for abandonment rather than design."

### 5. Cursor row in harness table: unverified claim stated as fact (Confidence: 82)

**File:** `skill-client-awareness.md` §1 harness table, row 3

The Cursor row ("MCP tools only; no UNITARES-aware hooks") is presented as a fact,
but CLAUDE.md, AGENTS.md, hooks.json, and commands/*.md contain zero Cursor-specific
content. The proposal itself acknowledges this in §4: "does Cursor really expose
UNITARES MCP the way I described?" — but the harness table in §1 does not carry that
caveat.

A `client-awareness` skill built from this table would teach unverified Cursor
behavior as authoritative. If Cursor's MCP integration differs from the description,
any agent trained on it would reason incorrectly about their available surfaces —
exactly the failure mode the skill is intended to prevent.

**Correction:** Mark the Cursor row with an explicit "unverified" tag in the table,
or remove it from the table and note it as a gap. The revision should make the
council aware that Cursor content needs primary-source validation before the skill
ships.

---

## Verified Files

- `docs/proposals/skill-client-awareness.md` — proposal under review
- `CLAUDE.md` — "What Claude should NOT reference" section; hook lifecycle; no slash commands for UNITARES
- `AGENTS.md` — Codex-specific slash commands list; "What Codex should NOT reference" section
- `hooks/hooks.json` — SessionStart, PostToolUse (Edit|Write), SessionEnd; no diagnose hook
- `commands/diagnose.md` — Codex-only; confirmed `/diagnose` is Codex-exclusive
- `skills/governance-lifecycle/SKILL.md` — `freshness_days: 14`, `source_files` scoped to UNITARES Python source
- `skills/governance-fundamentals/SKILL.md` — same pattern; `freshness_days: 14`
- `skills/dialectic-reasoning/SKILL.md` — same pattern; `freshness_days: 14`
- `skills/knowledge-graph/SKILL.md` — same pattern (frontmatter only)
- `docs/ontology/s15-server-side-skills.md` §13 — empirical update: §6 cure carried Hermes session; S15-e demoted to recall optimization

## Out of Scope for This Review

§3.1 (authority overlap / bootstrap vs. skill surface) and §3.3 (asymmetric teaching,
server-is-source-of-truth tension) are ontology-architecture questions assigned to
`dialectic-knowledge-architect`. No findings here.

§3.4 (what failure mode does this prevent) is a framing question for council. The
review finding in item 4 above bears on it but does not answer it — that answer
requires the council to examine whether any concrete failure pattern exists that
tool_descriptions.json guards cannot address.
