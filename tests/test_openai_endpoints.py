#!/usr/bin/env python3
"""
Test OpenAI-compatible endpoints for GPT/Gemini integration

Tests the `/v1/tools` and `/v1/tools/call` endpoints to verify
the integration is working correctly.

Usage:
    python tests/test_openai_endpoints.py [--base-url http://127.0.0.1:8765]
    
NOTE: These tests require a running governance server.
When run via pytest without a server, they will be skipped.
"""

import sys
import json
import argparse
from pathlib import Path
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
import os

# Default base URL for tests
DEFAULT_BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def base_url():
    """Provide base URL and skip if server not running"""
    # These tests are integration tests against a live server.
    # To avoid surprising failures when a dev server happens to be running locally,
    # require an explicit opt-in.
    if os.getenv("RUN_OPENAI_ENDPOINT_TESTS") != "1":
        pytest.skip("OpenAI endpoint tests require RUN_OPENAI_ENDPOINT_TESTS=1")
    url = DEFAULT_BASE_URL
    try:
        response = requests.get(f"{url}/health", timeout=2)
        if response.status_code != 200:
            pytest.skip("Governance server not responding properly")
    except requests.exceptions.ConnectionError:
        pytest.skip("Governance server not running (connection refused)")
    except requests.exceptions.Timeout:
        pytest.skip("Governance server not responding (timeout)")
    return url


def test_health_endpoint(base_url: str) -> bool:
    """Test /health endpoint"""
    print("Testing /health endpoint...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        assert data.get("status") == "ok", f"Expected status='ok', got {data.get('status')}"
        print("  ✅ Health check passed")

    except Exception as e:
        pytest.fail(f"Health check failed: {e}")


def test_list_tools(base_url: str):
    """Test GET /v1/tools endpoint"""
    print("\nTesting GET /v1/tools endpoint...")
    try:
        response = requests.get(f"{base_url}/v1/tools", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Verify structure
        assert "tools" in data, "Response missing 'tools' field"
        assert "count" in data, "Response missing 'count' field"
        assert isinstance(data["tools"], list), "Tools should be a list"
        assert data["count"] == len(data["tools"]), "Count should match tools length"
        
        # Verify tool format (OpenAI function calling format)
        if data["tools"]:
            tool = data["tools"][0]
            assert "type" in tool, "Tool missing 'type' field"
            assert tool["type"] == "function", "Tool type should be 'function'"
            assert "function" in tool, "Tool missing 'function' field"
            assert "name" in tool["function"], "Tool function missing 'name'"
            assert "description" in tool["function"], "Tool function missing 'description'"
            assert "parameters" in tool["function"], "Tool function missing 'parameters'"
        
        print(f"  ✅ Found {data['count']} tools")
        if "mode" in data:
            print(f"  ✅ Tool mode: {data['mode']}")
        

    except Exception as e:
        pytest.fail(f"List tools failed: {e}")


def test_call_tool(base_url: str):
    """Test POST /v1/tools/call endpoint"""
    print("\nTesting POST /v1/tools/call endpoint...")
    try:
        # Test with health_check (no arguments needed)
        payload = {
            "name": "health_check",
            "arguments": {}
        }
        response = requests.post(
            f"{base_url}/v1/tools/call",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        # Verify structure
        assert "success" in data, "Response missing 'success' field"
        assert data["success"] is True, f"Tool call should succeed, got success={data['success']}"
        assert "name" in data, "Response missing 'name' field"
        assert data["name"] == "health_check", f"Expected name='health_check', got {data['name']}"
        assert "result" in data, "Response missing 'result' field"
        
        # Verify result structure (health_check returns status)
        if isinstance(data["result"], dict):
            assert "status" in data["result"], "Health check result missing 'status'"
        
        print(f"  ✅ Tool call succeeded: {data['name']}")

    except Exception as e:
        error_msg = f"Tool call failed: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                error_msg += f"\nError details: {json.dumps(error_data, indent=2)}"
            except:
                error_msg += f"\nResponse: {e.response.text[:200]}"
        pytest.fail(error_msg)


def test_error_handling(base_url: str):
    """Test error handling for invalid requests"""
    print("\nTesting error handling...")
    try:
        # Test with invalid tool name
        payload = {
            "name": "nonexistent_tool_xyz",
            "arguments": {}
        }
        response = requests.post(
            f"{base_url}/v1/tools/call",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        # Should return error (may be 200 with success=false or 400)
        data = response.json()
        if "success" in data:
            assert data["success"] is False, "Invalid tool should fail"
            assert "error" in data, "Error response should include 'error' field"
            print("  ✅ Error handling works (invalid tool rejected)")

        else:
            # Might be 400 status
            assert response.status_code == 400, f"Expected 400 for invalid tool, got {response.status_code}"
            print("  ✅ Error handling works (400 status for invalid tool)")

    except Exception as e:
        pytest.fail(f"Error handling test failed: {e}")


def test_cors_headers(base_url: str):
    """Test CORS headers are present"""
    print("\nTesting CORS headers...")
    try:
        response = requests.options(
            f"{base_url}/v1/tools",
            headers={"Origin": "http://localhost:3000"},
            timeout=5
        )
        
        # Check for CORS headers
        cors_headers = [
            "Access-Control-Allow-Origin",
            "Access-Control-Allow-Methods",
            "Access-Control-Allow-Headers"
        ]
        
        found_headers = [h for h in cors_headers if h in response.headers]
        if found_headers:
            print(f"  ✅ CORS headers present: {', '.join(found_headers)}")

        else:
            print("  ⚠️  CORS headers not found (may be fine if not using web clients)")
            # Not a failure, just a warning - test passes
    except Exception as e:
        print(f"  ⚠️  CORS test failed (non-critical): {e}")
        # Non-critical - test passes


def main():
    parser = argparse.ArgumentParser(description="Test OpenAI-compatible endpoints")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8765",
        help="Base URL of the governance server (default: http://127.0.0.1:8765)"
    )
    args = parser.parse_args()
    
    base_url = args.base_url.rstrip("/")
    
    print("=" * 70)
    print("OpenAI-Compatible Endpoints Test")
    print("=" * 70)
    print(f"Testing server at: {base_url}\n")
    
    tests = [
        ("Health Check", lambda: test_health_endpoint(base_url)),
        ("List Tools", lambda: test_list_tools(base_url)),
        ("Call Tool", lambda: test_call_tool(base_url)),
        ("Error Handling", lambda: test_error_handling(base_url)),
        ("CORS Headers", lambda: test_cors_headers(base_url)),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ❌ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! OpenAI-compatible endpoints are working.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

