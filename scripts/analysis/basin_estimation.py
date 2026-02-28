#!/usr/bin/env python3
"""
Monte Carlo Basin Estimation for UNITARES EISV Attractor

Maps the safe operating region by random perturbation sampling.
Generates 2D heatmap slices of the 4D EISV basin of attraction.

Usage:
    python scripts/basin_estimation.py [--samples N] [--steps T] [--output-dir DIR] [--no-plot]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from governance_core.dynamics import (
    compute_dynamics, compute_equilibrium, State, check_basin,
)
from governance_core.parameters import (
    Theta, get_active_params, DEFAULT_THETA, get_i_dynamics_mode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def state_to_vec(state: State) -> np.ndarray:
    return np.array([state.E, state.I, state.S, state.V])


def vec_to_state(vec: np.ndarray) -> State:
    return State(E=float(vec[0]), I=float(vec[1]),
                 S=float(vec[2]), V=float(vec[3]))


def state_distance(a: State, b: State) -> float:
    return float(np.linalg.norm(state_to_vec(a) - state_to_vec(b)))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def integrate_trajectory(
    initial: State,
    params,
    theta: Theta,
    delta_eta: List[float],
    n_steps: int = 100,
    dt: float = 0.1,
    complexity: float = 0.5,
) -> List[State]:
    """Integrate forward from initial state for n_steps using compute_dynamics()."""
    trajectory = [initial]
    state = initial
    for _ in range(n_steps):
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


def classify_trajectory(
    trajectory: List[State],
    equilibrium: State,
    epsilon: float = 0.01,
) -> Dict[str, Any]:
    """
    Classify a trajectory as convergent, divergent, or stuck.

    Convergent: min distance to equilibrium < epsilon
    Divergent: final distance > 2x initial distance, or final state at bounds
    Stuck: neither
    """
    eq_vec = state_to_vec(equilibrium)
    distances = [float(np.linalg.norm(state_to_vec(s) - eq_vec))
                 for s in trajectory]

    min_dist = min(distances)
    final_dist = distances[-1]
    initial_dist = distances[0]
    converge_step = None

    classification = 'stuck'

    if min_dist < epsilon:
        classification = 'convergent'
        converge_step = next(i for i, d in enumerate(distances) if d < epsilon)
    else:
        final = trajectory[-1]
        at_bounds = (
            final.E <= 0.001 or final.E >= 0.999
            or final.I <= 0.001 or final.I >= 0.999
            or final.S >= 1.999
            or abs(final.V) >= 1.999
        )
        # Check distance trend in last quarter
        quarter = max(2, len(distances) // 4)
        tail = distances[-quarter:]
        monotone_increasing = all(
            tail[i + 1] >= tail[i] - 1e-6 for i in range(len(tail) - 1)
        )
        if at_bounds or (final_dist > initial_dist * 2) or monotone_increasing:
            classification = 'divergent'
        elif final_dist < initial_dist * 0.5 and final_dist < epsilon * 3:
            # Clearly converging but hasn't reached epsilon yet
            classification = 'convergent'
            converge_step = None  # Approximate convergence

    return {
        'classification': classification,
        'min_distance': min_dist,
        'final_distance': final_dist,
        'initial_distance': initial_dist,
        'converge_step': converge_step,
        'basin_label': check_basin(trajectory[-1]),
        'lyapunov_curve': [d * d for d in distances],
    }


def generate_perturbations(
    equilibrium: State,
    n_samples: int = 10000,
    magnitudes: Optional[np.ndarray] = None,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate random perturbations around equilibrium in 4D EISV space.

    Samples uniformly on the 4-sphere surface at each magnitude,
    then clips to state bounds.
    """
    rng = np.random.default_rng(seed)
    eq_vec = state_to_vec(equilibrium)

    if magnitudes is None:
        # Denser sampling near expected boundary (0.05-0.3)
        magnitudes = np.concatenate([
            np.linspace(0.01, 0.05, 10),
            np.linspace(0.05, 0.30, 30),
            np.linspace(0.30, 0.50, 10),
        ])

    # Distribute samples across magnitude levels
    samples_per_mag = max(1, n_samples // len(magnitudes))
    remainder = n_samples - samples_per_mag * len(magnitudes)

    results = []
    for i, mag in enumerate(magnitudes):
        n = samples_per_mag + (1 if i < remainder else 0)
        # Random directions on 4-sphere
        directions = rng.standard_normal((n, 4))
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        directions = directions / norms
        # Scale by magnitude and offset from equilibrium
        perturbed = eq_vec + directions * mag
        results.append(perturbed)

    all_perturbed = np.vstack(results)

    # Clip to state bounds
    all_perturbed[:, 0] = np.clip(all_perturbed[:, 0], 0.0, 1.0)    # E
    all_perturbed[:, 1] = np.clip(all_perturbed[:, 1], 0.0, 1.0)    # I
    all_perturbed[:, 2] = np.clip(all_perturbed[:, 2], 0.001, 2.0)  # S
    all_perturbed[:, 3] = np.clip(all_perturbed[:, 3], -2.0, 2.0)   # V

    return all_perturbed[:n_samples]


def run_basin_estimation(
    n_samples: int = 10000,
    n_steps: int = 100,
    dt: float = 0.1,
    epsilon: float = 0.01,
    complexity: float = 0.5,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Main basin estimation routine.

    1. Compute equilibrium
    2. Generate perturbations
    3. Integrate each forward
    4. Classify trajectories
    5. Compute empirical basin boundary
    """
    params = get_active_params()
    theta = DEFAULT_THETA
    delta_eta = [0.0] * 5

    eq = compute_equilibrium(params, theta, complexity=complexity)
    eq_vec = state_to_vec(eq)

    print(f"Equilibrium: E={eq.E:.4f}, I={eq.I:.4f}, S={eq.S:.4f}, V={eq.V:.4f}")
    print(f"I-dynamics mode: {get_i_dynamics_mode()}")
    print(f"Params: alpha={params.alpha}, gamma_I={params.gamma_I}, mu={params.mu}")
    print(f"Generating {n_samples} perturbations...")

    perturbations = generate_perturbations(eq, n_samples, seed=seed)

    results_list = []
    n_convergent = 0
    n_divergent = 0
    n_stuck = 0

    for i in range(n_samples):
        if (i + 1) % 1000 == 0 or i == 0:
            print(f"  Integrating sample {i + 1}/{n_samples}...")

        initial = vec_to_state(perturbations[i])
        traj = integrate_trajectory(initial, params, theta, delta_eta,
                                    n_steps=n_steps, dt=dt, complexity=complexity)
        result = classify_trajectory(traj, eq, epsilon=epsilon)

        mag = float(np.linalg.norm(perturbations[i] - eq_vec))
        result['perturbation_magnitude'] = mag
        result['initial_state'] = state_to_vec(initial).tolist()

        if result['classification'] == 'convergent':
            n_convergent += 1
        elif result['classification'] == 'divergent':
            n_divergent += 1
        else:
            n_stuck += 1

        # Don't store full Lyapunov curves in bulk (too much memory)
        # Keep a sample of 100 for plotting
        if i >= 100:
            del result['lyapunov_curve']

        results_list.append(result)

    # Compute max safe perturbation (95% convergence threshold)
    mag_convergence = {}
    for r in results_list:
        mag = round(r['perturbation_magnitude'], 3)
        if mag not in mag_convergence:
            mag_convergence[mag] = {'total': 0, 'convergent': 0}
        mag_convergence[mag]['total'] += 1
        if r['classification'] == 'convergent':
            mag_convergence[mag]['convergent'] += 1

    max_safe = 0.0
    for mag in sorted(mag_convergence.keys()):
        info = mag_convergence[mag]
        frac = info['convergent'] / info['total'] if info['total'] > 0 else 0
        if frac >= 0.95:
            max_safe = mag

    return {
        'equilibrium': state_to_vec(eq).tolist(),
        'n_samples': n_samples,
        'n_convergent': n_convergent,
        'n_divergent': n_divergent,
        'n_stuck': n_stuck,
        'convergence_fraction': n_convergent / n_samples,
        'max_safe_perturbation': max_safe,
        'results': results_list,
        'params_summary': {
            'i_mode': get_i_dynamics_mode(),
            'alpha': params.alpha,
            'beta_E': params.beta_E,
            'gamma_E': params.gamma_E,
            'k': params.k,
            'beta_I': params.beta_I,
            'gamma_I': params.gamma_I,
            'mu': params.mu,
            'kappa': params.kappa,
            'delta': params.delta,
            'dt': dt,
            'n_steps': n_steps,
            'epsilon': epsilon,
            'complexity': complexity,
        },
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_basin_heatmaps(results: Dict[str, Any], output_dir: Path) -> None:
    """Generate 2D heatmap slices and analysis plots."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        'font.family': 'serif',
        'font.size': 10,
        'axes.labelsize': 11,
        'figure.dpi': 300,
        'savefig.bbox': 'tight',
        'savefig.pad_inches': 0.05,
    })

    output_dir.mkdir(parents=True, exist_ok=True)
    eq = results['equilibrium']
    data = results['results']

    colors = {
        'convergent': '#2ca02c',
        'divergent': '#d62728',
        'stuck': '#ff7f0e',
    }

    # Extract initial states and classifications
    initials = np.array([r['initial_state'] for r in data])
    labels = [r['classification'] for r in data]

    # Plot 2D slices: pairs of dimensions
    dim_names = ['E', 'I', 'S', 'V']
    slice_pairs = [(0, 1), (2, 3), (0, 2), (1, 3)]
    slice_names = ['ei', 'sv', 'es', 'iv']

    for (d1, d2), name in zip(slice_pairs, slice_names):
        fig, ax = plt.subplots(figsize=(4.5, 3.5))
        for cls in ['divergent', 'stuck', 'convergent']:
            mask = [l == cls for l in labels]
            if any(mask):
                idx = np.where(mask)[0]
                ax.scatter(initials[idx, d1], initials[idx, d2],
                           c=colors[cls], s=4, alpha=0.5, label=cls, rasterized=True)
        ax.scatter(eq[d1], eq[d2], c='black', marker='*', s=100,
                   zorder=10, label='equilibrium')
        ax.set_xlabel(dim_names[d1])
        ax.set_ylabel(dim_names[d2])
        ax.set_title(f'Basin: {dim_names[d1]}-{dim_names[d2]} plane')
        ax.legend(fontsize=8, markerscale=3)
        fig.savefig(output_dir / f'basin_{name}_heatmap.png')
        plt.close(fig)

    # Convergence fraction vs perturbation magnitude
    mags = [r['perturbation_magnitude'] for r in data]
    convs = [1 if r['classification'] == 'convergent' else 0 for r in data]

    # Bin by magnitude
    mag_bins = np.linspace(0, max(mags) * 1.01, 30)
    bin_indices = np.digitize(mags, mag_bins)
    bin_fracs = []
    bin_centers = []
    for b in range(1, len(mag_bins)):
        mask = bin_indices == b
        if np.sum(mask) > 0:
            bin_fracs.append(np.mean(np.array(convs)[mask]))
            bin_centers.append((mag_bins[b - 1] + mag_bins[b]) / 2)

    fig, ax = plt.subplots(figsize=(4.5, 3.0))
    ax.bar(bin_centers, bin_fracs, width=(mag_bins[1] - mag_bins[0]) * 0.9,
           color='#1f77b4', alpha=0.8)
    ax.axhline(0.95, color='red', linestyle='--', linewidth=1, label='95% threshold')
    safe = results['max_safe_perturbation']
    if safe > 0:
        ax.axvline(safe, color='green', linestyle='--', linewidth=1,
                   label=f'max safe = {safe:.3f}')
    ax.set_xlabel('Perturbation magnitude (EISV norm)')
    ax.set_ylabel('Convergence fraction')
    ax.set_title('Convergence vs Perturbation Magnitude')
    ax.legend(fontsize=8)
    ax.set_ylim(0, 1.05)
    fig.savefig(output_dir / 'convergence_vs_magnitude.png')
    plt.close(fig)

    # Lyapunov decay curves (first 100 samples that have curves)
    fig, ax = plt.subplots(figsize=(4.5, 3.0))
    n_plotted = 0
    for r in data:
        if 'lyapunov_curve' not in r:
            continue
        curve = r['lyapunov_curve']
        color = colors.get(r['classification'], '#999')
        ax.plot(curve, color=color, alpha=0.3, linewidth=0.5)
        n_plotted += 1
        if n_plotted >= 100:
            break
    ax.set_xlabel('Time step')
    ax.set_ylabel('||x(t) - x*||²')
    ax.set_title('Lyapunov Function Decay')
    ax.set_yscale('log')
    fig.savefig(output_dir / 'lyapunov_decay.png')
    plt.close(fig)

    print(f"Plots saved to {output_dir}/")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: Dict[str, Any]) -> None:
    n = results['n_samples']
    print("\n" + "=" * 60)
    print("BASIN ESTIMATION RESULTS")
    print("=" * 60)
    eq = results['equilibrium']
    print(f"Equilibrium: E={eq[0]:.4f}, I={eq[1]:.4f}, S={eq[2]:.4f}, V={eq[3]:.4f}")
    print(f"Samples: {n}")
    print(f"Convergent: {results['n_convergent']} ({results['convergence_fraction']:.1%})")
    print(f"Divergent:  {results['n_divergent']} ({results['n_divergent']/n:.1%})")
    print(f"Stuck:      {results['n_stuck']} ({results['n_stuck']/n:.1%})")
    print(f"Max safe perturbation (95%): {results['max_safe_perturbation']:.4f}")
    print(f"\nParameters: {results['params_summary']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Monte Carlo Basin Estimation')
    parser.add_argument('--samples', '-n', type=int, default=10000)
    parser.add_argument('--steps', '-t', type=int, default=500)
    parser.add_argument('--dt', type=float, default=0.1)
    parser.add_argument('--epsilon', type=float, default=0.05)
    parser.add_argument('--complexity', type=float, default=0.5)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output-dir', '-o', type=str, default='data/analysis/basin')
    parser.add_argument('--no-plot', action='store_true')
    args = parser.parse_args()

    results = run_basin_estimation(
        n_samples=args.samples,
        n_steps=args.steps,
        dt=args.dt,
        epsilon=args.epsilon,
        complexity=args.complexity,
        seed=args.seed,
    )

    print_summary(results)

    if not args.no_plot:
        plot_basin_heatmaps(results, Path(args.output_dir))

    # Save machine-readable results (without full Lyapunov curves)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_data = {k: v for k, v in results.items() if k != 'results'}
    # Add per-sample summary (classification + magnitude only)
    save_data['sample_summary'] = [
        {
            'classification': r['classification'],
            'perturbation_magnitude': r['perturbation_magnitude'],
            'min_distance': r['min_distance'],
            'final_distance': r['final_distance'],
            'basin_label': r['basin_label'],
        }
        for r in results['results']
    ]
    with open(out_dir / 'basin_results.json', 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"Results saved to {out_dir / 'basin_results.json'}")


if __name__ == '__main__':
    main()
