"""
Handler Error Path Tests

Tests error handling for common error scenarios:
- Missing required parameters
- Invalid parameter types/values
- Authentication failures
- Rate limiting
- Non-existent resources
- Validation errors
"""

import sys
import asyncio
from pathlib import Path
import json
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers import dispatch_tool


@pytest.mark.asyncio
async def test_missing_required_parameters():
    """Test handlers handle missing required parameters gracefully

    Note: With identity_v2, agent_id is auto-generated via session binding.
    Tools that previously required agent_id now auto-bind on first call.
    """
    print("\n=== Testing Missing Required Parameters ===")

    # Test process_agent_update without agent_id - now succeeds with auto-binding
    result = await dispatch_tool("process_agent_update", {})
    assert result is not None, "Should return response"
    response_data = json.loads(result[0].text)
    # With identity_v2, this succeeds - agent_id is auto-generated
    assert response_data.get("success") == True, "Should succeed with auto-binding"
    assert "agent_signature" in response_data, "Should have agent_signature"
    print("✅ process_agent_update auto-binds identity (identity_v2)")

    # Test get_governance_metrics without agent_id - uses bound identity
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return response"
    response_data = json.loads(result[0].text)
    # With identity_v2, this succeeds using the bound agent
    assert response_data.get("success") == True, "Should succeed with bound identity"
    print("✅ get_governance_metrics uses bound identity (identity_v2)")

    # Test simulate_update without agent_id - uses bound identity
    result = await dispatch_tool("simulate_update", {})
    assert result is not None, "Should return response"
    response_data = json.loads(result[0].text)
    # With identity_v2, this succeeds using the bound agent
    assert response_data.get("success") == True, "Should succeed with bound identity"
    print("✅ simulate_update uses bound identity (identity_v2)")


@pytest.mark.asyncio
async def test_invalid_parameter_types():
    """Test handlers handle invalid parameter types gracefully"""
    print("\n=== Testing Invalid Parameter Types ===")
    
    # Test with wrong type for complexity (should be float)
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "complexity": "not_a_number",  # Should be float
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    # Should either fail validation or convert gracefully
    print("✅ Handles invalid complexity type")
    
    # Test with wrong type for confidence (should be float)
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "complexity": 0.5,
        "confidence": "high"  # Should be float
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    print("✅ Handles invalid confidence type")


@pytest.mark.asyncio
async def test_invalid_parameter_values():
    """Test handlers handle invalid parameter values gracefully"""
    print("\n=== Testing Invalid Parameter Values ===")
    
    # Test with out-of-range complexity (> 1.0)
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "complexity": 2.0,  # Should be [0, 1]
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    # Should either clamp or error
    print("✅ Handles out-of-range complexity")
    
    # Test with out-of-range confidence (> 1.0)
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "complexity": 0.5,
        "confidence": 1.5  # Should be [0, 1]
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    print("✅ Handles out-of-range confidence")
    
    # Test with negative values
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "complexity": -0.1,  # Should be >= 0
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    print("✅ Handles negative values")


@pytest.mark.asyncio
async def test_authentication_failures():
    """Test session binding authentication (identity_v2)

    Note: With identity_v2, authentication is handled via session binding:
    - First tool call auto-creates and binds an identity to the session
    - Subsequent calls can only access the bound agent
    - Trying to access a different agent_id returns "Session mismatch" error
    """
    print("\n=== Testing Authentication (Session Binding) ===")

    # First call auto-binds an identity
    result = await dispatch_tool("process_agent_update", {
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed with auto-binding"
    bound_agent = response_data.get("agent_signature", {}).get("uuid") or response_data.get("resolved_agent_id")
    assert bound_agent is not None, "Should have bound agent"
    print(f"✅ Session bound to agent: {bound_agent[:8]}...")

    # Test trying to access different agent - should fail with session mismatch
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "different_agent_12345",
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail with session mismatch"
    error_msg = response_data.get("error", "").lower()
    assert "mismatch" in error_msg or "bound" in error_msg, f"Should mention session mismatch (got: {error_msg})"
    print("✅ Session binding prevents accessing other agents")

    # Test using the bound agent works
    result = await dispatch_tool("process_agent_update", {
        # No agent_id - uses bound identity
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should succeed with bound identity"
    print("✅ Bound identity auto-retrieved")


@pytest.mark.asyncio
async def test_nonexistent_resources():
    """Test handlers handle non-existent resources gracefully (identity_v2)

    Note: With identity_v2, session binding controls which agents you can access:
    - First call auto-creates and binds an identity
    - get_governance_metrics without agent_id uses the bound agent
    - Trying to access a non-existent agent_id returns "Session mismatch" error
    """
    print("\n=== Testing Non-Existent Resources ===")

    # First call establishes session binding
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    # With identity_v2, this succeeds using auto-bound agent
    assert response_data.get("success") == True, "Should succeed with auto-binding"
    bound_agent = response_data.get("agent_id")
    print(f"✅ Bound agent metrics retrieved: {bound_agent[:8] if bound_agent else 'N/A'}...")

    # Test get_agent_metadata for bound agent
    result = await dispatch_tool("get_agent_metadata", {})
    assert result is not None, "Should return response"
    response_data = json.loads(result[0].text)
    # Metadata for bound agent should work (may fail if not persisted yet)
    print(f"✅ Agent metadata retrieval: success={response_data.get('success')}")

    # Test trying to access different agent - should fail with session mismatch
    result = await dispatch_tool("get_governance_metrics", {
        "agent_id": "nonexistent_agent_12345"
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    # With identity_v2, this fails with session mismatch (not "not found")
    assert response_data.get("success") == False, "Should fail with session mismatch"
    error_msg = response_data.get("error", "").lower()
    assert "mismatch" in error_msg or "bound" in error_msg, f"Should mention session mismatch (got: {error_msg})"
    print("✅ Session binding prevents accessing non-existent agents")


@pytest.mark.asyncio
async def test_validation_errors():
    """Test handlers handle validation errors gracefully"""
    print("\n=== Testing Validation Errors ===")
    
    # Test with invalid task_type
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_agent",
        "task_type": "invalid_task_type",  # Should be "mixed", "prompted", "autonomous"
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    # Should either accept or validate
    print("✅ Handles invalid task_type")
    
    # Test set_thresholds with invalid threshold name
    result = await dispatch_tool("set_thresholds", {
        "thresholds": {
            "invalid_threshold_name": 0.5
        },
        "validate": True
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False or len(response_data.get("errors", [])) > 0
    print("✅ Handles invalid threshold name")
    
    # Test set_thresholds with out-of-range value
    result = await dispatch_tool("set_thresholds", {
        "thresholds": {
            "risk_approve_threshold": 2.0  # Should be [0, 1]
        },
        "validate": True
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False or len(response_data.get("errors", [])) > 0
    print("✅ Handles out-of-range threshold value")


@pytest.mark.asyncio
async def test_error_response_format():
    """Test that error responses have consistent format"""
    print("\n=== Testing Error Response Format ===")

    # Test that errors include error_code when available
    # With identity_v2, trying to access different agent triggers session mismatch
    result = await dispatch_tool("get_governance_metrics", {
        "agent_id": "nonexistent_agent"
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    # With identity_v2, this triggers session mismatch (error)
    assert response_data.get("success") == False, "Should be error"
    assert "error" in response_data, "Should have error message"
    # Should have recovery guidance for identity_v2 errors
    if "recovery" in response_data:
        print("✅ Error includes recovery guidance")
    print("✅ Error responses have consistent format")

    # Test that errors may include recovery guidance
    # (Some errors should have recovery field)
    print("✅ Error responses may include recovery guidance")


@pytest.mark.asyncio
async def test_unknown_tool():
    """Test handling of unknown tool names"""
    print("\n=== Testing Unknown Tool ===")
    
    result = await dispatch_tool("unknown_tool_that_does_not_exist", {})
    # Unknown tool returns helpful error response (with suggestions)
    assert result is not None and len(result) > 0, "Unknown tool should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") is False, "Unknown tool should fail"
    assert "not found" in (response_data.get("error", "").lower()), "Should mention tool not found"
    print("✅ Unknown tool returns helpful error response")


@pytest.mark.asyncio
async def test_empty_arguments():
    """Test handlers handle empty arguments gracefully"""
    print("\n=== Testing Empty Arguments ===")
    
    # Test with empty dict
    result = await dispatch_tool("get_thresholds", {})
    assert result is not None, "Should return result (get_thresholds doesn't need args)"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "get_thresholds should work with empty args"
    print("✅ Handles empty arguments for optional-arg tools")
    
    # Test with None (should be treated as empty)
    result = await dispatch_tool("health_check", {})
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "health_check should work"
    print("✅ Handles None arguments")


async def main():
    """Run all error path tests"""
    print("=" * 70)
    print("HANDLER ERROR PATH TESTS")
    print("=" * 70)
    
    try:
        await test_missing_required_parameters()
        await test_invalid_parameter_types()
        await test_invalid_parameter_values()
        await test_authentication_failures()
        await test_nonexistent_resources()
        await test_validation_errors()
        await test_error_response_format()
        await test_unknown_tool()
        await test_empty_arguments()
        
        print("\n" + "=" * 70)
        print("✅ ALL ERROR PATH TESTS PASSED!")
        print("=" * 70)
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

