# Sever Fingerprint-Based EISV Inheritance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sever silent cross-identity EISV state transplant and implicit lineage claims caused by fingerprint matching during `onboard`. Make `parent_agent_id` lineage explicit-only; ensure the `continuity_token` path continues to work.

**Architecture:** Three targeted deletions plus one string change in `src/` (no new files in `src/`), two new test files in `tests/`, and selective updates to any existing tests that asserted the old behavior. No schema migration. Single PR.

**Tech Stack:** Python 3.11+, pytest-asyncio, unittest.mock (`AsyncMock`, `MagicMock`, `patch`), UNITARES identity stack (`src/mcp_handlers/identity/*`, `src/agent_lifecycle.py`).

**Spec:** `docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md`

---

## Prerequisite: Worktree

This plan was written without brainstorming creating a worktree. Before executing, create one:

```bash
cd /Users/cirwel/projects/unitares
git worktree add ../unitares-sever-inheritance -b sever-fingerprint-eisv-inheritance
cd ../unitares-sever-inheritance
```

All paths in this plan are relative to the unitares repo root (worktree or main). All file paths are the same; just run commands from the worktree.

---

## File Structure

**Modified (`src/`):**
- `src/agent_lifecycle.py` — delete the `else` transplant branch inside `get_or_create_monitor`; replace with a single `logger.info` call.
- `src/mcp_handlers/identity/resolution.py` — delete the two `_predecessor_uuid = agent_uuid` assignments (PATH 1 Redis hit, PATH 2 PostgreSQL hit). Downstream `if _predecessor_uuid:` guards stay as-is (defensive, harmless).
- `src/mcp_handlers/identity/handlers.py` — delete the now-unreachable block at lines 1093–1098 that wires `_parent_agent_id` from `existing_identity["predecessor_uuid"]`.
- `src/services/identity_payloads.py` — update the `predecessor` response note from *"Your state was inherited from it."* to *"Lineage record only; no state was inherited."*

**Created (`tests/`):**
- `tests/test_no_fingerprint_inheritance.py` — four new tests covering the spec's four test cases.

**Potentially modified (`tests/`):**
- `tests/test_identity_handlers.py` — if `test_onboard_resume_false` or related tests assert that `result["predecessor"]` is populated on fingerprint-match-only cases, update them to assert absence.
- `tests/test_thread_identity.py` — same treatment for any test asserting auto-lineage on fingerprint.

The scan for breakages happens in Task 8.

---

## Task 1: Red — state transplant test

**Files:**
- Create: `tests/test_no_fingerprint_inheritance.py`
- Reference: `src/agent_lifecycle.py:33-43`

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_fingerprint_inheritance.py` with:

```python
"""
Tests for the spec docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md

Covers:
- State transplant is gone (agent_lifecycle.get_or_create_monitor)
- Fingerprint match on resume=False no longer sets _predecessor_uuid
- Explicit parent_agent_id still records lineage (without state transplant)
- continuity_token round-trip preserves UUID
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from src.agent_metadata_model import AgentMetadata, agent_metadata
from src.agent_monitor_state import monitors


@pytest.fixture(autouse=True)
def _clear_process_state():
    """Each test starts with fresh in-memory identity state."""
    monitors.clear()
    agent_metadata.clear()
    yield
    monitors.clear()
    agent_metadata.clear()


def test_get_or_create_monitor_does_not_transplant_state_from_predecessor():
    """
    Regression guard: once agent_lifecycle.get_or_create_monitor no longer
    transplants state from a predecessor, a new agent with parent_agent_id
    set should start with a fresh GovernanceState (empty V_history).
    """
    from src.agent_lifecycle import get_or_create_monitor
    from src.governance_monitor import UNITARESMonitor

    # Build a predecessor monitor and populate its state so
    # load_monitor_state(parent_uuid) would return something real.
    parent_uuid = "parent-uuid-1111"
    parent_monitor = UNITARESMonitor(parent_uuid)
    parent_monitor.state.V_history.extend([0.1, 0.2, 0.3])
    monitors[parent_uuid] = parent_monitor

    # Child agent metadata points to the predecessor.
    child_uuid = "child-uuid-2222"
    agent_metadata[child_uuid] = AgentMetadata(
        agent_id=child_uuid, parent_agent_id=parent_uuid
    )

    # load_monitor_state(parent_uuid) in the real code path would return
    # the parent's persisted state. Force it to return the parent's in-memory
    # state so the "if we wanted to transplant, we could" path is exercised.
    def fake_load(agent_id):
        if agent_id == parent_uuid:
            return parent_monitor.state
        return None

    with patch("src.agent_lifecycle.load_monitor_state", side_effect=fake_load):
        child_monitor = get_or_create_monitor(child_uuid)

    assert child_monitor.state.V_history == [], (
        "Child agent must not inherit predecessor V_history "
        f"(got {child_monitor.state.V_history!r})"
    )
```

- [ ] **Step 2: Run test to verify it fails (red)**

```bash
cd /Users/cirwel/projects/unitares
pytest tests/test_no_fingerprint_inheritance.py::test_get_or_create_monitor_does_not_transplant_state_from_predecessor -v
```

Expected: **FAIL** — assertion `child_monitor.state.V_history == []` fails because current code transplants `[0.1, 0.2, 0.3]`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_no_fingerprint_inheritance.py
git commit -m "test(lifecycle): red test — no state transplant from predecessor"
```

---

## Task 2: Green — delete state transplant

**Files:**
- Modify: `src/agent_lifecycle.py:32-43`

- [ ] **Step 1: Read the current code**

Confirm the current block at `src/agent_lifecycle.py` lines 28–45:

```python
        persisted_state = load_monitor_state(agent_id)
        if persisted_state is not None:
            monitor.state = persisted_state
            logger.info(f"Loaded persisted state for {agent_id} ({len(persisted_state.V_history)} history entries)")
        else:
            # Inherit EISV from predecessor if available
            meta = agent_metadata.get(agent_id)
            if meta and meta.parent_agent_id:
                parent_state = load_monitor_state(meta.parent_agent_id)
                if parent_state:
                    monitor.state = parent_state
                    logger.info(f"Inherited EISV from predecessor {meta.parent_agent_id[:8]}...")
                else:
                    logger.info(f"Initialized new monitor for {agent_id} (predecessor {meta.parent_agent_id[:8]}... had no state)")
            else:
                logger.info(f"Initialized new monitor for {agent_id}")

        monitors[agent_id] = monitor
```

- [ ] **Step 2: Replace the `else` branch**

Edit `src/agent_lifecycle.py`. Replace lines 32–43 (the entire `else:` block including the `# Inherit EISV from predecessor if available` comment) with:

```python
        else:
            # Lineage is recorded via meta.parent_agent_id but never transplants
            # state; see docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md
            logger.info(f"Initialized new monitor for {agent_id}")
```

After the edit the block should look like:

```python
        persisted_state = load_monitor_state(agent_id)
        if persisted_state is not None:
            monitor.state = persisted_state
            logger.info(f"Loaded persisted state for {agent_id} ({len(persisted_state.V_history)} history entries)")
        else:
            # Lineage is recorded via meta.parent_agent_id but never transplants
            # state; see docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md
            logger.info(f"Initialized new monitor for {agent_id}")

        monitors[agent_id] = monitor
```

- [ ] **Step 3: Run the test — verify green**

```bash
pytest tests/test_no_fingerprint_inheritance.py::test_get_or_create_monitor_does_not_transplant_state_from_predecessor -v
```

Expected: **PASS**.

- [ ] **Step 4: Commit**

```bash
git add src/agent_lifecycle.py
git commit -m "fix(lifecycle): stop transplanting EISV state from predecessor

Lineage via parent_agent_id now records who came before without
adopting their V_history/coherence/regime/governor state. Continuity
of a single agent is carried via persisted state for that agent_id
(load_monitor_state(agent_id)), not via silent inheritance from a
fingerprint-matched predecessor.

Spec: docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md"
```

---

## Task 3: Red — fingerprint match no longer claims lineage

**Files:**
- Modify: `tests/test_no_fingerprint_inheritance.py`
- Reference: `src/mcp_handlers/identity/resolution.py:388-395` (PATH 1) and `505-510` (PATH 2)

- [ ] **Step 1: Add two red tests**

Append to `tests/test_no_fingerprint_inheritance.py`:

```python
@pytest.mark.asyncio
async def test_path1_redis_hit_resume_false_does_not_set_predecessor():
    """
    PATH 1: Redis lookup finds a cached agent. resume=False now creates
    a new identity WITHOUT recording the cached agent as predecessor.
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.mcp_handlers.identity import resolution as resolution_mod

    existing_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    cache_hit = {
        "agent_id": existing_uuid,
        "display_agent_id": "OldAgent",
    }
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=cache_hit)

    mock_raw_redis = AsyncMock()
    mock_raw_redis.expire = AsyncMock(return_value=True)

    mock_db = AsyncMock()
    mock_db.init = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=None)
    mock_db.upsert_agent = AsyncMock()
    mock_db.upsert_identity = AsyncMock()
    mock_db.create_session = AsyncMock()
    mock_db.get_identity = AsyncMock(return_value=None)

    with patch.object(resolution_mod, "get_cache", return_value=mock_redis), \
         patch.object(resolution_mod, "get_redis", return_value=mock_raw_redis), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_agent_exists_in_postgres", AsyncMock(return_value=True)), \
         patch.object(resolution_mod, "_get_agent_label", AsyncMock(return_value="OldAgent")), \
         patch.object(resolution_mod, "_get_agent_status", AsyncMock(return_value="active")), \
         patch.object(resolution_mod, "_soft_verify_trajectory", AsyncMock(return_value={"verified": True})), \
         patch.object(resolution_mod, "_cache_session", AsyncMock()):
        result = await resolution_mod.resolve_session_identity(
            session_key="fp-session-1",
            resume=False,
            persist=False,
        )

    # A brand-new identity should have been created.
    assert result["created"] is True
    assert result["agent_uuid"] != existing_uuid
    # And it MUST NOT carry predecessor_uuid forward.
    assert "predecessor_uuid" not in result, (
        f"resume=False + Redis fingerprint hit must not leak predecessor_uuid "
        f"(got {result.get('predecessor_uuid')!r})"
    )


@pytest.mark.asyncio
async def test_path2_postgres_hit_resume_false_does_not_set_predecessor():
    """
    PATH 2: Redis miss, PostgreSQL finds a session-bound agent.
    resume=False must not claim that agent as predecessor.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.mcp_handlers.identity import resolution as resolution_mod

    existing_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)  # PATH 1 miss

    mock_raw_redis = AsyncMock()
    mock_raw_redis.expire = AsyncMock(return_value=True)

    mock_db = AsyncMock()
    mock_db.init = AsyncMock()
    mock_db.get_session = AsyncMock(
        return_value=SimpleNamespace(agent_id=existing_uuid)
    )
    mock_db.upsert_agent = AsyncMock()
    mock_db.upsert_identity = AsyncMock()
    mock_db.create_session = AsyncMock()
    mock_db.get_identity = AsyncMock(return_value=None)

    with patch.object(resolution_mod, "get_cache", return_value=mock_redis), \
         patch.object(resolution_mod, "get_redis", return_value=mock_raw_redis), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_agent_exists_in_postgres", AsyncMock(return_value=True)), \
         patch.object(resolution_mod, "_get_agent_label", AsyncMock(return_value="OldAgent")), \
         patch.object(resolution_mod, "_get_agent_status", AsyncMock(return_value="active")), \
         patch.object(resolution_mod, "_soft_verify_trajectory", AsyncMock(return_value={"verified": True})), \
         patch.object(resolution_mod, "_cache_session", AsyncMock()):
        result = await resolution_mod.resolve_session_identity(
            session_key="fp-session-2",
            resume=False,
            persist=False,
        )

    assert result["created"] is True
    assert result["agent_uuid"] != existing_uuid
    assert "predecessor_uuid" not in result, (
        f"resume=False + PostgreSQL session hit must not leak predecessor_uuid "
        f"(got {result.get('predecessor_uuid')!r})"
    )
```

- [ ] **Step 2: Run tests — verify red**

```bash
pytest tests/test_no_fingerprint_inheritance.py::test_path1_redis_hit_resume_false_does_not_set_predecessor \
       tests/test_no_fingerprint_inheritance.py::test_path2_postgres_hit_resume_false_does_not_set_predecessor -v
```

Expected: **both FAIL** — `predecessor_uuid` is currently present in the result because PATH 1/2 set `_predecessor_uuid = agent_uuid` and PATH 3 populates `result["predecessor_uuid"]`.

If the mocks cause a different error (e.g., a mismatch in patched names), inspect `src/mcp_handlers/identity/resolution.py` imports near the top and adjust `patch.object` targets to match the actual import names used there (e.g., `get_cache` vs `get_redis_cache`). Fix the mocks and rerun. The tests should fail on the assertion, not on mock setup.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_no_fingerprint_inheritance.py
git commit -m "test(identity): red tests — fingerprint match no longer claims lineage"
```

---

## Task 4: Green — delete PATH 1 and PATH 2 predecessor assignments

**Files:**
- Modify: `src/mcp_handlers/identity/resolution.py:388-395` (PATH 1)
- Modify: `src/mcp_handlers/identity/resolution.py:505-510` (PATH 2)

- [ ] **Step 1: Edit PATH 1 (Redis hit)**

In `src/mcp_handlers/identity/resolution.py`, replace lines 388–395:

```python
                    # IDENTITY HONESTY: When resume=False, don't return cached identity.
                    # Record it as predecessor and fall through to PATH 3 (create new).
                    if not resume:
                        _predecessor_uuid = agent_uuid
                        logger.info(
                            f"[IDENTITY] resume=False, skipping Redis hit for {agent_uuid[:8]}... "
                            f"(will create new with predecessor link)"
                        )
                    else:
```

with:

```python
                    # IDENTITY HONESTY: resume=False means "I am not the cached
                    # agent" — fall through to PATH 3 (create new) WITHOUT
                    # claiming lineage. Fingerprint match is a hint, not a
                    # succession claim. See the 2026-04-16 EISV inheritance spec.
                    if not resume:
                        logger.info(
                            f"[IDENTITY] resume=False, skipping Redis hit for {agent_uuid[:8]}..."
                        )
                    else:
```

- [ ] **Step 2: Edit PATH 2 (PostgreSQL hit)**

Locate lines 505–510 — the PATH 2 analogue:

```python
                    # IDENTITY HONESTY: When resume=False, don't return PG identity.
                    if not resume:
                        _predecessor_uuid = agent_uuid
                        logger.info(
                            f"[IDENTITY] resume=False, skipping PG hit for {agent_uuid[:8]}... "
```

Replace the entire `if not resume:` block (assignment + log call, typically 4–6 lines) with:

```python
                    # IDENTITY HONESTY: resume=False falls through to PATH 3
                    # WITHOUT claiming lineage. See Redis-path comment above.
                    if not resume:
                        logger.info(
                            f"[IDENTITY] resume=False, skipping PG hit for {agent_uuid[:8]}..."
                        )
```

Use `grep -n "_predecessor_uuid = agent_uuid" src/mcp_handlers/identity/resolution.py` first to confirm both assignments are gone.

- [ ] **Step 3: Run the two PATH tests — verify green**

```bash
pytest tests/test_no_fingerprint_inheritance.py::test_path1_redis_hit_resume_false_does_not_set_predecessor \
       tests/test_no_fingerprint_inheritance.py::test_path2_postgres_hit_resume_false_does_not_set_predecessor -v
```

Expected: **both PASS**.

- [ ] **Step 4: Confirm no live assignments remain**

```bash
grep -n "_predecessor_uuid = agent_uuid" src/mcp_handlers/identity/resolution.py
```

Expected: **no matches**. The initialization at line 335 (`_predecessor_uuid = None`) stays; only the two assignments disappear. Downstream `if _predecessor_uuid:` guards at lines ~679, ~743, ~766 stay as-is (defensive; never trigger now).

- [ ] **Step 5: Commit**

```bash
git add src/mcp_handlers/identity/resolution.py
git commit -m "fix(identity): stop claiming lineage on fingerprint match

When resume=False and fingerprint matches a prior agent via Redis
(PATH 1) or session binding in PostgreSQL (PATH 2), we no longer
record that agent as the new identity's predecessor. Fingerprint
match is now purely a routing hint, not a succession claim.

Downstream guards on _predecessor_uuid remain in place as defensive
scaffolding for an explicit-forking API if one is added later.

Spec: docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md"
```

---

## Task 5: Delete dormant `handlers.py` wiring block

**Files:**
- Modify: `src/mcp_handlers/identity/handlers.py:1093-1098`

No new test: this block is now unreachable (verified by Task 4). Removing it improves clarity and is covered by the existing onboard tests continuing to pass.

- [ ] **Step 1: Read current code**

```bash
sed -n '1091,1100p' src/mcp_handlers/identity/handlers.py
```

Expected output includes:

```python
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            # IDENTITY HONESTY: Wire predecessor from resolve_session_identity
            # when resume=False found an existing identity but created a new UUID
            if not _parent_agent_id and existing_identity.get("predecessor_uuid"):
                _parent_agent_id = existing_identity["predecessor_uuid"]
                if not _spawn_reason:
                    _spawn_reason = "new_session"
            logger.info(f"[ONBOARD] Created fresh identity {agent_uuid[:8]}... (will persist)")
```

- [ ] **Step 2: Delete the dormant block**

Remove lines 1093–1098 (the comment + the `if not _parent_agent_id ...` block). The result should be:

```python
            agent_uuid = existing_identity.get("agent_uuid")
            agent_id = existing_identity.get("agent_id", agent_uuid)
            logger.info(f"[ONBOARD] Created fresh identity {agent_uuid[:8]}... (will persist)")
```

- [ ] **Step 3: Run existing onboard tests to confirm no regression**

```bash
pytest tests/test_identity_handlers.py -v -k "onboard"
```

Expected: all pass (minus any fingerprint-lineage-assuming tests we'll fix in Task 8).

- [ ] **Step 4: Commit**

```bash
git add src/mcp_handlers/identity/handlers.py
git commit -m "chore(identity): remove dormant predecessor wiring in onboard

After severing PATH 1/2 lineage claims in resolve_session_identity,
this block is unreachable. Delete rather than keep as stale defense.
If an explicit-forking API is added later that routes through the
resolver, the 5 lines can be re-added with an actual test."
```

---

## Task 6: Red + green — explicit `parent_agent_id` records lineage, no state

**Files:**
- Modify: `tests/test_no_fingerprint_inheritance.py`

No source change — Tasks 2 and 4 already produced the desired behavior. This test just asserts it stays that way.

- [ ] **Step 1: Add the test**

Append to `tests/test_no_fingerprint_inheritance.py`:

```python
def test_explicit_parent_agent_id_records_lineage_without_state_transplant():
    """
    When a caller explicitly asserts a predecessor via parent_agent_id on
    agent_metadata, the metadata row records lineage but the new agent's
    monitor starts with a fresh GovernanceState.
    """
    from src.agent_lifecycle import get_or_create_monitor
    from src.governance_monitor import UNITARESMonitor

    parent_uuid = "explicit-parent-uuid-3333"
    parent_monitor = UNITARESMonitor(parent_uuid)
    parent_monitor.state.V_history.extend([0.5, 0.6])
    monitors[parent_uuid] = parent_monitor

    child_uuid = "explicit-child-uuid-4444"
    # Explicit caller assertion: "I am forking from parent_uuid"
    agent_metadata[child_uuid] = AgentMetadata(
        agent_id=child_uuid, parent_agent_id=parent_uuid
    )

    def fake_load(agent_id):
        if agent_id == parent_uuid:
            return parent_monitor.state
        return None

    with patch("src.agent_lifecycle.load_monitor_state", side_effect=fake_load):
        child_monitor = get_or_create_monitor(child_uuid)

    # Lineage is recorded in metadata.
    assert agent_metadata[child_uuid].parent_agent_id == parent_uuid
    # But state is NOT transplanted.
    assert child_monitor.state.V_history == []
```

- [ ] **Step 2: Run it — expect green immediately**

```bash
pytest tests/test_no_fingerprint_inheritance.py::test_explicit_parent_agent_id_records_lineage_without_state_transplant -v
```

Expected: **PASS** (behavior is already correct after Tasks 2 and 4).

- [ ] **Step 3: Commit**

```bash
git add tests/test_no_fingerprint_inheritance.py
git commit -m "test(lifecycle): explicit parent_agent_id records lineage only"
```

---

## Task 7: Update response note in `identity_payloads.py`

**Files:**
- Modify: `src/services/identity_payloads.py:252-256`

- [ ] **Step 1: Read current code**

```bash
sed -n '250,258p' src/services/identity_payloads.py
```

Expected to contain:

```python
    if parent_agent_id and not force_new:
        result["predecessor"] = {
            "uuid": parent_agent_id,
            "note": "Previous instance in this trajectory. Your state was inherited from it.",
        }
```

- [ ] **Step 2: Replace the note string**

Replace the note value — the enclosing block stays the same. The new block:

```python
    if parent_agent_id and not force_new:
        result["predecessor"] = {
            "uuid": parent_agent_id,
            "note": "Lineage record only; no state was inherited.",
        }
```

- [ ] **Step 3: Check for tests that pin on the old string**

```bash
grep -rn "Your state was inherited from it" tests/ src/ docs/
```

Expected: no code matches. If `docs/` or `CHANGELOG.md` contains the old string, leave those (historical record). If any test asserts against the old string, note the file for Task 8.

- [ ] **Step 4: Run identity-payloads tests**

```bash
pytest tests/test_identity_payloads.py -v
```

Expected: all pass. If one fails because it asserts the old note string, fix it in this task (edit the expected string to match the new one) and commit together.

- [ ] **Step 5: Commit**

```bash
git add src/services/identity_payloads.py
# add tests/test_identity_payloads.py too if a string assertion was updated
git commit -m "fix(payloads): honest predecessor note — lineage only, no state

The previous note claimed 'Your state was inherited from it', which
was true under the old transplant code. After severing the transplant,
predecessor is a pure lineage record; the note now reflects that.

Predecessor field itself now only appears when a caller explicitly
asserted parent_agent_id (never auto-populated from fingerprint)."
```

---

## Task 8: Red — continuity token round-trip preserves UUID

**Files:**
- Modify: `tests/test_no_fingerprint_inheritance.py`

- [ ] **Step 1: Look at existing fixtures**

```bash
grep -n "patch_onboard_deps\b" tests/test_identity_handlers.py | head -5
```

The `patch_onboard_deps` fixture in `test_identity_handlers.py` provides a pre-wired environment for `handle_onboard_v2`. We'll import it via `conftest`-style fixture reuse.

- [ ] **Step 2: Add the test**

Append to `tests/test_no_fingerprint_inheritance.py`. This test uses the module directly; if `patch_onboard_deps` is defined inline in `test_identity_handlers.py` (not in `conftest.py`), duplicate the minimal needed mocking inline — do not import the fixture across test files.

```python
@pytest.mark.asyncio
async def test_continuity_token_roundtrip_preserves_uuid():
    """
    Onboard once, capture continuity_token, call a subsequent tool with
    that token, and assert the identity resolves to the same UUID.

    Guards against regressions in the explicit continuity path — the
    blessed alternative to fingerprint-based resumption.
    """
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.mcp_handlers.identity import resolution as resolution_mod
    from src.mcp_handlers.identity.handlers import handle_onboard_v2
    from tests.helpers import parse_result

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_raw_redis = AsyncMock()
    mock_raw_redis.expire = AsyncMock(return_value=True)
    mock_raw_redis.setex = AsyncMock()

    mock_db = AsyncMock()
    mock_db.init = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=None)
    mock_db.upsert_agent = AsyncMock()
    mock_db.upsert_identity = AsyncMock()
    mock_db.create_session = AsyncMock()
    mock_db.get_identity = AsyncMock(
        return_value=SimpleNamespace(identity_id="id-1", metadata={})
    )

    with patch.object(resolution_mod, "get_cache", return_value=mock_redis), \
         patch.object(resolution_mod, "get_redis", return_value=mock_raw_redis), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_cache_session", AsyncMock()):
        first = await handle_onboard_v2({
            "client_session_id": "token-roundtrip-1",
            "name": "TokenAgent",
        })
        first_data = parse_result(first)

    assert first_data["success"] is True
    onboarded_uuid = first_data["uuid"]
    assert onboarded_uuid, "onboard must return a uuid"
    token = first_data["continuity_token"]
    assert token, "onboard must return a continuity_token"

    # Second call — passing the continuity_token should resolve to the SAME UUID.
    # Make the mocks reflect that the agent now exists (so resume via token can
    # find it) by having the cache return the onboarded agent on lookup.
    mock_redis.get = AsyncMock(return_value={
        "agent_id": onboarded_uuid,
        "display_agent_id": first_data.get("agent_id"),
    })

    with patch.object(resolution_mod, "get_cache", return_value=mock_redis), \
         patch.object(resolution_mod, "get_redis", return_value=mock_raw_redis), \
         patch.object(resolution_mod, "get_db", return_value=mock_db), \
         patch.object(resolution_mod, "_agent_exists_in_postgres", AsyncMock(return_value=True)), \
         patch.object(resolution_mod, "_get_agent_label", AsyncMock(return_value="TokenAgent")), \
         patch.object(resolution_mod, "_get_agent_status", AsyncMock(return_value="active")), \
         patch.object(resolution_mod, "_soft_verify_trajectory", AsyncMock(return_value={"verified": True})):
        second = await handle_onboard_v2({
            "continuity_token": token,
        })
        second_data = parse_result(second)

    assert second_data["success"] is True
    assert second_data["uuid"] == onboarded_uuid, (
        "Passing continuity_token must resolve to the original UUID; "
        f"got {second_data['uuid']!r}"
    )
```

*Note to implementer*: The exact mocking surface (`get_cache` vs `get_redis_cache`, `tests.helpers.parse_result`, etc.) mirrors `test_identity_handlers.py`. If imports differ, sync the patch targets to whatever that file uses. The assertion is the contract; the plumbing is environment-dependent.

- [ ] **Step 3: Run — expect green (or surface a real regression)**

```bash
pytest tests/test_no_fingerprint_inheritance.py::test_continuity_token_roundtrip_preserves_uuid -v
```

Expected: **PASS**. The continuity_token path was not touched by Tasks 1–7; this test should pass immediately.

If it fails: (a) fix mocking to match actual imports, OR (b) if the failure is a real UUID-preservation regression, **stop and investigate** — the severance may have accidentally disturbed the token path. Do not continue to Task 9 until this is green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_no_fingerprint_inheritance.py
git commit -m "test(identity): continuity_token round-trip preserves UUID"
```

---

## Task 9: Scan and update existing tests that asserted the old behavior

**Files:**
- Possibly modify: `tests/test_identity_handlers.py`, `tests/test_thread_identity.py`, any test found by scan.

- [ ] **Step 1: Scan for tests depending on old behavior**

```bash
grep -rn "predecessor_uuid" tests/
grep -rn '"predecessor"' tests/
grep -rn "Inherited EISV" tests/
grep -rn "Your state was inherited" tests/
```

For each match, open the test and decide:

- If the test **asserts** that `result["predecessor"]` IS populated after a fingerprint match + `resume=False` with no explicit `parent_agent_id`, **update the assertion** to `assert "predecessor" not in result` (or equivalent).
- If the test asserts `predecessor` populated when the caller **explicitly passes `parent_agent_id`**, leave it — that path still works.
- If the test checks the note text, update to `"Lineage record only; no state was inherited."`.

- [ ] **Step 2: Run the full identity test suite**

```bash
pytest tests/test_identity_handlers.py tests/test_identity_session.py tests/test_identity_core.py \
       tests/test_identity_continuity.py tests/test_identity_payloads.py tests/test_thread_identity.py \
       tests/test_sticky_identity.py tests/test_no_fingerprint_inheritance.py -v
```

Expected: all pass. If a test fails on the old-inheritance assumption, fix it per Step 1.

- [ ] **Step 3: Commit (one commit per test file updated, or a single commit if ≤2 edits)**

```bash
git add tests/test_identity_handlers.py  # or whichever files
git commit -m "test(identity): update assertions for no-auto-lineage contract

After the sever-fingerprint-inheritance change, predecessor is only
populated on explicit parent_agent_id from the caller; tests that
previously expected auto-linking have been updated."
```

---

## Task 10: Full test suite + verification

- [ ] **Step 1: Run the whole suite**

```bash
cd /Users/cirwel/projects/unitares
pytest -x -q
```

Expected: all tests pass. `-x` stops on first failure so you can triage quickly.

If a test fails that is **not** in the identity/lineage area: investigate. It may be unrelated to this change, in which case note it and proceed (a pre-existing failure), or it may be a subtle coupling (e.g., a test that implicitly relied on stale `monitors` state from fingerprint matches). In the latter case, triage and fix in this task.

- [ ] **Step 2: Run the Watcher to confirm no new findings in the touched files**

```bash
python3 agents/watcher/agent.py --scan --paths \
  src/agent_lifecycle.py \
  src/mcp_handlers/identity/resolution.py \
  src/mcp_handlers/identity/handlers.py \
  src/services/identity_payloads.py
```

Expected: no new high- or medium-severity findings attributable to this change. (The pre-existing findings in other files — e.g., `middleware/identity_step.py`, `agent_metadata_model.py` — are out of scope and should be left for their own tickets.)

- [ ] **Step 3: Sanity-check the onboard response shape manually**

If a local server is available:

```bash
python3 -c "
import asyncio
from src.mcp_handlers.identity.handlers import handle_onboard_v2
result = asyncio.run(handle_onboard_v2({'client_session_id':'manual-check', 'name':'TestAgent'}))
print(result)
"
```

Expected: `is_new: true`, NO `predecessor` field in response (assuming no explicit `parent_agent_id` was passed). `session_resolution_source` may still be populated for diagnostics.

If `predecessor` still appears, something leaked — trace back through Tasks 4–7.

- [ ] **Step 4: No commit (verification only)**

---

## Task 11: Push branch and open PR

- [ ] **Step 1: Push**

```bash
cd /Users/cirwel/projects/unitares   # or worktree
git push -u origin sever-fingerprint-eisv-inheritance
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "Sever fingerprint-based EISV inheritance" --body "$(cat <<'EOF'
## Summary

- Stop silent transplant of predecessor `GovernanceState` onto new agents (deletes the \`else\` branch in \`agent_lifecycle.get_or_create_monitor\`).
- Stop auto-claiming lineage on fingerprint match when \`resume=False\` (PATH 1 Redis hit, PATH 2 PostgreSQL hit in \`resolve_session_identity\`).
- Remove now-unreachable dormant block in the onboard handler.
- Update the onboard response note to reflect honest semantics.

Lineage via \`parent_agent_id\` now records *who came before* without transplanting state. Continuity of a single agent flows through the explicit \`continuity_token\` path, as already documented in the governance-lifecycle skill.

Spec: \`docs/specs/2026-04-16-sever-fingerprint-eisv-inheritance-design.md\`
Plan: \`docs/plans/2026-04-16-sever-fingerprint-eisv-inheritance.md\`

## Test plan

- [x] New \`tests/test_no_fingerprint_inheritance.py\` covers:
  - State transplant is gone
  - PATH 1 (Redis) does not set \`predecessor_uuid\` on \`resume=False\`
  - PATH 2 (PG)   does not set \`predecessor_uuid\` on \`resume=False\`
  - Explicit \`parent_agent_id\` records lineage without state transplant
  - \`continuity_token\` round-trip preserves UUID
- [x] Existing identity test suite passes (updated assertions where they pinned on the old auto-lineage contract)
- [x] Full \`pytest -x -q\` passes
- [x] Watcher scan on touched files shows no new findings

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Report URL back to the user**

---

## Self-Review Notes

- Spec coverage: each of Goals 1–4 maps to one or more tasks:
  - Goal 1 (no implicit state adoption) → Tasks 1, 2, 6
  - Goal 2 (lineage explicit-only) → Tasks 3, 4
  - Goal 3 (continuity_token unchanged) → Task 8
  - Goal 4 (test coverage) → Tasks 1, 3, 6, 8
- Non-goals are respected: no DB migration, no new API surface, no `force_new`/`fork_with_state` introduced.
- All code snippets show actual code, not placeholders. Commands are concrete. Expected outputs are concrete.
- Identifier consistency: `_predecessor_uuid`, `parent_agent_id`, `result["predecessor_uuid"]`, `result["predecessor"]` — used consistently with their exact spellings throughout.
- Risks (R2, R3 in spec) are implicitly covered: fresh-workspace behavior change is tested by Task 3; consumer drift is addressed by Task 7 (note update) and Task 9 (test scan).
