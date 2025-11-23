#!/usr/bin/env python3
"""
Milestone 4: Comprehensive Validation Tests

Cross-validation: UNITARES vs unitaires vs governance_core
Performance benchmarks
Load testing preparation
"""

import sys
import time
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple

# Add paths
project_root = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "unitaires-server"))

# Import all three implementations
from governance_core import (
    State as CoreState,
    Theta as CoreTheta,
    DynamicsParams as CoreParams,
    step_state as core_step_state,
    coherence as core_coherence,
    phi_objective as core_phi_objective,
    DEFAULT_STATE as CORE_DEFAULT_STATE,
    DEFAULT_THETA as CORE_DEFAULT_THETA,
    DEFAULT_PARAMS as CORE_DEFAULT_PARAMS,
    DEFAULT_WEIGHTS as CORE_DEFAULT_WEIGHTS,
)

from src.governance_monitor import UNITARESMonitor

import unitaires_core as uc


def cross_validate_dynamics() -> Tuple[bool, Dict]:
    """Cross-validate dynamics across all three implementations"""
    print("\n" + "="*70)
    print("CROSS-VALIDATION: UNITARES vs unitaires vs governance_core")
    print("="*70)
    
    # Create equivalent initial states
    core_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)
    
    # Create monitor (UNITARES)
    monitor = UNITARESMonitor("validation_test")
    monitor.state.unitaires_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    
    # Test cases
    test_cases = [
        ([0.0], "zero drift"),
        ([0.1, 0.0, -0.05], "small drift"),
        ([0.3, 0.2, 0.1], "medium drift"),
        ([0.5, 0.5, 0.5], "large drift"),
    ]
    
    all_match = True
    max_diff = 0.0
    results = []
    
    for delta_eta, description in test_cases:
        # governance_core
        core_new = core_step_state(
            state=core_state,
            theta=CORE_DEFAULT_THETA,
            delta_eta=delta_eta,
            dt=0.1,
            params=CORE_DEFAULT_PARAMS
        )
        
        # unitaires_core
        uc_new = uc.step_state(
            state=uc_state,
            theta=uc.DEFAULT_THETA,
            delta_eta=delta_eta,
            dt=0.1,
            params=uc.DEFAULT_PARAMS
        )
        
        # UNITARES (via monitor)
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": delta_eta,
            "response_text": "",
            "complexity": 0.5
        }
        monitor.state.unitaires_state = CoreState(E=core_state.E, I=core_state.I, S=core_state.S, V=core_state.V)
        monitor.update_dynamics(agent_state, dt=0.1)
        unitares_new = monitor.state.unitaires_state
        
        # Compare
        diff_core_uc = max(
            abs(core_new.E - uc_new.E),
            abs(core_new.I - uc_new.I),
            abs(core_new.S - uc_new.S),
            abs(core_new.V - uc_new.V),
        )
        
        diff_core_unitares = max(
            abs(core_new.E - unitares_new.E),
            abs(core_new.I - unitares_new.I),
            abs(core_new.S - unitares_new.S),
            abs(core_new.V - unitares_new.V),
        )
        
        diff_uc_unitares = max(
            abs(uc_new.E - unitares_new.E),
            abs(uc_new.I - unitares_new.I),
            abs(uc_new.S - unitares_new.S),
            abs(uc_new.V - unitares_new.V),
        )
        
        max_case_diff = max(diff_core_uc, diff_core_unitares, diff_uc_unitares)
        max_diff = max(max_diff, max_case_diff)
        
        match = max_case_diff < 1e-10
        all_match = all_match and match
        
        results.append({
            "description": description,
            "delta_eta": delta_eta,
            "core_uc_diff": diff_core_uc,
            "core_unitares_diff": diff_core_unitares,
            "uc_unitares_diff": diff_uc_unitares,
            "max_diff": max_case_diff,
            "match": match
        })
        
        print(f"\n  {description}:")
        print(f"    governance_core: E={core_new.E:.6f}, I={core_new.I:.6f}, S={core_new.S:.6f}, V={core_new.V:.6f}")
        print(f"    unitaires_core:  E={uc_new.E:.6f}, I={uc_new.I:.6f}, S={uc_new.S:.6f}, V={uc_new.V:.6f}")
        print(f"    UNITARES:        E={unitares_new.E:.6f}, I={unitares_new.I:.6f}, S={unitares_new.S:.6f}, V={unitares_new.V:.6f}")
        print(f"    Max diff: {max_case_diff:.2e} {'✅' if match else '❌'}")
        
        # Update states
        core_state = core_new
        uc_state = uc_new
    
    print(f"\n  Overall max difference: {max_diff:.2e}")
    print(f"  All match: {'✅ YES' if all_match else '❌ NO'}")
    
    return all_match, {"max_diff": max_diff, "results": results}


def benchmark_performance() -> Dict:
    """Benchmark performance of all three implementations"""
    print("\n" + "="*70)
    print("PERFORMANCE BENCHMARKS")
    print("="*70)
    
    num_iterations = 1000
    delta_eta = [0.1, 0.05, 0.15]
    
    # Benchmark governance_core
    core_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    start = time.perf_counter()
    for _ in range(num_iterations):
        core_state = core_step_state(
            state=core_state,
            theta=CORE_DEFAULT_THETA,
            delta_eta=delta_eta,
            dt=0.1,
            params=CORE_DEFAULT_PARAMS
        )
    core_time = time.perf_counter() - start
    
    # Benchmark unitaires_core
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)
    start = time.perf_counter()
    for _ in range(num_iterations):
        uc_state = uc.step_state(
            state=uc_state,
            theta=uc.DEFAULT_THETA,
            delta_eta=delta_eta,
            dt=0.1,
            params=uc.DEFAULT_PARAMS
        )
    uc_time = time.perf_counter() - start
    
    # Benchmark UNITARES (via monitor)
    monitor = UNITARESMonitor("benchmark_test")
    agent_state = {
        "parameters": np.random.randn(128) * 0.01,
        "ethical_drift": delta_eta,
        "response_text": "",
        "complexity": 0.5
    }
    start = time.perf_counter()
    for _ in range(num_iterations):
        monitor.update_dynamics(agent_state, dt=0.1)
    unitares_time = time.perf_counter() - start
    
    core_ops_per_sec = num_iterations / core_time
    uc_ops_per_sec = num_iterations / uc_time
    unitares_ops_per_sec = num_iterations / unitares_time
    
    print(f"\n  Iterations: {num_iterations}")
    print(f"  governance_core: {core_time*1000:.2f}ms ({core_ops_per_sec:.0f} ops/sec)")
    print(f"  unitaires_core:  {uc_time*1000:.2f}ms ({uc_ops_per_sec:.0f} ops/sec)")
    print(f"  UNITARES:        {unitares_time*1000:.2f}ms ({unitares_ops_per_sec:.0f} ops/sec)")
    
    # Calculate overhead
    core_overhead = 0.0
    uc_overhead = (uc_time - core_time) / core_time * 100
    unitares_overhead = (unitares_time - core_time) / core_time * 100
    
    print(f"\n  Overhead vs governance_core:")
    print(f"    unitaires_core:  {uc_overhead:+.1f}%")
    print(f"    UNITARES:        {unitares_overhead:+.1f}%")
    
    return {
        "iterations": num_iterations,
        "governance_core_time": core_time,
        "unitaires_core_time": uc_time,
        "unitares_time": unitares_time,
        "governance_core_ops_per_sec": core_ops_per_sec,
        "unitaires_core_ops_per_sec": uc_ops_per_sec,
        "unitares_ops_per_sec": unitares_ops_per_sec,
        "overhead": {
            "unitaires_core": uc_overhead,
            "unitares": unitares_overhead
        }
    }


def test_coherence_consistency() -> Tuple[bool, Dict]:
    """Test coherence function consistency"""
    print("\n" + "="*70)
    print("COHERENCE FUNCTION CONSISTENCY")
    print("="*70)
    
    theta = CoreTheta(C1=1.0, eta1=0.3)
    test_Vs = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]
    
    all_match = True
    max_diff = 0.0
    results = []
    
    for V in test_Vs:
        core_C = core_coherence(V, theta, CORE_DEFAULT_PARAMS)
        uc_C = uc.coherence(V, uc.Theta(C1=1.0, eta1=0.3), uc.DEFAULT_PARAMS)
        
        diff = abs(core_C - uc_C)
        max_diff = max(max_diff, diff)
        match = diff < 1e-10
        all_match = all_match and match
        
        results.append({
            "V": V,
            "governance_core": core_C,
            "unitaires_core": uc_C,
            "diff": diff,
            "match": match
        })
        
        print(f"  V={V:5.1f}: governance_core={core_C:.6f}, unitaires_core={uc_C:.6f}, diff={diff:.2e} {'✅' if match else '❌'}")
    
    print(f"\n  Max difference: {max_diff:.2e}")
    print(f"  All match: {'✅ YES' if all_match else '❌ NO'}")
    
    return all_match, {"max_diff": max_diff, "results": results}


def test_phi_consistency() -> Tuple[bool, Dict]:
    """Test phi objective consistency"""
    print("\n" + "="*70)
    print("PHI OBJECTIVE CONSISTENCY")
    print("="*70)
    
    state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)
    test_deltas = [
        [],
        [0.0],
        [0.1, 0.0, -0.05],
        [0.3, 0.2, 0.1],
    ]
    
    all_match = True
    max_diff = 0.0
    results = []
    
    for delta_eta in test_deltas:
        core_phi = core_phi_objective(state, delta_eta, CORE_DEFAULT_WEIGHTS)
        uc_phi = uc.phi_objective(uc_state, delta_eta, uc.DEFAULT_WEIGHTS)
        
        diff = abs(core_phi - uc_phi)
        max_diff = max(max_diff, diff)
        match = diff < 1e-10
        all_match = all_match and match
        
        results.append({
            "delta_eta": delta_eta,
            "governance_core": core_phi,
            "unitaires_core": uc_phi,
            "diff": diff,
            "match": match
        })
        
        print(f"  delta_eta={delta_eta}: governance_core={core_phi:.6f}, unitaires_core={uc_phi:.6f}, diff={diff:.2e} {'✅' if match else '❌'}")
    
    print(f"\n  Max difference: {max_diff:.2e}")
    print(f"  All match: {'✅ YES' if all_match else '❌ NO'}")
    
    return all_match, {"max_diff": max_diff, "results": results}


def run_all_validation_tests() -> int:
    """Run all validation tests"""
    print("="*70)
    print("MILESTONE 4: COMPREHENSIVE VALIDATION")
    print("="*70)
    
    results = {}
    
    # Cross-validation
    dynamics_match, dynamics_results = cross_validate_dynamics()
    results["dynamics"] = {"match": dynamics_match, **dynamics_results}
    
    # Coherence consistency
    coherence_match, coherence_results = test_coherence_consistency()
    results["coherence"] = {"match": coherence_match, **coherence_results}
    
    # Phi consistency
    phi_match, phi_results = test_phi_consistency()
    results["phi"] = {"match": phi_match, **phi_results}
    
    # Performance benchmarks
    perf_results = benchmark_performance()
    results["performance"] = perf_results
    
    # Summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)
    
    all_tests_pass = dynamics_match and coherence_match and phi_match
    
    print(f"\n  Cross-validation (dynamics):     {'✅ PASS' if dynamics_match else '❌ FAIL'}")
    print(f"  Coherence consistency:           {'✅ PASS' if coherence_match else '❌ FAIL'}")
    print(f"  Phi objective consistency:       {'✅ PASS' if phi_match else '❌ FAIL'}")
    print(f"  Performance benchmarks:          ✅ COMPLETE")
    
    print(f"\n  Overall: {'✅ ALL TESTS PASS' if all_tests_pass else '❌ SOME TESTS FAILED'}")
    
    if all_tests_pass:
        print("\n🎉 Perfect consistency across all implementations!")
        print("   UNITARES, unitaires, and governance_core produce identical results.")
    
    return 0 if all_tests_pass else 1


if __name__ == "__main__":
    sys.exit(run_all_validation_tests())

