---
description: "Manual UNITARES governance check-in after meaningful work"
---

Before calling tools, check for `.unitares/session.json` in the current workspace.

Use the shared helper in this plugin repo:

- `scripts/client/session_cache.py get session`

If the cache contains `uuid`, treat it as the canonical identity anchor.

If current binding is unclear or this is a fresh session, call `identity(agent_uuid=<uuid>, resume=true)` before `process_agent_update()`.

If no `uuid` is cached, prefer `continuity_token` and otherwise use `client_session_id`.

If no local continuity state exists and the current identity is unclear, use `/governance-start` first.

Call `process_agent_update` for the current agent after a meaningful unit of work.

Inputs:

- `response_text`: concise summary of what was actually accomplished
- `complexity`: estimate `0.0-1.0`
- `confidence`: honest estimate `0.0-1.0`
- include `continuity_token` when available, otherwise `client_session_id`, when the client needs explicit continuity data
- use `response_mode="mirror"` by default for Codex

Guidelines:

- Do not check in after every trivial edit.
- Prefer one check-in per meaningful milestone, completed step, or decision point.
- If you had to rebind with `identity()`, use that restored binding for the update instead of inventing a new `agent_id`.
- If recent local edit context exists, use it to improve the summary, but do not report raw file churn as if it were real progress.
- If deterministic results already happened in the workflow, mention them concretely instead of speaking in generalities.

After the call:

- report the verdict
- report identity-assurance or continuity warnings when they are surfaced
- report margin or edge warnings when present
- report any guidance briefly
- report the mirror question when present
- if verdict is `pause` or `reject`, recommend `request_dialectic_review`
- if verdict is `guide`, summarize the guidance and adjust behavior
