"""
Behavioral tests for EISV dynamics.

These tests verify that the thermodynamic model produces correct
qualitative behavior — convergence, degradation, recovery, imbalance
tracking, and coherence feedback. Pure math, no DB or mocking.
"""

import pytest

from governance_core.dynamics import State, compute_dynamics
from governance_core.parameters import DEFAULT_THETA, get_active_params
from governance_core.scoring import phi_objective, verdict_from_phi


def _run(state, delta_eta, theta, params, steps, complexity=0.5, dt=0.1):
    """Run dynamics for N steps, returning list of states (including initial)."""
    trajectory = [state]
    for _ in range(steps):
        state = compute_dynamics(
            state=state,
            delta_eta=delta_eta,
            theta=theta,
            params=params,
            dt=dt,
            complexity=complexity,
        )
        trajectory.append(state)
    return trajectory


class TestConvergenceFromDefault:
    """Default state (E=0.7, I=0.8, S=0.2, V=0.0) converges to healthy equilibrium."""

    @pytest.fixture()
    def trajectory(self):
        params = get_active_params()
        state = State(E=0.7, I=0.8, S=0.2, V=0.0)
        return _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=200)

    def test_energy_converges_high(self, trajectory):
        final = trajectory[-1]
        assert final.E > 0.7, f"E should converge above 0.7, got {final.E:.4f}"

    def test_integrity_converges_high(self, trajectory):
        final = trajectory[-1]
        assert final.I > 0.7, f"I should converge above 0.7, got {final.I:.4f}"

    def test_entropy_converges_low(self, trajectory):
        final = trajectory[-1]
        assert final.S < 0.1, f"S should converge below 0.1, got {final.S:.4f}"

    def test_void_stays_near_zero(self, trajectory):
        final = trajectory[-1]
        assert abs(final.V) < 0.05, f"|V| should stay below 0.05, got {abs(final.V):.4f}"

    def test_verdict_is_safe_or_caution(self, trajectory):
        """At default complexity=0.5, verdict should be 'safe' or 'caution'.

        With phi_safe_threshold=0.13, the default equilibrium (phi~0.20)
        is correctly classified as 'safe'. Typical healthy agents should
        not perpetually show 'caution'.
        """
        final = trajectory[-1]
        phi = phi_objective(final, delta_eta=[0.0])
        v = verdict_from_phi(phi)
        assert v in ("safe", "caution"), f"Verdict should be 'safe' or 'caution', got '{v}' (phi={phi:.4f})"

    def test_state_stabilizes(self, trajectory):
        """Last 20 steps should show minimal change (< 1e-3 total drift per step)."""
        late = trajectory[-20:]
        max_drift = max(
            abs(late[i + 1].E - late[i].E)
            + abs(late[i + 1].I - late[i].I)
            + abs(late[i + 1].S - late[i].S)
            + abs(late[i + 1].V - late[i].V)
            for i in range(len(late) - 1)
        )
        assert max_drift < 1e-3, f"State should stabilize, max step drift = {max_drift:.6f}"


class TestDegradationUnderStress:
    """High complexity + ethical drift degrades the system."""

    @pytest.fixture()
    def trajectories(self):
        params = get_active_params()
        state = State(E=0.7, I=0.8, S=0.2, V=0.0)
        before = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=50)
        stressed = _run(state, delta_eta=[0.5, 0.5], theta=DEFAULT_THETA, params=params, steps=100, complexity=0.9)
        return before, stressed

    def test_integrity_decreases(self, trajectories):
        _, stressed = trajectories
        assert stressed[-1].I < stressed[0].I, "I should decrease under stress"

    def test_entropy_increases(self, trajectories):
        _, stressed = trajectories
        assert stressed[-1].S > stressed[0].S, "S should increase under stress"

    def test_verdict_degrades(self, trajectories):
        _, stressed = trajectories
        phi = phi_objective(stressed[-1], delta_eta=[0.5, 0.5])
        v = verdict_from_phi(phi)
        assert v == "high-risk", f"Verdict should be 'high-risk' under stress, got '{v}' (phi={phi:.4f})"


class TestRecoveryFromDegraded:
    """A degraded state recovers when drift is removed."""

    @pytest.fixture()
    def trajectory(self):
        params = get_active_params()
        # Start degraded. With C1=3.0, recovery from V=-0.3 is slower because
        # C(V=-0.3) ≈ 0.14 (vs 0.36 with C1=1.0), suppressing I growth early on.
        degraded = State(E=0.4, I=0.3, S=0.8, V=-0.3)
        return _run(degraded, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=500)

    def test_energy_recovers(self, trajectory):
        assert trajectory[-1].E > 0.7, f"E should recover above 0.7, got {trajectory[-1].E:.4f}"

    def test_integrity_recovers(self, trajectory):
        assert trajectory[-1].I > 0.7, f"I should recover above 0.7, got {trajectory[-1].I:.4f}"

    def test_entropy_recovers(self, trajectory):
        assert trajectory[-1].S < 0.1, f"S should recover below 0.1, got {trajectory[-1].S:.4f}"

    def test_verdict_transitions_from_high_risk(self, trajectory):
        """Recovery should move verdict away from high-risk.

        With phi_safe_threshold=0.13, the recovered equilibrium at
        default complexity=0.5 lands at 'safe' (phi~0.20). The key property
        is that the system recovers from 'high-risk' to a non-critical state.
        """
        phi_start = phi_objective(trajectory[0], delta_eta=[0.0])
        phi_end = phi_objective(trajectory[-1], delta_eta=[0.0])
        v_start = verdict_from_phi(phi_start)
        v_end = verdict_from_phi(phi_end)
        assert v_start == "high-risk", f"Initial verdict should be 'high-risk', got '{v_start}'"
        assert v_end in ("safe", "caution"), f"Final verdict should be 'safe' or 'caution', got '{v_end}' (phi={phi_end:.4f})"


class TestVTracksImbalance:
    """V integrates (E-I) with damping."""

    def test_v_positive_when_e_exceeds_i(self):
        params = get_active_params()
        state = State(E=0.9, I=0.3, S=0.1, V=0.0)
        traj = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=20)
        # V should become positive (E > I → positive accumulation)
        assert traj[5].V > 0, f"V should be positive when E>I, got {traj[5].V:.4f}"

    def test_v_negative_when_i_exceeds_e(self):
        params = get_active_params()
        state = State(E=0.3, I=0.9, S=0.1, V=0.0)
        traj = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=20)
        # V should become negative (I > E → negative accumulation)
        assert traj[5].V < 0, f"V should be negative when I>E, got {traj[5].V:.4f}"

    def test_v_decays_when_balanced(self):
        params = get_active_params()
        # Start with nonzero V but balanced E≈I
        state = State(E=0.75, I=0.75, S=0.1, V=0.5)
        traj = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=50)
        assert abs(traj[-1].V) < abs(traj[0].V), "V should decay toward zero when E≈I"


class TestCoherenceFeedbackStabilizes:
    """Coherence feedback prevents I collapse — compare normal vs zero-coherence."""

    def test_coherence_boosts_integrity(self):
        params = get_active_params()
        state = State(E=0.5, I=0.5, S=0.5, V=0.0)

        # Normal run with coherence
        traj_normal = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=100)

        # Run with zero coherence boost (beta_I=0)
        from dataclasses import replace
        params_no_coh = replace(params, beta_I=0.0)
        traj_no_coh = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params_no_coh, steps=100)

        assert traj_normal[-1].I > traj_no_coh[-1].I, (
            f"I with coherence ({traj_normal[-1].I:.4f}) should exceed "
            f"I without ({traj_no_coh[-1].I:.4f})"
        )

    def test_coherence_boosts_phi(self):
        params = get_active_params()
        state = State(E=0.5, I=0.5, S=0.5, V=0.0)

        traj_normal = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params, steps=100)
        from dataclasses import replace
        params_no_coh = replace(params, beta_I=0.0)
        traj_no_coh = _run(state, delta_eta=[0.0], theta=DEFAULT_THETA, params=params_no_coh, steps=100)

        phi_normal = phi_objective(traj_normal[-1], delta_eta=[0.0])
        phi_no_coh = phi_objective(traj_no_coh[-1], delta_eta=[0.0])
        assert phi_normal > phi_no_coh, (
            f"Phi with coherence ({phi_normal:.4f}) should exceed "
            f"Phi without ({phi_no_coh:.4f})"
        )
