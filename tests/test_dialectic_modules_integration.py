import pytest
"""
Integration tests for dialectic module splits.

Tests that the newly split modules (session, calibration, resolution, reviewer)
work correctly together and maintain backward compatibility.
"""

import sys
import asyncio
from pathlib import Path
import json
import tempfile
import shutil
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.types import TextContent
from src.dialectic_protocol import DialecticSession, DialecticPhase, Resolution, DialecticMessage


@pytest.mark.asyncio
async def test_session_module_imports():
    """Test that session module functions are accessible"""
    print("Testing session module imports...")
    
    from src.mcp_handlers.dialectic import (
        save_session,
        load_session,
        load_all_sessions,
        ACTIVE_SESSIONS,
        SESSION_STORAGE_DIR
    )
    
    assert callable(save_session), "save_session should be callable"
    assert callable(load_session), "load_session should be callable"
    assert callable(load_all_sessions), "load_all_sessions should be callable"
    assert isinstance(ACTIVE_SESSIONS, dict), "ACTIVE_SESSIONS should be a dict"
    
    print("✅ Session module imports work correctly")


@pytest.mark.asyncio
async def test_calibration_module_imports():
    """Test that calibration module functions are accessible"""
    print("Testing calibration module imports...")
    
    from src.mcp_handlers.dialectic import (
        update_calibration_from_dialectic,
        update_calibration_from_dialectic_disagreement,
        backfill_calibration_from_historical_sessions
    )
    
    assert callable(update_calibration_from_dialectic), "update_calibration_from_dialectic should be callable"
    assert callable(update_calibration_from_dialectic_disagreement), "update_calibration_from_dialectic_disagreement should be callable"
    assert callable(backfill_calibration_from_historical_sessions), "backfill_calibration_from_historical_sessions should be callable"
    
    print("✅ Calibration module imports work correctly")


@pytest.mark.asyncio
async def test_resolution_module_imports():
    """Test that resolution module functions are accessible"""
    print("Testing resolution module imports...")
    
    from src.mcp_handlers.dialectic import execute_resolution
    
    assert callable(execute_resolution), "execute_resolution should be callable"
    
    print("✅ Resolution module imports work correctly")


@pytest.mark.asyncio
async def test_reviewer_module_imports():
    """Test that reviewer module functions are accessible"""
    print("Testing reviewer module imports...")
    
    from src.mcp_handlers.dialectic import (
        select_reviewer,
        is_agent_in_active_session
    )
    
    assert callable(select_reviewer), "select_reviewer should be callable"
    assert callable(is_agent_in_active_session), "is_agent_in_active_session should be callable"
    
    print("✅ Reviewer module imports work correctly")


@pytest.mark.asyncio
async def test_module_source_verification():
    """Verify that functions are actually from the correct modules"""
    print("Testing module source verification...")
    
    import inspect
    
    from src.mcp_handlers.dialectic import (
        save_session,
        update_calibration_from_dialectic,
        execute_resolution,
        select_reviewer
    )
    
    # Check module sources
    save_mod = inspect.getmodule(save_session)
    cal_mod = inspect.getmodule(update_calibration_from_dialectic)
    res_mod = inspect.getmodule(execute_resolution)
    reviewer_mod = inspect.getmodule(select_reviewer)
    
    assert 'dialectic_session' in save_mod.__name__, f"save_session should be from dialectic_session, got {save_mod.__name__}"
    assert 'dialectic_calibration' in cal_mod.__name__, f"update_calibration_from_dialectic should be from dialectic_calibration, got {cal_mod.__name__}"
    assert 'dialectic_resolution' in res_mod.__name__, f"execute_resolution should be from dialectic_resolution, got {res_mod.__name__}"
    assert 'dialectic_reviewer' in reviewer_mod.__name__, f"select_reviewer should be from dialectic_reviewer, got {reviewer_mod.__name__}"
    
    print("✅ All functions are from correct modules")


@pytest.mark.asyncio
async def test_session_persistence():
    """Test that session persistence works correctly"""
    print("Testing session persistence...")
    
    from src.mcp_handlers.dialectic_session import save_session, load_session
    from src.dialectic_protocol import DialecticSession
    
    # Create a test session using the correct constructor signature
    session = DialecticSession(
        paused_agent_id="test_agent",
        reviewer_agent_id="reviewer_agent",
        dispute_type="verification"
    )
    
    # Save session
    await save_session(session)
    
    # Load session by session_id
    loaded = await load_session(session.session_id)
    
    assert loaded is not None, "Session should be loaded"
    assert loaded.session_id == session.session_id, "Session ID should match"
    assert loaded.paused_agent_id == session.paused_agent_id, "Paused agent ID should match"
    assert loaded.reviewer_agent_id == session.reviewer_agent_id, "Reviewer agent ID should match"
    
    print("✅ Session persistence works correctly")


@pytest.mark.asyncio
async def test_dialectic_handler_integration():
    """Test that dialectic handlers still work after module split"""
    print("Testing dialectic handler integration...")
    
    from src.mcp_handlers import dispatch_tool
    
    # Test get_dialectic_session (should work even with no sessions)
    result = await dispatch_tool("get_dialectic_session", {
        "session_id": "nonexistent_session"
    })
    
    assert result is not None, "get_dialectic_session should return result"
    assert len(result) > 0, "Result should have content"
    
    # Parse result
    response_text = result[0].text
    response_data = json.loads(response_text)
    
    # Should return error for nonexistent session (which is expected)
    assert "error" in response_data or "not found" in response_text.lower(), "Should handle nonexistent session gracefully"
    
    print("✅ Dialectic handlers work correctly after module split")


@pytest.mark.asyncio
async def test_backward_compatibility():
    """Test that backward compatibility is maintained (updated for v2.5.1+ archived dialectic)"""
    print("Testing backward compatibility...")
    
    # Test that all expected functions are still accessible from main dialectic module
    from src.mcp_handlers import dialectic
    
    # NOTE: Dialectic protocol handlers were mostly archived in v2.5.1+ (Dec 2025)
    # request_dialectic_review was restored as a lite recovery entry point.
    
    # Check that remaining handlers exist
    assert hasattr(dialectic, 'handle_get_dialectic_session'), "handle_get_dialectic_session should exist"
    assert hasattr(dialectic, 'handle_request_dialectic_review'), "handle_request_dialectic_review should exist"
    
    # Check that imported utility functions work (these are still available)
    assert callable(dialectic.save_session), "save_session should be callable"
    assert callable(dialectic.execute_resolution), "execute_resolution should be callable"
    assert callable(dialectic.select_reviewer), "select_reviewer should be callable"
    
    # Verify archived handlers are NOT present (expected behavior)
    assert not hasattr(dialectic, 'handle_submit_thesis'), "handle_submit_thesis was archived and should not exist"
    
    print("✅ Backward compatibility maintained (archived handlers correctly removed)")


async def main():
    """Run all integration tests"""
    print("=" * 70)
    print("Dialectic Module Integration Tests")
    print("=" * 70)
    print()
    
    tests = [
        ("Session Module Imports", test_session_module_imports),
        ("Calibration Module Imports", test_calibration_module_imports),
        ("Resolution Module Imports", test_resolution_module_imports),
        ("Reviewer Module Imports", test_reviewer_module_imports),
        ("Module Source Verification", test_module_source_verification),
        ("Session Persistence", test_session_persistence),
        ("Dialectic Handler Integration", test_dialectic_handler_integration),
        ("Backward Compatibility", test_backward_compatibility),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n[{test_name}]")
        try:
            await test_func()
            results.append((test_name, True))
        except AssertionError as e:
            print(f"  ❌ Assertion failed: {e}")
            results.append((test_name, False))
        except Exception as e:
            print(f"  ❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("\n" + "=" * 70)
    print("Integration Test Results Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All integration tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

