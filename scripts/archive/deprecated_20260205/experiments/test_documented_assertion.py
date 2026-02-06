#!/usr/bin/env python3
"""
Test the assertion from docs/DYNAMICS_ACTIVATION_STATUS.md line 109:
'S should be higher for high complexity (entropy increases)'

This is the system's own documented test for complexity coupling.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


async def test_documented_assertion():
    """
    From DYNAMICS_ACTIVATION_STATUS.md:

    # Test complexity effect
    result1 = process_agent_update(agent_id, complexity=0.1)  # Low complexity
    result2 = process_agent_update(agent_id, complexity=0.9)  # High complexity

    # S should be higher for high complexity (entropy increases)
    assert result2['metrics']['S'] > result1['metrics']['S']
    """

    print("="*70)
    print("TESTING DOCUMENTED ASSERTION")
    print("="*70)
    print("\nFrom docs/DYNAMICS_ACTIVATION_STATUS.md line 109:")
    print("  'S should be higher for high complexity (entropy increases)'")
    print()

    async with GovernanceMCPClient() as client:
        agent_id = "complexity_test"

        print("Test 1: Low complexity (0.1)")
        result1 = await client.process_agent_update(
            agent_id=agent_id,
            response_text="Low complexity task",
            complexity=0.1
        )
        S1 = result1['metrics']['S']
        print(f"  S = {S1:.4f}")

        print("\nTest 2: High complexity (0.9)")
        result2 = await client.process_agent_update(
            agent_id=agent_id,
            response_text="High complexity task",
            complexity=0.9
        )
        S2 = result2['metrics']['S']
        print(f"  S = {S2:.4f}")

        print("\n" + "="*70)
        print("ASSERTION CHECK")
        print("="*70)

        print(f"\nExpected: S2 ({S2:.4f}) > S1 ({S1:.4f})")
        print(f"  (High complexity should have higher entropy)")

        if S2 > S1:
            print("\n✅ ASSERTION PASSED")
            print("   Complexity coupling appears to be working")
        else:
            print(f"\n❌ ASSERTION FAILED")
            print(f"   S actually went: {S1:.4f} → {S2:.4f}")
            print(f"   Change: {S2 - S1:+.4f} (expected positive)")
            print()
            print("   CONCLUSION: Documentation says complexity coupling is ENABLED,")
            print("               but experimental reality shows it has ZERO effect.")
            print()
            print("   This is ASPIRATIONAL DOCUMENTATION - describes design intent,")
            print("   not actual implementation.")

        print()


if __name__ == "__main__":
    asyncio.run(test_documented_assertion())
