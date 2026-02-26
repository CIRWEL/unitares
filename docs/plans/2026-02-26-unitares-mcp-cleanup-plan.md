# UNITARES MCP Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce technical debt in the UNITARES MCP codebase — identity layer clarity, deprecated code removal, legacy branch cleanup — without breaking behavior.

**Architecture:** Incremental refactoring. Each phase is independently shippable. Tests must pass after every task. No big-bang rewrites.

**Tech Stack:** Python 3.12+, pytest, existing governance-mcp-v1 codebase

**Created:** February 26, 2026  
**Last Updated:** February 26, 2026  
**Status:** Complete (Phases 1–3)

---

## Execution Status (Feb 2026)

| Task | Status | Notes |
|------|--------|-------|
| 1.0 Fix broken import | ✅ Done | `get_bound_agent_id` → `identity_shared` |
| 1.1 Remove deprecated sync helpers | ✅ Done | `_derive_session_key` removed, admin migrated |
| 1.2 Terminology comments | ✅ Done | agent_id vs UUID clarified |
| 1.3 Legacy format branches | ❌ Cancelled | User cannot confirm no legacy data; branches kept for safety |
| 2.1 Identity spec refresh | ✅ Done | IDENTITY_REFACTOR_AGI_FORWARD updated |
| 3.1 Split lifecycle.py | ✅ Done | `lifecycle_stuck.py`, `lifecycle_resume.py` created |

---

## Prerequisites

- Run full test suite before starting: `pytest tests/ -v --tb=short`
- Baseline: 6,400+ tests, ~80% coverage
- Reference: `docs/archive/2026-02/specs/IDENTITY_REFACTOR_AGI_FORWARD.md` (direction, not current state)

---

## Phase 1: Low-Risk Cleanup (Est. 2–3 hours)

### Task 1.0: Fix Broken Import in mcp_server.py

**Context:** `mcp_server.py:941` imports `from mcp_handlers.identity import get_bound_agent_id` but `identity.py` does not exist. `get_bound_agent_id` lives in `identity_shared`.

**Files:**
- Modify: `src/mcp_server.py:941`

**Step 1: Fix import**

Change:
```python
from mcp_handlers.identity import get_bound_agent_id
```
To:
```python
from src.mcp_handlers.identity_shared import get_bound_agent_id
```

**Step 2: Verify**

```bash
python -c "from src.mcp_server import *" 2>/dev/null || python -c "import src.mcp_server"
```

**Step 3: Commit**

```bash
git add src/mcp_server.py
git commit -m "fix(mcp_server): correct get_bound_agent_id import (identity_shared not identity)"
```

---

### Task 1.1: Remove Deprecated Sync Session Key Helpers

**Context:** `identity_shared._get_session_key` and `identity_v2._derive_session_key` are deprecated. All callers should use `derive_session_key(signals, arguments)`.

**Files:**
- Modify: `src/mcp_handlers/identity_shared.py`
- Modify: `src/mcp_handlers/identity_v2.py`
- Modify: `src/mcp_handlers/admin.py` (if it uses `_derive_session_key`)
- Search: `grep -r "_get_session_key\|_derive_session_key" src/`

**Step 1: Find all callers**

```bash
cd governance-mcp-v1
grep -rn "_get_session_key\|_derive_session_key" src/
```

**Step 2: Migrate admin.py caller**

`admin.py:2214` — `handle_debug_request_context` is async. Replace:

```python
from .identity_v2 import _derive_session_key
# ...
session_key = context_session_key or _derive_session_key(arguments)
```

With:

```python
from .context import get_session_signals
from .identity_v2 import derive_session_key
# ...
signals = get_session_signals()
session_key = context_session_key or (await derive_session_key(signals, arguments or {}))
```

**Step 3: Remove _derive_session_key**

- Delete `_derive_session_key` from `identity_v2.py` (admin.py is the only caller; now migrated)

**Note:** `_get_session_key` in identity_shared.py is still used by `_get_identity_record_sync` (sync path). Keep it for now; add `# DEPRECATED: prefer derive_session_key for async callers` comment. Full migration would require making `get_bound_agent_id` async — deferred.

**Step 4: Run tests**

```bash
pytest tests/test_identity_v2_handlers.py tests/test_admin_handlers.py -v --tb=short
```

Expected: All pass.

**Step 5: Commit**

```bash
git add src/mcp_handlers/identity_shared.py src/mcp_handlers/identity_v2.py src/mcp_handlers/admin.py
git commit -m "refactor(identity): remove deprecated sync session key helpers

Migrate callers to derive_session_key(signals, arguments)."
```

---

### Task 1.2: Add Terminology Clarification Comments

**Context:** `agent_id` is overloaded (UUID vs model+date label). Add comments at key boundaries so future readers understand.

**Files:**
- Modify: `src/mcp_handlers/utils.py` (require_agent_id, get_bound_agent_id)
- Modify: `src/mcp_handlers/identity_v2.py` (resolve_session_identity return dict)
- Modify: `src/mcp_handlers/update_context.py` (UpdateContext.agent_id field)

**Step 1: Add docstring to require_agent_id**

In `utils.py`, update the docstring for `require_agent_id`:

```python
"""
CANONICAL ID CLARIFICATION:
- Session-bound identity is always UUID (36 chars, 4 hyphens)
- display_agent_id / agent_id in responses may be model+date (e.g. mcp_20260226)
- Internal maps (monitors, metadata) are keyed by UUID only
"""
```

**Step 2: Add comment to UpdateContext**

In `update_context.py`, at `agent_id` field:

```python
agent_id: str = ""  # Same as agent_uuid (UUID). Label/display in declared_agent_id.
```

**Step 3: Add comment to identity_v2 return dict**

In `resolve_session_identity` return blocks, add inline comment:

```python
"agent_id": agent_id,   # Human-readable (model+date). UUID for lookup is agent_uuid.
```

**Step 4: Run tests**

```bash
pytest tests/ -v --tb=line -q 2>/dev/null | tail -5
```

**Step 5: Commit**

```bash
git add src/mcp_handlers/utils.py src/mcp_handlers/update_context.py src/mcp_handlers/identity_v2.py
git commit -m "docs(identity): clarify agent_id vs UUID terminology"

```

---

### Task 1.3: Remove Legacy Format Branches (If Safe)

**Context:** Pre-v2.5.2 cached model+date format instead of UUID. Code has `is_uuid` branches.

**Prerequisite:** Confirm no Redis/Postgres data still has legacy format. If unsure, skip or add feature flag.

**Files:**
- Modify: `src/mcp_handlers/identity_v2.py` (PATH 1 Redis, PATH 2 Postgres)

**Step 1: Add migration check (optional)**

If legacy data might exist, add a one-time migration or log. Otherwise proceed.

**Step 2: Simplify Redis PATH 1**

Remove the `else` branch (lines ~321–328) that handles legacy format. Assume cached value is always UUID.

**Step 3: Simplify Postgres PATH 2**

Remove the `else` branch (lines ~416–422) for legacy format.

**Step 4: Run identity tests**

```bash
pytest tests/test_identity_v2_handlers.py tests/test_identity_v2_redis.py -v --tb=short
```

**Step 5: Commit**

```bash
git add src/mcp_handlers/identity_v2.py
git commit -m "refactor(identity): remove deprecated legacy format branches (pre-v2.5.2)"
```

---

## Phase 2: Identity Spec Refresh (Est. 1–2 hours)

### Task 2.1: Update IDENTITY_REFACTOR_AGI_FORWARD for identity_v2

**Context:** The spec targets old `identity.py`. Current code is `identity_v2.py`. Update the spec to reflect reality and remaining work.

**Files:**
- Modify: `docs/archive/2026-02/specs/IDENTITY_REFACTOR_AGI_FORWARD.md`
- Or create: `docs/plans/identity-refactor-status.md`

**Step 1: Audit current state**

List what exists:
- `identity_v2.py`: resolve_session_identity, onboard, identity tool
- No candidate lists in identity() — verify
- resume/agent_name rules in middleware

**Step 2: Add "Current State (Feb 2026)" section**

```markdown
## Current State (Feb 2026)

- identity_v2.py is authoritative. identity.py (v1) removed.
- onboard() uses name for PATH 2.5 (name-based claim).
- resume=True in arguments enables name lookup; otherwise agent_name only.
- No candidate lists in identity() — returns bound or unbound.
- X-Agent-Id header used for UUID recovery on reconnection.
```

**Step 3: Add "Remaining Work" section**

Prioritize from spec:
1. Terminology (agent_id → identity_id in API surface) — breaking
2. Active session protection (refuse auth if identity in use) — new feature
3. hello = new only, authenticate = prove existing — behavior change

**Step 4: Commit**

```bash
git add docs/archive/2026-02/specs/IDENTITY_REFACTOR_AGI_FORWARD.md
git commit -m "docs(identity): update AGI-forward spec for identity_v2 current state"
```

---

## Phase 3: Handler Splitting (Optional, Est. 4–6 hours)

### Task 3.1: Split lifecycle.py

**Context:** `lifecycle.py` is ~2,400 lines. Extract logical units.

**Files:**
- Create: `src/mcp_handlers/lifecycle_stuck.py` (detect_stuck_agents, related)
- Create: `src/mcp_handlers/lifecycle_resume.py` (operator_resume, direct_resume, etc.)
- Modify: `src/mcp_handlers/lifecycle.py` (import and re-export)

**Step 1: Identify extraction boundaries**

- `_detect_stuck_agents` and helpers → lifecycle_stuck.py
- `operator_resume_agent`, `direct_resume_if_safe` → lifecycle_resume.py

**Step 2: Extract with minimal changes**

Move functions, update imports. No behavior change.

**Step 3: Run lifecycle tests**

```bash
pytest tests/test_lifecycle_handlers.py tests/test_lifecycle_detect_stuck.py -v --tb=short
```

**Step 4: Commit**

```bash
git add src/mcp_handlers/lifecycle*.py
git commit -m "refactor(lifecycle): extract stuck detection and resume to separate modules"
```

---

## Phase 4: Deferred (Future)

- **MCP server unification:** Share logic between mcp_server.py and mcp_server_std.py. Large, high-risk.
- **Tool schema generation:** Replace 5.2K-line tool_schemas.py with generated/modular definitions.
- **Identity API breaking changes:** agent_id → identity_id, hello/authenticate split. Requires client coordination.

---

## Verification Checklist

After each phase:

- [ ] `pytest tests/ -v --tb=line -q` passes
- [ ] `python -m src.mcp_server --help` works (or equivalent)
- [ ] Manual onboard → checkin flow works
- [ ] No new linter errors in modified files

---

## Summary

| Phase | Tasks | Risk | Est. Time |
|-------|-------|------|-----------|
| 1. Low-risk cleanup | 3 | Low | 2–3 h |
| 2. Spec refresh | 1 | None | 1–2 h |
| 3. Handler splitting | 1 | Medium | 4–6 h |
| 4. Deferred | — | — | — |

**Recommended order:** Phase 1 → Phase 2. Phase 3 optional based on capacity.

---

**Plan complete and saved to `docs/plans/2026-02-26-unitares-mcp-cleanup-plan.md`.**

**Two execution options:**

1. **Subagent-Driven (this session)** — Dispatch fresh subagent per task, review between tasks, fast iteration.

2. **Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints.

**Which approach?**
