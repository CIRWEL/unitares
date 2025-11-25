#!/usr/bin/env python3
"""
Quick smoke test for critical functionality.

Runs basic tests to verify system is working correctly.
Useful for CI/CD and quick validation.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def test_imports():
    """Test that all critical modules can be imported"""
    print("Testing imports...")
    try:
        from src.governance_monitor import UNITARESMonitor
        from src.calibration import calibration_checker
        from src.telemetry import telemetry_collector
        from src.audit_log import audit_logger
        from src.knowledge_layer import get_knowledge_manager
        from src.mcp_server_std import monitors
        print("  ✅ All imports successful")
        return True
    except Exception as e:
        print(f"  ❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_monitor_creation():
    """Test that monitor can be created"""
    print("\nTesting monitor creation...")
    try:
        from src.governance_monitor import UNITARESMonitor
        monitor = UNITARESMonitor('smoke_test', load_state=False)
        assert monitor.agent_id == 'smoke_test'
        assert hasattr(monitor, 'created_at')
        assert monitor.created_at is not None
        print(f"  ✅ Monitor created: {monitor.agent_id}")
        print(f"     created_at: {monitor.created_at}")
        return True
    except Exception as e:
        print(f"  ❌ Monitor creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_calibration():
    """Test that calibration recording works"""
    print("\nTesting calibration...")
    try:
        from src.calibration import calibration_checker
        calibration_checker.record_prediction(0.8, True, None)
        pending = calibration_checker.get_pending_updates()
        print(f"  ✅ Calibration recording works (pending: {pending})")
        return True
    except Exception as e:
        print(f"  ❌ Calibration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_telemetry():
    """Test that telemetry collection works"""
    print("\nTesting telemetry...")
    try:
        from src.telemetry import telemetry_collector
        metrics = telemetry_collector.get_skip_rate_metrics()
        print(f"  ✅ Telemetry collection works")
        print(f"     Skip rate: {metrics.get('skip_rate', 'N/A')}")
        return True
    except Exception as e:
        print(f"  ❌ Telemetry failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_knowledge_layer():
    """Test that knowledge layer works"""
    print("\nTesting knowledge layer...")
    try:
        from src.knowledge_layer import get_knowledge_manager
        manager = get_knowledge_manager()
        stats = manager.get_stats()
        print(f"  ✅ Knowledge layer works")
        print(f"     Agents with knowledge: {stats['total_agents']}")
        return True
    except Exception as e:
        print(f"  ❌ Knowledge layer failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config():
    """Test that configuration loads correctly"""
    print("\nTesting configuration...")
    try:
        from config.governance_config import config
        assert hasattr(config, 'RISK_APPROVE_THRESHOLD')
        assert hasattr(config, 'RISK_REVISE_THRESHOLD')
        print(f"  ✅ Configuration loaded")
        print(f"     Risk approve threshold: {config.RISK_APPROVE_THRESHOLD}")
        print(f"     Risk revise threshold: {config.RISK_REVISE_THRESHOLD}")
        return True
    except Exception as e:
        print(f"  ❌ Configuration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all smoke tests"""
    print("=" * 60)
    print("SMOKE TEST SUITE")
    print("=" * 60)
    print()
    
    tests = [
        test_imports,
        test_monitor_creation,
        test_calibration,
        test_telemetry,
        test_knowledge_layer,
        test_config,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"  ❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 60)
    
    if all(results):
        print("\n🎉 All smoke tests passed!")
        return 0
    else:
        print("\n⚠️  Some smoke tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())

