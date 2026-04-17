---
description: "Start or resume a UNITARES session in Codex and refresh local continuity state"
---

Start by checking for a local continuity cache in `.unitares/session.json` inside the current workspace.

Use the shared helper in this plugin repo:

- `scripts/client/session_cache.py get session`

If the cache contains a `uuid`, treat it as the canonical identity anchor and call `identity(agent_uuid=<uuid>, resume=true)` first.

If there is no cached `uuid`, call `onboard()` against UNITARES:

- include `continuity_token` when available
- otherwise include `client_session_id` when available
- include `model_type` when the current runtime is clear from context
- do not invent a display name unless the user asked for one

If UUID-direct resume fails, or the cache is missing/stale, fall back to `onboard()` and refresh the cache from the successful response.

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

- say whether the identity was resumed by UUID, resumed through continuity metadata, or freshly created
- show the resolved display name or agent id
- note whether continuity is strong or weak
- mention the next useful command:
  - `/checkin` after meaningful work
  - `/diagnose` if continuity still looks wrong

Do not dump raw JSON unless the user asks for it.
Prefer a short interpreted summary.
