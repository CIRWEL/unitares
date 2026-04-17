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
- **Secret redaction** — applied to every string field before serialization. Reuses the 5-pattern regex already shipped in `unitares-governance-plugin/scripts/_redact.py`.
- **Size cap** — 4KB per payload row. Individual text fields capped at 512 chars after redaction.
- **Opt-in per tool** — unlisted tools continue to record `{}`. Better conservative silence than overeager leaks.

### What this is NOT

- Not a full request log. The payload is a summary view, not a replay tape.
- Not a replacement for observability dashboards. `audit.tool_usage` is for offline analysis, not live operator feeds.
- Not a trust / surveillance signal. The data sits in the existing audit partition that operators already read.

## 3. Design

### 3.1 Where the change lands

- Modify: `src/services/tool_usage_recorder.py` — `record_tool_usage` gains a `payload` parameter, builds it from the tool's arguments via an allowlist dispatcher.
- Add: `src/services/_redact.py` — port of `unitares-governance-plugin/scripts/_redact.py`. Small module, duplicated rather than cross-repo-imported because the plugin and server should not hard-depend on each other.
- Add: `src/services/audit_payload_policy.py` — the allowlist and per-tool field rules. Kept as its own module so future tools can be onboarded without touching the recorder.
- Call sites: `src/mcp_server_std.py` (stdio dispatch, lines 448-463 per the earlier audit) and `src/services/http_tool_service.py` (HTTP dispatch, lines 76-86). Both already call `record_tool_usage` — pass the arguments dict through.

### 3.2 Allowlist — what gets captured

Per tool, named fields only. Everything else dropped.

| Tool | Captured fields | Notes |
|---|---|---|
| `process_agent_update` | `response_text`, `complexity`, `confidence`, `task_type` | `response_text` redacted + capped at 512 chars. Never capture `continuity_token` or `client_session_id`. |
| `onboard` | `name`, `model_type`, `client_hint`, `spawn_reason`, `force_new` | `continuity_token` and `agent_uuid` deliberately excluded (transport identity, not behavioral signal). |
| `identity` | `resume`, `force_new`, `model_type` | Same reasoning — exclude identity credentials. |
| `outcome_event` | `outcome_type`, `outcome_score`, `is_bad`, `detail` (redacted, capped at 512) | `detail` is operator-visible free-form — subject to full redaction pass. |
| `knowledge(action=...)` | `action`, `query` (redacted, capped at 256), `tags` | Don't capture full `content` blobs — too large, often contain user data. |
| `request_dialectic_review` | `reason` (redacted, capped at 512) | Reason text is the behavioral signal. |
| `submit_thesis` / `submit_antithesis` / `submit_synthesis` | `reasoning` (redacted, capped at 512), `agrees` (on synthesis) | Numeric / boolean fields pass through. |
| Anything else | `{}` | Default-closed. Onboarding a tool to payload capture is a deliberate act. |

Rationale: the fields captured are the ones downstream analysis would want — they're all behavioral claims an agent made. Transport and identity credentials are explicitly out.

### 3.3 Redaction

`src/services/_redact.py::redact_secrets(text: str | None) -> str` — mirrors the plugin's module. Five patterns:

- Anthropic API keys (`sk-ant-…`)
- OpenAI API keys (`sk-…` / `sk-proj-…`)
- GitHub tokens (`gh[pousr]_…`)
- AWS access keys (`AKIA…`)
- Generic Bearer tokens (`Bearer <40+ chars>`)

Applied to every string field in the allowlist BEFORE truncation (so a key near the boundary doesn't sneak past via slicing, same invariant the plugin already tested).

**Not tamper-proof.** An agent crafting its own secrets-that-don't-match-these-patterns can still land them in the payload. This is defense-in-depth against accidental leaks from tool output / env reflection, not a security boundary against a motivated adversary.

### 3.4 Size cap

Two enforcement points:

- Per-field truncation — `response_text` / `reason` / `detail` / `query` capped at their per-tool limits after redaction.
- Total payload size — if `len(json.dumps(payload))` > 4096, fall back to `{"_truncated": true, "fields_present": [...], "reason": "payload exceeded 4KB"}`. The list of field names preserves enough diagnostic signal without the content.

Default cap 4096 is chosen because payload partitions are monthly and row volume is dominated by tool_usage — this keeps per-row storage bounded and queryable. Tunable via `AUDIT_PAYLOAD_MAX_BYTES` env var for future tuning; not exposed as an MCP config.

### 3.5 Backward compatibility

Existing `{}` rows stay as they are. The recorder change is forward-only. Any reader doing `WHERE payload != '{}'` picks up the new rows and skips the old — consistent with how the other audit tables evolved when new fields were added.

No migration. No backfill. No schema change (the column exists already).

### 3.6 Testing

- Unit tests on the allowlist dispatcher — each tool's captured fields match the table in §3.2, each omitted field is absent, and unknown tools produce `{}`.
- Unit tests on redaction integration — a `process_agent_update` call with `response_text="sk-ant-api03-abc123DEF456ghi789JKL"` produces a payload where that substring does not appear.
- Size cap test — 10 KB of `detail` produces `{"_truncated": true, ...}`, not a 10 KB row.
- Integration test — dispatch a real `process_agent_update` through `record_tool_usage`, query the row back, assert shape.

Reuse the plugin's `test_redact.py` patterns (port them too or depend on the redaction module's own suite).

## 4. Rollout

One PR. One commit per file ideally. No staged rollout — the change is idempotent and the old rows are untouched.

1. Port `_redact.py` → `src/services/_redact.py` with accompanying tests.
2. Add `src/services/audit_payload_policy.py` with the allowlist.
3. Extend `record_tool_usage` to accept `arguments: dict` and compute the payload via the policy.
4. Update both call sites (stdio + HTTP) to pass arguments.
5. Full test run.

## 5. Security / privacy review

What gets captured that wasn't before:
- Agent self-descriptions of their own work (`response_text`)
- Stated complexity / confidence numbers
- Dialectic reasoning
- Knowledge-graph search queries
- Discovery notes
- Onboarding signals (name, model_type, client_hint)

What explicitly does NOT get captured:
- Continuity tokens
- Client session IDs
- Agent UUIDs (as arguments; the `agent_id` column already has them as identifiers, which is fine)
- Full knowledge-graph content bodies
- File contents, diffs, tool outputs
- Any argument on any tool not in §3.2

Redaction pass on every captured string before write.

The governance DB already contains agent identities, EISV state, dialectic content, and knowledge graph entries — this change does not expand the *categories* of data stored, just the *fidelity within existing categories*. Consistent with the existing audit posture.

## 6. Acceptance

- `audit.tool_usage.payload` is non-empty for every `process_agent_update`, `onboard`, `identity`, `outcome_event`, `knowledge`, `request_dialectic_review`, `submit_*` call
- A known secret injected into `response_text` does not appear in the corresponding payload row
- A 10 KB `detail` argument produces a truncation marker, not a 10 KB row
- Unit tests for the allowlist dispatcher, redaction integration, and size cap pass
- Existing `{}` rows are untouched

## 7. What this unblocks (not in scope here)

This spec has no opinion on what the populated data gets used for. That work lives in future specs:

- An `audit_trajectory` / calibration-drift view
- Cross-agent behavioral analysis
- Observer-vs-self audit tools

Those specs depend on this one. They are scoped separately so this change can ship without entangling their design questions.
