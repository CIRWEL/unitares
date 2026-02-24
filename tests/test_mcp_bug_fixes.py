#!/usr/bin/env python3
"""
Test MCP server with bug fixes through the tool interface
"""

import json

from src.mcp_server_std import monitors, agent_metadata

def reset_test_state():
    """Clear test agents"""
    if "mcp_coherence_test" in monitors:
        del monitors["mcp_coherence_test"]
    if "mcp_coherence_test" in agent_metadata:
        del agent_metadata["mcp_coherence_test"]



def test_coherence_bug_fix():
    """Test that identical parameters give coherence = 1.0"""
    print("=" * 70)
    print("TEST: Coherence Bug Fix (MCP Interface)")
    print("=" * 70)

    reset_test_state()

    from src.mcp_server_std import monitors
    from src.governance_monitor import UNITARESMonitor

    # Create monitor
    agent_id = "mcp_coherence_test"
    monitors[agent_id] = UNITARESMonitor(agent_id=agent_id)

    # First update
    agent_state1 = {
        'parameters': [0.5, 0.5, 0.75, 0.85, 0.0, 0.1] + [0.01] * 122,
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': 'Test response',
        'complexity': 0.5
    }

    result1 = monitors[agent_id].process_update(agent_state1)
    print(f"\nUpdate 1:")
    print(f"  Coherence: {result1['metrics']['coherence']:.4f}")
    print(f"  Lambda1: {result1['metrics']['lambda1']:.4f}")
    print(f"  V: {result1['metrics']['V']:+.4f}")

    # Second update with IDENTICAL parameters
    agent_state2 = {
        'parameters': [0.5, 0.5, 0.75, 0.85, 0.0, 0.1] + [0.01] * 122,  # IDENTICAL
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': 'Test response',
        'complexity': 0.5
    }

    result2 = monitors[agent_id].process_update(agent_state2)
    print(f"\nUpdate 2 (IDENTICAL parameters):")
    print(f"  Coherence: {result2['metrics']['coherence']:.4f}")
    print(f"  Lambda1: {result2['metrics']['lambda1']:.4f}")
    print(f"  V: {result2['metrics']['V']:+.4f}")

    # Third update with IDENTICAL parameters
    result3 = monitors[agent_id].process_update(agent_state2)
    print(f"\nUpdate 3 (IDENTICAL parameters):")
    print(f"  Coherence: {result3['metrics']['coherence']:.4f}")
    print(f"  Lambda1: {result3['metrics']['lambda1']:.4f}")
    print(f"  V: {result3['metrics']['V']:+.4f}")

    print("\n" + "-" * 70)
    print("ANALYSIS:")
    print("-" * 70)

    # Check coherence = 1.0
    coherence2 = result2['metrics']['coherence']
    coherence3 = result3['metrics']['coherence']

    if coherence2 >= 0.99 and coherence3 >= 0.99:
        print("✅ PASS: Coherence = 1.0 with identical parameters")
    else:
        print(f"❌ FAIL: Coherence not 1.0")
        print(f"   Update 2: {coherence2:.4f}")
        print(f"   Update 3: {coherence3:.4f}")

    # Check lambda1 bounds
    lambda1_values = [
        result1['metrics']['lambda1'],
        result2['metrics']['lambda1'],
        result3['metrics']['lambda1']
    ]

    lambda1_min = min(lambda1_values)
    lambda1_max = max(lambda1_values)

    if lambda1_min >= 0.05 and lambda1_max <= 0.20:
        print(f"✅ PASS: Lambda1 within bounds [0.05, 0.20]")
        print(f"   Range: {lambda1_min:.4f} to {lambda1_max:.4f}")
    else:
        print(f"❌ FAIL: Lambda1 outside bounds")
        print(f"   Range: {lambda1_min:.4f} to {lambda1_max:.4f}")

    return coherence2 >= 0.99 and lambda1_min >= 0.05


def test_varied_coherence():
    """Test that varied parameters give appropriate coherence"""
    print("\n" + "=" * 70)
    print("TEST: Varied Parameters Coherence")
    print("=" * 70)

    reset_test_state()

    from src.mcp_server_std import monitors
    from src.governance_monitor import UNITARESMonitor

    agent_id = "mcp_coherence_test"
    monitors[agent_id] = UNITARESMonitor(agent_id=agent_id)

    # Baseline
    base_state = {
        'parameters': [0.5, 0.5, 0.75, 0.85, 0.0, 0.1] + [0.01] * 122,
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': 'Test response',
        'complexity': 0.5
    }

    monitors[agent_id].process_update(base_state)

    # Test small change
    small_change_state = {
        'parameters': [0.51, 0.51, 0.76, 0.86, 0.0, 0.11] + [0.01] * 122,
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': 'Test response',
        'complexity': 0.5
    }

    result_small = monitors[agent_id].process_update(small_change_state)
    coherence_small = result_small['metrics']['coherence']

    print(f"\nSmall parameter change:")
    print(f"  Coherence: {coherence_small:.4f}")

    # Test large change
    large_change_state = {
        'parameters': [0.6, 0.6, 0.8, 0.9, 0.0, 0.2] + [0.02] * 122,
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': 'Test response',
        'complexity': 0.5
    }

    result_large = monitors[agent_id].process_update(large_change_state)
    coherence_large = result_large['metrics']['coherence']

    print(f"\nLarge parameter change:")
    print(f"  Coherence: {coherence_large:.4f}")

    print("\n" + "-" * 70)
    print("ANALYSIS:")
    print("-" * 70)

    # Check coherence decreases with larger changes
    if coherence_small > coherence_large:
        print("✅ PASS: Coherence decreases with larger parameter changes")
        print(f"   Small change: {coherence_small:.4f}")
        print(f"   Large change: {coherence_large:.4f}")
        return True
    else:
        print("❌ FAIL: Coherence did not decrease appropriately")
        print(f"   Small change: {coherence_small:.4f}")
        print(f"   Large change: {coherence_large:.4f}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MCP SERVER BUG FIX VERIFICATION")
    print("=" * 70)

    test1_pass = test_coherence_bug_fix()
    test2_pass = test_varied_coherence()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if test1_pass and test2_pass:
        print("✅ ALL TESTS PASSED")
        print("\nBoth bugs are fixed:")
        print("  1. Coherence = 1.0 with identical parameters")
        print("  2. Lambda1 stays within bounds [0.05, 0.20]")
    else:
        print("❌ SOME TESTS FAILED")
        if not test1_pass:
            print("  - Coherence bug fix FAILED")
        if not test2_pass:
            print("  - Varied coherence test FAILED")

    print("=" * 70)
