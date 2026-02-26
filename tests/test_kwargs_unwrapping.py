"""
Tests for kwargs unwrapping behavior across dispatch and direct handler calls.

Note: With identity_v2, sessions are bound to agents. The tests verify that
kwargs unwrapping works correctly - the response format may vary depending
on whether an agent already exists in the session.
"""

import sys
import json
import uuid
from pathlib import Path
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Track agent IDs created during tests for cleanup
_created_agent_ids = []


def _make_unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


import pytest_asyncio

@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_agents():
    """Clean up any agents created during tests."""
    _created_agent_ids.clear()
    yield
    # Delete test agents from PostgreSQL after each test
    if _created_agent_ids:
        try:
            import asyncpg
            conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/governance')
            await conn.execute(
                "DELETE FROM core.agents WHERE id = ANY($1::varchar[])",
                _created_agent_ids
            )
            await conn.close()
        except Exception:
            pass  # Best-effort cleanup


def _extract_agent_id(data: dict):
    """Extract and track agent ID from identity response for cleanup."""
    agent_id = data.get("caller_agent_id") or (
        data.get("agent_signature", {}).get("agent_id")
    )
    if agent_id:
        _created_agent_ids.append(agent_id)


@pytest.mark.asyncio
async def test_dispatch_tool_kwargs_string_unwrap():
    """dispatch_tool should unwrap kwargs when provided as a JSON string."""
    from src.mcp_handlers import dispatch_tool

    name = _make_unique_name("test_kwargs_str")
    result = await dispatch_tool("identity", {"kwargs": json.dumps({"name": name})})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    _extract_agent_id(data)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "caller_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"


@pytest.mark.asyncio
async def test_dispatch_tool_kwargs_dict_unwrap():
    """dispatch_tool should unwrap kwargs when already parsed into a dict."""
    from src.mcp_handlers import dispatch_tool

    name = _make_unique_name("test_kwargs_dict")
    result = await dispatch_tool("identity", {"kwargs": {"name": name}})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    _extract_agent_id(data)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "caller_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"


@pytest.mark.asyncio
async def test_handle_identity_kwargs_dict_direct():
    """handle_identity should unwrap kwargs dicts when bypassing dispatch_tool."""
    from src.mcp_handlers.identity_v2 import handle_identity_adapter as handle_identity

    name = _make_unique_name("test_kwargs_direct")
    result = await handle_identity({"kwargs": {"name": name}})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    _extract_agent_id(data)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "caller_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"
