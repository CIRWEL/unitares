# Start in Codex

Use this path if you are working from Codex or ChatGPT and want the cleanest UNITARES workflow without depending on Claude-only hooks.

## Goal

Connect to a running UNITARES governance server, preserve continuity cleanly, and check in at meaningful milestones instead of every trivial edit.

## Recommended Default

Use `explicit` mode unless you are deliberately dogfooding tighter automation.

### Modes

- `explicit`: manual onboarding/check-in/diagnosis; best default
- `dogfood-light`: explicit check-ins plus stronger milestone reminders
- `dogfood-heavy`: research mode for tighter automation and deterministic outcome capture

This plugin currently optimizes for `explicit`.

## Recommended Flow

1. Run `/governance-start`
2. Keep continuity in `.unitares/session.json`
3. Do real work
4. Run `/checkin` after a meaningful milestone
5. Run `/diagnose` when continuity or governance state looks wrong
6. Use `/dialectic` when you need structured review

If you are not using commands directly, the equivalent raw tool flow is:

1. `onboard()`
2. keep `continuity_token` when supported, otherwise `client_session_id`
3. `process_agent_update()` after meaningful work
4. `get_governance_metrics()` for read-only state checks
5. `identity()` if continuity looks wrong
6. `health_check()` if the system itself may be part of the problem

## Local Continuity Cache

Codex should treat continuity as local workspace state, not Claude-only adapter state.

Preferred cache path:

- `.unitares/session.json`

Shared helper:

- `scripts/client/session_cache.py`

Treat this as local runtime state. It should not be used as a source of truth over the server, but it is the first place to look for:

- `continuity_token`
- `client_session_id`
- `uuid`
- `agent_id`
- `display_name`
- `session_resolution_source`

## Minimal Session Pattern

Typical session:

- start or resume with `/governance-start`
- do meaningful work
- check in after a milestone, completed step, or decision point
- diagnose only when needed

Do not treat every file edit as a governance event. High-signal check-ins are more useful than noisy ones.

## What to Watch

- `continuity_token`: prefer this when available
- `client_session_id`: fallback continuity token when strong resume is unavailable
- `session_resolution_source`: if this falls back to a weak source, resume explicitly
- `identity_assurance`: strong is better than implicit

## Commands

- `/governance-start` to onboard or resume and refresh local continuity state
- `/checkin` for a governance update after meaningful work
- `/diagnose` for identity, state, and operator diagnostics
- `/dialectic` for structured review

## Claude Note

Claude hooks remain supported in this repo, but they are an adapter convenience, not the canonical UNITARES workflow. The server is the source of truth; the client should stay thin.
