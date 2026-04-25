# KG Hygiene v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the write-strong/feedback-weak loop on the UNITARES KG by adding (1) a `supersedes:` field with permanent-tag guard at the store handler, (2) a Vigil "stale-opens" propose-only sweep, and (3) a Vigil retrieval-eval step that diffs nDCG@10 against config-matched baselines.

**Architecture:** Three independent items, each shippable on its own. Item 1 modifies the `handle_store_knowledge_graph` handler and the `DiscoveryNode` dataclass. Items 2 and 3 add new methods to `VigilAgent` plus two `with_*` boolean flags following the existing `with_tests`/`with_audit` pattern. No new files in `src/`, no new resident agents, no schema migrations.

**Tech Stack:** Python 3.12+, asyncio, asyncpg (via `src/storage/`), pytest with `unittest.mock`, AGE/Postgres knowledge backends.

**Spec:** `docs/superpowers/specs/2026-04-25-kg-hygiene-v1-design.md`

---

## File Structure

**Modify:**
- `src/knowledge_graph.py` — add `superseded_by: Optional[str] = None` to `DiscoveryNode` (L78–191); update status docstring (L88) to include `"superseded"`; update `to_dict` (L101) and `from_dict` (L159) to round-trip the new field.
- `src/mcp_handlers/knowledge/handlers.py` — add `supersedes:` parameter handling in `handle_store_knowledge_graph` (L330–650), inserted after argument parsing and before the `DiscoveryNode(...)` constructor at L556. Includes predecessor lookup, permanent-policy veto, and predecessor status flip.
- `agents/vigil/agent.py` — add `with_eval`, `with_hygiene` constructor flags (L260–265 area); add `_run_stale_opens_sweep` method; add `_run_eval_step` method with helper `_eval_baseline_for_config`; wire both into `run_cycle` between step 4 (Groundskeeper, L474) and step 5 (complexity computation, L491).

**Create:**
- `tests/test_kg_supersedes.py` — handler-level tests for Item 1 (happy path, permanent-veto, missing-predecessor).
- `tests/test_kg_supersedes_lifecycle.py` — verifies `_archive_old_resolved` does NOT touch `superseded` entries.
- `tests/test_vigil_stale_opens.py` — Item 3 sweep behavior (top-N cap, age ordering, propose-only — no status mutation).
- `tests/test_vigil_eval_step.py` — Item 2 step (config-tag derivation, baseline matching, regression threshold, no-baseline warning, `run_in_executor` wrapping).

**Notes on existing state (verified during planning):**
- `VALID_STATUSES` at `src/mcp_handlers/knowledge/handlers.py:1415` ALREADY includes `"superseded"` — no enum work needed.
- Both backends (`src/storage/knowledge_graph_age.py:486,767`, `src/storage/knowledge_graph_postgres.py:102,120`) already implement `get_discovery(id) -> Optional[DiscoveryNode]` and `update_discovery(id, updates: dict) -> bool`. Use these directly.
- `client.audit_knowledge(scope="open", top_n=N)` exists (called by Groundskeeper at `agents/vigil/agent.py:338`); use the same API for stale-opens sweep.
- `loop.run_in_executor(None, run_pytest, ...)` at `agents/vigil/agent.py:451` is the canonical pattern for offloading sync DB work from Vigil's anyio cycle context.
- `scripts/eval/retrieval_eval.py` already supports `--json` and `--labels` and `--limit-queries` flags.

---

## Item 1 — `supersedes:` field with permanent-tag guard

### Task 1: Add `superseded_by` field to `DiscoveryNode`

**Files:**
- Modify: `src/knowledge_graph.py:78-191`
- Test: `tests/test_kg_store.py` (extend with `superseded_by` round-trip cases)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_kg_store.py`:

```python
def test_discovery_node_superseded_by_round_trip():
    """superseded_by field round-trips through to_dict/from_dict."""
    d = DiscoveryNode(
        id="disc-new",
        agent_id="a",
        type="note",
        summary="replaces older",
        superseded_by=None,  # default
    )
    assert d.superseded_by is None

    # Set field, round-trip
    d2 = DiscoveryNode(
        id="disc-old",
        agent_id="a",
        type="note",
        summary="superseded by disc-new",
        status="superseded",
        superseded_by="disc-new",
    )
    serialized = d2.to_dict()
    assert serialized["status"] == "superseded"
    assert serialized["superseded_by"] == "disc-new"

    rehydrated = DiscoveryNode.from_dict(serialized)
    assert rehydrated.status == "superseded"
    assert rehydrated.superseded_by == "disc-new"

def test_discovery_node_superseded_by_omitted_when_none():
    """to_dict does not emit superseded_by key when None (keeps payload lean)."""
    d = DiscoveryNode(id="x", agent_id="a", type="note", summary="s")
    assert "superseded_by" not in d.to_dict()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cirwel/projects/unitares
pytest tests/test_kg_store.py::test_discovery_node_superseded_by_round_trip tests/test_kg_store.py::test_discovery_node_superseded_by_omitted_when_none --no-cov --tb=short -q
```

Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'superseded_by'`.

- [ ] **Step 3: Add the field and update serialization**

Edit `src/knowledge_graph.py`:

At L88, change:
```python
    status: str = "open"  # "open", "resolved", "archived", "disputed"
```
to:
```python
    status: str = "open"  # "open", "resolved", "archived", "disputed", "superseded", "closed", "wont_fix"
```

After the existing `responses_from` field (L91), add (preserving alphabetical/logical grouping):
```python
    superseded_by: Optional[str] = None  # discovery_id of the entry that superseded this one
```

In `to_dict` (L101), after the `if self.confidence is not None:` block (around L131), add:
```python
        if self.superseded_by is not None:
            result["superseded_by"] = self.superseded_by
```

In `from_dict` (L159), add to the constructor kwargs (alongside `provenance_chain=...`):
```python
            superseded_by=data.get("superseded_by"),
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_kg_store.py::test_discovery_node_superseded_by_round_trip tests/test_kg_store.py::test_discovery_node_superseded_by_omitted_when_none --no-cov --tb=short -q
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Run the full kg-store test file to confirm no regressions**

```bash
pytest tests/test_kg_store.py --no-cov --tb=short -q | tail -20
```

Expected: All previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add src/knowledge_graph.py tests/test_kg_store.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(kg): add superseded_by field to DiscoveryNode

Round-trips through to_dict/from_dict; omitted from output when None.
Status docstring updated to reflect VALID_STATUSES from handlers.py."
```

---

### Task 2: Handler-level `supersedes:` happy path

**Files:**
- Modify: `src/mcp_handlers/knowledge/handlers.py:330-650` (insert after summary validation, before `DiscoveryNode(...)` constructor)
- Create: `tests/test_kg_supersedes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_kg_supersedes.py`:

```python
"""Tests for supersedes: parameter on knowledge action=store."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge_graph import DiscoveryNode
from tests.helpers import parse_result


@pytest.mark.asyncio
async def test_supersedes_flips_predecessor_status():
    """Storing with supersedes=<old_id> flips old discovery's status to 'superseded' and sets superseded_by."""
    from src.mcp_handlers.knowledge.handlers import handle_store_knowledge_graph

    predecessor = DiscoveryNode(
        id="old-disc-1",
        agent_id="agent-a",
        type="note",
        summary="original",
        status="open",
        tags=["routine"],
    )

    mock_graph = MagicMock()
    mock_graph.get_discovery = AsyncMock(return_value=predecessor)
    mock_graph.add_discovery = AsyncMock()
    mock_graph.update_discovery = AsyncMock(return_value=True)
    mock_graph.find_similar = AsyncMock(return_value=[])

    with patch(
        "src.mcp_handlers.knowledge.handlers.get_knowledge_graph",
        new=AsyncMock(return_value=mock_graph),
    ):
        result = await handle_store_knowledge_graph({
            "agent_id": "agent-b",
            "summary": "replaces old-disc-1",
            "supersedes": "old-disc-1",
        })

    payload = parse_result(result)
    assert "discovery_id" in payload
    new_id = payload["discovery_id"]

    # Predecessor must have been flipped
    mock_graph.update_discovery.assert_awaited_once()
    call_args = mock_graph.update_discovery.await_args
    assert call_args[0][0] == "old-disc-1"
    updates = call_args[0][1]
    assert updates["status"] == "superseded"
    assert updates["superseded_by"] == new_id

    # Response surfaces the supersession
    assert payload.get("superseded") == "old-disc-1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_kg_supersedes.py::test_supersedes_flips_predecessor_status --no-cov --tb=short -q
```

Expected: FAIL — predecessor not flipped because handler doesn't process `supersedes` argument.

- [ ] **Step 3: Implement supersedes handling in the handler**

Edit `src/mcp_handlers/knowledge/handlers.py`. After `summary, error = require_argument(arguments, "summary", ...)` (around L392) and before the `try:` block at L397, insert:

```python
    # supersedes: optional pre-flight — find predecessor, prepare for status flip
    # The actual flip happens after the new discovery is stored, so we need only
    # the predecessor reference here. Permanent-policy veto runs in Task 3.
    supersedes_id = arguments.get("supersedes")
    supersedes_target = None
    if supersedes_id:
        supersedes_id = str(supersedes_id).strip()
        if not supersedes_id:
            return [error_response("supersedes parameter cannot be empty string")]
```

After `await graph.add_discovery(discovery)` (L601), and before the response is constructed (L608), insert:

```python
        # supersedes: flip predecessor status if requested
        # Predecessor lookup deferred until we have a graph instance.
        if supersedes_id:
            supersedes_target = await graph.get_discovery(supersedes_id)
            if supersedes_target is None:
                # Predecessor doesn't exist; new discovery is already stored.
                # Surface as a warning, not an error — caller's intent honored
                # for the new entry, but the supersession could not be applied.
                supersedes_warning = (
                    f"supersedes target '{supersedes_id}' not found; "
                    f"new discovery {discovery_id} stored without flip"
                )
            else:
                supersedes_warning = None
                await graph.update_discovery(supersedes_id, {
                    "status": "superseded",
                    "superseded_by": discovery_id,
                    "updated_at": datetime.now().isoformat(),
                })
```

In the response dict (around L608), add after `"discovery": discovery.to_dict(...)`:

```python
        if supersedes_id:
            if supersedes_target is not None:
                response["superseded"] = supersedes_id
            else:
                response["_supersedes_warning"] = supersedes_warning
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_kg_supersedes.py::test_supersedes_flips_predecessor_status --no-cov --tb=short -q
```

Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add src/mcp_handlers/knowledge/handlers.py tests/test_kg_supersedes.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(kg): supersedes: parameter flips predecessor status

knowledge action=store with supersedes=<old_id> looks up the predecessor
after the new discovery is stored, then flips status to superseded and
sets superseded_by pointing at the new discovery. Missing predecessor
surfaces as warning, not error."
```

---

### Task 3: Permanent-policy veto on supersedes

**Files:**
- Modify: `src/mcp_handlers/knowledge/handlers.py` (extend supersedes handling with policy check)
- Modify: `tests/test_kg_supersedes.py` (add veto + missing-predecessor cases)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_kg_supersedes.py`:

```python
@pytest.mark.asyncio
async def test_supersedes_vetoed_for_permanent_predecessor():
    """Permanent-tagged predecessors cannot be auto-flipped to superseded."""
    from src.mcp_handlers.knowledge.handlers import handle_store_knowledge_graph

    permanent_predecessor = DiscoveryNode(
        id="perm-1",
        agent_id="agent-a",
        type="architectural_decision",  # permanent type
        summary="ADR: schema choice",
        status="open",
        tags=["architecture"],
    )

    mock_graph = MagicMock()
    mock_graph.get_discovery = AsyncMock(return_value=permanent_predecessor)
    mock_graph.add_discovery = AsyncMock()
    mock_graph.update_discovery = AsyncMock(return_value=True)
    mock_graph.find_similar = AsyncMock(return_value=[])

    with patch(
        "src.mcp_handlers.knowledge.handlers.get_knowledge_graph",
        new=AsyncMock(return_value=mock_graph),
    ):
        result = await handle_store_knowledge_graph({
            "agent_id": "agent-b",
            "summary": "tries to supersede ADR",
            "supersedes": "perm-1",
        })

    payload = parse_result(result)
    # Veto must come BEFORE the new discovery is stored
    mock_graph.add_discovery.assert_not_awaited()
    mock_graph.update_discovery.assert_not_awaited()
    # Error response, not success
    assert "error" in payload or payload.get("error_code")


@pytest.mark.asyncio
async def test_supersedes_missing_predecessor_warns_not_errors():
    """Missing predecessor surfaces as warning; new discovery still stored."""
    from src.mcp_handlers.knowledge.handlers import handle_store_knowledge_graph

    mock_graph = MagicMock()
    mock_graph.get_discovery = AsyncMock(return_value=None)  # not found
    mock_graph.add_discovery = AsyncMock()
    mock_graph.update_discovery = AsyncMock()
    mock_graph.find_similar = AsyncMock(return_value=[])

    with patch(
        "src.mcp_handlers.knowledge.handlers.get_knowledge_graph",
        new=AsyncMock(return_value=mock_graph),
    ):
        result = await handle_store_knowledge_graph({
            "agent_id": "agent-b",
            "summary": "thinks it supersedes a ghost",
            "supersedes": "ghost-id",
        })

    payload = parse_result(result)
    assert "discovery_id" in payload  # new entry was still stored
    mock_graph.add_discovery.assert_awaited_once()
    mock_graph.update_discovery.assert_not_awaited()
    assert "_supersedes_warning" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_kg_supersedes.py --no-cov --tb=short -q
```

Expected: 1 PASS (from Task 2), `test_supersedes_vetoed_for_permanent_predecessor` FAIL (predecessor still gets flipped), `test_supersedes_missing_predecessor_warns_not_errors` should already PASS from Task 2's missing-predecessor handling.

- [ ] **Step 3: Add the permanent-policy veto**

Edit `src/mcp_handlers/knowledge/handlers.py`. The veto must run BEFORE `await graph.add_discovery(discovery)` so a vetoed supersession doesn't leave the new discovery orphaned.

Move the predecessor lookup forward — change the post-`add_discovery` block from Task 2 to instead live as a pre-flight, AND add the policy check. Replace the Task 2 post-store block with this pre-store version:

After `discovery = DiscoveryNode(...)` (around L569) and before `await _clamp_confidence_to_coherence(discovery, agent_id)` (L572), insert:

```python
        # supersedes: pre-flight — verify predecessor exists and is not permanent
        supersedes_target = None
        supersedes_warning = None
        if supersedes_id:
            supersedes_target = await graph.get_discovery(supersedes_id)
            if supersedes_target is None:
                supersedes_warning = (
                    f"supersedes target '{supersedes_id}' not found; "
                    f"new discovery will be stored without flip"
                )
            else:
                from src.knowledge_graph_lifecycle import KnowledgeGraphLifecycle
                lifecycle = KnowledgeGraphLifecycle()
                policy = lifecycle.get_lifecycle_policy(supersedes_target)
                if policy == "permanent":
                    return [error_response(
                        f"Cannot supersede permanent discovery '{supersedes_id}' "
                        f"(type={supersedes_target.type}, tags={supersedes_target.tags}). "
                        "Use knowledge(action='update') with explicit operator action to override."
                    )]
```

Then, replace the post-store block from Task 2 with the simpler version (predecessor already known to exist + non-permanent):

```python
        # supersedes: flip predecessor status (pre-flight already verified)
        if supersedes_id and supersedes_target is not None:
            await graph.update_discovery(supersedes_id, {
                "status": "superseded",
                "superseded_by": discovery_id,
                "updated_at": datetime.now().isoformat(),
            })
```

Response block stays the same (warning surfaces if `supersedes_target is None`; "superseded" surfaces if it was flipped).

- [ ] **Step 4: Run tests to verify all 3 pass**

```bash
pytest tests/test_kg_supersedes.py --no-cov --tb=short -q
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add src/mcp_handlers/knowledge/handlers.py tests/test_kg_supersedes.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(kg): permanent-policy veto on supersedes

Pre-flight check rejects supersedes targeting any discovery whose
get_lifecycle_policy() returns 'permanent'. Veto fires before the new
discovery is stored, so a rejected supersession does not orphan the
new entry. Missing predecessor remains a warning, not an error."
```

---

### Task 4: Lifecycle interaction guarantee

**Files:**
- Create: `tests/test_kg_supersedes_lifecycle.py`

- [ ] **Step 1: Write the lifecycle test**

Create `tests/test_kg_supersedes_lifecycle.py`:

```python
"""Verify _archive_old_resolved does NOT touch superseded entries.

The lifecycle module's _archive_old_resolved queries status='resolved' only.
A discovery flipped to 'superseded' should be invisible to that sweep,
which is intentional v1 behavior — we let superseded entries stay hot
until v2 decides their fate."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge_graph import DiscoveryNode
from src.knowledge_graph_lifecycle import KnowledgeGraphLifecycle


@pytest.mark.asyncio
async def test_archive_old_resolved_skips_superseded():
    """A 100-day-old superseded discovery is NOT archived by the resolved-sweep."""
    old_iso = (datetime.now() - timedelta(days=100)).isoformat()
    superseded = DiscoveryNode(
        id="ss-old",
        agent_id="a",
        type="note",
        summary="s",
        status="superseded",
        resolved_at=old_iso,  # eligible by age, but wrong status bucket
    )

    # Mock graph: query(status="resolved") returns [], query(status="open") returns []
    mock_graph = MagicMock()
    mock_graph.query = AsyncMock(return_value=[])  # NOT returning superseded
    mock_graph.update_discovery = AsyncMock()

    lifecycle = KnowledgeGraphLifecycle()
    lifecycle._graph = mock_graph

    archived, skipped = await lifecycle._archive_old_resolved(datetime.now(), dry_run=False)

    # Sanity: query was called with status='resolved' — superseded is a different bucket
    mock_graph.query.assert_awaited_with(status="resolved", limit=1000)
    assert archived == []
    assert skipped == 0
    # Most importantly: no update_discovery call against the superseded entry
    mock_graph.update_discovery.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it passes**

```bash
pytest tests/test_kg_supersedes_lifecycle.py --no-cov --tb=short -q
```

Expected: PASS — this is a verification test, not a regression test. It documents the v1 invariant ("superseded is not in the lifecycle vocabulary") so any future change to `_archive_old_resolved` that broadens its query will fail this test.

- [ ] **Step 3: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add tests/test_kg_supersedes_lifecycle.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "test(kg): lock in superseded ⊄ lifecycle-vocabulary invariant

_archive_old_resolved queries status='resolved' only. v1 deliberately
leaves superseded entries hot (no auto-archive). This test will fail
if a future change broadens the lifecycle sweep to include superseded."
```

---

## Item 3 — Vigil stale-opens sweep (propose-only)

(Implemented before Item 2 because it proves the new `with_*` flag pattern with simpler plumbing.)

### Task 5: Add `with_hygiene` flag and `_run_stale_opens_sweep` method

**Files:**
- Modify: `agents/vigil/agent.py:254-291` (constructor) and add new method
- Create: `tests/test_vigil_stale_opens.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_vigil_stale_opens.py`:

```python
"""Tests for Vigil's stale-opens propose-only sweep.

Reads the existing audit_knowledge handler's `top_stale` output (entries
already scored by src/knowledge_graph_lifecycle.py:_score_discovery with
age_days, last_activity_days, bucket). We do NOT re-parse timestamps."""
import pytest
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_audit_response(top_stale):
    """Mimic GovernanceClient.audit_knowledge response shape.

    audit_knowledge returns success_response with audit dict containing
    `buckets`, `top_stale`, `total_audited`. Each top_stale entry is a
    pre-scored dict with id, summary, type, age_days, last_activity_days,
    bucket, tags, activity_score."""
    resp = MagicMock()
    resp.success = True
    resp.audit = {
        "top_stale": top_stale,
        "buckets": {"stale": len(top_stale), "candidate_for_archive": 0},
        "total_audited": len(top_stale),
    }
    return resp


@pytest.mark.asyncio
async def test_stale_opens_sweep_returns_top_n_oldest_first():
    """Sweep returns at most 20 entries from top_stale, oldest first."""
    from agents.vigil.agent import VigilAgent

    # 25 stale entries, last_activity_days 31..55. Audit already orders by
    # last_activity_days desc (oldest first), but we re-sort defensively.
    top_stale = [
        {
            "id": f"d-{i}",
            "summary": f"summary {i}",
            "type": "note",
            "age_days": 60 + i,
            "last_activity_days": 31 + i,
            "bucket": "stale",
            "tags": [],
        }
        for i in range(25)
    ]
    # Audit orders by last_activity_days desc — d-24 (55d) first, d-0 (31d) last
    top_stale.sort(key=lambda x: x["last_activity_days"], reverse=True)

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=_make_audit_response(top_stale))

    vigil = VigilAgent(with_hygiene=True)
    result = await vigil._run_stale_opens_sweep(mock_client)

    assert isinstance(result, list)
    assert len(result) == 20  # capped
    assert result[0]["id"] == "d-24"  # last_activity_days=55, oldest first
    assert result[-1]["id"] == "d-5"  # 20th-oldest, last_activity_days=36


@pytest.mark.asyncio
async def test_stale_opens_sweep_no_action_taken():
    """Sweep is propose-only — never calls update_discovery or cleanup."""
    from agents.vigil.agent import VigilAgent

    top_stale = [{
        "id": "d-1",
        "summary": "stale",
        "type": "note",
        "age_days": 50,
        "last_activity_days": 45,
        "bucket": "stale",
        "tags": [],
    }]

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=_make_audit_response(top_stale))
    mock_client.cleanup_knowledge = AsyncMock()

    vigil = VigilAgent(with_hygiene=True)
    await vigil._run_stale_opens_sweep(mock_client)

    mock_client.cleanup_knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_opens_sweep_disabled_by_default():
    """with_hygiene=False → sweep returns empty list without calling client."""
    from agents.vigil.agent import VigilAgent

    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock()

    vigil = VigilAgent()  # with_hygiene defaults to False
    assert vigil.with_hygiene is False
    result = await vigil._run_stale_opens_sweep(mock_client)
    assert result == []
    mock_client.audit_knowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_opens_sweep_audit_failure_returns_empty():
    """audit_knowledge failure → sweep returns [], does not raise."""
    from agents.vigil.agent import VigilAgent

    failed = MagicMock()
    failed.success = False
    mock_client = MagicMock()
    mock_client.audit_knowledge = AsyncMock(return_value=failed)

    vigil = VigilAgent(with_hygiene=True)
    result = await vigil._run_stale_opens_sweep(mock_client)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vigil_stale_opens.py --no-cov --tb=short -q
```

Expected: FAIL — `with_hygiene` is not a constructor kwarg; `_run_stale_opens_sweep` does not exist.

- [ ] **Step 3: Add the flag and the method**

Edit `agents/vigil/agent.py`. In `VigilAgent.__init__` (L255-263), add `with_hygiene: bool = False` to the kwargs after `with_audit`:

```python
    def __init__(
        self,
        mcp_url: str = GOV_MCP_URL,
        label: str = "Vigil",
        heartbeat_interval: int = 1800,
        with_tests: bool = False,
        with_audit: bool = True,
        with_hygiene: bool = False,
        force_new: bool = False,
    ):
```

In the body, after `self.with_audit = with_audit` (L280), add:

```python
        self.with_hygiene = with_hygiene
```

After the `_run_groundskeeper` method (which ends around L390), add:

```python
    async def _run_stale_opens_sweep(
        self, client: GovernanceClient, top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        """Propose-only: surface oldest stale-open KG entries from the audit.

        Reads via client.audit_knowledge(scope='open'); the audit handler
        already scores each open entry and returns top_stale ordered by
        last_activity_days desc with bucket classification. We just take
        up to top_n entries and surface them — no action taken.

        Returns oldest-first (matches the audit's own ordering). Empty list
        on any failure or when with_hygiene is False — propose-only is
        best-effort, must not poison the cycle.
        """
        if not self.with_hygiene:
            return []

        try:
            result = await asyncio.wait_for(
                client.audit_knowledge(scope="open", top_n=top_n),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            log("stale-opens sweep timed out after 15s; continuing cycle")
            return []
        except Exception as e:
            log(f"stale-opens sweep failed ({e}); continuing cycle")
            return []

        if not getattr(result, "success", False):
            return []

        audit_data = getattr(result, "audit", None) or {}
        if not isinstance(audit_data, dict):
            return []
        top_stale = audit_data.get("top_stale", []) or []

        # The audit already orders by last_activity_days desc. Re-sort
        # defensively in case the contract ever changes.
        top_stale.sort(key=lambda x: x.get("last_activity_days", 0), reverse=True)
        return top_stale[:top_n]
```

No new imports required — `asyncio` is already imported at the top of `agents/vigil/agent.py`. Verify before adding anything.

- [ ] **Step 4: Run tests to verify all 3 pass**

```bash
pytest tests/test_vigil_stale_opens.py --no-cov --tb=short -q
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add agents/vigil/agent.py tests/test_vigil_stale_opens.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(vigil): with_hygiene flag + propose-only stale-opens sweep

_run_stale_opens_sweep reads via client.audit_knowledge, returns top-N
oldest-first, never mutates state. Defaults off; opt-in via with_hygiene.
Failures return [] — sweep is best-effort, must not poison the cycle."
```

---

### Task 6: Wire stale-opens sweep into Vigil's run_cycle

**Files:**
- Modify: `agents/vigil/agent.py:392-491` (insert sweep call between step 4 and step 5)

Wiring is verified by (a) the unit tests in Task 5 confirming `_run_stale_opens_sweep` returns the right shape, (b) the Vigil regression-test sweep in Step 3 below confirming no existing tests broke, and (c) the live smoke run in Task 9 Step 3 confirming the integration end-to-end. A full mocked-run_cycle test would require ~15 collaborators stubbed and would be brittler than the live smoke, so we skip that synthetic level.

- [ ] **Step 1: Wire the sweep into run_cycle**

Edit `agents/vigil/agent.py`. After the Groundskeeper block (ending around L489) and before step 5 (complexity, L491), insert:

```python
        # --- 4.5. Stale-opens propose-only sweep (optional) ---
        stale_opens = await self._run_stale_opens_sweep(client)
        if stale_opens:
            oldest = stale_opens[0]
            findings.append(
                f"hygiene: {len(stale_opens)} stale opens (oldest "
                f"{oldest.get('id', '?')[:12]}, "
                f"age={oldest.get('last_activity_days', 0)}d)"
            )
            for item in stale_opens[:5]:  # top 5 inline; rest in cycle state
                summary_short = (item.get("summary") or "")[:60]
                age_days = item.get("last_activity_days", 0)
                findings.append(
                    f"stale_open: {item.get('id', '?')[:12]} \"{summary_short}\" age={age_days}d"
                )
```

Also extend the cycle-state dict (within `self._cycle_state = {...}` around L538) to include:

```python
            "hygiene_stale_opens": len(stale_opens),
```

(`stale_opens` will always be defined by this point in run_cycle — `_run_stale_opens_sweep` returns `[]` when disabled, never raises.)

- [ ] **Step 2: Run a syntax-only verification**

```bash
python3 -c "import ast; ast.parse(open('/Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec/agents/vigil/agent.py').read())"
```

Expected: no output (valid Python).

- [ ] **Step 3: Run the existing Vigil tests to confirm no regressions**

```bash
pytest tests/test_vigil_*.py --no-cov --tb=short -q | tail -20
```

Expected: All previously-passing Vigil tests still pass (the new wiring is opt-in via `with_hygiene`).

- [ ] **Step 4: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add agents/vigil/agent.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(vigil): wire stale-opens sweep into run_cycle as step 4.5

Surfaces oldest 5 stale opens inline in cycle findings; full count
in hygiene_stale_opens cycle-state field for dashboard consumption.
Step is no-op when with_hygiene=False."
```

---

## Item 2 — Vigil retrieval-eval step

### Task 7: Config-tag derivation + baseline-matching helpers

**Files:**
- Modify: `agents/vigil/agent.py` (add module-level helpers `_derive_eval_config_tag`, `_pick_eval_baseline`)
- Create: `tests/test_vigil_eval_step.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vigil_eval_step.py`:

```python
"""Tests for Vigil's retrieval-eval step (config-tag, baseline match, regression)."""
import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.parametrize("env,expected", [
    ({"UNITARES_EMBEDDING_MODEL": "bge-m3"}, "bge_m3"),
    ({"UNITARES_EMBEDDING_MODEL": "bge-m3", "UNITARES_ENABLE_HYBRID": "1"}, "hybrid_rrf"),
    (
        {"UNITARES_EMBEDDING_MODEL": "bge-m3",
         "UNITARES_ENABLE_HYBRID": "1",
         "UNITARES_ENABLE_GRAPH_EXPANSION": "1"},
        "hybrid_graph",
    ),
    (
        {"UNITARES_EMBEDDING_MODEL": "bge-m3",
         "UNITARES_ENABLE_RERANKER": "1"},
        "bge_m3_reranked",
    ),
])
def test_derive_eval_config_tag(env, expected, monkeypatch):
    from agents.vigil.agent import _derive_eval_config_tag

    # Clear all relevant env vars first, then set the test set
    for k in ("UNITARES_EMBEDDING_MODEL", "UNITARES_ENABLE_HYBRID",
              "UNITARES_ENABLE_GRAPH_EXPANSION", "UNITARES_ENABLE_RERANKER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    assert _derive_eval_config_tag() == expected


def test_pick_eval_baseline_matches_config(tmp_path):
    """Picks the newest baseline file matching the live config tag."""
    from agents.vigil.agent import _pick_eval_baseline

    (tmp_path / "baseline_2026-04-19_bge_m3.json").write_text("{}")
    (tmp_path / "baseline_2026-04-20_hybrid_rrf.json").write_text("{}")
    (tmp_path / "baseline_2026-04-21_hybrid_rrf.json").write_text("{}")  # newest matching

    picked = _pick_eval_baseline(tmp_path, config_tag="hybrid_rrf")
    assert picked.name == "baseline_2026-04-21_hybrid_rrf.json"


def test_pick_eval_baseline_returns_none_when_no_match(tmp_path):
    """No matching baseline → None (caller logs warning, no regression alert)."""
    from agents.vigil.agent import _pick_eval_baseline
    (tmp_path / "baseline_2026-04-20_bge_m3.json").write_text("{}")
    assert _pick_eval_baseline(tmp_path, config_tag="hybrid_graph") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vigil_eval_step.py --no-cov --tb=short -q
```

Expected: FAIL — `_derive_eval_config_tag` and `_pick_eval_baseline` don't exist.

- [ ] **Step 3: Add the helpers**

Edit `agents/vigil/agent.py`. Near the other module-level helpers (search for an existing standalone `def` outside the `VigilAgent` class — e.g., near `_filter_sentinel_findings`), add:

```python
def _derive_eval_config_tag() -> str:
    """Derive a config tag matching baseline filename suffix from env vars.

    Tag values mirror existing baselines in tests/retrieval_eval/:
    bge_m3, bge_m3_reranked, hybrid_rrf, hybrid_graph.
    """
    embedding = os.environ.get("UNITARES_EMBEDDING_MODEL", "").strip().lower()
    hybrid = os.environ.get("UNITARES_ENABLE_HYBRID", "").strip() == "1"
    graph = os.environ.get("UNITARES_ENABLE_GRAPH_EXPANSION", "").strip() == "1"
    reranker = os.environ.get("UNITARES_ENABLE_RERANKER", "").strip() == "1"

    base = "bge_m3" if "bge-m3" in embedding else (embedding.replace("-", "_") or "default")

    if graph:
        return "hybrid_graph"
    if hybrid:
        return "hybrid_rrf"
    if reranker:
        return f"{base}_reranked"
    return base


def _pick_eval_baseline(baseline_dir: Path, config_tag: str) -> Optional[Path]:
    """Return newest baseline_*_<config_tag>.json by mtime, or None."""
    if not baseline_dir.exists():
        return None
    matches = sorted(
        baseline_dir.glob(f"baseline_*_{config_tag}.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None
```

Ensure `from typing import Optional` and `from pathlib import Path` are imported (verify against the existing imports at the top of the file).

- [ ] **Step 4: Run tests to verify all 5 pass**

```bash
pytest tests/test_vigil_eval_step.py::test_derive_eval_config_tag tests/test_vigil_eval_step.py::test_pick_eval_baseline_matches_config tests/test_vigil_eval_step.py::test_pick_eval_baseline_returns_none_when_no_match --no-cov --tb=short -q
```

Expected: 5 PASS (4 parametrize cases for derive_config_tag + 2 baseline-pick cases — adjust collection expectations as needed).

- [ ] **Step 5: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add agents/vigil/agent.py tests/test_vigil_eval_step.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(vigil): config-tag + baseline-pick helpers for eval step

_derive_eval_config_tag reads UNITARES_EMBEDDING_MODEL, *_ENABLE_HYBRID,
*_ENABLE_GRAPH_EXPANSION, *_ENABLE_RERANKER env vars to produce a tag
matching tests/retrieval_eval/baseline_*.json suffixes.

_pick_eval_baseline returns the newest matching baseline by mtime, or
None if no baseline matches the live config (caller logs warning, skips
regression alert)."
```

---

### Task 8: `_run_eval_step` method with `run_in_executor` wrapping

**Files:**
- Modify: `agents/vigil/agent.py` (add `with_eval` flag + `_run_eval_step` method)
- Modify: `tests/test_vigil_eval_step.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vigil_eval_step.py`:

```python
@pytest.mark.asyncio
async def test_run_eval_step_disabled_by_default():
    from agents.vigil.agent import VigilAgent
    vigil = VigilAgent()
    assert vigil.with_eval is False
    result = await vigil._run_eval_step()
    assert result == {"ran": False, "reason": "with_eval=False"}


@pytest.mark.asyncio
async def test_run_eval_step_no_baseline_returns_warning(tmp_path, monkeypatch):
    from agents.vigil.agent import VigilAgent

    monkeypatch.setenv("UNITARES_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.delenv("UNITARES_ENABLE_HYBRID", raising=False)
    monkeypatch.delenv("UNITARES_ENABLE_GRAPH_EXPANSION", raising=False)
    monkeypatch.delenv("UNITARES_ENABLE_RERANKER", raising=False)

    vigil = VigilAgent(with_eval=True)
    # Patch the baseline dir to an empty tmp_path
    with patch("agents.vigil.agent.RETRIEVAL_EVAL_DIR", tmp_path), \
         patch("agents.vigil.agent._run_eval_subprocess",
               new=AsyncMock(return_value={"nDCG@10": 0.7, "Recall@20": 0.85, "MRR": 0.6, "latency_p50": 50, "latency_p95": 120})):
        result = await vigil._run_eval_step()

    assert result["ran"] is True
    assert result["baseline"] is None
    assert "no_baseline_warning" in result
    assert result["regression"] is False  # no baseline → no regression alert


@pytest.mark.asyncio
async def test_run_eval_step_regression_alert(tmp_path, monkeypatch):
    """nDCG@10 drops by more than threshold → regression flag set."""
    from agents.vigil.agent import VigilAgent

    monkeypatch.setenv("UNITARES_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("UNITARES_ENABLE_HYBRID", "1")

    baseline = tmp_path / "baseline_2026-04-20_hybrid_rrf.json"
    baseline.write_text(json.dumps({
        "metrics": {"nDCG@10": 0.80, "Recall@20": 0.90, "MRR": 0.65, "latency_p50": 45, "latency_p95": 110}
    }))

    vigil = VigilAgent(with_eval=True)
    with patch("agents.vigil.agent.RETRIEVAL_EVAL_DIR", tmp_path), \
         patch("agents.vigil.agent._run_eval_subprocess",
               new=AsyncMock(return_value={"nDCG@10": 0.70, "Recall@20": 0.88, "MRR": 0.60, "latency_p50": 50, "latency_p95": 120})):
        result = await vigil._run_eval_step()

    assert result["ran"] is True
    assert result["regression"] is True
    assert result["delta"]["nDCG@10"] == pytest.approx(-0.10, abs=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_vigil_eval_step.py --no-cov --tb=short -q
```

Expected: FAIL — `with_eval`, `_run_eval_step`, `RETRIEVAL_EVAL_DIR`, `_run_eval_subprocess` don't exist.

- [ ] **Step 3: Add the flag, constants, and method**

Edit `agents/vigil/agent.py`.

Near other module-level path constants (search for `SESSION_FILE = ...`), add:

```python
RETRIEVAL_EVAL_DIR = project_root / "tests" / "retrieval_eval"
RETRIEVAL_EVAL_SCRIPT = project_root / "scripts" / "eval" / "retrieval_eval.py"
NDCG_REGRESSION_THRESHOLD = 0.05  # absolute drop in nDCG@10 that triggers a regression flag
```

Add `with_eval: bool = False` to `__init__` kwargs (after `with_hygiene`), and `self.with_eval = with_eval` in the body.

After the existing helpers (`_derive_eval_config_tag`, `_pick_eval_baseline`), add the subprocess runner:

```python
def _run_eval_subprocess() -> Dict[str, Any]:
    """Invoke the eval harness as a subprocess; return parsed JSON metrics.

    Sync function — designed to be called via run_in_executor from the async
    cycle. Returns {} on failure (caller handles).
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["python3", str(RETRIEVAL_EVAL_SCRIPT), "--json"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            log(f"eval subprocess returned {proc.returncode}: {proc.stderr[:200]}")
            return {}
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        log(f"eval subprocess failed: {e}")
        return {}
```

Add `import json` near the other imports — it is NOT in `agents/vigil/agent.py` today (verified: `import asyncio`, `import os`, `import subprocess`, `import sys`, `from datetime import datetime, timezone`, `from pathlib import Path`, `from typing import ...`).

In `VigilAgent`, add the method (after `_run_stale_opens_sweep`):

```python
    async def _run_eval_step(self) -> Dict[str, Any]:
        """Run retrieval_eval as a subprocess via executor; diff against baseline.

        Returns {"ran": bool, "metrics": dict, "baseline": str|None,
        "delta": dict, "regression": bool, ...}.
        Never raises — returns {"ran": False, ...} on any failure.
        """
        if not self.with_eval:
            return {"ran": False, "reason": "with_eval=False"}

        loop = asyncio.get_event_loop()
        try:
            metrics = await loop.run_in_executor(None, _run_eval_subprocess)
        except Exception as e:
            log(f"eval step failed: {e}")
            return {"ran": False, "reason": f"executor error: {e}"}

        if not metrics:
            return {"ran": False, "reason": "empty metrics"}

        config_tag = _derive_eval_config_tag()
        baseline_path = _pick_eval_baseline(RETRIEVAL_EVAL_DIR, config_tag)

        result: Dict[str, Any] = {
            "ran": True,
            "metrics": metrics,
            "config_tag": config_tag,
            "baseline": baseline_path.name if baseline_path else None,
            "delta": {},
            "regression": False,
        }

        if baseline_path is None:
            result["no_baseline_warning"] = (
                f"no matching baseline for config={config_tag}; "
                f"run output not compared. Promote manually if good."
            )
            log(result["no_baseline_warning"])
            return result

        try:
            baseline = json.loads(baseline_path.read_text())
            base_metrics = baseline.get("metrics", baseline)  # tolerate flat or nested
            for key in ("nDCG@10", "Recall@20", "MRR", "latency_p50", "latency_p95"):
                if key in metrics and key in base_metrics:
                    result["delta"][key] = metrics[key] - base_metrics[key]
            ndcg_delta = result["delta"].get("nDCG@10", 0.0)
            if ndcg_delta < -NDCG_REGRESSION_THRESHOLD:
                result["regression"] = True
        except Exception as e:
            log(f"baseline diff failed: {e}")
            result["diff_error"] = str(e)

        return result
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
pytest tests/test_vigil_eval_step.py --no-cov --tb=short -q
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add agents/vigil/agent.py tests/test_vigil_eval_step.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(vigil): with_eval flag + _run_eval_step

Subprocess-runs scripts/eval/retrieval_eval.py --json via run_in_executor
to dodge the anyio-asyncpg deadlock surface. Diffs against the newest
baseline matching the live retrieval-config tag (env-var-derived).
Sets regression flag when nDCG@10 drops more than 0.05 absolute.
No-baseline case logs warning and skips alert."
```

---

### Task 9: Wire eval step into Vigil's run_cycle and ship verification

**Files:**
- Modify: `agents/vigil/agent.py:392-491` (insert eval call after stale-opens sweep)

- [ ] **Step 1: Wire the eval step into run_cycle**

Edit `agents/vigil/agent.py`. After the stale-opens sweep block from Task 6 and before step 5 (complexity computation), insert:

```python
        # --- 4.7. Retrieval-eval step (optional) ---
        eval_result = await self._run_eval_step()
        if eval_result.get("ran"):
            metrics = eval_result["metrics"]
            delta = eval_result.get("delta", {})
            baseline_name = eval_result.get("baseline") or "no-baseline"
            ndcg = metrics.get("nDCG@10", 0.0)
            ndcg_delta = delta.get("nDCG@10", 0.0)
            p95 = metrics.get("latency_p95", 0)
            p95_delta = delta.get("latency_p95", 0)
            findings.append(
                f"eval: nDCG@10 {ndcg:.3f} (Δ {ndcg_delta:+.3f} vs {baseline_name}), "
                f"p95 {p95:.0f}ms (Δ {p95_delta:+.0f}ms)"
            )
            if eval_result.get("regression"):
                findings.append("⚠ eval regression: nDCG@10 dropped beyond threshold")
                issues += 1
```

Extend the `self._cycle_state` dict (around L538) with:

```python
            "eval_ndcg10": eval_result.get("metrics", {}).get("nDCG@10"),
            "eval_baseline": eval_result.get("baseline"),
            "eval_regression": eval_result.get("regression", False),
```

(`eval_result` is always defined by this point — `_run_eval_step` returns a dict with `ran=False` when disabled, never raises.)

- [ ] **Step 2: Run syntax check + Vigil tests**

```bash
python3 -c "import ast; ast.parse(open('/Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec/agents/vigil/agent.py').read())"
pytest tests/test_vigil_*.py --no-cov --tb=short -q | tail -30
```

Expected: no syntax error; all Vigil tests pass.

- [ ] **Step 3: Manual smoke test (one-shot, against live system)**

Activate the virtualenv used by the resident Vigil process, then:

```bash
cd /Users/cirwel/projects/unitares
UNITARES_EMBEDDING_MODEL=bge-m3 UNITARES_ENABLE_HYBRID=1 \
python3 -c "
import asyncio
from agents.vigil.agent import VigilAgent
from unitares_sdk.client import GovernanceClient
async def main():
    v = VigilAgent(with_eval=True, with_hygiene=True)
    print('eval:', await v._run_eval_step())
    async with GovernanceClient(v.mcp_url) as client:
        print('sweep:', await v._run_stale_opens_sweep(client))
asyncio.run(main())
"
```

Expected: eval prints metrics dict with nDCG@10, Recall@20, etc. + a baseline name + delta. Sweep prints up to 20 stale-open dicts. If either fails, capture stderr and resolve before final commit.

- [ ] **Step 4: Commit**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec add agents/vigil/agent.py
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec commit -m "feat(vigil): wire eval step into run_cycle as step 4.7

Posts nDCG@10 + p95 + delta vs config-matched baseline into cycle
findings. Regression (>0.05 absolute nDCG drop) increments issue count
and surfaces a ⚠ line. Cycle-state captures eval_ndcg10, eval_baseline,
eval_regression for dashboard panel consumption."
```

---

## Final Verification

- [ ] **Step 1: Run the full pre-commit test cache**

```bash
cd /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec
./scripts/dev/test-cache.sh
```

Expected: green. If failures appear:
1. First check whether the same test fails on `master` — `git -C /Users/cirwel/projects/unitares status` and `git -C /Users/cirwel/projects/unitares log master..spec/kg-hygiene-v1`. Per project memory, baseline failures are NOT regressions from this branch.
2. Fix any failures genuinely caused by this branch before merging.

- [ ] **Step 2: Push + open PR**

```bash
git -C /Users/cirwel/projects/unitares/.worktrees/kg-hygiene-v1-spec push -u origin spec/kg-hygiene-v1
```

Then open a PR from `spec/kg-hygiene-v1` → `master`. Title: `KG hygiene v1 — supersedes field, Vigil eval step, stale-opens sweep`. Body should reference the spec doc path and list the 9 implementing commits.

- [ ] **Step 3: Worktree cleanup (after PR merges)**

After merge, from the main checkout:

```bash
git -C /Users/cirwel/projects/unitares worktree remove .worktrees/kg-hygiene-v1-spec
git -C /Users/cirwel/projects/unitares branch -d spec/kg-hygiene-v1
```

---

## Success Criteria Recap (from spec)

After 2 weeks of v1 in production:
- ≥1 `superseded` discovery flipped via `supersedes:` field (proves Item 1).
- Vigil summary contains an `eval:` line every cycle, with observable nDCG@10 delta.
- Vigil summary contains `stale_open:` block when stale opens exist.
- Zero new alerts/incidents from eval-step latency or supersedes-check latency.

Volume data captured for v2 sizing:
- Count of `supersedes:` invocations / week.
- Count of stale-open candidates / cycle (sizes any future propose-queue table).
- Count of nDCG regressions caught (validates the 0.05 threshold).
