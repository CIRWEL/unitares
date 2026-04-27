# GPT Review — Refined Phase-5 Evidence Contract

**Reviewer:** GPT (via Kenny, 2026-04-26)
**Spec:** `refined-phase-5-evidence-contract.md`
**Question framed:** B vs C, given user lean toward C.

---

## Verdict

> Pick C, with a narrow compatibility allowance for B later if needed.

## Canonical contract should be structured API, not prose parsing

```json
process_agent_update({
  "response_text": "...",
  "complexity": 0.4,
  "confidence": 0.8,
  "recent_tool_results": [
    {
      "prediction_id": "...",
      "kind": "command",
      "tool": "pytest",
      "exit_code": 0,
      "summary": "tests passed",
      "observed_at": "..."
    }
  ]
})
```

## Rules

- No A. Regex over prose creates hidden calibration behavior.
- `recent_tool_results` is self-reported evidence, not ground truth unless server can corroborate it.
- Link to explicit `prediction_id`; only fall back to "last prediction" when unambiguous.
- Unknown fields forbidden via nested Pydantic model.
- Server emits `outcome_event` only after validation, and stores provenance as `source="agent_reported_tool_result"`.

## Bridge

B can be a bridge for clients that cannot change tool schema, but it should parse into the same internal model and be marked compatibility-only.

---

## Spec author's notes

GPT's review converges with the dialectic agent on every architectural choice that matters:
- **C as canonical** (vs hybrid)
- **No A** (vs prose-regex)
- **Provenance field** (GPT's `source=...`, dialectic's `verification_source=...` — same idea, same forward path to server-verified outcomes)
- **B as compat bridge** parsing into the same internal model

GPT's specific addition the dialectic agent didn't surface: **`extra="forbid"` strict nested Pydantic** instead of the existing `Dict[str, Any]` pattern. The spec adopts this — it's a deliberate choice toward stricter contracts. Documented inline.

GPT's framing of "unknown fields forbidden" + "stores provenance" is the cleanest single-paragraph summary of the contract; the spec's design section §1 follows it directly.
