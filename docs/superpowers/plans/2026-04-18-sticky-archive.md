# Sticky Archive (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `process_agent_update` from silently resurrecting agents that were just archived. Manual archives become sticky; any archive gets a short cooldown.

**Architecture:** Two complementary guards in the auto-resume path at `src/mcp_handlers/updates/phases.py:320-341`. (1) `handle_archive_agent` stamps `meta.notes` with a `"user requested"` marker so the existing gate at line 337 trips. (2) A new cooldown check refuses auto-resume if the archive happened within `UNITARES_ARCHIVE_COOLDOWN_SECONDS` (default 300), regardless of source. Together these cover manual archives (sticky forever) and all archives (sticky for N seconds) without touching the resident-agent auto-resume behavior that legitimately rescues falsely-sweeped agents after the cooldown.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2, pytest-asyncio, PostgreSQL@17.

**Out of scope (follow-up plans):**
- Stage 2: Audit resident agents (Watcher, Steward, Vigil, Sentinel) to confirm each explicitly calls `identity(agent_uuid=..., resume=true)` on startup rather than depending on `process_agent_update` auto-resume.
- Stage 3: Remove `process_agent_update` auto-resume entirely. Requires Stage 2 to complete first.

**Incident reference:** `acd8a774-0a05` archived at 01:29:33, resurrected at 01:29:43 via `process_agent_update`, circuit-breaker tripped at 02:16:52. Audit trail in `audit.events` for 2026-04-18.

---

## File Map

**Modify:**
- `src/mcp_handlers/lifecycle/mutation.py` — stamp `meta.notes` in `handle_archive_agent` before `_archive_one_agent`.
- `src/mcp_handlers/updates/phases.py:315-410` — add cooldown check in the auto-resume branch.
- `config/governance_config.py` — add `ARCHIVE_RESUME_COOLDOWN_SECONDS` constant (reads `UNITARES_ARCHIVE_COOLDOWN_SECONDS`, default 300).

**Test:**
- `tests/test_sticky_archive.py` — new file, regression coverage for both guards and the incident timeline.
- `tests/test_core_update.py` — existing `test_full_response_contract_preserves_archived_error_shape` stays green (it already uses `notes="User requested archive after handoff"`).

---

## Task 1: Config constant for cooldown window

**Files:**
- Modify: `config/governance_config.py`

- [ ] **Step 1: Read the current config file to find the right insertion point**

Run: `grep -n "^[A-Z_]* = " config/governance_config.py | head -20`

Look for a section where integer/timeout constants live (e.g., near other `*_SECONDS` or `*_HOURS` values).

- [ ] **Step 2: Add the constant**

Insert near other lifecycle/archive-related constants (search for `ARCHIVE` or `LIFECYCLE` in the file — pick the closest neighborhood). Append if no obvious home exists:

```python
# Sticky archive: cooldown window during which process_agent_update
# refuses to auto-resume an archived agent. Prevents the race where
# an archive is silently resurrected by a stale client holding the UUID.
# Override: UNITARES_ARCHIVE_COOLDOWN_SECONDS env var.
ARCHIVE_RESUME_COOLDOWN_SECONDS: int = int(
    os.getenv("UNITARES_ARCHIVE_COOLDOWN_SECONDS", "300")
)
```

If `os` is not already imported at the top of the file, add `import os`.

- [ ] **Step 3: Verify it imports cleanly**

Run: `python -c "from config.governance_config import ARCHIVE_RESUME_COOLDOWN_SECONDS; print(ARCHIVE_RESUME_COOLDOWN_SECONDS)"`
Expected: `300`

- [ ] **Step 4: Commit**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/sticky-archive
git add config/governance_config.py
git commit -m "feat(archive): add ARCHIVE_RESUME_COOLDOWN_SECONDS config"
```

---

## Task 2: Regression test for cooldown (failing)

**Files:**
- Create: `tests/test_sticky_archive.py`

- [ ] **Step 1: Write the failing test for cooldown refusal**

Create `tests/test_sticky_archive.py`:

```python
"""Tests for sticky-archive guard: manual-intent + cooldown window.

Regression coverage for the 2026-04-18 incident where acd8a774 was
manually archived at 01:29:33 and resurrected 10 seconds later via
process_agent_update, then circuit-broke ~45 min later.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_core_update import _make_metadata, parse_result
from tests.test_core_update import TestProcessAgentUpdate as _Base  # reuse fixtures


class TestStickyArchive(_Base):
    """Archive → immediate process_agent_update must NOT auto-resume."""

    @pytest.mark.asyncio
    async def test_recent_archive_within_cooldown_is_rejected(
        self, mock_server, mock_monitor
    ):
        """Archive <300s ago blocks auto-resume even without 'user requested' marker."""
        agent_uuid = "test-uuid-cooldown"
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        meta = _make_metadata(status="archived", total_updates=5)
        meta.archived_at = recent
        meta.notes = ""  # No manual marker — must still be blocked by cooldown.
        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.get_or_create_monitor.return_value = mock_monitor
        mock_server.monitors = {agent_uuid: mock_monitor}

        p = self._common_patches(mock_server, agent_uuid=agent_uuid)
        with self._apply_patches(p):
            from src.mcp_handlers.core import handle_process_agent_update
            result = await handle_process_agent_update({
                "response_text": "Immediate resurrection attempt.",
                "response_mode": "full",
            })
            data = parse_result(result)

        assert data["success"] is False
        assert "cooldown" in data["error"].lower() or "recent" in data["error"].lower()
        assert data["context"]["status"] == "archived"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_sticky_archive.py::TestStickyArchive::test_recent_archive_within_cooldown_is_rejected --no-cov --tb=short -q 2>&1 | tail -20`
Expected: FAIL — auto-resume currently succeeds, assertion `data["success"] is False` fails (test returns a successful resume response, not an error).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_sticky_archive.py
git commit -m "test(archive): add failing regression for archive cooldown"
```

---

## Task 3: Implement cooldown check

**Files:**
- Modify: `src/mcp_handlers/updates/phases.py:336-340` (insert cooldown check immediately above existing gate)

- [ ] **Step 1: Read the target region**

Run: `sed -n '315,370p' src/mcp_handlers/updates/phases.py`
Expected output begins with `# Auto-resume check` and contains the gate block starting at line 336 with `agent_notes = getattr(meta, 'notes', '') or ''`.

- [ ] **Step 2: Add cooldown check ABOVE the existing gate**

Modify `src/mcp_handlers/updates/phases.py`. Find this block (currently at lines 336-365):

```python
            agent_notes = getattr(meta, 'notes', '') or ''
            explicitly_archived = bool(agent_notes and "user requested" in agent_notes.lower())
            too_old = days_since_archive is not None and days_since_archive > 2.0
            too_few_updates = (getattr(meta, 'total_updates', 0) or 0) < 2

            if explicitly_archived or (too_old and too_few_updates):
```

Replace with (adds cooldown gate first, keeps existing gate unchanged):

```python
            # Cooldown guard: any archive within the cooldown window blocks
            # auto-resume regardless of source. Catches the race where a stale
            # client resurrects an agent seconds after it was archived.
            # Incident: 2026-04-18 acd8a774 archived at 01:29:33, resurrected
            # 10s later via process_agent_update, circuit-broke 45min later.
            from config.governance_config import ARCHIVE_RESUME_COOLDOWN_SECONDS
            seconds_since_archive = (
                days_since_archive * 86400 if days_since_archive is not None else None
            )
            in_cooldown = (
                seconds_since_archive is not None
                and seconds_since_archive < ARCHIVE_RESUME_COOLDOWN_SECONDS
            )

            agent_notes = getattr(meta, 'notes', '') or ''
            explicitly_archived = bool(agent_notes and "user requested" in agent_notes.lower())
            too_old = days_since_archive is not None and days_since_archive > 2.0
            too_few_updates = (getattr(meta, 'total_updates', 0) or 0) < 2

            if in_cooldown or explicitly_archived or (too_old and too_few_updates):
```

Then find the reasons block immediately below (currently at lines 342-348):

```python
                reasons = []
                if explicitly_archived:
                    reasons.append(f"explicitly archived: {agent_notes}")
                if too_old:
                    reasons.append(f"archived {days_since_archive:.1f} days ago")
                if too_few_updates:
                    reasons.append(f"only {getattr(meta, 'total_updates', 0) or 0} update(s)")
```

Replace with (adds cooldown reason first so the message surfaces the real cause):

```python
                reasons = []
                if in_cooldown:
                    reasons.append(
                        f"archived {seconds_since_archive:.0f}s ago "
                        f"(cooldown window {ARCHIVE_RESUME_COOLDOWN_SECONDS}s)"
                    )
                if explicitly_archived:
                    reasons.append(f"explicitly archived: {agent_notes}")
                if too_old:
                    reasons.append(f"archived {days_since_archive:.1f} days ago")
                if too_few_updates:
                    reasons.append(f"only {getattr(meta, 'total_updates', 0) or 0} update(s)")
```

- [ ] **Step 3: Run the cooldown test to verify it passes**

Run: `pytest tests/test_sticky_archive.py::TestStickyArchive::test_recent_archive_within_cooldown_is_rejected --no-cov --tb=short -q 2>&1 | tail -15`
Expected: PASS.

- [ ] **Step 4: Run the existing archived-contract test to verify it still passes**

Run: `pytest tests/test_core_update.py::TestProcessAgentUpdate::test_full_response_contract_preserves_archived_error_shape --no-cov --tb=short -q 2>&1 | tail -15`
Expected: PASS. (This test uses `notes="User requested archive after handoff"`, so `explicitly_archived` branch still fires; the cooldown branch also fires because `archived_at` in `_make_metadata` is recent, which is fine — either branch produces an error response.)

- [ ] **Step 5: Commit**

```bash
git add src/mcp_handlers/updates/phases.py
git commit -m "fix(archive): block auto-resume within cooldown window

Any archive within ARCHIVE_RESUME_COOLDOWN_SECONDS (default 300s) now
refuses auto-resume on process_agent_update. Catches the race where a
stale client holding the UUID resurrects an agent seconds after archive.

Ref: 2026-04-18 incident, acd8a774 archived→resurrected in 10s→
circuit-breaker tripped 45min later."
```

---

## Task 4: Add more cooldown coverage (boundary conditions)

**Files:**
- Modify: `tests/test_sticky_archive.py`

- [ ] **Step 1: Add tests for boundary behavior**

Append to `tests/test_sticky_archive.py`, inside class `TestStickyArchive`:

```python
    @pytest.mark.asyncio
    async def test_old_archive_outside_cooldown_can_still_auto_resume(
        self, mock_server, mock_monitor
    ):
        """Archive >300s ago with many updates and no marker IS auto-resumed.

        Preserves the existing behavior where resident agents falsely
        sweeped by orphan heuristic can recover by checking in again
        after the cooldown expires.
        """
        agent_uuid = "test-uuid-old-archive"
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        meta = _make_metadata(status="archived", total_updates=50)
        meta.archived_at = old
        meta.notes = ""
        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.get_or_create_monitor.return_value = mock_monitor
        mock_server.monitors = {agent_uuid: mock_monitor}

        p = self._common_patches(mock_server, agent_uuid=agent_uuid)
        with self._apply_patches(p):
            from src.mcp_handlers.core import handle_process_agent_update
            result = await handle_process_agent_update({
                "response_text": "Legitimate recovery after false sweep.",
                "response_mode": "full",
            })
            data = parse_result(result)

        # Should succeed — agent is auto-resumed. Status goes back to active.
        assert data.get("success") is True, (
            f"Expected auto-resume to succeed for agents archived outside "
            f"cooldown with no manual marker. Got: {json.dumps(data, default=str)[:500]}"
        )

    @pytest.mark.asyncio
    async def test_cooldown_env_override(self, mock_server, mock_monitor, monkeypatch):
        """UNITARES_ARCHIVE_COOLDOWN_SECONDS env var overrides default.

        Setting cooldown to 1s means a 10s-old archive is OUTSIDE cooldown,
        so it can auto-resume (assuming no other gate blocks).
        """
        # Re-import to pick up env override. The constant reads env at import.
        monkeypatch.setenv("UNITARES_ARCHIVE_COOLDOWN_SECONDS", "1")
        import importlib
        import config.governance_config as gc
        importlib.reload(gc)
        assert gc.ARCHIVE_RESUME_COOLDOWN_SECONDS == 1

        agent_uuid = "test-uuid-env-override"
        recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        meta = _make_metadata(status="archived", total_updates=50)
        meta.archived_at = recent
        meta.notes = ""
        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.get_or_create_monitor.return_value = mock_monitor
        mock_server.monitors = {agent_uuid: mock_monitor}

        p = self._common_patches(mock_server, agent_uuid=agent_uuid)
        with self._apply_patches(p):
            from src.mcp_handlers.core import handle_process_agent_update
            result = await handle_process_agent_update({
                "response_text": "With cooldown=1s, 10s-old archive is outside window.",
                "response_mode": "full",
            })
            data = parse_result(result)

        assert data.get("success") is True, (
            f"With cooldown=1s, 10s-old archive should auto-resume. "
            f"Got: {json.dumps(data, default=str)[:500]}"
        )

        # Restore default for later tests.
        monkeypatch.delenv("UNITARES_ARCHIVE_COOLDOWN_SECONDS", raising=False)
        importlib.reload(gc)
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/test_sticky_archive.py --no-cov --tb=short -q 2>&1 | tail -20`
Expected: All 3 tests PASS.

**Gotcha:** If `test_cooldown_env_override` fails with "constant not updated," it means `phases.py` imports the constant at module-load time instead of reading it per-call. The inline `from config.governance_config import ARCHIVE_RESUME_COOLDOWN_SECONDS` in Task 3 step 2 is intentionally inside the function body so reload works. If the reload test still fails, wrap the import in a `lambda`/helper or read the env var directly inside the function instead of via the constant.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sticky_archive.py
git commit -m "test(archive): cover cooldown boundary + env override"
```

---

## Task 5: Stamp manual archives with sticky marker (failing test)

**Files:**
- Modify: `tests/test_sticky_archive.py`

- [ ] **Step 1: Write failing test for manual-archive stamping**

Append to `tests/test_sticky_archive.py`:

```python
class TestManualArchiveMarker:
    """handle_archive_agent must stamp meta.notes so existing gate trips."""

    @pytest.mark.asyncio
    async def test_manual_archive_stamps_user_requested_marker(self):
        """After handle_archive_agent, meta.notes must contain 'user requested'."""
        from src.mcp_handlers.lifecycle.mutation import handle_archive_agent
        from src.agent_metadata_model import AgentMetadata

        agent_uuid = "test-uuid-manual-stamp"
        meta = AgentMetadata(agent_id=agent_uuid, label="test")
        meta.status = "active"
        meta.notes = ""

        mock_server = MagicMock()
        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.load_metadata_async = AsyncMock()
        mock_server.monitors = {}

        with patch("src.mcp_handlers.lifecycle.mutation.mcp_server", mock_server), \
             patch(
                 "src.mcp_handlers.lifecycle.mutation.require_registered_agent",
                 return_value=(agent_uuid, None),
             ), \
             patch(
                 "src.mcp_handlers.lifecycle.mutation.resolve_agent_uuid",
                 return_value=agent_uuid,
             ), \
             patch(
                 "src.mcp_handlers.lifecycle.helpers._archive_one_agent",
                 new=AsyncMock(return_value=True),
             ), \
             patch(
                 "src.mcp_handlers.lifecycle.mutation._invalidate_agent_cache",
                 new=AsyncMock(),
             ), \
             patch(
                 "src.mcp_handlers.lifecycle.mutation.get_bound_agent_id",
                 return_value="caller-uuid",
             ):
            result = await handle_archive_agent({
                "agent_id": agent_uuid,
                "reason": "Manual archive",
            })

        assert "user requested" in meta.notes.lower(), (
            f"handle_archive_agent must stamp meta.notes with 'user requested' "
            f"marker so phases.py:337 gate catches it. Got notes={meta.notes!r}"
        )
```

- [ ] **Step 2: Run — it fails**

Run: `pytest tests/test_sticky_archive.py::TestManualArchiveMarker --no-cov --tb=short -q 2>&1 | tail -15`
Expected: FAIL — `meta.notes` is still empty after `handle_archive_agent`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_sticky_archive.py
git commit -m "test(archive): add failing test for manual-archive notes stamping"
```

---

## Task 6: Implement manual-archive notes stamping

**Files:**
- Modify: `src/mcp_handlers/lifecycle/mutation.py` around line 201

- [ ] **Step 1: Read the target region**

Run: `sed -n '195,215p' src/mcp_handlers/lifecycle/mutation.py`
Expected output includes `reason = arguments.get("reason", "Manual archive")`.

- [ ] **Step 2: Stamp `meta.notes` before archival**

Find in `src/mcp_handlers/lifecycle/mutation.py`:

```python
    reason = arguments.get("reason", "Manual archive")
    keep_in_memory = arguments.get("keep_in_memory", False)

    # Persist-first: write to Postgres before mutating in-memory state
    from .helpers import _archive_one_agent
    monitors = None if keep_in_memory else mcp_server.monitors
    ok = await _archive_one_agent(agent_uuid, meta, reason, monitors=monitors)
```

Replace with:

```python
    reason = arguments.get("reason", "Manual archive")
    keep_in_memory = arguments.get("keep_in_memory", False)

    # Stamp notes with the sticky-archive marker so phases.py:337 auto-resume
    # gate refuses to resurrect this identity on a later process_agent_update.
    # The marker is intentionally additive to preserve any existing notes.
    existing_notes = (getattr(meta, "notes", "") or "").strip()
    marker = f"user requested archive: {reason}"
    if "user requested" not in existing_notes.lower():
        meta.notes = f"{existing_notes}\n{marker}".strip() if existing_notes else marker

    # Persist-first: write to Postgres before mutating in-memory state
    from .helpers import _archive_one_agent
    monitors = None if keep_in_memory else mcp_server.monitors
    ok = await _archive_one_agent(agent_uuid, meta, reason, monitors=monitors)
```

Note: this only runs in `handle_archive_agent` (the manual-archive path). `archive_orphan_agents` calls `_archive_one_agent` directly via a different code path and is unaffected — orphan sweep archives remain non-sticky, which is correct behavior (they may be false positives on legitimate residents).

- [ ] **Step 3: Run the test — it passes**

Run: `pytest tests/test_sticky_archive.py::TestManualArchiveMarker --no-cov --tb=short -q 2>&1 | tail -10`
Expected: PASS.

- [ ] **Step 4: Verify orphan-sweep is unaffected**

Run: `grep -n "_archive_one_agent\|meta.notes" src/agent_lifecycle.py 2>&1 | head -20`
Expected: `_archive_one_agent` appears but no `meta.notes` stamping near it. If it does stamp notes, stop and reconsider — orphan-sweep archives should not be sticky.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_handlers/lifecycle/mutation.py
git commit -m "fix(archive): stamp 'user requested' marker in meta.notes on manual archive

Manual archives via handle_archive_agent now stamp meta.notes so the
existing auto-resume gate at phases.py:337 trips on subsequent
process_agent_update calls. Orphan-sweep archives are unaffected (they
remain non-sticky — intentional, since the heuristic may false-positive
on legitimate resident agents)."
```

---

## Task 7: End-to-end incident timeline regression

**Files:**
- Modify: `tests/test_sticky_archive.py`

- [ ] **Step 1: Add incident-replay test**

Append to `tests/test_sticky_archive.py`:

```python
class TestIncidentReplay:
    """Replay the 2026-04-18 acd8a774 incident timeline."""

    @pytest.mark.asyncio
    async def test_archive_then_immediate_update_is_refused(
        self, mock_server, mock_monitor
    ):
        """Manual archive → 10s later process_agent_update → MUST NOT auto-resume.

        Exact timeline from the incident:
        - T+0: manual archive (stamps 'user requested' marker + sets archived_at)
        - T+10s: process_agent_update arrives with same agent_uuid
        - Expected: error response (blocked by manual marker AND cooldown)
        """
        agent_uuid = "test-uuid-incident-acd8a774"

        # Step 1: simulate the manual-archive state that handle_archive_agent
        # would have produced (meta.notes stamped, status=archived, archived_at=recent).
        archived_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        meta = _make_metadata(status="archived", total_updates=12)
        meta.archived_at = archived_at
        meta.notes = "user requested archive: Manual archive"

        mock_server.agent_metadata = {agent_uuid: meta}
        mock_server.get_or_create_monitor.return_value = mock_monitor
        mock_server.monitors = {agent_uuid: mock_monitor}

        # Step 2: process_agent_update from a stale client holding the UUID.
        p = self._common_patches(mock_server, agent_uuid=agent_uuid)
        with self._apply_patches(p):
            from src.mcp_handlers.core import handle_process_agent_update
            result = await handle_process_agent_update({
                "response_text": "Incident: stale client resuming after archive.",
                "response_mode": "full",
            })
            data = parse_result(result)

        assert data["success"] is False
        error_text = data["error"].lower()
        # Either marker OR cooldown may be cited first — both are correct.
        assert "cannot be auto-resumed" in error_text
        assert ("user requested" in error_text or "cooldown" in error_text)
        assert data["context"]["status"] == "archived"
```

Insert into `TestIncidentReplay` class — add the class definition if not present.

- [ ] **Step 2: Run it**

Run: `pytest tests/test_sticky_archive.py::TestIncidentReplay --no-cov --tb=short -q 2>&1 | tail -10`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sticky_archive.py
git commit -m "test(archive): regression test for 2026-04-18 incident timeline"
```

---

## Task 8: Full test suite + pre-commit

**Files:** None modified.

- [ ] **Step 1: Run the full focused test files**

Run: `pytest tests/test_sticky_archive.py tests/test_core_update.py --no-cov --tb=short -q 2>&1 | tail -30`
Expected: All tests PASS. No regressions in `test_core_update.py`.

- [ ] **Step 2: Run the pre-commit test cache**

Run: `./scripts/dev/test-cache.sh 2>&1 | tail -40`
Expected: PASS (may take a few minutes on first run for this worktree; subsequent runs hit the tree-hash cache).

**If it fails:** investigate. Do not commit broken tests. Do not skip with `--no-verify`.

- [ ] **Step 3: Verify shared-contract parity if any root .md was touched**

Run: `ls -la AGENTS.md CLAUDE.md 2>/dev/null && ./scripts/dev/check-shared-contract.sh 2>&1 | tail -5`
Expected: `OK` or equivalent. (This plan doesn't touch AGENTS.md/CLAUDE.md, so this should be a no-op — run it to be safe.)

---

## Task 9: Resolve Watcher findings and close the loop

**Files:** None modified. Audit + close.

- [ ] **Step 1: Confirm no new Watcher findings were introduced**

Run: `python3 agents/watcher/agent.py --sweep-stale 2>&1 | tail -10` (cleans stale)
Then: `python3 agents/watcher/agent.py --list 2>&1 | tail -30`
Expected: No new unresolved entries in files we modified (`phases.py`, `mutation.py`, `test_sticky_archive.py`).

If new findings appear, either resolve (if legitimate) or dismiss with a reason.

- [ ] **Step 2: Prepare PR description**

Summary for the PR:
```
Stop silent auto-resurrection of archived agents via process_agent_update.

Two guards added:
1. Manual archives (handle_archive_agent) stamp meta.notes with a
   'user requested' marker so the existing auto-resume gate blocks them.
2. Any archive within ARCHIVE_RESUME_COOLDOWN_SECONDS (default 300s,
   env override UNITARES_ARCHIVE_COOLDOWN_SECONDS) blocks auto-resume
   regardless of source.

Incident reference: 2026-04-18, acd8a774 archived at 01:29:33 by session
19aa67b5, resurrected 10s later via process_agent_update, drifted for
~45 min, circuit-breaker tripped at 02:16:52.

Out of scope (follow-up plans):
- Stage 2: audit resident agents' startup paths.
- Stage 3: remove process_agent_update auto-resume entirely.
```

- [ ] **Step 3: Ship**

Run: `./scripts/dev/ship.sh` and handle the routing prompts as it surfaces them.

---

## Self-Review Checklist

- **Spec coverage**
  - Option 1 (respect manual archives) → Tasks 5 + 6.
  - Option 2 (short-window refusal) → Tasks 1 + 2 + 3 + 4.
  - Incident regression → Task 7.
  - Options 3 (flip default) and the resident-agent audit → explicitly out of scope; listed as Stage 2 + 3 follow-ups in the header.

- **Placeholder scan**
  - No TBDs, no "implement later," no "add error handling" hand-waves.
  - Every step shows either exact code, an exact command, or exact expected output.

- **Type consistency**
  - `ARCHIVE_RESUME_COOLDOWN_SECONDS`: `int`, consistent across Task 1 and Task 3.
  - `meta.notes`: `str`, matches `AgentMetadata.notes: str = ""` at `src/agent_metadata_model.py:147`.
  - `seconds_since_archive`: computed from `days_since_archive` (already `float | None` in existing code).
  - `"user requested"` marker substring used identically in Tasks 3, 5, 6, 7.

- **Known risk**
  - Task 3's `importlib.reload(gc)` approach for env-override testing is fragile. If it fails, switch to reading `os.getenv("UNITARES_ARCHIVE_COOLDOWN_SECONDS", "300")` directly inside the phases.py check instead of via the constant. Noted in Task 4 Step 2 gotcha.
