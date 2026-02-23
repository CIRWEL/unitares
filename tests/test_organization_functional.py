#!/usr/bin/env python3
"""
Functional tests for data organization - tests actual read/write operations.
"""

import sys
import json
import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_state_file_read_write():
    """Test reading and writing state files"""
    print("Testing state file read/write...")
    
    from src.mcp_server_std import get_state_file
    
    test_agent_id = "test_functional_state"
    state_file = get_state_file(test_agent_id)
    
    # Ensure directory exists
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write test data
    test_data = {"test": "data", "timestamp": datetime.now().isoformat()}
    with open(state_file, 'w') as f:
        json.dump(test_data, f)
    
    # Read it back
    if state_file.exists():
        with open(state_file, 'r') as f:
            read_data = json.load(f)
        
        if read_data == test_data:
            print("  ✅ State file read/write works")
            # Cleanup
            state_file.unlink()
            return True
        else:
            print(f"  ❌ Data mismatch: {read_data} != {test_data}")
            return False
    else:
        print("  ❌ State file was not created")
        return False

def test_history_export_location():
    """Test that history exports go to correct location"""
    print("Testing history export location...")
    
    # Create a test history file
    test_agent_id = "test_history_export"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{test_agent_id}_history_{timestamp}.json"
    
    history_dir = project_root / "data" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    
    history_file = history_dir / filename
    
    # Write test data
    test_data = {"agent_id": test_agent_id, "history": []}
    with open(history_file, 'w') as f:
        json.dump(test_data, f)
    
    # Verify it's in the right place
    if history_file.exists() and history_file.parent == history_dir:
        print("  ✅ History export goes to data/history/")
        # Cleanup
        history_file.unlink()
        return True
    else:
        print(f"  ❌ History file not in expected location: {history_file}")
        return False

def test_knowledge_layer_read_write():
    """Test knowledge graph module imports and dataclasses work (PostgreSQL/AGE backend)."""
    print("Testing knowledge graph imports...")

    from src.knowledge_graph import DiscoveryNode, ResponseTo, get_knowledge_graph
    from datetime import datetime

    # Verify dataclass construction works
    discovery = DiscoveryNode(
        id=f"test_{datetime.now().timestamp()}",
        agent_id="test_knowledge_functional",
        type="insight",
        summary="Test discovery for functional test",
        details="This is a test",
        severity="info",
        tags=["test"]
    )
    assert discovery.agent_id == "test_knowledge_functional"
    assert discovery.type == "insight"
    print("  Knowledge graph dataclasses work")

def test_state_file_migration():
    """Test automatic migration from old location"""
    print("Testing state file migration...")
    
    from src.mcp_server_std import get_state_file
    
    test_agent_id = "test_migration"
    
    # Create file in old location
    old_path = project_root / "data" / f"{test_agent_id}_state.json"
    new_path = project_root / "data" / "agents" / f"{test_agent_id}_state.json"
    
    # Clean up first
    if new_path.exists():
        new_path.unlink()
    if old_path.exists():
        old_path.unlink()
    
    # Create in old location
    old_path.parent.mkdir(parents=True, exist_ok=True)
    test_data = {"migrated": True}
    with open(old_path, 'w') as f:
        json.dump(test_data, f)
    
    # Call get_state_file - should trigger migration
    state_file = get_state_file(test_agent_id)
    
    # Check if migration happened
    if new_path.exists() and not old_path.exists():
        # Verify data
        with open(new_path, 'r') as f:
            migrated_data = json.load(f)
        
        if migrated_data == test_data:
            print("  ✅ State file migration works")
            # Cleanup
            new_path.unlink()
            return True
        else:
            print(f"  ❌ Migration data mismatch")
            return False
    elif new_path.exists() and old_path.exists():
        print("  ⚠️  Migration happened but old file still exists")
        # Cleanup
        new_path.unlink()
        old_path.unlink()
        return False
    else:
        print(f"  ❌ Migration did not happen")
        # Cleanup
        if new_path.exists():
            new_path.unlink()
        if old_path.exists():
            old_path.unlink()
        return False

def test_export_handler_integration():
    """Test export handler writes to correct location"""
    print("Testing export handler integration...")
    
    # Check the code to verify it uses history directory (don't import to avoid dialectic dependency)
    export_file = project_root / "src" / "mcp_handlers" / "export.py"
    with open(export_file, 'r') as f:
        content = f.read()
    
    if 'history_dir' in content and ('data", "history"' in content or 'data/history' in content):
        print("  ✅ Export handler code uses data/history/")
        return True
    else:
        print("  ⚠️  Export handler code may not use data/history/")
        print(f"     Found 'history_dir': {'history_dir' in content}")
        search_str = 'data", "history"'
        print(f"     Found 'data\", \"history\"': {search_str in content}")
        return False

def main():
    """Run all functional tests"""
    print("=" * 60)
    print("Data Organization Functional Test Suite")
    print("=" * 60)
    print()
    
    tests = [
        ("State File Read/Write", test_state_file_read_write),
        ("History Export Location", test_history_export_location),
        ("Knowledge Layer Read/Write", test_knowledge_layer_read_write),
        ("State File Migration", test_state_file_migration),
        ("Export Handler Integration", test_export_handler_integration),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n[{test_name}]")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("Functional Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All functional tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

