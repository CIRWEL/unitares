---
description: "Create, declare lineage, or proof-resume a UNITARES session in Codex"
---

Start by checking for a local continuity cache in `.unitares/session.json` inside the current workspace.

Use the shared helper in this repo:

- `scripts/client/session_cache.py get session`

If the cache contains a `uuid`, treat it as a lineage candidate, not ownership proof.

Call `onboard()` against UNITARES using the strongest honest mode:

- if this is a fresh process with no prior UUID, pass `force_new=true`
- if this is a fresh process inheriting prior work, pass `force_new=true`, `parent_agent_id=<cached uuid>`, and `spawn_reason="new_session"`
- if you are rebinding the same live owner and have a current matching token, call `identity(agent_uuid=<uuid>, continuity_token=<token>, resume=true)` instead of `onboard()`
- include `model_type` when the current runtime is clear from context
- do not invent a display name unless the user asked for one

Do not use bare `identity(agent_uuid=<uuid>, resume=true)`. UUID alone is an unsigned claim and is hijack-shaped under strict identity mode.

Do not use `onboard(continuity_token=...)` as cross-process resume except when deliberately testing the S1-a deprecation path.

After a successful `identity()` or `onboard()` response:

- create or update `.unitares/session.json` using `scripts/client/session_cache.py set session --merge --stamp`
- keep it compact and machine-readable JSON
- include:
  - `server_url` when known
  - `uuid`
  - `agent_id`
  - `display_name`
  - `client_session_id`
  - `continuity_token`
  - `session_resolution_source`
  - `continuity_token_supported`
  - `updated_at`

When reporting back:

- say whether the identity was freshly created, proof-resumed, or created with lineage
- if lineage was declared, name the parent UUID prefix
- show the resolved display name or agent id
- note whether continuity is strong or weak
- mention the next useful command:
  - `/checkin` after meaningful work
  - `/diagnose` if continuity still looks wrong

Do not dump raw JSON unless the user asks for it.
Prefer a short interpreted summary.
