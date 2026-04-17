# Start in Codex

Use this path if you are working from Codex or ChatGPT and want the cleanest UNITARES workflow without depending on Claude-only hooks.

`AGENTS.md` is the machine-facing Codex bootstrap. This file is the human-facing quickstart.

## Goal

Connect to a running UNITARES governance server, preserve continuity cleanly, and check in at meaningful milestones instead of every trivial edit.

## Stable Workflow

1. Run `/governance-start`
2. Keep continuity in `.unitares/session.json`
3. Do real work
4. Run `/checkin` after a meaningful milestone
5. Run `/diagnose` when continuity or governance state looks wrong
6. Use `/dialectic` when you need structured review

If you are not using commands directly, the equivalent raw tool flow is:

1. `onboard()` once and save `uuid`
2. On subsequent sessions, call `identity(agent_uuid=..., resume=true)`
3. `process_agent_update()` after meaningful work
4. `get_governance_metrics()` for read-only state checks
5. `health_check()` only if the system itself may be part of the problem

## Codex Reality

- Codex uses slash commands and explicit tool calls, not Claude hooks
- nothing auto-checks in for you
- Watcher findings are manual unless you invoke the watcher CLI yourself
- `.unitares/session.json` is the local continuity cache you should trust first

## Continuity Model

- `uuid` is the primary identity anchor for resident agents
- `continuity_token` and `client_session_id` are useful resume metadata and fallback paths
- `session_resolution_source` tells you how the runtime actually resolved continuity
- if continuity falls back to a weak source, rerun `/governance-start` or `identity(agent_uuid=..., resume=true)`

## Local Cache

Codex should treat continuity as local workspace state, not Claude-only adapter state.

Preferred cache path:

- `.unitares/session.json`

Shared helper:

- `scripts/client/session_cache.py`

Treat this as local runtime state. It should not be used as a source of truth over the server, but it is the first place to look for:

- `uuid`
- `agent_id`
- `display_name`
- `continuity_token`
- `client_session_id`
- `session_resolution_source`

## Minimal Session Pattern

Typical session:

- start or resume with `/governance-start`
- do meaningful work
- check in after a milestone, completed step, or decision point
- diagnose only when needed

Do not treat every file edit as a governance event. High-signal check-ins are more useful than noisy ones.

## What to Watch

- `identity_status`
- `bound_identity`
- `session_resolution_source`
- `continuity_token_supported`
- `identity_assurance` when an update response includes it

## Commands

- `/governance-start` to onboard or resume and refresh local continuity state
- `/checkin` for a governance update after meaningful work
- `/diagnose` for identity, state, and operator diagnostics
- `/dialectic` for structured review

## Watcher

Codex does not get automatic Watcher surfacing. Use the CLI directly when you want the same signal:

```bash
python3 agents/watcher/agent.py --list-findings --only-open
python3 agents/watcher/agent.py --print-unresolved
python3 agents/watcher/agent.py --resolve <fingerprint> --agent-id <your-uuid>
python3 agents/watcher/agent.py --dismiss <fingerprint> --agent-id <your-uuid>
```

## Scope

This file documents the stable manual Codex path. Older planning docs mention `explicit`, `dogfood-light`, and `dogfood-heavy` modes; treat those as planning terms unless a concrete runtime surface is documented alongside them.

## Claude Note

Claude hooks remain supported in this repo, but they are an adapter convenience, not the canonical UNITARES workflow. The server is the source of truth; the client should stay thin.
