"""
Tests for src/mcp_handlers/lifecycle.py - Agent lifecycle handler functions.

Tests list_agents (lite mode), archive_agent, delete_agent, ping_agent
with mocked mcp_server and agent_storage.
"""

import pytest
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================================
# Helpers
# ============================================================================

def make_agent_meta(
    status="active",
    label=None,
    purpose=None,
    total_updates=5,
    last_update=None,
    tags=None,
    trust_tier=None,
    **kwargs,
):
    """Create a mock AgentMetadata object."""
    if last_update is None:
        last_update = datetime.now(timezone.utc).isoformat()
    meta = SimpleNamespace(
        status=status,
        label=label,
        purpose=purpose,
        total_updates=total_updates,
        last_update=last_update,
        tags=tags or [],
        trust_tier=trust_tier,
        archived_at=None,
        lifecycle_events=[],
        **kwargs,
    )
    meta.add_lifecycle_event = MagicMock()
    meta.to_dict = MagicMock(return_value={"status": status, "label": label})
    return meta


# ============================================================================
# list_agents (lite mode)
# ============================================================================

class TestListAgentsLite:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata = MagicMock()
        server.load_metadata_async = AsyncMock()
        return server

    @pytest.mark.asyncio
    async def test_empty_metadata(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True})

            data = json.loads(result[0].text)
            assert data["agents"] == []
            assert data["total_all"] == 0

    @pytest.mark.asyncio
    async def test_lists_active_agents(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            "a1": make_agent_meta(label="Alpha", total_updates=10),
            "a2": make_agent_meta(label="Beta", total_updates=3),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True})

            data = json.loads(result[0].text)
            assert data["total_all"] == 2
            assert len(data["agents"]) == 2

    @pytest.mark.asyncio
    async def test_filters_test_agents(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            "real-agent": make_agent_meta(label="Real"),
            "test_agent_1": make_agent_meta(label="Test"),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True, "include_test_agents": False})

            data = json.loads(result[0].text)
            ids = [a["id"] for a in data["agents"]]
            assert "real-agent" in ids
            assert "test_agent_1" not in ids

    @pytest.mark.asyncio
    async def test_includes_test_agents_when_requested(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            "real-agent": make_agent_meta(label="Real"),
            "test_agent_1": make_agent_meta(label="Test"),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True, "include_test_agents": True})

            data = json.loads(result[0].text)
            ids = [a["id"] for a in data["agents"]]
            assert "test_agent_1" in ids

    @pytest.mark.asyncio
    async def test_filters_archived_agents(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            "active-1": make_agent_meta(status="active"),
            "archived-1": make_agent_meta(status="archived"),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True, "status_filter": "active"})

            data = json.loads(result[0].text)
            ids = [a["id"] for a in data["agents"]]
            assert "active-1" in ids
            assert "archived-1" not in ids

    @pytest.mark.asyncio
    async def test_respects_limit(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            f"agent-{i}": make_agent_meta(label=f"Agent {i}", total_updates=i)
            for i in range(10)
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True, "limit": 3})

            data = json.loads(result[0].text)
            assert data["shown"] == 3
            assert len(data["agents"]) == 3

    @pytest.mark.asyncio
    async def test_filters_stale_agents_by_recency(self, mock_mcp_server):
        recent = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        mock_mcp_server.agent_metadata = {
            "recent-agent": make_agent_meta(last_update=recent),
            "old-agent": make_agent_meta(last_update=old),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_list_agents
            result = await handle_list_agents({"lite": True, "recent_days": 7})

            data = json.loads(result[0].text)
            ids = [a["id"] for a in data["agents"]]
            assert "recent-agent" in ids
            assert "old-agent" not in ids


# ============================================================================
# archive_agent
# ============================================================================

class TestArchiveAgent:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata = MagicMock()
        server.load_metadata_async = AsyncMock()
        return server

    @pytest.mark.asyncio
    async def test_archive_success(self, mock_mcp_server):
        meta = make_agent_meta(status="active")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage, \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=True):

            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_agent
            result = await handle_archive_agent({"agent_id": "agent-1"})

            data = json.loads(result[0].text)
            assert data["success"] is True
            assert meta.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_already_archived(self, mock_mcp_server):
        meta = make_agent_meta(status="archived")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)):

            from src.mcp_handlers.lifecycle import handle_archive_agent
            result = await handle_archive_agent({"agent_id": "agent-1"})

            text = result[0].text
            assert "already archived" in text.lower()

    @pytest.mark.asyncio
    async def test_archive_not_found(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)):

            from src.mcp_handlers.lifecycle import handle_archive_agent
            result = await handle_archive_agent({"agent_id": "agent-1"})

            text = result[0].text
            assert "not found" in text.lower() or "error" in text.lower()

    @pytest.mark.asyncio
    async def test_archive_ownership_denied(self, mock_mcp_server):
        meta = make_agent_meta(status="active")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=False):

            from src.mcp_handlers.lifecycle import handle_archive_agent
            result = await handle_archive_agent({"agent_id": "agent-1"})

            text = result[0].text
            assert "auth" in text.lower()


# ============================================================================
# delete_agent
# ============================================================================

class TestDeleteAgent:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata = MagicMock()
        server.load_metadata_async = AsyncMock()
        server.project_root = str(project_root)
        return server

    @pytest.mark.asyncio
    async def test_delete_requires_confirm(self, mock_mcp_server):
        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)):

            from src.mcp_handlers.lifecycle import handle_delete_agent
            result = await handle_delete_agent({"agent_id": "agent-1", "confirm": False})

            text = result[0].text
            assert "confirm" in text.lower()

    @pytest.mark.asyncio
    async def test_delete_pioneer_blocked(self, mock_mcp_server):
        meta = make_agent_meta(status="active", tags=["pioneer"])
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)):

            from src.mcp_handlers.lifecycle import handle_delete_agent
            result = await handle_delete_agent({"agent_id": "agent-1", "confirm": True})

            text = result[0].text
            assert "pioneer" in text.lower() or "cannot delete" in text.lower()

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_mcp_server):
        meta = make_agent_meta(status="active", tags=[])
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage, \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=True):

            mock_storage.delete_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_delete_agent
            result = await handle_delete_agent({
                "agent_id": "agent-1", "confirm": True, "backup_first": False,
            })

            data = json.loads(result[0].text)
            assert data["success"] is True
            assert meta.status == "deleted"

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)):

            from src.mcp_handlers.lifecycle import handle_delete_agent
            result = await handle_delete_agent({"agent_id": "agent-1", "confirm": True})

            text = result[0].text
            assert "not found" in text.lower() or "error" in text.lower()


# ============================================================================
# mark_response_complete
# ============================================================================

class TestMarkResponseComplete:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata = MagicMock()
        server.load_metadata_async = AsyncMock()
        return server

    @pytest.mark.asyncio
    async def test_mark_complete_success(self, mock_mcp_server):
        meta = make_agent_meta(status="active")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage, \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=True), \
             patch("src.knowledge_graph.get_knowledge_graph", new_callable=AsyncMock, side_effect=Exception("no graph")):

            mock_storage.update_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_mark_response_complete
            result = await handle_mark_response_complete({"agent_id": "agent-1"})

            data = json.loads(result[0].text)
            assert data["success"] is True
            assert data["status"] == "waiting_input"
            assert meta.status == "waiting_input"

    @pytest.mark.asyncio
    async def test_mark_complete_with_summary(self, mock_mcp_server):
        meta = make_agent_meta(status="active")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage, \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=True), \
             patch("src.knowledge_graph.get_knowledge_graph", new_callable=AsyncMock, side_effect=Exception("no graph")):

            mock_storage.update_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_mark_response_complete
            result = await handle_mark_response_complete({"agent_id": "agent-1", "summary": "Finished refactoring"})

            data = json.loads(result[0].text)
            assert data["success"] is True
            # lifecycle event should have been called with summary
            meta.add_lifecycle_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_complete_requires_registration(self, mock_mcp_server):
        from mcp.types import TextContent
        error = TextContent(type="text", text='{"error": "not registered"}')

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=(None, error)):

            from src.mcp_handlers.lifecycle import handle_mark_response_complete
            result = await handle_mark_response_complete({})

            assert "not registered" in result[0].text

    @pytest.mark.asyncio
    async def test_mark_complete_ownership_denied(self, mock_mcp_server):
        meta = make_agent_meta(status="active")
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.require_registered_agent", return_value=("agent-1", None)), \
             patch("src.mcp_handlers.utils.verify_agent_ownership", return_value=False):

            from src.mcp_handlers.lifecycle import handle_mark_response_complete
            result = await handle_mark_response_complete({"agent_id": "agent-1"})

            text = result[0].text
            assert "auth" in text.lower()


# ============================================================================
# ping_agent
# ============================================================================

class TestPingAgent:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata_async = AsyncMock()
        server.get_or_create_monitor = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_ping_alive_agent(self, mock_mcp_server):
        recent = datetime.now(timezone.utc).isoformat()
        meta = make_agent_meta(status="active", last_update=recent)
        meta.created_at = recent
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        mock_monitor = MagicMock()
        mock_monitor.get_metrics.return_value = {"E": 0.7}
        mock_mcp_server.get_or_create_monitor.return_value = mock_monitor

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_ping_agent
            result = await handle_ping_agent({"agent_id": "agent-1"})

            data = json.loads(result[0].text)
            assert data["responsive"] is True
            assert data["status"] == "alive"
            assert data["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_ping_stuck_agent(self, mock_mcp_server):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        meta = make_agent_meta(status="active", last_update=old)
        meta.created_at = old
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        mock_monitor = MagicMock()
        mock_monitor.get_metrics.return_value = {"E": 0.7}
        mock_mcp_server.get_or_create_monitor.return_value = mock_monitor

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_ping_agent
            result = await handle_ping_agent({"agent_id": "agent-1"})

            data = json.loads(result[0].text)
            assert data["responsive"] is True
            assert data["status"] == "stuck"  # >30 min old

    @pytest.mark.asyncio
    async def test_ping_not_found(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {}

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_ping_agent
            result = await handle_ping_agent({"agent_id": "nonexistent"})

            text = result[0].text
            assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_ping_unresponsive_agent(self, mock_mcp_server):
        recent = datetime.now(timezone.utc).isoformat()
        meta = make_agent_meta(status="active", last_update=recent)
        meta.created_at = recent
        mock_mcp_server.agent_metadata = {"agent-1": meta}

        mock_monitor = MagicMock()
        mock_monitor.get_metrics.side_effect = RuntimeError("cannot get metrics")
        mock_mcp_server.get_or_create_monitor.return_value = mock_monitor

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server):
            from src.mcp_handlers.lifecycle import handle_ping_agent
            result = await handle_ping_agent({"agent_id": "agent-1"})

            data = json.loads(result[0].text)
            assert data["responsive"] is False
            assert data["status"] == "unresponsive"

    @pytest.mark.asyncio
    async def test_ping_no_agent_id(self, mock_mcp_server):
        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.identity_shared.get_bound_agent_id", return_value=None):
            from src.mcp_handlers.lifecycle import handle_ping_agent
            result = await handle_ping_agent({})

            text = result[0].text
            assert "agent_id" in text.lower()


# ============================================================================
# archive_old_test_agents
# ============================================================================

class TestArchiveOldTestAgents:

    @pytest.fixture
    def mock_mcp_server(self):
        server = MagicMock()
        server.agent_metadata = {}
        server.monitors = {}
        server.load_metadata = MagicMock()
        server.load_metadata_async = AsyncMock()
        return server

    @pytest.mark.asyncio
    async def test_archive_test_agents_dry_run(self, mock_mcp_server):
        # Use naive datetimes (no timezone) - handler strips timezone before comparing
        from datetime import datetime as dt
        recent = dt.now().isoformat()
        old = (dt.now() - timedelta(hours=12)).isoformat()

        mock_mcp_server.agent_metadata = {
            "test_agent_1": make_agent_meta(status="active", last_update=old, total_updates=5),
            "real_agent": make_agent_meta(status="active", last_update=recent, total_updates=10),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage:
            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_old_test_agents
            result = await handle_archive_old_test_agents({"dry_run": True})

            data = json.loads(result[0].text)
            assert data["dry_run"] is True
            # test_agent_1 should be found (12h old > 6h default)
            assert data["archived_count"] >= 1
            # But dry_run means nothing was actually archived
            mock_storage.archive_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_archive_low_update_test_agents(self, mock_mcp_server):
        recent = datetime.now(timezone.utc).isoformat()
        mock_mcp_server.agent_metadata = {
            "test_ping_1": make_agent_meta(status="active", last_update=recent, total_updates=1),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage:
            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_old_test_agents
            result = await handle_archive_old_test_agents({})

            data = json.loads(result[0].text)
            # Low-update test agent (<=2 updates) should be archived immediately
            assert data["archived_count"] >= 1
            archived_ids = [a["id"] for a in data["archived_agents"]]
            assert "test_ping_1" in archived_ids

    @pytest.mark.asyncio
    async def test_archive_skips_already_archived(self, mock_mcp_server):
        mock_mcp_server.agent_metadata = {
            "test_archived": make_agent_meta(status="archived", total_updates=1),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage:
            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_old_test_agents
            result = await handle_archive_old_test_agents({})

            data = json.loads(result[0].text)
            assert data["archived_count"] == 0

    @pytest.mark.asyncio
    async def test_archive_skips_non_test_agents(self, mock_mcp_server):
        old = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        mock_mcp_server.agent_metadata = {
            "production-agent": make_agent_meta(status="active", last_update=old, total_updates=5),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage:
            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_old_test_agents
            result = await handle_archive_old_test_agents({})

            data = json.loads(result[0].text)
            assert data["archived_count"] == 0  # Not a test agent

    @pytest.mark.asyncio
    async def test_archive_include_all_flag(self, mock_mcp_server):
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        mock_mcp_server.agent_metadata = {
            "production-agent": make_agent_meta(status="active", last_update=old, total_updates=5),
        }

        with patch("src.mcp_handlers.lifecycle.mcp_server", mock_mcp_server), \
             patch("src.mcp_handlers.lifecycle.agent_storage") as mock_storage:
            mock_storage.archive_agent = AsyncMock()

            from src.mcp_handlers.lifecycle import handle_archive_old_test_agents
            result = await handle_archive_old_test_agents({"include_all": True})

            data = json.loads(result[0].text)
            assert data["include_all"] is True
            # 5 days old > 3 day default for include_all
            assert data["archived_count"] >= 1
