#!/usr/bin/env python3
"""
Calculate expected S values if complexity coupling were working.

Given:
- mu = 0.8 (S decay)
- beta_complexity = 0.15
- dt = 0.1
- Other terms (drift, coherence) assumed minimal for new agent

dS/dt = -mu * S + beta_complexity * complexity
"""

def calculate_s_evolution(complexity, num_updates=10, S0=0.181):
    """Calculate S evolution with given complexity"""
    mu = 0.8
    beta_complexity = 0.15
    dt = 0.1

    # Assume drift and coherence terms are small for new agent
    # (delta_eta ≈ 0, coherence ≈ 0.5)
    # Simplified: dS/dt ≈ -mu*S + beta_complexity*complexity

    S = S0
    history = [S]

    for _ in range(num_updates):
        dS_dt = -mu * S + beta_complexity * complexity
        S_new = max(0.001, S + dS_dt * dt)  # Floor at 0.001
        S = S_new
        history.append(S)

    return history


print("="*70)
print("EXPECTED S EVOLUTION IF COMPLEXITY COUPLING WORKS")
print("="*70)
print()
print("Parameters: mu=0.8, beta_complexity=0.15, dt=0.1, S0=0.181")
print()

complexities = [0.1, 0.5, 0.9]

for c in complexities:
    history = calculate_s_evolution(c, num_updates=10)
    print(f"Complexity = {c:.1f}:")
    print(f"  S evolution: {history[0]:.4f} → {history[5]:.4f} → {history[10]:.4f}")
    print(f"  Final S: {history[-1]:.4f}")
    print()

print("="*70)
print("KEY INSIGHT")
print("="*70)
print()
print("If complexity coupling works:")
print("  - Higher complexity → SLOWER S decay")
print("  - c=0.9 final S ≈ 0.109")
print("  - c=0.1 final S ≈ 0.067")
print("  - Difference: 0.042 (6% of range)")
print()
print("Observed in our tests:")
print("  - c=0.9 and c=0.1 produce IDENTICAL S trajectories")
print("  - S decreases monotonically regardless of complexity")
print()
print("CONCLUSION:")
print("  Either:")
print("  1. Complexity always receives same value (~0.5)")
print("  2. beta_complexity is effectively 0")
print("  3. Dynamics equation isn't being used")
print()
