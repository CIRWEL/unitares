# Violation Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a shared violation classification (CON, INT, ENT, REC, BEH, VOI) consumed by Watcher and Sentinel, with CI enforcement.

**Architecture:** A single YAML file in `agents/common/` defines six violation classes and their surface mappings. A thin Python module builds a reverse index for lookups. Watcher patterns get `violation_class:` annotations; Sentinel findings get a `violation_class` key. A CI test enforces bidirectional consistency.

**Tech Stack:** Python 3.12, PyYAML (already a dependency), pytest, dataclasses

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `agents/common/violation_taxonomy.yaml` | Create | Canonical vocabulary — six classes, surface mappings |
| `agents/common/taxonomy.py` | Create | Loader, validator, reverse lookup index |
| `agents/common/tests/__init__.py` | Create | Test package init |
| `agents/common/tests/test_taxonomy.py` | Create | CI consistency tests — uniqueness, orphan detection, coverage |
| `agents/watcher/patterns.md` | Modify | Add `violation_class: XXX` to each pattern header |
| `agents/watcher/agent.py` | Modify | Load violation classes from patterns, emit in findings |
| `agents/sentinel/agent.py` | Modify | Add `violation_class` to finding dicts, format in log output |

---

### Task 1: Create `agents/common/violation_taxonomy.yaml`

**Files:**
- Create: `agents/common/violation_taxonomy.yaml`

- [ ] **Step 1: Write the YAML file**

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

- [ ] **Step 2: Commit**

```bash
git add agents/common/violation_taxonomy.yaml
git commit -m "Add violation taxonomy YAML — six classes with surface mappings"
```

---

### Task 2: Create `agents/common/taxonomy.py`

**Files:**
- Create: `agents/common/taxonomy.py`
- Create: `agents/common/tests/__init__.py`
- Create: `agents/common/tests/test_taxonomy.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/common/tests/__init__.py` (empty file).

Create `agents/common/tests/test_taxonomy.py`:

```python
"""CI tests for the violation taxonomy.

Tests enforce:
- YAML parses and loads correctly
- All class IDs are unique and active
- Surface IDs are unique across classes (no duplicates)
- Reverse lookup works for all surfaces
- validate_class_id accepts active, rejects unknown
- Convenience wrappers return correct classes
"""

import pytest
from agents.common.taxonomy import (
    load_taxonomy,
    get_taxonomy,
    validate_class_id,
    validate_surface_mapping,
    lookup_class_for_surface,
    class_for_watcher_pattern,
    class_for_sentinel_finding,
    class_for_broadcast_event,
)


def test_load_taxonomy_returns_dict():
    tax = load_taxonomy()
    assert isinstance(tax, dict)
    assert tax["version"] == 1
    assert tax["kind"] == "unitares_violation_taxonomy"


def test_all_classes_have_required_fields():
    tax = load_taxonomy()
    for cls in tax["classes"]:
        assert "id" in cls
        assert "status" in cls
        assert "name" in cls
        assert "description" in cls
        assert "surfaces" in cls
        surfaces = cls["surfaces"]
        assert "watcher_patterns" in surfaces
        assert "sentinel_findings" in surfaces
        assert "broadcast_events" in surfaces


def test_all_class_ids_unique():
    tax = load_taxonomy()
    ids = [c["id"] for c in tax["classes"]]
    assert len(ids) == len(set(ids)), f"Duplicate class IDs: {ids}"


def test_surface_ids_unique_across_classes():
    """Each surface ID must appear in at most one class."""
    tax = load_taxonomy()
    seen: dict[str, str] = {}  # surface_id -> class_id
    for cls in tax["classes"]:
        for kind in ("watcher_patterns", "sentinel_findings", "broadcast_events"):
            for sid in cls["surfaces"].get(kind, []):
                assert sid not in seen, (
                    f"Surface '{sid}' in both {seen[sid]} and {cls['id']}"
                )
                seen[sid] = cls["id"]


def test_validate_class_id_accepts_active():
    assert validate_class_id("CON") is True
    assert validate_class_id("INT") is True
    assert validate_class_id("ENT") is True
    assert validate_class_id("REC") is True
    assert validate_class_id("BEH") is True
    assert validate_class_id("VOI") is True


def test_validate_class_id_rejects_unknown():
    assert validate_class_id("FAKE") is False
    assert validate_class_id("") is False


def test_reverse_lookup_watcher_patterns():
    assert class_for_watcher_pattern("P001") == "ENT"
    assert class_for_watcher_pattern("P004") == "REC"
    assert class_for_watcher_pattern("P011") == "INT"
    assert class_for_watcher_pattern("P006") == "VOI"
    assert class_for_watcher_pattern("P999") is None


def test_reverse_lookup_sentinel_findings():
    assert class_for_sentinel_finding("coordinated_degradation") == "CON"
    assert class_for_sentinel_finding("entropy_outlier") == "ENT"
    assert class_for_sentinel_finding("correlated_events") == "BEH"
    assert class_for_sentinel_finding("nonexistent") is None


def test_reverse_lookup_broadcast_events():
    assert class_for_broadcast_event("identity_assurance_change") == "CON"
    assert class_for_broadcast_event("circuit_breaker_trip") == "REC"
    assert class_for_broadcast_event("knowledge_confidence_clamped") == "INT"
    assert class_for_broadcast_event("nonexistent") is None


def test_validate_surface_mapping():
    assert validate_surface_mapping("watcher_patterns", "P001") is True
    assert validate_surface_mapping("sentinel_findings", "entropy_outlier") is True
    assert validate_surface_mapping("watcher_patterns", "P999") is False


def test_get_taxonomy_caches():
    t1 = get_taxonomy()
    t2 = get_taxonomy()
    assert t1 is t2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/common/tests/test_taxonomy.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `agents.common.taxonomy` does not exist yet.

- [ ] **Step 3: Write the implementation**

Create `agents/common/taxonomy.py`:

```python
"""Violation taxonomy loader, validator, and reverse-lookup index.

Loads agents/common/violation_taxonomy.yaml once, builds a reverse index
from surface IDs to class IDs. Used by Watcher and Sentinel at init.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_TAXONOMY_FILE = Path(__file__).parent / "violation_taxonomy.yaml"
_cached: Optional[dict] = None
_reverse: Optional[dict[str, dict[str, str]]] = None  # kind -> {surface_id: class_id}


def load_taxonomy() -> dict:
    """Parse violation_taxonomy.yaml, return raw dict.

    Raises ValueError if any surface ID appears in more than one class.
    """
    with open(_TAXONOMY_FILE) as f:
        data = yaml.safe_load(f)

    # Build and validate reverse index on every fresh load
    reverse: dict[str, dict[str, str]] = {
        "watcher_patterns": {},
        "sentinel_findings": {},
        "broadcast_events": {},
    }
    for cls in data.get("classes", []):
        cid = cls["id"]
        for kind in reverse:
            for sid in cls.get("surfaces", {}).get(kind, []):
                if sid in reverse[kind]:
                    raise ValueError(
                        f"Surface '{sid}' in both {reverse[kind][sid]} and {cid}"
                    )
                reverse[kind][sid] = cid

    global _cached, _reverse
    _cached = data
    _reverse = reverse
    return data


def get_taxonomy() -> dict:
    """Cached access to loaded taxonomy."""
    if _cached is None:
        load_taxonomy()
    return _cached


def _get_reverse() -> dict[str, dict[str, str]]:
    if _reverse is None:
        load_taxonomy()
    return _reverse


def validate_class_id(class_id: str) -> bool:
    """True if class_id is a known class with status 'active'.

    Classes with any other status fail validation.
    Logs a warning for unknown or inactive classes.
    """
    tax = get_taxonomy()
    for cls in tax.get("classes", []):
        if cls["id"] == class_id and cls.get("status") == "active":
            return True
    if class_id:
        logger.warning("Unknown or inactive violation class: %s", class_id)
    return False


def validate_surface_mapping(surface_kind: str, surface_id: str) -> bool:
    """True if surface_id appears under surface_kind in any class."""
    rev = _get_reverse()
    return surface_id in rev.get(surface_kind, {})


def lookup_class_for_surface(
    surface_kind: str, surface_id: str
) -> Optional[str]:
    """Reverse lookup: given a surface kind and ID, return the class ID."""
    rev = _get_reverse()
    return rev.get(surface_kind, {}).get(surface_id)


def class_for_watcher_pattern(pattern_id: str) -> Optional[str]:
    """Return violation class for a Watcher pattern ID, or None."""
    return lookup_class_for_surface("watcher_patterns", pattern_id)


def class_for_sentinel_finding(finding_type: str) -> Optional[str]:
    """Return violation class for a Sentinel finding type, or None."""
    return lookup_class_for_surface("sentinel_findings", finding_type)


def class_for_broadcast_event(event_type: str) -> Optional[str]:
    """Return violation class for a broadcast event type, or None."""
    return lookup_class_for_surface("broadcast_events", event_type)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/common/tests/test_taxonomy.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/common/taxonomy.py agents/common/tests/__init__.py agents/common/tests/test_taxonomy.py
git commit -m "Add taxonomy.py — loader, validator, reverse-lookup index with tests"
```

---

### Task 3: Annotate Watcher patterns with violation classes

**Files:**
- Modify: `agents/watcher/patterns.md` — all 14 active pattern headers + 1 experimental

- [ ] **Step 1: Add `violation_class:` to each active pattern header**

Change each `### Pxxx — Name (severity: level)` to `### Pxxx — Name (severity: level, violation_class: XXX)`.

The full mapping:

| Pattern | Class |
|---------|-------|
| P001 | ENT |
| P002 | ENT |
| P003 | ENT |
| P004 | REC |
| P005 | REC |
| P006 | VOI |
| P008 | VOI |
| P009 | ENT |
| P010 | INT |
| P011 | INT |
| P012 | INT |
| P013 | VOI |
| P014 | VOI |
| P015 | VOI |
| P016 | INT |
| P017 | REC |
| EXP-P007 | REC |

Apply each edit. Examples of the transformed lines:

```markdown
### P001 — Fire-and-forget task leak (severity: high, violation_class: ENT)
### P002 — Unbounded dict/list growth (severity: medium, violation_class: ENT)
### P003 — Transient monitor pattern (severity: high, project-specific, violation_class: ENT)
### P004 — DB-touching code inside MCP tool handler (severity: high, project-specific, violation_class: REC)
### P005 — Acquire without paired release (severity: high, violation_class: REC)
### P006 — Silent exception swallow (severity: medium, violation_class: VOI)
### P008 — Unchecked shell input (severity: critical, violation_class: VOI)
### P009 — Runaway polling without iteration cap (severity: medium, violation_class: ENT)
### P010 — Missing test coverage on behavior change (severity: medium, violation_class: INT)
### P011 — mutate-then-persist in memory (severity: high, project-specific, violation_class: INT)
### P012 — json.loads / yaml.load on untrusted input (severity: medium, violation_class: INT)
### P013 — --no-verify / --amend after hook failure (severity: critical, process, violation_class: VOI)
### P014 — Force push / reset --hard on shared branches (severity: critical, process, violation_class: VOI)
### P015 — Docker commands against retired containers (severity: medium, project-specific, violation_class: VOI)
### P016 — Nested-success-false swallowed in envelope parsing (severity: high, violation_class: INT)
### P017 — Bare await in daemon/launchd script without timeout (severity: high, violation_class: REC)
```

For the experimental section:

```markdown
### EXP-P007 — Path acquired from one pool, released to another (high, violation_class: REC)
```

- [ ] **Step 2: Commit**

```bash
git add agents/watcher/patterns.md
git commit -m "Annotate all Watcher patterns with violation_class"
```

---

### Task 4: Wire Watcher to load and emit violation classes

**Files:**
- Modify: `agents/watcher/agent.py:268-279` — pattern loading
- Modify: `agents/watcher/agent.py:492-531` — parse_findings
- Modify: `agents/watcher/agent.py:127-142` — Finding dataclass
- Modify: `agents/watcher/agent.py:844-853` — _format_findings_block output
- Test: `agents/watcher/tests/test_agent.py` — add test for violation_class loading and emission

- [ ] **Step 1: Write the failing test**

Add to `agents/watcher/tests/test_agent.py`:

```python
def test_load_pattern_violation_classes():
    from agents.watcher.agent import load_pattern_violation_classes
    classes = load_pattern_violation_classes()
    assert classes["P001"] == "ENT"
    assert classes["P004"] == "REC"
    assert classes["P011"] == "INT"
    assert classes["P006"] == "VOI"
    # Every pattern with a severity should also have a violation class
    from agents.watcher.agent import load_pattern_severities
    sevs = load_pattern_severities()
    for pid in sevs:
        assert pid in classes, f"Pattern {pid} has severity but no violation_class"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::test_load_pattern_violation_classes -v
```

Expected: `ImportError` — `load_pattern_violation_classes` does not exist.

- [ ] **Step 3: Add `load_pattern_violation_classes` to `agent.py`**

After `load_pattern_severities()` (line ~279), add:

```python
def load_pattern_violation_classes() -> dict[str, str]:
    """Map pattern id -> violation class from patterns.md headers."""
    import re

    classes: dict[str, str] = {}
    if not PATTERNS_FILE.exists():
        return classes
    text = PATTERNS_FILE.read_text()
    pat = re.compile(
        r"^###\s+((?:EXP-)?P\d{3})\b.*?violation_class:\s*([A-Z]+)",
        re.MULTILINE,
    )
    for m in pat.finditer(text):
        classes[m.group(1)] = m.group(2).strip()
    return classes
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::test_load_pattern_violation_classes -v
```

Expected: PASS.

- [ ] **Step 5: Add `violation_class` field to `Finding` dataclass**

At `agents/watcher/agent.py:127`, add field after `status`:

```python
@dataclass
class Finding:
    pattern: str
    file: str
    line: int
    hint: str
    severity: str  # critical | high | medium | low
    detected_at: str
    model_used: str
    line_content_hash: str = ""
    fingerprint: str = ""
    status: str = "open"  # open | surfaced | confirmed | dismissed | aged_out
    violation_class: str = ""  # CON | INT | ENT | REC | BEH | VOI
```

- [ ] **Step 6: Populate `violation_class` in `parse_findings`**

In `parse_findings()` at line ~492, after `library_severities = load_pattern_severities()`, add:

```python
    library_violation_classes = load_pattern_violation_classes()
```

Then in the Finding constructor (line ~518-528), add the field:

```python
                Finding(
                    pattern=pattern,
                    file=file_path,
                    line=line,
                    hint=hint,
                    severity=severity,
                    detected_at=now,
                    model_used=model_used,
                    violation_class=library_violation_classes.get(pattern, ""),
                ),
```

- [ ] **Step 7: Update `_format_findings_block` to show violation class**

In `_format_findings_block()` at line ~853, change the output format:

```python
    for f in shown:
        sev = str(f.get("severity", "?")).upper()
        pat = f.get("pattern", "?")
        vcls = f.get("violation_class", "")
        file = f.get("file", "?")
        line_no = f.get("line", "?")
        hint = f.get("hint", "")
        fp = str(f.get("fingerprint", ""))[:8]
        status = f.get("status", "open")
        marker = "" if status == "open" else f" ({status})"
        cls_tag = f"[{vcls}] " if vcls else ""
        lines.append(f"  [{sev}] {cls_tag}{pat} {file}:{line_no} — {hint}  (#{fp}){marker}")
```

This produces output like:

```
  [HIGH] [INT] P011 /path/to/file.py:558 — mutation before persistence  (#af28c6ae)
```

- [ ] **Step 8: Run full Watcher test suite**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "Wire Watcher to load and emit violation_class in findings"
```

---

### Task 5: Wire Sentinel to emit violation classes

**Files:**
- Modify: `agents/sentinel/agent.py:178-266` — FleetState.analyze()
- Modify: `agents/sentinel/agent.py:489-514` — run_cycle log output
- Test: `agents/sentinel/tests/test_cycle_timeout.py` or new test file

- [ ] **Step 1: Write the failing test**

Create or add to `agents/sentinel/tests/test_sentinel_taxonomy.py`:

```python
"""Test that Sentinel findings include violation_class."""

from agents.sentinel.agent import FleetState


def test_findings_have_violation_class():
    """All finding types emitted by FleetState must include violation_class."""
    # We can't easily trigger all findings without complex mocking,
    # so we verify the mapping is complete by checking against taxonomy.
    from agents.common.taxonomy import class_for_sentinel_finding

    # Every finding type Sentinel can emit
    sentinel_finding_types = [
        "coordinated_degradation",
        "entropy_outlier",
        "verdict_shift",
        "correlated_events",
    ]
    for ft in sentinel_finding_types:
        cls = class_for_sentinel_finding(ft)
        assert cls is not None, f"Sentinel finding type '{ft}' has no taxonomy mapping"
```

- [ ] **Step 2: Run test to verify it passes** (taxonomy already maps these)

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/sentinel/tests/test_sentinel_taxonomy.py -v
```

Expected: PASS — the taxonomy already has these mappings. This test is the CI orphan detector for Sentinel.

- [ ] **Step 3: Add `violation_class` to each finding dict in `FleetState.analyze()`**

At `agents/sentinel/agent.py`, add the import at the top of the file (near other imports):

```python
from agents.common.taxonomy import class_for_sentinel_finding
```

Then add `violation_class` to each of the four `findings.append()` calls:

**1. Coordinated degradation** (line ~194):

```python
            findings.append({
                "type": "coordinated_degradation",
                "violation_class": "CON",
                "severity": "high",
                "summary": f"Coordinated coherence drop: {agents_str}",
                "agents": [aid for aid, _, _ in degraded],
                "details": {aid: round(drop, 3) for aid, _, drop in degraded},
            })
```

**2. Entropy outlier** (line ~222):

```python
                            findings.append({
                                "type": "entropy_outlier",
                                "violation_class": "ENT",
                                "severity": "info" if is_self else "medium",
                                "summary": f"{name or aid[:8]} entropy outlier (z={z:.1f}, S={s:.3f})",
                                "agents": [aid],
                                "self_observation": is_self,
                            })
```

**3. Verdict shift** (line ~243):

```python
                findings.append({
                    "type": "verdict_shift",
                    "violation_class": "ENT",
                    "severity": "high",
                    "summary": f"Pause rate {pause_rate:.0%} in last {FLEET_COORDINATED_WINDOW // 60}min ({pause_count}/{len(recent_verdicts)})",
                    "details": {"pause_rate": round(pause_rate, 3), "pause_count": pause_count},
                })
```

**4. Correlated events** (line ~259):

```python
                findings.append({
                    "type": "correlated_events",
                    "violation_class": "BEH",
                    "severity": "medium",
                    "summary": f"{len(recent_typed)} governance events in {FLEET_COORDINATED_WINDOW // 60}min: {', '.join(sorted(event_types))}",
                    "details": {"event_types": sorted(event_types), "count": len(recent_typed)},
                })
```

- [ ] **Step 4: Update log output format in `run_cycle()`**

At `agents/sentinel/agent.py:491-493`, change the finding log line to use the `[CLASS_ID]` prefix:

```python
        if fleet_findings:
            self._findings_total += len(fleet_findings)
            for f in fleet_findings:
                vcls = f.get("violation_class", "")
                cls_tag = f"[{vcls}] " if vcls else ""
                parts.append(f"[{f['severity'].upper()}] {cls_tag}{f['summary']}")
                log(f"FINDING: [{f['severity']}] {cls_tag}{f['summary']}")
                if f["severity"] == "high":
                    notify("Sentinel", f["summary"])
```

And update the knowledge graph note format (line ~513):

```python
        for f in fleet_findings:
            if f["severity"] == "high":
                vcls = f.get("violation_class", "")
                cls_tag = f"[{vcls}] " if vcls else ""
                note_tuples.append((
                    f"[Sentinel] {cls_tag}{f['summary']}",
                    ["sentinel", f["type"], f["severity"]] + ([vcls.lower()] if vcls else []),
                ))
```

- [ ] **Step 5: Run Sentinel tests**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/sentinel/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/sentinel/agent.py agents/sentinel/tests/test_sentinel_taxonomy.py
git commit -m "Wire Sentinel to emit violation_class in findings and log output"
```

---

### Task 6: CI consistency test — orphan detection and coverage

**Files:**
- Modify: `agents/common/tests/test_taxonomy.py` — add cross-referencing tests

- [ ] **Step 1: Write the bidirectional consistency tests**

Add to `agents/common/tests/test_taxonomy.py`:

```python
def test_all_watcher_patterns_are_classified():
    """Every pattern ID in patterns.md must appear in the taxonomy.

    Orphan detection: if someone adds P018 without classifying it, this fails.
    """
    from agents.watcher.agent import load_pattern_severities
    from agents.common.taxonomy import class_for_watcher_pattern

    sevs = load_pattern_severities()
    missing = [pid for pid in sevs if class_for_watcher_pattern(pid) is None]
    assert not missing, f"Watcher patterns not in taxonomy: {missing}"


def test_all_sentinel_findings_are_classified():
    """Every finding type Sentinel can emit must appear in the taxonomy."""
    from agents.common.taxonomy import class_for_sentinel_finding

    # Authoritative list of finding types emitted by FleetState.analyze()
    sentinel_types = [
        "coordinated_degradation",
        "entropy_outlier",
        "verdict_shift",
        "correlated_events",
    ]
    missing = [ft for ft in sentinel_types if class_for_sentinel_finding(ft) is None]
    assert not missing, f"Sentinel findings not in taxonomy: {missing}"


def test_taxonomy_surfaces_exist_in_codebase():
    """Surface IDs in the YAML should reference real patterns/findings.

    Catches stale references (e.g. a removed pattern still listed).
    """
    from agents.watcher.agent import load_pattern_severities
    from agents.common.taxonomy import load_taxonomy

    tax = load_taxonomy()
    watcher_patterns = set(load_pattern_severities().keys())

    for cls in tax["classes"]:
        for pid in cls["surfaces"].get("watcher_patterns", []):
            assert pid in watcher_patterns, (
                f"Taxonomy references {pid} in class {cls['id']} "
                f"but it's not in patterns.md"
            )


def test_coverage_summary(capsys):
    """Print coverage summary for CI output."""
    from agents.watcher.agent import load_pattern_severities
    from agents.common.taxonomy import load_taxonomy

    tax = load_taxonomy()
    watcher_sevs = load_pattern_severities()
    watcher_mapped = sum(
        len(c["surfaces"].get("watcher_patterns", []))
        for c in tax["classes"]
    )
    sentinel_mapped = sum(
        len(c["surfaces"].get("sentinel_findings", []))
        for c in tax["classes"]
    )
    broadcast_mapped = sum(
        len(c["surfaces"].get("broadcast_events", []))
        for c in tax["classes"]
    )

    print(f"\nWatcher patterns covered: {watcher_mapped}/{len(watcher_sevs)}")
    print(f"Sentinel findings covered: {sentinel_mapped}")
    print(f"Broadcast events covered: {broadcast_mapped}")
```

- [ ] **Step 2: Run all taxonomy and agent tests**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/common/tests/ agents/watcher/tests/ agents/sentinel/tests/ -v -s
```

Expected: all tests PASS. Coverage summary prints (use `-s` to see):

```
Watcher patterns covered: 14/14
Sentinel findings covered: 4
Broadcast events covered: 7
```

- [ ] **Step 3: Commit**

```bash
git add agents/common/tests/test_taxonomy.py
git commit -m "Add CI consistency tests — orphan detection and coverage summary"
```

---

### Task 7: Full test suite validation

**Files:** None — verification only.

- [ ] **Step 1: Run the full project test suite**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/ agents/ -q --tb=short -x
```

Expected: no regressions. If any existing tests break due to the `Finding` dataclass change (new `violation_class` field has a default, so serialization should be backward-compatible), fix them.

- [ ] **Step 2: Verify Watcher output format manually**

```bash
cd /Users/cirwel/projects/unitares && python3 agents/watcher/agent.py --list
```

Verify findings show the `[CLASS]` prefix in output.

- [ ] **Step 3: Final commit if any fixes were needed**

Only if step 1 required fixes:

```bash
git add -u
git commit -m "Fix test regressions from violation_class field addition"
```
