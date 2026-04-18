# SessionStart Stops Creating Identities (Identity Honesty Part C)

**Status:** Draft plan — not yet executed
**Date:** 2026-04-17
**Author:** Kenny Wang, Independent Researcher (dogfooded with Claude Opus 4.7)
**Scope:** unitares-governance-plugin (primary) + optional unitares companion
**Supersedes tactical alleviations:** plugin#4, plugin#5, unitares#27, unitares#28

## Problem

The plugin's session-start hook creates an identity on the agent's behalf via HTTP `onboard`, then tells the agent "you are X." But the MCP stdio transport — which the agent actually uses for tool calls — is a separate channel. Its identity middleware auto-binds to whatever the sticky transport cache (`src/mcp_handlers/middleware/identity_step.py:221-255`) returns for the incoming fingerprint, independently of whatever the HTTP-side onboard created.

Result: two server-side identities per session. One gets orphaned and joins the ghost pool. The archive-every-night cleanup mitigates the symptom but doesn't remove the generator.

This also violates identity-invariants #1 ("Never silently substitute identity"): the hook makes a positive assertion about who the agent is *before the agent has declared.*

Tonight's alleviations made the assertion into a receipt (plugin#5), surfaced the source label ambiguity (unitares#28), and fixed the worst naming leak (hostname fallback). They improved truthfulness without removing the presumption.

## Goal

**SessionStart provides information. It does not act.** First MCP tool call is the only identity creation path.

Four invariants this enforces:

1. No identity exists on the server until the agent explicitly calls `onboard()` or `identity(agent_uuid=...)`.
2. The identity that emerges is bound to the transport the agent used to create it — no HTTP/stdio bifurcation.
3. The session cache (`~/.unitares/sessions/<slot>.json`) records what the agent *chose*, not what the hook *guessed*.
4. Labels are set by the agent, not derived from the workspace or the user's Mac hostname. (Tonight's naming fixes become unnecessary because nothing auto-names anything.)

## Architecture

### Old flow

```
SessionStart hook:
  1. curl onboard(...)          → creates UUID X on HTTP session
  2. curl process_agent_update   → post-onboard check-in (needs UUID X)
  3. curl get_governance_metrics → EISV summary
  4. Write ~/.unitares/session-<slot>.json with UUID X
  5. Emit context: "Agent: <label>, UUID: X, EISV: <summary>"

Agent's first MCP tool call:
  - Middleware sees no agent_uuid arg, no explicit bind
  - Sticky cache returns UUID X' from a prior fingerprint match
  - Or, if no cache match, the server auto-creates UUID Z
  - Either way, UUID X is orphaned
```

### New flow

```
SessionStart hook:
  1. curl /health                → confirm governance is reachable
  2. Read ~/.unitares/sessions/  → list recent UUIDs for this workspace
  3. Emit context:
     "Governance is online. No identity has been created on your behalf.
      To join, call one of:
        onboard(purpose=...)                            — new identity
        identity(agent_uuid=X, resume=true)             — resume known UUID
        bind_session(agent_uuid=X, resume=true)         — resume explicitly
      Recent session UUIDs for this workspace:
        - <uuid> (<label>, last active <date>)
        - ..."

Agent's first MCP tool call (must be one of the three above):
  - Middleware PATH 0 (identity_step.py:296-317) handles agent_uuid
  - Onboard creates with caller-chosen name
  - Response includes UUID + continuity_token

PostToolUse hook (NEW, matches onboard|identity|bind_session):
  - Captures UUID + token + label from response
  - Writes ~/.unitares/sessions/<slot>.json
  - No identity creation happens here — just recording

Edit auto-checkin hook (modified):
  - Reads session cache; if empty, silently skip
  - No implicit onboarding on first edit

SessionEnd / PostStop hooks (modified):
  - Read session cache; if empty, no check-in
```

## Changes

### Plugin repo (CIRWEL/unitares-governance-plugin)

| File | Change |
|---|---|
| `hooks/session-start` | Reduce from ~440 → ~80 lines. Health check + skill inject + informational context. No onboard, no checkin, no metrics. |
| `hooks/post-tool-use` | **NEW**. Matches `mcp__unitares-governance__(onboard\|identity\|bind_session)`. Parses response, writes session cache. |
| `hooks/hooks.json` | Register new PostToolUse matcher for identity-creating tools. |
| `hooks/post-edit` | Tolerate missing cache (already mostly does via `_session_lookup.py`). Verify auto-checkin path silently skips. |
| `hooks/post-stop` | Silent skip if no session cache (was: try to fetch state anyway). |
| `hooks/session-end` | Silent skip if no session cache. |
| `scripts/onboard_helper.py` | Repurpose: called only by explicit `/governance-start` slash command, never by hooks. Can be simplified. |
| `scripts/session_cache.py` | New entry point: `record_from_tool_response(workspace, slot, tool_name, response)`. Used by post-tool-use. |
| `scripts/checkin.py` | Tolerate missing session (skip silently, log). |
| `config/defaults.env` | `UNITARES_AUTO_ONBOARD=0` — new behavior default. Fallback `=1` preserves old behavior for operators who want it. |
| `tests/test_session_start_*.py` | Rewrite: assert session-start emits ZERO tool calls when auto-onboard=0. |
| `tests/test_post_tool_use.py` | **NEW**. Asserts onboard/identity/bind_session responses get recorded to session cache. |
| `tests/test_post_stop_hook.py`, `test_session_end_hook.py` | New cases: no cache → silent skip. |

### Unitares repo (CIRWEL/unitares) — optional companion, can ship separately

| File | Change |
|---|---|
| `src/mcp_handlers/middleware/identity_step.py` | Feature flag `UNITARES_REQUIRE_EXPLICIT_BIND`. When set, first tool call from a new fingerprint without `agent_uuid` returns 401 with guidance. When unset (default initially), behavior unchanged. |
| `docs/specs/...` | This plan. |
| Tests | Coverage for the new 401 path and the flag gating. |

## Sequencing

**Session A (~1 hour):** Plugin changes behind `UNITARES_AUTO_ONBOARD=0` default-off flag. Still onboards by default, but new post-tool-use hook records cache from tool responses. Tests green. Ship as one plugin PR.

**Session B (~1 hour):** Flip default to `UNITARES_AUTO_ONBOARD=0`. Delete the `curl onboard` from session-start hook. Tests assert zero tool calls during session-start. Ship as second plugin PR.

**Session C (~1 hour, optional, days later):** Unitares-side `UNITARES_REQUIRE_EXPLICIT_BIND` flag. Grace-period: log "would have rejected" for 2 weeks. Then flip. Ship as unitares PR.

Three small PRs beats one big one. Each reversible.

## Risk + migration

### What breaks immediately

Nothing. The feature flag gates the whole change. Default-off means existing behavior until flipped.

### What breaks when flag flips to `=0`

- Agents that never make an MCP tool call — no identity created. Previously they got a ghost created anyway. Actually that's an improvement.
- Resident agents (Watcher, Vigil, Sentinel, Lumen) — unaffected. They all already call `identity(agent_uuid=...)` explicitly; the plugin hook isn't in their path.
- `/checkin` slash command — needs to succeed on first invocation. May need to call `onboard()` implicitly if no session cache exists, with a visible "creating new identity" notice.
- `/diagnose` — already tolerates missing cache. Verify.
- Post-stop / session-end — explicitly modified to silent-skip.

### What breaks if the unitares companion flag flips to require explicit bind

- External REST clients that call tools without ever calling `onboard()` first. Risk: Codex plugin (uses a different hook chain); Pi/Anima integration; Discord bridge. **Must survey these before flipping.**
- Dashboard / fleet monitoring that queries from various IPs. If they don't bind first, they'll 401.

Mitigation: log-only mode for 2 weeks. See how many callers would have 401'd. Fix them. Then flip.

## What this does NOT do

- Does not eliminate the sticky transport cache (it's still useful for stable sessions that have bound once). It only prevents *creation* from fingerprint, not resumption.
- Does not archive existing ghost identities. Tonight's manual cleanup covers the active pool; older ghosts age out naturally.
- Does not rename existing agents or change labels retroactively.
- Does not touch the dialectic / KG / EISV code. Identity is ONE layer; this plan is scoped to it.

## Axiom alignment

Invariant 1 (Never silently substitute) — honored. Identity only exists when the agent said so.
Invariant 2 (force_new is explicit opt-in only) — honored; no automatic retries.
Invariant 3 (Per-instance isolation) — preserved; session_cache still slot-scoped.
Invariant 4 (Name is cosmetic) — honored; no auto-naming. Label comes from agent's own `onboard(name=X)` or `identity(name=X)` call.

## Open questions

1. Should session-start still inject the EISV baseline? If the agent hasn't bound yet, there's no baseline to inject. Probably drop from SessionStart; make it the first line of the `onboard` / `identity` tool response.
2. What does `/checkin` do on its first invocation in a session with no identity? Options: (a) auto-onboard with a clear notice; (b) error with guidance "call onboard() first"; (c) offer both. I lean (a) — the slash command is a voluntary explicit action, so the presumption is smaller.
3. Should the post-tool-use hook also record responses from `process_agent_update` or other tools that may affect identity metadata? Initially: no. Keep it narrow — only creation/resume tools. Widen later if needed.

## Non-goals (explicit)

- No Schema migration (the heuristic `label_source` from unitares#28 stays).
- No UUID format changes.
- No changes to how PostgreSQL/AGE store identities.
- No changes to the middleware identity-resolution order (`PATH 0`, `PATH 1`, etc.) beyond the optional companion flag.
