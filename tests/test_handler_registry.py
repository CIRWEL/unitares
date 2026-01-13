"""
Test handler registry refactoring.

Tests that extracted handlers work correctly and fallback mechanism functions.
"""

import sys
import asyncio
from pathlib import Path
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import json
from mcp.types import TextContent


@pytest.mark.asyncio
async def test_handler_registry():
    """Test that handler registry works correctly"""
    print("Testing handler registry...")
    
    # Import registry
    from src.mcp_handlers import TOOL_HANDLERS, dispatch_tool
    
    # Check registry loaded
    assert len(TOOL_HANDLERS) > 0, "Registry should have handlers"
    print(f"✅ Registry loaded with {len(TOOL_HANDLERS)} handlers")
    
    # Test that extracted handlers are in registry
    extracted_handlers = [
        "process_agent_update",
        "get_governance_metrics",
        "simulate_update",
        "get_thresholds",
        "set_thresholds",
        "get_server_info",
        "health_check"
    ]
    
    for handler_name in extracted_handlers:
        assert handler_name in TOOL_HANDLERS, f"Handler {handler_name} should be in registry"
        print(f"✅ Handler '{handler_name}' found in registry")
    
    # Test dispatch_tool with a simple handler
    print("\nTesting dispatch_tool...")
    
    # Test get_thresholds (simple handler)
    result = await dispatch_tool("get_thresholds", {})
    assert result is not None, "get_thresholds should return result"
    assert len(result) > 0, "Result should have content"
    
    # Parse result
    response_text = result[0].text
    response_data = json.loads(response_text)
    
    assert response_data.get("success") == True, "get_thresholds should succeed"
    assert "thresholds" in response_data, "Response should have thresholds"
    print(f"✅ get_thresholds handler works: {len(response_data.get('thresholds', {}))} thresholds")
    
    # Test get_server_info
    result = await dispatch_tool("get_server_info", {})
    assert result is not None, "get_server_info should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "get_server_info should succeed"
    assert "server_version" in response_data, "Response should have server_version"
    print(f"✅ get_server_info handler works: version {response_data.get('server_version')}")
    
    # Test health_check
    result = await dispatch_tool("health_check", {})
    assert result is not None, "health_check should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "health_check should succeed"
    assert "status" in response_data, "Response should have status"
    print(f"✅ health_check handler works: status {response_data.get('status')}")
    
    # Unknown handler now returns a helpful error response (with suggestions)
    result = await dispatch_tool("unknown_tool", {})
    assert result is not None and len(result) > 0, "Unknown tool should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") is False, "Unknown tool should fail"
    assert "not found" in (response_data.get("error", "").lower()), "Should mention tool not found"
    print("✅ Unknown handler returns helpful error response")
    
    print("\n✅ All handler registry tests passed!")


@pytest.mark.asyncio
async def test_call_tool_integration():
    """Test that call_tool function works with registry"""
    print("\nTesting call_tool integration...")
    
    # Import call_tool from mcp_server_std
    from src.mcp_server_std import call_tool
    
    # Test get_thresholds through call_tool
    result = await call_tool("get_thresholds", {})
    assert len(result) > 0, "call_tool should return result"
    
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "call_tool should succeed"
    print("✅ call_tool integration works with registry")
    
    # Test that legacy handlers still work (fallback)
    # Use a handler that hasn't been extracted yet
    result = await call_tool("list_agents", {})
    assert len(result) > 0, "Legacy handler should work via fallback"
    
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Legacy handler should succeed"
    print("✅ Legacy handler fallback works")
    
    print("\n✅ All integration tests passed!")


async def main():
    """Run all tests"""
    try:
        await test_handler_registry()
        await test_call_tool_integration()
        print("\n🎉 All tests passed!")
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

