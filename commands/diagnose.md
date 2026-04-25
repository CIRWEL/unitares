---
description: "Show current UNITARES governance state and operator-relevant diagnostics"
---

Start by checking for `.unitares/session.json` in the current workspace.

Use the shared helper in this repo:

- `scripts/client/session_cache.py get session`

If the cache contains `uuid`, treat it as a local identity anchor and lineage candidate.

Do not verify by bare UUID resume. If you need to test ownership of a cached UUID, call `identity(agent_uuid=<uuid>, continuity_token=<token>, resume=true)` only when a matching current token is available.

If no proof-owned UUID rebind is available, call `identity()` to inspect current binding. Use `/governance-start` to create a fresh process identity with `parent_agent_id=<cached uuid>` if this process should inherit prior work.

Call `identity()` first when continuity or binding is unclear.

Then call `get_governance_metrics` for the current agent using the same continuity data.

Call `health_check()` only when system health, not agent state, may be part of the issue.

Display:

- whether identity was proof-resumed, freshly created, or created with lineage
- whether lineage was declared through `parent_agent_id`
- `identity_status`
- `bound_identity`
- `session_resolution_source`
- `continuity_token_supported`
- `identity_assurance`
- deprecation warnings
- whether continuity looks strong or weak
- E, I, S, V
- coherence
- risk score
- verdict
- summary or mode/basin if available
- behavioral vs ODE authority when it is obvious in the response

If `health_check()` is used, also show:

- overall system status
- degraded checks
- first operator action

Call `list_process_bindings()` (optionally with `agent_uuid=<uuid>`) to show live execution-context bindings for the agent. When `concurrent_binding_detected` is true, surface the `bindings[]` tuples — each row is `{host_id, pid, pid_start_time, transport, tty, last_seen}` — so the operator can see which contexts are siphoning the same UUID. See issue #123.

If the live identity differs from `.unitares/session.json`, refresh the local cache with the latest `uuid`, identity fields, and continuity data using `scripts/client/session_cache.py set session --merge --stamp`.

Do not dump raw JSON unless the user explicitly asks for it.
Prefer a short interpreted summary.
