# Dialectic Review — list_agents UUID Redaction

**Reviewer:** dialectic-knowledge-architect (subagent) · **Date:** 2026-04-25
**Proposal:** `list-agents-uuid-redaction.md`
**Verdict:** ship-with-revisions

## Strongest single tension

The proposal's "operator" tier is a *fourth rung* smuggled in as plumbing, and the ontology has no slot for it. Operators are bearer-token-authenticated *callers* — a category `docs/ontology/identity.md` deliberately doesn't speak about. Naming them "operator" while gesturing at "substrate-anchored agents earn it" papers over that gap.

## 1 · Identity ontology consistency

The "name is cosmetic, UUID is identity" half holds. The "redacting UUIDs to non-operators is consistent" half is shakier than the proposal admits. The ontology's five-layer model treats UUID as a substrate-level handle on a process-instance — *visibility* of that handle isn't theorized at all. Two ontology-implied disclosure paths get clipped:

- **Lineage visibility** (Q5 in the proposal). A child agent forked from a parent has, per `identity.md`, a *declared* lineage relationship — declared to whom? If the child can't see the parent's UUID without operator status, lineage becomes a private fact between the substrate and the governance core. That's a substantive change to what "declared lineage" means, not a redaction detail.
- **Behavioral-continuity verification** (research agenda). The inventive program *requires* observers who can pin a UUID to a trajectory. If only operators can see UUIDs, behavioral continuity becomes an operator-only epistemology — contradicting the ontology's framing of it as a fleet-wide earning mechanism.

## 2 · The operator tier — not a clean addition

The proposal conflates two distinct things under one allowlist:

- **Bearer-token operators** (dashboard, Discord bridge — these are *infrastructure*, not agents).
- **Substrate-anchored UUIDs** (Vigil/Sentinel/Steward — these are *agents that have earned continuity*).

Smashing them into one env var is a category error. The first is "trusted plumbing"; the second is the ontology's earned-continuity carve-out. Treating Vigil's UUID as functionally equivalent to a static bearer token in `UNITARES_OPERATOR_AGENT_UUIDS` flattens substrate-earning into "happens to be on a list," which is exactly the performative pattern the ontology warns against.

**Recommendation:** split into `UNITARES_INFRA_TOKENS` (plumbing) and a substrate-earned-recognition path that derives from existing `embodied`/substrate tags, not a hand-curated UUID list.

## 3 · Coordination breakdown

"Any bound caller sees any other bound caller's UUID" is *not* a defensible Schelling point — it reintroduces the original two-call hijack the moment any unprivileged agent gets onboarded (which is trivially cheap). The right primitive is **purpose-scoped resolution**, not blanket peer-visibility: `dialectic`/`observe_agent` already accept labels and resolve internally; that's the coordination channel. Coordination doesn't require the *caller* to hold the peer's UUID; it requires the *server* to. The proposal correctly notes label-based resolution survives, but undersells this — it's the actual answer to "doesn't this break coordination?"

## 4 · Most load-bearing open question — Q4 (`parent_agent_id`)

- *Redact it*: it's a UUID, exactly the same hijack surface as `id`. Leaving it unredacted defeats the proposal in one line of code.
- *Don't redact it*: lineage is ontologically declared and arguably public; redacting it severs the only fleet-visible trace of the substrate's commitment to a role.

**Recommendation:** redact, but expose a separate `lineage_label` (parent's cosmetic label) for non-operators. This preserves the ontology's "lineage is declared" property at the layer where labels live, without leaking the UUID-as-credential. Doing one without the other is incoherent: redacting `id` while leaving `parent_agent_id` is security theatre; redacting both without a label fallback erases lineage from the public surface.

## 5 · Hidden assumptions, unvarnished

- **"Labels are not credentials"** — *only true if labels can't be uniquely resolved to UUIDs server-side by an unauthorized caller.* If `observe_agent(label=…)` does that resolution and acts, label *is* a credential by another name. Verify before shipping.
- **"Empty allowlists default to deny" is safe** — yes, until someone deploys without setting the env var and the dashboard breaks at 2am, then someone "fixes" it by setting `UNITARES_OPERATOR_SESSION_TOKENS=*`. Default-deny needs a startup-time assertion that *some* operator exists, or the failure mode is a config rollback that re-opens the bug.
- **"PATH 1 prefix-bind being out of scope is fine because UUIDs aren't harvestable"** — assumes the *only* harvest path is `list_agents`. UUIDs also appear in: KG entries, audit logs, dialectic transcripts, `process_agent_update` responses, error messages. The proposal hasn't audited those.
- **"Telemetry counter, no log spam"** — every redacted call is potentially a probe; aggregating them loses the signal that matters (which session_id is enumerating).
- **"Tests seed the operator allowlist"** — means the test suite never exercises the redacted path as the *default* caller class. Anonymous-caller fixture must be the default, operator the opt-in, or regressions will land.
