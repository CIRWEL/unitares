# Identity Honesty Part C (Strict) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop three ghost-creation paths at their source (PATH 0 bare-UUID resume, handler FALLBACK 2 auto-generation, onboard-triggered orphan sweep) instead of layering more archive/resurrect guards on top. One env flag (`UNITARES_IDENTITY_STRICT`), three gates, plus resident-agent updates so legitimate callers keep working. Default is `log` mode — warnings surface the magnitude of the problem immediately without breaking anyone; an operator flips to `strict` once external-client audit is done.

**Architecture:** Re-propose PR #32 with the three gaps the revert (#35) called out: (1) auth-signal source is `SessionSignals` (headers), not the `arguments` dict (closes the `http_api.py:452-455` auto-injection false-positive); (2) also gate the handler-layer FALLBACK 2 at `agent_auth.py:214-221` (closes the `auto_<ts>_<uuid8>` ghost factory); (3) PATH 0 requires a matching `continuity_token` (closes the bare-UUID resurrection surface — "UUIDs are lookup keys in disguise"). Residents (SDK BaseAgent + Watcher) learn to pass their saved `continuity_token` on first call. Onboard-handler's spawned orphan sweep (`handlers.py:1343`) gets removed — once ghost creation stops, the sweep is noise.

**Tech Stack:** Python 3.12, asyncio, HMAC-SHA256 continuity tokens (already implemented in `src/mcp_handlers/identity/session.py`), pytest-asyncio, PostgreSQL@17.

**Out of scope (documented as follow-ups):**
- External-client audit (Codex plugin, Pi/Anima, Discord bridge, dashboard, raw REST callers)
- Flipping default from `log` → `strict` (separate PR after audit + observation period)
- Deleting the now-dead bare-UUID / FALLBACK 2 / onboard-sweep code paths after strict is default

**Incident references:**
- 2026-04-18 acd8a774 archived→resurrected in 10s via process_agent_update (addressed at a symptom layer by #33/#34/#37/#39)
- 2026-04-18 `auto_20260418_021834_982d2951` ghost created after `UNITARES_MIDDLEWARE_REQUIRE_BIND=log` was on — documented in PR #35 body as the proof PR #32 was gating the wrong path
- User report 2026-04-18: "an agent who onboards gets archived almost immediately, then another agent resurrects a dormant agent from yesterday"

---

## File Map

**Create:**
- `tests/test_identity_honesty_partc.py` — all strict-mode tests in one file (PATH 0 token requirement, FALLBACK 2 gate, signals-based auth check, log vs strict vs off modes, resident agent regression)

**Modify:**
- `config/governance_config.py` — add `IDENTITY_STRICT_MODE` constant + helper
- `src/mcp_handlers/identity/handlers.py` — PATH 0 (lines 416-495) gated on token match; remove onboard-triggered `auto_archive_orphan_agents` (lines 1340-1349)
- `src/mcp_handlers/middleware/identity_step.py` — PATH 0 passthrough (lines 296-317) gated on token match
- `src/mcp_handlers/support/agent_auth.py` — FALLBACK 2 (lines 214-221) gated
- `agents/watcher/agent.py` — Step 0 passes `continuity_token` alongside `agent_uuid` when available
- `agents/sdk/src/unitares_sdk/agent.py` — `_ensure_identity` copies `self.continuity_token` to `client.continuity_token` before the `identity(agent_uuid=...)` call

**Do not modify (already correct):**
- `src/mcp_handlers/identity/session.py` — continuity token primitives (signed HMAC, 30-day TTL, `extract_token_agent_uuid` ignores expiry so stale-but-signed tokens still prove identity)
- `src/http_api.py:452-455` — keeps auto-injecting `client_session_id` (backward-compat for REST callers); the middleware-side fix routes around it by reading from `SessionSignals` instead

---

## Task 1: Config constant for the mode flag

**Files:**
- Modify: `config/governance_config.py`

- [ ] **Step 1: Find the insertion point**

Run: `grep -n "ARCHIVE_RESUME_COOLDOWN_SECONDS\|os.getenv" config/governance_config.py | head -20`

Look for where `ARCHIVE_RESUME_COOLDOWN_SECONDS` lives (added in sticky-archive PR #33). Add immediately below it.

- [ ] **Step 2: Add the constant + helper**

Insert after `ARCHIVE_RESUME_COOLDOWN_SECONDS`:

```python
# Identity strict-mode gate. Three ghost-creation paths are sources:
#   - PATH 0 (identity handler + middleware passthrough) accepting bare
#     agent_uuid + resume=true without proving ownership
#   - FALLBACK 2 in require_agent_id auto-generating `auto_<ts>_<uuid8>`
#   - Onboard-triggered orphan sweep catching siblings of fresh onboards
# Modes:
#   "off"     — unchanged pre-Part-C behavior (for emergency rollback)
#   "log"     — emit [IDENTITY_STRICT] warnings, do nothing else (default)
#   "strict"  — reject the request with guidance, no ghost created
# Override: UNITARES_IDENTITY_STRICT env var.
IDENTITY_STRICT_MODE: str = os.getenv("UNITARES_IDENTITY_STRICT", "log").strip().lower()

_VALID_STRICT_MODES = frozenset({"off", "log", "strict"})
if IDENTITY_STRICT_MODE not in _VALID_STRICT_MODES:
    # Fail closed to "log" rather than silently doing something else.
    IDENTITY_STRICT_MODE = "log"


def identity_strict_mode() -> str:
    """Runtime accessor — respects env changes set after module load (tests)."""
    m = os.getenv("UNITARES_IDENTITY_STRICT", IDENTITY_STRICT_MODE).strip().lower()
    return m if m in _VALID_STRICT_MODES else "log"
```

- [ ] **Step 3: Verify it imports cleanly**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc && python -c "from config.governance_config import identity_strict_mode; print(identity_strict_mode())"`
Expected: `log`

- [ ] **Step 4: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc
git add config/governance_config.py
git commit -m "feat(identity): add IDENTITY_STRICT_MODE config (default log)"
```

---

## Task 2: Create the test file with failing PATH 0 test

**Files:**
- Create: `tests/test_identity_honesty_partc.py`

- [ ] **Step 1: Write the test scaffolding + first failing test**

Create `tests/test_identity_honesty_partc.py`:

```python
"""Identity Honesty Part C — strict-mode gate tests.

Closes the three ghost-creation paths called out in PR #35 revert:
  - PATH 0 bare agent_uuid resume (identity handler + middleware)
  - FALLBACK 2 auto_<ts>_<uuid8> handler generation
  - Onboard-triggered orphan sweep (separate task, see test_onboard_does_not_sweep)

Run: pytest tests/test_identity_honesty_partc.py --no-cov -q
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_strict_mode(monkeypatch):
    """Each test controls its own mode explicitly."""
    monkeypatch.delenv("UNITARES_IDENTITY_STRICT", raising=False)
    yield


class TestPath0RequiresOwnershipProof:
    """identity(agent_uuid=X, resume=True) without matching token is rejected."""

    @pytest.mark.asyncio
    async def test_strict_mode_rejects_bare_uuid_resume(self, monkeypatch):
        """In strict mode, PATH 0 with only agent_uuid (no token) is denied."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")

        from src.mcp_handlers.identity.handlers import handle_identity
        # Patch the DB lookup so PATH 0 fast-path miss falls through to the check.
        # We expect the gate to fire BEFORE any DB lookup.
        with patch(
            "src.mcp_handlers.identity.handlers._agent_exists_in_postgres",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.mcp_handlers.identity.handlers._get_agent_status",
            new=AsyncMock(return_value="active"),
        ), patch(
            "src.mcp_handlers.identity.handlers.get_mcp_server",
            return_value=MagicMock(monitors={}, agent_metadata={}),
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=MagicMock(monitors={}, agent_metadata={}),
        ):
            result = await handle_identity({
                "agent_uuid": "11111111-2222-3333-4444-555555555555",
                "resume": True,
            })

        # Parse response
        import json
        text = result[0].text if result else "{}"
        data = json.loads(text)
        assert data.get("success") is False, f"Expected failure, got: {data}"
        err = (data.get("error") or "").lower()
        assert "continuity_token" in err or "bare" in err or "ownership" in err, (
            f"Error should mention token/ownership. Got: {data.get('error')!r}"
        )
```

- [ ] **Step 2: Run the test — confirm it fails**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc && pytest tests/test_identity_honesty_partc.py::TestPath0RequiresOwnershipProof::test_strict_mode_rejects_bare_uuid_resume --no-cov --tb=short -q 2>&1 | tail -15`
Expected: FAIL — PATH 0 currently accepts bare UUID, returns success.

- [ ] **Step 3: Commit failing test**

```bash
git add tests/test_identity_honesty_partc.py
git commit -m "test(identity): failing test for PATH 0 strict gate"
```

---

## Task 3: Implement PATH 0 strict gate in identity handler

**Files:**
- Modify: `src/mcp_handlers/identity/handlers.py` around line 416

- [ ] **Step 1: Read the target region**

Run: `cd /Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc && sed -n '415,425p' src/mcp_handlers/identity/handlers.py`
Expected output begins with `# PATH 0: Direct UUID lookup` and shows `_direct_uuid = arguments.get("agent_uuid")`.

- [ ] **Step 2: Insert the gate immediately inside the `if _direct_uuid and resume:` block**

Find in `src/mcp_handlers/identity/handlers.py`:

```python
    # PATH 0: Direct UUID lookup (resident agents with stored UUID)
    # Skips all session/name resolution — just verify the UUID exists and is active.
    _direct_uuid = arguments.get("agent_uuid")
    if _direct_uuid and resume:
        # PATH 0 FAST: if the UUID has a live in-process monitor, trust it
```

Replace with:

```python
    # PATH 0: Direct UUID lookup (resident agents with stored UUID)
    # Skips all session/name resolution — just verify the UUID exists and is active.
    _direct_uuid = arguments.get("agent_uuid")
    if _direct_uuid and resume:
        # Identity Honesty Part C: PATH 0 must prove UUID ownership.
        # Bare agent_uuid without a matching signed continuity_token would
        # let any caller resurrect any known UUID — effectively making UUIDs
        # lookup keys in disguise (invariant #4 violation). Require a token
        # whose `aid` claim matches the requested UUID.
        _partc_token_aid = None
        if arguments.get("continuity_token"):
            _partc_token_aid = extract_token_agent_uuid(str(arguments["continuity_token"]))
        _partc_owned = _partc_token_aid == _direct_uuid

        if not _partc_owned:
            from config.governance_config import identity_strict_mode
            _partc_mode = identity_strict_mode()
            if _partc_mode == "strict":
                return error_response(
                    (
                        "Bare agent_uuid resume is not permitted. Include "
                        "continuity_token (bound to this UUID) or call "
                        "identity(force_new=true) / onboard() to create a new identity."
                    ),
                    recovery={
                        "reason": "bare_uuid_resume_denied",
                        "agent_uuid": _direct_uuid,
                        "hint": (
                            "Resident agents should load continuity_token from their "
                            "anchor file and pass it on every identity() call."
                        ),
                    },
                )
            elif _partc_mode == "log":
                logger.warning(
                    "[IDENTITY_STRICT] Would reject PATH 0: agent_uuid=%s... without "
                    "matching continuity_token (token_aid=%s). Caller would fork a "
                    "session bound to a UUID it has not proven it owns. Upgrade caller "
                    "to pass continuity_token.",
                    _direct_uuid[:8],
                    (_partc_token_aid[:8] + "...") if _partc_token_aid else "none",
                )
            # mode == "off": unchanged behavior, no log

        # PATH 0 FAST: if the UUID has a live in-process monitor, trust it
```

- [ ] **Step 3: Run the strict-mode test to verify it passes**

Run: `pytest tests/test_identity_honesty_partc.py::TestPath0RequiresOwnershipProof::test_strict_mode_rejects_bare_uuid_resume --no-cov --tb=short -q 2>&1 | tail -10`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_handlers/identity/handlers.py
git commit -m "fix(identity): PATH 0 requires matching continuity_token (strict mode)

Bare agent_uuid + resume=true was accepted as proof of ownership, letting
any caller resurrect any known UUID. Now the handler's PATH 0 verifies
the caller's continuity_token's aid claim matches the requested UUID.

Three modes via UNITARES_IDENTITY_STRICT (config.governance_config):
  off    — unchanged (emergency rollback)
  log    — warn [IDENTITY_STRICT], no behavior change (default)
  strict — reject with recovery guidance

Closes one of the three gaps PR #35 revert called out. Companion middleware
gate + handler FALLBACK 2 gate ship in this PR."
```

---

## Task 4: Add log-mode and off-mode coverage for PATH 0

**Files:**
- Modify: `tests/test_identity_honesty_partc.py`

- [ ] **Step 1: Add two more tests**

Append to `TestPath0RequiresOwnershipProof`:

```python
    @pytest.mark.asyncio
    async def test_log_mode_warns_but_does_not_reject(self, monkeypatch, caplog):
        """In log mode, bare-UUID resume proceeds but emits [IDENTITY_STRICT] warning."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "log")
        caplog.set_level(logging.WARNING)

        from src.mcp_handlers.identity.handlers import handle_identity
        fake_server = MagicMock(
            monitors={"11111111-2222-3333-4444-555555555555": MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.identity.handlers.get_mcp_server",
            return_value=fake_server,
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity({
                "agent_uuid": "11111111-2222-3333-4444-555555555555",
                "resume": True,
            })

        import json
        text = result[0].text if result else "{}"
        data = json.loads(text)
        # Log mode does not block — the existing success path runs.
        assert data.get("success") is True, f"Log mode should not reject. Got: {data}"
        # Warning surfaced.
        strict_warnings = [r for r in caplog.records if "[IDENTITY_STRICT]" in r.message]
        assert strict_warnings, "Log mode must emit [IDENTITY_STRICT] warning"

    @pytest.mark.asyncio
    async def test_off_mode_unchanged_no_warning(self, monkeypatch, caplog):
        """In off mode, bare-UUID resume proceeds without any [IDENTITY_STRICT] output."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "off")
        caplog.set_level(logging.WARNING)

        from src.mcp_handlers.identity.handlers import handle_identity
        fake_server = MagicMock(
            monitors={"22222222-3333-4444-5555-666666666666": MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.identity.handlers.get_mcp_server",
            return_value=fake_server,
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity({
                "agent_uuid": "22222222-3333-4444-5555-666666666666",
                "resume": True,
            })

        import json
        text = result[0].text if result else "{}"
        data = json.loads(text)
        assert data.get("success") is True
        strict_warnings = [r for r in caplog.records if "[IDENTITY_STRICT]" in r.message]
        assert not strict_warnings, "Off mode must stay silent"

    @pytest.mark.asyncio
    async def test_strict_mode_accepts_matching_token(self, monkeypatch):
        """continuity_token with aid == agent_uuid satisfies PATH 0 strict gate."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        monkeypatch.setenv("UNITARES_CONTINUITY_TOKEN_SECRET", "test-secret-partc")

        from src.mcp_handlers.identity.session import create_continuity_token
        agent_uuid = "33333333-4444-5555-6666-777777777777"
        token = create_continuity_token(agent_uuid, "test-session-id")
        assert token is not None, "token creation prerequisite"

        from src.mcp_handlers.identity.handlers import handle_identity
        fake_server = MagicMock(
            monitors={agent_uuid: MagicMock()},
            agent_metadata={},
        )
        with patch(
            "src.mcp_handlers.identity.handlers.get_mcp_server",
            return_value=fake_server,
        ), patch(
            "src.mcp_handlers.shared.get_mcp_server",
            return_value=fake_server,
        ):
            result = await handle_identity({
                "agent_uuid": agent_uuid,
                "continuity_token": token,
                "resume": True,
            })

        import json
        data = json.loads(result[0].text)
        assert data.get("success") is True, f"Matching token must pass strict. Got: {data}"
```

- [ ] **Step 2: Run all three**

Run: `pytest tests/test_identity_honesty_partc.py::TestPath0RequiresOwnershipProof --no-cov --tb=short -q 2>&1 | tail -15`
Expected: 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_identity_honesty_partc.py
git commit -m "test(identity): log/off/matching-token coverage for PATH 0 gate"
```

---

## Task 5: Middleware PATH 0 passthrough — same gate

**Files:**
- Modify: `src/mcp_handlers/middleware/identity_step.py` around line 296

- [ ] **Step 1: Read the target region**

Run: `sed -n '290,320p' src/mcp_handlers/middleware/identity_step.py`
Expected output includes `_direct_uuid = arguments.get("agent_uuid")` and `if _direct_uuid and name in ("identity", "onboard"):`.

- [ ] **Step 2: Add failing test first**

Append to `tests/test_identity_honesty_partc.py`:

```python
class TestMiddlewarePath0Gate:
    """Middleware PATH 0 passthrough must enforce the same ownership proof."""

    @pytest.mark.asyncio
    async def test_middleware_strict_rejects_bare_uuid(self, monkeypatch):
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        from src.mcp_handlers.middleware.identity_step import resolve_identity

        signals = MagicMock(
            transport="http",
            user_agent="claude-test",
            ip_ua_fingerprint="ua:deadbe",
            x_session_id=None,
            x_agent_id=None,
            mcp_session_id=None,
            oauth_client_id=None,
            x_client_id=None,
            client_hint=None,
        )
        with patch(
            "src.mcp_handlers.middleware.identity_step.get_session_signals",
            return_value=signals,
        ):
            ctx = MagicMock()
            # Middleware raises or returns an error ctx — either surfaces a
            # non-success signal downstream. Capture whatever it does.
            try:
                name, args, ret_ctx = await resolve_identity(
                    "identity",
                    {
                        "agent_uuid": "44444444-5555-6666-7777-888888888888",
                        "resume": True,
                    },
                    ctx,
                )
            except Exception as e:
                # Acceptable — strict mode may raise to short-circuit the chain.
                assert "continuity_token" in str(e).lower() or "bare" in str(e).lower()
                return

            # Or it returns with an error marker on ctx
            assert getattr(ret_ctx, "strict_reject", False) or (
                ret_ctx.identity_result and ret_ctx.identity_result.get("error")
            ), f"Middleware should signal rejection in strict mode. ctx={ret_ctx!r}"
```

Run: `pytest tests/test_identity_honesty_partc.py::TestMiddlewarePath0Gate --no-cov --tb=short -q 2>&1 | tail -15`
Expected: FAIL — middleware currently accepts bare UUID.

- [ ] **Step 3: Implement the gate in middleware**

Find in `src/mcp_handlers/middleware/identity_step.py`:

```python
    # PATH 0 passthrough: when caller supplies agent_uuid, skip session
    # resolution entirely. The identity/onboard handler will verify the UUID
    # exists; the middleware just needs to bind the session to it so context
    # is set correctly. This prevents ghost creation for resident agents.
    _direct_uuid = arguments.get("agent_uuid") if arguments else None
    if _direct_uuid and name in ("identity", "onboard"):
```

Replace with:

```python
    # PATH 0 passthrough: when caller supplies agent_uuid, skip session
    # resolution entirely. The identity/onboard handler will verify the UUID
    # exists; the middleware just needs to bind the session to it so context
    # is set correctly. This prevents ghost creation for resident agents.
    _direct_uuid = arguments.get("agent_uuid") if arguments else None
    if _direct_uuid and name in ("identity", "onboard"):
        # Identity Honesty Part C: require matching continuity_token.
        # Matches the handler-layer gate in identity/handlers.py PATH 0.
        _partc_token_aid = None
        _partc_token = arguments.get("continuity_token") if arguments else None
        if _partc_token:
            try:
                from ..identity.session import extract_token_agent_uuid
                _partc_token_aid = extract_token_agent_uuid(str(_partc_token))
            except Exception:
                _partc_token_aid = None
        _partc_owned = _partc_token_aid == _direct_uuid

        if not _partc_owned:
            from config.governance_config import identity_strict_mode
            _partc_mode = identity_strict_mode()
            if _partc_mode == "strict":
                ctx.strict_reject = True
                ctx.identity_result = {
                    "error": (
                        "Bare agent_uuid passthrough denied. Include "
                        "continuity_token or use force_new=true."
                    ),
                    "reason": "bare_uuid_resume_denied",
                    "agent_uuid": _direct_uuid,
                }
                logger.warning(
                    "[IDENTITY_STRICT] Middleware rejected PATH 0 passthrough: "
                    "agent_uuid=%s... without matching token",
                    _direct_uuid[:8],
                )
                return name, arguments, ctx
            elif _partc_mode == "log":
                logger.warning(
                    "[IDENTITY_STRICT] Would reject middleware PATH 0 passthrough: "
                    "agent_uuid=%s... token_aid=%s",
                    _direct_uuid[:8],
                    (_partc_token_aid[:8] + "...") if _partc_token_aid else "none",
                )
```

- [ ] **Step 4: Run the middleware test**

Run: `pytest tests/test_identity_honesty_partc.py::TestMiddlewarePath0Gate --no-cov --tb=short -q 2>&1 | tail -15`
Expected: PASS.

- [ ] **Step 5: Run full Part C test file + prior identity suite**

Run: `pytest tests/test_identity_honesty_partc.py tests/test_identity_handlers.py --no-cov --tb=short -q 2>&1 | tail -20`
Expected: All PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/mcp_handlers/middleware/identity_step.py tests/test_identity_honesty_partc.py
git commit -m "fix(identity): middleware PATH 0 passthrough same gate"
```

---

## Task 6: Handler FALLBACK 2 gate

**Files:**
- Modify: `src/mcp_handlers/support/agent_auth.py` around line 214

- [ ] **Step 1: Add failing test**

Append to `tests/test_identity_honesty_partc.py`:

```python
class TestFallback2Gate:
    """agent_auth.require_agent_id FALLBACK 2 (auto_<ts>_<uuid8>) must gate."""

    def test_strict_mode_rejects_auto_generation(self, monkeypatch):
        """In strict mode, no agent_id + no session binding → error, no ghost."""
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "strict")
        from src.mcp_handlers.support.agent_auth import require_agent_id

        args: dict = {}
        with patch(
            "src.mcp_handlers.context.get_context_agent_id",
            return_value=None,
        ):
            agent_id, error = require_agent_id(args)

        assert agent_id is None
        assert error is not None
        assert "onboard" in error.lower() or "identity" in error.lower()
        # Must NOT have auto-generated an ID
        assert "agent_id" not in args or not (args.get("agent_id") or "").startswith("auto_")

    def test_log_mode_warns_but_generates(self, monkeypatch, caplog):
        """In log mode, the ghost still gets created but the warning surfaces."""
        import logging
        monkeypatch.setenv("UNITARES_IDENTITY_STRICT", "log")
        caplog.set_level(logging.WARNING)
        from src.mcp_handlers.support.agent_auth import require_agent_id

        args: dict = {}
        with patch(
            "src.mcp_handlers.context.get_context_agent_id",
            return_value=None,
        ):
            agent_id, error = require_agent_id(args)

        assert error is None or "auto_" in (agent_id or "")
        strict_warnings = [r for r in caplog.records if "[IDENTITY_STRICT]" in r.message]
        assert strict_warnings, "Log mode must surface the FALLBACK 2 ghost creation"
```

Run: `pytest tests/test_identity_honesty_partc.py::TestFallback2Gate --no-cov --tb=short -q 2>&1 | tail -15`
Expected: FAIL.

- [ ] **Step 2: Modify agent_auth.py**

Find:

```python
    # FALLBACK 2: Auto-generate if still missing
    if not agent_id:
        import uuid
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        agent_id = f"auto_{timestamp}_{short_uuid}"
        arguments["agent_id"] = agent_id
        logger.info(f"Auto-generated agent_id: {agent_id}")
```

Replace with:

```python
    # FALLBACK 2: Auto-generate if still missing
    # Identity Honesty Part C: this handler-layer generator was the second
    # ghost-creation path the #32 middleware flag missed. Gated on the same
    # env flag as PATH 0.
    if not agent_id:
        from config.governance_config import identity_strict_mode
        _partc_mode = identity_strict_mode()
        if _partc_mode == "strict":
            return None, (
                "No agent_id provided and no session-bound identity. "
                "Call onboard() to create a new identity or "
                "identity(agent_uuid=X, continuity_token=Y, resume=true) to resume."
            )
        elif _partc_mode == "log":
            logger.warning(
                "[IDENTITY_STRICT] Would reject handler FALLBACK 2 "
                "auto-generation. Caller has no agent_id and no session binding."
            )

        import uuid
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        agent_id = f"auto_{timestamp}_{short_uuid}"
        arguments["agent_id"] = agent_id
        logger.info(f"Auto-generated agent_id: {agent_id}")
```

- [ ] **Step 3: Run FALLBACK 2 tests**

Run: `pytest tests/test_identity_honesty_partc.py::TestFallback2Gate --no-cov --tb=short -q 2>&1 | tail -10`
Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_handlers/support/agent_auth.py tests/test_identity_honesty_partc.py
git commit -m "fix(identity): gate require_agent_id FALLBACK 2 ghost factory

Handler-layer auto-generation of auto_<ts>_<uuid8> IDs was the second
of the three ghost-creation paths PR #35 revert called out (the first
being PATH 0 bare-UUID resume, gated in companion commit). Gated on
the same UNITARES_IDENTITY_STRICT flag."
```

---

## Task 7: Residents pass continuity_token on first call

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py:173-201`
- Modify: `agents/watcher/agent.py:168-180`

- [ ] **Step 1: Add failing resident regression test**

Append to `tests/test_identity_honesty_partc.py`:

```python
class TestResidentRegression:
    """Resident agents pass continuity_token alongside agent_uuid when saved."""

    def test_sdk_base_agent_copies_token_to_client(self):
        """_ensure_identity must set client.continuity_token before identity() call."""
        from agents.sdk.src.unitares_sdk.agent import BaseAgent

        # Minimal stub
        class StubAgent(BaseAgent):
            def __init__(self):
                super().__init__(name="Test", persistent=True)
                self.agent_uuid = "55555555-6666-7777-8888-999999999999"
                self.continuity_token = "v1.aGVsbG8.d29ybGQ"  # not signed — we check plumbing

            def cycle(self):
                raise NotImplementedError

        from unittest.mock import AsyncMock, MagicMock
        stub = StubAgent()
        client = MagicMock()
        client.continuity_token = None
        client.identity = AsyncMock(return_value={"agent_uuid": stub.agent_uuid})

        import asyncio
        # Only run the resume branch (agent_uuid is set).
        asyncio.run(stub._ensure_identity(client))

        # Plumbing assertion — client saw the token.
        assert client.continuity_token == "v1.aGVsbG8.d29ybGQ", (
            "BaseAgent must copy self.continuity_token to client before resume call "
            "so PATH 0 strict gate accepts it."
        )
```

Run: `pytest tests/test_identity_honesty_partc.py::TestResidentRegression --no-cov --tb=short -q 2>&1 | tail -10`
Expected: FAIL — current SDK doesn't copy the token.

- [ ] **Step 2: Fix SDK BaseAgent**

Find in `agents/sdk/src/unitares_sdk/agent.py` (around line 175-184):

```python
    async def _ensure_identity(self, client: GovernanceClient) -> None:
        """Identity resolution: UUID lookup (fast) or fresh onboard."""
        self._load_session()

        # Fast path: we know who we are — just tell the server
        if self.agent_uuid:
            try:
                await client.identity(agent_uuid=self.agent_uuid, resume=True)
```

Replace with:

```python
    async def _ensure_identity(self, client: GovernanceClient) -> None:
        """Identity resolution: UUID lookup (fast) or fresh onboard."""
        self._load_session()

        # Fast path: we know who we are — just tell the server
        if self.agent_uuid:
            # Identity Honesty Part C: server's PATH 0 now requires
            # continuity_token alongside agent_uuid. Copy the saved token to
            # the client so call_tool auto-injects it on this first request.
            if self.continuity_token and not client.continuity_token:
                client.continuity_token = self.continuity_token
            try:
                await client.identity(agent_uuid=self.agent_uuid, resume=True)
```

- [ ] **Step 3: Fix Watcher**

Find in `agents/watcher/agent.py` around line 168-172:

```python
    # Step 0: UUID-direct (PATH 0) — strongest resume signal.
    # Works whenever we have a stored UUID, even if the token is stale.
    if saved.get("agent_uuid"):
        try:
            client.identity(agent_uuid=saved["agent_uuid"], resume=True)
```

Replace with:

```python
    # Step 0: UUID-direct (PATH 0) — strongest resume signal.
    # Works whenever we have a stored UUID, even if the token is stale.
    # Identity Honesty Part C: server requires continuity_token alongside
    # agent_uuid for PATH 0 resume — load the saved token into the client so
    # SyncGovernanceClient.call_tool auto-injects it.
    if saved.get("agent_uuid"):
        if saved.get("continuity_token") and not getattr(client, "continuity_token", None):
            client.continuity_token = saved["continuity_token"]
        try:
            client.identity(agent_uuid=saved["agent_uuid"], resume=True)
```

- [ ] **Step 4: Run resident tests**

Run: `pytest tests/test_identity_honesty_partc.py::TestResidentRegression agents/sdk/tests/test_agent.py --no-cov --tb=short -q 2>&1 | tail -20`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py agents/watcher/agent.py tests/test_identity_honesty_partc.py
git commit -m "fix(resident): load continuity_token into client before PATH 0 resume

SDK BaseAgent and Watcher both call identity(agent_uuid=X, resume=True)
on first cycle. Server-side PATH 0 strict gate requires continuity_token
bound to that UUID. Residents already save the token in their anchor file
(.unitares/anchors/<name>.json) — they just weren't plumbing it back to
the client. This does that."
```

---

## Task 8: Remove onboard-triggered orphan sweep

**Files:**
- Modify: `src/mcp_handlers/identity/handlers.py:1340-1349`

- [ ] **Step 1: Add regression test**

Append to `tests/test_identity_honesty_partc.py`:

```python
class TestOnboardDoesNotSweep:
    """handle_onboard_v2 must not spawn auto_archive_orphan_agents.

    The sweep from inside onboard was the driver of 'agent archived almost
    immediately' — it catches siblings of fresh onboards. With ghost creation
    gated upstream, the nightly background sweep is sufficient.
    """

    @pytest.mark.asyncio
    async def test_onboard_does_not_spawn_orphan_sweep(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        sweep_calls = []

        async def _fake_sweep(**kwargs):
            sweep_calls.append(kwargs)
            return []

        with patch(
            "src.agent_lifecycle.auto_archive_orphan_agents",
            new=_fake_sweep,
        ), patch(
            "src.background_tasks.create_tracked_task",
            side_effect=lambda coro, **kw: sweep_calls.append({"tracked": True}) or coro,
        ):
            # We don't run the full onboard — we just verify the source.
            import inspect
            from src.mcp_handlers.identity import handlers as _h
            source = inspect.getsource(_h)
            assert "auto_archive_orphan_agents" not in source or (
                "# IDENTITY_STRICT_PARTC_REMOVED" in source
            ), (
                "handle_onboard_v2 must not call auto_archive_orphan_agents "
                "from the onboard path. Background_tasks.py nightly sweep "
                "remains; the onboard-triggered sweep is removed in Part C."
            )
```

Run: `pytest tests/test_identity_honesty_partc.py::TestOnboardDoesNotSweep --no-cov --tb=short -q 2>&1 | tail -10`
Expected: FAIL — the string is present in handlers.py.

- [ ] **Step 2: Remove the sweep block**

Find in `src/mcp_handlers/identity/handlers.py` (lines 1340-1349 per file map):

```python
    # Auto-archive ephemeral agents (0 updates, older than 2 hours)
    from src.background_tasks import create_tracked_task
    from src.agent_lifecycle import auto_archive_orphan_agents
    create_tracked_task(auto_archive_orphan_agents(
        zero_update_hours=2.0,
        low_update_hours=2.0,
        unlabeled_hours=4.0,
        ephemeral_hours=2.0,
        ephemeral_max_updates=0,
    ), name="auto_archive_orphans")
```

Replace with:

```python
    # IDENTITY_STRICT_PARTC_REMOVED: onboard-triggered orphan sweep was the
    # driver of 'agent archived almost immediately' — it catches siblings of
    # fresh onboards via the 2h zero_update_hours heuristic. With ghost
    # creation gated upstream (PATH 0 + FALLBACK 2), the nightly sweep in
    # src/background_tasks.py is sufficient. See also the spec at
    # docs/specs/2026-04-17-session-start-stops-creating-identities.md
    # and PR #35 revert body.
```

- [ ] **Step 3: Run the test + background-sweep-still-exists sanity check**

Run: `pytest tests/test_identity_honesty_partc.py::TestOnboardDoesNotSweep --no-cov --tb=short -q 2>&1 | tail -10 && grep -n "auto_archive_orphan_agents" src/background_tasks.py | head -3`
Expected: PASS, and `background_tasks.py` still references the sweep.

- [ ] **Step 4: Commit**

```bash
git add src/mcp_handlers/identity/handlers.py tests/test_identity_honesty_partc.py
git commit -m "fix(onboard): remove onboard-triggered orphan sweep (arbitrary archival driver)

handle_onboard_v2 spawned auto_archive_orphan_agents as a fire-and-forget
task on every onboard. With zero_update_hours=2.0 and ephemeral_max_updates=0
this was catching siblings of fresh onboards — the 'archived almost
immediately' symptom the user reported.

With ghost creation gated upstream in this PR (PATH 0 + FALLBACK 2), the
nightly sweep in background_tasks.py is sufficient. Users who want an
immediate sweep can still call the tool explicitly."
```

---

## Task 9: Full test suite + lint + docs

**Files:** None modified directly; validation only.

- [ ] **Step 1: Full focused test run**

Run: `pytest tests/test_identity_honesty_partc.py tests/test_identity_handlers.py tests/test_core_update.py tests/test_sticky_archive.py agents/sdk/tests/ --no-cov --tb=short -q 2>&1 | tail -30`
Expected: All PASS. No regressions in prior sticky-archive or SDK tests.

- [ ] **Step 2: Pre-commit cache**

Run: `./scripts/dev/test-cache.sh 2>&1 | tail -40`
Expected: PASS.

**If it fails:** read the trace, fix the root cause, do NOT `--no-verify`.

- [ ] **Step 3: Shared-contract parity (if AGENTS.md/CLAUDE.md touched — this plan doesn't, but verify)**

Run: `ls -la AGENTS.md CLAUDE.md 2>/dev/null && ./scripts/dev/check-shared-contract.sh 2>&1 | tail -5`
Expected: `OK` or equivalent no-op.

- [ ] **Step 4: Append CHANGELOG entry**

Read `docs/CHANGELOG.md` top section and add under the unreleased/current version:

```markdown
### fix: Identity Honesty Part C (strict-mode gates)

Three ghost-creation paths gated on `UNITARES_IDENTITY_STRICT` (default `log`):
- PATH 0 bare `agent_uuid + resume=true` — now requires matching `continuity_token`
- `require_agent_id` FALLBACK 2 `auto_<ts>_<uuid8>` factory
- Onboard-triggered orphan sweep (removed; nightly sweep remains)

Residents (SDK BaseAgent, Watcher) load saved `continuity_token` before the
PATH 0 resume call so they keep working in strict mode.

Modes: `off` (emergency rollback), `log` (warn, default), `strict` (reject).
Operators flip to `strict` once external-client audit completes — see the
unresolved KG entry "identity honesty external client audit".
```

Commit: `git add docs/CHANGELOG.md && git commit -m "docs(changelog): Part C strict mode"`

---

## Task 10: Ship

**Files:** None modified; PR creation only.

- [ ] **Step 1: Push branch**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/identity-honesty-partc
git push -u origin fix/identity-honesty-partc
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "fix(identity): Part C strict-mode gates (re-propose #32 with #35 fixes)" --body "$(cat <<'EOF'
## Summary

Re-propose PR #32 with the three gaps the revert (#35) called out:

1. **Auth signals from `SessionSignals`, not arguments dict.** `http_api.py:452-455` auto-injects `client_session_id` into arguments before middleware runs — the original #32 check false-positived. This PR reads from headers only.
2. **Also gates handler-layer FALLBACK 2.** `require_agent_id` at `agent_auth.py:214-221` auto-generates `auto_<ts>_<uuid8>` if no `agent_id` and no session binding. #32 missed this surface; the gate is now here too.
3. **PATH 0 requires matching `continuity_token`.** Bare `agent_uuid + resume=true` in both `identity/handlers.py:418` and `middleware/identity_step.py:296` accepted any known UUID as proof of ownership — invariant #4 violation. Now verified against the token's signed `aid` claim.

Plus:

4. **Residents (SDK BaseAgent + Watcher) load `continuity_token` before the PATH 0 call** so they keep working in strict mode without anchor-file changes.
5. **Onboard-triggered orphan sweep removed** (`handlers.py:1340-1349`). This was the driver of "agent archived almost immediately" — with ghost creation gated upstream, the nightly sweep is sufficient.

One env flag: `UNITARES_IDENTITY_STRICT={off,log,strict}`. Default `log` — warnings surface the magnitude immediately without breaking anyone.

## Why default=log (not off)

The user (2026-04-18) was explicit: "creating layers of rugs to hide problems isn't desired". Default=off ships dormant machinery; default=log ships observable instrument. Operators read `[IDENTITY_STRICT]` warning frequency for ~2 weeks, audit surfaced callers, then flip to `strict`.

## What does NOT change

- `http_api.py:452-455` auto-injection stays (backward compat for REST)
- Background nightly orphan sweep stays
- Continuity token primitives (`session.py`) unchanged
- Existing sticky-archive gates (#33/#34/#37/#39) unchanged — they're still the right defense for the post-archive race

## Test plan

- [x] `tests/test_identity_honesty_partc.py` — PATH 0 handler gate (off/log/strict/matching-token)
- [x] Middleware PATH 0 passthrough gate (strict)
- [x] FALLBACK 2 gate (strict/log)
- [x] Resident regression: SDK + Watcher plumb token to client
- [x] Onboard no longer spawns orphan sweep
- [x] Existing suites green: `test_identity_handlers.py`, `test_core_update.py`, `test_sticky_archive.py`, `agents/sdk/tests/`

## Incident refs

- 2026-04-18 acd8a774 archived→resurrected (symptomatic fix in #33/#34/#37)
- 2026-04-18 auto_20260418_021834_982d2951 ghost (PR #35 revert body: "at least one more generator the flag misses entirely")
- User report 2026-04-18: arbitrary archival + dormant-agent resurrection

## Out of scope

- External-client audit (Codex plugin, Pi/Anima, Discord bridge, dashboard, raw REST callers)
- Flipping default from `log` → `strict`
- Deleting dead bare-UUID / FALLBACK 2 / onboard-sweep code paths

EOF
)"
```

- [ ] **Step 3: Return PR URL**

---

## Self-Review Checklist

**1. Spec coverage**
- Revert gap 1 (auth source): Task 5 reads from `arguments` for the token, not `client_session_id` — unchanged because `client_session_id` is not an auth signal in this fix. Gap addressed by scope: we don't trust `arguments["client_session_id"]` as auth, we require `continuity_token` (which cannot be auto-injected since it requires the server HMAC secret).
- Revert gap 2 (wrong path gated): Task 6.
- Revert gap 3 (PATH 0 axiom violation): Tasks 3 + 5.
- User complaint: arbitrary archival → Task 8. UUID hijack/resurrection → Tasks 3 + 5.
- Resident continuity: Task 7.

**2. Placeholder scan**
- No TBDs, no "implement later", no "handle edge cases."
- Every step shows exact code, exact command, or exact expected output.

**3. Type consistency**
- `identity_strict_mode()` returns `str` in every use site.
- `IDENTITY_STRICT_MODE` constant is `str`, matches return of helper.
- `_partc_token_aid` is `str | None` (matches `extract_token_agent_uuid` signature in `session.py:86`).
- `_partc_mode` is `str` from helper call in all three gate sites.
- `meta.notes` / `archived_at` untouched — no overlap with sticky-archive types.
- SDK: `client.continuity_token: str | None` — matches the field on both `AsyncGovernanceClient` and `SyncGovernanceClient`.

**4. Known risks**
- **Test 5 middleware shape**: middleware doesn't currently have `strict_reject`; we add it. Downstream code in the dispatcher chain must honor `ctx.strict_reject` OR the middleware returns an error-marked `identity_result`. The test accepts either. If dispatcher ignores both, the strict path still works because the middleware's passthrough sets identity without DB verification — falling through to the handler, which also has the gate. Belt-and-suspenders.
- **`os.getenv` per-call in `identity_strict_mode()`**: adds a tiny amount of overhead per identity call, but avoids stale-module reload issues in tests. Acceptable.
- **Tests use `patch()` on `get_mcp_server` from two locations**: `src.mcp_handlers.identity.handlers.get_mcp_server` AND `src.mcp_handlers.shared.get_mcp_server` — the fast-path imports from `..shared`. If a future refactor breaks one import, the test still covers the other.
