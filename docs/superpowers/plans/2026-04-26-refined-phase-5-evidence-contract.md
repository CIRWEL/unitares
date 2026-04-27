# Refined Phase-5 Evidence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resupply the auto-calibration loop with structured agent-reported tool outcomes, gated by a deploy flag, with observable prediction binding so silent degradation becomes visible.

**Architecture:** Add a strict-Pydantic `recent_tool_results` field on `process_agent_update`. Inside the same MCP call, Phase-5 emits `outcome_event` per item with `verification_source="agent_reported_tool_result"`. Hardens TTL on `consume_prediction` and echoes `prediction_binding` so callers can see whether their prediction_id actually bound. Behind a `UNITARES_PHASE5_EVIDENCE_WRITE` flag (off → shadow → enable) so the calibrator's class-conditional scales aren't silently shifted by a flood of new rows.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, PostgreSQL@17. Spec at `docs/proposals/refined-phase-5-evidence-contract.md`.

**Branching:** Each task lands as its own commit on a single feature branch (`fix/refined-phase-5-evidence-contract`). Use `./scripts/dev/ship.sh` after the full test suite passes — runtime classification will route to PR + auto-merge.

---

## File Map

**Modify (runtime):**
- `src/monitor_prediction.py` — add `ttl_seconds` parameter to `consume_prediction`; hard expiry check (Task 1)
- `src/mcp_handlers/observability/outcome_events.py` — two-phase peek/consume; `prediction_binding` label; `verification_source` propagation (Tasks 1, 3)
- `src/mcp_handlers/schemas/core.py` — `verification_source` on `OutcomeEventParams`; new `ToolResultEvidence` model; `recent_tool_results` on `ProcessAgentUpdateParams` (Tasks 3, 4)
- `src/services/update_response_service.py` — merge `ctx.warnings` into `response_data["warnings"]` (Task 2)
- `src/mcp_handlers/response_formatter.py` — pass `prediction_id` + `warnings` through `_format_standard`/`_format_mirror`/`_format_compact` (Task 2)
- `src/mcp_handlers/updates/phases.py` — Phase-5 iteration over `recent_tool_results` after confidence correction; deploy-flag gate (Task 4)
- `src/mcp_handlers/updates/context.py` — add `recent_tool_results: List[ToolResultEvidence]` to `UpdateContext` (Task 4)
- `src/sequential_calibration.py:36-47` — docstring fix (Task 5)
- `src/mcp_handlers/admin/system.py` (or wherever describe_tool lives) — update `process_agent_update` returns block (Task 5)

**Modify (tests):**
- `tests/test_outcome_calibration.py` — `prediction_binding` table; concurrency canary; `verification_source` round-trip (Tasks 1, 3)
- `tests/test_calibration_corrections.py` — already covers `apply_confidence_correction`; no change in this plan
- `tests/test_response_formatter.py` — `prediction_id` + `warnings` preservation in each mode (Task 2)
- `tests/test_pydantic_schemas.py` — `ToolResultEvidence` validation; `recent_tool_results` field acceptance (Tasks 3, 4)
- `tests/test_phases_phase5_evidence.py` (new) — Phase-5 iteration; per-item isolation; deploy-flag behavior (Task 4)
- `tests/test_describe_tool_drift.py` (new) — schema vs describe_tool returns block parity (Task 5)

---

## Task 1: `prediction_binding` echo + hard TTL on `consume_prediction`

**Why bundled:** Per spec §"Implementation order" — both touch the same code path; the binding label is the point of the TTL check. Shipping one without the other creates either visibility-without-enforcement or enforcement-without-visibility.

**Files:**
- Modify: `src/monitor_prediction.py:48-64`
- Modify: `src/mcp_handlers/observability/outcome_events.py:163-225`
- Test: `tests/test_outcome_calibration.py`

- [ ] **Step 1: Write failing test for `consume_prediction` TTL parameter**

Add to `tests/test_outcome_calibration.py`:

```python
import time
from src.monitor_prediction import register_tactical_prediction, consume_prediction

class TestConsumePredictionHardTTL:
    def test_consume_returns_none_when_past_ttl(self):
        open_predictions = {}
        pid = register_tactical_prediction(
            open_predictions, confidence=0.7, prediction_ttl_seconds=3600.0
        )
        # Force the record's age past TTL by rewriting created_at
        open_predictions[pid]["created_at"] -= 7200.0  # 2 hours old
        result = consume_prediction(open_predictions, pid, ttl_seconds=3600.0)
        assert result is None

    def test_consume_succeeds_when_within_ttl(self):
        open_predictions = {}
        pid = register_tactical_prediction(open_predictions, confidence=0.7)
        result = consume_prediction(open_predictions, pid, ttl_seconds=3600.0)
        assert result is not None
        assert result["confidence"] == 0.7

    def test_expired_record_is_not_consumed(self):
        # The expired record stays in the dict (not consumed) so the
        # caller's lookup_prediction can later distinguish "expired" from
        # "missing" when computing prediction_binding.
        open_predictions = {}
        pid = register_tactical_prediction(open_predictions, confidence=0.7)
        open_predictions[pid]["created_at"] -= 7200.0
        consume_prediction(open_predictions, pid, ttl_seconds=3600.0)
        assert open_predictions[pid].get("consumed") is not True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_outcome_calibration.py::TestConsumePredictionHardTTL -v --no-cov --tb=short
```

Expected: 3 FAILS — `consume_prediction()` doesn't accept `ttl_seconds` keyword.

- [ ] **Step 3: Add `ttl_seconds` parameter to `consume_prediction`**

Replace the body of `consume_prediction` in `src/monitor_prediction.py`:

```python
def consume_prediction(
    open_predictions: Dict[str, Dict],
    prediction_id: str,
    *,
    ttl_seconds: float = 3600.0,
) -> Optional[Dict[str, Any]]:
    """Mark a prediction as consumed and return its record.

    Returns None if the id is unknown, already consumed, or past TTL.
    Expired records are NOT marked consumed — they remain in the registry
    so callers using lookup_prediction can distinguish "missing" from
    "expired" when computing prediction_binding labels.
    """
    if not prediction_id:
        return None
    record = open_predictions.get(prediction_id)
    if not record or record.get("consumed"):
        return None
    age = _time.monotonic() - float(record.get("created_at", 0.0))
    if age > ttl_seconds:
        return None
    record["consumed"] = True
    return dict(record)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_outcome_calibration.py::TestConsumePredictionHardTTL -v --no-cov --tb=short
```

Expected: 3 PASS.

- [ ] **Step 5: Write failing tests for `prediction_binding` echo**

Add to `tests/test_outcome_calibration.py`:

```python
import pytest

class TestPredictionBindingEcho:
    """Six binding labels per spec §4. Each fallback path emits a distinct label."""

    @pytest.mark.asyncio
    async def test_binding_registry_when_id_lives(self, monkeypatch, registered_agent):
        # registered_agent fixture mints a prediction_id via process_agent_update
        pid = registered_agent.last_prediction_id
        result = await call_outcome_event(
            outcome_type="test_passed",
            prediction_id=pid,
            client_session_id=registered_agent.session_id,
        )
        assert result["prediction_binding"] == "registry"

    @pytest.mark.asyncio
    async def test_binding_missing_prediction_when_id_unknown(self, registered_agent):
        result = await call_outcome_event(
            outcome_type="test_passed",
            prediction_id="00000000-0000-0000-0000-000000000000",
            confidence=0.5,
            client_session_id=registered_agent.session_id,
        )
        assert result["prediction_binding"] in ("missing_prediction", "argument_fallback")
        # Spec: missing then argument fallback fires; binding label is the FIRST resolution attempted.
        assert result["prediction_binding"] == "missing_prediction"

    @pytest.mark.asyncio
    async def test_binding_ttl_expired_when_record_present_but_old(
        self, monkeypatch, registered_agent
    ):
        pid = registered_agent.last_prediction_id
        # Force the record past TTL
        monitor = registered_agent.monitor
        monitor._open_predictions[pid]["created_at"] -= 7200.0
        result = await call_outcome_event(
            outcome_type="test_passed",
            prediction_id=pid,
            confidence=0.5,
            client_session_id=registered_agent.session_id,
        )
        assert result["prediction_binding"] == "ttl_expired_fallback"

    @pytest.mark.asyncio
    async def test_binding_argument_fallback_when_no_id_supplied(self, registered_agent):
        result = await call_outcome_event(
            outcome_type="test_passed",
            confidence=0.5,
            client_session_id=registered_agent.session_id,
        )
        assert result["prediction_binding"] == "argument_fallback"

    @pytest.mark.asyncio
    async def test_binding_no_binding_when_all_fallbacks_fail(self, fresh_agent_no_history):
        # Fresh agent: no monitor, no prev_confidence, no audit trail
        result = await call_outcome_event(
            outcome_type="test_passed",
            client_session_id=fresh_agent_no_history.session_id,
        )
        assert result["prediction_binding"] == "no_binding"
```

> The fixtures (`registered_agent`, `fresh_agent_no_history`, `call_outcome_event`) are utilities: if they don't exist, add minimal helpers in the test module (don't put in conftest unless reused beyond this file). Each fixture should call the real onboard/process_agent_update flow to mint state.

- [ ] **Step 6: Run tests to verify they fail**

```bash
pytest tests/test_outcome_calibration.py::TestPredictionBindingEcho -v --no-cov --tb=short
```

Expected: 5 FAILS — response shape doesn't include `prediction_binding`.

- [ ] **Step 7: Add `prediction_binding` computation to `outcome_events.py`**

In `src/mcp_handlers/observability/outcome_events.py`, replace the prediction-resolution block (lines 170-207) with two-phase logic:

```python
# Two-phase prediction resolution: peek first to compute binding label,
# then consume only if live. See spec §4 — without peek, ttl_expired and
# missing collapse into the same None return from consume_prediction.
from src.monitor_prediction import lookup_prediction, consume_prediction
import time as _time

_confidence: Optional[float] = None
prediction_source: Optional[str] = None
prediction_record: Optional[Dict[str, Any]] = None
prediction_binding: str = "no_binding"
ttl_seconds = float(getattr(mcp_server.monitors.get(agent_id), "_prediction_ttl_seconds", 3600.0))

if prediction_id:
    monitor = mcp_server.monitors.get(agent_id)
    open_predictions = getattr(monitor, "_open_predictions", None) if monitor else None
    if open_predictions is not None:
        record_peek = lookup_prediction(open_predictions, prediction_id)
        if record_peek is None:
            prediction_binding = "missing_prediction"
        else:
            age = _time.monotonic() - float(record_peek.get("created_at", 0.0))
            if age > ttl_seconds:
                prediction_binding = "ttl_expired_fallback"
            else:
                prediction_record = consume_prediction(
                    open_predictions, prediction_id, ttl_seconds=ttl_seconds
                )
                if prediction_record is not None:
                    _confidence = float(prediction_record.get("confidence"))
                    prediction_source = "registry"
                    prediction_binding = "registry"
                else:
                    # Race: another consumer beat us. Treat as missing.
                    prediction_binding = "missing_prediction"

if _confidence is None:
    _raw_conf = arguments.get("confidence")
    if _raw_conf is not None:
        _confidence = float(_raw_conf)
        prediction_source = prediction_source or "argument"
        if prediction_binding == "no_binding":
            prediction_binding = "argument_fallback"

if _confidence is None:
    try:
        monitor = mcp_server.monitors.get(agent_id)
        prev_confidence = getattr(monitor, "_prev_confidence", None) if monitor else None
        if isinstance(prev_confidence, (int, float)):
            _confidence = float(prev_confidence)
            prediction_source = prediction_source or "prev_confidence_fallback"
            if prediction_binding == "no_binding":
                prediction_binding = "prev_confidence_fallback"
    except Exception:
        pass

if _confidence is None:
    try:
        db_conf = await db.get_latest_confidence_before(agent_id=agent_id)
        if db_conf is not None:
            _confidence = db_conf
            prediction_source = prediction_source or "audit_trail_fallback"
            if prediction_binding == "no_binding":
                prediction_binding = "audit_trail_fallback"
    except Exception:
        pass
```

Then in the response payload at the end of `handle_outcome_event`, add `prediction_binding`:

```python
return [success_response({
    "outcome_id": outcome_id,
    "outcome_type": outcome_type,
    "is_bad": is_bad,
    "outcome_score": outcome_score,
    "eisv_snapshot": snapshot,
    "prediction_binding": prediction_binding,
})]
```

- [ ] **Step 8: Run all outcome_event tests to verify**

```bash
pytest tests/test_outcome_calibration.py -v --no-cov --tb=short
```

Expected: all PASS (existing + 5 new binding tests + 3 new TTL tests).

- [ ] **Step 9: Add concurrency regression canary**

Append to `tests/test_outcome_calibration.py`:

```python
class TestPredictionBindingConcurrencyCanary:
    """Regression canary, NOT a correctness assertion. Documents current
    behavior under racing outcome_events for the same prediction_id.
    The lock fix is explicitly deferred per spec §4. If this test ever
    starts failing because both calls resolve as `registry`, the race
    has become observable and the lock is no longer optional.
    """

    @pytest.mark.asyncio
    async def test_concurrent_outcome_events_one_wins_one_misses(self, registered_agent):
        import asyncio
        pid = registered_agent.last_prediction_id
        results = await asyncio.gather(
            call_outcome_event(outcome_type="test_passed", prediction_id=pid,
                               client_session_id=registered_agent.session_id),
            call_outcome_event(outcome_type="test_passed", prediction_id=pid,
                               client_session_id=registered_agent.session_id),
        )
        bindings = sorted(r["prediction_binding"] for r in results)
        # Under typical scheduling: one wins (registry), one misses (missing_prediction).
        # Under unlucky scheduling without a lock, both could resolve as registry —
        # which is the failure mode this canary will eventually catch.
        assert bindings.count("registry") <= 1, (
            "Concurrency race made both calls resolve to registry — "
            "the lock fix deferred in v1 is no longer optional"
        )
```

- [ ] **Step 10: Run full test suite to confirm no regressions**

```bash
./scripts/dev/test-cache.sh
```

Expected: all PASS (≥ 7501 like prior runs + new tests).

- [ ] **Step 11: Stage + commit + push via ship.sh**

```bash
git add src/monitor_prediction.py src/mcp_handlers/observability/outcome_events.py tests/test_outcome_calibration.py
./scripts/dev/ship.sh "phase-5: prediction_binding echo + hard TTL on consume_prediction"
```

Expected: routes as runtime → PR auto-opened.

---

## Task 2: Plumb `prediction_id` + `warnings` through formatter modes

**Files:**
- Modify: `src/services/update_response_service.py:16-50` (merge `ctx.warnings` into response_data)
- Modify: `src/mcp_handlers/response_formatter.py:115,159,331` (`_format_standard`, `_format_mirror`, `_format_compact` — pass through both fields)
- Test: `tests/test_response_formatter.py`

> `_format_minimal` is intentionally bandwidth-constrained per spec §6 — leave stripped.

- [ ] **Step 1: Write failing tests for `prediction_id` preservation**

Add to `tests/test_response_formatter.py`:

```python
class TestFormatStandardPreservesPredictionId:
    def test_prediction_id_passes_through(self):
        from src.mcp_handlers.response_formatter import _format_standard
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "prediction_id": "abc-123",
        }
        result = _format_standard(response_data, task_type="general")
        assert result.get("prediction_id") == "abc-123"

    def test_warnings_passes_through(self):
        from src.mcp_handlers.response_formatter import _format_standard
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "warnings": ["evidence record failed for tool=pytest"],
        }
        result = _format_standard(response_data, task_type="general")
        assert result.get("warnings") == ["evidence record failed for tool=pytest"]


class TestFormatMirrorPreservesPredictionId:
    def test_prediction_id_passes_through(self):
        from src.mcp_handlers.response_formatter import _format_mirror
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "prediction_id": "abc-123",
        }
        result = _format_mirror(response_data, saved_trust_tier=None, meta=None)
        assert result.get("prediction_id") == "abc-123"

    def test_warnings_passes_through(self):
        from src.mcp_handlers.response_formatter import _format_mirror
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "warnings": ["W"],
        }
        result = _format_mirror(response_data, saved_trust_tier=None, meta=None)
        assert result.get("warnings") == ["W"]


class TestFormatCompactPreservesPredictionId:
    def test_prediction_id_passes_through(self):
        from src.mcp_handlers.response_formatter import _format_compact
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "prediction_id": "abc-123",
        }
        result = _format_compact(response_data, using_default_mode=False, saved_trust_tier=None)
        assert result.get("prediction_id") == "abc-123"


class TestFormatMinimalIntentionallyStrips:
    def test_minimal_does_not_include_prediction_id(self):
        # Spec §6: minimal mode is bandwidth-constrained; prediction_id stripped intentionally.
        from src.mcp_handlers.response_formatter import _format_minimal
        response_data = {
            "decision": {"action": "proceed"},
            "metrics": {"E": 0.5, "I": 0.5, "S": 0.3, "V": 0.0, "phi": 0.7},
            "prediction_id": "abc-123",
        }
        result = _format_minimal(response_data, using_default_mode=False, saved_trust_tier=None)
        assert "prediction_id" not in result


class TestUpdateResponseServiceMergesWarnings:
    def test_ctx_warnings_appear_in_response_data(self):
        # build_process_update_response_data should merge ctx.warnings (de-duped)
        # into response_data["warnings"].
        from src.services.update_response_service import build_process_update_response_data
        from src.mcp_handlers.updates.context import UpdateContext
        ctx = UpdateContext()  # adapt to real constructor signature
        ctx.warnings = ["w1", "w1", "w2"]  # duplicate to verify de-dup
        # build_process_update_response_data takes more args than this stub —
        # adapt to real signature; the assertion is the load-bearing piece:
        response_data = build_process_update_response_data(ctx)
        assert sorted(response_data.get("warnings", [])) == ["w1", "w2"]
```

> If `UpdateContext()` requires args you don't have, use the existing test's pattern for constructing it (search test files for `UpdateContext(`).

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_response_formatter.py -k "PreservesPredictionId or IntentionallyStrips or MergesWarnings" -v --no-cov --tb=short
```

Expected: 7 FAILS.

- [ ] **Step 3: Add `prediction_id` + `warnings` to each formatter's result dict**

In `src/mcp_handlers/response_formatter.py`, edit `_format_standard` (around line 138-149) — append before `return result`:

```python
if response_data.get("prediction_id"):
    result["prediction_id"] = response_data["prediction_id"]
if response_data.get("warnings"):
    result["warnings"] = response_data["warnings"]
```

Repeat the same two-line addition inside `_format_mirror` (right before its `return`), and inside `_format_compact` (right before its `return`).

`_format_minimal` is left unchanged per spec §6.

- [ ] **Step 4: Add `ctx.warnings → response_data["warnings"]` merge in `build_process_update_response_data`**

In `src/services/update_response_service.py`, inside `build_process_update_response_data`, after the existing fields populate `response_data`, add:

```python
warnings_seen = []
for w in (getattr(ctx, "warnings", None) or []):
    if w not in warnings_seen:
        warnings_seen.append(w)
if warnings_seen:
    response_data["warnings"] = warnings_seen
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_response_formatter.py -k "PreservesPredictionId or IntentionallyStrips or MergesWarnings" -v --no-cov --tb=short
```

Expected: 7 PASS.

- [ ] **Step 6: Run full test suite**

```bash
./scripts/dev/test-cache.sh
```

Expected: all PASS.

- [ ] **Step 7: Stage + commit + push**

```bash
git add src/services/update_response_service.py src/mcp_handlers/response_formatter.py tests/test_response_formatter.py
./scripts/dev/ship.sh "phase-5: plumb prediction_id + warnings through formatter modes"
```

---

## Task 3: `verification_source` enum on `outcome_event`

**Files:**
- Modify: `src/mcp_handlers/schemas/core.py:181-191` (add field to `OutcomeEventParams`)
- Modify: `src/mcp_handlers/observability/outcome_events.py` (forward to `detail` dict; default if missing)
- Test: `tests/test_pydantic_schemas.py` + `tests/test_outcome_calibration.py`

Storage decision: in v1, store as `detail["verification_source"]` rather than promoting to a typed DB column. v1 records the dimension; v2 (when calibrator weighting goes live) can promote to a typed column if filtering performance demands it.

- [ ] **Step 1: Write failing schema test**

Add to `tests/test_pydantic_schemas.py`:

```python
class TestVerificationSource:
    def test_default_is_agent_reported_tool_result(self):
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        params = OutcomeEventParams(outcome_type="test_passed")
        assert params.verification_source == "agent_reported_tool_result"

    def test_accepts_server_observation(self):
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        params = OutcomeEventParams(
            outcome_type="test_passed",
            verification_source="server_observation",
        )
        assert params.verification_source == "server_observation"

    def test_rejects_unknown_value(self):
        import pytest
        from pydantic import ValidationError
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        with pytest.raises(ValidationError):
            OutcomeEventParams(
                outcome_type="test_passed",
                verification_source="random_made_up_string",
            )
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_pydantic_schemas.py::TestVerificationSource -v --no-cov --tb=short
```

Expected: 3 FAILS — `OutcomeEventParams` has no `verification_source` field.

- [ ] **Step 3: Add field to `OutcomeEventParams`**

In `src/mcp_handlers/schemas/core.py:181-191`, add after `agent_id`:

```python
    verification_source: Literal[
        "agent_reported_tool_result",
        "server_observation",
        "external_signal",
    ] = Field(
        "agent_reported_tool_result",
        description=(
            "Provenance of this outcome. v1 default is agent_reported_tool_result. "
            "server_observation reserved for v2 server-verified primitive (KG writes, "
            "dialectic verdicts, state transitions). external_signal for CI webhooks etc."
        ),
    )
```

- [ ] **Step 4: Run schema tests to verify pass**

```bash
pytest tests/test_pydantic_schemas.py::TestVerificationSource -v --no-cov --tb=short
```

Expected: 3 PASS.

- [ ] **Step 5: Forward `verification_source` to `detail` in handler**

In `src/mcp_handlers/observability/outcome_events.py`, in the `detail` population block (around lines 218-225), add:

```python
detail["verification_source"] = arguments.get(
    "verification_source", "agent_reported_tool_result"
)
```

- [ ] **Step 6: Write integration test for round-trip**

Append to `tests/test_outcome_calibration.py`:

```python
class TestVerificationSourceRoundTrip:
    @pytest.mark.asyncio
    async def test_default_recorded_in_detail(self, registered_agent):
        result = await call_outcome_event(
            outcome_type="test_passed",
            confidence=0.7,
            client_session_id=registered_agent.session_id,
        )
        # Read back from the DB row via outcome_id
        row = await fetch_outcome_row(result["outcome_id"])
        assert row["detail"]["verification_source"] == "agent_reported_tool_result"

    @pytest.mark.asyncio
    async def test_server_observation_recorded_when_set(self, registered_agent):
        result = await call_outcome_event(
            outcome_type="test_passed",
            confidence=0.7,
            verification_source="server_observation",
            client_session_id=registered_agent.session_id,
        )
        row = await fetch_outcome_row(result["outcome_id"])
        assert row["detail"]["verification_source"] == "server_observation"
```

> If `fetch_outcome_row` doesn't exist as a test util, add a minimal helper in this module that queries `outcome_events` by id.

- [ ] **Step 7: Run + commit + push**

```bash
pytest tests/test_outcome_calibration.py::TestVerificationSourceRoundTrip -v --no-cov --tb=short
./scripts/dev/test-cache.sh
git add src/mcp_handlers/schemas/core.py src/mcp_handlers/observability/outcome_events.py tests/test_pydantic_schemas.py tests/test_outcome_calibration.py
./scripts/dev/ship.sh "phase-5: verification_source enum on outcome_event"
```

---

## Task 4: `ToolResultEvidence` model + `recent_tool_results` field + Phase-5 iteration + deploy gate

**Why bundled:** Schema and consumer ship together so the field never accepts data the server silently drops. Deploy gate ships with the iteration so the production calibration distribution isn't shifted by the merge.

**Files:**
- Modify: `src/mcp_handlers/schemas/core.py` (add `ToolResultEvidence` model + field on `ProcessAgentUpdateParams`)
- Modify: `src/mcp_handlers/updates/context.py` (`UpdateContext` gains `recent_tool_results: List[ToolResultEvidence]`)
- Modify: `src/mcp_handlers/updates/phases.py` around line 430 (Phase-5 iteration after `apply_confidence_correction`)
- Test: `tests/test_pydantic_schemas.py` + new `tests/test_phases_phase5_evidence.py`

- [ ] **Step 1: Write failing schema tests for `ToolResultEvidence`**

Add to `tests/test_pydantic_schemas.py`:

```python
class TestToolResultEvidence:
    def test_minimal_valid(self):
        from src.mcp_handlers.schemas.core import ToolResultEvidence
        ev = ToolResultEvidence(kind="test", tool="pytest", summary="ok")
        assert ev.kind == "test"
        assert ev.exit_code is None

    def test_rejects_extra_fields(self):
        import pytest
        from pydantic import ValidationError
        from src.mcp_handlers.schemas.core import ToolResultEvidence
        with pytest.raises(ValidationError):
            ToolResultEvidence(kind="test", tool="pytest", summary="ok", random_field="x")

    def test_rejects_unknown_kind(self):
        import pytest
        from pydantic import ValidationError
        from src.mcp_handlers.schemas.core import ToolResultEvidence
        with pytest.raises(ValidationError):
            ToolResultEvidence(kind="not_a_real_kind", tool="x", summary="x")

    def test_tool_name_max_length(self):
        import pytest
        from pydantic import ValidationError
        from src.mcp_handlers.schemas.core import ToolResultEvidence
        with pytest.raises(ValidationError):
            ToolResultEvidence(kind="test", tool="x" * 65, summary="ok")


class TestProcessAgentUpdateAcceptsRecentToolResults:
    def test_optional_field_defaults_none(self):
        from src.mcp_handlers.schemas.core import ProcessAgentUpdateParams
        params = ProcessAgentUpdateParams(response_text="hello")
        assert params.recent_tool_results is None

    def test_accepts_list_of_evidence(self):
        from src.mcp_handlers.schemas.core import ProcessAgentUpdateParams
        params = ProcessAgentUpdateParams(
            response_text="ran tests",
            recent_tool_results=[
                {"kind": "test", "tool": "pytest", "summary": "passed", "exit_code": 0}
            ],
        )
        assert len(params.recent_tool_results) == 1
        assert params.recent_tool_results[0].kind == "test"
```

- [ ] **Step 2: Run to verify fail**

```bash
pytest tests/test_pydantic_schemas.py -k "ToolResultEvidence or ProcessAgentUpdateAcceptsRecentToolResults" -v --no-cov --tb=short
```

Expected: 6 FAILS — `ToolResultEvidence` doesn't exist, `recent_tool_results` field missing.

- [ ] **Step 3: Add `ToolResultEvidence` model + field**

In `src/mcp_handlers/schemas/core.py`, add ABOVE `class OutcomeEventParams`:

```python
class ToolResultEvidence(BaseModel):
    """Self-reported tool outcome evidence from a recent agent action.

    Self-report — the server treats this as
    `verification_source="agent_reported_tool_result"`. A future server-verified
    primitive will provide `server_observation` outcomes for the subset of
    work the server can independently verify. See spec §1.
    """
    model_config = ConfigDict(extra="forbid")

    kind: Literal["command", "test", "lint", "build", "file_op", "tool_call"]
    tool: str = Field(..., max_length=64)
    summary: str = Field(..., max_length=512)
    exit_code: Optional[int] = None
    is_bad: Optional[bool] = None
    prediction_id: Optional[str] = None
    observed_at: Optional[datetime] = None
```

In `class ProcessAgentUpdateParams`, add:

```python
    recent_tool_results: Optional[List[ToolResultEvidence]] = Field(
        None,
        description=(
            "Self-reported tool outcomes from the agent's most recent actions. "
            "Server emits one outcome_event per item (gated by "
            "UNITARES_PHASE5_EVIDENCE_WRITE). See docs/proposals/refined-phase-5-evidence-contract.md."
        ),
    )
```

Make sure `from datetime import datetime`, `from pydantic import ConfigDict`, and `from typing import List` are imported at the top of the module (they likely already are; check).

- [ ] **Step 4: Run schema tests to verify pass**

```bash
pytest tests/test_pydantic_schemas.py -k "ToolResultEvidence or ProcessAgentUpdateAcceptsRecentToolResults" -v --no-cov --tb=short
```

Expected: 6 PASS.

- [ ] **Step 5: Add `recent_tool_results` to `UpdateContext`**

In `src/mcp_handlers/updates/context.py` (around line 73 where `warnings` lives), add:

```python
    recent_tool_results: List[Any] = field(default_factory=list)
```

(Use `Any` here to avoid a circular import on `ToolResultEvidence`; coerce at consumption site.)

Then in the existing `transform_inputs` Phase 3 (`phases.py` around the existing `ctx.confidence` assignment), populate it:

```python
ctx.recent_tool_results = ctx.arguments.get("recent_tool_results") or []
```

- [ ] **Step 6: Write failing tests for Phase-5 iteration**

Create `tests/test_phases_phase5_evidence.py`:

```python
"""Phase-5 iteration over recent_tool_results — spec §2.

Tests the full process_agent_update path with a list of evidence items
under each UNITARES_PHASE5_EVIDENCE_WRITE deploy-flag setting.
"""

import os
import pytest


@pytest.mark.asyncio
async def test_evidence_iteration_off_by_default(registered_agent, monkeypatch):
    monkeypatch.delenv("UNITARES_PHASE5_EVIDENCE_WRITE", raising=False)
    samples_before = await get_eligible_samples()
    await call_process_agent_update(
        client_session_id=registered_agent.session_id,
        response_text="ran 3 tests",
        confidence=0.7,
        recent_tool_results=[
            {"kind": "test", "tool": "pytest", "summary": "passed", "exit_code": 0}
        ],
    )
    samples_after = await get_eligible_samples()
    assert samples_after == samples_before, "default off should not write outcome_events"


@pytest.mark.asyncio
async def test_evidence_iteration_shadow_writes_with_flag(registered_agent, monkeypatch):
    monkeypatch.setenv("UNITARES_PHASE5_EVIDENCE_WRITE", "shadow")
    samples_before = await get_eligible_samples()
    result = await call_process_agent_update(
        client_session_id=registered_agent.session_id,
        response_text="ran 3 tests",
        confidence=0.7,
        recent_tool_results=[
            {"kind": "test", "tool": "pytest", "summary": "passed", "exit_code": 0}
        ],
    )
    samples_after = await get_eligible_samples()
    # Shadow rows are written but excluded from the calibration sample count
    assert samples_after == samples_before


@pytest.mark.asyncio
async def test_evidence_iteration_enabled_advances_calibration(registered_agent, monkeypatch):
    monkeypatch.setenv("UNITARES_PHASE5_EVIDENCE_WRITE", "1")
    samples_before = await get_eligible_samples()
    await call_process_agent_update(
        client_session_id=registered_agent.session_id,
        response_text="ran 3 tests",
        confidence=0.7,
        recent_tool_results=[
            {"kind": "test", "tool": "pytest", "summary": "passed", "exit_code": 0}
        ],
    )
    samples_after = await get_eligible_samples()
    assert samples_after == samples_before + 1


@pytest.mark.asyncio
async def test_per_item_isolation_one_bad_does_not_abort_siblings(registered_agent, monkeypatch):
    monkeypatch.setenv("UNITARES_PHASE5_EVIDENCE_WRITE", "1")
    samples_before = await get_eligible_samples()
    response = await call_process_agent_update(
        client_session_id=registered_agent.session_id,
        response_text="three results, middle one will fail to record",
        confidence=0.7,
        recent_tool_results=[
            {"kind": "test", "tool": "pytest", "summary": "ok", "exit_code": 0},
            {"kind": "test", "tool": "pytest_bad", "summary": "x" * 600, "exit_code": 0},  # exceeds summary max_length — won't reach handler since pydantic validates first
            {"kind": "test", "tool": "pytest", "summary": "ok", "exit_code": 0},
        ],
    )
    # Pydantic catches the over-length summary at the schema layer, so item 2 is
    # rejected before Phase-5 runs. Items 1 and 3 still record. The whole call
    # returns the validation error as a 4xx — to test true per-item isolation,
    # construct a runtime failure instead (e.g., a prediction_id that triggers
    # a server-side path failure). Adapt to the actual failure surface.
    # Acceptance: when the handler IS called with valid items + one runtime-failing item,
    # the failing item appends to ctx.warnings and siblings still produce outcome rows.
    samples_after = await get_eligible_samples()
    assert samples_after - samples_before == 2  # items 1 and 3 only
    # warnings field should mention the failed tool
    assert any("pytest_bad" in w for w in response.get("warnings", []))


@pytest.mark.asyncio
async def test_kind_to_outcome_type_mapping(registered_agent, monkeypatch):
    """Spec §1: test → test_passed/test_failed; everything else → task_completed/task_failed."""
    monkeypatch.setenv("UNITARES_PHASE5_EVIDENCE_WRITE", "1")
    await call_process_agent_update(
        client_session_id=registered_agent.session_id,
        response_text="various tools",
        confidence=0.7,
        recent_tool_results=[
            {"kind": "test", "tool": "pytest", "summary": "ok", "exit_code": 0},
            {"kind": "lint", "tool": "ruff", "summary": "ok", "exit_code": 0},
            {"kind": "command", "tool": "git", "summary": "fail", "exit_code": 1},
        ],
    )
    rows = await fetch_recent_outcome_rows(registered_agent.agent_uuid, limit=3)
    types = sorted(r["outcome_type"] for r in rows)
    assert types == ["task_completed", "task_failed", "test_passed"]
```

> Test fixtures `registered_agent`, `call_process_agent_update`, `get_eligible_samples`, `fetch_recent_outcome_rows` — minimal helpers in this module if not already in conftest.

- [ ] **Step 7: Run to verify all fail**

```bash
pytest tests/test_phases_phase5_evidence.py -v --no-cov --tb=short
```

Expected: all FAIL — Phase-5 iteration not implemented.

- [ ] **Step 8: Implement `_derive_outcome` helper**

Add a module-level helper at the top of `src/mcp_handlers/updates/phases.py` (after imports):

```python
def _derive_outcome(evidence) -> tuple[str, bool]:
    """Map ToolResultEvidence to (outcome_type, is_bad) per spec §1 mapping table."""
    is_bad = evidence.is_bad
    if is_bad is None:
        is_bad = (evidence.exit_code is not None and evidence.exit_code != 0)
    if evidence.kind == "test":
        return ("test_failed" if is_bad else "test_passed", is_bad)
    return ("task_failed" if is_bad else "task_completed", is_bad)
```

- [ ] **Step 9: Implement Phase-5 iteration with deploy gate**

In `src/mcp_handlers/updates/phases.py`, AFTER the `apply_confidence_correction` block (around line 446), insert:

```python
    # Phase-5: iterate self-reported tool evidence. Spec §2 + §8.
    evidence_mode = os.environ.get("UNITARES_PHASE5_EVIDENCE_WRITE", "").lower()
    if ctx.recent_tool_results and evidence_mode in ("shadow", "1", "enable"):
        from src.mcp_handlers.observability.outcome_events import handle_outcome_event
        for evidence in ctx.recent_tool_results:
            try:
                outcome_type, is_bad = _derive_outcome(evidence)
                detail = {
                    "tool": evidence.tool,
                    "summary": evidence.summary,
                    "kind": evidence.kind,
                    "exit_code": evidence.exit_code,
                    "phase5_emitter": True,
                }
                if evidence_mode == "shadow":
                    detail["shadow_write"] = True
                await handle_outcome_event({
                    "outcome_type": outcome_type,
                    "is_bad": is_bad,
                    "prediction_id": evidence.prediction_id,
                    "confidence": ctx.confidence,
                    "verification_source": "agent_reported_tool_result",
                    "detail": detail,
                    "agent_id": ctx.agent_id,
                    "client_session_id": ctx.arguments.get("client_session_id"),
                })
            except Exception as e:
                ctx.warnings.append(
                    f"evidence record failed for tool={getattr(evidence, 'tool', '?')}: {e}"
                )
                logger.debug("Phase-5 evidence record failed: %s", e, exc_info=True)
    elif ctx.recent_tool_results:
        # Default off: log per-item count only, per spec §8
        logger.info(
            "Phase-5 evidence iteration skipped (UNITARES_PHASE5_EVIDENCE_WRITE unset); "
            "would have processed %d items for agent=%s",
            len(ctx.recent_tool_results), ctx.agent_id,
        )
```

Make sure `import os` is at the top of the module if not already.

- [ ] **Step 10: Run Phase-5 tests to verify pass**

```bash
pytest tests/test_phases_phase5_evidence.py -v --no-cov --tb=short
```

Expected: all PASS.

- [ ] **Step 11: Run full test suite**

```bash
./scripts/dev/test-cache.sh
```

Expected: all PASS. Look for any regression in `tests/test_phases*.py`.

- [ ] **Step 12: Stage + commit + push**

```bash
git add src/mcp_handlers/schemas/core.py src/mcp_handlers/updates/context.py src/mcp_handlers/updates/phases.py tests/test_pydantic_schemas.py tests/test_phases_phase5_evidence.py
./scripts/dev/ship.sh "phase-5: ToolResultEvidence + recent_tool_results field + iteration + deploy gate"
```

---

## Task 5: `describe_tool` returns documentation + `sequential_calibration.py` docstring fix + drift test

**Why bundled:** Both are doc-only fixes; the drift test catches future regressions in either direction.

**Files:**
- Modify: `src/sequential_calibration.py:36-47`
- Modify: wherever `describe_tool` returns block for `process_agent_update` lives — find via grep
- Test: new `tests/test_describe_tool_drift.py`

- [ ] **Step 1: Find `describe_tool` returns block source**

```bash
grep -rln "RETURNS\|returns block" src/mcp_handlers/admin/ src/tool_descriptions.py 2>/dev/null
grep -n "process_agent_update" src/tool_descriptions.py 2>/dev/null
```

Note the file. Subsequent steps reference it as `<DESCRIBE_FILE>`.

- [ ] **Step 2: Write failing drift test**

Create `tests/test_describe_tool_drift.py`:

```python
"""describe_tool returns block must mention every documented response field.

Catches the regression class that triggered spec rev 3 — a documented
contract drifting from actual behavior because nothing tests the description.
"""

import pytest


@pytest.mark.asyncio
async def test_process_agent_update_describe_mentions_prediction_id():
    from src.mcp_handlers.admin.system import handle_describe_tool  # adapt path
    result = await handle_describe_tool({"tool_name": "process_agent_update"})
    body = result[0].text  # MCP TextContent
    assert "prediction_id" in body, (
        "describe_tool returns block must document prediction_id "
        "(spec §6 — exposed in default response modes)"
    )


@pytest.mark.asyncio
async def test_process_agent_update_describe_mentions_warnings():
    from src.mcp_handlers.admin.system import handle_describe_tool
    result = await handle_describe_tool({"tool_name": "process_agent_update"})
    body = result[0].text
    assert "warnings" in body, (
        "describe_tool returns block must document warnings "
        "(spec §2 — surfaced via formatters)"
    )


@pytest.mark.asyncio
async def test_process_agent_update_describe_mentions_recent_tool_results():
    from src.mcp_handlers.admin.system import handle_describe_tool
    result = await handle_describe_tool({"tool_name": "process_agent_update"})
    body = result[0].text
    assert "recent_tool_results" in body, (
        "describe_tool block must document recent_tool_results "
        "(spec §1 — new agent contract field)"
    )
```

- [ ] **Step 3: Run to verify fail**

```bash
pytest tests/test_describe_tool_drift.py -v --no-cov --tb=short
```

Expected: 3 FAILS.

- [ ] **Step 4: Update describe_tool returns block**

In `<DESCRIBE_FILE>`, find the `process_agent_update` description's `RETURNS` block. Add (preserving existing structure):

```
- prediction_id (str, optional): A tactical prediction id. Pass this to outcome_event later
  to bind the (confidence, timestamp) pair from this check-in to a recorded outcome.
  Subject to TTL (default 3600s).
- warnings (List[str], optional): Per-call non-fatal warnings, e.g. evidence-record failures
  from recent_tool_results. Inspect to detect silent calibration-loss.
- recent_tool_results (input field, List[ToolResultEvidence]): Self-reported tool outcomes
  the agent just observed. Each item is iterated server-side under the
  UNITARES_PHASE5_EVIDENCE_WRITE flag; failures append to warnings.
```

- [ ] **Step 5: Run drift test to verify pass**

```bash
pytest tests/test_describe_tool_drift.py -v --no-cov --tb=short
```

Expected: 3 PASS.

- [ ] **Step 6: Fix `sequential_calibration.py` docstring**

In `src/sequential_calibration.py:36-47`, replace:

```
    No prediction_id seam yet — when calibration_checker.record_tactical_decision
    is called from observation paths, only confidence + immediate_outcome are
    available. A prediction_id seam is phase-two work and is required before
    composing this e-process with knowledge-graph or dialectic evidence streams.
```

with:

```
    The prediction_id seam is operational at the outcome_event tool level:
    register_tactical_prediction (governance_monitor) mints; outcome_event consumes
    via consume_prediction. The remaining gap was the report path — closed by the
    Refined Phase-5 Evidence Contract (docs/proposals/refined-phase-5-evidence-contract.md),
    which adds recent_tool_results to process_agent_update and emits outcome_event
    server-side per item with verification_source="agent_reported_tool_result".
```

- [ ] **Step 7: Run full test suite**

```bash
./scripts/dev/test-cache.sh
```

Expected: all PASS.

- [ ] **Step 8: Stage + commit + push**

```bash
git add src/sequential_calibration.py <DESCRIBE_FILE> tests/test_describe_tool_drift.py
./scripts/dev/ship.sh "phase-5: describe_tool returns + sequential_calibration docstring + drift test"
```

---

## Post-merge: deploy sequence

After all PRs merge to master and the LaunchAgent restarts (per `restart` command in the local CLAUDE.md), follow spec §8 deploy sequence:

1. **Default unset** — observe per-check-in counts in logs for 24h. Confirm counts are non-zero (agents are populating `recent_tool_results`) and within expected order of magnitude.
2. **Flip to `shadow`** — set `UNITARES_PHASE5_EVIDENCE_WRITE=shadow` in the LaunchAgent plist + restart. Run for 48h. Compare `(agent_reported, shadow)` distribution against current sparse mix using a quick query against `outcome_events.detail`.
3. **Flip to `1`** — once distribution looks acceptable, enable live writes. Watch dashboard calibration card for staleness flip from `signal_stale` to live values.

This deploy sequence is operator work, not a code task — left out of the per-task checklist.

---

## Self-review notes

**Spec coverage check:**
- §1 contract → Task 4 ✓
- §2 Phase-5 processing → Task 4 (iteration), Task 2 (warnings plumbing) ✓
- §3 verification_source → Task 3 ✓
- §4 prediction_binding echo → Task 1 ✓
- §5 hard TTL → Task 1 ✓
- §6 expose prediction_id → Task 2 ✓
- §7 docstring fix → Task 5 ✓
- §8 deploy gate → Task 4 ✓
- §9 compatibility bridge — out of v1 scope per spec ✓ (no task)
- All test plan items have a task ✓

**Type consistency:** `ToolResultEvidence` (Task 4) referenced in Task 5 docs. `prediction_binding` enum values consistent across Task 1 (compute) and Task 5 (docs). `verification_source` string matches across Tasks 3, 4, 5.

**Placeholder scan:** `<DESCRIBE_FILE>` in Task 5 is intentionally a discovery step (Task 5 Step 1). All other paths and code blocks are concrete.

**Bundling sanity:** Task 1 = visibility+enforcement together. Task 4 = schema+consumer+gate together. Both align with spec §"Implementation order" squashes.
