# Watcher Governance Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Watcher a persistent governance identity, periodic check-ins, and a resolution audit trail so finding judgments are tracked across sessions and agents.

**Architecture:** Three additive changes to `agents/watcher/agent.py`: (1) identity resolution preamble in `main()` using `SyncGovernanceClient`, (2) check-in logic appended to `surface_pending()`, (3) governance event posting added to `update_finding_status()`. No new files — all changes are in the existing agent module and its test file.

**Tech Stack:** `unitares_sdk.SyncGovernanceClient` (REST transport), `agents.common.findings.post_finding`, existing `data/watcher/state.json` for scan counter persistence.

**Spec:** `docs/superpowers/specs/2026-04-16-watcher-governance-checkin-design.md`

---

### Task 1: Identity resolution

**Files:**
- Modify: `agents/watcher/agent.py` (add identity module, update `main()`)
- Modify: `.gitignore` (add `.watcher_session`)
- Test: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Write failing tests for identity resolution**

Add to `agents/watcher/tests/test_agent.py`:

```python
# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


SESSION_FILE_NAME = ".watcher_session"


class TestWatcherIdentity:
    """Watcher identity resolution: token resume → name resume → fresh onboard."""

    def test_fresh_onboard_when_no_session_file(self, watcher_module, tmp_path, monkeypatch):
        """First-ever invocation: no .watcher_session → fresh onboard."""
        session_file = tmp_path / SESSION_FILE_NAME
        monkeypatch.setattr(watcher_module, "SESSION_FILE", session_file)

        onboard_called = {}

        class FakeClient:
            client_session_id = "sess-123"
            continuity_token = "tok-abc"
            agent_uuid = "uuid-watcher-001"

            def onboard(self, name, **kwargs):
                onboard_called["name"] = name
                onboard_called["kwargs"] = kwargs
                return type("R", (), {"success": True})()

        watcher_module.resolve_identity(FakeClient())
        identity = watcher_module.get_watcher_identity()

        assert onboard_called["name"] == "Watcher"
        assert onboard_called["kwargs"].get("spawn_reason") == "resident_observer"
        assert identity["agent_uuid"] == "uuid-watcher-001"
        assert session_file.exists()

    def test_token_resume_when_session_exists(self, watcher_module, tmp_path, monkeypatch):
        """Session file with continuity_token → token resume, no onboard."""
        session_file = tmp_path / SESSION_FILE_NAME
        session_file.write_text(json.dumps({
            "client_session_id": "old-sess",
            "continuity_token": "old-tok",
            "agent_uuid": "uuid-watcher-001",
        }))
        monkeypatch.setattr(watcher_module, "SESSION_FILE", session_file)

        identity_called = {}
        onboard_called = {}

        class FakeClient:
            client_session_id = "new-sess"
            continuity_token = "new-tok"
            agent_uuid = "uuid-watcher-001"

            def identity(self, **kwargs):
                identity_called.update(kwargs)
                return type("R", (), {"success": True})()

            def onboard(self, name, **kwargs):
                onboard_called["name"] = name

        watcher_module.resolve_identity(FakeClient())
        assert identity_called.get("continuity_token") == "old-tok"
        assert identity_called.get("resume") is True
        assert not onboard_called  # should NOT have fallen through to onboard

    def test_name_resume_when_token_fails(self, watcher_module, tmp_path, monkeypatch):
        """Token resume fails → fall back to name resume."""
        session_file = tmp_path / SESSION_FILE_NAME
        session_file.write_text(json.dumps({
            "continuity_token": "stale-tok",
            "agent_uuid": "uuid-old",
        }))
        monkeypatch.setattr(watcher_module, "SESSION_FILE", session_file)

        calls = []

        class FakeClient:
            client_session_id = "new-sess"
            continuity_token = "new-tok"
            agent_uuid = "uuid-watcher-001"

            def identity(self, **kwargs):
                calls.append(("identity", kwargs))
                if kwargs.get("continuity_token"):
                    raise RuntimeError("token expired")
                return type("R", (), {"success": True})()

            def onboard(self, name, **kwargs):
                calls.append(("onboard", name))

        watcher_module.resolve_identity(FakeClient())
        assert calls[0] == ("identity", {"continuity_token": "stale-tok", "resume": True})
        assert calls[1] == ("identity", {"name": "Watcher", "resume": True})
        assert len(calls) == 2  # no onboard needed

    def test_governance_down_leaves_identity_none(self, watcher_module, tmp_path, monkeypatch):
        """If governance is unreachable, identity is None — scanning still works."""
        session_file = tmp_path / SESSION_FILE_NAME
        monkeypatch.setattr(watcher_module, "SESSION_FILE", session_file)

        class FakeClient:
            def onboard(self, *a, **kw):
                raise ConnectionError("governance down")

            def identity(self, **kw):
                raise ConnectionError("governance down")

        watcher_module.resolve_identity(FakeClient())
        assert watcher_module.get_watcher_identity() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherIdentity -v`
Expected: FAIL — `resolve_identity` and `get_watcher_identity` don't exist yet.

- [ ] **Step 3: Implement identity resolution**

In `agents/watcher/agent.py`, after the existing imports and constants (after line 69), add:

```python
# ---------------------------------------------------------------------------
# Identity — persistent governance presence
# ---------------------------------------------------------------------------

SESSION_FILE = PROJECT_ROOT / ".watcher_session"

_watcher_identity: dict[str, str] | None = None


def _load_session() -> dict[str, str]:
    """Load .watcher_session if it exists."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_session(client_session_id: str, continuity_token: str, agent_uuid: str) -> None:
    """Persist identity state to .watcher_session."""
    data = {
        "client_session_id": client_session_id,
        "continuity_token": continuity_token,
        "agent_uuid": agent_uuid,
    }
    try:
        SESSION_FILE.write_text(json.dumps(data))
    except OSError as e:
        log(f"failed to save session: {e}", "warning")


def resolve_identity(client) -> None:
    """Three-step identity resolution: token → name → fresh onboard.

    Sets module-level _watcher_identity on success, leaves it None on failure.
    Mirrors the GovernanceAgent._ensure_identity pattern but synchronous.
    """
    global _watcher_identity
    saved = _load_session()

    # Step 1: Token resume (strong)
    if saved.get("continuity_token"):
        try:
            client.identity(continuity_token=saved["continuity_token"], resume=True)
            _sync_identity(client)
            return
        except Exception as e:
            log(f"token resume failed: {e}", "warning")

    # Step 2: Name resume (weak)
    try:
        client.identity(name="Watcher", resume=True)
        _sync_identity(client)
        return
    except Exception as e:
        log(f"name resume failed: {e}", "warning")

    # Step 3: Fresh onboard
    try:
        client.onboard("Watcher", spawn_reason="resident_observer")
        _sync_identity(client)
    except Exception as e:
        log(f"onboard failed — identity unavailable: {e}", "warning")
        _watcher_identity = None


def _sync_identity(client) -> None:
    """Capture identity from client after successful resolution."""
    global _watcher_identity
    _watcher_identity = {
        "client_session_id": client.client_session_id or "",
        "continuity_token": client.continuity_token or "",
        "agent_uuid": client.agent_uuid or "",
    }
    _save_session(
        _watcher_identity["client_session_id"],
        _watcher_identity["continuity_token"],
        _watcher_identity["agent_uuid"],
    )


def get_watcher_identity() -> dict[str, str] | None:
    """Return resolved identity or None if governance is unavailable."""
    return _watcher_identity
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherIdentity -v`
Expected: 4 passed.

- [ ] **Step 5: Add `.watcher_session` to `.gitignore`**

In `.gitignore`, after the `.sentinel_state` line (line 177), add:

```
.watcher_session
```

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py .gitignore
git commit -m "feat(watcher): add identity resolution with three-step resume

Token resume → name resume → fresh onboard, matching the GovernanceAgent
pattern but synchronous via SyncGovernanceClient. Graceful degradation:
if governance is down, identity stays None and scanning continues."
```

---

### Task 2: Wire identity into main()

**Files:**
- Modify: `agents/watcher/agent.py:1493-1565` (`main()` function)

- [ ] **Step 1: Write failing test for identity wiring**

Add to `agents/watcher/tests/test_agent.py`:

```python
class TestMainIdentityWiring:
    """main() calls resolve_identity before dispatching subcommands."""

    def test_main_resolves_identity_before_scan(self, watcher_module, tmp_path, monkeypatch):
        """--file path triggers identity resolution before scanning."""
        resolved = {"called": False}

        original_resolve = watcher_module.resolve_identity

        def mock_resolve(client):
            resolved["called"] = True

        monkeypatch.setattr(watcher_module, "resolve_identity", mock_resolve)
        # Make scan_file a no-op so we don't need a real file
        monkeypatch.setattr(watcher_module, "scan_file", lambda *a, **kw: [])
        # Prevent SyncGovernanceClient from connecting
        monkeypatch.setattr(
            watcher_module, "_make_identity_client",
            lambda: type("C", (), {
                "onboard": lambda *a, **kw: None,
                "identity": lambda **kw: None,
                "client_session_id": None,
                "continuity_token": None,
                "agent_uuid": None,
            })(),
        )

        monkeypatch.setattr("sys.argv", ["watcher", "--file", "/dev/null"])
        watcher_module.main()
        assert resolved["called"]

    def test_main_proceeds_when_governance_down(self, watcher_module, tmp_path, monkeypatch):
        """Governance failure during identity doesn't prevent scan."""
        scan_called = {"called": False}
        original_scan = watcher_module.scan_file

        def mock_scan(*a, **kw):
            scan_called["called"] = True
            return []

        monkeypatch.setattr(watcher_module, "scan_file", mock_scan)
        monkeypatch.setattr(
            watcher_module, "_make_identity_client",
            lambda: (_ for _ in ()).throw(ConnectionError("down")),
        )

        monkeypatch.setattr("sys.argv", ["watcher", "--file", "/dev/null"])
        watcher_module.main()
        assert scan_called["called"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestMainIdentityWiring -v`
Expected: FAIL — `_make_identity_client` doesn't exist, `main()` doesn't call `resolve_identity`.

- [ ] **Step 3: Add identity wiring to main()**

In `agents/watcher/agent.py`, add a factory function near the identity section:

```python
def _make_identity_client():
    """Create a SyncGovernanceClient for identity resolution."""
    from unitares_sdk import SyncGovernanceClient
    return SyncGovernanceClient(rest_url=GOV_REST_URL, transport="rest", timeout=5)
```

Then modify `main()`. After `args = parser.parse_args()` (line 1548) and before the subcommand dispatch (line 1550), insert:

```python
    # --- Identity resolution (best-effort) ---
    try:
        client = _make_identity_client()
        resolve_identity(client)
    except Exception as e:
        log(f"identity resolution skipped: {e}", "warning")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestMainIdentityWiring -v`
Expected: 2 passed.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -v --tb=short`
Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "feat(watcher): wire identity resolution into main()

resolve_identity runs once before subcommand dispatch. Governance
failures are caught — scanning proceeds regardless."
```

---

### Task 3: Check-in after surface_pending

**Files:**
- Modify: `agents/watcher/agent.py` (add check-in helpers, modify `surface_pending()`)
- Test: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Write failing tests for check-in**

Add to `agents/watcher/tests/test_agent.py`:

```python
class TestWatcherCheckin:
    """Check-in appended to surface_pending()."""

    def _write_findings(self, watcher_module, findings: list[dict]):
        """Helper: write findings to the isolated findings.jsonl."""
        watcher_module.FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with watcher_module.FINDINGS_FILE.open("w") as f:
            for finding in findings:
                f.write(json.dumps(finding) + "\n")

    def test_checkin_posts_summary_after_surface(self, watcher_module, monkeypatch):
        """surface_pending() calls checkin with a summary of current findings."""
        self._write_findings(watcher_module, [
            {"fingerprint": "aaa1", "status": "open", "severity": "high",
             "pattern": "P001", "file": "/tmp/x.py", "line": 10, "hint": "bad",
             "timestamp": datetime.now(timezone.utc).isoformat()},
            {"fingerprint": "bbb2", "status": "confirmed", "severity": "medium",
             "pattern": "P002", "file": "/tmp/y.py", "line": 20, "hint": "ok",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])

        # Set up identity so check-in proceeds
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-w", "client_session_id": "s1", "continuity_token": "t1",
        })

        checkin_args = {}

        class FakeClient:
            client_session_id = "s1"
            continuity_token = "t1"
            agent_uuid = "uuid-w"

            def checkin(self, **kwargs):
                checkin_args.update(kwargs)
                return type("R", (), {"success": True, "verdict": "proceed",
                                      "guidance": None, "coherence": 0.5,
                                      "metrics": {}})()

        monkeypatch.setattr(watcher_module, "_make_identity_client", lambda: FakeClient())

        watcher_module.surface_pending()

        assert "response_text" in checkin_args
        assert "1 confirmed" in checkin_args["response_text"]
        assert checkin_args["complexity"] > 0  # has open findings
        assert checkin_args["response_mode"] == "compact"

    def test_checkin_skipped_when_no_identity(self, watcher_module, monkeypatch):
        """No identity → surface works, check-in silently skipped."""
        monkeypatch.setattr(watcher_module, "_watcher_identity", None)

        self._write_findings(watcher_module, [
            {"fingerprint": "ccc3", "status": "open", "severity": "low",
             "pattern": "P003", "file": "/tmp/z.py", "line": 5, "hint": "meh",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])

        # surface_pending should complete without error
        result = watcher_module.surface_pending()
        assert result == 0

    def test_checkin_idle_heartbeat(self, watcher_module, monkeypatch):
        """No findings at all → idle heartbeat with low complexity."""
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-w", "client_session_id": "s1", "continuity_token": "t1",
        })

        checkin_args = {}

        class FakeClient:
            client_session_id = "s1"
            continuity_token = "t1"
            agent_uuid = "uuid-w"

            def checkin(self, **kwargs):
                checkin_args.update(kwargs)
                return type("R", (), {"success": True, "verdict": "proceed",
                                      "guidance": None, "coherence": 0.5,
                                      "metrics": {}})()

        monkeypatch.setattr(watcher_module, "_make_identity_client", lambda: FakeClient())

        watcher_module.surface_pending()

        assert "idle" in checkin_args["response_text"].lower()
        assert checkin_args["complexity"] <= 0.1

    def test_complexity_scales_with_open_findings(self, watcher_module):
        """complexity = 0.1 at 0 findings, 0.6 at 10+, linear between."""
        assert watcher_module.compute_checkin_complexity(0) == pytest.approx(0.1)
        assert watcher_module.compute_checkin_complexity(5) == pytest.approx(0.35)
        assert watcher_module.compute_checkin_complexity(10) == pytest.approx(0.6)
        assert watcher_module.compute_checkin_complexity(20) == pytest.approx(0.6)  # capped

    def test_confidence_from_resolution_ratio(self, watcher_module):
        """confidence = confirmed / (confirmed + dismissed), default 0.7 during warmup."""
        assert watcher_module.compute_checkin_confidence(0, 0) == pytest.approx(0.7)  # warmup
        assert watcher_module.compute_checkin_confidence(3, 1) == pytest.approx(0.7)  # < 5 total
        assert watcher_module.compute_checkin_confidence(4, 1) == pytest.approx(0.8)  # 5 total
        assert watcher_module.compute_checkin_confidence(0, 5) == pytest.approx(0.0)  # all dismissed
        assert watcher_module.compute_checkin_confidence(5, 0) == pytest.approx(1.0)  # all confirmed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherCheckin -v`
Expected: FAIL — `compute_checkin_complexity`, `compute_checkin_confidence` don't exist, `surface_pending` doesn't check in.

- [ ] **Step 3: Implement check-in helpers and wire into surface_pending**

In `agents/watcher/agent.py`, add after the identity section:

```python
# ---------------------------------------------------------------------------
# Check-in — periodic EISV signal to governance
# ---------------------------------------------------------------------------


def compute_checkin_complexity(active_count: int) -> float:
    """Map active finding count to complexity: 0→0.1, 10+→0.6, linear between."""
    return min(0.6, 0.1 + active_count * 0.05)


def compute_checkin_confidence(confirmed: int, dismissed: int) -> float:
    """Confirmed / (confirmed + dismissed), with warmup default of 0.7."""
    total = confirmed + dismissed
    if total < 5:
        return 0.7
    return confirmed / total


def _build_checkin_summary() -> tuple[str, float, float]:
    """Build check-in response_text, complexity, and confidence from findings.jsonl."""
    findings = _iter_findings_raw()
    if not findings:
        return "Watcher idle", 0.05, 0.9

    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        status = f.get("status", "open")
        by_status[status] = by_status.get(status, 0) + 1
        if status in ("open", "surfaced"):
            sev = f.get("severity", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1

    active = by_status.get("open", 0) + by_status.get("surfaced", 0)
    confirmed = by_status.get("confirmed", 0)
    dismissed = by_status.get("dismissed", 0)

    sev_parts = ", ".join(f"{n} {s}" for s, n in sorted(by_severity.items()) if n > 0)
    summary_parts = []
    if active:
        summary_parts.append(f"{active} unresolved ({sev_parts})" if sev_parts else f"{active} unresolved")
    if confirmed:
        summary_parts.append(f"{confirmed} confirmed")
    if dismissed:
        summary_parts.append(f"{dismissed} dismissed")
    summary = f"Watcher: {', '.join(summary_parts)}" if summary_parts else "Watcher idle"

    complexity = compute_checkin_complexity(active)
    confidence = compute_checkin_confidence(confirmed, dismissed)
    return summary, complexity, confidence


def _do_checkin() -> None:
    """Post a check-in to governance. Called at the end of surface_pending()."""
    identity = get_watcher_identity()
    if identity is None:
        return

    summary, complexity, confidence = _build_checkin_summary()

    try:
        client = _make_identity_client()
        # Restore identity state so the client can inject session args
        client.client_session_id = identity["client_session_id"]
        client.continuity_token = identity["continuity_token"]
        client.agent_uuid = identity["agent_uuid"]

        client.checkin(
            response_text=summary,
            complexity=complexity,
            confidence=confidence,
            response_mode="compact",
        )
        log(f"check-in: {summary}")
    except Exception as e:
        log(f"check-in failed: {e}", "warning")
```

Then modify `surface_pending()`. At the end of the function, before `return 0` (currently line 989), add:

```python
    # --- Check in to governance ---
    _do_checkin()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherCheckin -v`
Expected: 5 passed.

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "feat(watcher): add governance check-in after surface_pending

Check-in runs at the end of surface_pending() with a summary of
current finding stats. Complexity scales with active finding count,
confidence from confirmed/dismissed ratio with warmup dampening.
Skipped gracefully when governance is down or identity is unresolved."
```

---

### Task 4: Resolution audit trail

**Files:**
- Modify: `agents/watcher/agent.py` (`update_finding_status()`, `main()` argparse)
- Test: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Write failing tests for resolution events**

Add to `agents/watcher/tests/test_agent.py`:

```python
class TestResolutionAuditTrail:
    """--resolve/--dismiss posts watcher_resolution governance events."""

    def _write_findings(self, watcher_module, findings: list[dict]):
        watcher_module.FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with watcher_module.FINDINGS_FILE.open("w") as f:
            for finding in findings:
                f.write(json.dumps(finding) + "\n")

    def test_resolve_posts_governance_event(self, watcher_module, monkeypatch):
        """--resolve posts a watcher_resolution event with action=confirmed."""
        self._write_findings(watcher_module, [
            {"fingerprint": "ff27c1b200000000", "status": "open", "severity": "high",
             "pattern": "P004", "file": "/tmp/x.py", "line": 97,
             "hint": "asyncpg deadlock", "violation_class": "REC",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-watcher",
            "client_session_id": "s1",
            "continuity_token": "t1",
        })

        posted = {}
        monkeypatch.setattr(watcher_module, "post_finding", lambda **kw: posted.update(kw) or True)

        watcher_module.update_finding_status("ff27c1b2", "confirmed", resolver_agent_id="uuid-agent-X")

        assert posted["event_type"] == "watcher_resolution"
        assert posted["extra"]["action"] == "confirmed"
        assert posted["extra"]["resolved_by"] == "uuid-agent-X"
        assert posted["extra"]["pattern"] == "P004"
        assert posted["agent_id"] == "uuid-watcher"

    def test_dismiss_posts_governance_event(self, watcher_module, monkeypatch):
        """--dismiss posts a watcher_resolution event with action=dismissed."""
        self._write_findings(watcher_module, [
            {"fingerprint": "8266dfb800000000", "status": "surfaced", "severity": "high",
             "pattern": "P004", "file": "/tmp/y.py", "line": 114,
             "hint": "asyncpg deadlock", "violation_class": "REC",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-watcher",
            "client_session_id": "s1",
            "continuity_token": "t1",
        })

        posted = {}
        monkeypatch.setattr(watcher_module, "post_finding", lambda **kw: posted.update(kw) or True)

        watcher_module.update_finding_status("8266dfb8", "dismissed", resolver_agent_id="uuid-agent-Y")

        assert posted["event_type"] == "watcher_resolution"
        assert posted["extra"]["action"] == "dismissed"
        assert posted["extra"]["resolved_by"] == "uuid-agent-Y"

    def test_resolve_without_agent_id(self, watcher_module, monkeypatch):
        """--resolve without --agent-id sets resolved_by to None."""
        self._write_findings(watcher_module, [
            {"fingerprint": "abcd123400000000", "status": "open", "severity": "medium",
             "pattern": "P002", "file": "/tmp/z.py", "line": 50,
             "hint": "unbounded growth", "violation_class": "ENT",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-watcher",
            "client_session_id": "s1",
            "continuity_token": "t1",
        })

        posted = {}
        monkeypatch.setattr(watcher_module, "post_finding", lambda **kw: posted.update(kw) or True)

        watcher_module.update_finding_status("abcd1234", "confirmed")

        assert posted["extra"]["resolved_by"] is None

    def test_resolve_skips_event_when_no_identity(self, watcher_module, monkeypatch):
        """No identity → local status update works, governance event skipped."""
        self._write_findings(watcher_module, [
            {"fingerprint": "dead000000000000", "status": "open", "severity": "low",
             "pattern": "P001", "file": "/tmp/a.py", "line": 1,
             "hint": "test", "violation_class": "CON",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])
        monkeypatch.setattr(watcher_module, "_watcher_identity", None)

        posted = {}
        monkeypatch.setattr(watcher_module, "post_finding", lambda **kw: posted.update(kw) or True)

        result = watcher_module.update_finding_status("dead0000", "confirmed")

        assert result == 0  # local update succeeded
        assert not posted  # no governance event

    def test_governance_event_failure_doesnt_break_local_update(self, watcher_module, monkeypatch):
        """post_finding failure doesn't prevent the local status update."""
        self._write_findings(watcher_module, [
            {"fingerprint": "beef000000000000", "status": "open", "severity": "high",
             "pattern": "P004", "file": "/tmp/b.py", "line": 10,
             "hint": "test", "violation_class": "REC",
             "timestamp": datetime.now(timezone.utc).isoformat()},
        ])
        monkeypatch.setattr(watcher_module, "_watcher_identity", {
            "agent_uuid": "uuid-watcher",
            "client_session_id": "s1",
            "continuity_token": "t1",
        })

        def exploding_post(**kw):
            raise RuntimeError("governance exploded")

        monkeypatch.setattr(watcher_module, "post_finding", exploding_post)

        result = watcher_module.update_finding_status("beef0000", "confirmed")
        assert result == 0  # local update still worked

        # Verify the local status was actually updated
        findings = watcher_module._iter_findings_raw()
        assert findings[0]["status"] == "confirmed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestResolutionAuditTrail -v`
Expected: FAIL — `update_finding_status` doesn't accept `resolver_agent_id`, doesn't post events.

- [ ] **Step 3: Modify update_finding_status to post resolution events**

In `agents/watcher/agent.py`, modify the `update_finding_status` function signature (line 738) to accept `resolver_agent_id`:

Change:
```python
def update_finding_status(fingerprint_prefix: str, new_status: str) -> int:
```
To:
```python
def update_finding_status(fingerprint_prefix: str, new_status: str, resolver_agent_id: str | None = None) -> int:
```

Then, after the successful local update (after `_write_findings_atomic(updated)` at line 778 and the log/print at lines 779-783), add the governance event posting:

```python
    # --- Post resolution event to governance ---
    if new_status in ("confirmed", "dismissed"):
        _post_resolution_event(matches[0], new_status, resolver_agent_id)
```

Add the helper function near the identity section:

```python
def _post_resolution_event(finding: dict, action: str, resolver_agent_id: str | None) -> None:
    """Post a watcher_resolution event to the governance event stream."""
    identity = get_watcher_identity()
    if identity is None:
        return

    try:
        post_finding(
            event_type="watcher_resolution",
            severity=finding.get("severity", "unknown"),
            message=f"[{action}] {finding.get('pattern', '?')} {finding.get('file', '?')}:{finding.get('line', '?')} — {finding.get('hint', '')}",
            agent_id=identity["agent_uuid"],
            agent_name="Watcher",
            fingerprint=finding.get("fingerprint", ""),
            extra={
                "action": action,
                "pattern": finding.get("pattern", ""),
                "file": finding.get("file", ""),
                "line": finding.get("line", 0),
                "violation_class": finding.get("violation_class", ""),
                "resolved_by": resolver_agent_id,
            },
        )
    except Exception as e:
        log(f"resolution event failed: {e}", "warning")
```

- [ ] **Step 4: Add --agent-id argument to argparse in main()**

In `main()`, after the `--dismiss` argument (line 1521), add:

```python
    parser.add_argument(
        "--agent-id",
        metavar="UUID",
        help="governance UUID of the agent resolving/dismissing (for audit trail)",
    )
```

Then modify the resolve/dismiss dispatch (lines 1554-1557) to pass it:

Change:
```python
    if args.resolve:
        return update_finding_status(args.resolve, "confirmed")
    if args.dismiss:
        return update_finding_status(args.dismiss, "dismissed")
```
To:
```python
    if args.resolve:
        return update_finding_status(args.resolve, "confirmed", resolver_agent_id=args.agent_id)
    if args.dismiss:
        return update_finding_status(args.dismiss, "dismissed", resolver_agent_id=args.agent_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestResolutionAuditTrail -v`
Expected: 5 passed.

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -v --tb=short`
Expected: All tests pass. Existing `update_finding_status` tests still pass because `resolver_agent_id` defaults to `None`.

- [ ] **Step 7: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "feat(watcher): post resolution audit events to governance

--resolve and --dismiss now post watcher_resolution events carrying
the pattern, disposition, and resolver agent UUID. Enables cross-agent
calibration queries over the governance event stream.

--agent-id flag lets the calling agent pass its governance UUID.
Omitting it (manual CLI use) records resolved_by as null."
```

---

### Task 5: Update surface hook hint text

**Files:**
- Modify: `agents/watcher/agent.py` (the `_format_findings_block` function)

- [ ] **Step 1: Find and update the hint text**

In `agents/watcher/agent.py`, locate the `_format_findings_block` function (line 840). Find the lines that generate the `Resolve:` and `Dismiss:` hints in the output block. Update them to include `--agent-id <your-uuid>`:

Find the strings like:
```python
f"Resolve: python3 agents/watcher/agent.py --resolve <fingerprint>"
f"Dismiss: python3 agents/watcher/agent.py --dismiss <fingerprint>"
```

Update to:
```python
f"Resolve: python3 agents/watcher/agent.py --resolve <fingerprint> --agent-id <your-uuid>"
f"Dismiss: python3 agents/watcher/agent.py --dismiss <fingerprint> --agent-id <your-uuid>"
```

- [ ] **Step 2: Verify the hint text appears in output**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -k "surface" -v --tb=short`
Expected: Existing surface tests still pass. If any test asserts on the exact hint text, update it.

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py agents/watcher/tests/test_agent.py
git commit -m "docs(watcher): update surface hint to include --agent-id"
```

---

### Task 6: Integration test — full lifecycle

**Files:**
- Test: `agents/watcher/tests/test_agent.py`

- [ ] **Step 1: Write integration test**

Add to `agents/watcher/tests/test_agent.py`:

```python
class TestWatcherLifecycleIntegration:
    """End-to-end: identity → scan → surface + check-in → resolve with audit."""

    def test_full_lifecycle(self, watcher_module, tmp_path, monkeypatch):
        """Identity → persist finding → surface (triggers check-in) → resolve (posts event)."""
        session_file = tmp_path / SESSION_FILE_NAME
        monkeypatch.setattr(watcher_module, "SESSION_FILE", session_file)

        # Track all governance interactions
        gov_calls = []

        class FakeClient:
            client_session_id = "sess-int"
            continuity_token = "tok-int"
            agent_uuid = "uuid-watcher-int"

            def onboard(self, name, **kwargs):
                gov_calls.append(("onboard", name))
                return type("R", (), {"success": True})()

            def identity(self, **kwargs):
                raise RuntimeError("no prior session")

            def checkin(self, **kwargs):
                gov_calls.append(("checkin", kwargs.get("response_text", "")))
                return type("R", (), {
                    "success": True, "verdict": "proceed",
                    "guidance": None, "coherence": 0.5, "metrics": {},
                })()

        monkeypatch.setattr(watcher_module, "_make_identity_client", lambda: FakeClient())

        # 1. Resolve identity (fresh onboard)
        watcher_module.resolve_identity(FakeClient())
        assert watcher_module.get_watcher_identity()["agent_uuid"] == "uuid-watcher-int"
        assert ("onboard", "Watcher") in gov_calls

        # 2. Simulate a finding being persisted
        watcher_module.FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        finding = {
            "fingerprint": "integ00000000000",
            "status": "open",
            "severity": "high",
            "pattern": "P004",
            "file": str(tmp_path / "test_code.py"),
            "line": 42,
            "hint": "asyncpg in handler",
            "violation_class": "REC",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with watcher_module.FINDINGS_FILE.open("w") as f:
            f.write(json.dumps(finding) + "\n")

        # 3. Surface pending (triggers check-in)
        watcher_module.surface_pending()
        checkin_calls = [c for c in gov_calls if c[0] == "checkin"]
        assert len(checkin_calls) == 1
        assert "1 unresolved" in checkin_calls[0][1]

        # 4. Resolve finding (posts audit event)
        posted_events = []
        monkeypatch.setattr(watcher_module, "post_finding", lambda **kw: posted_events.append(kw) or True)

        result = watcher_module.update_finding_status("integ000", "confirmed", resolver_agent_id="uuid-agent-resolver")
        assert result == 0
        assert len(posted_events) == 1
        assert posted_events[0]["event_type"] == "watcher_resolution"
        assert posted_events[0]["extra"]["resolved_by"] == "uuid-agent-resolver"

        # Verify local status also updated
        findings = watcher_module._iter_findings_raw()
        assert findings[0]["status"] == "confirmed"
```

- [ ] **Step 2: Run integration test**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py::TestWatcherLifecycleIntegration -v`
Expected: PASS (all implementation is in place from prior tasks).

- [ ] **Step 3: Run full test suite one final time**

Run: `cd /Users/cirwel/projects/unitares && python3 -m pytest agents/watcher/tests/test_agent.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/tests/test_agent.py
git commit -m "test(watcher): add full lifecycle integration test

Covers: identity resolution → finding persistence → surface with
check-in → resolve with audit trail event."
```

---

### Task 7: Update agent.py docstring and remove stale comments

**Files:**
- Modify: `agents/watcher/agent.py` (docstring, stale "No agent_id" comments)

- [ ] **Step 1: Update the module docstring**

Replace lines 31-34 (the stale design notes about no agent_id):

```python
Design notes:
    - Never blocks the editor. The PostToolUse hook forks this script and exits.
    - No agent_id passed to call_model → skips the governance DB path → no
      anyio deadlock (see anyio-deadlock.md).
```

With:

```python
Design notes:
    - Never blocks the editor. The PostToolUse hook forks this script and exits.
    - Persistent governance identity via SyncGovernanceClient (REST transport).
      Checks in after surface_pending; resolution events posted on --resolve/--dismiss.
```

- [ ] **Step 2: Remove the stale comment at call_model_via_governance**

At line 370, remove or update:
```python
        - No `agent_id` passed → skips the governance DB path → no anyio deadlock.
```

Replace with:
```python
        - Uses REST /v1/tools/call transport (no anyio deadlock).
```

- [ ] **Step 3: Commit**

```bash
cd /Users/cirwel/projects/unitares
git add agents/watcher/agent.py
git commit -m "docs(watcher): update docstring for governance check-in

Remove stale 'no agent_id' comments — Watcher now has a persistent
identity and checks in to governance."
```
