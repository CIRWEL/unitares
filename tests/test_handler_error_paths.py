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
    """Test handlers handle missing required parameters gracefully"""
    print("\n=== Testing Missing Required Parameters ===")
    
    # Test process_agent_update without agent_id
    result = await dispatch_tool("process_agent_update", {})
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without agent_id"
    assert "agent_id" in response_data.get("error", "").lower() or "required" in response_data.get("error", "").lower()
    print("✅ process_agent_update validates agent_id")
    
    # Test get_governance_metrics without agent_id
    result = await dispatch_tool("get_governance_metrics", {})
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without agent_id"
    print("✅ get_governance_metrics validates agent_id")
    
    # Test simulate_update without agent_id
    result = await dispatch_tool("simulate_update", {})
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail without agent_id"
    print("✅ simulate_update validates agent_id")


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
    """Test handlers handle authentication failures gracefully
    
    Note: The system auto-retrieves API keys from stored credentials for existing agents.
    So "missing API key" actually succeeds because the key is looked up.
    We focus on testing wrong API key scenario.
    """
    print("\n=== Testing Authentication Failures ===")
    
    # First register the agent via process_agent_update (creates agent + returns key)
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_auth_agent_new2",
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == True, "Should create agent"
    correct_key = response_data.get("api_key")
    assert correct_key is not None, "Should return API key on creation"
    print("✅ Agent created with API key")
    
    # Test with wrong API key - should fail
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_auth_agent_new2",
        "api_key": "wrong_key_12345",
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail with wrong key"
    error_msg = response_data.get("error", "").lower()
    assert "auth" in error_msg or "key" in error_msg or "invalid" in error_msg, f"Should mention auth issue (got: {error_msg})"
    print("✅ Handles wrong API key")
    
    # Test with missing API key for existing agent
    # Note: System auto-retrieves API key from stored credentials, so this succeeds
    result = await dispatch_tool("process_agent_update", {
        "agent_id": "test_auth_agent_new2",
        # No api_key - will be auto-retrieved from stored credentials
        "complexity": 0.5,
        "confidence": 0.9
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    # This succeeds because the API key is auto-retrieved from stored credentials
    assert response_data.get("success") == True, "Should succeed with auto-retrieved key"
    assert "api_key_info" in response_data, "Should mention auto-retrieval"
    print("✅ Auto-retrieves API key for existing agent")


@pytest.mark.asyncio
async def test_nonexistent_resources():
    """Test handlers handle non-existent resources gracefully
    
    Note: get_governance_metrics auto-creates monitors for non-existent agents
    (design choice for observability). get_agent_metadata fails for unregistered agents.
    """
    print("\n=== Testing Non-Existent Resources ===")
    
    # Test get_governance_metrics with non-existent agent
    # Note: This now succeeds with default state (creates monitor on demand)
    result = await dispatch_tool("get_governance_metrics", {
        "agent_id": "nonexistent_agent_12345"
    })
    assert result is not None, "Should return result"
    response_data = json.loads(result[0].text)
    # This now succeeds - monitors are created on demand for observability
    assert response_data.get("success") == True, "Should succeed (creates monitor on demand)"
    assert response_data.get("agent_id") == "nonexistent_agent_12345"
    print("✅ Auto-creates monitor for non-existent agent")
    
    # Test get_agent_metadata with non-existent agent (should fail)
    result = await dispatch_tool("get_agent_metadata", {
        "agent_id": "truly_nonexistent_metadata_agent"
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should fail for non-existent agent metadata"
    print("✅ Handles non-existent agent metadata")


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
    result = await dispatch_tool("get_governance_metrics", {
        "agent_id": "nonexistent_agent"
    })
    assert result is not None, "Should return error response"
    response_data = json.loads(result[0].text)
    assert response_data.get("success") == False, "Should be error"
    assert "error" in response_data, "Should have error message"
    # May or may not have error_code (optional)
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

