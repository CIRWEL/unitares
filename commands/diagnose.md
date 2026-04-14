---
description: "Show current UNITARES governance state and operator-relevant diagnostics"
---

Start by checking for `.unitares/session.json` in the current workspace.

Use the shared helper in this plugin repo:

- `scripts/session_cache.py get session`

If continuity state exists:

- prefer `continuity_token`
- otherwise use `client_session_id`

Call `identity()` first when continuity or binding is unclear.

Then call `get_governance_metrics` for the current agent using the same continuity data.

Call `health_check()` only when system health, not agent state, may be part of the issue.

Display:

- whether identity was resumed or freshly created
- `identity_status`
- `bound_identity`
- `session_resolution_source`
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

If the live identity differs from `.unitares/session.json`, refresh the local cache with the latest continuity data.

Do not dump raw JSON unless the user explicitly asks for it.
Prefer a short interpreted summary.
