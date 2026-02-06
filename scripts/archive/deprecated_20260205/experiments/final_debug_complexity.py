#!/usr/bin/env python3
"""
Final debug: Add temporary logging to compute_dynamics to see what complexity
values it actually receives.

Strategy: Monkey-patch compute_dynamics to log inputs.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Monkey-patch compute_dynamics with logging
from governance_core import dynamics
original_compute_dynamics = dynamics.compute_dynamics

def logged_compute_dynamics(state, delta_eta, theta, params, dt=0.1, noise_S=0.0, complexity=0.5):
    """Wrapper that logs complexity value"""
    print(f"  [DYNAMICS] complexity={complexity:.2f}, S_before={state.S:.4f}", end="")
    result = original_compute_dynamics(state, delta_eta, theta, params, dt, noise_S, complexity)
    print(f", S_after={result.S:.4f}, change={result.S - state.S:+.4f}")
    return result

dynamics.compute_dynamics = logged_compute_dynamics

# Now run test
from scripts.mcp_sse_client import GovernanceMCPClient


async def test_with_logging():
    print("="*70)
    print("FINAL DEBUG: Logging complexity values in compute_dynamics()")
    print("="*70)
    print("\nRunning 3 updates with different complexity values...")
    print("If complexity reaches dynamics, we'll see:")
    print("  - Different complexity values logged")
    print("  - Different S changes based on complexity")
    print()

    async with GovernanceMCPClient() as client:
        agent_id = "final_debug"

        for i, complexity in enumerate([0.1, 0.5, 0.9], 1):
            print(f"\nUpdate {i}: complexity={complexity:.1f}")
            result = await client.process_agent_update(
                agent_id=agent_id,
                response_text=f"Update {i}",
                complexity=complexity
            )

    print("\n" + "="*70)
    print("ANALYSIS")
    print("="*70)
    print("\nIf all logged complexity values are 0.50:")
    print("  → Complexity parameter is being overridden somewhere")
    print()
    print("If logged complexity values vary (0.10, 0.50, 0.90):")
    print("  → Complexity is reaching dynamics correctly")
    print("  → But beta_complexity (0.15) may be too weak vs mu (0.8)")
    print()


if __name__ == "__main__":
    asyncio.run(test_with_logging())
