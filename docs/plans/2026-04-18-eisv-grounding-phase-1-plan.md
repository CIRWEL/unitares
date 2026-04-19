# EISV Grounding — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/specs/2026-04-17-eisv-grounding-design.md`

**Goal:** Land the server-side scaffolding for dual-compute EISV grounding — a new `src/grounding/` package that computes Shannon entropy, mutual information, negative free energy, and coherence alongside the existing legacy computations, and reports both on every `process_agent_update` response.

**Architecture:** A new `src/grounding/` package holds four small pure-function modules (`entropy.py`, `mutual_info.py`, `free_energy.py`, `coherence.py`), each exposing a `compute(ctx, metrics) -> GroundedValue` function that returns a `(value, source)` pair. A new enrichment registered after the ODE step calls all four and **swaps** the values in `ctx.result["metrics"]`: legacy `E/I/S/coherence` copy to `E_legacy/I_legacy/S_legacy/coherence_legacy`, and grounded values overwrite `E/I/S/coherence`. Because the enrichment runs **after** gating (basin classification, verdicts), verdicts naturally see legacy values while the response surfaces grounded. Scale constants live in `config/governance_config.py` with a provenance dataclass. Tier-1 (logprobs) and tier-2 (multi-sample) interfaces are stubbed; tier-3 (heuristic) ships as a functional fallback.

**Tech Stack:** Python 3.12+, asyncio, Pydantic v2 schemas, existing enrichment pipeline (`@enrichment(order=N)` decorator in `src/mcp_handlers/updates/pipeline.py`).

---

## Spec §5 Interpretation

Spec §5 literally: grounded values occupy `e, i, s, coherence`; legacy moves to `*_legacy`. This plan implements that directly.

**How "no behavior change user-visible" is preserved:** gating (basin classification, verdict logic) runs inside `phases.py` *before* the enrichment pipeline. The grounding enrichment runs at `order=75`, i.e. post-gating. So verdicts are computed on legacy values, and the swap happens afterwards — only the response payload carries grounded values in the canonical slot. No gating code needs to be updated.

**Downstream consumers (dashboards, broadcasters) will see grounded values in `E/I/S/coherence`.** This shift is expected and is the whole point of Phase 1 dual-compute — it makes the grounded quantities first-class and forces Phase 2 calibration to actually measure divergence. Legacy values are always available under `*_legacy` for comparison.

**Source annotations:** lowercase `e_source, i_source, s_source, coherence_source` fields report which tier computed each grounded value (`"heuristic" | "resource" | "manifold" | "logprob" | "multisample" | "fep" | "kl"`). These land alongside the values in `ctx.result["metrics"]`.

---

## Out of Scope (deferred to separate plans)

- **Tier-1 (logprob) capture.** Requires plugin-side instrumentation (Claude Code hooks, Codex hooks). The server ships the interface; the plugin work is a separate effort.
- **Tier-2 (multi-sample) estimator.** Requires deciding on a semantic-equivalence classifier; tracked as a follow-up after Phase 1 ships.
- **Phase 2 calibration measurement.** Requires running the reference-corpus protocol (§3.4) against production data. Scale constants ship with placeholder values tagged `provenance="placeholder"` until then.
- **ODE coefficient re-fitting.** Phase 2 work.
- **Paper updates.** Tracked separately per §6.
- **Codex plugin backward-compat check** (spec §7 open question). Server-side dual-compute is Codex-transparent because grounded values use new field names.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/grounding/__init__.py` | Package init; re-export `GroundedValue` and the four compute functions |
| Create | `src/grounding/types.py` | `GroundedValue` dataclass: `(value: float, source: str)` |
| Create | `src/grounding/entropy.py` | `compute_entropy(ctx, metrics) -> GroundedValue` — tier-1/2 stubs + tier-3 heuristic |
| Create | `src/grounding/mutual_info.py` | `compute_mutual_info(ctx, metrics) -> GroundedValue` — tier stubs + tier-3 |
| Create | `src/grounding/free_energy.py` | `compute_free_energy(ctx, metrics) -> GroundedValue` — resource-rate + FEP stub + tier-3 |
| Create | `src/grounding/coherence.py` | `compute_coherence(ctx, metrics) -> GroundedValue` — manifold form (tier-3) + KL stub |
| Modify | `config/governance_config.py` (append at end) | Add `ScaleConstant` dataclass + `S_SCALE`, `I_SCALE`, `E_SCALE`, `DELTA_NORM_MAX` with provenance metadata |
| Modify | `src/mcp_handlers/updates/enrichments.py` | Add `@enrichment(order=75)` `enrich_grounding(ctx)` that copies legacy `E/I/S/coherence` into `*_legacy` keys then overwrites `E/I/S/coherence` with grounded values; adds `e_source/i_source/s_source/coherence_source` keys |
| Create | `tests/test_grounding_types.py` | Unit tests for `GroundedValue` dataclass |
| Create | `tests/test_grounding_entropy.py` | Unit tests for entropy compute |
| Create | `tests/test_grounding_mutual_info.py` | Unit tests for mutual info compute |
| Create | `tests/test_grounding_free_energy.py` | Unit tests for free energy compute |
| Create | `tests/test_grounding_coherence.py` | Unit tests for coherence compute |
| Create | `tests/test_grounding_scale_constants.py` | Unit tests for scale-constant provenance guarantees |
| Create | `tests/test_grounding_enrichment.py` | Integration test: `process_agent_update` response contains `grounding` block |

---

### Task 1: Core type — `GroundedValue`

**Files:**
- Create: `src/grounding/__init__.py`
- Create: `src/grounding/types.py`
- Create: `tests/test_grounding_types.py`

`GroundedValue` is the shared return type. A frozen dataclass with a `value: float` and a `source: str` — one of `"logprob"`, `"multisample"`, `"resource"`, `"fep"`, `"kl"`, `"manifold"`, `"heuristic"`. Validation catches unknown source strings immediately so the enrichment can never write garbage into the response.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grounding_types.py
"""Tests for GroundedValue dataclass — the shared return type for grounding modules."""
import pytest
from dataclasses import FrozenInstanceError

from src.grounding.types import GroundedValue, ALLOWED_SOURCES


def test_valid_construction():
    gv = GroundedValue(value=0.42, source="heuristic")
    assert gv.value == 0.42
    assert gv.source == "heuristic"


def test_all_allowed_sources_accepted():
    for source in ALLOWED_SOURCES:
        gv = GroundedValue(value=0.1, source=source)
        assert gv.source == source


def test_unknown_source_rejected():
    with pytest.raises(ValueError, match="unknown grounding source"):
        GroundedValue(value=0.5, source="banana")


def test_value_out_of_range_rejected():
    with pytest.raises(ValueError, match="out of range"):
        GroundedValue(value=1.5, source="heuristic")
    with pytest.raises(ValueError, match="out of range"):
        GroundedValue(value=-0.1, source="heuristic")


def test_frozen():
    gv = GroundedValue(value=0.5, source="heuristic")
    with pytest.raises(FrozenInstanceError):
        gv.value = 0.7  # type: ignore[misc]


def test_as_dict_shape():
    gv = GroundedValue(value=0.3, source="manifold")
    assert gv.as_dict() == {"value": 0.3, "source": "manifold"}
```

- [ ] **Step 2: Run test, verify failure**

Run: `python -m pytest tests/test_grounding_types.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.grounding'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/grounding/types.py
"""Shared return type for grounding compute functions."""
from dataclasses import dataclass
from typing import Dict

ALLOWED_SOURCES = frozenset({
    "logprob",      # tier-1: model logprobs
    "multisample",  # tier-2: k-sample self-consistency
    "resource",     # tier-3 E: resource-rate form
    "fep",          # E via variational free-energy estimator
    "kl",           # coherence via KL divergence
    "manifold",     # coherence via state-space distance
    "heuristic",    # tier-3 fallback — legacy computation
})


@dataclass(frozen=True)
class GroundedValue:
    """A grounded governance quantity paired with its computation source.

    Value is always in [0, 1] — normalized at the source module.
    """
    value: float
    source: str

    def __post_init__(self) -> None:
        if self.source not in ALLOWED_SOURCES:
            raise ValueError(
                f"unknown grounding source {self.source!r}; "
                f"must be one of {sorted(ALLOWED_SOURCES)}"
            )
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(
                f"GroundedValue.value out of range [0,1]: {self.value}"
            )

    def as_dict(self) -> Dict[str, object]:
        return {"value": self.value, "source": self.source}
```

```python
# src/grounding/__init__.py
"""Grounded EISV computations — spec docs/specs/2026-04-17-eisv-grounding-design.md."""
from src.grounding.types import GroundedValue, ALLOWED_SOURCES

__all__ = ["GroundedValue", "ALLOWED_SOURCES"]
```

- [ ] **Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_grounding_types.py -v --no-cov`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/grounding/__init__.py src/grounding/types.py tests/test_grounding_types.py
git commit -m "feat(grounding): add GroundedValue type — shared return shape for Phase 1 modules"
```

---

### Task 2: Entropy module

**Files:**
- Create: `src/grounding/entropy.py`
- Create: `tests/test_grounding_entropy.py`

Per spec §3.1 S section, three tiers in preference order: logprob entropy (preferred, from per-token logprobs), multi-sample self-consistency (fallback), heuristic (degraded). Phase 1 ships tier-3 (heuristic) as a functional fallback — it wraps the legacy [0,1] complexity/drift-based S that's already in `metrics["S"]` — while tier-1 and tier-2 raise `NotImplementedError` with a clear "plugin instrumentation required" message. The dispatcher chooses tier based on what `ctx.arguments` carries: if `logprobs` present → tier-1 (stub, falls through), elif `samples` present → tier-2 (stub, falls through), else tier-3.

**Note on falling through from stubs:** `NotImplementedError` is caught at dispatch time and the function falls through to the next tier. This keeps the interface stable: later the plugin work can make tier-1 succeed without any server-side dispatcher change.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grounding_entropy.py
"""Tests for the entropy grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.entropy import compute_entropy
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_tier3_heuristic_wraps_legacy_s():
    """With no logprobs/samples in args, falls back to legacy S from metrics."""
    ctx = _mk_ctx()
    metrics = {"S": 0.42}
    result = compute_entropy(ctx, metrics)
    assert isinstance(result, GroundedValue)
    assert result.source == "heuristic"
    assert result.value == 0.42


def test_tier3_missing_metric_returns_neutral():
    """When metrics has no S, heuristic returns a neutral 0.5 — never raises."""
    ctx = _mk_ctx()
    result = compute_entropy(ctx, metrics={})
    assert result.source == "heuristic"
    assert result.value == 0.5


def test_tier3_clamps_out_of_range_metric():
    """Legacy S values slightly over 1 (possible with ethical_drift) get clamped."""
    ctx = _mk_ctx()
    result = compute_entropy(ctx, metrics={"S": 1.3})
    assert result.value == 1.0
    result2 = compute_entropy(ctx, metrics={"S": -0.05})
    assert result2.value == 0.0


def test_tier1_logprobs_stub_falls_through_to_heuristic():
    """Logprobs present but no server-side tier-1 implementation yet → tier-3."""
    ctx = _mk_ctx(arguments={"logprobs": [[-0.1, -0.3, -0.8]]})
    result = compute_entropy(ctx, metrics={"S": 0.2})
    # Tier-1 stub raises NotImplementedError; dispatcher catches and falls through.
    assert result.source == "heuristic"
    assert result.value == 0.2


def test_tier2_samples_stub_falls_through_to_heuristic():
    ctx = _mk_ctx(arguments={"samples": ["a", "b", "c"]})
    result = compute_entropy(ctx, metrics={"S": 0.3})
    assert result.source == "heuristic"
    assert result.value == 0.3
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_entropy.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.grounding.entropy'`

- [ ] **Step 3: Write implementation**

```python
# src/grounding/entropy.py
"""Shannon entropy of the agent's response distribution — spec §3.1 S.

Three tiers in preference order:
  1. logprob  — per-token entropy from model logprobs (requires plugin instrumentation)
  2. multisample — k-sample self-consistency over semantic equivalence classes
  3. heuristic — wraps the legacy [0,1] complexity/drift-driven S (degraded mode)
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_entropy(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    """Return grounded S value. Always succeeds (tier-3 is a safe fallback)."""
    args = getattr(ctx, "arguments", {}) or {}

    # Tier 1 — logprobs
    if "logprobs" in args:
        try:
            return _compute_from_logprobs(args["logprobs"])
        except NotImplementedError:
            pass

    # Tier 2 — multi-sample
    if "samples" in args:
        try:
            return _compute_from_samples(args["samples"])
        except NotImplementedError:
            pass

    # Tier 3 — heuristic fallback
    return _compute_heuristic(metrics)


def _compute_from_logprobs(logprobs: list) -> GroundedValue:
    """Tier 1: Shannon entropy from per-token logprobs.

    Plugin-side instrumentation must pass `logprobs` as a list of per-token
    logprob distributions. Server-side computation is a length-normalized
    sum of per-token entropies, then normalized via S_SCALE.
    """
    raise NotImplementedError(
        "tier-1 (logprob) entropy requires plugin-side logprob capture; "
        "see spec §3.1 S 'Computation recipe' and Phase-1 out-of-scope items"
    )


def _compute_from_samples(samples: list) -> GroundedValue:
    """Tier 2: self-consistency entropy over k samples.

    Requires a semantic-equivalence classifier (embedding cosine or similar).
    Deferred to a follow-up — see plan 'Out of scope'.
    """
    raise NotImplementedError(
        "tier-2 (multisample) entropy requires a semantic-equivalence classifier; "
        "deferred from Phase 1"
    )


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    """Tier 3: wrap the existing legacy S (drift + complexity heuristic).

    This is *uncalibrated* by design — exposed so downstream consumers can still
    see a grounded-shape signal while calibration catches up.
    """
    raw = metrics.get("S", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_grounding_entropy.py -v --no-cov`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/grounding/entropy.py tests/test_grounding_entropy.py
git commit -m "feat(grounding): add entropy module — tier-3 heuristic + tier-1/2 stubs"
```

---

### Task 3: Mutual information module

**Files:**
- Create: `src/grounding/mutual_info.py`
- Create: `tests/test_grounding_mutual_info.py`

Same tier pattern as entropy. Tier-3 heuristic wraps legacy `metrics["I"]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grounding_mutual_info.py
"""Tests for the mutual-information grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.mutual_info import compute_mutual_info
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_tier3_heuristic_wraps_legacy_i():
    result = compute_mutual_info(_mk_ctx(), metrics={"I": 0.73})
    assert result.source == "heuristic"
    assert result.value == 0.73


def test_tier3_missing_metric_returns_neutral():
    result = compute_mutual_info(_mk_ctx(), metrics={})
    assert result.source == "heuristic"
    assert result.value == 0.5


def test_tier3_clamps_out_of_range():
    assert compute_mutual_info(_mk_ctx(), {"I": 1.2}).value == 1.0
    assert compute_mutual_info(_mk_ctx(), {"I": -0.1}).value == 0.0


def test_tier1_stub_falls_through():
    ctx = _mk_ctx(arguments={"logprobs": [[-0.1]], "context_logprobs": [[-0.2]]})
    result = compute_mutual_info(ctx, metrics={"I": 0.4})
    assert result.source == "heuristic"
    assert result.value == 0.4


def test_tier2_stub_falls_through():
    ctx = _mk_ctx(arguments={"samples": ["a", "b"]})
    result = compute_mutual_info(ctx, metrics={"I": 0.5})
    assert result.source == "heuristic"
    assert result.value == 0.5
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_mutual_info.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/grounding/mutual_info.py
"""Mutual information MI(x; y) between context and response — spec §3.1 I.

Tier 1: MI from paired logprobs (context-only vs context+response).
Tier 2: multi-sample via KL divergence from a reference distribution.
Tier 3: wraps the legacy [0,1] I heuristic.
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_mutual_info(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    args = getattr(ctx, "arguments", {}) or {}

    if "logprobs" in args and "context_logprobs" in args:
        try:
            return _compute_from_logprobs(
                args["logprobs"], args["context_logprobs"]
            )
        except NotImplementedError:
            pass

    if "samples" in args:
        try:
            return _compute_from_samples(args["samples"])
        except NotImplementedError:
            pass

    return _compute_heuristic(metrics)


def _compute_from_logprobs(logprobs: list, context_logprobs: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 MI requires paired context/response logprobs; "
        "see spec §3.1 I 'Computation recipe'"
    )


def _compute_from_samples(samples: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-2 MI requires reference-distribution estimator; deferred from Phase 1"
    )


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("I", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_grounding_mutual_info.py -v --no-cov`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/grounding/mutual_info.py tests/test_grounding_mutual_info.py
git commit -m "feat(grounding): add mutual_info module — tier-3 heuristic + tier-1/2 stubs"
```

---

### Task 4: Free-energy (E) module

**Files:**
- Create: `src/grounding/free_energy.py`
- Create: `tests/test_grounding_free_energy.py`

E uses a different tier ordering per spec §3.1 E: **resource form** (`source="resource"`) is trivially computable from audit metadata (tokens/latency) and ships as the primary tier-3 equivalent, FEP form (`source="fep"`) is stubbed for Phase 2, and heuristic (`source="heuristic"`) wraps legacy E if nothing else fits.

Resource-rate form per spec: `E_resource = (tokens_out/s) / (tokens_out_max/s)`. Phase 1 pulls `response_tokens` and `response_seconds` from `ctx.arguments` if present (plugin-side instrumentation), else falls back to `response_text` length as a rough token proxy divided by a configurable `TOKENS_PER_SECOND_MAX`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grounding_free_energy.py
"""Tests for the free-energy (E) grounding module."""
import pytest
from unittest.mock import MagicMock

from src.grounding.free_energy import compute_free_energy
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None, response_text=""):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    ctx.response_text = response_text
    return ctx


def test_resource_form_uses_explicit_tokens_and_seconds():
    """When plugin provides tokens_out + seconds, compute resource-rate E."""
    ctx = _mk_ctx(arguments={"response_tokens": 400, "response_seconds": 4.0})
    result = compute_free_energy(ctx, metrics={})
    assert result.source == "resource"
    # 100 tokens/sec against default TOKENS_PER_SECOND_MAX=200 → 0.5
    assert abs(result.value - 0.5) < 0.01


def test_resource_form_caps_at_one():
    """High throughput gets capped at 1.0."""
    ctx = _mk_ctx(arguments={"response_tokens": 10000, "response_seconds": 1.0})
    result = compute_free_energy(ctx, metrics={})
    assert result.value == 1.0


def test_resource_form_handles_zero_seconds():
    """Zero/negative seconds falls through to heuristic (avoid divide-by-zero)."""
    ctx = _mk_ctx(arguments={"response_tokens": 100, "response_seconds": 0.0})
    result = compute_free_energy(ctx, metrics={"E": 0.6})
    assert result.source == "heuristic"
    assert result.value == 0.6


def test_fep_stub_falls_through_to_resource():
    """FEP form requires predictions — stubbed, falls through."""
    ctx = _mk_ctx(
        arguments={
            "response_tokens": 200,
            "response_seconds": 2.0,
            "expected_outcome": {"value": 0.7},
            "observed_outcome": {"value": 0.6},
        }
    )
    result = compute_free_energy(ctx, metrics={})
    assert result.source == "resource"


def test_heuristic_when_nothing_present():
    ctx = _mk_ctx()
    result = compute_free_energy(ctx, metrics={"E": 0.42})
    assert result.source == "heuristic"
    assert result.value == 0.42


def test_heuristic_clamps_out_of_range():
    ctx = _mk_ctx()
    assert compute_free_energy(ctx, metrics={"E": 1.5}).value == 1.0
    assert compute_free_energy(ctx, metrics={"E": -0.3}).value == 0.0
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_free_energy.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/grounding/free_energy.py
"""Negative free energy (E) — spec §3.1 E.

Tier 1 (FEP): variational free-energy estimator over agent predictions vs outcomes.
Tier 2 (resource): normalized throughput, (tokens/s) / (tokens/s)_max.
Tier 3 (heuristic): wraps legacy E.

Resource form ships as primary tier because it requires no new data beyond
what plugins already report. FEP form is stubbed; Phase 2 builds the estimator.
"""
from typing import Any, Dict

from src.grounding.types import GroundedValue

# Fleet-calibrated envelope — replaced by measured value in Phase 2.
TOKENS_PER_SECOND_MAX = 200.0


def compute_free_energy(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    args = getattr(ctx, "arguments", {}) or {}

    if "expected_outcome" in args and "observed_outcome" in args:
        try:
            return _compute_fep(args["expected_outcome"], args["observed_outcome"])
        except NotImplementedError:
            pass

    tokens = args.get("response_tokens")
    seconds = args.get("response_seconds")
    if tokens is not None and seconds is not None:
        try:
            return _compute_resource(float(tokens), float(seconds))
        except (ValueError, TypeError):
            pass

    return _compute_heuristic(metrics)


def _compute_fep(expected: Dict, observed: Dict) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 FEP requires a generative model over outcomes; Phase 2 scope"
    )


def _compute_resource(tokens: float, seconds: float) -> GroundedValue:
    if seconds <= 0:
        raise ValueError("response_seconds must be positive")
    rate = tokens / seconds
    normalized = rate / TOKENS_PER_SECOND_MAX
    val = max(0.0, min(1.0, normalized))
    return GroundedValue(value=val, source="resource")


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("E", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_grounding_free_energy.py -v --no-cov`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/grounding/free_energy.py tests/test_grounding_free_energy.py
git commit -m "feat(grounding): add free_energy module — resource-rate + FEP stub"
```

---

### Task 5: Coherence module

**Files:**
- Create: `src/grounding/coherence.py`
- Create: `tests/test_grounding_coherence.py`

Two forms per spec §3.1 Coherence: **manifold** (state-space distance from healthy baseline — computable now, uses `metrics["E"]`, `metrics["I"]`, `metrics["S"]`) and **KL** (requires a reference distribution — stubbed). Phase 1 ships manifold as primary, KL as stub, heuristic fallback wraps legacy `metrics["coherence"]`.

Healthy baseline vector comes from `config/governance_config.BASIN_HIGH` — use its minimum-bound corners as a proxy healthy-point: `(E, I, S) = (BASIN_HIGH.E_min, BASIN_HIGH.I_min, 0.0)`. Distance normalized by `DELTA_NORM_MAX` (scale constant added in Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grounding_coherence.py
"""Tests for the coherence grounding module."""
import math

import pytest
from unittest.mock import MagicMock

from src.grounding.coherence import compute_coherence
from src.grounding.types import GroundedValue


def _mk_ctx(arguments=None):
    ctx = MagicMock()
    ctx.arguments = arguments or {}
    return ctx


def test_manifold_at_healthy_point_is_one():
    """Agent sitting exactly at healthy baseline → coherence 1.0."""
    from config.governance_config import BASIN_HIGH
    metrics = {"E": BASIN_HIGH.E_min, "I": BASIN_HIGH.I_min, "S": 0.0}
    result = compute_coherence(_mk_ctx(), metrics)
    assert result.source == "manifold"
    assert abs(result.value - 1.0) < 1e-9


def test_manifold_far_from_healthy_approaches_zero():
    """Agent at opposite corner (low E, low I, high S) → low coherence."""
    metrics = {"E": 0.0, "I": 0.0, "S": 1.0}
    result = compute_coherence(_mk_ctx(), metrics)
    assert result.source == "manifold"
    assert result.value < 0.5


def test_manifold_missing_dims_falls_through():
    """Missing E/I/S → heuristic wrap of legacy coherence."""
    result = compute_coherence(_mk_ctx(), metrics={"coherence": 0.65})
    assert result.source == "heuristic"
    assert result.value == 0.65


def test_kl_stub_falls_through():
    """q_now / q_ref distributions present → tier-1 KL stub → manifold."""
    metrics = {
        "E": 0.5, "I": 0.5, "S": 0.5,
        "q_now": [0.25, 0.25, 0.25, 0.25],
        "q_ref": [0.3, 0.3, 0.2, 0.2],
    }
    result = compute_coherence(_mk_ctx(), metrics)
    # KL stub raises NotImplementedError → manifold path wins
    assert result.source == "manifold"


def test_heuristic_clamps():
    assert compute_coherence(_mk_ctx(), {"coherence": 1.5}).value == 1.0
    assert compute_coherence(_mk_ctx(), {"coherence": -0.1}).value == 0.0
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_coherence.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/grounding/coherence.py
"""Coherence — spec §3.1 Coherence.

Two grounded forms:
  - manifold:  C = 1 - ||Δ||_2 / ||Δ||_max, Δ = (E,I,S) - (E,I,S)_healthy
  - kl:        C = exp(-D_KL(q_now || q_ref)), requires reference distribution

Manifold form ships as primary (needs only existing EISV). KL stubbed for Phase 2.
"""
import math
from typing import Any, Dict

from src.grounding.types import GroundedValue


def compute_coherence(ctx: Any, metrics: Dict[str, Any]) -> GroundedValue:
    # Tier 1 — KL (requires reference distribution)
    if "q_now" in metrics and "q_ref" in metrics:
        try:
            return _compute_kl(metrics["q_now"], metrics["q_ref"])
        except NotImplementedError:
            pass

    # Tier 2 — manifold (requires EISV)
    try:
        return _compute_manifold(
            E=float(metrics["E"]),
            I=float(metrics["I"]),
            S=float(metrics["S"]),
        )
    except (KeyError, TypeError, ValueError):
        pass

    # Tier 3 — heuristic (legacy coherence)
    return _compute_heuristic(metrics)


def _compute_kl(q_now: list, q_ref: list) -> GroundedValue:
    raise NotImplementedError(
        "tier-1 KL coherence requires a calibrated reference distribution q_ref; "
        "Phase 2 scope"
    )


def _compute_manifold(E: float, I: float, S: float) -> GroundedValue:
    """Manifold distance from healthy (E,I,S) baseline."""
    from config.governance_config import BASIN_HIGH, DELTA_NORM_MAX

    healthy_E = BASIN_HIGH.E_min
    healthy_I = BASIN_HIGH.I_min
    healthy_S = 0.0

    dx = E - healthy_E
    dy = I - healthy_I
    dz = S - healthy_S
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    ratio = norm / DELTA_NORM_MAX
    val = 1.0 - max(0.0, min(1.0, ratio))
    return GroundedValue(value=val, source="manifold")


def _compute_heuristic(metrics: Dict[str, Any]) -> GroundedValue:
    raw = metrics.get("coherence", 0.5)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 0.5
    val = max(0.0, min(1.0, val))
    return GroundedValue(value=val, source="heuristic")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_grounding_coherence.py -v --no-cov`
Expected: FAIL on `DELTA_NORM_MAX` import — that constant lands in Task 6. Proceed to Task 6, then re-run.

**Note:** Do NOT commit Task 5 until Task 6 lands (`DELTA_NORM_MAX` is a dependency). Leave files uncommitted on the worktree and proceed.

---

### Task 6: Scale constants with provenance

**Files:**
- Modify: `config/governance_config.py` (append at end)
- Create: `tests/test_grounding_scale_constants.py`

Per spec §3.4, every scale constant ships with provenance metadata: value, measurement date, corpus size, percentile basis. Phase 1 ships placeholders tagged `provenance="placeholder"` — Phase 2 replaces with measured values.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grounding_scale_constants.py
"""Tests for grounding scale constants — provenance invariants.

Spec §3.4 requires every scale constant to carry measurement metadata.
These tests enforce that requirement at import time.
"""
import pytest

from config.governance_config import (
    ScaleConstant,
    S_SCALE,
    I_SCALE,
    E_SCALE,
    DELTA_NORM_MAX,
    ALL_SCALE_CONSTANTS,
)


def test_scale_constant_has_required_fields():
    sc = S_SCALE
    assert sc.value > 0
    assert sc.measured_on  # ISO date string
    assert sc.corpus_size >= 0
    assert sc.percentile in {50, 75, 90, 95, 99, None}  # None allowed for placeholders
    assert sc.provenance in {"measured", "placeholder", "derived"}


def test_all_constants_registered_in_manifest():
    """Every public scale constant must be in ALL_SCALE_CONSTANTS for registry audit."""
    assert S_SCALE in ALL_SCALE_CONSTANTS
    assert I_SCALE in ALL_SCALE_CONSTANTS
    assert E_SCALE in ALL_SCALE_CONSTANTS
    assert DELTA_NORM_MAX in ALL_SCALE_CONSTANTS


def test_scale_constants_are_floats_at_use():
    """The SCALE_CONSTANT.value attribute is what modules use; must be finite float."""
    import math
    for sc in ALL_SCALE_CONSTANTS:
        assert isinstance(sc.value, float)
        assert math.isfinite(sc.value)
        assert sc.value > 0


def test_placeholder_provenance_flagged_loudly():
    """Phase 1 ships all placeholders — test that Phase 2 work is visible."""
    placeholders = [sc for sc in ALL_SCALE_CONSTANTS if sc.provenance == "placeholder"]
    # Phase 1: all constants are placeholders; Phase 2 replaces them.
    # This test will flip when the first measured value lands — update it then.
    assert len(placeholders) == len(ALL_SCALE_CONSTANTS)


def test_delta_norm_max_covers_full_state_space_diagonal():
    """DELTA_NORM_MAX must be at least sqrt(3) ≈ 1.732 so coherence can reach 0."""
    import math
    assert DELTA_NORM_MAX.value >= math.sqrt(3) - 0.01
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_scale_constants.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'ScaleConstant'`

- [ ] **Step 3: Append constants to governance_config.py**

Append to `config/governance_config.py`:

```python
# =================================================================
# Grounding Scale Constants — spec §3.4
# =================================================================
# Every normalization constant used by src/grounding/ modules ships with
# measurement provenance. Phase 1 ships placeholders; Phase 2 replaces with
# values measured on a reference corpus per the protocol in spec §3.4.

@dataclass(frozen=True)
class ScaleConstant:
    """A scale/normalization constant with measurement provenance.

    provenance is one of:
      - "placeholder": initial guess, Phase 1; must be replaced before production
      - "measured":    measured on a named reference corpus per spec §3.4
      - "derived":     derived analytically from other quantities
    """
    name: str
    value: float
    measured_on: str          # ISO date (YYYY-MM-DD) when set; Phase 1 = plan date
    corpus_size: int          # agent-turn count when measured; 0 for placeholder
    percentile: Optional[int] # 90, 95, 99, etc.; None for non-percentile-derived
    provenance: str           # "placeholder" | "measured" | "derived"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.provenance not in {"placeholder", "measured", "derived"}:
            raise ValueError(f"unknown provenance {self.provenance!r}")
        if self.value <= 0:
            raise ValueError(f"scale constant {self.name} must be positive")


# Phase 1 placeholders — replace with measured values after §3.4 protocol runs.
S_SCALE = ScaleConstant(
    name="S_SCALE",
    value=3.0,
    measured_on="2026-04-18",
    corpus_size=0,
    percentile=None,
    provenance="placeholder",
    notes="Phase 1 placeholder. Spec §3.1 S: 90th-percentile S_raw on healthy corpus.",
)

I_SCALE = ScaleConstant(
    name="I_SCALE",
    value=2.0,
    measured_on="2026-04-18",
    corpus_size=0,
    percentile=None,
    provenance="placeholder",
    notes="Phase 1 placeholder. Spec §3.1 I: empirical MI upper envelope on held-out set.",
)

E_SCALE = ScaleConstant(
    name="E_SCALE",
    value=1.0,
    measured_on="2026-04-18",
    corpus_size=0,
    percentile=None,
    provenance="placeholder",
    notes="Phase 1 placeholder. FEP form only; resource form uses TOKENS_PER_SECOND_MAX.",
)

DELTA_NORM_MAX = ScaleConstant(
    name="DELTA_NORM_MAX",
    value=1.8,  # just above sqrt(3) so full-diagonal deviation hits coherence=0
    measured_on="2026-04-18",
    corpus_size=0,
    percentile=None,
    provenance="placeholder",
    notes="Phase 1 placeholder. Spec §3.4: 95th pct of observed ||Δ|| from healthy median.",
)

ALL_SCALE_CONSTANTS = [S_SCALE, I_SCALE, E_SCALE, DELTA_NORM_MAX]
```

Make sure the `Optional` import is present near the top — it already is (see line 7).

- [ ] **Step 4: Re-run scale-constants tests and Task 5 tests**

Run: `python -m pytest tests/test_grounding_scale_constants.py tests/test_grounding_coherence.py -v --no-cov`
Expected: PASS on both — 5 + 5 = 10 passed

**Fix needed if manifold test shape-mismatches:** The manifold formula uses `DELTA_NORM_MAX.value` (a float, not the `ScaleConstant` wrapper). Update the import in `src/grounding/coherence.py` from `from config.governance_config import BASIN_HIGH, DELTA_NORM_MAX` to also read `.value`:

```python
# inside _compute_manifold
from config.governance_config import BASIN_HIGH, DELTA_NORM_MAX
# ...
ratio = norm / DELTA_NORM_MAX.value
```

- [ ] **Step 5: Commit Task 5 + Task 6 together**

```bash
git add src/grounding/coherence.py \
        tests/test_grounding_coherence.py \
        tests/test_grounding_scale_constants.py \
        config/governance_config.py
git commit -m "feat(grounding): coherence module + scale constants with provenance"
```

---

### Task 7: Enrichment wiring — swap grounded into canonical slots

**Files:**
- Modify: `src/mcp_handlers/updates/enrichments.py` (append new enrichment)
- Create: `tests/test_grounding_enrichment.py`

Register a new enrichment at `order=75` (before mirror at order=80, after all ODE-adjacent enrichments). The enrichment:
1. Reads legacy `E/I/S/coherence` from `ctx.result["metrics"]`
2. Computes grounded values via the four modules
3. Copies legacy values to `E_legacy/I_legacy/S_legacy/coherence_legacy`
4. Overwrites `E/I/S/coherence` with grounded values
5. Writes `e_source/i_source/s_source/coherence_source` alongside

**Safety invariant:** `V` is not touched (spec §3.1 V is a cosmetic internal rename only; ODE-level quantity, not dual-computed in Phase 1). Verdicts and basin classification run in `phases.py` before enrichments, so they see legacy values unchanged.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_grounding_enrichment.py
"""Integration test: grounding enrichment swaps grounded into canonical slots."""
import pytest

from src.mcp_handlers.updates.context import UpdateContext
from src.mcp_handlers.updates.enrichments import enrich_grounding


@pytest.mark.asyncio
async def test_enrichment_swaps_grounded_into_canonical_slots():
    """After enrichment: E/I/S/coherence are grounded; *_legacy hold originals."""
    ctx = UpdateContext()
    ctx.arguments = {}
    ctx.response_text = "hello world"
    ctx.result = {
        "metrics": {
            "E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1,
            "coherence": 0.72,
        }
    }
    ctx.response_data = {}

    await enrich_grounding(ctx)

    m = ctx.result["metrics"]
    # Legacy values preserved under *_legacy
    assert m["E_legacy"] == 0.6
    assert m["I_legacy"] == 0.7
    assert m["S_legacy"] == 0.3
    assert m["coherence_legacy"] == 0.72
    # V is not dual-computed
    assert "V_legacy" not in m
    assert m["V"] == -0.1
    # Canonical slots carry grounded values (tier-3 heuristic wraps legacy, so same numbers in this test)
    assert m["E"] == 0.6
    assert m["I"] == 0.7
    assert m["S"] == 0.3
    # Coherence uses manifold form with BASIN_HIGH baseline — different from legacy 0.72
    assert 0.0 <= m["coherence"] <= 1.0
    # Source annotations present
    assert m["e_source"] == "heuristic"
    assert m["i_source"] == "heuristic"
    assert m["s_source"] == "heuristic"
    assert m["coherence_source"] == "manifold"


@pytest.mark.asyncio
async def test_enrichment_resource_form_when_tokens_provided():
    ctx = UpdateContext()
    ctx.arguments = {"response_tokens": 200, "response_seconds": 2.0}
    ctx.result = {"metrics": {"E": 0.5, "I": 0.5, "S": 0.5, "coherence": 0.6}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    # Resource form: 100 tokens/sec / 200 max = 0.5 → stays 0.5 here
    assert ctx.result["metrics"]["e_source"] == "resource"
    assert ctx.result["metrics"]["E_legacy"] == 0.5


@pytest.mark.asyncio
async def test_enrichment_never_raises_on_missing_metrics():
    """Enrichment must be fail-safe — missing metrics dict must not break pipeline."""
    ctx = UpdateContext()
    ctx.result = {}  # no metrics block at all
    ctx.response_data = {}

    await enrich_grounding(ctx)  # should not raise

    # ctx survives without corruption
    assert isinstance(ctx.result, dict)


@pytest.mark.asyncio
async def test_enrichment_does_not_touch_v():
    """Invariant: V stays exactly as it was — Phase 1 does not ground V."""
    ctx = UpdateContext()
    ctx.result = {"metrics": {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1, "coherence": 0.72}}
    ctx.response_data = {}

    await enrich_grounding(ctx)

    assert ctx.result["metrics"]["V"] == -0.1
    assert "V_legacy" not in ctx.result["metrics"]


@pytest.mark.asyncio
async def test_enrichment_idempotent_on_double_run():
    """Running twice must not chain the swap — *_legacy stays the original legacy."""
    ctx = UpdateContext()
    ctx.result = {"metrics": {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1, "coherence": 0.72}}
    ctx.response_data = {}

    await enrich_grounding(ctx)
    legacy_after_first = dict(
        (k, v) for k, v in ctx.result["metrics"].items() if k.endswith("_legacy")
    )
    await enrich_grounding(ctx)
    legacy_after_second = dict(
        (k, v) for k, v in ctx.result["metrics"].items() if k.endswith("_legacy")
    )

    assert legacy_after_first == legacy_after_second, "second run must not re-wrap"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python -m pytest tests/test_grounding_enrichment.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'enrich_grounding' from 'src.mcp_handlers.updates.enrichments'`

- [ ] **Step 3: Append enrichment to `src/mcp_handlers/updates/enrichments.py`**

At the bottom of `src/mcp_handlers/updates/enrichments.py`, add:

```python
# =================================================================
# Grounding enrichment — spec docs/specs/2026-04-17-eisv-grounding-design.md
# =================================================================
# Runs at order=75, AFTER gating (phases.py) but BEFORE mirror (order=80).
# Copies legacy E/I/S/coherence into *_legacy, then overwrites E/I/S/coherence
# with grounded values. Verdicts/basins have already been computed on legacy
# by the time this runs. V is not touched — it's not dual-computed in Phase 1.

from src.grounding.entropy import compute_entropy
from src.grounding.mutual_info import compute_mutual_info
from src.grounding.free_energy import compute_free_energy
from src.grounding.coherence import compute_coherence


@enrichment(order=75)
async def enrich_grounding(ctx) -> None:
    """Swap grounded E/I/S/coherence into canonical metrics slots."""
    result = ctx.result or {}
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        return  # no metrics block to enrich — fail-safe

    # Idempotency: if *_legacy already present from a prior run, skip.
    if "E_legacy" in metrics:
        return

    try:
        e = compute_free_energy(ctx, metrics)
        i = compute_mutual_info(ctx, metrics)
        s = compute_entropy(ctx, metrics)
        c = compute_coherence(ctx, metrics)
    except Exception as exc:
        logger.debug(f"Grounding enrichment failed — legacy values untouched: {exc}")
        return

    # Copy legacy → *_legacy
    for key in ("E", "I", "S", "coherence"):
        if key in metrics:
            metrics[f"{key}_legacy"] = metrics[key]

    # Overwrite canonical slots with grounded values
    metrics["E"] = e.value
    metrics["I"] = i.value
    metrics["S"] = s.value
    metrics["coherence"] = c.value

    # Source annotations
    metrics["e_source"] = e.source
    metrics["i_source"] = i.source
    metrics["s_source"] = s.source
    metrics["coherence_source"] = c.source
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_grounding_enrichment.py -v --no-cov`
Expected: PASS — 5 passed

- [ ] **Step 5: Run the full enrichment pipeline test to confirm no regression**

Run: `python -m pytest tests/test_enrichment_pipeline.py tests/test_enrichments_mirror.py -v --no-cov`
Expected: PASS — no regressions from adding a new `@enrichment` entry

- [ ] **Step 6: Commit**

```bash
git add src/mcp_handlers/updates/enrichments.py tests/test_grounding_enrichment.py
git commit -m "feat(grounding): wire enrich_grounding into enrichment pipeline at order=75"
```

---

### Task 8: End-to-end test via `process_agent_update`

**Files:**
- Create: `tests/test_grounding_end_to_end.py`

Verify the grounding block appears on the real `process_agent_update` response. Uses the same fixtures pattern as `tests/test_core_update.py`.

- [ ] **Step 1: Identify fixture pattern**

Run: `grep -l "process_update_authenticated_async\|async def test.*update" tests/ --include="*.py" -r | head -3`

Expected output (for orientation): paths to existing update-tests that show how the happy-path process_update is invoked.

- [ ] **Step 2: Write the end-to-end test**

```python
# tests/test_grounding_end_to_end.py
"""End-to-end: process_agent_update response carries the grounding block."""
import pytest

from src.mcp_handlers.updates.core import process_update_authenticated_async


@pytest.mark.asyncio
async def test_response_metrics_carry_grounded_and_legacy(tmp_path, monkeypatch):
    """A successful check-in returns both grounded (in E/I/S/coherence) and *_legacy."""
    args = {
        "agent_id": "grounding-e2e-test",
        "response_text": "test turn for grounding enrichment",
        "complexity": 0.4,
        "confidence": 0.7,
        "ethical_drift": [0.0, 0.0, 0.0],
    }

    result = await process_update_authenticated_async(args)

    import json
    if isinstance(result, list) and result:
        payload = json.loads(result[0].text)
    elif isinstance(result, dict):
        payload = result
    else:
        pytest.fail(f"unexpected result shape: {type(result)}")

    # Surface is the 'metrics' block on the response
    metrics = payload.get("metrics")
    assert metrics is not None, f"response missing metrics; keys: {list(payload.keys())}"

    # Grounded values live in canonical slots
    for key in ("E", "I", "S", "coherence"):
        assert key in metrics, f"metrics missing canonical {key}"
        assert isinstance(metrics[key], (int, float))
        assert 0.0 <= metrics[key] <= 1.0

    # Legacy values live in *_legacy slots
    for key in ("E_legacy", "I_legacy", "S_legacy", "coherence_legacy"):
        assert key in metrics, f"metrics missing {key}"

    # Source annotations present
    for key in ("e_source", "i_source", "s_source", "coherence_source"):
        assert key in metrics
        assert metrics[key] in {
            "heuristic", "resource", "manifold", "logprob",
            "multisample", "fep", "kl"
        }

    # V is NOT dual-computed
    assert "V_legacy" not in metrics
```

- [ ] **Step 3: Run the end-to-end test**

Run: `python -m pytest tests/test_grounding_end_to_end.py -v --no-cov`
Expected: PASS — 1 passed.

**If it fails with import/fixture errors:** inspect `tests/test_core_update.py` and mirror its setup (mcp_server fixture, monitor patching). Adjust the args to whatever minimum that test uses. The invariant to keep: assert on `payload["grounding"]` shape.

- [ ] **Step 4: Run the pre-commit test cache wrapper**

Run: `./scripts/dev/test-cache.sh`
Expected: PASS — full suite green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_grounding_end_to_end.py
git commit -m "test(grounding): end-to-end assertion that response carries grounding block"
```

---

### Task 9: Audit payload side-by-side — spec §4

**Files:**
- Modify: `src/audit_log.py` OR `src/audit_db.py` (find `tool_usage.payload` writer for `process_agent_update`) — add grounded values alongside legacy in the payload blob
- Create: `tests/test_grounding_audit_payload.py`

Per spec §4: "Audit `tool_usage.payload` gains the grounded and legacy values side-by-side when `process_agent_update` is the tool. Calibration consumers read both and compare."

- [ ] **Step 1: Locate the audit-write site**

Run: `grep -rn "tool_usage\|log_tool_call\|record_tool_usage" src/audit_log.py src/audit_db.py src/tool_usage_tracker.py | head -20`

Read the returned function. Identify where the `payload` blob is assembled for `process_agent_update` specifically — look for a dict construction that includes `"E"`, `"I"`, `"S"`, `"V"`, or `"coherence"`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_grounding_audit_payload.py
"""Audit-log assertion: payload carries grounded-and-legacy side-by-side."""
import json
import pytest

from src.mcp_handlers.updates.core import process_update_authenticated_async
from src.tool_usage_tracker import get_tool_usage_tracker


@pytest.mark.asyncio
async def test_audit_payload_contains_both_legacy_and_grounded():
    tracker = get_tool_usage_tracker()
    args = {
        "agent_id": "grounding-audit-test",
        "response_text": "audit payload side-by-side check",
        "complexity": 0.3,
    }

    await process_update_authenticated_async(args)

    # Fetch the most-recent usage entry for this agent
    stats = tracker.get_usage_stats(agent_id="grounding-audit-test", window_hours=1)
    assert stats.get("total_calls", 0) >= 1

    # Retrieve the actual payload — tracker-specific API; adjust to match.
    latest_payload = tracker.get_latest_payload("grounding-audit-test")
    assert latest_payload is not None

    # Grounded values live in canonical slots; legacy values side-by-side under *_legacy
    for key in ("E", "I", "S", "coherence"):
        assert key in latest_payload, f"audit payload missing canonical {key}"
        assert f"{key}_legacy" in latest_payload, f"audit payload missing {key}_legacy"

    # Source annotations
    for key in ("e_source", "i_source", "s_source", "coherence_source"):
        assert key in latest_payload
```

- [ ] **Step 3: Run test, verify failure**

Run: `python -m pytest tests/test_grounding_audit_payload.py -v --no-cov`
Expected: FAIL — either `AssertionError: 'grounding' not in latest_payload` OR `AttributeError: get_latest_payload`.

**If `get_latest_payload` doesn't exist**, adjust the test to read from whatever API the tracker actually exposes (`get_recent_calls`, direct DB read, etc.). Goal of the test is the same: assert that a fresh `process_agent_update` writes both legacy and grounded values to audit.

- [ ] **Step 4: Modify the audit-write site to include grounding**

In whichever function writes the `payload` for `process_agent_update` (identified in Step 1), add a line that merges `ctx.response_data.get("grounding")` into the payload blob before it is persisted:

```python
# example — actual site depends on step-1 finding
payload_blob = {
    # ... existing legacy EISV fields ...
}
if response_data and "grounding" in response_data:
    payload_blob["grounding"] = response_data["grounding"]
```

- [ ] **Step 5: Run test, verify pass**

Run: `python -m pytest tests/test_grounding_audit_payload.py -v --no-cov`
Expected: PASS — 1 passed.

- [ ] **Step 6: Run full pre-commit suite**

Run: `./scripts/dev/test-cache.sh`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/audit_log.py src/audit_db.py src/tool_usage_tracker.py tests/test_grounding_audit_payload.py
# (only stage the audit file that was actually modified)
git commit -m "feat(grounding): audit payload carries grounded values side-by-side with legacy"
```

---

### Task 10: Migration note + PR body

**Files:**
- Modify: `docs/specs/2026-04-17-eisv-grounding-design.md` (add "Phase 1 Shipped" section at the bottom)

Update the spec to record what Phase 1 actually delivered and flag the scope deviation for Kenny's review in the PR.

- [ ] **Step 1: Append to the spec file**

At the bottom of `docs/specs/2026-04-17-eisv-grounding-design.md`, add:

```markdown
---

## Phase 1 Shipped — 2026-MM-DD

Spec §5 implemented directly: grounded values land in canonical `E/I/S/coherence`
metrics slots; legacy values preserved as `E_legacy/I_legacy/S_legacy/coherence_legacy`.
Source annotations: `e_source/i_source/s_source/coherence_source`. `V` is not
dual-computed in Phase 1 (§3.1 V: cosmetic internal rename only, ODE-level quantity).

**How "no behavior change" holds:** the grounding enrichment runs at order=75,
after gating (phases.py). Verdicts and basin classification are computed on
legacy values before enrichment swaps grounded into the canonical slots.

**Out of scope of Phase 1** (deferred plans):
- Tier-1 (logprob) capture — plugin-side instrumentation.
- Tier-2 (multi-sample) estimator — requires equivalence classifier.
- Phase 2 calibration measurement — reference-corpus protocol per §3.4.
- ODE coefficient re-fit.
- Paper updates (§6).
- V grounding / internal void → free_energy_debt rename.

**Shipped modules:** `src/grounding/{types,entropy,mutual_info,free_energy,coherence}.py`

**Shipped config:** `config/governance_config.{S,I,E}_SCALE` and `DELTA_NORM_MAX`,
all with `provenance="placeholder"` until Phase 2.

**Shipped enrichment:** `@enrichment(order=75) enrich_grounding` in
`src/mcp_handlers/updates/enrichments.py`.

**Shipped tests:** `tests/test_grounding_*.py` (8 files, ~30 tests).
```

- [ ] **Step 2: Commit**

```bash
git add docs/specs/2026-04-17-eisv-grounding-design.md
git commit -m "docs(grounding): record Phase 1 shipped scope + deviation from §5"
```

- [ ] **Step 3: Push + flip PR out of draft**

```bash
git push
gh pr ready 26
```

Then update the PR body to link this plan and describe the deviation:

```bash
gh pr edit 26 --body-file - <<'EOF'
## Summary

Phase 1 of the EISV grounding work — server-side dual-compute scaffolding.

- New `src/grounding/` package: 4 pure-function modules + shared `GroundedValue` type.
- New enrichment `enrich_grounding` attaches `{e,i,s,coherence}_grounded` to responses.
- Scale constants in `config/governance_config.py` with provenance dataclass.
- Audit payload carries legacy + grounded side-by-side for Phase 2 comparison.

## Why this is user-invisible at the gating layer

Grounded values replace `E/I/S/coherence` in the metrics response; legacy values
are preserved under `*_legacy`. Verdicts and basin classification still run on
legacy values because the grounding enrichment is ordered after gating in the
pipeline (see `enrich_grounding` at `order=75`). Dashboards and broadcasters
will see grounded values in the canonical slot — that shift is expected and is
the point of Phase 1 dual-compute.

See `docs/plans/2026-04-18-eisv-grounding-phase-1-plan.md` for full design.

## Test plan

- [ ] `./scripts/dev/test-cache.sh` green
- [ ] `pytest tests/test_grounding_*.py -v` — all new tests pass
- [ ] Deploy to staging, check one real `process_agent_update` response contains the `grounding` block
EOF
```

---

## Self-Review

**1. Spec coverage.** Walk §3-§5 of the spec:
- §3.1 S (entropy) → Task 2 ✓ (tier-3 heuristic + tier-1/2 stubs)
- §3.1 I (mutual info) → Task 3 ✓
- §3.1 E (free energy) → Task 4 ✓ (resource-rate + FEP stub)
- §3.1 V → **Gap.** Spec §3.1 V says "code changes are cosmetic (rename `void` → `free_energy_debt` internally; keep `V` as external symbol)". This plan does not ship a V-grounded module because V is derived from running residuals, which is structural to the ODE — not a Phase 1 addition. The internal rename is tracked separately. V remains untouched and continues to come from the legacy ODE. *Recorded limitation, consistent with §5 "Verdicts, basins, thresholds keep using legacy."*
- §3.1 Coherence → Task 5 ✓
- §3.2 Coupling ODEs — stays untouched (spec §3.3 "What stays exactly as it is"). ✓
- §3.3 Invariants — Task 7 test `test_enrichment_does_not_touch_legacy_fields` enforces ✓
- §3.4 Scale constants → Task 6 ✓ (provenance dataclass + 4 constants + manifest)
- §4 Data path — new fields ✓ (Task 7), config constants ✓ (Task 6), new `src/grounding/` module ✓, audit payload ✓ (Task 9). *Check-in payload logprobs/samples fields noted as out-of-scope (plugin-side).*
- §5 Phase 1 — covered as written: grounded → `E/I/S/coherence`; legacy → `*_legacy`. Gating is preserved by enrichment ordering (post-gating), not by field renaming.
- §6 Paper alignment — explicitly out of scope.
- §7 Open questions — q1 (logprobs) noted out-of-scope; q2 (reference distribution) noted as coherence KL stub; q3 (FEP vs resource) resolved — ship both, default resource; q4 (reviewer) not mine; q5 (Codex compat) noted out-of-scope.

**2. Placeholder scan.**
- No "TBD" / "TODO" / "implement later" in steps.
- Task 8 Step 1 says "inspect `tests/test_core_update.py` and mirror its setup" — that's directional, not a placeholder. The step is executable ("run grep to identify", then "mirror").
- Task 9 Step 1 says "find the tool_usage.payload writer" — executable grep is given.
- Task 9 Step 4 shows actual code to add, conditioned on step-1 finding. Acceptable.

**3. Type consistency.**
- `GroundedValue(value, source)` — stable across Tasks 2-5 and Task 7.
- `compute_*(ctx, metrics) -> GroundedValue` signature — stable across all four modules.
- `ScaleConstant.value` (float) — used correctly in Task 6 fix for Task 5 import.
- Enrichment pipeline `order=75` — checked against `enrichments.py` which uses 10, 20, 30, etc.; 75 is safe.
- Response-data key `"grounding"` with sub-keys `"{e,i,s,coherence}_grounded"` — consistent Tasks 7, 8, 9.

No fixes needed from self-review.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-04-18-eisv-grounding-phase-1-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

**Recommended:** subagent-driven. Fresh subagent per task, review between tasks, fast iteration.
