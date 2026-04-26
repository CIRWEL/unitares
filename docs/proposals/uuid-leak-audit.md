# UUID Leak Path Audit

**Status:** findings · **Author:** Claude_20260425 · **Date:** 2026-04-25
**Context:** Triggered by dialectic review of `list-agents-uuid-redaction.md`, which flagged that redacting `list_agents` alone may be insufficient — UUIDs leak from many other handlers.
**Closes:** N/A (informational; informs scope of KG `2026-04-20T00:57:45.655488`).

## Verdict

**Redaction-only approach does not close the bug.** Ten distinct cross-agent UUID leaks exist beyond `list_agents`. Most importantly, **`observe_agent` and `get_agent_metadata` accept a label and emit the resolved UUID** — so even with `list_agents` returning labels-only, an attacker can:

1. `list_agents()` → harvest labels
2. `observe_agent(label="X")` → get the UUID
3. `client_session_id="agent-<first12>"` → bind via PATH 1

The intermediate step (`list_agents` redaction) buys nothing.

## Inventory

| Handler | File:Line | UUID Field | Class | Notes |
|---|---|---|---|---|
| `list_agents` (lite) | `lifecycle/query.py:124` | `"id": agent_id` | redactable | label or `structured_id` would suffice for non-operator |
| `list_agents` (full) | `lifecycle/query.py:278, 287` | `"agent_id"`, `"parent_agent_id"` | redactable | also redact parent for non-self |
| `get_agent_metadata` | `lifecycle/query.py:136, 161` | `"agent_id"`, `"parent_agent_id"` | redactable | **resolves label → UUID and emits the UUID; this defeats `list_agents` redaction** |
| `observe_agent` | `dialectic/handlers.py:136` | `"agent_id": resolved_uuid` | redactable | **same defect — label IS a credential here** |
| KG `search`/`get` | `knowledge/handlers.py:1190, 1423` | `"_agent_id": discovery.agent_id` | redactable | replace with `display_name` + truncated hash; preserves attribution without UUID |
| `stuck_agents` | `lifecycle/stuck.py:515` | `"agent_id"` in array | redactable | `agent_name` fallback already present |
| `compare_agents` | `cirs/.../handlers.py:207, 264` | `"agent_id"` per row + outliers | redactable | use labels in comparison matrix |
| Dialectic session state | `dialectic/handlers.py:596-597, 1018` | `"paused_agent_id"`, `"reviewer_agent_id"` | load-bearing | needed for participants; gate by session-membership check (auth already at 220-305) |
| `get_governance_metrics` | `services/runtime_queries.py:180` | `"agent_uuid"` (conditional) | load-bearing | only emit when caller == agent or has explicit grant |
| `archive_orphan_agents` | `lifecycle/operations.py:662` | `r["id"][:12] + "..."` | gated-by-default | already truncated; no action |

## Key insight: label IS a credential

The dialectic review flagged this as a hidden assumption in the `list-agents-uuid-redaction.md` proposal:

> "Labels are not credentials — *only true if labels can't be uniquely resolved to UUIDs server-side by an unauthorized caller.* If `observe_agent(label=…)` does that resolution and acts, label *is* a credential by another name."

The audit confirms this is the operative case. `observe_agent` and `get_agent_metadata` both resolve label → UUID and emit the UUID in the response. The proposal's reliance on "label-based discovery still works for `observe_agent`/`dialectic`" was correct that the *function* still works, but missed that the function itself leaks the UUID.

## Strategic options

The original proposal addresses the **leak** half of the "leak + PATH 1 = hijack" chain. The audit shows the leak surface is 10x wider than scoped. Three plausible responses:

### Option A — Widen the redaction PR

Apply UUID redaction to all 10 surfaces in one PR or coordinated series. Each surface needs the operator gate (PR #187) and per-handler redaction logic. Estimated 5-7 PRs of work; touches dashboard, Discord bridge, ollama bridge, all of which use these handlers.

**Pro:** closes the leak as proposed.
**Con:** large surface change; high regression risk; consumer churn (every API consumer that reads `agent_id` fields needs to handle absence).

### Option B — Close PATH 1 instead

The bug is "leak + PATH 1 = hijack." Closing PATH 1 (the `agent-{uuid12}` prefix-bind at `src/mcp_handlers/identity/shared.py:139-166` that resolves UUID prefixes with no ownership proof) breaks the second half of the chain. UUIDs would still be enumerable, but couldn't be used to bind.

**Pro:** single-PR scope; surgical; doesn't break any consumer.
**Con:** the original KG discovery is tagged `unauth-leak` — the leak IS the bug, in the discovery filer's framing. Closing PATH 1 leaves the leak "morally" unfixed, even if exploitation is blocked.

### Option C — Both, in sequence

Close PATH 1 first (fast, low-risk, neutralizes the exploit). Then audit each leak surface and decide individually whether redaction is worth its cost. Treats the bug as "exploit chain" rather than "single leak point."

**Pro:** matches the actual threat model (the leak is only consequential because of PATH 1); allows leak fixes to be cost-justified one at a time.
**Con:** the leak surface keeps growing as new handlers are added; without the discipline of a redaction policy, drift continues.

## Recommendation

**Option C.** Land a PATH 1 ownership-proof PR first — it's the single load-bearing change that converts the bug from "two-call hijack" to "labels-visible inventory." After that, each redaction decision becomes a UX/design question (do we want consumers to see UUIDs?) rather than a security gate.

Specifically:
- **PR-next:** PATH 1 ownership proof. `agent-{uuid12}` binds only when paired with a continuity_token signed for that UUID, or when accompanied by `force_new=true`. Anything else → reject with a clear error message pointing at the canonical pattern.
- **Then:** revisit `list-agents-uuid-redaction.md` as a UX/scope decision, not a security gate. The operator-token plumbing in `unitares` PR #187 stands either way; it's useful for any "trusted infrastructure" carve-out.

PR #187 (operator header) and `unitares-discord-bridge` PR #12 (defensive empty-id handling) remain valuable independently of which strategy ships next — they're the substrate that any of these options would build on.

## Out of scope for this audit

- SessionStart hook hijack (KG `2026-04-20T00:09:51`) — separate fix in flight.
- `governance-lifecycle/SKILL.md` teaching the bare-UUID resume pattern — separate fix.
- Server-internal logs and audit trails — those don't surface to MCP callers.
- Discovery IDs and other non-UUID identifiers that happen to be in responses.
