# list_agents UUID Redaction

**Status:** proposal — superseded in scope by [`uuid-leak-audit.md`](./uuid-leak-audit.md). The redaction-only approach as proposed does not close the bug; the audit found 9 other leak paths, including `observe_agent` and `get_agent_metadata` which resolve label → UUID and emit the UUID — defeating any `list_agents`-only redaction. Recommendation now is to close PATH 1 (the `agent-{uuid12}` prefix-bind) first, then revisit redaction as a UX/scope decision rather than a security gate.
**Author:** Claude_20260425 · **Date:** 2026-04-25
**Reviews:** [code-review](./list-agents-uuid-redaction.code-review.md) · [dialectic-review](./list-agents-uuid-redaction.dialectic-review.md) · [audit](./uuid-leak-audit.md)

## Council findings — required revisions

Two blocking issues from code review:

1. **`_is_operator_session` doesn't connect to any auth surface that exists.** `client_session_id` at handler entry is a transport fingerprint (IP:UA, MCP session header, or `agent-{uuid12}`), not a bearer token. The proposed env-var allowlist will never match. Fix requires adding an explicit `X-Unitares-Operator` header plumbed through `SessionSignals`, or wiring `oauth_client_id` from a bearer token. **Prerequisite header-plumbing PR before this one can ship.**
2. **Discord bridge HUD breaks silently after redaction.** `mcp_client.py:207` falls back to `id=""` when the field is missing, then calls `get_governance_metrics(agent_id="")` for every non-self agent. Fix must land in the same PR as the redaction.

Plus revisions from dialectic review:

3. **Split the operator tier.** `UNITARES_INFRA_TOKENS` (bearer-token plumbing) vs. substrate-earned recognition (Vigil/Sentinel/Steward). Don't conflate them in one allowlist.
4. **`parent_agent_id` redaction with `lineage_label` fallback.** Redacting `id` while leaving `parent_agent_id` is security theatre; redacting both without the label fallback erases lineage from the public surface.
5. **Coordination via server-side label resolution, not peer-visibility.** "Any bound caller sees other bound UUIDs" reintroduces the hijack as soon as any unprivileged agent onboards. The right primitive is purpose-scoped resolution at the server (which `dialectic`/`observe_agent` already do).
6. **Remove Vigil/Sentinel/Steward from the allowlist** — they don't call `list_agents` at all (verified).
7. **Cover `agent_id` in full-mode redaction** (not just `id`).
8. **Tests**: anonymous caller as default fixture, operator as opt-in via `monkeypatch.setenv`.
9. **Audit other UUID leak paths**: `get_agent_metadata`, KG `_agent_id` fields, dialectic transcripts, error messages. Redacting `list_agents` alone is not sufficient.
10. **Default-deny needs a startup-time assertion** that *some* operator is configured, or the failure mode is a config rollback that re-opens the bug.

---

## Original proposal follows.


**Closes:** KG `2026-04-20T00:57:45.655488` (high-severity, `council-review`)
**Adjacent:** KG `2026-04-20T00:09:51.214738` (SessionStart hook hijack), PATH 1 `agent-{uuid12}` bypass at `src/mcp_handlers/identity/shared.py:139-166`

## Problem

`handle_list_agents` (`src/mcp_handlers/lifecycle/query.py:32`) is decorated `register=False, rate_limit_exempt=True`. Any caller — including a fresh agent that has never onboarded and proven nothing — gets back every active agent's `id` (full UUID), `parent_agent_id`, status, label, and last-update.

Combined with the PATH 1 prefix bypass (where `client_session_id="agent-<first12>"` resolves by prefix scan with no ownership check), this is a two-call hijack:

1. `list_agents()` → harvest fleet UUIDs.
2. `<any tool>` with `client_session_id="agent-<first12 of victim UUID>"` → bind to victim identity.

Same anti-pattern as the SessionStart hook hijack, broader blast radius (fleet vs. one host), no LLM prompting required.

## Goals

- A pre-onboard caller cannot enumerate other agents' UUIDs.
- Legitimate consumers (Discord bridge HUD, dashboard, ollama bridge, resident agents Vigil/Sentinel/Steward) keep working.
- Caller can always see their own UUID (the `you: true` row).
- Label-based discovery (used by `observe_agent`, `dialectic`, label→UUID resolution in the bridge) still works without UUIDs.

## Non-goals

- Closing PATH 1 prefix-bind. That is its own fix (`require_uuid_proof` per identity ontology); this proposal makes it useless without already-known UUIDs.
- Closing the SessionStart hook menu. Already in flight per KG `2026-04-20T00:09:51`.
- Changing the dashboard/bridge auth model.

## Threat model — who can see what

| Caller class | What they see |
|---|---|
| Pre-onboard / unidentified | Labels, counts, status — **no UUIDs at all**. Still useful for `observe_agent(label=…)` and dialectic discovery. |
| Onboarded (own session bound) | Own UUID + `you:true`; other agents' UUIDs **redacted** (`id: "redacted"` or omitted; label/status retained). |
| Operator-tier (admin allowlist) | Full output, current behavior. |

## Mechanism — minimum viable gate

Reuse identity infrastructure already present:

1. **Determine caller class** at handler entry:
   - `caller_uuid = get_context_agent_id()` — None if pre-onboard.
   - `is_operator = _is_operator_session(arguments)` — see below.

2. **`_is_operator_session`**: a *new* helper, single source of truth.
   - Returns True if the caller's `client_session_id` matches any of:
     - csv env `UNITARES_OPERATOR_SESSION_TOKENS` (long random tokens; bridge/dashboard/ollama get one each via plist/secrets).
     - csv env `UNITARES_OPERATOR_AGENT_UUIDS` (resident agents Vigil/Sentinel/Steward listed by UUID — they earn operator status via substrate-anchored identity per `docs/ontology/identity.md`).
   - Empty allowlists default to **deny** (operators must be explicitly listed).

3. **Redact in the response builder**:
   - In both lite-mode and full-mode loops, when constructing the per-agent dict:
     - If `is_operator`: include `id` as today.
     - Elif `caller_uuid == agent_uuid`: include `id` (it's the caller's own).
     - Else: omit `id` and `parent_agent_id`; keep `label`, `status`, `purpose`, `updates`, `last`, `trust_tier`.
   - Add a top-level `redacted: true` flag on the response when any UUIDs were redacted, with `_redacted_message` explaining how to gain full visibility (operator token).

4. **Telemetry**: log a counter when redaction was applied, and when an unidentified caller hit the endpoint. No log spam — single counter per N calls.

## Consumer impact (verified)

| Consumer | Token? | Today | After |
|---|---|---|---|
| `unitares-discord-bridge` (`mcp_client.py:179`) | yes (deployment-side) | full UUIDs | full UUIDs (operator) |
| `dashboard/dashboard.js:846` | yes (admin path) | full UUIDs | full UUIDs (operator) |
| `scripts/client/ollama_bridge.py` | yes (operator) | full UUIDs | full UUIDs (operator) |
| Vigil/Sentinel/Steward | substrate-anchored UUID | full UUIDs | full UUIDs (operator-by-UUID) |
| Tests (`tests/helpers.py:317`) | n/a | full UUIDs | full UUIDs (test fixture seeds operator allowlist) |
| Fresh agent before onboard | none | full UUIDs | labels only |
| Onboarded agent | bound | full UUIDs | own UUID + others redacted |
| `dialectic`/`observe_agent` label resolution | bound (caller has identity) | full UUIDs | own UUID; resolves other agents by label, not UUID — already supported |

## Ontology alignment

Per `docs/ontology/identity.md`:
- "Name is cosmetic" — labels are not credentials, redacting UUIDs but exposing labels is consistent.
- "First MCP call is sole identity source" — pre-onboard callers have not declared identity; they have no claim to other agents' identifiers.
- Substrate-anchored agents (Lumen, residents) keep their cross-process continuity and operator status via the explicit allowlist, matching the ontology's earned-continuity carve-out.

## Out of scope (separate PRs)

- **PR2**: Rename `agent-{uuid12}` PATH 1 to require ownership proof. Once UUIDs aren't harvestable, the prefix bypass is far less useful, but it should still be closed.
- **PR3**: SessionStart hook dedupe + filter to caller's own session_id (KG `2026-04-20T00:09:51`).
- **PR4**: `governance-lifecycle/SKILL.md` — replace bare-UUID resume guidance with continuity-token/parent-id pattern.

## Test plan

- Unit: redaction matrix across `(operator | caller-self | other)` × `(lite | full)`. Verify `id` present iff allowed; label always present.
- Unit: `_is_operator_session` accepts allowlisted token, rejects empty/missing/wrong.
- Integration: harness the existing `tests/helpers.py:317` fixture to seed `UNITARES_OPERATOR_SESSION_TOKENS`; existing tests keep passing as operators.
- Regression: a fresh fixture ("anonymous caller") asserts `redacted=true` and absence of `id` fields.
- Negative: assert that PATH 1 prefix-bind still works (out of scope) but cannot be reached without already knowing the prefix.

## Open questions for council

1. **Allowlist shape.** `UNITARES_OPERATOR_SESSION_TOKENS` (csv of bearer tokens) vs. a header (`X-Unitares-Operator: <token>`) vs. `UNITARES_OPERATOR_AGENT_UUIDS` for resident agents. Token rotation story?
2. **Redaction granularity.** Omit `id` field entirely, or replace with `id: "redacted"` (telemetry-friendlier but client churn)?
3. **Default deny vs. log mode.** Mirror `UNITARES_IDENTITY_STRICT={log,enforce}` so we can canary in `log` mode for one release? Memory note `feedback_design-doc-council-review.md` cautions against over-engineering, but identity ontology hist had recent rollouts via log-mode.
4. **`parent_agent_id`.** This is a UUID too — redact it for non-operators, since it leaks lineage UUIDs of agents the caller has no relationship to.
5. **Lineage for forked agents.** Should a child see its parent's UUID without operator status? Today it does; under this proposal it would not unless caller has parent_agent_id stored locally. Probably acceptable since the hook is the canonical disclosure path.
