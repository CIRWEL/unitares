"""
Test extracted handlers individually.

Tests the more complex handlers to ensure they work correctly.
"""

import sys
import asyncio
from pathlib import Path
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def test_get_governance_metrics():
    """Test get_governance_metrics handler"""
    print("\nTesting get_governance_metrics...")
    
    from src.mcp_handlers import dispatch_tool
    
    # Test with non-existent agent (should error gracefully)
    result = await dispatch_tool("get_governance_metrics", {"agent_id": "test_nonexistent_agent"})
    assert result is not None, "Should return error response"
    
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail for non-existent agent"
    print("✅ Handles non-existent agent correctly")
    
    # Test with missing agent_id (should error)
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return error response"
    
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without agent_id"
    error_msg = response_data.get("error", "").lower()
    assert "agent_id" in error_msg or "required" in error_msg, f"Should mention agent_id or required (got: {error_msg})"
    print("✅ Validates required arguments")
    
    print("✅ get_governance_metrics handler tests passed")


async def test_simulate_update():
    """Test simulate_update handler"""
    print("\nTesting simulate_update...")
    
    from src.mcp_handlers import dispatch_tool
    
    # Test with missing agent_id
    result = await dispatch_tool("simulate_update", {})
    assert result is not None, "Should return error response"
    
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without agent_id"
    print("✅ Validates required arguments")
    
    # Test with valid agent_id (will create monitor if needed)
    result = await dispatch_tool("simulate_update", {
        "agent_id": "test_simulate_agent",
        "parameters": [0.7, 0.8, 0.15, 0.0],
        "ethical_drift": [0.0, 0.0, 0.0],
        "complexity": 0.3,
        "confidence": 0.9
    })
    
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed with valid args"
    assert response_data.get("simulation") == True, "Should mark as simulation"
    assert "metrics" in response_data, "Should have metrics"
    print("✅ Simulates update correctly")
    
    print("✅ simulate_update handler tests passed")


async def test_set_thresholds():
    """Test set_thresholds handler"""
    print("\nTesting set_thresholds...")
    
    from src.mcp_handlers import dispatch_tool
    
    # Get current thresholds first
    result = await dispatch_tool("get_thresholds", {})
    current_data = json.loads(result[0].text)
    original_risk_approve = current_data["thresholds"]["risk_approve_threshold"]
    
    # Test setting a threshold
    new_value = 0.32
    result = await dispatch_tool("set_thresholds", {
        "thresholds": {"risk_approve_threshold": new_value},
        "validate": True
    })
    
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed"
    assert "risk_approve_threshold" in response_data.get("updated", []), "Should update threshold"
    
    # Verify it was updated
    result = await dispatch_tool("get_thresholds", {})
    updated_data = json.loads(result[0].text)
    assert updated_data["thresholds"]["risk_approve_threshold"] == new_value, "Threshold should be updated"
    print("✅ Sets threshold correctly")
    
    # Reset to original value
    await dispatch_tool("set_thresholds", {
        "thresholds": {"risk_approve_threshold": original_risk_approve},
        "validate": True
    })
    print("✅ Reset threshold to original value")
    
    print("✅ set_thresholds handler tests passed")


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

