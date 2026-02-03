#!/usr/bin/env python3
"""
Integration Test: UNITARES v2.0 with governance_core

Verifies that the UNITARES production monitor works correctly
with the new governance_core module.

NOTE: These tests are designed to be run both via pytest and as a standalone script.
When run via pytest, each test function is independent.
When run as script, run_all_tests() chains them together.
"""

import sys
import numpy as np
from pathlib import Path
import pytest

# Add paths
project_root = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.governance_monitor import UNITARESMonitor


# Pytest fixture for monitor instance
@pytest.fixture
def monitor():
    """Create a fresh monitor for each test"""
    return UNITARESMonitor(agent_id="test_agent_v2")


def test_monitor_creation():
    """Test that monitor can be created"""
    print("\n1. Testing monitor creation...")
    mon = UNITARESMonitor(agent_id="test_agent_v2")
    assert mon.agent_id == "test_agent_v2"
    print("   ✅ Monitor created successfully")
    print(f"   - Initial λ₁: {mon.state.lambda1:.4f}")
    print(f"   - Initial E: {mon.state.E:.3f}")
    print(f"   - Initial I: {mon.state.I:.3f}")
    return mon


def test_process_update(monitor):
    """Test that process_update works"""
    print("\n2. Testing process_update...")

    agent_state = {
        'parameters': np.random.randn(128) * 0.01,
        'ethical_drift': np.array([0.1, 0.0, -0.05]),
        'response_text': "This is a test response.",
        'complexity': 0.3
    }

    result = monitor.process_update(agent_state)

    assert 'status' in result
    assert 'decision' in result
    assert 'metrics' in result
    assert 'sampling_params' in result

    print(f"   ✅ process_update successful")
    print(f"   - Status: {result['status']}")
    print(f"   - Decision: {result['decision']['action']}")
    print(f"   - Coherence: {result['metrics']['coherence']:.3f}")
    print(f"   - Risk: {result['metrics']['risk_score']:.3f}")

    return result


def test_multi_updates(monitor):
    """Test multiple updates"""
    print("\n3. Testing 20 updates...")

    results = []
    for i in range(20):
        agent_state = {
            'parameters': np.random.randn(128) * 0.01,
            'ethical_drift': np.random.rand(3) * 0.1,
            'response_text': f"Test response {i}",
            'complexity': 0.3 + 0.1 * (i % 5)
        }
        result = monitor.process_update(agent_state)
        results.append(result)

    print(f"   ✅ Completed 20 updates")
    print(f"   - Final E: {results[-1]['metrics']['E']:.3f}")
    print(f"   - Final I: {results[-1]['metrics']['I']:.3f}")
    print(f"   - Final S: {results[-1]['metrics']['S']:.3f}")
    print(f"   - Final V: {results[-1]['metrics']['V']:.3f}")
    print(f"   - Final coherence: {results[-1]['metrics']['coherence']:.3f}")

    # Check that state evolved
    initial_state = (0.7, 0.8, 0.2, 0.0)  # DEFAULT_STATE
    final_state = (
        results[-1]['metrics']['E'],
        results[-1]['metrics']['I'],
        results[-1]['metrics']['S'],
        results[-1]['metrics']['V']
    )

    # At least one state variable should have changed
    changed = any(abs(i - f) > 0.001 for i, f in zip(initial_state, final_state))
    assert changed, "State should evolve over multiple updates"

    return results


def test_get_metrics(monitor):
    """Test get_metrics"""
    print("\n4. Testing get_metrics...")

    metrics = monitor.get_metrics()

    assert 'agent_id' in metrics
    assert 'state' in metrics
    assert 'status' in metrics
    assert 'stability' in metrics

    print(f"   ✅ get_metrics successful")
    print(f"   - Agent ID: {metrics['agent_id']}")
    print(f"   - Status: {metrics['status']}")
    print(f"   - Stability: {metrics['stability']['stable']}")
    mean_risk = metrics.get('mean_risk')
    print(f"   - Mean risk: {mean_risk:.3f}" if mean_risk is not None else "   - Mean risk: N/A")

    return metrics


def test_export_history(monitor):
    """Test history export"""
    print("\n5. Testing export_history...")

    json_export = monitor.export_history(format='json')
    csv_export = monitor.export_history(format='csv')

    assert len(json_export) > 0
    assert len(csv_export) > 0

    print(f"   ✅ History export successful")
    print(f"   - JSON export: {len(json_export)} bytes")
    print(f"   - CSV export: {len(csv_export)} bytes")

    return json_export, csv_export


def test_governance_core_usage():
    """Verify that governance_core functions are being used"""
    print("\n6. Verifying governance_core usage...")

    # Import to check that it's using governance_core
    from governance_monitor import (
        step_state, coherence, phi_objective, verdict_from_phi
    )

    # These should be from governance_core
    import governance_core

    assert step_state == governance_core.step_state
    assert coherence == governance_core.coherence
    assert phi_objective == governance_core.phi_objective
    assert verdict_from_phi == governance_core.verdict_from_phi

    print("   ✅ Confirmed using governance_core functions")
    print("   - step_state: governance_core.step_state")
    print("   - coherence: governance_core.coherence")
    print("   - phi_objective: governance_core.phi_objective")
    print("   - verdict_from_phi: governance_core.verdict_from_phi")


def run_all_tests():
    """Run complete integration test suite"""
    print("=" * 70)
    print("INTEGRATION TEST: UNITARES v2.0 with governance_core")
    print("=" * 70)

    try:
        # Test 1: Monitor creation
        monitor = test_monitor_creation()

        # Test 2: Single update
        test_process_update(monitor)

        # Test 3: Multiple updates
        test_multi_updates(monitor)

        # Test 4: Get metrics
        test_get_metrics(monitor)

        # Test 5: Export history
        test_export_history(monitor)

        # Test 6: Verify governance_core usage
        test_governance_core_usage()

        print("\n" + "=" * 70)
        print("✅ ALL INTEGRATION TESTS PASSED")
        print("=" * 70)
        print("\nUNITARES v2.0 successfully integrated with governance_core!")
        print("The production monitor now uses the canonical dynamics implementation.")
        return 0

    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
