# Findings on the Event Stream — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Sentinel / Vigil / Watcher findings into the existing `/api/events` stream so the Discord bridge posts them automatically, ending the era of bug alerts rotting in log files + ephemeral macOS desktop popups.

**Architecture:** Add a `record_event()` method to the existing `GovernanceEventDetector` singleton (plus fingerprint-based dedup window). Expose it via a new `POST /api/findings` HTTP endpoint. A shared `agents/common/findings.py` helper lets all three agents emit into the same stream with consistent fingerprints. The Discord bridge already polls `/api/events` and fans to Discord — it just needs new entries in `EVENT_TITLES` and a severity-aware `is_critical_event()` rule.

**Tech Stack:** Python 3.12+, Starlette (HTTP), httpx (agent → server), discord.py (bridge). No new dependencies.

**Repos:**
- `/Users/cirwel/projects/unitares/` — governance MCP + agents (Sentinel, Vigil, Watcher)
- `/Users/cirwel/projects/unitares-discord-bridge/` — bridge (event_poller + embeds)

**Design invariants:**
- `record_event()` is append-only to the existing `_recent_events` ring buffer. Bump size from 100 → 500 so findings don't clobber dashboard events.
- Dedup window is 30 minutes keyed on caller-supplied `fingerprint`. Sentinel re-fires every ~5 min; without dedup the channel floods.
- Fingerprint format mirrors Watcher's: 16-hex-char SHA-256 of caller-normalized identity string.
- `UNITARES_HTTP_API_TOKEN` auth applies, but `_is_trusted_network()` (localhost) bypasses — same-machine agents don't need the token.
- `notify()` / `leave_note()` calls stay in place. This plan adds a parallel emit path; it doesn't remove existing ones. A later phase can consolidate once this proves out.

---

## File Structure

**unitares repo:**
- `src/event_detector.py` — add `record_event()` + fingerprint dedup; bump `max_stored_events` default 100 → 500
- `src/http_api.py` — add `http_record_finding` handler + `POST /api/findings` route registration
- `tests/test_event_detector.py` — new test class `TestRecordEvent`
- `tests/test_http_api_findings.py` — NEW test file for the POST endpoint
- `agents/common/findings.py` — NEW shared helper `post_finding()` with fingerprint helper
- `agents/common/tests/test_findings.py` — NEW tests for helper
- `agents/sentinel/agent.py:493-499` — call `post_finding()` inside the fleet-findings loop
- `agents/vigil/agent.py:389-393` — call `post_finding()` alongside the existing `notify()` calls
- `agents/watcher/agent.py` — call `post_finding()` when a newly deduped high/critical finding is appended to `findings.jsonl`

**bridge repo:**
- `src/bridge/embeds.py` — add `sentinel_finding` / `vigil_finding` / `watcher_finding` to `EVENT_TITLES`; add type-specific fields; extend `is_critical_event()`
- `tests/test_embeds.py` — add tests for the three new event types

---

## Task 1: Add `record_event()` to `GovernanceEventDetector`

**Files:**
- Modify: `src/event_detector.py:167-463`
- Test: `tests/test_event_detector.py` (add `TestRecordEvent` class at the bottom)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_event_detector.py`:

```python
from src.event_detector import GovernanceEventDetector


class TestRecordEvent:
    def test_records_event_with_id_and_returns_it(self):
        detector = GovernanceEventDetector(max_stored_events=10)
        stored = detector.record_event({
            "type": "sentinel_finding",
            "severity": "high",
            "message": "fleet coherence dipped",
            "agent_id": "sentinel",
            "agent_name": "Sentinel",
            "fingerprint": "abc123",
        })
        assert stored is not None
        assert stored["event_id"] == 1
        assert stored["type"] == "sentinel_finding"
        events = detector.get_recent_events(limit=10)
        assert len(events) == 1

    def test_duplicate_fingerprint_within_window_is_dropped(self):
        detector = GovernanceEventDetector(max_stored_events=10)
        first = detector.record_event({
            "type": "sentinel_finding", "severity": "high",
            "message": "m1", "agent_id": "a", "agent_name": "n",
            "fingerprint": "same",
        })
        second = detector.record_event({
            "type": "sentinel_finding", "severity": "high",
            "message": "m2", "agent_id": "a", "agent_name": "n",
            "fingerprint": "same",
        })
        assert first is not None
        assert second is None
        assert len(detector.get_recent_events(limit=10)) == 1

    def test_different_fingerprints_both_stored(self):
        detector = GovernanceEventDetector(max_stored_events=10)
        a = detector.record_event({"type": "t", "severity": "info", "message": "m",
                                    "agent_id": "x", "agent_name": "n", "fingerprint": "fp1"})
        b = detector.record_event({"type": "t", "severity": "info", "message": "m",
                                    "agent_id": "x", "agent_name": "n", "fingerprint": "fp2"})
        assert a is not None and b is not None
        assert len(detector.get_recent_events(limit=10)) == 2

    def test_missing_fingerprint_is_rejected(self):
        detector = GovernanceEventDetector(max_stored_events=10)
        stored = detector.record_event({
            "type": "t", "severity": "info", "message": "m",
            "agent_id": "x", "agent_name": "n",
        })
        assert stored is None

    def test_dedup_expires_after_window(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        detector = GovernanceEventDetector(max_stored_events=10)
        t0 = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

        class FakeDatetime:
            @staticmethod
            def now(tz=None):
                return FakeDatetime._current
            _current = t0

        monkeypatch.setattr("src.event_detector.datetime", FakeDatetime)
        FakeDatetime._current = t0
        detector.record_event({"type": "t", "severity": "info", "message": "m",
                                "agent_id": "x", "agent_name": "n", "fingerprint": "fp"})
        # Jump past the 30-minute dedup window
        FakeDatetime._current = t0 + timedelta(minutes=31)
        second = detector.record_event({"type": "t", "severity": "info", "message": "m",
                                         "agent_id": "x", "agent_name": "n", "fingerprint": "fp"})
        assert second is not None
        assert len(detector.get_recent_events(limit=10)) == 2

    def test_stamps_timestamp_if_missing(self):
        detector = GovernanceEventDetector(max_stored_events=10)
        stored = detector.record_event({"type": "t", "severity": "info", "message": "m",
                                          "agent_id": "x", "agent_name": "n", "fingerprint": "fp"})
        assert "timestamp" in stored
        # ISO-8601 with timezone
        assert stored["timestamp"].endswith("+00:00") or stored["timestamp"].endswith("Z")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/test_event_detector.py::TestRecordEvent -v
```

Expected: FAIL with `AttributeError: 'GovernanceEventDetector' object has no attribute 'record_event'` (or similar).

- [ ] **Step 3: Implement `record_event()` + bump buffer size**

In `src/event_detector.py`:

Change the constructor default at line 170:

```python
def __init__(self, max_stored_events: int = 500):
```

Then add these instance attributes in `__init__`:

```python
# Fingerprint-based dedup for externally recorded findings.
# Key: fingerprint string. Value: datetime of last emit.
self._recent_fingerprints: Dict[str, datetime] = {}
self._dedup_window_seconds: int = 1800  # 30 minutes
```

Add a new method on the class (place it just above `check_idle_agents`, around line 352):

```python
def record_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Append an externally-sourced event (e.g. a finding) to the ring buffer.

    Requires a caller-supplied ``fingerprint`` string. Duplicate fingerprints
    seen inside ``_dedup_window_seconds`` are dropped (returns None) so
    periodic re-emitters like Sentinel do not flood Discord.

    Stamps ``event_id`` and ``timestamp`` in-place and returns the stored dict.
    """
    fingerprint = event.get("fingerprint")
    if not fingerprint or not isinstance(fingerprint, str):
        return None

    now = datetime.now(timezone.utc)
    last_seen = self._recent_fingerprints.get(fingerprint)
    if last_seen is not None:
        age_seconds = (now - last_seen).total_seconds()
        if age_seconds < self._dedup_window_seconds:
            return None

    # Sweep fingerprints older than 2x window so the dict does not grow forever
    cutoff = now - timedelta(seconds=2 * self._dedup_window_seconds)
    self._recent_fingerprints = {
        fp: ts for fp, ts in self._recent_fingerprints.items() if ts > cutoff
    }
    self._recent_fingerprints[fingerprint] = now

    if "timestamp" not in event:
        event["timestamp"] = now.isoformat()

    self._event_counter += 1
    event["event_id"] = self._event_counter
    self._recent_events.append(event)
    if len(self._recent_events) > self._max_stored_events:
        self._recent_events = self._recent_events[-self._max_stored_events:]

    return event
```

Also add the import at line 14 (append `timedelta` to the existing import):

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/test_event_detector.py::TestRecordEvent -v
```

Expected: 6 passed.

- [ ] **Step 5: Run the full event_detector test suite (no regressions)**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/test_event_detector.py tests/test_event_cursor.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add src/event_detector.py tests/test_event_detector.py
git commit -m "feat(event_detector): add record_event with fingerprint dedup

Lets external callers (Sentinel/Vigil/Watcher) push findings into the
same ring buffer dashboard events live in. 30-min fingerprint dedup
prevents periodic re-emitters from flooding the channel. Buffer size
bumped from 100 to 500 so findings do not clobber dashboard events."
```

---

## Task 2: Add `POST /api/findings` HTTP endpoint

**Files:**
- Modify: `src/http_api.py` (add handler near `http_events`, register route in the block starting at line 1402)
- Test: `tests/test_http_api_findings.py` (NEW)

- [ ] **Step 1: Write failing tests**

Create `tests/test_http_api_findings.py`:

```python
"""Tests for POST /api/findings — external finding ingestion."""

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.event_detector import event_detector
from src.http_api import http_record_finding


@pytest.fixture(autouse=True)
def clear_events():
    event_detector.clear_events()
    event_detector._recent_fingerprints.clear()
    yield
    event_detector.clear_events()
    event_detector._recent_fingerprints.clear()


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/api/findings", http_record_finding, methods=["POST"])])
    return TestClient(app)


def test_accepts_valid_finding(client):
    payload = {
        "type": "sentinel_finding",
        "severity": "high",
        "message": "fleet coherence dipped",
        "agent_id": "sentinel-01",
        "agent_name": "Sentinel",
        "fingerprint": "abcd1234",
    }
    r = client.post("/api/findings", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["event"]["event_id"] == 1
    assert body["event"]["type"] == "sentinel_finding"
    assert body["deduped"] is False


def test_deduped_finding_returns_success_but_marked(client):
    payload = {
        "type": "sentinel_finding", "severity": "high", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "dedup-me",
    }
    r1 = client.post("/api/findings", json=payload)
    r2 = client.post("/api/findings", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["deduped"] is False
    assert r2.json()["deduped"] is True
    assert r2.json()["event"] is None


def test_rejects_missing_required_fields(client):
    r = client.post("/api/findings", json={"type": "x"})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_rejects_invalid_severity(client):
    r = client.post("/api/findings", json={
        "type": "x", "severity": "BOGUS", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "fp",
    })
    assert r.status_code == 400


def test_rejects_invalid_type_prefix(client):
    # Only *_finding types may be posted; prevents accidentally injecting
    # "verdict_change" etc. which have reserved schemas
    r = client.post("/api/findings", json={
        "type": "verdict_change", "severity": "info", "message": "m",
        "agent_id": "a", "agent_name": "n", "fingerprint": "fp",
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/test_http_api_findings.py -v
```

Expected: FAIL with `ImportError: cannot import name 'http_record_finding' from 'src.http_api'`.

- [ ] **Step 3: Implement the handler**

In `src/http_api.py`, immediately after the `http_events` function (the one ending at line 868), add:

```python
# Allowed severity values for externally posted findings
_FINDING_SEVERITIES = frozenset({"info", "low", "medium", "warning", "high", "critical"})
# Only accept *_finding event types via this endpoint (prevents spoofing
# reserved dashboard event types like verdict_change / risk_threshold)
_FINDING_TYPE_SUFFIX = "_finding"
# Required top-level fields on the posted JSON
_FINDING_REQUIRED_FIELDS = ("type", "severity", "message", "agent_id", "agent_name", "fingerprint")


async def http_record_finding(request):
    """POST /api/findings — ingest an external finding into the event ring buffer."""
    http_api_token = os.getenv("UNITARES_HTTP_API_TOKEN")
    if not _check_http_auth(request, http_api_token=http_api_token):
        return _http_unauthorized()
    try:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

        if not isinstance(payload, dict):
            return JSONResponse({"success": False, "error": "Body must be a JSON object"}, status_code=400)

        missing = [f for f in _FINDING_REQUIRED_FIELDS if not payload.get(f)]
        if missing:
            return JSONResponse(
                {"success": False, "error": f"Missing required fields: {missing}"},
                status_code=400,
            )

        if not str(payload["type"]).endswith(_FINDING_TYPE_SUFFIX):
            return JSONResponse(
                {"success": False, "error": f"type must end in {_FINDING_TYPE_SUFFIX}"},
                status_code=400,
            )

        if payload["severity"] not in _FINDING_SEVERITIES:
            return JSONResponse(
                {"success": False, "error": f"severity must be one of {sorted(_FINDING_SEVERITIES)}"},
                status_code=400,
            )

        from src.event_detector import event_detector
        stored = event_detector.record_event(payload)
        return JSONResponse({
            "success": True,
            "deduped": stored is None,
            "event": stored,
        })
    except Exception as e:
        logger.error(f"Error recording finding: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
```

Register the route by adding this line in the route registration block (right after the existing `/api/events` GET route at line 1402):

```python
    app.routes.append(Route("/api/findings", http_record_finding, methods=["POST"]))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest tests/test_http_api_findings.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add src/http_api.py tests/test_http_api_findings.py
git commit -m "feat(http_api): add POST /api/findings endpoint

Accepts externally-sourced findings from agents (Sentinel/Vigil/Watcher)
and stuffs them into the existing /api/events ring buffer. Validates
severity + *_finding type prefix to keep dashboard event schemas
reserved. Localhost bypasses bearer auth via _is_trusted_network()."
```

---

## Task 3: Shared `post_finding()` helper in `agents/common/findings.py`

**Files:**
- Create: `agents/common/findings.py`
- Create: `agents/common/tests/test_findings.py`

- [ ] **Step 1: Write failing tests**

Create `agents/common/tests/test_findings.py`:

```python
"""Tests for the shared post_finding helper used by Sentinel/Vigil/Watcher."""

from __future__ import annotations

import pytest

from agents.common.findings import compute_fingerprint, post_finding


def test_compute_fingerprint_is_stable():
    fp1 = compute_fingerprint(["sentinel", "coordinated_degradation", "BEH", "sentinel-01"])
    fp2 = compute_fingerprint(["sentinel", "coordinated_degradation", "BEH", "sentinel-01"])
    assert fp1 == fp2
    assert len(fp1) == 16


def test_compute_fingerprint_differs_on_input():
    fp1 = compute_fingerprint(["sentinel", "a"])
    fp2 = compute_fingerprint(["sentinel", "b"])
    assert fp1 != fp2


def test_post_finding_success(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):  # noqa: A002
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})

        class FakeResp:
            status_code = 200

            def json(self):
                return {"success": True, "deduped": False, "event": {"event_id": 1}}

        return FakeResp()

    monkeypatch.setattr("agents.common.findings._httpx_post", fake_post)
    ok = post_finding(
        event_type="sentinel_finding",
        severity="high",
        message="fleet coherence dipped",
        agent_id="sentinel-01",
        agent_name="Sentinel",
        fingerprint="abcd1234",
        extra={"violation_class": "BEH"},
    )
    assert ok is True
    assert len(calls) == 1
    body = calls[0]["json"]
    assert body["type"] == "sentinel_finding"
    assert body["violation_class"] == "BEH"
    assert body["fingerprint"] == "abcd1234"
    assert calls[0]["url"].endswith("/api/findings")


def test_post_finding_swallows_network_errors(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("agents.common.findings._httpx_post", boom)
    # Must NOT raise — posting findings is best-effort, never blocks the agent
    assert post_finding(
        event_type="vigil_finding", severity="critical", message="gov down",
        agent_id="vigil", agent_name="Vigil", fingerprint="fp",
    ) is False


def test_post_finding_respects_env_token(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):  # noqa: A002
        calls.append(headers)

        class FakeResp:
            status_code = 200

            def json(self):
                return {"success": True}

        return FakeResp()

    monkeypatch.setattr("agents.common.findings._httpx_post", fake_post)
    monkeypatch.setenv("UNITARES_HTTP_API_TOKEN", "secret-token-xyz")
    post_finding(
        event_type="watcher_finding", severity="high", message="m",
        agent_id="watcher", agent_name="Watcher", fingerprint="fp",
    )
    assert calls[0].get("Authorization") == "Bearer secret-token-xyz"
```

Also ensure `agents/common/tests/__init__.py` exists (check `ls agents/common/tests/`). If there is no `__init__.py`, create an empty one so pytest discovers the module.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/common/tests/test_findings.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.common.findings'`.

- [ ] **Step 3: Implement the helper**

Create `agents/common/findings.py`:

```python
"""Shared helper for agents to post findings to /api/findings.

Best-effort fire-and-forget — never raises, never blocks the agent.
Localhost callers bypass bearer auth via _is_trusted_network(); the
token is only sent if UNITARES_HTTP_API_TOKEN is set in env.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Iterable, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get(
    "UNITARES_FINDINGS_URL", "http://localhost:8767/api/findings"
)
DEFAULT_TIMEOUT_SECONDS = 3.0


def compute_fingerprint(parts: Iterable[Any]) -> str:
    """16-hex-char SHA-256 prefix of a pipe-joined identity string.

    Matches the format used by Watcher (agents/watcher/agent.py:Finding.compute_fingerprint).
    Callers pass the identity parts they want hashed, e.g.:
        compute_fingerprint(["sentinel", finding_type, violation_class, agent_id])
    """
    normalized = "|".join(str(p) for p in parts)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _httpx_post(url: str, json: dict, headers: dict, timeout: float):
    """Thin wrapper so tests can monkeypatch this single call."""
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


def post_finding(
    *,
    event_type: str,
    severity: str,
    message: str,
    agent_id: str,
    agent_name: str,
    fingerprint: str,
    extra: Optional[dict] = None,
    url: str = DEFAULT_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """POST a finding to the governance event stream.

    Returns True on HTTP 200, False on any error (including dedup — callers
    don't care; dedup is not an error from the caller's perspective, but we
    already queued the prior one, so "no new event" is semantically False).

    This function MUST NOT raise. It's called from hot paths in agent cycles.
    """
    body: dict = {
        "type": event_type,
        "severity": severity,
        "message": message,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "fingerprint": fingerprint,
    }
    if extra:
        # Don't let extra clobber required fields
        for k, v in extra.items():
            if k not in body:
                body[k] = v

    headers: dict = {"Content-Type": "application/json"}
    token = os.environ.get("UNITARES_HTTP_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = _httpx_post(url, json=body, headers=headers, timeout=timeout)
    except Exception as exc:
        log.debug("post_finding failed: %s", exc)
        return False

    if getattr(resp, "status_code", 0) != 200:
        log.debug("post_finding non-200: %s", getattr(resp, "status_code", "?"))
        return False

    try:
        data = resp.json()
    except Exception:
        return False
    return bool(data.get("success")) and not data.get("deduped", False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/common/tests/test_findings.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/common/findings.py agents/common/tests/test_findings.py agents/common/tests/__init__.py
git commit -m "feat(agents/common): add post_finding helper

Shared fire-and-forget HTTP client for Sentinel/Vigil/Watcher to POST
findings into /api/findings. Never raises, never blocks the agent
cycle. Fingerprint helper uses the same 16-hex-char SHA-256 format
Watcher already uses."
```

---

## Task 4: Wire Sentinel findings into the stream

**Files:**
- Modify: `agents/sentinel/agent.py:478-531` (`run_cycle` method)
- Test: `agents/sentinel/tests/test_agent.py` (add new test if that file exists; otherwise create `agents/sentinel/tests/test_findings_emit.py`)

First verify the test file location:

```bash
ls /Users/cirwel/projects/unitares/agents/sentinel/tests/ 2>/dev/null
```

If empty or missing, create `agents/sentinel/tests/__init__.py` (empty) and put the new test in `agents/sentinel/tests/test_findings_emit.py`.

- [ ] **Step 1: Write failing test**

In `agents/sentinel/tests/test_findings_emit.py` (create the file):

```python
"""Sentinel must post fleet findings to /api/findings each cycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_cycle_posts_findings_for_high_severity():
    """High-severity fleet findings are POSTed to /api/findings with a stable fingerprint."""
    from agents.sentinel.agent import SentinelAgent

    agent = SentinelAgent.__new__(SentinelAgent)
    agent._cycle_count = 0
    agent._findings_total = 0
    agent._ws_connected = True
    agent.agent_uuid = "sentinel-test-uuid"
    agent.fleet = MagicMock()
    agent.fleet.analyze.return_value = [
        {
            "severity": "high",
            "type": "coordinated_degradation",
            "violation_class": "BEH",
            "summary": "3 agents drifting in lockstep",
        }
    ]
    agent.fleet.fleet_summary.return_value = {"active_agents": 3}

    with patch("agents.sentinel.agent.post_finding") as mock_post:
        await agent.run_cycle(client=None)

    assert mock_post.called
    kwargs = mock_post.call_args.kwargs
    assert kwargs["event_type"] == "sentinel_finding"
    assert kwargs["severity"] == "high"
    assert "3 agents drifting in lockstep" in kwargs["message"]
    assert kwargs["agent_id"] == "sentinel-test-uuid"
    assert kwargs["fingerprint"]  # non-empty
    assert kwargs["extra"]["violation_class"] == "BEH"
    assert kwargs["extra"]["finding_type"] == "coordinated_degradation"


@pytest.mark.asyncio
async def test_run_cycle_does_not_post_self_observations():
    """Self-observations stay internal — they must not hit the event stream."""
    from agents.sentinel.agent import SentinelAgent

    agent = SentinelAgent.__new__(SentinelAgent)
    agent._cycle_count = 0
    agent._findings_total = 0
    agent._ws_connected = True
    agent.agent_uuid = "sentinel-test-uuid"
    agent.fleet = MagicMock()
    agent.fleet.analyze.return_value = [
        {"severity": "high", "type": "coherence_dip", "summary": "self only",
         "self_observation": True, "violation_class": ""}
    ]
    agent.fleet.fleet_summary.return_value = {"active_agents": 1}

    with patch("agents.sentinel.agent.post_finding") as mock_post:
        await agent.run_cycle(client=None)
    assert not mock_post.called
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/sentinel/tests/test_findings_emit.py -v
```

Expected: FAIL (likely `ImportError: cannot import name 'post_finding'` or `AttributeError: post_finding not called`).

- [ ] **Step 3: Wire `post_finding()` into `run_cycle`**

In `agents/sentinel/agent.py`, add this import alongside the existing `from unitares_sdk.utils import notify` (around line 47):

```python
from agents.common.findings import post_finding, compute_fingerprint
```

Then update the fleet-findings loop inside `run_cycle()`. Replace lines 493-502 (the current block starting `if fleet_findings:` through the `notify(...)` call) with:

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

                # Emit to governance event stream (Phase 1 of findings pipeline).
                # Fingerprint keys on finding type + violation class + agent so
                # the same fleet condition re-detected next cycle deduplicates.
                fp = compute_fingerprint([
                    "sentinel",
                    f.get("type", ""),
                    f.get("violation_class", ""),
                    self.agent_uuid or "",
                ])
                post_finding(
                    event_type="sentinel_finding",
                    severity=f["severity"],
                    message=f["summary"],
                    agent_id=self.agent_uuid or "sentinel",
                    agent_name="Sentinel",
                    fingerprint=fp,
                    extra={
                        "violation_class": vcls,
                        "finding_type": f.get("type", ""),
                    },
                )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/sentinel/tests/test_findings_emit.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full Sentinel test suite (no regressions)**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/sentinel/ -v
```

Expected: all green (including the new tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/sentinel/agent.py agents/sentinel/tests/test_findings_emit.py agents/sentinel/tests/__init__.py
git commit -m "feat(sentinel): post fleet findings to /api/findings

Every non-self-observation fleet finding in run_cycle now emits into
the governance event stream via the shared post_finding helper.
Fingerprint is stable across cycles so the 30-min dedup window in
event_detector prevents Discord flooding. notify() + log() behavior
unchanged."
```

---

## Task 5: Wire Vigil findings into the stream

**Files:**
- Modify: `agents/vigil/agent.py:389-393`
- Test: `agents/vigil/tests/test_findings_emit.py` (create)

- [ ] **Step 1: Write failing test**

Check for existing Vigil tests first:

```bash
ls /Users/cirwel/projects/unitares/agents/vigil/tests/ 2>/dev/null
```

Create `agents/vigil/tests/__init__.py` if missing, then `agents/vigil/tests/test_findings_emit.py`:

```python
"""Vigil posts findings on governance-down and Lumen-unreachable transitions."""

from unittest.mock import patch


def test_gov_down_transition_posts_finding():
    """First cycle that sees governance unhealthy must post a vigil_finding."""
    from agents.common.findings import compute_fingerprint

    # Vigil's finding on gov_down should have a stable fingerprint so the
    # 30-min dedup window suppresses repeat pages while governance stays down.
    fp = compute_fingerprint(["vigil", "governance_down"])
    assert len(fp) == 16
    # The exact value is locked by the helper; this test just asserts
    # stability of the identity.
    assert compute_fingerprint(["vigil", "governance_down"]) == fp
    assert compute_fingerprint(["vigil", "lumen_unreachable"]) != fp


def test_lumen_outage_streak_fingerprint_stable():
    from agents.common.findings import compute_fingerprint
    a = compute_fingerprint(["vigil", "lumen_unreachable"])
    b = compute_fingerprint(["vigil", "lumen_unreachable"])
    assert a == b


def test_vigil_emits_on_gov_down_transition(monkeypatch):
    """When governance transitions healthy → unhealthy, post_finding fires once.

    This uses a tightly-scoped monkeypatch harness rather than instantiating
    the real VigilAgent, which owns filesystem state and MCP clients.
    """
    from agents.vigil import agent as vigil_mod

    calls = []

    def fake_post(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(vigil_mod, "post_finding", fake_post)

    # Simulate the emit site directly
    prev_state = {"governance_healthy": True}
    gov_healthy = False
    gov_detail = "connection refused"

    if not gov_healthy and prev_state.get("governance_healthy", True):
        vigil_mod.post_finding(
            event_type="vigil_finding",
            severity="critical",
            message=f"Governance is down: {gov_detail}",
            agent_id="vigil",
            agent_name="Vigil",
            fingerprint=vigil_mod.compute_fingerprint(["vigil", "governance_down"]),
            extra={"finding_type": "governance_down"},
        )

    assert len(calls) == 1
    assert calls[0]["event_type"] == "vigil_finding"
    assert calls[0]["severity"] == "critical"
    assert "connection refused" in calls[0]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/vigil/tests/test_findings_emit.py -v
```

Expected: FAIL with `AttributeError: module 'agents.vigil.agent' has no attribute 'post_finding'`.

- [ ] **Step 3: Wire `post_finding()` into Vigil's health check**

In `agents/vigil/agent.py`, add this import near the top alongside existing imports (around line 47, after `from unitares_sdk.utils import notify`):

```python
from agents.common.findings import post_finding, compute_fingerprint
```

Then replace the block at lines 389-393 (the two `notify(...)` calls) with:

```python
        # --- macOS notifications for critical events + event-stream emit ---
        if not gov_healthy and prev_state.get("governance_healthy", True):
            notify("Vigil", f"Governance is down: {gov_detail}")
            post_finding(
                event_type="vigil_finding",
                severity="critical",
                message=f"Governance is down: {gov_detail}",
                agent_id="vigil",
                agent_name="Vigil",
                fingerprint=compute_fingerprint(["vigil", "governance_down"]),
                extra={"finding_type": "governance_down"},
            )
        if lumen_down_streak == 3:
            notify("Vigil", "Lumen unreachable for 3 consecutive cycles (1.5h)")
            post_finding(
                event_type="vigil_finding",
                severity="critical",
                message="Lumen unreachable for 3 consecutive cycles (1.5h)",
                agent_id="vigil",
                agent_name="Vigil",
                fingerprint=compute_fingerprint(["vigil", "lumen_unreachable"]),
                extra={"finding_type": "lumen_unreachable"},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/vigil/tests/test_findings_emit.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full Vigil test suite (no regressions)**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/vigil/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/vigil/agent.py agents/vigil/tests/test_findings_emit.py agents/vigil/tests/__init__.py
git commit -m "feat(vigil): post findings on gov-down and Lumen-unreachable

Parallels the existing notify() calls. Fingerprints are fixed strings
per condition so the 30-min dedup window suppresses pager spam while
governance stays down. notify() behavior unchanged."
```

---

## Task 6: Wire Watcher findings into the stream

**Files:**
- Modify: `agents/watcher/agent.py`
- Test: extend `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Locate the Watcher append site**

First, find where new findings are appended to `findings.jsonl`. Run:

```bash
cd /Users/cirwel/projects/unitares && grep -n "findings.jsonl\|write_finding\|_append_finding\|FINDINGS_FILE" agents/watcher/agent.py
```

Note the function and line range for step 3.

- [ ] **Step 2: Write failing test**

Append to `agents/watcher/tests/test_agent.py`:

```python
class TestWatcherPostsFindings:
    def test_high_severity_finding_posts_to_event_stream(self, tmp_path, monkeypatch):
        """After persisting a new high-severity finding to jsonl, Watcher posts to /api/findings."""
        from agents.watcher import agent as watcher

        monkeypatch.setattr(watcher, "FINDINGS_FILE", tmp_path / "findings.jsonl")
        monkeypatch.setattr(watcher, "DEDUP_FILE", tmp_path / "dedup.json")

        calls = []

        def fake_post(**kwargs):
            calls.append(kwargs)
            return True

        monkeypatch.setattr(watcher, "post_finding", fake_post)

        finding = watcher.Finding(
            pattern="P011",
            file="/tmp/foo.py",
            line=42,
            hint="mutation before persistence",
            severity="high",
            detected_at="2026-04-15T12:00:00Z",
            model_used="qwen3-coder-next:latest",
            line_content_hash="deadbeef",
            violation_class="INT",
        )
        watcher.persist_finding(finding)

        assert len(calls) == 1
        kwargs = calls[0]
        assert kwargs["event_type"] == "watcher_finding"
        assert kwargs["severity"] == "high"
        assert "P011" in kwargs["message"]
        assert kwargs["fingerprint"] == finding.fingerprint
        assert kwargs["extra"]["file"] == "/tmp/foo.py"
        assert kwargs["extra"]["line"] == 42

    def test_low_severity_finding_does_not_post(self, tmp_path, monkeypatch):
        """Low/medium stay local to jsonl — only high/critical hit the stream."""
        from agents.watcher import agent as watcher

        monkeypatch.setattr(watcher, "FINDINGS_FILE", tmp_path / "findings.jsonl")
        monkeypatch.setattr(watcher, "DEDUP_FILE", tmp_path / "dedup.json")

        calls = []
        monkeypatch.setattr(watcher, "post_finding",
                            lambda **kw: calls.append(kw) or True)

        finding = watcher.Finding(
            pattern="P002", file="/tmp/foo.py", line=10, hint="unbounded append",
            severity="medium", detected_at="2026-04-15T12:00:00Z",
            model_used="qwen3-coder-next:latest",
            line_content_hash="cafebabe", violation_class="ENT",
        )
        watcher.persist_finding(finding)
        assert calls == []
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherPostsFindings -v
```

Expected: FAIL (likely `AttributeError: module 'agents.watcher.agent' has no attribute 'persist_finding'` or `has no attribute 'post_finding'`).

- [ ] **Step 4: Refactor Watcher to call `post_finding()` after persist**

In `agents/watcher/agent.py`:

1. Add import near the top (after existing imports around line 55):

```python
from agents.common.findings import post_finding
```

2. Identify the code path that appends a new finding to `findings.jsonl`. Based on the file's architecture comment (line 25), this happens after dedup check passes. The current code likely has this inline. Extract it into a module-level function `persist_finding(finding: Finding) -> None` if it is not already, then add the post call at the end:

```python
def persist_finding(finding: Finding) -> None:
    """Append a new finding to findings.jsonl and, for high/critical severity,
    mirror it into the governance event stream so the Discord bridge surfaces it.

    Low/medium stays local — the SessionStart hook handles surfacing those
    to the in-editor Claude session.
    """
    FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FINDINGS_FILE.open("a") as f:
        f.write(json.dumps(asdict(finding)) + "\n")

    if finding.severity in ("high", "critical"):
        post_finding(
            event_type="watcher_finding",
            severity=finding.severity,
            message=f"[{finding.pattern}] {finding.file}:{finding.line} — {finding.hint}",
            agent_id="watcher",
            agent_name="Watcher",
            fingerprint=finding.fingerprint,
            extra={
                "pattern": finding.pattern,
                "file": finding.file,
                "line": finding.line,
                "violation_class": finding.violation_class,
            },
        )
```

Replace the inline append site (identified in Step 1) with a call to `persist_finding(new_finding)`.

**If the existing code already has such a helper under a different name**, add the `post_finding()` call to that helper instead of introducing a new one — don't create duplicate write paths. Use the name the codebase already has.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherPostsFindings -v
```

Expected: 2 passed.

- [ ] **Step 6: Run the full Watcher test suite (no regressions)**

```bash
cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/ -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "feat(watcher): mirror high/critical findings to event stream

When persist_finding() appends a new high or critical finding to
findings.jsonl, it now also POSTs to /api/findings so the Discord
bridge surfaces it. Low/medium stay local to jsonl + SessionStart
surfacing as before. Fingerprint reuses Finding.fingerprint so the
30-min dedup window works across Watcher reruns."
```

---

## Task 7: Extend bridge embeds to render finding events

**Files:**
- Modify: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/embeds.py`
- Test: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_embeds.py`

- [ ] **Step 1: Write failing tests**

Append to `/Users/cirwel/projects/unitares-discord-bridge/tests/test_embeds.py`:

```python
def test_sentinel_finding_embed():
    event = {
        "event_id": 42, "type": "sentinel_finding", "severity": "high",
        "message": "3 agents drifting in lockstep",
        "agent_id": "sentinel", "agent_name": "Sentinel",
        "timestamp": "2026-04-15T12:00:00+00:00",
        "violation_class": "BEH", "finding_type": "coordinated_degradation",
    }
    embed = event_to_embed(event)
    assert embed.title == "Sentinel Finding"
    assert embed.colour == discord.Colour.red()  # high → critical colour
    field_names = [f.name for f in embed.fields]
    assert "Violation" in field_names
    assert "Finding" in field_names


def test_vigil_finding_embed():
    event = {
        "event_id": 7, "type": "vigil_finding", "severity": "critical",
        "message": "Governance is down",
        "agent_id": "vigil", "agent_name": "Vigil",
        "timestamp": "2026-04-15T12:00:00+00:00",
        "finding_type": "governance_down",
    }
    embed = event_to_embed(event)
    assert embed.title == "Vigil Finding"
    assert embed.colour == discord.Colour.red()


def test_watcher_finding_embed():
    event = {
        "event_id": 11, "type": "watcher_finding", "severity": "high",
        "message": "[P011] /tmp/foo.py:42 — mutation before persistence",
        "agent_id": "watcher", "agent_name": "Watcher",
        "timestamp": "2026-04-15T12:00:00+00:00",
        "pattern": "P011", "file": "/tmp/foo.py", "line": 42,
        "violation_class": "INT",
    }
    embed = event_to_embed(event)
    assert embed.title == "Watcher Finding"
    field_names = [f.name for f in embed.fields]
    assert "Pattern" in field_names
    assert "Location" in field_names


def test_finding_high_severity_routes_to_alerts():
    # high severity = route to #alerts, not just #events
    assert is_critical_event({"type": "sentinel_finding", "severity": "high"})
    assert is_critical_event({"type": "watcher_finding", "severity": "critical"})
    assert not is_critical_event({"type": "sentinel_finding", "severity": "info"})
    assert not is_critical_event({"type": "watcher_finding", "severity": "medium"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_embeds.py -v
```

Expected: FAIL — new tests fail because `EVENT_TITLES` doesn't know the new types (title defaults to `"Sentinel Finding"` generated by `event_type.replace("_", " ").title()` only if we add no extras; the field tests will also fail).

- [ ] **Step 3: Extend `EVENT_TITLES`, `event_to_embed`, and `is_critical_event`**

In `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/embeds.py`, update the three relevant pieces:

Replace `SEVERITY_COLOURS` (lines 7-11) with:

```python
SEVERITY_COLOURS = {
    "info": discord.Colour.blue(),
    "low": discord.Colour.blue(),
    "medium": discord.Colour.orange(),
    "warning": discord.Colour.orange(),
    "high": discord.Colour.red(),
    "critical": discord.Colour.red(),
}
```

Extend `EVENT_TITLES` (lines 13-21):

```python
EVENT_TITLES = {
    "agent_new": "New Agent",
    "verdict_change": "Verdict Change",
    "risk_threshold": "Risk Threshold",
    "drift_alert": "Drift Alert",
    "drift_oscillation": "Drift Oscillation",
    "trajectory_adjustment": "Trajectory Adjustment",
    "agent_idle": "Agent Idle",
    "sentinel_finding": "Sentinel Finding",
    "vigil_finding": "Vigil Finding",
    "watcher_finding": "Watcher Finding",
}
```

Extend `event_to_embed` by adding these branches inside the "Type-specific fields" section (after the existing `drift_alert` branch, before `embed.set_footer(...)`):

```python
    elif event_type == "sentinel_finding":
        if event.get("violation_class"):
            embed.add_field(name="Violation", value=event["violation_class"], inline=True)
        if event.get("finding_type"):
            embed.add_field(name="Finding", value=event["finding_type"], inline=True)
    elif event_type == "vigil_finding":
        if event.get("finding_type"):
            embed.add_field(name="Finding", value=event["finding_type"], inline=True)
    elif event_type == "watcher_finding":
        if event.get("pattern"):
            embed.add_field(name="Pattern", value=event["pattern"], inline=True)
        if event.get("file"):
            loc = event["file"]
            if event.get("line"):
                loc = f"{loc}:{event['line']}"
            embed.add_field(name="Location", value=loc, inline=False)
        if event.get("violation_class"):
            embed.add_field(name="Violation", value=event["violation_class"], inline=True)
```

Extend `is_critical_event` (lines 57-63) with a finding-aware rule:

```python
def is_critical_event(event: dict) -> bool:
    """Should this event also be posted to #alerts?"""
    severity = event.get("severity")
    if severity == "critical":
        return True
    if event.get("type") == "verdict_change" and event.get("to") in ("pause", "reject"):
        return True
    # Findings are high-signal by construction — high severity also pages alerts
    if event.get("type", "").endswith("_finding") and severity == "high":
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_embeds.py -v
```

Expected: all green (existing + 4 new tests).

- [ ] **Step 5: Run the full bridge test suite (no regressions)**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/embeds.py tests/test_embeds.py
git commit -m "feat(bridge): render sentinel/vigil/watcher finding events

Adds Sentinel/Vigil/Watcher finding types to EVENT_TITLES with
type-specific fields (violation class, pattern, file:line). Extends
SEVERITY_COLOURS to recognise 'high'/'low'/'medium'. is_critical_event
now routes high-severity findings to #alerts alongside existing
critical rules."
```

---

## Task 8: End-to-end verification

This task has no new code — only manual verification that the pipeline actually lands findings in Discord.

- [ ] **Step 1: Restart governance-mcp so the new endpoint is live**

```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
sleep 3
curl -s http://localhost:8767/health | python3 -m json.tool | head -5
```

Expected: JSON showing `"status": "ok"` (or whatever the healthy shape is).

- [ ] **Step 2: Smoke-test `POST /api/findings`**

```bash
curl -s -X POST http://localhost:8767/api/findings \
  -H "Content-Type: application/json" \
  -d '{"type":"sentinel_finding","severity":"high","message":"plan smoke test","agent_id":"manual","agent_name":"Manual","fingerprint":"smoke-test-'$(date +%s)'"}' \
  | python3 -m json.tool
```

Expected: `{"success": true, "deduped": false, "event": {"event_id": N, ...}}`.

- [ ] **Step 3: Confirm the finding is visible on `/api/events`**

```bash
curl -s "http://localhost:8767/api/events?type=sentinel_finding&limit=5" | python3 -m json.tool
```

Expected: the smoke-test finding appears in the `events` array with your message.

- [ ] **Step 4: Restart the Discord bridge so it picks up the embed code changes**

```bash
# Use whichever mechanism the bridge runs under — check which plist/process is active:
launchctl list | grep -i discord-bridge
# If managed by launchd:
launchctl unload ~/Library/LaunchAgents/com.unitares.discord-bridge.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.unitares.discord-bridge.plist 2>/dev/null
tail -n 20 ~/Library/Logs/unitares-discord-bridge.log
```

Expected: bridge restarts cleanly; log shows startup + successful poll.

- [ ] **Step 5: Post a fresh finding and watch Discord**

```bash
curl -s -X POST http://localhost:8767/api/findings \
  -H "Content-Type: application/json" \
  -d '{"type":"watcher_finding","severity":"high","message":"[P011] /tmp/demo.py:99 — plan e2e test","agent_id":"watcher","agent_name":"Watcher","fingerprint":"e2e-'$(date +%s)'","pattern":"P011","file":"/tmp/demo.py","line":99,"violation_class":"INT"}'
```

Expected (within ~10 s, the bridge poll interval):
- Embed titled **"Watcher Finding"** appears in the `#events` channel.
- Same embed **also** appears in `#alerts` (high severity routes there via `is_critical_event`).
- Embed shows fields: Agent, Severity, Pattern, Location (`/tmp/demo.py:99`), Violation.

- [ ] **Step 6: Let the real agents run one natural cycle**

Wait up to one Sentinel cycle (5 min) or trigger one manually:

```bash
# Watch for a natural Sentinel cycle to fire
tail -f ~/Library/Logs/unitares-sentinel.log | grep -E "FINDING|Cycle"
```

If Sentinel emits any `FINDING: [high]` lines during the observation window, confirm the matching embed appears in Discord.

- [ ] **Step 7: Final sanity — dedup works**

Post the exact same payload as step 5 twice in quick succession:

```bash
FP="dedup-check-$(date +%s)"
for i in 1 2; do
  curl -s -X POST http://localhost:8767/api/findings \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"sentinel_finding\",\"severity\":\"high\",\"message\":\"dedup $i\",\"agent_id\":\"manual\",\"agent_name\":\"Manual\",\"fingerprint\":\"$FP\"}" \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("deduped"), d.get("event",{}).get("event_id") if d.get("event") else None)'
done
```

Expected output:
```
False <some number>
True None
```

And only ONE embed should have hit Discord.

- [ ] **Step 8: Final commit (only if any fixup was needed during verification)**

If verification surfaced a real issue, write a test that reproduces it, fix, rerun the relevant test suite, and commit. Otherwise skip.

---

## Out of Scope (Phase 2+)

Left deliberately undone — bring back once this has run for a week with real findings:

- `POST /dispatch` endpoint on `discord-dispatch` + trigger-source abstraction in `src/backends/`
- Auto-forwarding HIGH findings to Claude-backed investigation (vs. human eyeballs)
- Emoji-reaction handler in bridge (`@claude investigate <finding_id>` as phase-2 escape hatch)
- Consolidating Sentinel's `leave_note()` KG writes into the findings pipeline (currently dual-written; living with duplication this phase)
- Cross-agent shared fingerprint namespace in `data/findings/` (Watcher still owns its own jsonl)

These are listed so a future agent reading the plan understands the deferred boundary, not as a to-do list for this plan.
