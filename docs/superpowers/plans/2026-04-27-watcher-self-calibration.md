# Watcher Self-Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Watcher self-calibrates a per-`(pattern × file_class)` precision floor from its own confirm/dismiss history, demotes findings whose floor falls below 0.3 with N≥10, and reserves a forced exploration quota so demoted patterns can recover.

**Architecture:** Pure-function calibration math (`calibration.py`) computes Jeffreys-95-lower-bound precision over an exponentially-decayed window. Persisted floor state (`floor_state.py`) is written atomically and consulted at surfacing time. ε-greedy probes (1-in-K, K adaptive on N) keep demoted buckets recoverable. Phase 0 fixes the silently-broken resolution-event path that the council found before any calibration relies on it.

**Tech Stack:** Python 3.12+, existing watcher/findings.jsonl substrate, pytest, no new deps.

---

## File Structure

**Created (new files):**
- `agents/watcher/calibration.py` — pure-function precision math (~180 LOC)
- `agents/watcher/floor_state.py` — atomic persistence of `pattern_floor.json` (~90 LOC)
- `agents/watcher/tests/test_calibration.py` — math/file-class/decay tests
- `agents/watcher/tests/test_floor_state.py` — atomic-write + corruption tests
- `agents/watcher/tests/test_resolution_event.py` — Phase 0 dead-path regression test
- `agents/watcher/tests/test_demotion_logic.py` — surfacing-with-floor tests
- `agents/watcher/tests/test_reason_taxonomy.py` — `--reason` enum tests

**Modified:**
- `agents/watcher/findings.py` — `_format_findings_block` reads floor + applies demotion/probe; `update_finding_status` accepts validated `reason` enum
- `agents/watcher/agent.py` — `compute_checkin_confidence` uses Jeffreys; `_post_resolution_event` uses compliant event-type suffix; CLI gains `--reason` and `--recompute-floor`
- `agents/watcher/_util.py` — add `STATE_DIR` re-export if needed for floor_state (likely a no-op; STATE_DIR already exported via findings.py)

**Out of scope (deferred to follow-up plans):**
- Adding a `confidence` field to the Finding dataclass (Phase B)
- Wiring `outcome_event` MCP tool to accept watcher-shaped enum values (Phase C — requires governance schema change, not a watcher PR)
- Dismissal-reversal cooldown table (operator-reliability gating)

---

## Phase 0 — Fix the dead `_post_resolution_event` path

The live-verifier confirmed `_post_resolution_event` posts `event_type="watcher_resolution"` to `/api/findings`, which rejects any type not ending in `_finding` (HTTP 400, swallowed by `post_finding`). Every `--resolve` / `--dismiss` for the corpus's lifetime has silently failed to reach governance. Fix this before adding any code that depends on the resolution signal.

### Task 0.1: Regression test for the dead path

**Files:**
- Create: `agents/watcher/tests/test_resolution_event.py`

- [ ] **Step 1: Write the failing test**

```python
# agents/watcher/tests/test_resolution_event.py
"""Regression test: _post_resolution_event must use an event_type the
governance /api/findings endpoint actually accepts. The HTTP layer rejects
any type not ending in '_finding' (src/http_api.py:1090). The original
implementation posted 'watcher_resolution' and got silently 400'd."""

from unittest.mock import patch

from agents.watcher.agent import _post_resolution_event


def test_resolution_event_type_passes_findings_suffix_gate():
    """The event_type Watcher posts must end in '_finding' so the
    /api/findings suffix gate accepts it. Without this, every confirm/dismiss
    is silently dropped."""
    finding = {
        "fingerprint": "abcd1234efgh5678",
        "pattern": "P-DUMMY",
        "file": "/tmp/x.py",
        "line": 1,
        "hint": "h",
        "severity": "medium",
        "violation_class": "BEH",
    }
    captured = {}

    def fake_post_finding(*, event_type, **kwargs):
        captured["event_type"] = event_type
        captured["kwargs"] = kwargs
        return True

    with patch("agents.watcher.agent.post_finding", side_effect=fake_post_finding):
        _post_resolution_event(finding, "confirmed", "agent-uuid", reason="fp")

    assert "event_type" in captured, "post_finding was not called"
    assert captured["event_type"].endswith("_finding"), (
        f"event_type {captured['event_type']!r} would be 400'd by the "
        "/api/findings suffix gate"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest agents/watcher/tests/test_resolution_event.py -v --no-cov
```

Expected: FAIL with `event_type 'watcher_resolution' would be 400'd…` (or whatever the current code emits).

- [ ] **Step 3: Read the current implementation**

```bash
grep -n "_post_resolution_event\|watcher_resolution" agents/watcher/agent.py
```

Identify the literal `event_type` string used in `_post_resolution_event` and confirm it does not end in `_finding`.

- [ ] **Step 4: Fix the event_type**

Edit `agents/watcher/agent.py` inside `_post_resolution_event`. Change the `event_type=` argument from `"watcher_resolution"` to `"watcher_resolution_finding"`.

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest agents/watcher/tests/test_resolution_event.py -v --no-cov
```

Expected: PASS.

- [ ] **Step 6: Run the full watcher suite to confirm no regression**

```bash
pytest agents/watcher/tests/ --no-cov --tb=short -q
```

Expected: all tests pass (baseline was 145 passing).

- [ ] **Step 7: Commit**

```bash
git add agents/watcher/tests/test_resolution_event.py agents/watcher/agent.py
git commit -m "fix(watcher): rename resolution event_type so /api/findings stops silently 400'ing it

The /api/findings endpoint at src/http_api.py:1090 enforces a '_finding'
suffix gate (anti-spoofing for reserved dashboard event types). The
'watcher_resolution' event_type _post_resolution_event has been emitting
fails that gate and post_finding swallows the 400, so no resolution
event has ever reached governance. Renaming to 'watcher_resolution_finding'
unblocks the calibration-feedback path Phase A depends on."
```

---

## Phase A — Self-calibration loop

### Task A.1: Jeffreys lower bound primitive

**Files:**
- Create: `agents/watcher/calibration.py`
- Create: `agents/watcher/tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

```python
# agents/watcher/tests/test_calibration.py
"""Tests for the calibration primitives — Jeffreys interval, file
classifier, exponential-decay weighting, and per-(pattern, file_class)
precision aggregation."""

import math

import pytest

from agents.watcher.calibration import jeffreys_lower_bound


class TestJeffreysLowerBound:
    """Beta(0.5, 0.5) prior. Posterior is Beta(0.5+s, 0.5+f). We return
    the 2.5% lower quantile, which behaves well at small N (no division
    by zero, monotonic in N) but is NOT 0.5 at N=0 — it's near zero. A
    min_n gate at the demotion callsite handles 'unmeasured' separately
    from 'measured-as-zero'."""

    def test_returns_float_in_unit_interval(self):
        for s, f in [(0, 0), (1, 0), (0, 1), (5, 5), (50, 50), (100, 0), (0, 100)]:
            lb = jeffreys_lower_bound(s, f)
            assert 0.0 <= lb <= 1.0, f"({s},{f}) → {lb} out of [0,1]"

    def test_n_zero_returns_low_value(self):
        # No observations — posterior is Beta(0.5, 0.5), 2.5% quantile ≈ 0.0015
        lb = jeffreys_lower_bound(0, 0)
        assert lb < 0.01, f"N=0 should return near-zero, got {lb}"

    def test_all_successes_high_n_high_lower_bound(self):
        # 100 successes, 0 failures: posterior tightly above 0.95
        lb = jeffreys_lower_bound(100, 0)
        assert lb > 0.95, f"100/0 should give high lower bound, got {lb}"

    def test_all_failures_high_n_zero_lower_bound(self):
        lb = jeffreys_lower_bound(0, 100)
        assert lb < 0.05, f"0/100 should give near-zero lower bound, got {lb}"

    def test_monotonic_in_successes(self):
        # Adding successes can only raise the lower bound
        lo = jeffreys_lower_bound(5, 5)
        hi = jeffreys_lower_bound(15, 5)
        assert hi > lo, f"more successes should raise lower bound: {lo} → {hi}"

    def test_negative_input_raises(self):
        with pytest.raises(ValueError):
            jeffreys_lower_bound(-1, 0)
        with pytest.raises(ValueError):
            jeffreys_lower_bound(0, -1)

    def test_fractional_input_accepted(self):
        # Decay-weighted counts are floats, not ints. The function must accept them.
        lb = jeffreys_lower_bound(2.5, 7.5)
        assert 0.0 <= lb <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_calibration.py -v --no-cov
```

Expected: ImportError — `calibration` module doesn't exist yet.

- [ ] **Step 3: Implement the primitive**

Create `agents/watcher/calibration.py`:

```python
"""Pure-function calibration math for Watcher self-calibration.

This module is I/O-free. It computes:

- ``jeffreys_lower_bound(successes, failures)`` — the 2.5% lower quantile
  of the Beta(0.5+s, 0.5+f) posterior. Used as the precision floor
  estimator. Compared to Wilson, it accepts fractional counts (we use
  decay-weighted observations) and has no degenerate behavior at small N.

- ``classify_file(path)`` — maps an absolute file path to one of six
  coarse classes ``{app, test, migration, generated, config, doc}``.
  Patterns calibrate per-(pattern × file_class) so a regex that's noisy
  on tests but precise on application code doesn't get globally demoted.

- ``decay_weight(detected_at, now, half_life_days)`` — exponential decay
  weight. Replaces a hard 90-day cutoff so rare patterns retain history
  and fast-moving ones weight recent reality.

- ``precision_by_pattern_and_class(findings, ...)`` — aggregates the
  above into the per-bucket precision dict consumed by floor_state.py.

Persistence and CLI wiring live elsewhere — keeping this file pure makes
the math trivially testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


# ---------------------------------------------------------------------------
# Jeffreys interval
# ---------------------------------------------------------------------------


def jeffreys_lower_bound(successes: float, failures: float) -> float:
    """2.5% lower quantile of the Beta(0.5+s, 0.5+f) posterior.

    Accepts non-integer counts (decay-weighted observations). Returns a
    value in [0, 1]. At s=f=0 the posterior is Beta(0.5, 0.5) and the
    lower bound is ~0.0015 — callers that distinguish "unmeasured" from
    "measured-as-zero" should gate on N separately.
    """
    if successes < 0 or failures < 0:
        raise ValueError(
            f"jeffreys_lower_bound: counts must be non-negative, "
            f"got successes={successes}, failures={failures}"
        )

    alpha = 0.5 + successes
    beta = 0.5 + failures
    return _beta_lower_quantile(alpha, beta, q=0.025)


def _beta_lower_quantile(alpha: float, beta: float, q: float) -> float:
    """Inverse-CDF of Beta(alpha, beta) at probability ``q``. Bisection on
    the regularized incomplete beta function (math.lgamma + series via
    ``math.gamma``-free CDF). We use bisection rather than scipy to keep
    Watcher dependency-free.

    20 iterations of bisection over [0, 1] gives <1e-6 precision, which
    is well below the threshold-tuning resolution we care about (0.3).
    """
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _beta_cdf(mid, alpha, beta) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _beta_cdf(x: float, alpha: float, beta: float) -> float:
    """Regularized incomplete beta function I_x(alpha, beta).

    Implementation: continued-fraction expansion (Numerical Recipes §6.4).
    Stable for the alpha/beta ranges Watcher produces (0.5 ≤ a ≤ ~10^4).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # log B(a,b) prefactor
    log_bt = (
        math.lgamma(alpha + beta)
        - math.lgamma(alpha)
        - math.lgamma(beta)
        + alpha * math.log(x)
        + beta * math.log(1.0 - x)
    )
    bt = math.exp(log_bt)
    # Continued fraction is more efficient on the side closer to zero
    if x < (alpha + 1.0) / (alpha + beta + 2.0):
        return bt * _betacf(x, alpha, beta) / alpha
    return 1.0 - bt * _betacf(1.0 - x, beta, alpha) / beta


def _betacf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 3e-7) -> float:
    """Continued-fraction evaluation for the incomplete beta. Lentz's
    method. ``max_iter=200`` is overkill for our parameter range; a
    typical convergence is <30 iterations."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    return h
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_calibration.py -v --no-cov
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/calibration.py agents/watcher/tests/test_calibration.py
git commit -m "feat(watcher): jeffreys_lower_bound primitive for precision math

Pure-function 2.5% lower quantile of Beta(0.5+s, 0.5+f). Accepts
fractional counts (we'll feed it decay-weighted observations). No
scipy dep — bisection over the continued-fraction incomplete-beta CDF."
```

### Task A.2: File classifier

**Files:**
- Modify: `agents/watcher/calibration.py`
- Modify: `agents/watcher/tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

Append to `agents/watcher/tests/test_calibration.py`:

```python
from agents.watcher.calibration import classify_file, FileClass


class TestClassifyFile:
    """File class is the second axis of the calibration bucket. Six
    coarse classes are enough to capture the heterogeneity the dialectic
    flagged (a regex that's 90% precise on app code and 10% on tests
    averages to ~50% globally and gets demoted everywhere)."""

    def test_test_files(self):
        assert classify_file("/repo/agents/watcher/tests/test_x.py") == FileClass.TEST
        assert classify_file("/repo/tests/integration/foo.py") == FileClass.TEST
        assert classify_file("/repo/foo_test.py") == FileClass.TEST
        assert classify_file("/repo/test_bar.py") == FileClass.TEST

    def test_migration_files(self):
        assert classify_file("/repo/migrations/018_foo.sql") == FileClass.MIGRATION
        assert classify_file("/repo/db/migrations/up.py") == FileClass.MIGRATION

    def test_generated_files(self):
        assert classify_file("/repo/build/foo.py") == FileClass.GENERATED
        assert classify_file("/repo/dist/bundle.js") == FileClass.GENERATED
        assert classify_file("/repo/__pycache__/x.pyc") == FileClass.GENERATED
        assert classify_file("/repo/foo.pb.go") == FileClass.GENERATED

    def test_config_files(self):
        assert classify_file("/repo/pyproject.toml") == FileClass.CONFIG
        assert classify_file("/repo/setup.cfg") == FileClass.CONFIG
        assert classify_file("/repo/.github/workflows/ci.yml") == FileClass.CONFIG
        assert classify_file("/repo/Makefile") == FileClass.CONFIG

    def test_doc_files(self):
        assert classify_file("/repo/README.md") == FileClass.DOC
        assert classify_file("/repo/docs/foo.md") == FileClass.DOC
        assert classify_file("/repo/CHANGELOG") == FileClass.DOC

    def test_app_default(self):
        assert classify_file("/repo/src/server.py") == FileClass.APP
        assert classify_file("/repo/agents/watcher/agent.py") == FileClass.APP
        assert classify_file("/repo/governance_core/eisv.py") == FileClass.APP

    def test_test_wins_over_app(self):
        # tests/ is the strongest signal — it sits inside src/ in some layouts
        assert classify_file("/repo/src/tests/foo.py") == FileClass.TEST
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_calibration.py::TestClassifyFile -v --no-cov
```

Expected: ImportError — `classify_file`/`FileClass` don't exist.

- [ ] **Step 3: Add the classifier**

Append to `agents/watcher/calibration.py`:

```python
# ---------------------------------------------------------------------------
# File classifier
# ---------------------------------------------------------------------------


class FileClass:
    """Closed enum of file classes used as the second calibration axis.

    Strings (not IntEnum) so they round-trip through pattern_floor.json
    losslessly without requiring a converter. Ordering matters in
    ``classify_file`` — first match wins, with TEST checked before APP
    so test files inside src/ trees still classify as tests.
    """

    APP = "app"
    TEST = "test"
    MIGRATION = "migration"
    GENERATED = "generated"
    CONFIG = "config"
    DOC = "doc"


_TEST_FRAGMENTS = ("/tests/", "/test/")
_TEST_NAME_PREFIX = "test_"
_TEST_NAME_SUFFIX = "_test"

_MIGRATION_FRAGMENTS = ("/migrations/",)

_GENERATED_FRAGMENTS = ("/build/", "/dist/", "/__pycache__/", "/.venv/", "/node_modules/")
_GENERATED_SUFFIXES = (".pb.go", ".pb.py", ".min.js", ".pyc")

_CONFIG_FRAGMENTS = ("/.github/",)
_CONFIG_BASENAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "Makefile", "tox.ini",
    ".gitignore", ".dockerignore", "Dockerfile", "docker-compose.yml",
    "pre-commit-config.yaml", ".pre-commit-config.yaml",
})
_CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".ini", ".cfg")

_DOC_SUFFIXES = (".md", ".rst", ".txt")
_DOC_BASENAMES = frozenset({"README", "CHANGELOG", "LICENSE", "NOTICE", "AUTHORS"})


def classify_file(path: str) -> str:
    """Map a file path to a FileClass.

    Order: test → migration → generated → doc → config → app. TEST wins
    over APP because tests/ trees often live inside src/ trees and the
    regex precision on test fixtures is qualitatively different from
    application code.
    """
    p = Path(path)
    name = p.name
    norm = "/" + str(p).strip("/")

    # 1. test
    if any(frag in norm for frag in _TEST_FRAGMENTS):
        return FileClass.TEST
    if name.startswith(_TEST_NAME_PREFIX):
        return FileClass.TEST
    stem = p.stem
    if stem.endswith(_TEST_NAME_SUFFIX):
        return FileClass.TEST

    # 2. migration
    if any(frag in norm for frag in _MIGRATION_FRAGMENTS):
        return FileClass.MIGRATION

    # 3. generated
    if any(frag in norm for frag in _GENERATED_FRAGMENTS):
        return FileClass.GENERATED
    if any(name.endswith(suf) for suf in _GENERATED_SUFFIXES):
        return FileClass.GENERATED

    # 4. doc
    if name in _DOC_BASENAMES:
        return FileClass.DOC
    if any(name.endswith(suf) for suf in _DOC_SUFFIXES):
        return FileClass.DOC

    # 5. config
    if any(frag in norm for frag in _CONFIG_FRAGMENTS):
        return FileClass.CONFIG
    if name in _CONFIG_BASENAMES:
        return FileClass.CONFIG
    if any(name.endswith(suf) for suf in _CONFIG_SUFFIXES):
        return FileClass.CONFIG

    # 6. default
    return FileClass.APP
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_calibration.py::TestClassifyFile -v --no-cov
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/calibration.py agents/watcher/tests/test_calibration.py
git commit -m "feat(watcher): file classifier for the second calibration axis

Six classes (app/test/migration/generated/config/doc). Calibrating
per-(pattern, file_class) lets a regex that's precise on application
code stay surfaced even if it's noisy on tests."
```

### Task A.3: Decay weight primitive

**Files:**
- Modify: `agents/watcher/calibration.py`
- Modify: `agents/watcher/tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

Append to `agents/watcher/tests/test_calibration.py`:

```python
from datetime import datetime, timedelta, timezone

from agents.watcher.calibration import decay_weight, parse_iso_z


class TestDecayWeight:
    """Exponential decay replaces the 90-day hard cutoff. Half-life ~30d
    means a 60-day-old observation contributes 0.25× of a fresh one.
    Old observations don't fall off a cliff; they just matter less."""

    def test_zero_age_full_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        assert decay_weight(now, now, half_life_days=30.0) == pytest.approx(1.0)

    def test_one_half_life_half_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        assert decay_weight(thirty_days_ago, now, half_life_days=30.0) == pytest.approx(0.5, rel=1e-9)

    def test_two_half_lives_quarter_weight(self):
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        sixty_days_ago = now - timedelta(days=60)
        assert decay_weight(sixty_days_ago, now, half_life_days=30.0) == pytest.approx(0.25, rel=1e-9)

    def test_future_timestamps_clamp_to_one(self):
        """Clock skew shouldn't manufacture > 1.0 weights."""
        now = datetime(2026, 4, 27, tzinfo=timezone.utc)
        future = now + timedelta(hours=1)
        assert decay_weight(future, now, half_life_days=30.0) == pytest.approx(1.0)

    def test_naive_datetime_raises(self):
        now = datetime.now(timezone.utc)
        naive = datetime(2026, 4, 1)
        with pytest.raises(ValueError):
            decay_weight(naive, now, half_life_days=30.0)


class TestParseIsoZ:
    """Tolerate the two timestamp formats actually present in
    findings.jsonl: '2026-04-20T12:34:56Z' (Watcher's own writes) and
    '2026-04-20T12:34:56+00:00' (governance writes via Python isoformat)."""

    def test_z_suffix(self):
        ts = parse_iso_z("2026-04-20T12:34:56Z")
        assert ts == datetime(2026, 4, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_plus_zero_suffix(self):
        ts = parse_iso_z("2026-04-20T12:34:56+00:00")
        assert ts == datetime(2026, 4, 20, 12, 34, 56, tzinfo=timezone.utc)

    def test_garbage_returns_none(self):
        assert parse_iso_z("not a date") is None
        assert parse_iso_z("") is None
        assert parse_iso_z(None) is None  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_calibration.py::TestDecayWeight agents/watcher/tests/test_calibration.py::TestParseIsoZ -v --no-cov
```

Expected: ImportError on `decay_weight` / `parse_iso_z`.

- [ ] **Step 3: Implement decay primitives**

Append to `agents/watcher/calibration.py`:

```python
# ---------------------------------------------------------------------------
# Decay weighting
# ---------------------------------------------------------------------------


def parse_iso_z(value: str | None) -> datetime | None:
    """Tolerant parser for the two timestamp formats present in
    findings.jsonl. Returns None on any failure — callers exclude the
    row from the weighted aggregate rather than crashing the loop.
    """
    if not value or not isinstance(value, str):
        return None
    candidates = (
        ("%Y-%m-%dT%H:%M:%SZ", value),
        ("%Y-%m-%dT%H:%M:%S%z", value.replace("Z", "+0000")),
    )
    for fmt, raw in candidates:
        try:
            ts = datetime.strptime(raw, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except (TypeError, ValueError):
            continue
    # Fall back to fromisoformat (handles '+00:00' style and microseconds)
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (TypeError, ValueError):
        return None


def decay_weight(detected_at: datetime, now: datetime, half_life_days: float) -> float:
    """Exponential decay weight: ``2^(-age_days / half_life_days)``.

    Future timestamps clamp to 1.0 (clock skew shouldn't produce
    ``> 1.0`` weights). Both arguments must be timezone-aware; comparing
    naive and aware datetimes raises a TypeError, which we surface as a
    ValueError so callers don't silently miscompute against a wall-clock
    age that's actually wrong by the local UTC offset.
    """
    if detected_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("decay_weight: both timestamps must be timezone-aware")
    age_seconds = (now - detected_at).total_seconds()
    if age_seconds <= 0:
        return 1.0
    age_days = age_seconds / 86400.0
    return 0.5 ** (age_days / half_life_days)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_calibration.py::TestDecayWeight agents/watcher/tests/test_calibration.py::TestParseIsoZ -v --no-cov
```

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/calibration.py agents/watcher/tests/test_calibration.py
git commit -m "feat(watcher): exponential-decay weighting + tolerant ISO parser

Half-life-based weighting so old observations contribute less without
falling off a cliff. parse_iso_z handles both Z-suffix and +00:00
timestamp formats actually present in findings.jsonl."
```

### Task A.4: Per-(pattern × file_class) precision aggregation

**Files:**
- Modify: `agents/watcher/calibration.py`
- Modify: `agents/watcher/tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

Append to `agents/watcher/tests/test_calibration.py`:

```python
from agents.watcher.calibration import (
    PRECISION_REASONS_TRUE_NEGATIVE,
    BucketStats,
    precision_by_pattern_and_class,
)


def _row(*, pattern, file, status, ts, reason=None, confirmed_at=None, dismissed_at=None):
    """Helper: build a findings.jsonl-shaped dict."""
    r = {
        "pattern": pattern,
        "file": file,
        "line": 1,
        "hint": "h",
        "severity": "medium",
        "status": status,
        "detected_at": ts,
        "fingerprint": "abcd1234",
        "violation_class": "BEH",
    }
    if confirmed_at:
        r["confirmed_at"] = confirmed_at
    if dismissed_at:
        r["dismissed_at"] = dismissed_at
    if reason is not None:
        r["resolution_reason"] = reason
    return r


class TestPrecisionByPatternAndClass:
    """The aggregator combines decay-weighting and the reason filter to
    produce per-bucket {weighted_confirmed, weighted_dismissed, ci_lower}.

    Critical behaviors:
      - Only confirmed/dismissed rows count (open/surfaced/aged_out skipped)
      - 'wont_fix', 'out_of_scope', 'unclear' dismissals are EXCLUDED from
        precision math (precision means 'TP / (TP + FP)', and these aren't
        false positives)
      - Legacy free-text reasons are excluded too (no taxonomy alignment)
      - Buckets with weighted_n < min_weighted_n return ci_lower=None
        (the demotion callsite gates on this)
    """

    NOW = datetime(2026, 4, 27, tzinfo=timezone.utc)
    YESTERDAY = "2026-04-26T12:00:00Z"

    def test_empty_findings_empty_dict(self):
        result = precision_by_pattern_and_class([], now=self.NOW)
        assert result == {}

    def test_only_confirmed_dismissed_count(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="open", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="surfaced", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="aged_out", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="dismissed", reason="fp", ts=self.YESTERDAY),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=0.5)
        bucket = result[("P1", "app")]
        assert bucket.weighted_confirmed == pytest.approx(1.0, rel=0.01)
        assert bucket.weighted_dismissed == pytest.approx(1.0, rel=0.01)

    def test_wont_fix_excluded_from_dismissed(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="dismissed", reason="wont_fix", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="dismissed", reason="dup", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="dismissed", reason="unclear", ts=self.YESTERDAY),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=0.5)
        bucket = result[("P1", "app")]
        assert bucket.weighted_confirmed == pytest.approx(1.0, rel=0.01)
        # wont_fix, dup, unclear all excluded → only the confirmed row contributes
        assert bucket.weighted_dismissed == pytest.approx(0.0, abs=0.01)

    def test_legacy_free_text_reason_excluded(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="dismissed",
                 reason="this was a false alarm imo", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/src/x.py", status="dismissed",
                 reason="fp", ts=self.YESTERDAY),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=0.5)
        bucket = result[("P1", "app")]
        assert bucket.weighted_dismissed == pytest.approx(1.0, rel=0.01)

    def test_buckets_split_on_file_class(self):
        rows = [
            _row(pattern="P1", file="/a/src/foo.py", status="confirmed", ts=self.YESTERDAY),
            _row(pattern="P1", file="/a/tests/test_foo.py", status="dismissed",
                 reason="fp", ts=self.YESTERDAY),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=0.5)
        assert ("P1", "app") in result
        assert ("P1", "test") in result
        assert result[("P1", "app")].weighted_confirmed > 0
        assert result[("P1", "app")].weighted_dismissed == 0
        assert result[("P1", "test")].weighted_confirmed == 0
        assert result[("P1", "test")].weighted_dismissed > 0

    def test_decay_applied(self):
        """A 60-day-old confirmation contributes 0.25× of a fresh one."""
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="confirmed",
                 ts=(self.NOW - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")),
            _row(pattern="P1", file="/a/src/x.py", status="confirmed",
                 ts=self.NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, half_life_days=30.0,
                                                min_weighted_n=0.5)
        bucket = result[("P1", "app")]
        # 1.0 (today) + 0.25 (60d ago) = 1.25
        assert bucket.weighted_confirmed == pytest.approx(1.25, rel=0.01)

    def test_min_weighted_n_returns_none_ci(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts=self.YESTERDAY),
        ]
        # Require 10 effective observations; we only have 1
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=10.0)
        bucket = result[("P1", "app")]
        assert bucket.ci_lower is None, "below min_weighted_n should yield ci_lower=None"

    def test_above_min_weighted_n_returns_ci(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts=self.YESTERDAY)
            for _ in range(20)
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=10.0)
        bucket = result[("P1", "app")]
        assert bucket.ci_lower is not None
        assert bucket.ci_lower > 0.7  # 20 confirmed, 0 dismissed → high lower bound

    def test_unparseable_timestamp_skipped(self):
        rows = [
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts="garbage"),
            _row(pattern="P1", file="/a/src/x.py", status="confirmed", ts=self.YESTERDAY),
        ]
        result = precision_by_pattern_and_class(rows, now=self.NOW, min_weighted_n=0.5)
        bucket = result[("P1", "app")]
        # Garbage row dropped, only the parseable one contributes
        assert bucket.weighted_confirmed == pytest.approx(1.0, rel=0.01)


def test_precision_reasons_constant_shape():
    """Document the canonical taxonomy. Precision math counts as TN ONLY
    the reasons that mean 'this finding was a false positive'."""
    assert PRECISION_REASONS_TRUE_NEGATIVE == frozenset({"fp"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_calibration.py::TestPrecisionByPatternAndClass -v --no-cov
```

Expected: ImportError on `precision_by_pattern_and_class` / `BucketStats` / `PRECISION_REASONS_TRUE_NEGATIVE`.

- [ ] **Step 3: Implement the aggregator**

Append to `agents/watcher/calibration.py`:

```python
# ---------------------------------------------------------------------------
# Per-(pattern × file_class) aggregation
# ---------------------------------------------------------------------------


# Reasons that count as a true negative (i.e. "the finding was wrong").
# wont_fix / out_of_scope / dup / unclear / stale are excluded — they
# represent operator decisions that are not statements about the finding's
# correctness. Legacy free-text reasons are also excluded (they predate the
# enum and have no consistent meaning).
PRECISION_REASONS_TRUE_NEGATIVE = frozenset({"fp"})


@dataclass(frozen=True)
class BucketStats:
    """Per-(pattern, file_class) precision summary.

    ``ci_lower`` is None when ``weighted_n < min_weighted_n`` — callers
    must distinguish 'unmeasured' from 'measured-as-zero' to avoid the
    cold-trap the council flagged. Demotion logic should never fire on
    a None ci_lower.
    """

    pattern: str
    file_class: str
    weighted_confirmed: float
    weighted_dismissed: float
    weighted_n: float
    ci_lower: float | None
    latest_observation: str | None  # ISO-Z string of the most recent contributing row


def precision_by_pattern_and_class(
    findings: Iterable[Mapping[str, object]],
    *,
    now: datetime | None = None,
    half_life_days: float = 30.0,
    min_weighted_n: float = 10.0,
    true_negative_reasons: Iterable[str] = PRECISION_REASONS_TRUE_NEGATIVE,
) -> dict[tuple[str, str], BucketStats]:
    """Aggregate findings into per-(pattern, file_class) precision stats.

    Only ``confirmed`` and qualifying ``dismissed`` rows contribute. A
    dismissed row qualifies when its ``resolution_reason`` is in
    ``true_negative_reasons`` (default: just ``{'fp'}``). Legacy rows
    with free-text reasons or no reason are excluded from the dismissed
    count — they don't represent a precision-relevant signal.

    Returns ``{(pattern, file_class): BucketStats}``. Buckets with
    ``weighted_n < min_weighted_n`` carry ``ci_lower=None`` so callers
    can distinguish 'unmeasured' from 'measured-as-zero'.
    """
    reference = now or datetime.now(timezone.utc)
    tn_reasons = frozenset(true_negative_reasons)

    # Walk findings once, accumulate per-bucket weighted counts.
    aggregates: dict[tuple[str, str], dict[str, float | str | None]] = {}

    for row in findings:
        status = row.get("status")
        if status not in ("confirmed", "dismissed"):
            continue
        pattern = row.get("pattern")
        file_path = row.get("file")
        if not isinstance(pattern, str) or not isinstance(file_path, str):
            continue

        # The decay clock anchors on the most relevant timestamp:
        # confirmed_at / dismissed_at when present (resolution time is
        # what we're calibrating), falling back to detected_at.
        resolved_at = row.get("confirmed_at") if status == "confirmed" else row.get("dismissed_at")
        ts_raw = resolved_at if isinstance(resolved_at, str) else row.get("detected_at")
        if not isinstance(ts_raw, str):
            continue
        ts = parse_iso_z(ts_raw)
        if ts is None:
            continue

        # Reason filter for dismissed rows
        if status == "dismissed":
            reason = row.get("resolution_reason")
            if not isinstance(reason, str) or reason not in tn_reasons:
                continue

        file_class = classify_file(file_path)
        key = (pattern, file_class)
        weight = decay_weight(ts, reference, half_life_days)
        bucket = aggregates.setdefault(
            key,
            {"confirmed": 0.0, "dismissed": 0.0, "latest": None},
        )
        if status == "confirmed":
            bucket["confirmed"] = float(bucket["confirmed"]) + weight
        else:
            bucket["dismissed"] = float(bucket["dismissed"]) + weight

        latest = bucket["latest"]
        if latest is None or (isinstance(latest, str) and ts_raw > latest):
            bucket["latest"] = ts_raw

    # Materialize into BucketStats with ci_lower gated on min_weighted_n
    out: dict[tuple[str, str], BucketStats] = {}
    for (pattern, file_class), agg in aggregates.items():
        wc = float(agg["confirmed"])
        wd = float(agg["dismissed"])
        wn = wc + wd
        ci = jeffreys_lower_bound(wc, wd) if wn >= min_weighted_n else None
        latest_value = agg["latest"]
        out[(pattern, file_class)] = BucketStats(
            pattern=pattern,
            file_class=file_class,
            weighted_confirmed=wc,
            weighted_dismissed=wd,
            weighted_n=wn,
            ci_lower=ci,
            latest_observation=latest_value if isinstance(latest_value, str) else None,
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_calibration.py -v --no-cov
```

Expected: ALL `test_calibration.py` tests pass (Jeffreys + classifier + decay + aggregator + constant).

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/calibration.py agents/watcher/tests/test_calibration.py
git commit -m "feat(watcher): per-(pattern × file_class) precision aggregator

Decay-weighted confirmed/dismissed counts → BucketStats with Jeffreys
lower bound. Reason filter excludes wont_fix / out_of_scope / dup /
unclear / stale and legacy free-text from the dismissed count — those
aren't false positives, so they don't belong in precision math.
ci_lower=None when weighted_n is below the min — distinguishing
'unmeasured' from 'measured-as-zero' at the bucket level prevents the
cold trap the council flagged."
```

### Task A.5: Atomic floor-state persistence

**Files:**
- Create: `agents/watcher/floor_state.py`
- Create: `agents/watcher/tests/test_floor_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# agents/watcher/tests/test_floor_state.py
"""Tests for atomic persistence of pattern_floor.json.

Per the council review: pattern_floor.json must use tmp+rename atomic
writes (the same pattern as _write_findings_atomic in findings.py:234).
A direct write_text would let a concurrent reader (the surface hook
fires on every UserPromptSubmit) see a truncated JSON file mid-write."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.watcher.calibration import BucketStats
from agents.watcher.floor_state import (
    FLOOR_FILE_NAME,
    FloorState,
    load_floor,
    save_floor,
)


def _bucket(pattern, fc, *, wc=10.0, wd=2.0, ci=0.6, latest="2026-04-20T00:00:00Z"):
    return BucketStats(
        pattern=pattern,
        file_class=fc,
        weighted_confirmed=wc,
        weighted_dismissed=wd,
        weighted_n=wc + wd,
        ci_lower=ci,
        latest_observation=latest,
    )


class TestFloorRoundTrip:
    def test_save_then_load_round_trip(self, tmp_path):
        state = FloorState(
            updated_at="2026-04-27T00:00:00Z",
            buckets={
                ("P1", "app"): _bucket("P1", "app", ci=0.85),
                ("P1", "test"): _bucket("P1", "test", ci=0.10, wc=1.0, wd=9.0),
            },
        )
        save_floor(state, state_dir=tmp_path)
        loaded = load_floor(state_dir=tmp_path)
        assert loaded.updated_at == "2026-04-27T00:00:00Z"
        assert ("P1", "app") in loaded.buckets
        assert loaded.buckets[("P1", "app")].ci_lower == pytest.approx(0.85)
        assert loaded.buckets[("P1", "test")].ci_lower == pytest.approx(0.10)

    def test_load_missing_file_returns_empty_state(self, tmp_path):
        loaded = load_floor(state_dir=tmp_path)
        assert loaded.buckets == {}
        assert loaded.updated_at is not None  # epoch-default acceptable

    def test_load_corrupt_file_returns_empty_state(self, tmp_path):
        (tmp_path / FLOOR_FILE_NAME).write_text("{not valid json")
        loaded = load_floor(state_dir=tmp_path)
        assert loaded.buckets == {}

    def test_save_uses_tmp_then_rename(self, tmp_path, monkeypatch):
        """Verify the writer never leaves a half-written floor file
        observable to a concurrent reader. We do this by patching
        json.dump to crash mid-write and asserting the on-disk file
        is still the previous version."""
        # Seed an initial good state
        good = FloorState(
            updated_at="2026-04-20T00:00:00Z",
            buckets={("OLD", "app"): _bucket("OLD", "app")},
        )
        save_floor(good, state_dir=tmp_path)
        target = tmp_path / FLOOR_FILE_NAME
        good_payload = target.read_text()

        # Now try to save a new state but make json.dump crash
        bad = FloorState(updated_at="2026-04-27T00:00:00Z", buckets={})

        original_dump = json.dump

        def crashing_dump(obj, fp, *args, **kwargs):
            fp.write('{"partial')
            raise IOError("simulated mid-write crash")

        monkeypatch.setattr(json, "dump", crashing_dump)
        with pytest.raises(IOError):
            save_floor(bad, state_dir=tmp_path)

        # The on-disk file should still be the original — atomic write
        # means the tmp file took the partial write and was never renamed.
        assert target.read_text() == good_payload, (
            "save_floor must write to tmp + rename so a crash mid-write "
            "doesn't corrupt the live file"
        )
        # Recover real json.dump (monkeypatch will undo on teardown anyway)
        monkeypatch.setattr(json, "dump", original_dump)

    def test_save_creates_state_dir(self, tmp_path):
        nested = tmp_path / "deep" / "watcher_data"
        save_floor(FloorState(updated_at="t", buckets={}), state_dir=nested)
        assert (nested / FLOOR_FILE_NAME).exists()


class TestFloorBucketLookup:
    def test_get_returns_bucket(self):
        state = FloorState(
            updated_at="t",
            buckets={("P1", "app"): _bucket("P1", "app", ci=0.7)},
        )
        bucket = state.get("P1", "app")
        assert bucket is not None
        assert bucket.ci_lower == pytest.approx(0.7)

    def test_get_returns_none_for_unknown(self):
        state = FloorState(updated_at="t", buckets={})
        assert state.get("P1", "app") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_floor_state.py -v --no-cov
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Implement the persistence module**

```python
# agents/watcher/floor_state.py
"""Atomic persistence for the per-(pattern, file_class) precision floor.

State lives at ``data/watcher/pattern_floor.json``. Writes use
tmp + rename (mirroring ``_write_findings_atomic`` in findings.py:234)
so a concurrent reader — the surface hook fires on every
UserPromptSubmit, and Vigil/CLI/scan-hook may all touch the watcher
state dir — never sees a truncated file.

Schema:

    {
      "updated_at": "2026-04-27T00:00:00Z",
      "buckets": {
        "PATTERN|file_class": {
          "weighted_confirmed": 10.5,
          "weighted_dismissed": 2.3,
          "weighted_n": 12.8,
          "ci_lower": 0.45,
          "latest_observation": "2026-04-26T12:34:56Z"
        },
        ...
      }
    }

The "PATTERN|file_class" key uses '|' as the separator because patterns
are uppercase identifiers (P-XYZ, etc.) and file_class values are
lowercase enum values — '|' won't collide with either.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from agents.watcher._util import PROJECT_ROOT
from agents.watcher.calibration import BucketStats


FLOOR_FILE_NAME = "pattern_floor.json"
DEFAULT_STATE_DIR = PROJECT_ROOT / "data" / "watcher"
_KEY_SEP = "|"


@dataclass
class FloorState:
    updated_at: str
    buckets: dict[tuple[str, str], BucketStats] = field(default_factory=dict)

    def get(self, pattern: str, file_class: str) -> BucketStats | None:
        return self.buckets.get((pattern, file_class))


def _bucket_to_dict(b: BucketStats) -> dict:
    return {
        "weighted_confirmed": b.weighted_confirmed,
        "weighted_dismissed": b.weighted_dismissed,
        "weighted_n": b.weighted_n,
        "ci_lower": b.ci_lower,
        "latest_observation": b.latest_observation,
    }


def _dict_to_bucket(pattern: str, file_class: str, payload: Mapping[str, object]) -> BucketStats:
    return BucketStats(
        pattern=pattern,
        file_class=file_class,
        weighted_confirmed=float(payload.get("weighted_confirmed", 0.0)),
        weighted_dismissed=float(payload.get("weighted_dismissed", 0.0)),
        weighted_n=float(payload.get("weighted_n", 0.0)),
        ci_lower=(
            float(payload["ci_lower"])
            if isinstance(payload.get("ci_lower"), (int, float))
            else None
        ),
        latest_observation=(
            payload["latest_observation"]
            if isinstance(payload.get("latest_observation"), str)
            else None
        ),
    )


def save_floor(state: FloorState, *, state_dir: Path | None = None) -> None:
    """Atomically persist ``state`` to ``pattern_floor.json``.

    Writes to a sibling ``.tmp`` file and renames over the target — a
    crash mid-write leaves the previous file intact.
    """
    target_dir = state_dir or DEFAULT_STATE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / FLOOR_FILE_NAME
    tmp = target.with_suffix(target.suffix + ".tmp")

    payload = {
        "updated_at": state.updated_at,
        "buckets": {
            f"{pattern}{_KEY_SEP}{file_class}": _bucket_to_dict(bucket)
            for (pattern, file_class), bucket in sorted(state.buckets.items())
        },
    }

    with tmp.open("w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    tmp.replace(target)


def load_floor(*, state_dir: Path | None = None) -> FloorState:
    """Load floor state. Missing or corrupt files yield an empty state
    (fail-open: a missing floor means no demotion fires, which is the
    safe default — we surface findings rather than hide them)."""
    target_dir = state_dir or DEFAULT_STATE_DIR
    target = target_dir / FLOOR_FILE_NAME
    if not target.exists():
        return FloorState(updated_at=_epoch_iso(), buckets={})
    try:
        payload = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return FloorState(updated_at=_epoch_iso(), buckets={})

    raw_buckets = payload.get("buckets")
    if not isinstance(raw_buckets, dict):
        return FloorState(updated_at=str(payload.get("updated_at", _epoch_iso())), buckets={})

    buckets: dict[tuple[str, str], BucketStats] = {}
    for key, bp in raw_buckets.items():
        if not isinstance(key, str) or _KEY_SEP not in key or not isinstance(bp, dict):
            continue
        pattern, file_class = key.split(_KEY_SEP, 1)
        buckets[(pattern, file_class)] = _dict_to_bucket(pattern, file_class, bp)

    return FloorState(
        updated_at=str(payload.get("updated_at", _epoch_iso())),
        buckets=buckets,
    )


def _epoch_iso() -> str:
    return datetime(1970, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_floor_state.py -v --no-cov
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/floor_state.py agents/watcher/tests/test_floor_state.py
git commit -m "feat(watcher): atomic persistence for pattern_floor.json

tmp + rename writes (mirrors _write_findings_atomic) — concurrent
readers from the surface hook can never observe a truncated file.
Missing/corrupt files yield an empty state (fail-open: no floor
means no demotion fires, which preserves the existing surface
behavior)."
```

### Task A.6: `--recompute-floor` CLI subcommand

**Files:**
- Modify: `agents/watcher/agent.py`
- Modify: `agents/watcher/floor_state.py`
- Modify: `agents/watcher/tests/test_floor_state.py`

- [ ] **Step 1: Write the failing test**

Append to `agents/watcher/tests/test_floor_state.py`:

```python
from agents.watcher.floor_state import recompute_floor


class TestRecomputeFloor:
    def test_recompute_aggregates_findings_into_state(self, tmp_path):
        # Synthesize a minimal findings.jsonl fixture
        findings_file = tmp_path / "findings.jsonl"
        rows = []
        # 15 confirmed + 0 fp dismissed for P1/app → ci_lower should be high
        for _ in range(15):
            rows.append({
                "pattern": "P1",
                "file": "/repo/src/x.py",
                "line": 1,
                "hint": "h",
                "severity": "medium",
                "status": "confirmed",
                "detected_at": "2026-04-20T00:00:00Z",
                "confirmed_at": "2026-04-21T00:00:00Z",
                "fingerprint": f"abcd{_:04d}",
                "violation_class": "BEH",
            })
        # 12 fp-dismissed for P2/test
        for i in range(12):
            rows.append({
                "pattern": "P2",
                "file": "/repo/tests/test_x.py",
                "line": 1,
                "hint": "h",
                "severity": "medium",
                "status": "dismissed",
                "detected_at": "2026-04-20T00:00:00Z",
                "dismissed_at": "2026-04-21T00:00:00Z",
                "resolution_reason": "fp",
                "fingerprint": f"efgh{i:04d}",
                "violation_class": "BEH",
            })

        with findings_file.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

        state = recompute_floor(findings_file=findings_file, state_dir=tmp_path)
        # P1/app: 15 confirmed, 0 dismissed → high ci_lower
        b1 = state.get("P1", "app")
        assert b1 is not None
        assert b1.ci_lower is not None
        assert b1.ci_lower > 0.7
        # P2/test: 0 confirmed, 12 dismissed → ci_lower ~0
        b2 = state.get("P2", "test")
        assert b2 is not None
        assert b2.ci_lower is not None
        assert b2.ci_lower < 0.3
        # State persisted to disk
        from agents.watcher.floor_state import load_floor
        reloaded = load_floor(state_dir=tmp_path)
        assert ("P1", "app") in reloaded.buckets
        assert ("P2", "test") in reloaded.buckets
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest agents/watcher/tests/test_floor_state.py::TestRecomputeFloor -v --no-cov
```

Expected: ImportError on `recompute_floor`.

- [ ] **Step 3: Implement `recompute_floor`**

Append to `agents/watcher/floor_state.py`:

```python
def recompute_floor(
    *,
    findings_file: Path | None = None,
    state_dir: Path | None = None,
    half_life_days: float = 30.0,
    min_weighted_n: float = 10.0,
    now: datetime | None = None,
) -> FloorState:
    """Read findings.jsonl, aggregate per-(pattern, file_class), persist.

    Returns the new FloorState. Designed to be called nightly (cron) or
    from the ``--recompute-floor`` CLI for ad-hoc rebuilds.
    """
    from agents.watcher.calibration import precision_by_pattern_and_class
    from agents.watcher.findings import FINDINGS_FILE, _iter_findings_raw

    if findings_file is None:
        rows = _iter_findings_raw()
    else:
        # Test path: load directly from the supplied file
        rows = []
        if findings_file.exists():
            with findings_file.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    reference = now or datetime.now(timezone.utc)
    buckets = precision_by_pattern_and_class(
        rows,
        now=reference,
        half_life_days=half_life_days,
        min_weighted_n=min_weighted_n,
    )

    state = FloorState(
        updated_at=reference.strftime("%Y-%m-%dT%H:%M:%SZ"),
        buckets=buckets,
    )
    save_floor(state, state_dir=state_dir)
    return state
```

- [ ] **Step 4: Wire CLI subcommand**

Find the argparse setup in `agents/watcher/agent.py` (search for `add_argument` / `argparse.ArgumentParser`). Add the flag near the other lifecycle flags (`--resolve` / `--dismiss`):

```python
parser.add_argument(
    "--recompute-floor",
    action="store_true",
    help="Recompute pattern_floor.json from findings.jsonl and persist.",
)
```

Add the dispatch branch in the main CLI handler (alongside `--resolve` / `--dismiss`):

```python
if args.recompute_floor:
    from agents.watcher.floor_state import recompute_floor
    state = recompute_floor()
    log(
        f"recompute_floor: {len(state.buckets)} bucket(s) "
        f"updated_at={state.updated_at}"
    )
    print(f"ok: {len(state.buckets)} bucket(s) at {state.updated_at}")
    return 0
```

- [ ] **Step 5: Run tests + manual smoke**

```bash
pytest agents/watcher/tests/test_floor_state.py -v --no-cov
```

Expected: PASS (8 tests including the new TestRecomputeFloor).

```bash
python3 agents/watcher/agent.py --recompute-floor
```

Expected: `ok: <N> bucket(s) at <iso-timestamp>` printed; `data/watcher/pattern_floor.json` exists and is valid JSON.

- [ ] **Step 6: Commit**

```bash
git add agents/watcher/floor_state.py agents/watcher/agent.py agents/watcher/tests/test_floor_state.py
git commit -m "feat(watcher): --recompute-floor CLI + recompute_floor entry point

Reads findings.jsonl → aggregates per-(pattern, file_class) → persists
to pattern_floor.json atomically. Designed for nightly Vigil cron and
ad-hoc operator rebuilds."
```

### Task A.7: ε-greedy probe selection

**Files:**
- Modify: `agents/watcher/calibration.py`
- Modify: `agents/watcher/tests/test_calibration.py`

- [ ] **Step 1: Write the failing tests**

Append to `agents/watcher/tests/test_calibration.py`:

```python
from agents.watcher.calibration import probe_rate_for_n, should_probe


class TestProbeRateForN:
    """Adaptive probe rate. Smaller buckets need higher exploration so
    they can acquire signal; larger buckets settle into exploit mode.

    Schedule:
      - n < 10: probe rate = 1.0 (no demotion at all — handled at callsite)
      - 10 ≤ n < 30: probe rate = 1/3
      - 30 ≤ n < 100: probe rate = 1/5
      - n ≥ 100: probe rate = 1/10
    """

    def test_below_min_n_full_probe(self):
        assert probe_rate_for_n(0) == 1.0
        assert probe_rate_for_n(9) == 1.0

    def test_low_n_high_probe(self):
        assert probe_rate_for_n(10) == pytest.approx(1.0 / 3.0)
        assert probe_rate_for_n(29) == pytest.approx(1.0 / 3.0)

    def test_mid_n_moderate_probe(self):
        assert probe_rate_for_n(30) == pytest.approx(1.0 / 5.0)
        assert probe_rate_for_n(99) == pytest.approx(1.0 / 5.0)

    def test_high_n_low_probe(self):
        assert probe_rate_for_n(100) == pytest.approx(1.0 / 10.0)
        assert probe_rate_for_n(1000) == pytest.approx(1.0 / 10.0)


class TestShouldProbe:
    """Deterministic probe selection: hash of (fingerprint, today) →
    bool. Same finding probes consistently within a day; over many days
    the probe rate converges to ``probe_rate_for_n``."""

    def test_deterministic_within_day(self):
        a = should_probe("abc123", date_iso="2026-04-27", probe_rate=0.5)
        b = should_probe("abc123", date_iso="2026-04-27", probe_rate=0.5)
        assert a == b

    def test_different_fingerprints_distribute(self):
        rate = 0.2
        results = [
            should_probe(f"fp{i:04d}", date_iso="2026-04-27", probe_rate=rate)
            for i in range(2000)
        ]
        observed = sum(results) / len(results)
        # 2000 samples at rate=0.2 → SE ≈ 0.009; 5σ window is ~0.045
        assert abs(observed - rate) < 0.05

    def test_zero_rate_never_probes(self):
        assert should_probe("abc", date_iso="2026-04-27", probe_rate=0.0) is False

    def test_one_rate_always_probes(self):
        assert should_probe("abc", date_iso="2026-04-27", probe_rate=1.0) is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_calibration.py::TestProbeRateForN agents/watcher/tests/test_calibration.py::TestShouldProbe -v --no-cov
```

Expected: ImportError.

- [ ] **Step 3: Implement probe selection**

Append to `agents/watcher/calibration.py`:

```python
# ---------------------------------------------------------------------------
# ε-greedy probe selection
# ---------------------------------------------------------------------------


def probe_rate_for_n(weighted_n: float) -> float:
    """Adaptive ε for the demotion exploration policy.

    Below the min-N gate (``< 10``) we don't demote at all — return 1.0
    for completeness (no demotion → all surface). Above min-N, the rate
    steps down with bucket maturity. Stepped (not continuous) so the
    behavior is easy to reason about and tweak.
    """
    if weighted_n < 10.0:
        return 1.0
    if weighted_n < 30.0:
        return 1.0 / 3.0
    if weighted_n < 100.0:
        return 1.0 / 5.0
    return 1.0 / 10.0


def should_probe(fingerprint: str, *, date_iso: str, probe_rate: float) -> bool:
    """Deterministic per-(fingerprint, day) probe decision.

    Hashing on ``(fingerprint, day)`` means a given finding is either
    probed for the whole day or not — no flicker as the surface hook
    fires repeatedly within a session. Across days the choice
    re-randomizes, so a demoted bucket has a path back to visibility.

    The hash is sha256 over the joined string; we take the first 8 hex
    chars as an unsigned int and divide by 2**32. Cryptographic strength
    isn't required, but using sha256 means we don't need to import
    Python's per-process randomized hash() and the test suite is
    reproducible across runs.
    """
    if probe_rate >= 1.0:
        return True
    if probe_rate <= 0.0:
        return False
    import hashlib

    digest = hashlib.sha256(f"{fingerprint}|{date_iso}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / float(0x1_00000000)
    return bucket < probe_rate
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_calibration.py::TestProbeRateForN agents/watcher/tests/test_calibration.py::TestShouldProbe -v --no-cov
```

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/watcher/calibration.py agents/watcher/tests/test_calibration.py
git commit -m "feat(watcher): adaptive ε-greedy probe selection

Smaller buckets explore more (1/3 at 10≤n<30) so they can acquire
signal; mature buckets settle into exploit (1/10 at n≥100). Hashed
on (fingerprint, day) so the choice is deterministic within a day
but re-randomizes across days — a demoted bucket always has a path
back to visibility. This is the structural fix for the cold trap
the council flagged."
```

### Task A.8: Wire demotion + probe into surfacing

**Files:**
- Modify: `agents/watcher/findings.py`
- Create: `agents/watcher/tests/test_demotion_logic.py`

- [ ] **Step 1: Write the failing tests**

```python
# agents/watcher/tests/test_demotion_logic.py
"""Tests for demotion + probe behavior in _format_findings_block.

Behavior matrix:

  ci_lower=None (unmeasured) → no demotion, original severity surfaces
  ci_lower≥0.3                → no demotion
  ci_lower<0.3 AND probe       → exempt (surface at original severity)
  ci_lower<0.3 AND no probe    → demote one severity notch

Demotion ladder: critical → high → medium → low. Low never demotes
further (it's already file-only)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agents.watcher.calibration import BucketStats
from agents.watcher.findings import _format_findings_block, _apply_floor_to_finding
from agents.watcher.floor_state import FloorState


def _f(*, pattern, severity, fingerprint, file="/repo/src/x.py"):
    return {
        "pattern": pattern,
        "file": file,
        "line": 1,
        "hint": "h",
        "severity": severity,
        "status": "open",
        "detected_at": "2026-04-27T00:00:00Z",
        "fingerprint": fingerprint,
        "violation_class": "BEH",
    }


def _bucket(*, ci, n=15.0):
    return BucketStats(
        pattern="X",
        file_class="app",
        weighted_confirmed=n,
        weighted_dismissed=0.0,
        weighted_n=n,
        ci_lower=ci,
        latest_observation="2026-04-26T00:00:00Z",
    )


class TestApplyFloorToFinding:
    TODAY = "2026-04-27"

    def test_unmeasured_bucket_no_demotion(self):
        """ci_lower=None means weighted_n < min — no demotion fires."""
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=None, n=5.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"
        assert out.get("calibration_demoted_from") is None

    def test_high_ci_no_demotion(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.85)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"

    def test_low_ci_no_probe_demotes(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="zzzz9999")
        # Force probe-off
        with patch("agents.watcher.findings.should_probe", return_value=False):
            out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "medium"
        assert out["calibration_demoted_from"] == "high"

    def test_low_ci_probe_exempts(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        finding = _f(pattern="P1", severity="high", fingerprint="abcd1234")
        with patch("agents.watcher.findings.should_probe", return_value=True):
            out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"
        assert out.get("calibration_probe") is True

    def test_demotion_ladder(self):
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        with patch("agents.watcher.findings.should_probe", return_value=False):
            for src, expected in [
                ("critical", "high"),
                ("high", "medium"),
                ("medium", "low"),
                ("low", "low"),  # bottom of ladder, no further demotion
            ]:
                finding = _f(pattern="P1", severity=src, fingerprint="abcd1234")
                out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
                assert out["severity"] == expected, f"{src} should demote to {expected}"

    def test_pattern_not_in_floor_no_demotion(self):
        floor = FloorState(updated_at="t", buckets={})
        finding = _f(pattern="UNKNOWN", severity="high", fingerprint="abcd1234")
        out = _apply_floor_to_finding(finding, floor=floor, today=self.TODAY)
        assert out["severity"] == "high"


class TestFormatBlockWithFloor:
    def test_demoted_high_does_not_appear_in_block_when_dropped_to_low(self):
        """High → medium still surfaces (medium shows under cap). High → low (via two
        demotions across separate runs) doesn't, since low is file-only. Verify the
        single-step demotion still keeps the finding visible."""
        floor = FloorState(updated_at="t", buckets={
            ("P1", "app"): _bucket(ci=0.10, n=15.0)
        })
        rows = [_f(pattern="P1", severity="high", fingerprint="abcd1234")]
        with patch("agents.watcher.findings.load_floor", return_value=floor), \
             patch("agents.watcher.findings.should_probe", return_value=False):
            block, shown = _format_findings_block(rows, header="hdr")
        assert block is not None
        assert "[MEDIUM]" in block, "demoted-to-medium should still surface"
        assert len(shown) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_demotion_logic.py -v --no-cov
```

Expected: ImportError on `_apply_floor_to_finding` and missing `load_floor` import in findings.

- [ ] **Step 3: Add the demotion helper to findings.py**

Open `agents/watcher/findings.py`. Just below the imports block, add:

```python
from agents.watcher.calibration import (
    classify_file,
    probe_rate_for_n,
    should_probe,
)
from agents.watcher.floor_state import FloorState, load_floor
```

Then add the demotion helper near the other private helpers (above `_format_findings_block`):

```python
_SEVERITY_DEMOTION_LADDER = {
    "critical": "high",
    "high": "medium",
    "medium": "low",
    "low": "low",
}


def _apply_floor_to_finding(
    finding: dict,
    *,
    floor: FloorState,
    today: str,
) -> dict:
    """Return a copy of ``finding`` with severity demoted if the
    pattern's calibration floor has fallen below 0.3 and the finding
    isn't selected for an ε-greedy exploration probe.

    Adds two diagnostic fields when a decision fires:
      ``calibration_demoted_from`` — original severity (set on demote)
      ``calibration_probe`` — True (set when bucket below floor but probe carved out)

    These are rendered nowhere user-visible; they exist for downstream
    audit / future dashboard panels.
    """
    pattern = finding.get("pattern", "")
    file_path = finding.get("file", "")
    severity = finding.get("severity", "low")
    fingerprint = finding.get("fingerprint", "")

    file_class = classify_file(file_path)
    bucket = floor.get(pattern, file_class)
    if bucket is None or bucket.ci_lower is None or bucket.ci_lower >= 0.3:
        return finding  # unmeasured or healthy → no change

    # Below the precision floor. ε-greedy probe might exempt this finding.
    rate = probe_rate_for_n(bucket.weighted_n)
    if should_probe(fingerprint, date_iso=today, probe_rate=rate):
        out = dict(finding)
        out["calibration_probe"] = True
        return out

    new_severity = _SEVERITY_DEMOTION_LADDER.get(severity, severity)
    if new_severity == severity:
        return finding  # already at the bottom of the ladder
    out = dict(finding)
    out["severity"] = new_severity
    out["calibration_demoted_from"] = severity
    return out
```

- [ ] **Step 4: Wire `_apply_floor_to_finding` into `_format_findings_block`**

In `agents/watcher/findings.py`, modify `_format_findings_block` so that immediately after the `if not findings and not out_of_scope_groups:` early-return, it loads the floor and rewrites each finding through `_apply_floor_to_finding`. Insert this block right after the early return:

```python
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    floor = load_floor()
    findings = [
        _apply_floor_to_finding(f, floor=floor, today=today)
        for f in findings
    ]
```

Place this *before* the existing `severity_order = {...}` sort line so the sort sees the demoted severities.

Also add a single-line log of any demotion immediately after the rewrite:

```python
    for f in findings:
        if "calibration_demoted_from" in f:
            log(
                f"calibration: demoted {f.get('pattern','?')} on "
                f"{f.get('file','?')} from {f['calibration_demoted_from']} "
                f"to {f.get('severity','?')} (ci_lower below floor)",
                "info",
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_demotion_logic.py -v --no-cov
```

Expected: 9 PASS.

- [ ] **Step 6: Run full watcher suite**

```bash
pytest agents/watcher/tests/ --no-cov --tb=short -q
```

Expected: all tests pass — no regression in the existing 145.

- [ ] **Step 7: Commit**

```bash
git add agents/watcher/findings.py agents/watcher/tests/test_demotion_logic.py
git commit -m "feat(watcher): demote findings whose precision floor fell below 0.3

_format_findings_block reads pattern_floor.json and demotes one
severity notch when the (pattern, file_class) bucket's Jeffreys
lower bound is below 0.3. ε-greedy probe (1-in-K, K adaptive on N)
exempts a fraction of findings so demoted buckets keep accumulating
signal — closes the cold trap the council flagged.

Unmeasured buckets (ci_lower=None) never demote: 'no signal' is not
'low precision'."
```

### Task A.9: `--reason` enum on `--dismiss`

**Files:**
- Modify: `agents/watcher/findings.py`
- Modify: `agents/watcher/agent.py`
- Create: `agents/watcher/tests/test_reason_taxonomy.py`

- [ ] **Step 1: Write the failing tests**

```python
# agents/watcher/tests/test_reason_taxonomy.py
"""--reason enum: only certain reasons mean 'false positive'. Others
(wont_fix, out_of_scope, dup, unclear, stale) document operator intent
without claiming the finding was wrong, and are excluded from the
precision math."""

import json
from pathlib import Path

import pytest

from agents.watcher.findings import (
    DISMISSAL_REASONS,
    update_finding_status,
)


@pytest.fixture
def findings_file_with_one_open(tmp_path, monkeypatch):
    """Plant a single open finding and point the watcher state-dir at
    tmp_path so the lifecycle helpers operate against it."""
    state_dir = tmp_path / "watcher"
    state_dir.mkdir()
    findings_file = state_dir / "findings.jsonl"
    row = {
        "pattern": "P1",
        "file": "/repo/src/x.py",
        "line": 1,
        "hint": "h",
        "severity": "medium",
        "status": "open",
        "detected_at": "2026-04-27T00:00:00Z",
        "fingerprint": "abcd1234efgh5678",
        "violation_class": "BEH",
    }
    findings_file.write_text(json.dumps(row) + "\n")

    # Redirect module globals to the tmp dir
    monkeypatch.setattr("agents.watcher.findings.STATE_DIR", state_dir)
    monkeypatch.setattr("agents.watcher.findings.FINDINGS_FILE", findings_file)
    monkeypatch.setattr("agents.watcher.findings.DEDUP_FILE", state_dir / "dedup.json")
    return findings_file


def test_valid_reasons_constant_shape():
    assert "fp" in DISMISSAL_REASONS
    assert "wont_fix" in DISMISSAL_REASONS
    assert "out_of_scope" in DISMISSAL_REASONS
    assert "dup" in DISMISSAL_REASONS
    assert "unclear" in DISMISSAL_REASONS
    assert "stale" in DISMISSAL_REASONS


def test_dismiss_with_valid_reason_persists_it(findings_file_with_one_open, monkeypatch):
    monkeypatch.setattr(
        "agents.watcher.agent._post_resolution_event", lambda *a, **kw: None
    )
    rc = update_finding_status("abcd1234", "dismissed", reason="fp")
    assert rc == 0
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    assert persisted["status"] == "dismissed"
    assert persisted["resolution_reason"] == "fp"


def test_dismiss_with_invalid_reason_rejected(findings_file_with_one_open):
    rc = update_finding_status("abcd1234", "dismissed", reason="just because")
    assert rc == 2
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    # Status must NOT have changed
    assert persisted["status"] == "open"


def test_dismiss_without_reason_still_works(findings_file_with_one_open, monkeypatch):
    """Backward compat: existing scripts don't pass a reason. Status
    transitions, but resolution_reason is unset (treated as 'unknown'
    by precision math, i.e. excluded from TN counts)."""
    monkeypatch.setattr(
        "agents.watcher.agent._post_resolution_event", lambda *a, **kw: None
    )
    rc = update_finding_status("abcd1234", "dismissed", reason=None)
    assert rc == 0
    persisted = json.loads(findings_file_with_one_open.read_text().strip())
    assert persisted["status"] == "dismissed"
    assert "resolution_reason" not in persisted
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_reason_taxonomy.py -v --no-cov
```

Expected: ImportError on `DISMISSAL_REASONS`.

- [ ] **Step 3: Add the enum + validation**

In `agents/watcher/findings.py`, add the constant near `VALID_FINDING_STATUSES`:

```python
DISMISSAL_REASONS = frozenset({"fp", "wont_fix", "out_of_scope", "dup", "unclear", "stale"})
```

Modify `update_finding_status` to validate `reason` against `DISMISSAL_REASONS` when `new_status == "dismissed"`:

Find the existing signature:
```python
def update_finding_status(
    fingerprint_prefix: str,
    new_status: str,
    resolver_agent_id: str | None = None,
    reason: str | None = None,
) -> int:
```

Right after the existing `if new_status not in VALID_FINDING_STATUSES:` validation, add:

```python
    if new_status == "dismissed" and reason is not None and reason not in DISMISSAL_REASONS:
        log(f"update_finding_status: invalid reason {reason!r}", "error")
        print(
            f"error: invalid reason {reason!r}; must be one of "
            f"{sorted(DISMISSAL_REASONS)}"
        )
        return 2
```

- [ ] **Step 4: Wire CLI flag**

In `agents/watcher/agent.py`, find the argparse setup and modify the `--dismiss` definition (or add the flag adjacent to it) to include:

```python
parser.add_argument(
    "--reason",
    choices=sorted({"fp", "wont_fix", "out_of_scope", "dup", "unclear", "stale"}),
    default=None,
    help="Why this finding is being dismissed. 'fp' = false positive (counts as TN "
         "in precision math). Others document operator intent without claiming the "
         "finding was wrong, and are excluded from precision.",
)
```

Find the `--dismiss` dispatch branch and pass `args.reason` to `update_finding_status`:

```python
return update_finding_status(args.dismiss, "dismissed", resolver_agent_id=args.agent_id, reason=args.reason)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_reason_taxonomy.py -v --no-cov
```

Expected: 4 PASS.

- [ ] **Step 6: Run full watcher suite**

```bash
pytest agents/watcher/tests/ --no-cov --tb=short -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agents/watcher/findings.py agents/watcher/agent.py agents/watcher/tests/test_reason_taxonomy.py
git commit -m "feat(watcher): --reason enum {fp, wont_fix, out_of_scope, dup, unclear, stale}

Only 'fp' counts as a TN in precision math. The others document
operator intent (this finding is correct but I won't fix it / it's
out of scope / it's a duplicate / I'm not sure / the file is gone)
and are excluded from the dismissed count so they don't suppress a
correct pattern.

Backward compat: --dismiss without --reason still works; the
resulting row has no resolution_reason and is excluded from
precision math entirely (same as legacy free-text rows)."
```

### Task A.10: Replace dishonest warmup in `compute_checkin_confidence`

**Files:**
- Modify: `agents/watcher/agent.py`
- Modify: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `agents/watcher/tests/test_agent.py`:

```python
class TestCheckinConfidenceWarmup:
    """The previous warmup default of 0.7 at N<5 was overconfidence
    shipped to governance. Replace with the Jeffreys posterior point
    estimate (mean of Beta(0.5+s, 0.5+f)), which degrades gracefully
    to 0.5 at N=0 and tracks the data thereafter."""

    def test_no_data_neutral(self):
        from agents.watcher.agent import compute_checkin_confidence
        assert compute_checkin_confidence(0, 0) == pytest.approx(0.5)

    def test_one_each_near_neutral(self):
        from agents.watcher.agent import compute_checkin_confidence
        # Beta(1.5, 1.5) mean = 0.5
        assert compute_checkin_confidence(1, 1) == pytest.approx(0.5)

    def test_unanimous_confirmed_high(self):
        from agents.watcher.agent import compute_checkin_confidence
        # Beta(20.5, 0.5) mean ≈ 0.976
        result = compute_checkin_confidence(20, 0)
        assert result > 0.95

    def test_unanimous_dismissed_low(self):
        from agents.watcher.agent import compute_checkin_confidence
        result = compute_checkin_confidence(0, 20)
        assert result < 0.05

    def test_does_not_return_07_at_small_n(self):
        """The previous code returned 0.7 for any total<5. Confirm the
        new implementation does NOT exhibit this behavior."""
        from agents.watcher.agent import compute_checkin_confidence
        # 0.7 was the old warmup for total < 5. Verify several small-N
        # cases all differ from 0.7.
        for s, f in [(0, 0), (1, 0), (0, 1), (2, 0), (0, 2), (2, 2)]:
            result = compute_checkin_confidence(s, f)
            # Either >0.7 (lots of confirms) or <0.7 (lots of dismisses)
            # or near 0.5 (balanced) — but never *exactly* 0.7 like the
            # old code's hardcoded warmup.
            assert abs(result - 0.7) > 0.05 or s + f >= 5, (
                f"({s},{f}) → {result}: looks like the old hardcoded warmup"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest agents/watcher/tests/test_agent.py::TestCheckinConfidenceWarmup -v --no-cov
```

Expected: FAIL on `test_no_data_neutral` (current code returns 0.7).

- [ ] **Step 3: Replace the warmup**

In `agents/watcher/agent.py`, replace the existing `compute_checkin_confidence`:

```python
def compute_checkin_confidence(confirmed: int, dismissed: int) -> float:
    """Posterior mean of Beta(0.5+confirmed, 0.5+dismissed).

    Replaces the old 'return 0.7 if total<5 else confirmed/total'
    warmup, which was overconfidence shipped to governance: a freshly
    deployed Watcher with zero observations was claiming 0.7 confidence
    in its own findings. With the Jeffreys prior, no observations
    yields exactly 0.5 (true neutrality) and the value tracks the data
    smoothly as it accumulates.
    """
    if confirmed < 0 or dismissed < 0:
        return 0.5
    alpha = 0.5 + confirmed
    beta = 0.5 + dismissed
    return alpha / (alpha + beta)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest agents/watcher/tests/test_agent.py::TestCheckinConfidenceWarmup -v --no-cov
```

Expected: 5 PASS.

- [ ] **Step 5: Run full watcher suite — older tests may pin the old warmup**

```bash
pytest agents/watcher/tests/ --no-cov --tb=short -q
```

If a pre-existing test asserted the 0.7 warmup behavior directly, update it to assert the new Jeffreys behavior in the same commit. Search:

```bash
grep -n "0.7\|warmup" agents/watcher/tests/test_agent.py
```

If matches reference `compute_checkin_confidence`, update them to expect the new behavior (Beta(0.5+s, 0.5+f) posterior mean) rather than the hardcoded 0.7.

- [ ] **Step 6: Commit**

```bash
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "fix(watcher): replace dishonest 0.7 warmup with Jeffreys posterior mean

The old compute_checkin_confidence returned 0.7 for total<5 — overconfidence
shipped to governance with no observational support. A freshly deployed
Watcher with zero confirmed/dismissed history was telling the calibration
system 'I'm 70% sure'.

Replaced with the Beta(0.5+s, 0.5+f) posterior mean: no data → 0.5
(neutral), tracks the data smoothly thereafter, no magic constant."
```

### Task A.11: Vigil cron entry for nightly recompute

**Files:**
- Modify: `agents/vigil/agent.py` OR the Vigil entry plist (whichever is canonical here)

This task is about wiring the existing Vigil resident to call `--recompute-floor` once per day. Vigil already runs every 30min via launchd; we add a "once-per-24h" guard inside Vigil so the recompute fires at most once per day per host.

- [ ] **Step 1: Locate Vigil's task list**

```bash
grep -rn "vigil\|recompute\|task" agents/vigil/ 2>/dev/null | head -20
ls agents/vigil/
```

Identify how Vigil's tasks are registered (likely a list of callables in `agents/vigil/agent.py` or a tasks/ subdir).

- [ ] **Step 2: Write the failing test**

Append to `agents/vigil/tests/test_*.py` (or create `agents/vigil/tests/test_calibration_task.py`):

```python
"""Vigil should recompute the watcher pattern_floor.json once per day."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch


def test_vigil_recomputes_floor_when_stale(tmp_path):
    """If the last recompute timestamp is >24h old, Vigil triggers
    a fresh recompute."""
    from agents.vigil.agent import maybe_recompute_watcher_floor

    last = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sentinel_called = []

    def fake_recompute(**kwargs):
        sentinel_called.append(True)
        from agents.watcher.floor_state import FloorState
        return FloorState(updated_at="now", buckets={})

    with patch("agents.vigil.agent.recompute_floor", side_effect=fake_recompute):
        with patch(
            "agents.vigil.agent._last_floor_recompute_iso",
            return_value=last,
        ):
            maybe_recompute_watcher_floor()
    assert sentinel_called == [True]


def test_vigil_skips_recompute_when_fresh():
    from agents.vigil.agent import maybe_recompute_watcher_floor

    last = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sentinel_called = []

    with patch("agents.vigil.agent.recompute_floor", side_effect=lambda **kw: sentinel_called.append(True)):
        with patch(
            "agents.vigil.agent._last_floor_recompute_iso",
            return_value=last,
        ):
            maybe_recompute_watcher_floor()
    assert sentinel_called == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest agents/vigil/tests/test_calibration_task.py -v --no-cov
```

Expected: ImportError.

- [ ] **Step 4: Implement the maybe-recompute hook**

Add to `agents/vigil/agent.py`:

```python
from datetime import datetime, timedelta, timezone

from agents.watcher.floor_state import load_floor, recompute_floor


def _last_floor_recompute_iso() -> str | None:
    """Read pattern_floor.json's updated_at field. Used to gate the
    daily recompute — a 30min Vigil cycle means we'd otherwise recompute
    48× per day."""
    try:
        return load_floor().updated_at
    except Exception:
        return None


def maybe_recompute_watcher_floor(*, max_age_hours: float = 24.0) -> bool:
    """Trigger a watcher floor recompute if the last one is older than
    ``max_age_hours``. Returns True if a recompute fired.
    """
    last_iso = _last_floor_recompute_iso()
    if last_iso:
        try:
            last = datetime.strptime(last_iso, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            age = datetime.now(timezone.utc) - last
            if age < timedelta(hours=max_age_hours):
                return False
        except (TypeError, ValueError):
            pass  # unparseable → recompute (safer to refresh than skip)
    recompute_floor()
    return True
```

Wire `maybe_recompute_watcher_floor` into Vigil's regular task pipeline (alongside the other 30min tasks).

- [ ] **Step 5: Run tests**

```bash
pytest agents/vigil/tests/test_calibration_task.py -v --no-cov
```

Expected: 2 PASS.

- [ ] **Step 6: Smoke test end-to-end**

```bash
python3 agents/vigil/agent.py --once  # or whatever the manual-trigger flag is
ls -la data/watcher/pattern_floor.json
```

Expected: `pattern_floor.json` exists; if it pre-existed and was <24h old, `updated_at` should be unchanged. Touch it backwards in time (`touch -t 202604200000 data/watcher/pattern_floor.json` won't change the JSON content; instead manually edit the `updated_at` field to a 25h-old timestamp) and re-run to confirm the recompute fires.

- [ ] **Step 7: Commit**

```bash
git add agents/vigil/agent.py agents/vigil/tests/test_calibration_task.py
git commit -m "feat(vigil): nightly recompute of watcher pattern_floor.json

Vigil cycles every 30min, so we gate recompute on a 24h staleness
check against pattern_floor.json's updated_at. Avoids recomputing
48× per day while still keeping the floor fresh enough for the
demotion logic."
```

---

## Phase A Final Verification

Before declaring Phase A done, run the full repo suite and the council's verification trail.

- [ ] **Step 1: Run the test cache**

```bash
./scripts/dev/test-cache.sh
```

Expected: PASS (or `(cached)` if no further changes).

- [ ] **Step 2: Smoke the end-to-end loop**

```bash
# Resolve a finding with a reason
python3 agents/watcher/agent.py --resolve <fingerprint>
# Dismiss with --reason fp (counts as TN)
python3 agents/watcher/agent.py --dismiss <fingerprint> --reason fp
# Dismiss with --reason wont_fix (excluded from precision)
python3 agents/watcher/agent.py --dismiss <fingerprint> --reason wont_fix
# Recompute floor
python3 agents/watcher/agent.py --recompute-floor
# Inspect
cat data/watcher/pattern_floor.json | python3 -m json.tool | head -40
```

- [ ] **Step 3: Confirm the resolution event reaches governance**

```bash
# Tail the governance MCP log while running --resolve
tail -f data/logs/mcp_server.log &
TAIL_PID=$!
python3 agents/watcher/agent.py --resolve <fingerprint>
sleep 2
kill $TAIL_PID
```

Expected: a log line acknowledging a `watcher_resolution_finding` event (no HTTP 400). If the verifier's claim (Phase 0 fix) was correct, this should now succeed where it silently failed before.

- [ ] **Step 4: Confirm cold-trap exit**

Manually plant a low-precision bucket via fixture, run `_format_findings_block` over a sample finding 30 times with day-of-month varying, and count probe-exempt surfaces. With `n=15` and probe rate `1/3`, ~10 of 30 should surface at original severity.

```bash
python3 -c "
from datetime import datetime, timezone
from agents.watcher.calibration import BucketStats, should_probe, probe_rate_for_n
n = 15
rate = probe_rate_for_n(n)
exempt = sum(should_probe('test_fp_xx', date_iso=f'2026-04-{d:02d}', probe_rate=rate)
             for d in range(1, 31))
print(f'rate={rate:.3f} exempt {exempt}/30 over a month')
"
```

Expected: `rate=0.333 exempt 10/30` ± a few.

---

## Self-Review

**Spec coverage:**

- Phase 0 dead-path fix ✓ (Task 0.1)
- Jeffreys lower bound ✓ (A.1)
- File classifier ✓ (A.2)
- Exponential decay ✓ (A.3)
- Per-(pattern × file_class) precision aggregator ✓ (A.4)
- Atomic floor persistence ✓ (A.5)
- `--recompute-floor` CLI ✓ (A.6)
- ε-greedy probe ✓ (A.7)
- Surfacing demotion + probe ✓ (A.8)
- `--reason` enum ✓ (A.9)
- Honest warmup in `compute_checkin_confidence` ✓ (A.10)
- Vigil nightly cron ✓ (A.11)

**Out of scope (intentionally deferred):**
- Phase B: `confidence` field on Finding dataclass (separate plan)
- Phase C: `outcome_event` MCP enum extension on the governance side (separate plan, requires governance schema migration)
- Dismissal-reversal cooldown table (separate plan; meta-guard against reflexive-dismiss attack)

**Placeholder scan:**

No "TBD", "implement later", "appropriate error handling", "similar to Task N", or unbacked references. The Vigil task in A.11 has a step "Locate Vigil's task list" that's exploratory rather than prescriptive — acceptable because Vigil's internal structure isn't in the council brief; the implementer will discover it on first pass.

**Type consistency:**

- `BucketStats` defined in calibration.py (A.4), consumed by floor_state.py (A.5), tested with the same fields throughout
- `FloorState.get(pattern, file_class) -> BucketStats | None` consistent across A.5/A.8
- `probe_rate_for_n(weighted_n) -> float` and `should_probe(fingerprint, date_iso, probe_rate)` signatures consistent across A.7/A.8
- `DISMISSAL_REASONS` and `PRECISION_REASONS_TRUE_NEGATIVE` are different sets — DISMISSAL_REASONS is "what the operator may pass on the CLI" (6 values), PRECISION_REASONS_TRUE_NEGATIVE is "what counts toward FP for precision math" (just `{fp}`). Both names appear in Phase A and the distinction is preserved.

---

## Council follow-up

Per `feedback_council-also-for-implementation`, runtime/hook code that can brick a fleet pipeline gets a council pass on the implementation, not just the design. After Phase 0 + Phase A land in feature branch, dispatch parallel:

- `dialectic-knowledge-architect` — verify the conceptual frame survived implementation (still no cold trap, still honest at small N, still robust to operator-reflexive-dismiss)
- `feature-dev:code-reviewer` — adversarial bug-hunt over the actual diffs (concurrent writes, exception paths, drift between calibration.py and surfacing call site)
- `live-verifier` — call the running governance MCP after a `--resolve` to confirm `watcher_resolution_finding` is no longer 400'd, and the resolution event actually lands in the dashboard event ring
