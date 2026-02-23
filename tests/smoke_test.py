#!/usr/bin/env python3
"""
Quick smoke test for critical functionality.

Runs basic tests to verify system is working correctly.
Useful for CI/CD and quick validation.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def test_imports():
    """Test that all critical modules can be imported"""
    print("Testing imports...")
    from src.governance_monitor import UNITARESMonitor
    from src.calibration import calibration_checker
    from src.telemetry import telemetry_collector
    from src.audit_log import audit_logger
    # knowledge_layer is deprecated and moved to archive
    from src.mcp_server_std import monitors
    print("  ✅ All imports successful")


def test_monitor_creation():
    """Test that monitor can be created"""
    print("\nTesting monitor creation...")
    from src.governance_monitor import UNITARESMonitor
    monitor = UNITARESMonitor('smoke_test', load_state=False)
    assert monitor.agent_id == 'smoke_test'
    assert hasattr(monitor, 'created_at')
    assert monitor.created_at is not None
    print(f"  ✅ Monitor created: {monitor.agent_id}")
    print(f"     created_at: {monitor.created_at}")


def test_calibration():
    """Test that calibration recording works"""
    print("\nTesting calibration...")
    from src.calibration import calibration_checker
    calibration_checker.record_prediction(0.8, True, None)
    pending = calibration_checker.get_pending_updates()
    print(f"  ✅ Calibration recording works (pending: {pending})")


def test_telemetry():
    """Test that telemetry collection works"""
    print("\nTesting telemetry...")
    from src.telemetry import telemetry_collector
    metrics = telemetry_collector.get_skip_rate_metrics()
    print(f"  ✅ Telemetry collection works")
    print(f"     Skip rate: {metrics.get('skip_rate', 'N/A')}")


def test_knowledge_layer():
    """Test that knowledge graph (PostgreSQL/AGE) works"""
    import asyncio

    async def _get_stats():
        from src.knowledge_graph import get_knowledge_graph
        kg = await get_knowledge_graph()
        return await kg.get_stats()

    print("\nTesting knowledge graph...")
    stats = asyncio.run(_get_stats())
    assert 'total_discoveries' in stats
    assert 'total_agents' in stats
    print(f"  Knowledge graph works")
    print(f"     Total discoveries: {stats.get('total_discoveries', 0)}")
    print(f"     Unique agents: {stats.get('unique_agents', 0)}")


def test_config():
    """Test that configuration loads correctly"""
    print("\nTesting configuration...")
    from config.governance_config import config
    assert hasattr(config, 'RISK_APPROVE_THRESHOLD')
    assert hasattr(config, 'RISK_REVISE_THRESHOLD')
    print(f"  ✅ Configuration loaded")
    print(f"     Risk approve threshold: {config.RISK_APPROVE_THRESHOLD}")
    print(f"     Risk revise threshold: {config.RISK_REVISE_THRESHOLD}")


def run_all_tests():
    """Run all smoke tests (for standalone execution)"""
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
            test()
            results.append(True)
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
