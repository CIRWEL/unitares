---
name: Audit Payload Capture
description: Populate audit.tool_usage.payload with tool arguments under a narrow field allowlist, with secret redaction and per-row size cap. Today every row's payload is {}; this lands the data so later audit / calibration / observation work has something to read.
status: Draft
author: Kenny Wang
date: 2026-04-17
---

# Audit Payload Capture — Design Spec

## 1. Problem

`audit.tool_usage` records every MCP tool call — agent_id, tool_name, session_id, timestamp, latency, success, error_type — and has since 2026-04-17 morning (commits `9c64e8fa` HTTP, `a3e672f9` stdio). The `payload` column exists and is populated with `json.dumps({})` on every insert. Nothing actually writes tool arguments.

This makes the table useful for *tool-call rate and timing* analysis but blind to *what agents claimed*. Any downstream consumer that wants to compare self-reported complexity/confidence against observed outcomes — calibration audits, drift detection, trajectory comparison — has no window into the self-report half of the gap.

This is the minimal change. No audit tool, no calibration delta, no dashboard surface — just land the data so later specs have something to query.

## 2. Approach

Capture a **narrow, allowlisted slice** of each tool's arguments into `audit.tool_usage.payload`, subject to:

- **Field allowlist per tool** — not "all arguments." Arguments that are secrets (tokens), transport artifacts (session IDs), or too free-form to fit in 4KB (large JSON blobs) are excluded at source.
- **Recursive secret redaction** — applied to every string in captured values (top-level fields and list/dict elements) before serialization.
- **Size cap** — 4KB per payload row, measured as UTF-8 byte length of the serialized JSON. Individual text fields capped at 512 bytes (not chars) after redaction.
- **Whole-row fallback** on overflow — if the aggregate serialized payload exceeds the cap, the entire row is replaced by a marker object. No partial payloads.
- **Opt-in per tool** — unlisted tools continue to record `{}`. Better conservative silence than overeager leaks.

### What this is NOT

- Not a full request log. The payload is a summary view, not a replay tape.
- Not a replacement for observability dashboards. `audit.tool_usage` is for offline analysis, not live operator feeds.
- Not a trust / surveillance signal. The data sits in the existing audit partition that operators already read.
- **Not resistant to a motivated agent adversary.** Regex redaction catches accidental leakage classes only. Out-of-band secret channels — whitespace insertion (`sk-a nt-...`), case variation (`SK-ANT-...`), unicode lookalikes (Cyrillic `а`), base64-wrapped secrets, chunking across fields, non-English high-entropy strings — are NOT defended against. An adversarial agent that wants to leak can.

## 3. Design

### 3.1 Where the change lands

- Modify: `src/services/tool_usage_recorder.py` — `record_tool_usage` gains an `arguments` parameter, builds the payload from it via the allowlist policy.
- Add: `src/services/_redact.py` — port of `unitares-governance-plugin/scripts/_redact.py` with expanded pattern set (see §3.3). Small module, duplicated rather than cross-repo-imported because the plugin and server should not hard-depend on each other.
- Add: `src/services/audit_payload_policy.py` — the allowlist and per-tool field rules. Its own module so future tools can be onboarded without touching the recorder.
- Call sites: `src/mcp_server_std.py` (stdio dispatch, lines 448-463) and `src/services/http_tool_service.py` (HTTP dispatch, lines 76-86). Both already call `record_tool_usage` — pass the arguments dict through.

**Scope note on `session_id`:** `record_tool_usage` today does not pass `session_id` to `append_tool_usage_async` either — that column in `audit.tool_usage` stays NULL from this path. This spec does not fix that. Either (a) thread `session_id` through in the same PR as a trivial follow-on, or (b) leave it for a later PR and accept that downstream queries over `(agent_id, session_id, ts)` aren't possible until then. Recommend (a) — 1-line change at the same call sites.

### 3.2 Allowlist — what gets captured

Per tool, named fields only. Everything else dropped.

| Tool | Captured fields | Notes |
|---|---|---|
| `process_agent_update` | `response_text`, `complexity`, `confidence`, `task_type` | `response_text` redacted + capped at 512 bytes. Never capture `continuity_token` or `client_session_id`. |
| `onboard` | `name`, `model_type`, `client_hint`, `spawn_reason`, `force_new` | `continuity_token` and `agent_uuid` deliberately excluded (transport identity, not behavioral signal). |
| `identity` | `resume`, `force_new`, `model_type` | Same reasoning — exclude identity credentials. |
| `outcome_event` | `outcome_type`, `outcome_score`, `is_bad` | `detail` intentionally **not captured**. It is operator-authored free-form that has historically carried pasted tokens, stack traces, file paths with env values, and UUIDs. Safer to drop it than to defend it. If downstream analysis later needs detail content, a separate gated audit surface can be added. |
| `knowledge(action="search")` | `action`, `query` (redacted, capped at 256 bytes), `tags` (each element redacted) | Search-time signal. |
| `knowledge(action="store")` | `action`, `summary` (redacted, capped at 512 bytes), `tags` (each element redacted), `discovery_type` | Store-time behavioral signal lives in `summary`, not `query`. |
| `knowledge(action=...)` other | `action` only | Default-closed for other actions until each is reviewed. |
| `request_dialectic_review` | `reason` (redacted, capped at 512 bytes) — **sentinel-drop** | The handler defaults `reason` to the literal string `"Dialectic review requested"` when the caller omits it. Policy MUST detect this exact sentinel and emit `{}` instead. Otherwise every dialectic request produces a non-signal row. |
| `submit_thesis` / `submit_antithesis` / `submit_synthesis` | `reasoning` (redacted, capped at 512 bytes), `agrees` (on synthesis) | Numeric / boolean fields pass through. |
| Anything else | `{}` | Default-closed. Onboarding a tool to payload capture is a deliberate act. |

Rationale: the fields captured are the ones downstream analysis would want — they're all behavioral claims an agent made. Transport and identity credentials are explicitly out.

### 3.3 Redaction

`src/services/_redact.py::redact_secrets(value) -> value` — mirrors the plugin's module, expanded. Works recursively on strings, lists, dicts; non-string scalars pass through unchanged.

Pattern set:

- Anthropic API keys (`sk-ant-…`)
- OpenAI API keys (`sk-…` / `sk-proj-…`)
- GitHub tokens (`gh[pousr]_…`, `github_pat_…`)
- AWS access keys (`AKIA…`)
- Stripe keys (`sk_live_…`, `rk_live_…`)
- Slack tokens (`xox[bpoas]-…`)
- Generic Bearer tokens (`Bearer <40+ chars>`)
- JWTs (`eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`)
- PEM private key headers (`-----BEGIN [A-Z ]*PRIVATE KEY-----` through the matching `-----END … PRIVATE KEY-----`)
- Connection strings with inline credentials (`(postgres|postgresql|mysql|mongodb|redis|amqp)://[^:@\s/]+:[^@\s/]+@[^\s/]+`)

Applied **before** any truncation — a key near a byte boundary should not sneak past via slicing. Applied **recursively** into list and dict elements (critical for `tags`, which is a list).

**Not tamper-proof.** See §2 "What this is NOT" for the bypass classes we deliberately do not defend against.

**High-redaction-ratio stubs.** If after redaction more than 50% of the original bytes of a single field were replaced by `[REDACTED:…]` markers, the field is dropped entirely and the payload gains `{"<field>_fully_redacted": true}` instead. A stub of `"[REDACTED] ... [REDACTED] ... [REDACTED]"` looks like signal but isn't — better to explicitly mark it suppressed.

### 3.4 Size cap

Three enforcement points:

- **Per-field byte truncation.** `response_text` / `reason` / `reasoning` / `summary` / `query` capped at their per-tool byte limits (`.encode("utf-8")` length). Truncation runs AFTER redaction so redaction always sees the original content.
- **Aggregate payload byte cap.** `len(json.dumps(payload).encode("utf-8"))` compared to `AUDIT_PAYLOAD_MAX_BYTES` (default 4096).
- **Whole-row fallback on overflow.** If the aggregate exceeds the cap, the entire payload is replaced by a single marker:
  ```json
  {"_truncated": true, "fields_present": ["response_text", "complexity", ...], "reason": "payload exceeded 4096 bytes"}
  ```
  No partial content survives. The list of field names gives enough diagnostic signal to know which tool path ran without preserving any potentially-sensitive per-field content.

Byte-counting (not char-counting) matters: Python's `len(str)` returns chars, and 4096 chars can be 16 KB of UTF-8 for non-ASCII input. Always measure bytes.

`AUDIT_PAYLOAD_MAX_BYTES` env var is tunable for future operators; not exposed as an MCP config.

### 3.5 Backward compatibility

Existing `{}` rows stay as they are. The recorder change is forward-only. No existing reader filters on `payload != '{}'` — confirmed by grep. Readers that appear later can use that predicate to distinguish old rows from new.

No migration. No backfill. No schema change (the column exists already).

### 3.6 Testing

Required:

- **Allowlist dispatcher.** Each tool's captured fields match the table in §3.2 exactly; each omitted field is absent; unknown tools produce `{}`; the `request_dialectic_review` sentinel-drop fires when `reason == "Dialectic review requested"` and suppresses otherwise.
- **Redaction — base patterns.** Each of the 10 pattern classes is matched and replaced by `[REDACTED:<label>]`.
- **Redaction — recursion.** `tags=["sk-ant-api03-..."]` produces tags with the string redacted, not the literal secret in the list element.
- **Redaction — high-ratio stub suppression.** A field where more than half the bytes are redaction markers becomes `<field>_fully_redacted: true` instead of a mangled stub.
- **Size cap — UTF-8 byte boundary.** A 2000-char Cyrillic string (~4000 UTF-8 bytes) truncates at byte 512 after the redaction pass, not at char 512.
- **Size cap — aggregate overflow whole-row fallback.** Stack up allowlisted fields to exceed 4096 bytes; assert the payload row is exactly `{"_truncated": true, "fields_present": [...], "reason": "..."}` and not a partial.
- **Non-secret legitimate content preservation.** A 4000-char `response_text` that is clean prose (no pattern matches) passes through truncated to 512 bytes but not mangled.
- **Integration.** Dispatch a real `process_agent_update` through `record_tool_usage`, query the row back, assert shape.

Port the plugin's `test_redact.py` verbatim (adjust import path), then add the new cases above.

## 4. Rollout

One PR. One commit per logical step.

1. Port + expand `_redact.py` → `src/services/_redact.py` with full test suite (base + recursion + high-ratio stub).
2. Add `src/services/audit_payload_policy.py` with the allowlist.
3. Extend `record_tool_usage` to accept `arguments: dict` and compute the payload via the policy. Thread `session_id` at same call sites (scope note from §3.1).
4. Update both call sites (stdio + HTTP) to pass `arguments` and `session_id`.
5. Full test run.

## 5. Security / privacy

### What gets captured that wasn't before

- Agent self-descriptions of their own work (`response_text`)
- Stated complexity / confidence numbers
- Dialectic reasoning
- Knowledge-graph search queries and store summaries
- Discovery tags
- Onboarding signals (name, model_type, client_hint, spawn_reason)

### What explicitly does NOT get captured

- Continuity tokens
- Client session IDs
- Agent UUIDs (as arguments; the `agent_id` column already has them as identifiers, which is fine)
- Full knowledge-graph content bodies
- `outcome_event.detail` free-form text
- File contents, diffs, tool outputs
- Any argument on any tool not in §3.2

### Operator-surface scope

- **Backup surface.** `audit.tool_usage` is included in the standard `~/backups/governance/` pg_dump rotation. Backup trust equals DB trust — if the backup location is operator-local (same filesystem or encrypted external), this is consistent with existing audit posture. If it's off-device, treat the payload rows with the same sensitivity as the rest of the audit partition.
- **Dashboard surface.** Any operator with read access to `audit.tool_usage` (currently: any psql-capable operator on the host) can read redacted payload rows. This is intended and consistent with pre-existing `audit.tool_usage` visibility.
- **Partition retention.** `audit.tool_usage` partitions are monthly per existing schema. Retention follows the standard audit partition drop policy — this change does not alter it.

### Threat model — what this DOES and does NOT defend against

Defends against: accidental leakage of well-known secret tokens (API keys, bearer tokens, DB credentials, JWTs, PEM private keys) that land in captured fields via tool output reflection, environment variable echoes, or operator paste.

Does NOT defend against: a motivated agent crafting secrets to evade regex (whitespace/case/unicode bypass, chunking, base64 wrapping, non-English high-entropy strings, custom tokenization). See §2 "What this is NOT."

The governance DB already contains agent identities, EISV state, dialectic content, and knowledge graph entries — this change does not expand the *categories* of data stored, just the *fidelity within existing categories*. Consistent with the existing audit posture.

## 6. Acceptance

- `audit.tool_usage.payload` is non-empty for every `process_agent_update`, `onboard`, `identity`, `outcome_event`, `knowledge` (search/store), `request_dialectic_review` (when reason != sentinel), and `submit_*` call
- Redaction test suite (base + recursion + high-ratio stub + byte-boundary) passes
- 10 KB payload produces exactly the `{"_truncated": true, "fields_present": [...], "reason": "..."}` marker, not partial content
- UTF-8 multibyte input truncates at byte boundary, not char boundary
- `request_dialectic_review` with default `reason` produces `{}`, not a non-signal row
- Existing `{}` rows are untouched
- `session_id` column is populated for new rows (if §3.1 scope note option (a) taken)

## 7. What this unblocks (not in scope here)

This spec has no opinion on what the populated data gets used for. That work lives in future specs:

- An `audit_trajectory` / calibration-drift view
- Cross-agent behavioral analysis
- Observer-vs-self audit tools

Those specs depend on this one. They are scoped separately so this change can ship without entangling their design questions.
