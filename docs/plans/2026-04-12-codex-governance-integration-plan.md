# Codex Governance Integration Plan

**Date:** 2026-04-12
**Status:** Proposed
**Scope:** `unitares-governance` client/plugin plus light runtime-facing expectations

## Goal

Make UNITARES feel native in Codex without turning every file edit into a governance ritual.

The target state is:

- Codex can onboard and resume cleanly
- continuity survives across sessions
- check-ins happen at meaningful milestones
- deterministic outcomes can still be captured automatically
- dogfood intensity is configurable instead of hardcoded

## Current state

The local plugin install already has a real Codex surface:

- Codex plugin manifest exists in `.codex-plugin/plugin.json`
- Codex docs exist in `CODEX_START.md`
- manual commands exist:
  - `commands/checkin.md`
  - `commands/diagnose.md`
  - `commands/dialectic.md`
- shared skills exist:
  - `governance-lifecycle`
  - `governance-fundamentals`
  - `knowledge-graph`
  - `dialectic-reasoning`

But the actual automation layer is still Claude-shaped:

- `hooks/hooks.json` wires `SessionStart` and `PostToolUse`
- the commands are routed through `${CLAUDE_PLUGIN_ROOT}`
- `hooks/session-start` writes cached state into `.claude/unitares-session.json`
- `hooks/post-edit` writes `.claude/unitares-last-edit.json`
- `post-edit` intentionally does **not** auto-call `process_agent_update()`

That split is why Codex currently feels explicit/manual while Claude feels more ambient.

## Design principles

1. **High-signal over high-frequency**
   - do not auto-check in on every write
   - do prefer one check-in after a meaningful milestone

2. **Continuity first**
   - the main Codex pain is not lack of hooks; it is weak continuity
   - onboarding and resumption need to be frictionless and visible

3. **Transport-neutral state**
   - do not keep Codex continuity in `.claude/...`
   - use a neutral cache path such as `.unitares/session.json`

4. **Deterministic outcomes can be more automatic than reflective check-ins**
   - `outcome_event` for tests/commits is lower-risk to automate
   - `process_agent_update` should remain more intentional

5. **Dogfood mode must be opt-in by intensity**
   - default Codex mode should stay explicit
   - tighter automation should exist as `dogfood` modes, not baseline behavior

## What should change

### Phase 1: Make Codex explicit mode excellent

This phase does not require Codex hook support.

#### 1. Add a first-class Codex onboarding command

Add a command in `unitares-governance/commands/` for session start, for example:

- `/governance-start`
  - call `onboard()`
  - surface `agent_uuid` (primary stored identity)
  - explain whether identity was `created` or `resumed`
  - store `agent_uuid` in a local neutral cache for `identity(agent_uuid=..., resume=true)`

This removes the need for Codex users to remember the raw onboarding sequence.

#### 2. Make `/checkin` continuity-aware by default

The current `commands/checkin.md` is directionally right, but it should be stricter:

- prefer `continuity_token` over `client_session_id` when present
- load cached continuity state automatically when possible
- include `response_mode="mirror"` by default for Codex
- explicitly avoid fabricating progress from raw file churn

#### 3. Make `/diagnose` the default repair path

The existing `commands/diagnose.md` is close. It should become the standard answer to:

- “who does UNITARES think I am?”
- “did continuity break?”
- “is the system warning me or am I actually degraded?”

It should prefer:

1. `identity()`
2. `get_governance_metrics()`
3. `health_check()` only when needed

#### 4. Use a transport-neutral cache path

Move local adapter state from:

- `.claude/unitares-session.json`
- `.claude/unitares-last-edit.json`

to something like:

- `.unitares/session.json`
- `.unitares/last-milestone.json`

Claude-specific adapters can still mirror or reuse that path, but the canonical cache should not be branded as Claude-only.

### Phase 2: Add light Codex dogfood mode

This is the right “I want Codex to dogfood more” layer.

#### Mode name

Add a client-side mode such as:

- `UNITARES_CODEX_MODE=explicit`
- `UNITARES_CODEX_MODE=dogfood-light`
- `UNITARES_CODEX_MODE=dogfood-heavy`

Default should remain `explicit`.

#### Dogfood-light behavior

In `dogfood-light`:

- on session start, run the equivalent of `/governance-start`
- persist continuity locally
- capture recent edit context or milestone context locally
- do **not** auto-send `process_agent_update()` after every write
- do surface a reminder when a milestone is likely due

Examples of reminder triggers:

- first significant code edit after onboarding
- explicit test run completed
- git commit created
- 30+ minutes of active coding without a check-in

The output should be suggestive, not mandatory:

`You’ve crossed a meaningful milestone. Consider /checkin.`

### Phase 3: Add heavy dogfood mode for research

This mode is for learning from Codex behavior, not for all users.

#### Dogfood-heavy behavior

- automatic session-start onboarding/resume
- stronger milestone detection
- optional auto-checkin after high-confidence milestones
- automatic deterministic `outcome_event` emission for:
  - pytest pass/fail
  - lint pass/fail
  - git commit

Even here, raw edit events should not directly trigger `process_agent_update()`.

Heavy mode is for studying agent behavior under governance, not for normal operator ergonomics.

## Concrete file targets in `unitares-governance`

### Immediate

- `CODEX_START.md`
  - add explicit `explicit / dogfood-light / dogfood-heavy` modes
  - document neutral continuity cache path

- `.codex-plugin/plugin.json`
  - keep as the Codex entry surface
  - optionally improve `defaultPrompt` to include onboarding and diagnosis phrasing

- `commands/checkin.md`
  - make continuity-token preference explicit
  - standardize `mirror` as the default check-in response

- `commands/diagnose.md`
  - make it the canonical continuity + state debugging command

### Next

- add `commands/governance-start.md`
  - Codex-native onboarding/resume entry point

- add a shared helper script or adapter-neutral cache helper
  - avoid duplicating state handling between Codex and Claude adapters

### Later

- refactor `hooks/session-start` and `hooks/post-edit`
  - extract transport-neutral logic
  - leave thin Claude wrappers around it
  - reuse the same core milestone logic for future Codex automation if the platform supports it cleanly

## Runtime expectations from `governance-mcp-v1`

Codex-side integration will feel better if the runtime keeps improving these caller-facing surfaces:

1. onboarding/resume payloads must stay continuity-rich
2. mirror-mode responses should remain short and grounded
3. authority should be explicit when the system is in behavioral warmup / ODE fallback

That work is tracked separately in:

- `docs/plans/2026-04-12-codex-dogfood-ux-tightening.md`

## What not to do

- do not make every `Edit` or `Write` a governance event
- do not make Codex emulate Claude just because Claude has hooks
- do not hide continuity state in adapter-branded folders
- do not auto-check in trivial churn and then call it dogfooding

## Recommended default

For normal Codex use:

- baseline mode: `explicit`
- workflow:
  - start with `/governance-start` or `onboard()`
  - use `/checkin` after meaningful milestones
  - use `/diagnose` when continuity or state looks wrong
  - let deterministic outcome capture stay more automatic than reflective updates

For active UNITARES research and dogfooding:

- opt into `dogfood-light`
- reserve `dogfood-heavy` for deliberate experiments

## Success criteria

This plan is successful when Codex users can do the following without memorizing raw tool choreography:

1. start a session and reliably resume the same identity
2. know when to check in
3. diagnose continuity failures quickly
4. dogfood governance more often without turning work into ceremony
5. increase automation intensity intentionally rather than accidentally
