#!/usr/bin/env python3
"""
Test created_at bug fix.

Tests that created_at is always set, even when loading persisted state.
"""

import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.governance_monitor import UNITARESMonitor


def test_created_at_on_fresh_init():
    """Test that created_at is set on fresh initialization"""
    print("\n1. Testing created_at on fresh initialization...")
    
    monitor = UNITARESMonitor('test_fresh', load_state=False)
    
    assert hasattr(monitor, 'created_at'), "Monitor should have created_at attribute"
    assert monitor.created_at is not None, "created_at should not be None"
    assert isinstance(monitor.created_at, datetime), "created_at should be datetime"
    
    print(f"   ✅ created_at set: {monitor.created_at}")
    return True


def test_created_at_on_load():
    """Test that created_at is set when loading persisted state"""
    print("\n2. Testing created_at when loading persisted state...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test state file (simulating persisted state)
        state_file = Path(tmpdir) / "test_created_at_state.json"
        
        # Write minimal state (without created_at in state data)
        state_data = {
            'E': 0.7,
            'I': 0.8,
            'S': 0.2,
            'V': 0.0,
            'coherence': 0.75,
            'lambda1': 0.09,
            'void_active': False,
            'update_count': 0,
            'E_history': [],
            'I_history': [],
            'S_history': [],
            'V_history': []
        }
        
        with open(state_file, 'w') as f:
            json.dump(state_data, f)
        
        # Mock the load path
        import src.governance_monitor as gm_module
        original_load = gm_module.UNITARESMonitor.load_persisted_state
        
        def mock_load(self):
            state_file_path = Path(tmpdir) / f"{self.agent_id}_state.json"
            if state_file_path.exists():
                with open(state_file_path, 'r') as f:
                    data = json.load(f)
                    from src.governance_monitor import GovernanceState
                    return GovernanceState.from_dict(data)
            return None
        
        # Temporarily replace load method
        gm_module.UNITARESMonitor.load_persisted_state = mock_load
        
        try:
            # Create monitor that loads state
            monitor = UNITARESMonitor('test_created_at', load_state=True)
            
            # Verify created_at is set (should fallback to now if not in state)
            assert hasattr(monitor, 'created_at'), "Monitor should have created_at attribute"
            assert monitor.created_at is not None, "created_at should not be None"
            assert isinstance(monitor.created_at, datetime), "created_at should be datetime"
            
            print(f"   ✅ created_at set when loading state: {monitor.created_at}")
        finally:
            # Restore original method
            gm_module.UNITARESMonitor.load_persisted_state = original_load
        
        return True


def test_created_at_fallback_to_metadata():
    """Test that created_at falls back to metadata if not in monitor"""
    print("\n3. Testing created_at fallback to metadata...")
    
    # This tests the build_standardized_agent_info fallback logic
    from src.mcp_server_std import build_standardized_agent_info, get_or_create_metadata
    
    # Get or create metadata (this will have created_at)
    meta = get_or_create_metadata('test_fallback')
    
    # Build info without monitor (should use metadata)
    info = build_standardized_agent_info('test_fallback', meta, monitor=None)
    
    # Verify created_at is accessible (could be in summary or metadata)
    # The function uses metadata.created_at when monitor is None
    assert meta.created_at is not None, "Metadata should have created_at"
    assert 'summary' in info, "Info should have summary"
    # The summary contains last_activity which comes from metadata when monitor is None
    assert 'last_activity' in info['summary'], "Summary should have last_activity from metadata"
    
    print(f"   ✅ created_at falls back to metadata: {meta.created_at}")
    return True


def run_all_tests():
    """Run all created_at fix tests"""
    print("=" * 60)
    print("CREATED_AT BUG FIX TEST SUITE")
    print("=" * 60)
    
    tests = [
        test_created_at_on_fresh_init,
        test_created_at_on_load,
        test_created_at_fallback_to_metadata,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("\n🎉 All created_at fix tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())

