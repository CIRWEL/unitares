#!/usr/bin/env python3
"""
Proper complexity test: Different agents with CONSTANT complexity

Compare:
- Agent A: c=0.1 for all 10 updates
- Agent B: c=0.5 for all 10 updates
- Agent C: c=0.9 for all 10 updates

If complexity works, Agent C's S should decrease slowest.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


async def test_constant_complexity():
    print("="*70)
    print("PROPER COMPLEXITY TEST: Different Agents, Constant Complexity")
    print("="*70)
    print()

    async with GovernanceMCPClient() as client:
        agents = [
            ("agent_low_complexity", 0.1),
            ("agent_mid_complexity", 0.5),
            ("agent_high_complexity", 0.9),
        ]

        results = {}

        for agent_id, complexity in agents:
            print(f"\n{agent_id} (complexity={complexity}):")
            s_history = []

            for i in range(10):
                result = await client.process_agent_update(
                    agent_id=agent_id,
                    response_text=f"Update {i+1}",
                    complexity=complexity
                )
                s = result['metrics']['S']
                s_history.append(s)

                if i == 0 or i == 4 or i == 9:
                    print(f"  Update {i+1:2d}: S={s:.4f}")

                await asyncio.sleep(0.3)

            results[agent_id] = {
                'complexity': complexity,
                's_start': s_history[0],
                's_final': s_history[-1],
                's_change': s_history[-1] - s_history[0]
            }

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    print()

    for agent_id, data in results.items():
        print(f"{agent_id}:")
        print(f"  Complexity: {data['complexity']:.1f}")
        print(f"  S: {data['s_start']:.4f} → {data['s_final']:.4f}")
        print(f"  Change: {data['s_change']:+.4f}")
        print()

    # Compare
    low_final = results['agent_low_complexity']['s_final']
    mid_final = results['agent_mid_complexity']['s_final']
    high_final = results['agent_high_complexity']['s_final']

    print("="*70)
    print("ANALYSIS")
    print("="*70)
    print()
    print(f"Final S values:")
    print(f"  c=0.1: {low_final:.4f}")
    print(f"  c=0.5: {mid_final:.4f}")
    print(f"  c=0.9: {high_final:.4f}")
    print()

    if high_final > mid_final > low_final:
        diff = high_final - low_final
        print(f"✅ COMPLEXITY WORKS!")
        print(f"   Higher complexity → slower S decay")
        print(f"   Difference: {diff:.4f} ({diff/low_final*100:.1f}% relative)")
        print()
        print("   The effect was masked in sequential tests because decay dominates.")
        print("   But when comparing different agents with constant complexity,")
        print("   the effect accumulates and becomes visible!")
    else:
        print(f"❌ COMPLEXITY HAS NO EFFECT")
        print(f"   S values don't follow expected pattern")


if __name__ == "__main__":
    asyncio.run(test_constant_complexity())
