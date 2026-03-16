"""
Pytest configuration and fixtures for governance-mcp-v1 tests.
"""
import pytest
import pytest_asyncio
import warnings
import sys
from collections import defaultdict, deque
from unittest.mock import AsyncMock

# Filter ResourceWarnings globally before any imports
warnings.filterwarnings("ignore", category=ResourceWarning)


def pytest_configure(config):
    """Configure pytest to filter ResourceWarnings from SQLite."""
    # This catches warnings during collection phase
    warnings.filterwarnings(
        "ignore",
        message="unclosed database",
        category=ResourceWarning
    )


@pytest.fixture(autouse=True)
def _isolate_db_backend(monkeypatch):
    """
    Prevent tests from accidentally connecting to production PostgreSQL.

    Sets a mock DB backend as the get_db() singleton, so any code path that
    reaches get_db() without explicit mocking gets a safe no-op mock instead
    of a real database connection. This prevents ghost agents from being
    created in the production database during test runs.

    Tests that need real DB access (e.g. test_postgres_backend_integration.py)
    create their own backend instances directly, bypassing get_db().

    Tests that already mock at higher levels (agent_storage, get_db patches)
    are unaffected — their mocks intercept before reaching the singleton.
    """
    import src.db as db_module
    import src.agent_storage as storage_module

    mock_backend = AsyncMock()
    # Identity operations
    mock_backend.get_identity.return_value = None
    mock_backend.get_identity_by_id.return_value = None
    mock_backend.upsert_identity.return_value = 1
    mock_backend.upsert_agent.return_value = True
    mock_backend.update_agent_fields.return_value = True
    mock_backend.list_identities.return_value = []
    mock_backend.update_identity_status.return_value = True
    mock_backend.update_identity_metadata.return_value = True
    mock_backend.verify_api_key.return_value = True
    mock_backend.get_agent_label.return_value = None
    mock_backend.find_agent_by_label.return_value = None
    # Session operations
    mock_backend.create_session.return_value = True
    mock_backend.get_session.return_value = None
    mock_backend.update_session_activity.return_value = True
    mock_backend.end_session.return_value = True
    mock_backend.get_active_sessions_for_identity.return_value = []
    mock_backend.cleanup_expired_sessions.return_value = 0
    # State operations
    mock_backend.record_agent_state.return_value = 1
    mock_backend.get_latest_agent_state.return_value = None
    mock_backend.get_agent_state_history.return_value = []
    # Audit/tool operations
    mock_backend.append_audit_event.return_value = True
    mock_backend.query_audit_events.return_value = []
    mock_backend.search_audit_events.return_value = []
    mock_backend.append_tool_usage.return_value = True
    mock_backend.query_tool_usage.return_value = []
    # Calibration
    mock_backend.get_calibration.return_value = {}
    mock_backend.update_calibration.return_value = True
    # Graph
    mock_backend.graph_query.return_value = []
    mock_backend.graph_available.return_value = False
    # Dialectic
    mock_backend.create_dialectic_session.return_value = {"session_id": "test", "created": True}
    mock_backend.get_dialectic_session.return_value = None
    mock_backend.get_dialectic_session_by_agent.return_value = None
    mock_backend.get_all_active_dialectic_sessions_for_agent.return_value = []
    mock_backend.update_dialectic_session_phase.return_value = True
    mock_backend.update_dialectic_session_reviewer.return_value = True
    mock_backend.add_dialectic_message.return_value = 1
    mock_backend.resolve_dialectic_session.return_value = True
    mock_backend.is_agent_in_active_dialectic_session.return_value = False
    mock_backend.get_pending_dialectic_sessions.return_value = []
    # Health
    mock_backend.init.return_value = None
    mock_backend.close.return_value = None
    mock_backend.health_check.return_value = {"status": "ok", "backend": "test_mock"}
    # acquire() — must be a regular (non-async) call returning an async context manager
    from unittest.mock import MagicMock
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_conn.fetchval.return_value = None
    mock_conn.fetchrow.return_value = None
    mock_conn.execute.return_value = "SELECT 0"
    mock_backend.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    # Set mock as the singleton — ALL get_db() calls return this
    monkeypatch.setattr(db_module, "_db_instance", mock_backend)
    # Clear the db-ready cache so _ensure_db_ready() doesn't skip init
    storage_module._db_ready_cache.clear()

    yield mock_backend

    # monkeypatch auto-restores _db_instance on teardown
    storage_module._db_ready_cache.clear()


@pytest.fixture(autouse=True)
def _neutralize_metadata_loading(monkeypatch):
    """
    Prevent ensure_metadata_loaded() from trying to connect to PostgreSQL.

    Sets _metadata_loaded = True in agent_state so the fast-path returns
    immediately. Tests that need to exercise metadata loading should
    explicitly set _metadata_loaded = False and mock load_metadata_async.
    """
    try:
        import src.agent_state as agent_state
        monkeypatch.setattr(agent_state, '_metadata_loaded', True)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_identity_state():
    """
    Reset all in-memory identity and session state between tests.

    Without this, each test that triggers dispatch or identity resolution
    accumulates ghost agent entries in shared module-level dicts. These
    persist across the entire test session because Python module globals
    survive between test functions.

    Clears:
    - _session_identities: session -> agent binding cache
    - _uuid_prefix_index: UUID prefix -> full UUID lookup
    - agent_metadata / monitors: server-level agent registries
    - pattern tracker per-agent state
    - middleware _tool_call_history: rate-limit loop detection
    - contextvars: session_context, mcp_session_id, transport_client_hint,
      session_signals, trajectory_confidence
    """
    yield

    # --- identity_shared module-level caches ---
    try:
        from src.mcp_handlers.identity.shared import (
            _session_identities, _uuid_prefix_index,
        )
        _session_identities.clear()
        _uuid_prefix_index.clear()
    except Exception:
        pass

    # --- agent_state (canonical) + mcp_server_std (re-exports) agent_metadata & monitors ---
    try:
        if 'src.agent_state' in sys.modules:
            mod = sys.modules['src.agent_state']
            if hasattr(mod, 'agent_metadata'):
                mod.agent_metadata.clear()
            if hasattr(mod, 'monitors'):
                mod.monitors.clear()
            # Reset metadata loading state so ensure_metadata_loaded doesn't carry over
            mod._metadata_loaded = False
            mod._metadata_loading = False
            mod._metadata_loaded_event.clear()
    except Exception:
        pass
    try:
        if 'src.mcp_server_std' in sys.modules:
            mcp = sys.modules['src.mcp_server_std']
            if hasattr(mcp, 'agent_metadata'):
                mcp.agent_metadata.clear()
            if hasattr(mcp, 'monitors'):
                mcp.monitors.clear()
    except Exception:
        pass

    # --- pattern tracker per-agent state ---
    try:
        from src.pattern_tracker import get_pattern_tracker
        tracker = get_pattern_tracker()
        if hasattr(tracker, 'pattern_history'):
            tracker.pattern_history.clear()
        if hasattr(tracker, 'investigations'):
            tracker.investigations.clear()
        if hasattr(tracker, 'hypotheses'):
            tracker.hypotheses.clear()
    except Exception:
        pass

    # --- dialectic session in-memory state ---
    try:
        from src.mcp_handlers.dialectic.session import (
            ACTIVE_SESSIONS, _SESSION_METADATA_CACHE,
        )
        ACTIVE_SESSIONS.clear()
        _SESSION_METADATA_CACHE.clear()
    except Exception:
        pass

    # --- middleware rate-limit loop history ---
    try:
        from src.mcp_handlers import middleware
        middleware._tool_call_history.clear()
    except Exception:
        pass

    # --- contextvars (reset to defaults) ---
    try:
        from src.mcp_handlers.context import (
            _session_context,
            _mcp_session_id,
            _transport_client_hint,
            _session_signals,
            _trajectory_confidence,
            _session_resolution_source,
        )
        # Reset each contextvar to its default by setting then immediately
        # using the ContextVar default mechanism
        _session_context.set({})
        _mcp_session_id.set(None)
        _transport_client_hint.set(None)
        _session_signals.set(None)
        _trajectory_confidence.set(None)
        _session_resolution_source.set(None)
    except Exception:
        pass


@pytest.fixture(autouse=True, scope="session")
def _cleanup_stale_ghost_files():
    """Remove test agent files left over from previous test runs."""
    from pathlib import Path
    agents_dir = Path(__file__).parent.parent / "data" / "agents"
    if agents_dir.exists():
        for pattern in ["test_*_state.json", ".test_*_state.lock",
                        "mcp_*test*_state.json", ".mcp_*test*_state.lock"]:
            for f in agents_dir.glob(pattern):
                try:
                    f.unlink()
                except Exception:
                    pass
    yield


@pytest.fixture(autouse=True)
def _cleanup_ghost_agent_state_files():
    """
    Remove agent state files created during each test.

    Tests that call dispatch_tool("process_agent_update") or create
    UNITARESMonitor instances with load_state=True auto-save state to
    data/agents/{agent_id}_state.json. Without per-test cleanup, these
    accumulate and can cause cross-test contamination.
    """
    from pathlib import Path
    agents_dir = Path(__file__).parent.parent / "data" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    pre_existing = set(agents_dir.iterdir())

    yield

    # Remove files created during this test
    for f in agents_dir.iterdir():
        if f not in pre_existing:
            try:
                f.unlink()
            except Exception:
                pass


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary database path for tests."""
    db_path = tmp_path / "test.db"
    yield db_path
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest_asyncio.fixture
async def live_postgres_backend():
    """
    Provide a real PostgresBackend connected to governance_test.

    Use for integration tests that need live DB. Skips if governance_test
    is unavailable. Schema is bootstrapped and tables truncated per test.
    See tests.test_db_utils for primitives.
    """
    from tests.test_db_utils import (
        TEST_DB_URL,
        can_connect_to_test_db,
        ensure_test_database_schema,
        TRUNCATE_SQL,
        CALIBRATION_RESET_SQL,
    )

    if not can_connect_to_test_db():
        pytest.skip("governance_test database not available")

    await ensure_test_database_schema()

    import os
    os.environ["DB_POSTGRES_URL"] = TEST_DB_URL
    os.environ["DB_POSTGRES_MIN_CONN"] = "1"
    os.environ["DB_POSTGRES_MAX_CONN"] = "3"
    os.environ["DB_AGE_GRAPH"] = "governance_graph"

    from src.db.postgres_backend import PostgresBackend

    be = PostgresBackend()
    await be.init()

    async with be.acquire() as conn:
        await conn.execute(TRUNCATE_SQL)
        await conn.execute(CALIBRATION_RESET_SQL)

    yield be
    await be.close()
