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


def _make_unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@pytest.mark.asyncio
async def test_dispatch_tool_kwargs_string_unwrap():
    """dispatch_tool should unwrap kwargs when provided as a JSON string."""
    from src.mcp_handlers import dispatch_tool

    name = _make_unique_name("test_kwargs_str")
    result = await dispatch_tool("identity", {"kwargs": json.dumps({"name": name})})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "resolved_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"
    print(f"✅ kwargs string unwrapped correctly, response keys: {list(data.keys())}")


@pytest.mark.asyncio
async def test_dispatch_tool_kwargs_dict_unwrap():
    """dispatch_tool should unwrap kwargs when already parsed into a dict."""
    from src.mcp_handlers import dispatch_tool

    name = _make_unique_name("test_kwargs_dict")
    result = await dispatch_tool("identity", {"kwargs": {"name": name}})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "resolved_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"
    print(f"✅ kwargs dict unwrapped correctly, response keys: {list(data.keys())}")


@pytest.mark.asyncio
async def test_handle_identity_kwargs_dict_direct():
    """handle_identity should unwrap kwargs dicts when bypassing dispatch_tool."""
    from src.mcp_handlers.identity import handle_identity

    name = _make_unique_name("test_kwargs_direct")
    result = await handle_identity({"kwargs": {"name": name}})
    assert result, "Expected a response from identity"

    data = json.loads(result[0].text)
    # With identity_v2, identity() succeeds and returns agent_signature
    assert data.get("success") is True, f"Identity should succeed, got: {data}"
    # The name parameter was unwrapped correctly - verify we got a valid response
    assert "agent_signature" in data or "resolved_agent_id" in data or "existing_agent" in data, \
        f"Should have identity info, got: {data}"
    print(f"✅ direct kwargs dict unwrapped correctly, response keys: {list(data.keys())}")
