# Dialectic Review — Refined Phase-5 Evidence Contract

**Reviewer:** `dialectic-knowledge-architect` subagent
**Date:** 2026-04-26
**Spec:** `refined-phase-5-evidence-contract.md`
**Question framed:** B (structured evidence block in response_text) vs C (tool-call introspection field). User leaning C.

---

## Steel-man for C (Tool-call introspection field)

C's strongest case isn't truthfulness — it's **schema-enforced decomposability**. A structured field forces the agent to factor its claim into named slots (`tool`, `exit_code`, `summary`), which means downstream calibration code never has to parse free-text. That's not just ergonomic — it eliminates an entire class of silent-drift failures where B's regex parser changes meaning under a model upgrade. C also makes the contract **inspectable at the API boundary**: the schema itself is the documentation, versionable, and lintable. B's `<eisv-evidence>` block is invisible to anyone who hasn't read the parser source. For a governance system whose whole pitch is legibility, C wins on auditability of the *contract*, even if not of the *claim*.

## Counter to C (and to B)

**On Q1 — honesty.** You're right: both rely on self-report. C is not more truthful; it's more *legible when truthful and more legible when lying*. That second property matters. A fabricated structured row is easier to cross-check against server-visible signals (was there actually a tool call in this session?) than fabricated prose. So C buys *forensic* honesty, not *intrinsic* honesty.

**On Q2 — noise.** Your instinct is correct and important. C's field-shape invites completionism ("fill the array"); B's block-shape invites deliberation ("is this worth a block?"). C will have higher recall and lower precision; B the inverse. For a *signal-starved* calibrator, C's recall advantage is real. For a calibrator that needs to *not poison* itself, B's precision is real. Today you're starved → C. Six months from now → possibly B.

**On Q3 — prediction_id realism.** This is the load-bearing weakness of both. Requiring agents to register-then-verify across two MCP calls is a fiction unless (a) the agent framework persists prediction state, or (b) the server can reconstruct the pairing from session continuity. Most agents won't carry prediction_id forward. The contract will be honored ~10% of the time, and the 10% will be selection-biased toward agents that already calibrate well — making your tactical channel look better than reality.

**On Q4 — hybrid.** Worst of both. Two surfaces drift; precedence rules become folklore; reviewers don't know which to trust. Pick one.

**On Q5 — the third primitive.** Yes, and it's the one you're skipping: **server-verifiable outcomes**. The server already sees agent-state transitions, dialectic verdicts, KG write success/failure, downstream sweeper outcomes, test-suite results from CI webhooks. Calibrate against *those*, not against agent self-report at all. The agent's prior `confidence` becomes the prediction; the server's later observation becomes the truth-check. No prediction_id, no agent cooperation, no fabrication surface. This is the calibration topology that doesn't require the truth-source to also be the claim-source.

## Recommendation

Ship **C as a thin v1** to unblock the starved channel, but scope it as a *bridge* to the server-verified primitive — not a destination. Add a `verification_source` field to outcome_event from day one (`agent_self_report` | `server_observation` | `external_signal`) so when the third primitive lands, you can deprecate C's contributions without rewriting the calibrator. Do not build the hybrid.
