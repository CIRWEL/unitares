# Temporal Narrator Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a temporal narrator to governance that injects relative, contextual time awareness into onboarding and check-in responses — but only when time is telling the agent something worth knowing.

**Architecture:** A single module `src/temporal.py` with one async function `build_temporal_context()`. It reads existing timestamped data from `core.sessions`, `core.agent_state`, and `knowledge.discoveries`. It returns a short plain-text string when thresholds are crossed, or `None` when time is unremarkable. Injected via the async onboard handler (after `_build_onboard_response()` returns) and the enrichment pipeline.

**Tech Stack:** Python 3.12, asyncio, PostgreSQL (existing tables), pytest

**Spec:** `docs/superpowers/specs/2026-03-13-temporal-narrator-design.md`

---

## Chunk 1: Config and Database Queries

### Task 1: Add temporal narrator config to governance_config.py

**Files:**
- Modify: `config/governance_config.py` (add before `# Export singleton config` comment at line 592)
- Test: `tests/test_temporal.py` (new)

- [ ] **Step 1: Write config test**

```python
# tests/test_temporal.py
"""Tests for temporal narrator."""
from config.governance_config import GovernanceConfig


def test_temporal_config_exists():
    """Temporal narrator thresholds are defined in config."""
    assert hasattr(GovernanceConfig, 'TEMPORAL_LONG_SESSION_HOURS')
    assert hasattr(GovernanceConfig, 'TEMPORAL_GAP_HOURS')
    assert hasattr(GovernanceConfig, 'TEMPORAL_IDLE_MINUTES')
    assert hasattr(GovernanceConfig, 'TEMPORAL_CROSS_AGENT_MINUTES')
    assert hasattr(GovernanceConfig, 'TEMPORAL_HIGH_CHECKIN_COUNT')
    assert hasattr(GovernanceConfig, 'TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES')


def test_temporal_config_values():
    """Config values are sensible defaults."""
    assert GovernanceConfig.TEMPORAL_LONG_SESSION_HOURS == 2
    assert GovernanceConfig.TEMPORAL_GAP_HOURS == 24
    assert GovernanceConfig.TEMPORAL_IDLE_MINUTES == 30
    assert GovernanceConfig.TEMPORAL_CROSS_AGENT_MINUTES == 60
    assert GovernanceConfig.TEMPORAL_HIGH_CHECKIN_COUNT == 10
    assert GovernanceConfig.TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py -v -x`
Expected: FAIL — attributes don't exist yet

- [ ] **Step 3: Add config constants**

Add to `config/governance_config.py` before line 592 (before `# Export singleton config`):

```python
    # =================================================================
    # Temporal Narrator Configuration
    # =================================================================

    TEMPORAL_LONG_SESSION_HOURS = 2       # Signal when session exceeds this
    TEMPORAL_GAP_HOURS = 24               # Signal when gap since last session exceeds this
    TEMPORAL_IDLE_MINUTES = 30            # Signal when idle within session exceeds this
    TEMPORAL_CROSS_AGENT_MINUTES = 60     # Surface cross-agent activity within this window
    TEMPORAL_HIGH_CHECKIN_COUNT = 10      # High density: this many check-ins...
    TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES = 30  # ...within this window
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py -v -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add config/governance_config.py tests/test_temporal.py
git commit -m "add temporal narrator config thresholds"
```

---

### Task 2: Add database query for most recent inactive session

**Files:**
- Modify: `src/db/mixins/session.py` (add new method after `get_active_sessions_for_identity` at line 106)
- Test: `tests/test_temporal.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/test_temporal.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


def test_get_last_inactive_session_exists():
    """SessionMixin has get_last_inactive_session method."""
    from src.db.mixins.session import SessionMixin
    assert hasattr(SessionMixin, 'get_last_inactive_session')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_get_last_inactive_session_exists -v -x`
Expected: FAIL — method doesn't exist

- [ ] **Step 3: Add the query method**

Add to `src/db/mixins/session.py` after `get_active_sessions_for_identity` (after line 106):

```python
    async def get_last_inactive_session(
        self,
        identity_id: int,
    ) -> Optional[SessionRecord]:
        """Get most recent inactive session for an identity."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.session_id, s.identity_id, i.agent_id, s.created_at, s.last_active,
                       s.expires_at, s.is_active, s.client_type, s.client_info, s.metadata
                FROM core.sessions s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id = $1 AND s.is_active = FALSE
                ORDER BY s.last_active DESC
                LIMIT 1
                """,
                identity_id,
            )
            if not row:
                return None
            return self._row_to_session(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_get_last_inactive_session_exists -v -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/db/mixins/session.py tests/test_temporal.py
git commit -m "add get_last_inactive_session query"
```

---

### Task 3: Add cross-agent activity query to database

**Files:**
- Modify: `src/db/mixins/state.py` (add new method after `get_all_latest_agent_states`)
- Test: `tests/test_temporal.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/test_temporal.py`:

```python
def test_cross_agent_activity_method_exists():
    """StateMixin has get_recent_cross_agent_activity method."""
    from src.db.mixins.state import StateMixin
    assert hasattr(StateMixin, 'get_recent_cross_agent_activity')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_cross_agent_activity_method_exists -v -x`
Expected: FAIL

- [ ] **Step 3: Add the query method**

Add to `src/db/mixins/state.py` after `get_all_latest_agent_states`:

```python
    async def get_recent_cross_agent_activity(
        self,
        exclude_identity_id: int,
        minutes: int = 60,
    ) -> list[dict]:
        """Get recent activity from other agents, grouped by agent.

        Returns list of dicts with agent_id, recorded_at (most recent), count.
        """
        from config.governance_config import GovernanceConfig
        window = minutes or GovernanceConfig.TEMPORAL_CROSS_AGENT_MINUTES
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT i.agent_id,
                       MAX(s.recorded_at) as recorded_at,
                       COUNT(*) as count
                FROM core.agent_state s
                JOIN core.identities i ON i.identity_id = s.identity_id
                WHERE s.identity_id != $1
                  AND s.recorded_at > now() - ($2 * interval '1 minute')
                GROUP BY i.agent_id
                ORDER BY MAX(s.recorded_at) DESC
                LIMIT 5
                """,
                exclude_identity_id, window,
            )
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_cross_agent_activity_method_exists -v -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/db/mixins/state.py tests/test_temporal.py
git commit -m "add cross-agent activity query"
```

---

### Task 4: Add `created_after` filter to `kg_query`

The existing `kg_query` in `src/db/mixins/knowledge_graph.py` does not accept a `created_after` parameter. The temporal narrator needs to query discoveries added since a given timestamp.

**Files:**
- Modify: `src/db/mixins/knowledge_graph.py:73-81` (add `created_after` parameter)
- Test: `tests/test_temporal.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/test_temporal.py`:

```python
import inspect

def test_kg_query_accepts_created_after():
    """kg_query accepts a created_after parameter."""
    from src.db.mixins.knowledge_graph import KnowledgeGraphMixin
    sig = inspect.signature(KnowledgeGraphMixin.kg_query)
    assert 'created_after' in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_kg_query_accepts_created_after -v -x`
Expected: FAIL

- [ ] **Step 3: Add `created_after` parameter to `kg_query`**

In `src/db/mixins/knowledge_graph.py`, modify the `kg_query` method signature (line 73) to add `created_after`:

```python
    async def kg_query(
        self,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        created_after: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
```

Then add the filter condition inside the method body, after the `tags` condition block (after the existing `param_idx += 1` for tags):

```python
            if created_after:
                conditions.append(f"created_at > ${param_idx}")
                params.append(created_after)
                param_idx += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_kg_query_accepts_created_after -v -x`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/db/mixins/knowledge_graph.py tests/test_temporal.py
git commit -m "add created_after filter to kg_query"
```

---

## Chunk 2: Core Function

### Task 5: Build the core temporal narrator function

**Files:**
- Create: `src/temporal.py`
- Test: `tests/test_temporal.py` (append)

**Dependencies:** Tasks 1-4 must be completed first (config, all DB queries).

- [ ] **Step 1: Write tests for the narrator**

Append to `tests/test_temporal.py`:

```python
from src.temporal import build_temporal_context, _format_duration


# ─── Duration formatter tests ─────────────────────────────────────

def test_format_duration_seconds():
    assert _format_duration(timedelta(seconds=30)) == "30s"

def test_format_duration_minutes():
    assert _format_duration(timedelta(minutes=15)) == "15min"

def test_format_duration_hours():
    assert _format_duration(timedelta(hours=3, minutes=12)) == "3h 12min"

def test_format_duration_exact_hours():
    assert _format_duration(timedelta(hours=2)) == "2h"

def test_format_duration_one_day():
    assert _format_duration(timedelta(days=1)) == "1 day"

def test_format_duration_multiple_days():
    assert _format_duration(timedelta(days=5)) == "5 days"

def test_format_duration_zero():
    assert _format_duration(timedelta(seconds=0)) == "0s"


# ─── Core narrator tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_temporal_silence_when_unremarkable(mock_db):
    """Returns None when nothing temporal is noteworthy."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(minutes=30))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_temporal_long_session(mock_db):
    """Signals when session exceeds threshold."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(hours=3, minutes=12))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "3h" in result


@pytest.mark.asyncio
async def test_temporal_long_gap(mock_db):
    """Signals when gap since last session is large."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(minutes=5))
    ]
    mock_db.get_last_inactive_session.return_value = MagicMock(
        last_active=now - timedelta(days=2)
    )
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "2 days" in result


@pytest.mark.asyncio
async def test_temporal_idle(mock_db):
    """Signals when idle within session exceeds threshold."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(hours=1))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=45)
    )
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "45min" in result


@pytest.mark.asyncio
async def test_temporal_cross_agent(mock_db):
    """Surfaces cross-agent activity."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(minutes=10))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_recent_cross_agent_activity.return_value = [
        {"agent_id": "other-agent", "recorded_at": now - timedelta(minutes=14), "count": 3}
    ]
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "agent" in result.lower()


@pytest.mark.asyncio
async def test_temporal_new_discoveries(mock_db):
    """Surfaces discoveries added since last session."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(minutes=5))
    ]
    mock_db.get_last_inactive_session.return_value = MagicMock(
        last_active=now - timedelta(days=1, hours=2)
    )
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = [
        {"id": "d1", "summary": "found a bug"},
        {"id": "d2", "summary": "pattern discovered"},
        {"id": "d3", "summary": "insight noted"},
    ]

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "3" in result
    assert "discover" in result.lower() or "knowledge" in result.lower()


@pytest.mark.asyncio
async def test_temporal_high_checkin_density(mock_db):
    """Signals when check-in density is high."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(minutes=25))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=1)
    )
    # 14 check-ins in 22 minutes — high density
    mock_db.get_agent_state_history.return_value = [
        MagicMock(recorded_at=now - timedelta(minutes=i * 1.5))
        for i in range(14)
    ]
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "14" in result or "high" in result.lower()


@pytest.mark.asyncio
async def test_temporal_identity_not_found(mock_db):
    """Returns None gracefully when identity doesn't exist."""
    mock_db.get_identity.return_value = None

    result = await build_temporal_context("nonexistent-uuid", mock_db)
    assert result is None


@pytest.mark.asyncio
async def test_temporal_multiple_signals(mock_db):
    """Combines multiple temporal signals into one string."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=now - timedelta(hours=3))
    ]
    mock_db.get_last_inactive_session.return_value = MagicMock(
        last_active=now - timedelta(days=3)
    )
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_agent_state_history.return_value = []
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    assert result is not None
    assert "3h" in result
    assert "3 days" in result


@pytest.mark.asyncio
async def test_temporal_partial_db_failure(mock_db):
    """One query failing doesn't crash the whole function."""
    now = datetime.now(timezone.utc)

    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    # Session query raises
    mock_db.get_active_sessions_for_identity.side_effect = Exception("db down")
    # But gap query works and has signal
    mock_db.get_last_inactive_session.return_value = MagicMock(
        last_active=now - timedelta(days=5)
    )
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=now - timedelta(minutes=2)
    )
    mock_db.get_agent_state_history.return_value = []
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    result = await build_temporal_context("test-uuid", mock_db)
    # Should still return the gap signal despite session query failing
    assert result is not None
    assert "5 days" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py -v -x -k "not test_temporal_config and not test_get_last and not test_cross_agent_activity and not test_kg_query"`
Expected: FAIL — `src.temporal` doesn't exist

- [ ] **Step 3: Write the temporal narrator module**

Create `src/temporal.py`:

```python
"""
Temporal Narrator — contextual time awareness for agents.

Silence by default, signal when time matters.
Reads existing timestamped data and produces short, relative,
human-readable temporal context when thresholds are crossed.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from config.governance_config import GovernanceConfig
from src.logging_utils import get_logger

logger = get_logger(__name__)


def _format_duration(td: timedelta) -> str:
    """Format a timedelta as a human-readable relative string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    remaining_min = minutes % 60
    if hours < 24:
        if remaining_min:
            return f"{hours}h {remaining_min}min"
        return f"{hours}h"
    days = hours // 24
    if days == 1:
        return "1 day"
    return f"{days} days"


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def build_temporal_context(
    agent_id: str,
    db,
    include_cross_agent: bool = True,
) -> Optional[str]:
    """
    Build temporal context string for an agent.

    Returns None if time is unremarkable. Returns a short plain-text
    string when one or more temporal thresholds are crossed.
    """
    try:
        now = datetime.now(timezone.utc)
        signals = []

        # Resolve identity
        identity = await db.get_identity(agent_id)
        if not identity:
            return None
        identity_id = identity.identity_id

        # Current session duration
        try:
            sessions = await db.get_active_sessions_for_identity(identity_id)
            if sessions:
                session_start = _ensure_utc(sessions[0].created_at)
                session_duration = now - session_start
                if session_duration > timedelta(hours=GovernanceConfig.TEMPORAL_LONG_SESSION_HOURS):
                    signals.append(f"Session: {_format_duration(session_duration)}.")
        except Exception as e:
            logger.debug(f"Temporal: session query failed: {e}")

        # Gap since last session
        last_session_end = None
        try:
            last_session = await db.get_last_inactive_session(identity_id)
            if last_session and last_session.last_active:
                last_session_end = _ensure_utc(last_session.last_active)
                gap = now - last_session_end
                if gap > timedelta(hours=GovernanceConfig.TEMPORAL_GAP_HOURS):
                    signals.append(f"Last session: {_format_duration(gap)} ago.")
        except Exception as e:
            logger.debug(f"Temporal: gap query failed: {e}")

        # Idle within session (time since last check-in)
        try:
            latest_state = await db.get_latest_agent_state(identity_id)
            if latest_state and latest_state.recorded_at:
                recorded = _ensure_utc(latest_state.recorded_at)
                idle = now - recorded
                if idle > timedelta(minutes=GovernanceConfig.TEMPORAL_IDLE_MINUTES):
                    signals.append(f"Idle: {_format_duration(idle)} since last check-in.")
        except Exception as e:
            logger.debug(f"Temporal: idle query failed: {e}")

        # High check-in density
        try:
            window = timedelta(minutes=GovernanceConfig.TEMPORAL_HIGH_CHECKIN_WINDOW_MINUTES)
            history = await db.get_agent_state_history(identity_id, limit=50)
            cutoff = now - window
            recent_count = sum(
                1 for s in history
                if _ensure_utc(s.recorded_at) > cutoff
            )
            if recent_count >= GovernanceConfig.TEMPORAL_HIGH_CHECKIN_COUNT:
                signals.append(f"High activity: {recent_count} check-ins in {_format_duration(window)}.")
        except Exception as e:
            logger.debug(f"Temporal: density query failed: {e}")

        # Cross-agent activity
        if include_cross_agent:
            try:
                cross_activity = await db.get_recent_cross_agent_activity(identity_id)
                if cross_activity:
                    entry = cross_activity[0]
                    agent_time = _ensure_utc(entry.get("recorded_at", now))
                    ago = _format_duration(now - agent_time)
                    count = entry.get("count", 1)
                    signals.append(f"Another agent active {ago} ago ({count} updates).")
            except Exception as e:
                logger.debug(f"Temporal: cross-agent query failed: {e}")

        # New discoveries since last session
        if last_session_end:
            try:
                discoveries = await db.kg_query(
                    created_after=last_session_end.isoformat(),
                    limit=50,
                )
                if discoveries:
                    count = len(discoveries)
                    signals.append(
                        f"{count} knowledge graph {'entry' if count == 1 else 'entries'} "
                        f"added since last session."
                    )
            except Exception as e:
                logger.debug(f"Temporal: discovery query failed: {e}")

        if not signals:
            return None

        return " ".join(signals)

    except Exception as e:
        logger.debug(f"Temporal narrator failed: {e}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py -v -x`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/temporal.py tests/test_temporal.py
git commit -m "add temporal narrator core function"
```

---

## Chunk 3: Integration

### Task 6: Inject temporal context into onboarding response

`_build_onboard_response()` is a sync function (defined with `def`, not `async def`). The temporal narrator is async. Therefore, inject the temporal context in the async **caller** (`handle_onboard_v2`) after `_build_onboard_response()` returns, not inside the sync function itself.

**Files:**
- Modify: `src/mcp_handlers/identity/handlers.py` (in `handle_onboard_v2`, after line ~960 where `result = _build_onboard_response(...)` returns)
- Test: `tests/test_temporal.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/test_temporal.py`:

```python
from unittest.mock import patch


@pytest.mark.asyncio
async def test_temporal_context_injected_into_onboard_result():
    """Temporal context is added to onboard result dict when relevant."""
    from src.temporal import build_temporal_context

    mock_db = AsyncMock()
    mock_db.get_identity.return_value = MagicMock(identity_id=1)
    mock_db.get_active_sessions_for_identity.return_value = [
        MagicMock(created_at=datetime.now(timezone.utc) - timedelta(hours=4))
    ]
    mock_db.get_last_inactive_session.return_value = None
    mock_db.get_latest_agent_state.return_value = MagicMock(
        recorded_at=datetime.now(timezone.utc) - timedelta(minutes=2)
    )
    mock_db.get_agent_state_history.return_value = []
    mock_db.get_recent_cross_agent_activity.return_value = []
    mock_db.kg_query.return_value = []

    # Simulate what the onboard handler does: call build_temporal_context,
    # then add result to the response dict
    result = {}
    temporal = await build_temporal_context("test-uuid", mock_db)
    if temporal:
        result["temporal_context"] = temporal

    assert "temporal_context" in result
    assert "4h" in result["temporal_context"]
```

- [ ] **Step 2: Run test to verify it passes** (function already exists from Task 5)

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_temporal_context_injected_into_onboard_result -v -x`
Expected: PASS

- [ ] **Step 3: Add temporal context injection to onboard handler**

In `src/mcp_handlers/identity/handlers.py`, find `handle_onboard_v2`. After the line `result = _build_onboard_response(...)` (line ~947-960) and before the return, add:

```python
    # Temporal narrator — contextual time awareness (silence by default)
    try:
        from src.temporal import build_temporal_context
        from src.db import get_db
        temporal = await build_temporal_context(agent_uuid, get_db())
        if temporal:
            result["temporal_context"] = temporal
    except Exception:
        pass  # Temporal narrator is non-critical
```

Note: verify the exact variable name for the agent UUID in scope — should be `agent_uuid` based on the function signature.

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: ALL PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/mcp_handlers/identity/handlers.py tests/test_temporal.py
git commit -m "inject temporal context into onboarding response"
```

---

### Task 7: Add temporal narrator as a check-in enrichment

**Files:**
- Modify: `src/mcp_handlers/updates/enrichments.py` (add new enrichment function)
- Test: `tests/test_temporal.py` (append)

- [ ] **Step 1: Write the test**

Append to `tests/test_temporal.py`:

```python
@pytest.mark.asyncio
async def test_temporal_enrichment():
    """Temporal enrichment adds temporal_context to response_data."""
    from src.mcp_handlers.updates.context import UpdateContext

    ctx = UpdateContext()
    ctx.agent_uuid = "test-uuid"
    ctx.response_data = {}

    with patch("src.mcp_handlers.updates.enrichments.build_temporal_context", new_callable=AsyncMock) as mock_btc:
        mock_btc.return_value = "Session: 3h 12min."

        from src.mcp_handlers.updates.enrichments import enrich_temporal_context
        await enrich_temporal_context(ctx)

        assert ctx.response_data.get("temporal_context") == "Session: 3h 12min."


@pytest.mark.asyncio
async def test_temporal_enrichment_silence():
    """Temporal enrichment adds nothing when time is unremarkable."""
    from src.mcp_handlers.updates.context import UpdateContext

    ctx = UpdateContext()
    ctx.agent_uuid = "test-uuid"
    ctx.response_data = {}

    with patch("src.mcp_handlers.updates.enrichments.build_temporal_context", new_callable=AsyncMock) as mock_btc:
        mock_btc.return_value = None

        from src.mcp_handlers.updates.enrichments import enrich_temporal_context
        await enrich_temporal_context(ctx)

        assert "temporal_context" not in ctx.response_data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py::test_temporal_enrichment -v -x`
Expected: FAIL — `enrich_temporal_context` doesn't exist

- [ ] **Step 3: Add the enrichment**

Add to `src/mcp_handlers/updates/enrichments.py` after the last existing enrichment:

```python
# ─── Temporal Context ──────────────────────────────────────────────────

from src.temporal import build_temporal_context

@enrichment(order=215)
async def enrich_temporal_context(ctx: UpdateContext) -> None:
    """Inject temporal awareness when time is telling the agent something."""
    try:
        from src.db import get_db
        temporal = await build_temporal_context(ctx.agent_uuid, get_db())
        if temporal:
            ctx.response_data['temporal_context'] = temporal
    except Exception as e:
        logger.debug(f"Could not enrich temporal context: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_temporal.py -v -x`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: ALL PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/mcp_handlers/updates/enrichments.py tests/test_temporal.py
git commit -m "add temporal narrator enrichment to check-in pipeline"
```

---

### Task 8: Final validation

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: ALL PASS

- [ ] **Step 2: Manual smoke test**

Restart governance service and verify temporal context appears in onboarding:

```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
# Wait 5 seconds, then call onboard() via MCP and check for temporal_context field
```

- [ ] **Step 3: Verify silence**

In a fresh session with no long gaps or unusual state, verify that `temporal_context` is absent from onboarding and check-in responses. Silence is the default.
