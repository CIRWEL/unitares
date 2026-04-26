# S11-a — Skill text drift from the S11 contract

**Date:** 2026-04-25
**Scope:** S11 regression. Stale plugin command/skill text still teaches the retired `continuity_token` cache pattern, despite S11 (resolved 2026-04-21) stating that the v2 cache schema empties the token field. Fix the canonical plugin source so every harness that surfaces this content stops emitting the deprecated pattern.
**Stance:** Descriptive + small fix. No ontology change.
**Parent row:** S11 — `unitares-governance-plugin#17` (commit `743952ab`) landed banner inversion + `hooks/post-identity` v2 cache schema. The hook was fixed; the skill/command surface that teaches *agents* what to write was not.
**Authors:** Kenny Wang (CIRWEL) + process-instance `a61763e1` (Claude Opus 4.7, claude_code, 2026-04-25).

---

## TL;DR

S11 fixed the hook path: `hooks/post-identity` writes `schema_version: 2` and empties `continuity_token`. But the **agent-facing teaching surface** — the `governance-start` command at `unitares-governance-plugin/commands/governance-start.md` (also surfaced as a Claude Skill via the plugin cache) — still tells the agent to:

- prefer `continuity_token` when present (line 14)
- include `continuity_token` when available (line 19)
- run `set session --merge --stamp` *without* `--slot` (line 26)
- persist `continuity_token` and `continuity_token_supported` in the cache (lines 34, 36)

Agents that follow this guidance write a flat `session.json` with the token field populated — exactly the v1 schema S11 retired. The hook then writes its own v2 entry on top. Net effect: v2 schema present at the post-identity write, v1 pattern present in the agent-issued write, depending on which path runs first and whether the agent re-reads after the hook.

This is a **regression of S11's intent**, not a new ontology concern.

## 1. Surfaces that need updating

| File | Repo | Issue |
|---|---|---|
| `commands/governance-start.md` | `unitares-governance-plugin` | Lines 14, 19, 26, 34, 36 — see TL;DR |
| (any sibling commands that surface cache writes) | `unitares-governance-plugin` | Audit needed; same edit class |

## 2. Channel-bleed observation (not a fix here)

The `commands/` directory is described in `unitares` repo's `CLAUDE.md` as Codex-only. In practice it is also surfaced to Claude through the Skill tool path — verified 2026-04-25 when this exact file ran on a Claude session and instructed the cache write that prompted S11-a.

This means the audit scope for "client teaching surfaces" must include `commands/*.md` regardless of the CLAUDE.md framing. Recorded as a memory note (`feedback_plugin-commands-as-claude-skills.md`); not a code change here.

## 3. Fix

Single edit to `commands/governance-start.md`:

- Drop `continuity_token` from the "prefer when present" / "include when available" lists.
- Update the `set session` command to require `--slot=<harness-session-id>` (or remove the cache-write step entirely if S20.1 lands first and the helper rejects slotless writes).
- Drop `continuity_token` and `continuity_token_supported` from the persisted-fields list.
- Update the surrounding language to declare lineage via `parent_agent_id` rather than resume via token.

## 4. Sequencing

- S11-a is **independent of S20**. Either can ship first.
- If S20.1 lands first, the helper rejects slotless writes; S11-a's command text is then *forced* to comply (the agent's `set` call would fail otherwise). Cleaner.
- If S11-a lands first, the regression is closed at the teaching-surface layer; S20 still fixes the underlying convention.
- Recommended: **S11-a first** because it is small, low-risk, and closes the live regression immediately. S20 is a multi-PR multi-week sequence.

## 5. What this row does not address

- The `unitares` repo's `scripts/client/onboard_helper.py:234-245` direct-writer that also persists `continuity_token` — that is **S20 §3c**, not S11-a, because the fix involves either converging on the helper (C1) or mirroring the contract (C2), which is structural rather than a text edit.
- The CLAUDE.md "commands are Codex-only" framing — see channel-bleed memory note.
- Pruning of stale slot files in `~/.unitares/` — separate cleanup row.
- **Pre-existing flat `session.json` files on disk that already contain `continuity_token` from v1-pattern writes.** Those remain world-readable (umask-default 0644 on the direct-writer path) and token-bearing until S20.3 ships parity + the operator runs the §3d cleanup. S11-a closes the *teaching surface*; the *legacy fingerprint window* closes with S20.

## 6. Tests

- Lint/grep test that fails if `commands/governance-start.md` (or any plugin command file) contains `continuity_token` outside a deprecation comment.
- Optional: a contract test that runs the command's `set session ...` snippet through `session_cache.py` once S20.1 lands; expects rejection if the command omits `--slot`.

## 7. Relationship to other rows

- **S11** (parent): the text drifted; this closes the gap.
- **S20** (companion): together they enforce the cache contract at both the teaching layer (S11-a) and the helper layer (S20). Independent ship order.
- **S1**: orthogonal. Does not change token format.
