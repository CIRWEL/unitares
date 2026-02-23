#!/usr/bin/env python3
"""
Test script to verify data organization works correctly.

Tests:
1. State file access and migration
2. History export to correct location
3. Knowledge layer access
4. Dialectic sessions
5. Directory structure
"""

import sys
import json
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_state_file_paths():
    """Test that state files use correct paths"""
    print("Testing state file paths...")
    
    from src.mcp_server_std import get_state_file
    
    test_agent_id = "test_org_verification"
    state_file = get_state_file(test_agent_id)
    
    expected_path = project_root / "data" / "agents" / f"{test_agent_id}_state.json"
    
    if str(state_file) == str(expected_path):
        print("  ✅ State file path correct")
        return True
    else:
        print(f"  ❌ State file path incorrect: {state_file} != {expected_path}")
        return False

def test_history_export_path():
    """Test that history exports go to correct location"""
    print("Testing history export path...")
    
    # Check the export handler code
    export_file = project_root / "src" / "mcp_handlers" / "export.py"
    
    with open(export_file, 'r') as f:
        content = f.read()
        
    if 'data", "history"' in content or 'data/history' in content:
        print("  ✅ Export handler uses data/history/")
        return True
    else:
        print("  ❌ Export handler may not use data/history/")
        return False

def test_knowledge_layer_paths():
    """Test that knowledge graph module imports correctly (PostgreSQL/AGE backend)."""
    print("Testing knowledge graph imports...")

    from src.knowledge_graph import DiscoveryNode, ResponseTo, get_knowledge_graph
    assert DiscoveryNode is not None
    assert get_knowledge_graph is not None
    print("  Knowledge graph module imports correctly")

def test_dialectic_sessions_path():
    """Test that dialectic sessions use correct path"""
    print("Testing dialectic sessions path...")
    
    dialectic_file = project_root / "src" / "mcp_handlers" / "dialectic.py"
    
    with open(dialectic_file, 'r') as f:
        content = f.read()
        
    if 'dialectic_sessions' in content:
        print("  ✅ Dialectic sessions use data/dialectic_sessions/")
        return True
    else:
        print("  ❌ Dialectic sessions path may be incorrect")
        return False

def test_directory_structure():
    """Test that required directories exist"""
    print("Testing directory structure...")
    
    required_dirs = [
        "data/agents",
        "data/history",
        "data/knowledge",
        "data/dialectic_sessions",
        "data/archive/agents",
        "data/archive/exports",
        "data/archive/sessions",
        "data/test_files"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        full_path = project_root / dir_path
        if full_path.exists():
            print(f"  ✅ {dir_path} exists")
        else:
            print(f"  ❌ {dir_path} missing")
            all_exist = False
    
    return all_exist

def test_data_root_clean():
    """Test that data root only has expected files"""
    print("Testing data root cleanliness...")
    
    data_root = project_root / "data"
    allowed_files = {
        "agent_metadata.json",
        "agent_metadata.example.json",
        "audit_log.jsonl",
        "README.md"
    }
    
    json_files = [f.name for f in data_root.glob("*.json")]
    jsonl_files = [f.name for f in data_root.glob("*.jsonl")]
    all_files = set(json_files + jsonl_files)
    
    unexpected = all_files - allowed_files
    
    if not unexpected:
        print("  ✅ Data root is clean (only expected files)")
        return True
    else:
        print(f"  ⚠️  Unexpected files in data root: {unexpected}")
        print("     (These may be legacy files that need migration)")
        return False

def test_workspace_health():
    """Test workspace health check tool"""
    print("Testing workspace health check...")
    
    try:
        from src.workspace_health import get_workspace_health
        
        health = get_workspace_health()
        
        if health.get("health") in ["healthy", "degraded", "unhealthy"]:
            print(f"  ✅ Workspace health check works (status: {health.get('health')})")
            return True
        else:
            print(f"  ❌ Workspace health check returned unexpected format")
            return False
    except Exception as e:
        print(f"  ❌ Workspace health check failed: {e}")
        return False

def test_imports():
    """Test that all critical modules import correctly"""
    print("Testing imports...")
    
    modules_to_test = [
        ("src.mcp_server_std", "get_state_file"),
        ("src.knowledge_graph", "get_knowledge_graph"),
        ("src.workspace_health", "get_workspace_health"),
    ]
    
    all_imported = True
    for module_name, attr_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            getattr(module, attr_name)
            print(f"  ✅ {module_name}.{attr_name} imports correctly")
        except Exception as e:
            print(f"  ❌ {module_name}.{attr_name} import failed: {e}")
            all_imported = False
    
    return all_imported

def main():
    """Run all tests"""
    print("=" * 60)
    print("Data Organization Test Suite")
    print("=" * 60)
    print()
    
    tests = [
        ("Imports", test_imports),
        ("Directory Structure", test_directory_structure),
        ("State File Paths", test_state_file_paths),
        ("History Export Path", test_history_export_path),
        ("Knowledge Layer Paths", test_knowledge_layer_paths),
        ("Dialectic Sessions Path", test_dialectic_sessions_path),
        ("Data Root Clean", test_data_root_clean),
        ("Workspace Health", test_workspace_health),
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
    print("Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Organization is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

