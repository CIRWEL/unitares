#!/usr/bin/env python3
"""
Parity Test: governance_core vs unitaires_core

Verifies that the new governance_core module produces identical
results to the original unitaires_core.py implementation.

This ensures the extraction didn't introduce bugs.
"""

import sys
from pathlib import Path

# Add paths
project_root = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src" / "unitaires-server"))

# Import governance_core (new)
from governance_core import (
    State as CoreState,
    Theta as CoreTheta,
    DynamicsParams as CoreParams,
    compute_dynamics as core_compute,
    coherence as core_coherence,
    lambda1 as core_lambda1,
    lambda2 as core_lambda2,
    phi_objective as core_phi,
    verdict_from_phi as core_verdict,
    drift_norm as core_drift_norm,
)

# Import unitaires_core (original)
import unitaires_core as uc


def test_drift_norm_parity():
    """Test drift_norm produces same results"""
    print("\nTesting drift_norm parity...")

    test_cases = [
        [],
        [0.0],
        [0.3, 0.4],  # 3-4-5 triangle
        [0.1, -0.2, 0.3],
        [0.5, 0.5, 0.5],
    ]

    for delta_eta in test_cases:
        core_result = core_drift_norm(delta_eta)
        uc_result = uc.drift_norm(delta_eta)

        diff = abs(core_result - uc_result)
        assert diff < 1e-10, f"drift_norm mismatch for {delta_eta}: {core_result} vs {uc_result}"

    print(f"✅ drift_norm parity verified for {len(test_cases)} cases")
    return True


def test_coherence_parity():
    """Test coherence function produces same results"""
    print("\nTesting coherence parity...")

    # Create equivalent parameters
    core_params = CoreParams()
    uc_params = uc.DEFAULT_PARAMS

    # Create equivalent theta
    core_theta = CoreTheta(C1=1.0, eta1=0.3)
    uc_theta = uc.Theta(C1=1.0, eta1=0.3)

    test_Vs = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]

    for V in test_Vs:
        core_result = core_coherence(V, core_theta, core_params)
        uc_result = uc.coherence(V, uc_theta, uc_params)

        diff = abs(core_result - uc_result)
        assert diff < 1e-10, f"coherence mismatch at V={V}: {core_result} vs {uc_result}"

    print(f"✅ coherence parity verified for {len(test_Vs)} V values")
    return True


def test_lambda_parity():
    """Test lambda functions produce same results"""
    print("\nTesting lambda functions parity...")

    core_params = CoreParams()
    uc_params = uc.DEFAULT_PARAMS

    core_theta = CoreTheta(C1=1.0, eta1=0.3)
    uc_theta = uc.Theta(C1=1.0, eta1=0.3)

    # Test lambda1
    core_l1 = core_lambda1(core_theta, core_params)
    uc_l1 = uc.lambda1(uc_theta, uc_params)
    assert abs(core_l1 - uc_l1) < 1e-10, f"lambda1 mismatch: {core_l1} vs {uc_l1}"

    # Test lambda2
    core_l2 = core_lambda2(core_theta, core_params)
    uc_l2 = uc.lambda2(uc_theta, uc_params)
    assert abs(core_l2 - uc_l2) < 1e-10, f"lambda2 mismatch: {core_l2} vs {uc_l2}"

    print(f"✅ lambda1={core_l1:.4f}, lambda2={core_l2:.4f} - parity verified")
    return True


def test_dynamics_parity():
    """Test dynamics computation produces identical results"""
    print("\nTesting dynamics parity...")

    # Create equivalent initial states
    core_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)

    # Create equivalent parameters
    core_params = CoreParams()
    uc_params = uc.DEFAULT_PARAMS

    core_theta = CoreTheta(C1=1.0, eta1=0.3)
    uc_theta = uc.Theta(C1=1.0, eta1=0.3)

    # Test different delta_eta values
    test_cases = [
        [0.0],
        [0.1, 0.0, -0.05],
        [0.3, 0.2, 0.1],
        [],
    ]

    for delta_eta in test_cases:
        # Evolve both implementations
        core_new = core_compute(
            state=core_state,
            delta_eta=delta_eta,
            theta=core_theta,
            params=core_params,
            dt=0.1,
            noise_S=0.0,
        )

        uc_new = uc.step_state(
            state=uc_state,
            theta=uc_theta,
            delta_eta=delta_eta,
            dt=0.1,
            noise_S=0.0,
            params=uc_params,
        )

        # Compare results
        diff_E = abs(core_new.E - uc_new.E)
        diff_I = abs(core_new.I - uc_new.I)
        diff_S = abs(core_new.S - uc_new.S)
        diff_V = abs(core_new.V - uc_new.V)

        max_diff = max(diff_E, diff_I, diff_S, diff_V)

        print(f"  delta_eta={delta_eta}")
        print(f"    governance_core: E={core_new.E:.6f}, I={core_new.I:.6f}, S={core_new.S:.6f}, V={core_new.V:.6f}")
        print(f"    unitaires_core:  E={uc_new.E:.6f}, I={uc_new.I:.6f}, S={uc_new.S:.6f}, V={uc_new.V:.6f}")
        print(f"    max diff: {max_diff:.2e}")

        assert max_diff < 1e-10, f"Dynamics mismatch for {delta_eta}: max diff = {max_diff}"

        # Update states for next iteration
        core_state = core_new
        uc_state = uc_new

    print(f"✅ Dynamics parity verified for {len(test_cases)} cases")
    return True


def test_phi_parity():
    """Test phi_objective produces same results"""
    print("\nTesting phi_objective parity...")

    # Create equivalent states
    core_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)

    # Create equivalent weights (need to import from governance_core.parameters)
    from governance_core.parameters import Weights as CoreWeights
    core_weights = CoreWeights(wE=0.5, wI=0.5, wS=0.5, wV=0.5, wEta=0.5)
    uc_weights = uc.Weights(wE=0.5, wI=0.5, wS=0.5, wV=0.5, wEta=0.5)

    test_deltas = [
        [],
        [0.0],
        [0.1, 0.0, -0.05],
        [0.5, 0.3],
    ]

    for delta_eta in test_deltas:
        core_phi_result = core_phi(core_state, delta_eta, core_weights)
        uc_phi_result = uc.phi_objective(uc_state, delta_eta, uc_weights)

        diff = abs(core_phi_result - uc_phi_result)
        assert diff < 1e-10, f"phi_objective mismatch for {delta_eta}: {core_phi_result} vs {uc_phi_result}"

    print(f"✅ phi_objective parity verified for {len(test_deltas)} cases")
    return True


def test_verdict_parity():
    """Test verdict_from_phi produces same results"""
    print("\nTesting verdict_from_phi parity...")

    test_phis = [-1.0, -0.5, -0.01, 0.0, 0.01, 0.1, 0.3, 0.5, 1.0]

    for phi in test_phis:
        core_verdict_result = core_verdict(phi)
        uc_verdict_result = uc.verdict_from_phi(phi)

        assert core_verdict_result == uc_verdict_result, f"verdict mismatch at phi={phi}: {core_verdict_result} vs {uc_verdict_result}"

    print(f"✅ verdict_from_phi parity verified for {len(test_phis)} cases")
    return True


def test_multi_step_parity():
    """Test that multi-step evolution remains identical"""
    print("\nTesting multi-step evolution parity...")

    # Initial states
    core_state = CoreState(E=0.7, I=0.8, S=0.2, V=0.0)
    uc_state = uc.State(E=0.7, I=0.8, S=0.2, V=0.0)

    core_params = CoreParams()
    uc_params = uc.DEFAULT_PARAMS

    core_theta = CoreTheta(C1=1.0, eta1=0.3)
    uc_theta = uc.Theta(C1=1.0, eta1=0.3)

    # Evolve for 100 steps with varying drift
    num_steps = 100
    max_diff_history = []

    for i in range(num_steps):
        # Varying drift pattern
        delta_eta = [0.1 * (i % 3), 0.05 * ((i + 1) % 2), -0.02 * (i % 5)]

        core_state = core_compute(core_state, delta_eta, core_theta, core_params, dt=0.05)
        uc_state = uc.step_state(uc_state, uc_theta, delta_eta, dt=0.05, params=uc_params)

        # Track maximum difference
        max_diff = max(
            abs(core_state.E - uc_state.E),
            abs(core_state.I - uc_state.I),
            abs(core_state.S - uc_state.S),
            abs(core_state.V - uc_state.V),
        )
        max_diff_history.append(max_diff)

    final_max_diff = max(max_diff_history)
    avg_diff = sum(max_diff_history) / len(max_diff_history)

    print(f"  Steps: {num_steps}")
    print(f"  Max difference across all steps: {final_max_diff:.2e}")
    print(f"  Average difference: {avg_diff:.2e}")
    print(f"  Final states:")
    print(f"    governance_core: E={core_state.E:.6f}, I={core_state.I:.6f}, S={core_state.S:.6f}, V={core_state.V:.6f}")
    print(f"    unitaires_core:  E={uc_state.E:.6f}, I={uc_state.I:.6f}, S={uc_state.S:.6f}, V={uc_state.V:.6f}")

    assert final_max_diff < 1e-9, f"Multi-step evolution diverged: max diff = {final_max_diff}"

    print(f"✅ Multi-step parity verified - implementations are identical")
    return True


def run_all_tests():
    """Run all parity tests"""
    print("=" * 70)
    print("PARITY TEST: governance_core vs unitaires_core")
    print("=" * 70)
    print("\nThis test verifies that the new governance_core module produces")
    print("IDENTICAL results to the original unitaires_core.py implementation.")

    tests = [
        test_drift_norm_parity,
        test_coherence_parity,
        test_lambda_parity,
        test_dynamics_parity,
        test_phi_parity,
        test_verdict_parity,
        test_multi_step_parity,
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

    print("\n" + "=" * 70)
    print(f"RESULTS: {sum(results)}/{len(results)} parity tests passed")
    print("=" * 70)

    if all(results):
        print("\n🎉 PERFECT PARITY!")
        print("governance_core produces IDENTICAL results to unitaires_core")
        print("The extraction was successful with zero numerical drift.")
        return 0
    else:
        print("\n⚠️  Some parity tests failed.")
        print("There may be differences between implementations.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
