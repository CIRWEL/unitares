# Violation Taxonomy Design

## Context

UNITARES has three independent systems that surface code and runtime findings:

- **Watcher** — 14 active patterns (P001–P017), classified by severity only
- **Sentinel** — 4 fleet-level finding types, classified by severity only
- **Broadcaster** — 9 event types with no classification

None share a common violation vocabulary. This design introduces one.

### Origin

The taxonomy originated from a GPT-proposed set of "identity axioms" that
mapped cleanly to existing UNITARES mechanisms. Review concluded the axioms
were a correct retrospective description of what the code already does, not a
new architectural layer. The useful artifact is the violation classification —
a shared vocabulary grounded in implementation surfaces.

### Positioning

This taxonomy is:

- **Descriptive, not constitutive** — it labels existing findings, it does not decide them
- **Communicative, not architectural** — it names what the code already operationalizes
- **Empirically tuned** — thresholds and detection logic remain in code, not derived from the taxonomy

## Design

### Artifact: `agents/common/violation_taxonomy.yaml`

Single source of truth for violation class vocabulary. Consumed by Watcher and
Sentinel at runtime. Human-readable header for onboarding and external
communication.

```yaml
version: 1
kind: unitares_violation_taxonomy
header: >
  Interpretive overlay on existing UNITARES governance mechanisms.
  Classes describe violation types already surfaced by Watcher, Sentinel,
  and broadcast events. Detection logic and thresholds remain in code.
  Empirically tuned — not derived from first principles.

  Listed surfaces reflect current known integration points and may be
  incomplete. The taxonomy is canonical for class vocabulary, not a
  guarantee that all related surfaces are enumerated.

classes:
  - id: CON
    status: active
    name: Continuity
    description: >
      Unexplained discontinuity in governed state or identity trajectory.
    surfaces:
      watcher_patterns: []
      sentinel_findings: [coordinated_degradation]
      broadcast_events: [identity_assurance_change, identity_drift]

  - id: INT
    status: active
    name: Integrity
    description: >
      Loss of coherence, assurance, or validated coupling between
      claims, state, and evidence.
    surfaces:
      watcher_patterns: [P010, P011, P012, P016]
      sentinel_findings: []
      broadcast_events: [knowledge_confidence_clamped]

  - id: ENT
    status: active
    name: Entropy
    description: >
      Unbounded growth, resource exhaustion, or systemic destabilization
      through uncontrolled state dispersion.
    surfaces:
      watcher_patterns: [P001, P002, P003, P009]
      sentinel_findings: [entropy_outlier, verdict_shift]
      broadcast_events: []

  - id: REC
    status: active
    name: Recoverability
    description: >
      Resource leak, deadlock, or structural failure that prevents
      clean recovery or re-entry to governed state.
    surfaces:
      watcher_patterns: [P004, P005, P017]
      sentinel_findings: []
      broadcast_events: [circuit_breaker_trip]

  - id: BEH
    status: active
    name: Behavioral Consistency
    description: >
      Observable behavior that diverges from expected governed patterns
      at the agent or fleet level.
    surfaces:
      watcher_patterns: []
      sentinel_findings: [correlated_events]
      broadcast_events: [lifecycle_silent, lifecycle_silent_critical]
    interpretation_notes: >
      correlated_events has partial overlap with ENT when the burst
      reflects systemic destabilization rather than behavioral divergence.
      Classified here because Sentinel's detection keys on cross-agent
      behavioral patterns, not entropy measurement.

  - id: VOI
    status: active
    name: Void Compliance
    description: >
      Action taken despite insufficient validation, hidden failure state,
      or unresolved uncertainty.
    surfaces:
      watcher_patterns: [P006, P008, P013, P014, P015]
      sentinel_findings: []
      broadcast_events: []
```

### Violation-to-Failure Mapping

Concrete failure modes observed in the UNITARES incident history, mapped to
violation classes:

| Class | Failure Mode | Reference |
|-------|-------------|-----------|
| CON | Unexplained mode jump, prompt injection, state splice | identity_drift broadcast |
| CON | Trust tier bouncing on threshold boundary | identity_assurance_change broadcast |
| INT | Mutation before persistence (state clobbered on reload) | P011, 2026-04 auto_archive incident |
| INT | Nested success-false swallowed by envelope parser | P016, scripts/unitares parse_onboard |
| INT | Missing test coverage on behavior change | P010, standing project rule |
| ENT | Fire-and-forget task leak, RSS runaway | P001, 2026-04-10 stuck_agent incident |
| ENT | Unbounded dict growth in per-event handlers | P002, adaptive_prediction.py |
| ENT | Transient monitor storms | P003, stuck.py incident |
| REC | asyncpg deadlock inside MCP handler | P004, health_check Option F |
| REC | Acquired resource not released on all paths | P005, agent_storage.py |
| REC | Bare await in daemon hangs launchd | P017, heartbeat_agent incident |
| BEH | Agent silent beyond expected interval | lifecycle_silent_critical broadcast |
| BEH | Heterogeneous event burst in short window | correlated_events finding |
| VOI | Silent exception swallow on main logic path | P006 |
| VOI | Shell injection via unquoted subprocess input | P008 |
| VOI | Force push / reset --hard without approval | P014, 2026-02-25 incident |
| VOI | Commit hook bypass after hook failure | P013 |
| VOI | Commands against retired Docker containers | P015 |

### Integration: `agents/common/taxonomy.py`

Thin module (~50 lines). Loaded by both Watcher and Sentinel at init.

**Public API:**

```python
def load_taxonomy() -> dict:
    """Parse violation_taxonomy.yaml, return raw dict."""

def get_taxonomy() -> dict:
    """Cached access to loaded taxonomy."""

def validate_class_id(class_id: str) -> bool:
    """True if class_id is a known class with status 'active'. Logs warning if not.
    Classes with any other status (e.g. 'deprecated') fail validation."""

def validate_surface_mapping(surface_kind: str, surface_id: str) -> bool:
    """True if surface_id appears under surface_kind in any class."""

def lookup_class_for_surface(surface_kind: str, surface_id: str) -> Optional[str]:
    """Reverse lookup: given 'watcher_patterns'/'P001', return 'ENT'."""

# Convenience wrappers:
def class_for_watcher_pattern(pattern_id: str) -> Optional[str]: ...
def class_for_sentinel_finding(finding_type: str) -> Optional[str]: ...
def class_for_broadcast_event(event_type: str) -> Optional[str]: ...
```

The reverse index is built once at load time from the YAML surfaces — no
duplication, single source of truth. Building the index enforces uniqueness:
if a surface ID appears in more than one class, `load_taxonomy()` raises
`ValueError`.

### Integration: Watcher

Add `violation_class:` annotation to each pattern header in `patterns.md`:

```markdown
### P001 — Fire-and-forget task leak (severity: high, violation_class: ENT)
```

The existing `load_pattern_severities()` in `agent.py:268` parses headers via
regex: `### P\d{3} ... (severity: <value>)`. Extend this regex to also capture
`violation_class: <ID>` from the same parenthetical. Both fields live in the
parenthetical, comma-separated. A new `load_pattern_violation_classes()`
function mirrors the severity loader.

At init, Watcher loads the taxonomy and validates that every `violation_class`
in patterns.md is a known active class ID.

Watcher findings already include the pattern ID. Adding `violation_class` to
the finding output is one line — read from the parsed pattern metadata.

### Integration: Sentinel

Add `violation_class` key to each finding dict in `FleetState.analyze()`:

```python
findings.append({
    "type": "entropy_outlier",
    "violation_class": "ENT",
    "severity": "medium",
    "summary": f"...",
})
```

Both `type` and `violation_class` remain in outputs. `type` is the concrete
detector output; `violation_class` is the interpretive label. Never replace
one with the other.

At init, Sentinel loads the taxonomy and validates that all emitted
`violation_class` values are known.

**Log/output format:** Both Watcher and Sentinel use a standardized prefix
when emitting classified findings in logs, sitreps, and knowledge graph notes:

```
[ENT] entropy_outlier — 568743e0 entropy outlier (z=2.2, S=0.433)
```

Format: `[CLASS_ID] finding_type — summary`. Grep-able, visually consistent,
fast triage under pressure.

### Validation Strategy

Two levels:

1. **Runtime** — warn visibly on unknown class IDs, continue operating.
   A bad annotation should not crash an agent.

2. **CI / pre-commit** — fail on:
   - Unknown class IDs in patterns.md annotations
   - Unknown class IDs in Sentinel finding dicts
   - Surface IDs referenced in YAML that don't exist in the codebase
     (e.g., a pattern ID that was removed)
   - Duplicate surface IDs across classes (uniqueness constraint)
   - **Orphan detection**: any Watcher pattern ID in patterns.md that
     does not appear in the taxonomy, and any Sentinel finding type
     emitted in `FleetState.analyze()` that does not appear in the
     taxonomy. New patterns/findings must be classified before merge.

   Implementation: a pytest test in `agents/common/tests/` that loads the
   taxonomy, cross-references patterns.md and Sentinel's finding types,
   and asserts bidirectional consistency. Test should also print a
   coverage summary:
   ```
   Watcher patterns covered: 14/14
   Sentinel findings covered: 4/4
   Broadcast events covered: 9/9
   ```

### Guardrails

1. **Descriptive, not normative** — the taxonomy labels findings, it does not
   decide them. Detection logic stays in Watcher patterns and Sentinel analyzers.

2. **No implementation logic in YAML** — no thresholds, formulas, or rules.

3. **Canonical IDs only** — agents emit class IDs from the shared file, no
   local aliases.

4. **Unknown classes fail visibly** — runtime warning, CI failure.

5. **Uniqueness** — a surface ID maps to at most one violation class.
   Enforced at load time (`ValueError`) and in CI.

6. **Active semantics** — only classes with `status: active` are valid for
   emission by agents. Future statuses (e.g. `deprecated`) may exist in YAML
   for history but will fail `validate_class_id()`.

7. **Orphan detection** — every Watcher pattern and Sentinel finding type must
   appear in the taxonomy. Unclassified surfaces fail CI.

8. **Surface lists are advisory** — canonical for vocabulary, not a guarantee
   that all related surfaces are enumerated. Absence does not mean "not related."

### Out of Scope

- No changes to `governance_core` or EISV dynamics
- No new broadcast event types
- No dashboard changes
- No new doctrine or philosophy documents
- Process patterns (P013, P014) stay in the taxonomy as VOI but are detected
  by Watcher's LLM, not enforced programmatically
- No `secondary_classes` or multi-class tagging in v1 — noted as a possible
  future extension for cases like `correlated_events` (BEH/ENT overlap)

### Files Changed

| File | Change |
|------|--------|
| `agents/common/violation_taxonomy.yaml` | **New** — taxonomy definition |
| `agents/common/taxonomy.py` | **New** — loader, validator, reverse lookup |
| `agents/common/tests/test_taxonomy.py` | **New** — CI validation test |
| `agents/watcher/patterns.md` | **Modified** — add `violation_class:` to each pattern header |
| `agents/watcher/agent.py` | **Modified** — load taxonomy at init, emit `violation_class` in findings |
| `agents/sentinel/agent.py` | **Modified** — add `violation_class` to finding dicts, load taxonomy at init |
