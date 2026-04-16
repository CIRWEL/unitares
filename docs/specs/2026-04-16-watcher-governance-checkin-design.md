---
name: Watcher Governance Check-in
description: Give Watcher a persistent governance identity, periodic check-ins, and a resolution audit trail so finding judgments are tracked across sessions and agents.
status: Draft
author: Kenny Wang
date: 2026-04-16
---

# Watcher Governance Check-in — Design Spec

## 1. Problem

Watcher detects code issues and surfaces them to Claude Code agents, but it has no governance presence. It operates outside the EISV trajectory system — no identity, no check-ins, no audit trail for how its findings are handled.

Three signals are lost:

1. **Dismissals have no memory.** When an agent dismisses a finding, the status flips in findings.jsonl. After 7 days, `compact_findings` drops it. If the same pattern re-fires on different code, there's no record of the prior dismissal or whether it was correct.

2. **Agent judgment is unaudited.** An agent's dismiss/resolve decision is a governance-relevant action — overriding a sensor — but it's not tracked as a governance event. If an agent systematically dismisses findings that turn out to be real, there's no way to detect that pattern.

3. **No continuity.** Watcher's state lives in gitignored local files. Its operational history is only in commit messages and log files. Nothing persists in governance across sessions.

## 2. Approach

**Approach C: Check-in + resolution audit trail.**

Watcher gets a persistent identity and periodic check-ins (matching Vigil's model). Additionally, when `--resolve` or `--dismiss` runs, a governance event records who judged the finding and how. This captures the judgment audit trail without flooding governance with every scan.

Key insight: *findings* are high-volume operational data (dozens per session), but *judgments on findings* are low-volume governance data (a few per session). Track the judgments.

### What this enables later (not in scope)

- **Cross-agent calibration queries:** "Which agent UUIDs dismiss findings that later re-fire?" This is a read query over the resolution events this design produces. The analysis layer is future work; this spec lays the data foundation.
- **Full finding mirroring (Approach B):** If every finding needs to be in governance, promote the finding pipeline to post events. Extending C to B is additive, not a rearchitecture.

## 3. Design

### 3.1 Identity

Watcher uses `SyncGovernanceClient` (already imported) for identity. It does NOT subclass `GovernanceAgent` (that's an async base class for long-running processes; Watcher is a sync CLI script).

**Session file:** `.watcher_session` in the repo root (same JSON format as `.vigil_session`):

```json
{
  "client_session_id": "...",
  "continuity_token": "...",
  "agent_uuid": "..."
}
```

**Identity resolution** runs once per process invocation, early in `main()`, before dispatching to the subcommand. All code paths (scan, surface, resolve, dismiss) share the same resolved identity for that invocation. Three-step, same as Vigil:

1. **Token resume** (strong): if `.watcher_session` has a `continuity_token`, call `client.identity(continuity_token=..., resume=True)`
2. **Name resume** (weak): call `client.identity(name="Watcher", resume=True)`
3. **Fresh onboard**: call `client.onboard("Watcher", spawn_reason="resident_observer")`

Result stored in a module-level `_watcher_identity` dict so all code paths can reference `_watcher_identity["agent_uuid"]`.

**Graceful degradation:** If identity resolution fails (governance down, timeout, etc.), `_watcher_identity` stays `None`. Scanning proceeds normally. Check-in and resolution events are skipped. A warning goes to the log. The scan is the primary job — a governance outage must not silence the bug detector.

**Why this is low-risk for identity bugs:** Watcher is the simplest identity case — one stable name, always "Watcher", no parallel instances, no model-type ambiguity. The ghost proliferation patterns (cold-start without trajectory_signature, stateless-client `mcp_YYYYMMDD` fallback) came from agents that didn't declare a stable name. Watcher always does.

### 3.2 Check-in

**Trigger:** The `UserPromptSubmit` hook already runs `--surface-pending`. The check-in logic runs at the end of `surface_pending()` internally — one process invocation, one identity resolution, surface then check in.

No new CLI flag needed. The check-in is an internal step of `--surface-pending`, not a separate command.

**What the check-in reports** (`response_text`):

```
Watcher: 12 scans, 3 new findings (1 high, 2 medium), 
1 confirmed, 0 dismissed, 4 unresolved
```

Built from:
- **Scan counter:** incremented by `scan_file()`, persisted in `data/watcher/state.json`, reset after each check-in
- **Finding stats:** read from `findings.jsonl` at check-in time — counts by status, by severity

**EISV inputs:**

| Field | Derivation |
|-------|-----------|
| `complexity` | Scales with active (open+surfaced) finding count. 0 findings → 0.1. 10+ findings → 0.6. Linear interpolation, capped. |
| `confidence` | `confirmed / (confirmed + dismissed)` over a rolling window (last 30 days of findings). Warmup: needs 5+ resolutions before the ratio is used; defaults to 0.7 during warmup. |
| `response_mode` | `"compact"` |

**Idle check-in:** If nothing happened since the last check-in (no scans, no resolution changes), the check-in is a heartbeat: `"Watcher idle"` with complexity 0.05, confidence 0.9. This keeps the EISV trajectory alive without pretending there was activity.

**Cadence:** Once per `UserPromptSubmit` chime — roughly per-turn during active coding, so every few minutes. This matches Vigil's ~30min cadence in spirit (low-overhead periodic signal) at higher frequency because Watcher is event-driven.

### 3.3 Resolution audit trail

When `--resolve` or `--dismiss` runs successfully (finding found, status updated in findings.jsonl), a governance event is also posted.

**CLI change:** `--resolve` and `--dismiss` gain an optional `--agent-id` argument:

```bash
python3 agents/watcher/agent.py --resolve ff27c1b2 --agent-id a1b2c3d4-...
```

The calling agent passes its own governance UUID. If omitted (manual CLI use), `resolved_by` is `null`.

**Event payload** (via the existing `post_finding` helper from `agents/common`):

```python
post_finding(
    event_type="watcher_resolution",
    severity=finding["severity"],
    message=f"[{action}] {pattern} {file}:{line} — {hint}",
    agent_id=WATCHER_AGENT_UUID,       # Watcher's own UUID
    agent_name="Watcher",
    fingerprint=finding["fingerprint"],
    extra={
        "action": "confirmed" | "dismissed",
        "pattern": finding["pattern"],
        "file": finding["file"],
        "line": finding["line"],
        "violation_class": finding["violation_class"],
        "resolved_by": agent_id_arg,    # resolver's UUID or null
    },
)
```

**Graceful degradation:** If governance is down when `--resolve`/`--dismiss` runs, the local findings.jsonl update still happens (it's just a file write). The governance event is best-effort — log a warning and move on.

**Surface hook update:** The `<unitares-watcher-findings>` block that SessionStart/UserPromptSubmit injects should update the resolve/dismiss syntax hint to include `--agent-id`:

```
Resolve: python3 agents/watcher/agent.py --resolve <fingerprint> --agent-id <your-uuid>
Dismiss: python3 agents/watcher/agent.py --dismiss <fingerprint> --agent-id <your-uuid>
```

### 3.4 What stays the same

- **Scan pipeline:** `--file`, pattern library, model calls, dedup, findings.jsonl append. Untouched.
- **Severity routing:** low/medium stay local, high/critical go to event stream via `post_finding`. Unchanged.
- **Surface hooks:** SessionStart `--print-unresolved`, UserPromptSubmit `--surface-pending`. Same behavior, check-in appended to the end of `surface_pending()`.
- **Lifecycle commands:** `--sweep-stale`, `--compact`, `--list-findings`. All local operations, unchanged.
- **Ollama fallback:** governance down → direct Ollama for model calls. Unchanged.
- **`GovernanceAgent` base class:** Watcher does NOT subclass it. Stays a sync CLI script.
- **Finding data model:** `Finding` dataclass, findings.jsonl schema — no new fields.

## 4. Data flow

```
Agent edits code
    → PostToolUse hook fires
    → watcher --file <path>
        → identity resolution (resume or onboard)
        → scan → findings.jsonl (local)
        → high/critical → event stream (existing)

Agent submits prompt
    → UserPromptSubmit hook fires
    → watcher --surface-pending
        → identity resolution (resume)
        → print open findings to session context
        → check in to governance (new)
            → response_text: scan/finding summary
            → complexity/confidence from finding stats

Agent acts on finding
    → watcher --resolve <fp> --agent-id <uuid>
        → identity resolution (resume)
        → update findings.jsonl status (existing)
        → post watcher_resolution event (new)
            → carries: pattern, disposition, resolver UUID
```

## 5. Testing

- **Identity:** resume via token works, resume via name works, fresh onboard works, governance-down skips gracefully
- **Check-in:** summary text correctly reflects findings.jsonl state, complexity/confidence compute correctly, idle heartbeat fires when nothing changed
- **Resolution events:** `--resolve` posts `watcher_resolution` with `action=confirmed`, `--dismiss` posts with `action=dismissed`, `--agent-id` is carried through, missing `--agent-id` results in `null`, governance-down doesn't break local status update
- **Integration:** full cycle — scan a file, surface findings, resolve one, check in, verify EISV trajectory exists for Watcher in governance

## 6. Migration

No migration needed. Watcher currently has no governance identity. First invocation after this change will fresh-onboard and create the identity. Existing findings.jsonl is unaffected — no schema change.

The `.watcher_session` file will be created on first run. Add it to `.gitignore` alongside `.vigil_session`.
