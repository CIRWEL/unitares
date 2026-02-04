import pytest
"""
Test extracted handlers individually.

Tests the more complex handlers to ensure they work correctly.

NOTE: With identity_v2, missing agent_id triggers auto-binding (session-based identity).
Tests updated to reflect this behavior.
"""

import sys
import asyncio
from pathlib import Path
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.asyncio
async def test_get_governance_metrics():
    """Test get_governance_metrics handler

    With identity_v2, missing agent_id triggers auto-binding.
    The handler should succeed and return metrics for the auto-bound agent.

    Note: Once a session is bound, you CANNOT switch to a different agent_id.
    This is by design - each session is bound to one agent identity.
    """
    print("\nTesting get_governance_metrics...")

    from src.mcp_handlers import dispatch_tool

    # Test with missing agent_id - should auto-bind (identity_v2 behavior)
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return response"

    response_data = json.loads(result[0].text)
    # With identity_v2, auto-binding creates a new agent, so success=True
    assert response_data.get("success") == True, "Should succeed with auto-binding"
    assert "agent_signature" in response_data or "resolved_agent_id" in response_data, \
        "Should have identity info from auto-binding"
    print("✅ Auto-binds agent when agent_id missing (identity_v2)")

    # Subsequent calls without agent_id should also succeed (uses bound identity)
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed on subsequent calls"
    print("✅ Works on subsequent calls (uses bound identity)")

    print("✅ get_governance_metrics handler tests passed")


@pytest.mark.asyncio
async def test_simulate_update():
    """Test simulate_update handler

    With identity_v2, auto-binding allows simulation without prior registration.
    Note: Once bound, you cannot switch agent_ids within the same session.
    """
    print("\nTesting simulate_update...")

    from src.mcp_handlers import dispatch_tool

    # Test with missing agent_id - should auto-bind and succeed (identity_v2)
    result = await dispatch_tool("simulate_update", {})
    assert result is not None, "Should return response"

    response_data = json.loads(result[0].text)
    # With identity_v2, auto-binding means this succeeds
    assert response_data.get("success") == True, "Should succeed with auto-binding"
    assert response_data.get("simulation") == True, "Should mark as simulation"
    print("✅ Auto-binds and simulates (identity_v2)")

    # Test with explicit parameters but NO agent_id (uses bound identity)
    result = await dispatch_tool("simulate_update", {
        "parameters": [0.7, 0.8, 0.15, 0.0],
        "ethical_drift": [0.0, 0.0, 0.0],
        "complexity": 0.3,
        "confidence": 0.9
    })

    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed"
    assert response_data.get("simulation") == True, "Should mark as simulation"
    assert "metrics" in response_data, "Should have metrics"
    print("✅ Simulates with explicit parameters")

    print("✅ simulate_update handler tests passed")


@pytest.mark.asyncio
async def test_set_thresholds():
    """Test set_thresholds handler

    Note: set_thresholds requires admin privileges (security fix 2025-12).
    Admin status requires 'admin' tag or 100+ updates.
    For testing, we verify the auth rejection and get_thresholds (read-only).
    """
    print("\nTesting set_thresholds...")

    from src.mcp_handlers import dispatch_tool

    # Test that unauthenticated/non-admin request fails
    result = await dispatch_tool("set_thresholds", {
        "thresholds": {"risk_approve_threshold": 0.32},
        "validate": True
    })
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without admin"
    print("✅ Rejects non-admin requests")

    # Verify get_thresholds works (read-only, no auth needed)
    result = await dispatch_tool("get_thresholds", {})
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed for read-only"
    assert "thresholds" in response_data, "Should have thresholds"
    print("✅ get_thresholds works (read-only)")

    print("✅ set_thresholds handler tests passed")


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling in handlers"""
    print("\nTesting error handling...")

    from src.mcp_handlers import dispatch_tool

    # Test with invalid arguments
    result = await dispatch_tool("set_thresholds", {
        "thresholds": {"invalid_threshold": 999},
        "validate": True
    })

    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    # Should either succeed (if invalid threshold ignored) or fail gracefully
    assert "success" in response_data, "Should have success field"
    print("✅ Handles invalid arguments gracefully")

    print("✅ Error handling tests passed")


async def main():
    """Run all handler tests"""
    try:
        await test_get_governance_metrics()
        await test_simulate_update()
        await test_set_thresholds()
        await test_error_handling()
        print("\n🎉 All handler tests passed!")
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
