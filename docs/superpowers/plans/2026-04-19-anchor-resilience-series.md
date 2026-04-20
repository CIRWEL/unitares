# Anchor Resilience Series — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent and detect rotation-induced resident forks. Three independent, ship-separately PRs: (1) server-side resident-fork detector that alarms in seconds instead of hours, (2) committed rotation-secrets script that replaces the anchor-wiping runbook with the surgical variant, (3) opt-in SDK flag `refuse_fresh_onboard=True` for residents so silent fresh-onboard becomes impossible.

**Architecture:** The adversarial council reviewer named the unasked question: *the invariant is "a resident role should never have two active UUIDs" — a fleet-state problem, not a rotation/filesystem problem.* Phase 1 encodes that invariant in server code by escalating the already-present label-collision detection (`persistence.py:383-386`) into a WARNING log + `broadcast_event('resident_fork_detected', ...)`. Phase 2 makes the rotation runbook a committed, testable script. Phase 3 adds a per-instance opt-in client-side guard on the three SDK-using residents (Vigil, Sentinel, Watcher); Steward is excluded by construction because it does not inherit `GovernanceAgent`. Ephemeral agents are untouched.

**Tech Stack:** Python 3.12, PostgreSQL@17, `core.agents` table, `src/broadcaster.py` WebSocket broadcaster, `unitares_sdk.GovernanceAgent` base class, pytest-asyncio, bash.

**Incident references:**
- 2026-04-19 secret rotation wiped `~/.unitares/anchors/` → Watcher `907e3195` → ghost `7bf970d4`, Steward `9a6681ec` → ghost `62f24e09`. Vigil and Sentinel hand-restored, Watcher + Steward sat broken ~15 hours. See `memory/project_identity-audit-2026-04-19.md` ("Rotation-induced resident forks").
- Existing evidence: `core.agents` today still has `Watcher` (empty tags) AND `Watcher_7bf970d4` (`persistent` tag) both active — the ghost survived because the SDK stamped `persistent` on it at `agents/sdk/src/unitares_sdk/agent.py:208-213`.

**Out of scope (follow-ups):**
- Auto-archiving the ghost `7bf970d4` / rebuilding the OG's tag set — data hygiene, not this plan.
- Residents registry / DB-backed `residents` table — council rejected (DB is already the registry via `core.agents`; duplicating creates drift).
- File-per-instance identity redesign — explicitly shelved 2026-04-19, 10-14 week migration.

**Phase independence:** Each phase ships as its own PR. Phase 1 is the highest-leverage and independent; ship it first. Phase 2 is a 50-line shell script with a smoke test. Phase 3 touches three residents but each wire-up is trivial after the SDK flag lands.

---

# Phase 1 — Resident-Fork Detector

**Subsystem:** `src/mcp_handlers/identity/persistence.py` + `src/broadcaster.py`

**What it does:** When the onboard handler detects a label collision with an EXISTING agent that has the `persistent` tag, emit a WARNING log and a `broadcast_event('resident_fork_detected', ...)` alongside the existing silent-rename behavior. Dashboards (WebSocket clients) and Discord bridge subscribers see it on next event. The rename behavior itself is preserved — the fork still completes (can't break the onboard path) but it announces itself.

**Files:**
- Modify: `src/mcp_handlers/identity/persistence.py` (around line 383-386)
- Create: `tests/test_resident_fork_detector.py`

## Task 1.1: Write the failing test

**Files:**
- Create: `tests/test_resident_fork_detector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resident_fork_detector.py
"""Resident-fork detector: label collision on persistent-tagged agent emits event."""
from unittest.mock import AsyncMock, patch

import pytest

from src.mcp_handlers.identity import persistence


@pytest.mark.asyncio
async def test_label_collision_on_persistent_agent_emits_event():
    """When fresh onboard collides with a persistent-tagged existing agent,
    broadcaster should receive resident_fork_detected with both UUIDs."""
    existing_uuid = "907e3195-c649-49db-b753-1edc1a105f33"
    new_uuid = "7bf970d4-5713-4184-a6f8-58e798275f3f"
    label = "Watcher"

    mock_broadcaster = AsyncMock()
    mock_db = AsyncMock()
    mock_db.get_identity.return_value = None
    mock_db.update_agent_fields.return_value = True

    with patch.object(persistence, "_find_agent_by_label",
                      AsyncMock(return_value=existing_uuid)), \
         patch.object(persistence, "_agent_has_tag",
                      AsyncMock(return_value=True)), \
         patch.object(persistence, "get_db", return_value=mock_db), \
         patch.object(persistence, "_broadcaster", return_value=mock_broadcaster):

        await persistence.set_agent_label(new_uuid, label, session_key="sk")

    mock_broadcaster.broadcast_event.assert_called_once()
    call = mock_broadcaster.broadcast_event.call_args
    assert call.kwargs["event_type"] == "resident_fork_detected"
    assert call.kwargs["agent_id"] == new_uuid
    payload = call.kwargs["payload"]
    assert payload["existing_agent_id"] == existing_uuid
    assert payload["label"] == label
    assert payload["new_label"] == f"Watcher_{new_uuid[:8]}"


@pytest.mark.asyncio
async def test_label_collision_on_non_persistent_agent_no_event():
    """Collision with a non-persistent existing agent is still silently renamed
    (no change from current behavior for ephemerals)."""
    mock_broadcaster = AsyncMock()
    mock_db = AsyncMock()
    mock_db.get_identity.return_value = None
    mock_db.update_agent_fields.return_value = True

    with patch.object(persistence, "_find_agent_by_label",
                      AsyncMock(return_value="some-other-uuid")), \
         patch.object(persistence, "_agent_has_tag",
                      AsyncMock(return_value=False)), \
         patch.object(persistence, "get_db", return_value=mock_db), \
         patch.object(persistence, "_broadcaster", return_value=mock_broadcaster):

        await persistence.set_agent_label(
            "new-uuid-here", "temp-ephemeral", session_key="sk",
        )

    mock_broadcaster.broadcast_event.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_resident_fork_detector.py -v --no-cov`

Expected: FAIL. The module lacks `_agent_has_tag` and `_broadcaster` helpers, and `set_agent_label` does not emit events. Error will be `AttributeError` or `AssertionError: Expected 'broadcast_event' to have been called once`.

## Task 1.2: Add the `_agent_has_tag` helper

**Files:**
- Modify: `src/mcp_handlers/identity/persistence.py`

- [ ] **Step 1: Read the current imports and helpers section**

Run: `sed -n '1,40p' src/mcp_handlers/identity/persistence.py`

Locate where `_find_agent_by_label` is defined. Add `_agent_has_tag` immediately after it.

- [ ] **Step 2: Add the helper**

```python
async def _agent_has_tag(agent_uuid: str, tag: str) -> bool:
    """Return True iff the agent exists in core.agents with `tag` in its tags[]."""
    try:
        db = get_db()
        row = await db.fetchrow(
            "SELECT tags FROM core.agents WHERE id = $1",
            agent_uuid,
        )
    except Exception as e:
        logger.warning(f"_agent_has_tag: DB probe failed for {agent_uuid[:8]}: {e}")
        return False
    if not row or not row.get("tags"):
        return False
    return tag in row["tags"]
```

Notes: `get_db()` is already imported in this module. `db.fetchrow` exists on the backend adapter (see usages in `persistence.py` and `src/db.py`). If the adapter name is different in this codebase, match the existing pattern used by `_find_agent_by_label` verbatim — the point is a read against `core.agents`.

## Task 1.3: Add the broadcaster accessor

**Files:**
- Modify: `src/mcp_handlers/identity/persistence.py`

- [ ] **Step 1: Add the module-level accessor**

Paste immediately after `_agent_has_tag`:

```python
def _broadcaster():
    """Lazy accessor for the shared broadcaster. Returns None if broadcaster
    is not installed (e.g., in unit tests without a live server)."""
    try:
        from src.broadcaster import broadcaster as _b
    except ImportError:
        return None
    return _b
```

Rationale: `src/broadcaster.py` exposes a module-level `broadcaster` singleton. Importing lazily keeps `persistence.py` testable without the full server boot.

## Task 1.4: Emit the event on collision

**Files:**
- Modify: `src/mcp_handlers/identity/persistence.py:381-386`

- [ ] **Step 1: Replace the silent-rename block**

Find the existing block (around line 381-386):

```python
        # Check for duplicate labels
        existing = await _find_agent_by_label(label)
        if existing and existing != agent_uuid:
            # Append UUID suffix to make unique
            label = f"{label}_{agent_uuid[:8]}"
            logger.info(f"Label collision, using: {label}")
```

Replace with:

```python
        # Check for duplicate labels
        existing = await _find_agent_by_label(label)
        if existing and existing != agent_uuid:
            new_label = f"{label}_{agent_uuid[:8]}"
            existing_is_resident = await _agent_has_tag(existing, "persistent")
            if existing_is_resident:
                # Resident-fork detected: a persistent-tagged agent already
                # owns this label. Emit a governance event so dashboards and
                # Discord surface the anomaly within one broadcast cycle. The
                # rename itself still happens (can't block onboard) — the
                # event is the signal.
                logger.warning(
                    "[RESIDENT_FORK] label collision: existing agent %s is persistent "
                    "but onboard minted %s with same label '%s' — renaming new agent "
                    "to '%s'. This is the silent-fork class (rotation wipe, anchor "
                    "corruption, or misconfigured bootstrap). See memory: "
                    "project_identity-audit-2026-04-19.md.",
                    existing[:8], agent_uuid[:8], label, new_label,
                )
                b = _broadcaster()
                if b is not None:
                    try:
                        await b.broadcast_event(
                            event_type="resident_fork_detected",
                            agent_id=agent_uuid,
                            payload={
                                "existing_agent_id": existing,
                                "label": label,
                                "new_label": new_label,
                            },
                        )
                    except Exception as e:
                        logger.warning(
                            f"[RESIDENT_FORK] broadcast_event failed: {e}"
                        )
            else:
                logger.info(f"Label collision, using: {new_label}")
            label = new_label
```

- [ ] **Step 2: Run the unit tests to verify they pass**

Run: `pytest tests/test_resident_fork_detector.py -v --no-cov`

Expected: 2 passed.

## Task 1.5: End-to-end regression test

**Files:**
- Modify: `tests/test_resident_fork_detector.py`

- [ ] **Step 1: Add an integration test that exercises the full onboard handler**

Append to the test file:

```python
@pytest.mark.asyncio
async def test_onboard_after_anchor_wipe_fires_event():
    """Integration: simulate a resident doing fresh onboard with its label
    already held by a persistent-tagged agent. Event must fire."""
    from src.mcp_handlers.identity import handlers as onboard_handlers

    # Seed an existing persistent Watcher
    db = get_db()
    existing_uuid = "00000000-0000-0000-0000-000000000aaa"
    await db.execute(
        "INSERT INTO core.agents (id, api_key, status, label, tags) "
        "VALUES ($1, $2, 'active', 'Watcher', ARRAY['persistent']) "
        "ON CONFLICT (id) DO UPDATE SET label='Watcher', tags=ARRAY['persistent'], status='active'",
        existing_uuid, "testkey",
    )

    captured = []

    class _StubBroadcaster:
        async def broadcast_event(self, **kwargs):
            captured.append(kwargs)

    with patch.object(persistence, "_broadcaster",
                      return_value=_StubBroadcaster()):
        await onboard_handlers.handle_onboard_v2({
            "name": "Watcher",
            "client_session_id": "test-session-fork",
        })

    fork_events = [c for c in captured if c["event_type"] == "resident_fork_detected"]
    assert len(fork_events) == 1
    assert fork_events[0]["payload"]["label"] == "Watcher"
    assert fork_events[0]["payload"]["existing_agent_id"] == existing_uuid

    # Cleanup
    await db.execute("DELETE FROM core.agents WHERE id = $1", existing_uuid)
```

Notes: This test requires a live Postgres. It's fine to mark it `@pytest.mark.integration` if the repo distinguishes unit vs integration tests. Check existing `tests/test_identity_*.py` for the convention.

- [ ] **Step 2: Run it**

Run: `pytest tests/test_resident_fork_detector.py::test_onboard_after_anchor_wipe_fires_event -v --no-cov`

Expected: PASS (requires live Postgres).

## Task 1.6: Commit Phase 1

- [ ] **Step 1: Run the test-cache**

Run: `./scripts/dev/test-cache.sh`

Expected: all green. If failures exist pre-existing on this branch, verify against master first per `feedback_verify-baseline-on-base-branch.md`.

- [ ] **Step 2: Commit**

```bash
git add tests/test_resident_fork_detector.py src/mcp_handlers/identity/persistence.py
git commit -m "feat(identity): resident-fork detector emits event on label collision with persistent agent

The onboard handler already detected label collisions and silently renamed
the new agent (Watcher -> Watcher_7bf970d4). That absorbed rotation-induced
silent forks without any signal. Detection took ~15 hours via human
inspection on 2026-04-19.

Now: when the existing label-holder carries the 'persistent' tag, log at
WARNING and emit broadcast_event('resident_fork_detected', ...). Dashboards
and Discord bridge surface it within one broadcast cycle. Rename behavior
preserved (cannot block onboard).

Addresses the detection-gap blindspot of the 2026-04-19 anchor-resilience
council review."
```

- [ ] **Step 3: Ship Phase 1**

```bash
./scripts/dev/ship.sh
```

Expected: worktree + PR (runtime code change). Phase 1 is self-contained; Phase 2 and Phase 3 can proceed in parallel worktrees.

---

# Phase 2 — Commit `rotate-secrets.sh`

**Subsystem:** `scripts/ops/`

**What it does:** Converts the rotation runbook from English prose into an executable script. Rotates `UNITARES_CONTINUITY_TOKEN_SECRET` + `UNITARES_HTTP_API_TOKEN` in the 9 LaunchAgent plists, then — critically — uses the **surgical variant** on `~/.unitares/anchors/*.json`: drops `continuity_token` and `client_session_id` but preserves `agent_uuid`. On next resident cycle, PATH 0 UUID-direct resume re-mints a token against the new secret.

**Files:**
- Create: `scripts/ops/rotate-secrets.sh`
- Create: `tests/test_rotate_secrets_script.py`
- Modify: `memory/project_identity-audit-2026-04-19.md` (in-repo reference, if that doc is tracked — otherwise this is a follow-up in Kenny's memory dir)

## Task 2.1: Write the script skeleton

**Files:**
- Create: `scripts/ops/rotate-secrets.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# rotate-secrets.sh — rotate UNITARES bearer-token secrets.
#
# Rotation steps:
#   1. Generate new secret values (32 bytes, base64url).
#   2. Write them into the 9 LaunchAgent plists that reference them.
#   3. Surgical-strip each anchor in ~/.unitares/anchors/:
#        drop continuity_token + client_session_id, keep agent_uuid.
#   4. Bounce the governance-mcp launchd service.
#
# Residents wake on their normal cadence and resume via PATH 0 UUID-direct
# identity lookup (shipped 2026-04-17). They do NOT fresh-onboard and do
# NOT get new UUIDs.
#
# Why this exists: on 2026-04-19 the ad-hoc rotation runbook wiped the
# anchors/ dir wholesale. Every resident then fresh-onboarded with a new
# UUID. See memory/project_identity-audit-2026-04-19.md and the
# anchor-resilience series plan.

set -euo pipefail

ANCHOR_DIR="${HOME}/.unitares/anchors"
LAUNCHAGENTS_DIR="${HOME}/Library/LaunchAgents"
GOVERNANCE_PLIST="${LAUNCHAGENTS_DIR}/com.unitares.governance-mcp.plist"
DATE_STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${HOME}/.unitares/rotation-backup-${DATE_STAMP}"

log()  { printf '\033[1;34m[rotate]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[rotate]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[rotate]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Pre-flight ---
[[ -d "${ANCHOR_DIR}" ]] || die "anchor dir missing: ${ANCHOR_DIR}"
[[ -f "${GOVERNANCE_PLIST}" ]] || die "governance plist missing: ${GOVERNANCE_PLIST}"

# Every anchor must already have an agent_uuid — if any don't, abort loudly;
# operator needs to re-bootstrap that resident explicitly.
missing=()
for f in "${ANCHOR_DIR}"/*.json; do
  [[ -e "$f" ]] || continue
  if ! python3 -c "
import json, sys
d = json.load(open('$f'))
sys.exit(0 if d.get('agent_uuid') else 1)
" 2>/dev/null; then
    missing+=("$f")
  fi
done
if (( ${#missing[@]} > 0 )); then
  die "anchors missing agent_uuid (cannot do surgical rotation): ${missing[*]}"
fi

log "backup dir: ${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"
cp -a "${ANCHOR_DIR}" "${BACKUP_DIR}/anchors"

# --- Generate new secrets ---
new_continuity_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
new_http_api_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# --- Write into plists (all 9 com.unitares.*.plist files) ---
log "rotating secrets in LaunchAgents plists..."
for plist in "${LAUNCHAGENTS_DIR}"/com.unitares.*.plist; do
  [[ -e "$plist" ]] || continue
  cp "$plist" "${BACKUP_DIR}/$(basename "$plist")"
  /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:UNITARES_CONTINUITY_TOKEN_SECRET ${new_continuity_secret}" "$plist" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:UNITARES_HTTP_API_TOKEN ${new_http_api_token}" "$plist" 2>/dev/null || true
done

# --- Surgical anchor strip: drop continuity_token + client_session_id,
#     keep agent_uuid. ---
log "surgical anchor strip..."
for f in "${ANCHOR_DIR}"/*.json; do
  [[ -e "$f" ]] || continue
  python3 - "$f" <<'PY'
import json, os, sys, tempfile
path = sys.argv[1]
with open(path) as fh:
    d = json.load(fh)
uuid = d.get("agent_uuid")
if not uuid:
    sys.exit(f"refusing to strip {path}: no agent_uuid")
new = {"agent_uuid": uuid}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as fh:
    json.dump(new, fh)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
done

# --- Bounce governance-mcp so it picks up the new secrets. ---
log "restarting governance-mcp..."
launchctl unload "${GOVERNANCE_PLIST}" 2>/dev/null || true
launchctl load   "${GOVERNANCE_PLIST}"

log "rotation complete. backup at ${BACKUP_DIR}"
log "residents will re-auth via PATH 0 on their next cycle."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/ops/rotate-secrets.sh
```

## Task 2.2: Write a smoke test

**Files:**
- Create: `tests/test_rotate_secrets_script.py`

- [ ] **Step 1: Smoke test the surgical-anchor behavior (no launchctl, no plist touch)**

```python
"""rotate-secrets.sh smoke test — verifies the surgical anchor behavior
preserves agent_uuid while stripping tokens."""
import json
import subprocess
import tempfile
from pathlib import Path


def test_surgical_strip_preserves_uuid(tmp_path):
    """Feed a realistic anchor through the Python inline-strip block
    and verify shape."""
    anchor = tmp_path / "watcher.json"
    anchor.write_text(json.dumps({
        "client_session_id": "agent-907e3195-c64",
        "continuity_token": "v1.somelongtoken.sig",
        "agent_uuid": "907e3195-c649-49db-b753-1edc1a105f33",
    }))

    # The script's surgical block, verbatim.
    script = f"""
import json, os, sys, tempfile
path = {str(anchor)!r}
with open(path) as fh:
    d = json.load(fh)
uuid = d.get("agent_uuid")
if not uuid:
    sys.exit("no uuid")
new = {{"agent_uuid": uuid}}
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as fh:
    json.dump(new, fh)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
"""
    subprocess.check_call(["python3", "-c", script])

    result = json.loads(anchor.read_text())
    assert result == {"agent_uuid": "907e3195-c649-49db-b753-1edc1a105f33"}
    assert oct(anchor.stat().st_mode)[-3:] == "600"


def test_refuses_anchor_without_uuid(tmp_path):
    """Script must die if anchor lacks agent_uuid — operator re-bootstraps."""
    anchor = tmp_path / "broken.json"
    anchor.write_text(json.dumps({"client_session_id": "sk"}))

    script = f"""
import json, sys
d = json.load(open({str(anchor)!r}))
sys.exit(0 if d.get("agent_uuid") else 1)
"""
    result = subprocess.run(["python3", "-c", script])
    assert result.returncode == 1  # script's preflight loop would abort
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_rotate_secrets_script.py -v --no-cov`

Expected: 2 passed.

## Task 2.3: Point memory at the script

**Files:**
- The memory file lives in `~/.claude/projects/-Users-cirwel/memory/project_identity-audit-2026-04-19.md` — outside the unitares repo. Kenny updates memory himself.

- [ ] **Step 1: Note the follow-up**

Do not edit memory from this plan. Instead, the commit message in Task 2.4 should reference the memory-update requirement so Kenny sees it during PR review.

## Task 2.4: Commit Phase 2

- [ ] **Step 1: Run test-cache**

Run: `./scripts/dev/test-cache.sh`

- [ ] **Step 2: Commit**

```bash
git add scripts/ops/rotate-secrets.sh tests/test_rotate_secrets_script.py
git commit -m "ops: committed rotate-secrets.sh with surgical anchor strip

Replaces the ad-hoc rotation runbook whose 2026-04-19 wipe-based recipe
forked every resident. New script:
  - generates fresh UNITARES_CONTINUITY_TOKEN_SECRET + UNITARES_HTTP_API_TOKEN
  - rewrites all 9 com.unitares.*.plist LaunchAgents
  - surgical-strips ~/.unitares/anchors/*.json: drops continuity_token and
    client_session_id, keeps agent_uuid
  - refuses to run if any anchor lacks agent_uuid (operator re-bootstraps)
  - backs up everything under ~/.unitares/rotation-backup-<timestamp>/

Residents wake and resume via PATH 0 UUID-direct. No fresh-onboard, no
fork.

Follow-up (memory): update project_identity-audit-2026-04-19.md
'Rotation-induced resident forks' section to link at scripts/ops/rotate-secrets.sh
instead of describing the recipe in prose."
```

- [ ] **Step 3: Ship**

```bash
./scripts/dev/ship.sh
```

---

# Phase 3 — `refuse_fresh_onboard` SDK opt-in

**Subsystem:** `agents/sdk/src/unitares_sdk/agent.py` + resident wire-ups

**What it does:** Adds a `refuse_fresh_onboard: bool = False` parameter to `GovernanceAgent.__init__`. When True, `_ensure_identity` raises `IdentityBootstrapRefused` if `self.agent_uuid` is falsy after `_load_session()`. Bootstrap path is an explicit `UNITARES_FIRST_RUN=1` env var. Vigil, Sentinel, Watcher wire-up sets the flag True. Steward is in `unitares-pi-plugin` and does not inherit `GovernanceAgent` — excluded by construction.

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (add flag + guard at lines ~80-210)
- Modify: `agents/sdk/src/unitares_sdk/errors.py` (add `IdentityBootstrapRefused`)
- Modify: `agents/vigil/agent.py:275`, `agents/sentinel/agent.py:426` (flag True)
- Modify: `agents/watcher/agent.py` (its own identity-resolution path, analogous guard)
- Create: `agents/sdk/tests/test_refuse_fresh_onboard.py`

## Task 3.1: Add the exception class

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/errors.py`

- [ ] **Step 1: Read the file**

Run: `cat agents/sdk/src/unitares_sdk/errors.py`

- [ ] **Step 2: Append the new exception**

```python
class IdentityBootstrapRefused(Exception):
    """Raised when a resident agent's anchor is missing and the agent was
    configured with refuse_fresh_onboard=True (the default for Vigil,
    Sentinel, Watcher).

    Fix: either restore the anchor from a rotation backup, or explicitly
    bootstrap a new identity by running the agent once with the
    UNITARES_FIRST_RUN=1 environment variable set. Never silently swap
    identities."""
```

## Task 3.2: Write the failing SDK test

**Files:**
- Create: `agents/sdk/tests/test_refuse_fresh_onboard.py`

- [ ] **Step 1: Write tests for all three states**

```python
"""refuse_fresh_onboard guard: residents refuse silent fresh-onboard."""
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from unitares_sdk.agent import GovernanceAgent
from unitares_sdk.errors import IdentityBootstrapRefused


class _Dummy(GovernanceAgent):
    async def run_cycle(self, client):
        return None


@pytest.mark.asyncio
async def test_refuse_raises_when_no_anchor(tmp_path, monkeypatch):
    """No anchor file + refuse=True + no FIRST_RUN env => raises."""
    anchor = tmp_path / "watcher.json"
    a = _Dummy(
        name="Watcher",
        mcp_url="stdio:test",
        session_file=anchor,
        refuse_fresh_onboard=True,
    )
    monkeypatch.delenv("UNITARES_FIRST_RUN", raising=False)
    client = AsyncMock()
    with pytest.raises(IdentityBootstrapRefused):
        await a._ensure_identity(client)
    client.onboard.assert_not_called()


@pytest.mark.asyncio
async def test_refuse_allows_when_first_run_set(tmp_path, monkeypatch):
    """No anchor file + refuse=True + FIRST_RUN=1 => allows onboard."""
    anchor = tmp_path / "watcher.json"
    a = _Dummy(
        name="Watcher",
        mcp_url="stdio:test",
        session_file=anchor,
        refuse_fresh_onboard=True,
    )
    monkeypatch.setenv("UNITARES_FIRST_RUN", "1")
    client = AsyncMock()
    client.onboard = AsyncMock()
    client.agent_uuid = "abc123"
    client.client_session_id = "s"
    client.continuity_token = "t"
    await a._ensure_identity(client)
    client.onboard.assert_called_once()


@pytest.mark.asyncio
async def test_refuse_resumes_normally_when_anchor_present(tmp_path):
    """Anchor present => UUID-direct resume, flag irrelevant."""
    anchor = tmp_path / "watcher.json"
    anchor.write_text('{"agent_uuid": "907e3195-..."}')
    a = _Dummy(
        name="Watcher",
        mcp_url="stdio:test",
        session_file=anchor,
        refuse_fresh_onboard=True,
    )
    client = AsyncMock()
    client.identity = AsyncMock()
    client.agent_uuid = "907e3195-..."
    client.client_session_id = "s"
    client.continuity_token = "t"
    await a._ensure_identity(client)
    client.identity.assert_called_once()
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest agents/sdk/tests/test_refuse_fresh_onboard.py -v --no-cov`

Expected: FAIL. `GovernanceAgent.__init__` does not accept `refuse_fresh_onboard`.

## Task 3.3: Add the flag and the guard

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py`

- [ ] **Step 1: Add the parameter to `__init__`**

Locate `def __init__` around line 80. Add after `persistent`:

```python
        refuse_fresh_onboard: bool = False,
```

And in the docstring / attributes block:

```python
        # Residents (Vigil, Sentinel, Watcher) set this True. When True,
        # _ensure_identity refuses to fresh-onboard if the anchor is
        # missing; the operator must set UNITARES_FIRST_RUN=1 to bootstrap
        # a new identity. Prevents the 2026-04-19 rotation-wipe silent-fork
        # class. See docs/superpowers/plans/2026-04-19-anchor-resilience-series.md
        self.refuse_fresh_onboard = refuse_fresh_onboard
```

- [ ] **Step 2: Guard the fresh-onboard path in `_ensure_identity`**

Locate `_ensure_identity` (around line 173-206). Find the "First run — onboard" comment (around line 197) and insert the guard immediately before the `await client.onboard(...)` call:

```python
        # First run — onboard, get a UUID, save it
        if self.refuse_fresh_onboard and os.environ.get("UNITARES_FIRST_RUN") != "1":
            from .errors import IdentityBootstrapRefused
            raise IdentityBootstrapRefused(
                f"{self.name}: anchor missing at {self.session_file}, and "
                "refuse_fresh_onboard=True. Either restore the anchor from a "
                "rotation backup, or run this agent once with UNITARES_FIRST_RUN=1 "
                "to explicitly bootstrap a new identity. Never silent-swap."
            )

        onboard_kwargs: dict[str, Any] = {}
```

(The `onboard_kwargs` line already exists — you're inserting above it.)

Make sure `import os` is at the top of the file (it almost certainly is; grep to confirm).

- [ ] **Step 3: Run the SDK tests**

Run: `pytest agents/sdk/tests/test_refuse_fresh_onboard.py -v --no-cov`

Expected: 3 passed.

## Task 3.4: Wire up Vigil

**Files:**
- Modify: `agents/vigil/agent.py:275`

- [ ] **Step 1: Set the flag in Vigil's super().__init__()**

Find the `super().__init__(...)` block around line 268-276. Change:

```python
        super().__init__(
            name=label,
            mcp_url=mcp_url,
            session_file=SESSION_FILE,
            legacy_session_file=LEGACY_SESSION_FILE,
            state_dir=STATE_FILE.parent,
            timeout=30.0,
            persistent=True,
        )
```

To:

```python
        super().__init__(
            name=label,
            mcp_url=mcp_url,
            session_file=SESSION_FILE,
            legacy_session_file=LEGACY_SESSION_FILE,
            state_dir=STATE_FILE.parent,
            timeout=30.0,
            persistent=True,
            refuse_fresh_onboard=True,
        )
```

## Task 3.5: Wire up Sentinel

**Files:**
- Modify: `agents/sentinel/agent.py:426`

- [ ] **Step 1: Same one-line addition**

Locate `super().__init__(` around line 420-430 and add `refuse_fresh_onboard=True,` adjacent to `persistent=True,`.

## Task 3.6: Wire up Watcher

**Files:**
- Modify: `agents/watcher/agent.py` (resolve_identity function, around line 211-239)

Watcher does NOT inherit `GovernanceAgent` — it has its own three-step `resolve_identity`. Apply the same guard inline.

- [ ] **Step 1: Add the guard before Step 2 (fresh onboard)**

Locate lines 211-213:

```python
    # Step 2: Fresh onboard — only when nothing else works.
    try:
        client.onboard("Watcher", spawn_reason="resident_observer")
```

Replace with:

```python
    # Step 2: Fresh onboard — only when nothing else works.
    # Silent-fork guard (added 2026-04-19 anchor-resilience series): Watcher
    # is a resident; missing anchor + no UNITARES_FIRST_RUN means the
    # operator did not authorize a fresh identity. Refuse loudly rather
    # than silently forking.
    import os as _os
    if _os.environ.get("UNITARES_FIRST_RUN") != "1":
        log(
            "anchor missing and UNITARES_FIRST_RUN not set — refusing to fresh-onboard. "
            "Restore the anchor from a rotation backup, or set UNITARES_FIRST_RUN=1 "
            "to explicitly bootstrap a new Watcher identity.",
            "error",
        )
        _watcher_identity = None
        return
    try:
        client.onboard("Watcher", spawn_reason="resident_observer")
```

- [ ] **Step 2: Write a Watcher-specific test**

Append to `agents/watcher/tests/test_agent.py` or create `agents/watcher/tests/test_refuse_fresh_onboard.py`:

```python
def test_watcher_refuses_fresh_onboard_without_first_run(monkeypatch, tmp_path):
    """With no anchor and no UNITARES_FIRST_RUN, resolve_identity returns
    without calling client.onboard."""
    from agents.watcher import agent as watcher

    monkeypatch.delenv("UNITARES_FIRST_RUN", raising=False)
    monkeypatch.setattr(watcher, "_load_session", lambda: {})
    client = _MockClient()
    watcher.resolve_identity(client)

    assert client.onboard_calls == 0
    assert watcher._watcher_identity is None
```

where `_MockClient` is a small stub or imported helper matching existing tests.

- [ ] **Step 3: Run it**

Run: `pytest agents/watcher/tests/ -v --no-cov`

Expected: new test passes; existing tests still pass (they may need to set `UNITARES_FIRST_RUN=1` if they rely on fresh onboard).

## Task 3.7: Document the bootstrap procedure

**Files:**
- Modify: `agents/sdk/src/unitares_sdk/agent.py` (module docstring)

- [ ] **Step 1: Add a short note near the top**

Locate the module docstring (top of file). Add:

```python
# First-time resident bootstrap:
#   UNITARES_FIRST_RUN=1 python3 -m agents.vigil  # or sentinel, watcher
# This is the ONLY path that mints a new UUID for a resident with
# refuse_fresh_onboard=True. Every other path must resume the stored
# anchor UUID.
```

Do not add a new README or docs file — this is a runbook note, not documentation.

## Task 3.8: Commit Phase 3

- [ ] **Step 1: Run test-cache**

Run: `./scripts/dev/test-cache.sh`

- [ ] **Step 2: Commit**

```bash
git add agents/sdk/src/unitares_sdk/agent.py \
        agents/sdk/src/unitares_sdk/errors.py \
        agents/sdk/tests/test_refuse_fresh_onboard.py \
        agents/vigil/agent.py \
        agents/sentinel/agent.py \
        agents/watcher/agent.py \
        agents/watcher/tests/test_refuse_fresh_onboard.py
git commit -m "feat(sdk): refuse_fresh_onboard opt-in for residents

Adds refuse_fresh_onboard=True flag to GovernanceAgent and wires it into
Vigil, Sentinel, Watcher. When True, _ensure_identity raises
IdentityBootstrapRefused if the anchor is missing and UNITARES_FIRST_RUN
is not set.

Before: rotation wiped anchors and every resident silently fresh-onboarded
a new UUID. Detection took ~15 hours of inspection.

After: a wipe makes the resident refuse to start with an actionable error
message. Operator restores anchor or sets UNITARES_FIRST_RUN=1 to
authorize a new identity explicitly.

Steward does not inherit GovernanceAgent (it lives in unitares-pi-plugin)
and is excluded by construction. Ephemeral agents never set this flag."
```

- [ ] **Step 3: Ship**

```bash
./scripts/dev/ship.sh
```

---

# Self-Review

1. **Spec coverage:** Phase 1 addresses the detection gap (server-side event on collision). Phase 2 hardens the runbook (committed script, surgical variant). Phase 3 encodes the invariant in client code (refuse silent fork). All three council concerns covered; file-per-instance redesign explicitly out of scope.

2. **Placeholder scan:** No TBD / TODO / "implement later" / "add appropriate error handling". All code blocks concrete. Test code complete.

3. **Type consistency:** `IdentityBootstrapRefused` defined in Task 3.1, imported by tests in 3.2, raised in 3.3. `refuse_fresh_onboard` kwarg consistent across 3.3/3.4/3.5. `resident_fork_detected` event_type consistent between 1.4 and 1.1 test assertion.

**Known risk:** `db.fetchrow` API shape in Task 1.2 was stated from the pattern in `persistence.py`; executor should verify the exact adapter call by reading `_find_agent_by_label` in the same file before implementing.
