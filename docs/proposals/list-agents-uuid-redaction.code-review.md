# Code Review — list_agents UUID Redaction

**Reviewer:** feature-dev:code-reviewer (subagent) · **Date:** 2026-04-25
**Proposal:** `list-agents-uuid-redaction.md`
**Verdict:** needs-revisions (blocking)

## Critical — `_is_operator_session` is structurally unsound

`_is_operator_session` checks `client_session_id`, but `client_session_id` at handler entry is **not a bearer token** — it is an IP:UA fingerprint, MCP session header, or `agent-{uuid12}` prefix string.

Trace: the `client_session_id` in context (set by `set_session_context` in `context.py`) is whatever `_session_id_from_ctx()` or the ASGI middleware resolved — values like `mcp:abc123`, `34.162.136.91:0`, or `agent-5e728ecb1234`. None of these are the long random operator tokens the proposal describes. The proposed `UNITARES_OPERATOR_SESSION_TOKENS` csv would be compared against transport fingerprints, not application-level bearer tokens. **They will never match.**

There is no bearer token flowing into `client_session_id` today. The `oauth_client_id` field in `SessionSignals` is the only place an OAuth client identity could plausibly appear, but nothing currently sets this for the bridge or dashboard. The bridge calls `list_agents` as a plain MCP tool call with no admin header; it identifies itself only by its session key, which is derived from transport signals.

To make `_is_operator_session` actually work, the proposal must either:

- Add a new auth header (e.g. `X-Unitares-Operator`) that the bridge/dashboard send, plumbed into `SessionSignals`, and read at handler entry via `get_session_signals()` — not via `client_session_id`. **(Recommended.)**
- Or gate on `oauth_client_id` from a bearer token on the request, after adding bearer-token issuance to the bridge deployment.

Confidence: 100.

## Critical — Discord bridge HUD breaks silently after redaction

`unitares-discord-bridge/src/bridge/mcp_client.py:207-209`:

```python
agent_id = item.get("agent_id") or item.get("id", "")
```

After redaction, non-operator callers get no `id` field in lite mode. The fallback resolves to `""`. Every non-self agent in the HUD list gets `id=""`, which then goes into `fetch_metrics` at line 222 as the `agent_id` parameter — silently requesting metrics for `""`. The bridge won't crash; it will return an empty metrics dict for every agent and show a HUD with labels but no EISV state.

This is distinct from the open question about omitting vs. `"redacted"` — even if you set `id: "redacted"`, the bridge then fires `get_governance_metrics(agent_id="redacted")` for every row. The bridge normalization needs to be updated **in the same PR** to handle missing/redacted IDs explicitly.

Confidence: 95.

## Per-question findings

### 1 · `_is_operator_session` mechanism

Broken as written (see Critical above). `get_context_client_session_id()` returns a transport-derived session key, not a bearer token. A fresh agent using IP:UA fingerprint would get a session key like `34.162.136.91:0`; comparing that to a csv of long random operator tokens is an identity-category mismatch that will always return False.

### 2 · Consumer impact verification

| Consumer | Status | Notes |
|---|---|---|
| `dashboard/dashboard.js:846` | confirmed | calls `agent(action='list')` → routes through `handle_agent` (consolidated.py:122) → `handle_list_agents` |
| `unitares-discord-bridge/src/bridge/mcp_client.py:178-213` | calls `list_agents` directly (not `agent`), lite mode | bug noted above |
| `scripts/client/ollama_bridge.py:101-103` | calls `agent(action='list')` via smolagents wrapper | ollama is not a resident agent and has no privileged session — would be redacted under proposal; mechanism to grant operator status is the same broken token comparison |
| `tests/helpers.py:317` | `patch_lifecycle_server` patches `mcp_server` — does NOT seed env vars | proposal's "seed `UNITARES_OPERATOR_SESSION_TOKENS`" needs explicit `monkeypatch.setenv` |
| **Vigil/Sentinel/Steward** | **none of them call `list_agents`** | confirmed by full read of both implementations. Drop from allowlist table entirely. |

### 3 · UUID escape sites in `query.py`

The proposal covers the main loop correctly but **misses full-mode line 277-289**, where the key is `"agent_id"` not `"id"`. The proposal's redaction spec says nothing about `agent_id`. Full mode would still leak UUIDs.

Confidence: 90.

### 4 · Response-shape break

Dashboard's `loadAgents` uses `agent_id` (line 1041: `a.agent_id === pinnedId`) for pinned-agent persistence. Lite mode returns `id`, full mode returns `agent_id`. This is a pre-existing field-name mismatch unrelated to this proposal, but the proposal's redaction of `id` without also handling `agent_id` in full mode creates **asymmetric breakage**: lite-mode dashboard works, full-mode dashboard's pinned-agent state breaks for all non-operator dashboards.

### 5 · PATH 1 surviving leak vectors

The claim that "UUIDs aren't harvestable" after this fix is overstated. Survivors:

- `get_agent_metadata(target_agent=<label>)` returns full metadata including the resolved UUID.
- KG notes contain `agent_id` fields. Any caller can search KG and extract UUIDs from note metadata.
- `get_governance_metrics(agent_id=<uuid>)` — if you already know a UUID fragment, you can probe it.
- Dialectic participant lists — gap acknowledged in proposal.
- `get_governance_metrics()` with no args returns the caller's own UUID. Not cross-agent, but confirms the pattern.

### 6 · Testability

`patch_lifecycle_server` is the right fixture to extend. Test matrix is achievable — add `monkeypatch.setenv("UNITARES_OPERATOR_SESSION_TOKENS", "mytoken")` per test, and patch `get_context_client_session_id` to return `"mytoken"` — but **only after fixing the mechanism so `_is_operator_session` reads a header or env var that actually correlates to something the client controls.** Without the mechanism fix, all "operator grants full UUIDs" tests pass vacuously.

## Required changes before implementation

1. **Redesign `_is_operator_session`** to key on an explicit request-level credential (new `X-Unitares-Operator` header plumbed through `SessionSignals`, or `oauth_client_id`), not `client_session_id`.
2. **Cover `agent_id`** (not just `id`) in the full-mode redaction at lines 277-289.
3. **Update Discord bridge `fetch_agents`** to handle absent/redacted `id` gracefully (skip or mark as unresolvable, don't pass `""` to `get_governance_metrics`) — same PR.
4. **Remove Vigil/Sentinel/Steward** from the allowlist table — they don't call this endpoint.
5. **Update test plan** to use `monkeypatch.setenv` explicitly; `patch_lifecycle_server` does not handle it automatically.
