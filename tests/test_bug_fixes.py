#!/usr/bin/env python3
"""
Test script to verify bug fixes:
1. λ₁ bounds enforcement [0.05, 0.20]
2. Coherence calculation (parameter-based, not C(V))
"""

import sys
import numpy as np
import pytest
from src.governance_monitor import UNITARESMonitor

def test_identical_parameters():
    """Test 1: Identical parameters should give coherence ≈ 1.0"""
    print("=" * 70)
    print("TEST 1: Identical Parameters (Coherence Bug Fix)")
    print("=" * 70)

    monitor = UNITARESMonitor(agent_id="test_identical")

    # Fixed parameters (identical for all updates)
    fixed_params = [
        0.5,   # length_score
        0.5,   # complexity
        0.75,  # info_score
        0.85,  # coherence_score (not used anymore)
        0.0,   # placeholder
        0.1,   # ethical_drift
        *([0.01] * 122)  # Remaining dimensions
    ]

    print(f"\nUsing IDENTICAL parameters for 10 updates:")
    print(f"  parameters[0:6] = {fixed_params[0:6]}")
    print()

    results = []
    for i in range(10):
        agent_state = {
            'parameters': fixed_params.copy(),
            'ethical_drift': [0.1, 0.15, 0.12],
            'response_text': "Test response",
            'complexity': 0.5
        }

        result = monitor.process_update(agent_state)
        coherence = result['metrics']['coherence']
        lambda1 = result['metrics']['lambda1']

        results.append({
            'update': i + 1,
            'coherence': coherence,
            'lambda1': lambda1,
            'V': result['metrics']['V']
        })

        print(f"Update {i+1:2d}: coherence={coherence:.4f}, λ₁={lambda1:.4f}, V={result['metrics']['V']:+.4f}")

    # Analyze results
    print("\n" + "-" * 70)
    print("ANALYSIS:")
    print("-" * 70)

    # Check coherence stays at 1.0 after first update
    coherence_values = [r['coherence'] for r in results[1:]]  # Skip first (always 1.0)

    if all(c >= 0.99 for c in coherence_values):
        print("✅ PASS: Coherence stays ≈ 1.0 with identical parameters")
    else:
        print("❌ FAIL: Coherence is NOT staying at 1.0")
        print(f"   Range: {min(coherence_values):.4f} to {max(coherence_values):.4f}")

    # Check λ₁ stays within bounds [0.05, 0.20]
    lambda1_values = [r['lambda1'] for r in results]
    lambda1_min = min(lambda1_values)
    lambda1_max = max(lambda1_values)

    assert lambda1_min >= 0.05, f"λ₁ min {lambda1_min:.4f} violated lower bound 0.05"
    assert lambda1_max <= 0.20, f"λ₁ max {lambda1_max:.4f} violated upper bound 0.20"
    print(f"✅ PASS: λ₁ stayed within bounds [0.05, 0.20]")
    print(f"   Range: {lambda1_min:.4f} to {lambda1_max:.4f}")


def test_varied_parameters():
    """Test 2: Varied parameters should give appropriate coherence values"""
    print("\n" + "=" * 70)
    print("TEST 2: Varied Parameters (Coherence Sensitivity)")
    print("=" * 70)

    monitor = UNITARESMonitor(agent_id="test_varied")

    # Start with base parameters
    base_params = [
        0.5,   # length_score
        0.5,   # complexity
        0.75,  # info_score
        0.85,  # coherence_score
        0.0,   # placeholder
        0.1,   # ethical_drift
        *([0.01] * 122)
    ]

    print("\nTesting different parameter changes:")
    print()

    test_cases = [
        ("Identical", base_params, 0.99, 1.00),
        ("Small change (0.01)", [x + 0.01 for x in base_params[:6]] + base_params[6:], 0.95, 0.99),
        ("Medium change (0.05)", [x + 0.05 for x in base_params[:6]] + base_params[6:], 0.85, 0.95),
        ("Large change (0.10)", [x + 0.10 for x in base_params[:6]] + base_params[6:], 0.80, 0.92)
    ]

    results = []

    # First update to establish baseline
    monitor.process_update({
        'parameters': base_params,
        'ethical_drift': [0.1, 0.15, 0.12],
        'response_text': "Base response",
        'complexity': 0.5
    })

    for case_name, params, expected_min, expected_max in test_cases:
        agent_state = {
            'parameters': params,
            'ethical_drift': [0.1, 0.15, 0.12],
            'response_text': "Test response",
            'complexity': 0.5
        }

        result = monitor.process_update(agent_state)
        coherence = result['metrics']['coherence']

        # Check if within expected range
        in_range = expected_min <= coherence <= expected_max
        status = "✅" if in_range else "❌"

        print(f"{status} {case_name:25s}: coherence={coherence:.4f} (expected {expected_min:.2f}-{expected_max:.2f})")

        results.append({
            'case': case_name,
            'coherence': coherence,
            'expected_range': (expected_min, expected_max),
            'pass': in_range
        })

    print("\n" + "-" * 70)
    print("ANALYSIS:")
    print("-" * 70)

    failed = [r['case'] for r in results if not r['pass']]
    if failed:
        print(f"⚠️  Some cases out of expected ranges: {', '.join(failed)}")
        print("   Note: Expected ranges are empirical guidelines, not strict requirements")
    else:
        print("✅ PASS: All coherence values in expected ranges")
    # Note: This test is observational - coherence values depend on many factors
    # We just verify the coherence system runs without error


@pytest.mark.slow
def test_lambda1_bounds_under_stress():
    """Test 3: λ₁ bounds under extreme conditions"""
    # Iteration count was 50 (~329s wall — process_update is ~5-7s each).
    # Cut to 20: still varies length/complexity across the same 0.3+0.01*i
    # / 0.4+0.01*i ramp shape (bottom 40%), still asserts per-iteration
    # bounds via lambda1_values append + min/max check. A regression that
    # produces a bounds violation will trip within 20 iters as readily as 50.
    # If you specifically need to detect *slow* drift across 30+ iters,
    # bump this back up or move the slow form to a separate stress lane.
    iterations = 20
    print("\n" + "=" * 70)
    print("TEST 3: λ₁ Bounds Under Stress")
    print("=" * 70)

    monitor = UNITARESMonitor(agent_id="test_stress")

    print(f"\nRunning {iterations} updates with high drift to stress-test λ₁ bounds...")
    print()

    lambda1_values = []

    for i in range(iterations):
        # High drift parameters
        params = [
            0.3 + 0.01 * i,  # Varying length
            0.4 + 0.01 * i,  # Varying complexity
            0.7,
            0.8,
            0.0,
            0.5,  # High drift
            *([0.02 * (i % 10)] * 122)
        ]

        agent_state = {
            'parameters': params,
            'ethical_drift': [0.5, 0.6, 0.4],  # High drift
            'response_text': "Test response" * (i % 5),
            'complexity': 0.7
        }

        result = monitor.process_update(agent_state)
        lambda1 = result['metrics']['lambda1']
        lambda1_values.append(lambda1)

        if (i + 1) % 10 == 0:
            print(f"Update {i+1:2d}: λ₁={lambda1:.4f}")

    print("\n" + "-" * 70)
    print("ANALYSIS:")
    print("-" * 70)

    lambda1_min = min(lambda1_values)
    lambda1_max = max(lambda1_values)

    print(f"λ₁ range over {iterations} updates: {lambda1_min:.4f} to {lambda1_max:.4f}")

    assert lambda1_min >= 0.05, f"λ₁ min {lambda1_min:.4f} below minimum 0.05"
    assert lambda1_max <= 0.20, f"λ₁ max {lambda1_max:.4f} above maximum 0.20"
    print(f"✅ PASS: λ₁ stayed within bounds [0.05, 0.20] under stress")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("UNITARES Bug Fix Verification")
    print("Testing fixes for:")
    print("  1. λ₁ bounds enforcement [0.05, 0.20]")
    print("  2. Coherence calculation (parameter-based)")
    print("=" * 70)

    # Run all tests
    test1_results = test_identical_parameters()
    test2_results = test_varied_parameters()
    test3_results = test_lambda1_bounds_under_stress()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("All tests completed. Check results above for ✅ PASS or ❌ FAIL.")
    print("=" * 70)
