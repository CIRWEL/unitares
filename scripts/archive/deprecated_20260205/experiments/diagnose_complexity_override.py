#!/usr/bin/env python3
"""
Diagnose if complexity is being overridden by derive_complexity().

Strategy: Add logging to governance_core/dynamics.py to see what complexity
value actually reaches compute_dynamics.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


async def test_complexity_values():
    print("="*70)
    print("COMPLEXITY OVERRIDE DIAGNOSIS")
    print("="*70)
    print("\nHypothesis: derive_complexity() returns ~0.5 regardless of input")
    print("Test: Vary complexity dramatically and check if different values")
    print("      reach the dynamics equations")
    print()

    async with GovernanceMCPClient() as client:
        agent_id = "complexity_diagnostic"

        test_cases = [
            ("Simple math: 2+2=4", 0.1),
            ("Complex algorithm with recursion and optimization", 0.9),
            ("Just a sentence", 0.2),
            ("Code:\n```python\ndef complex():\n    pass\n```", 0.8),
        ]

        print("Running 4 updates with varying complexity and text...\n")

        for text, complexity in test_cases:
            result = await client.process_agent_update(
                agent_id=agent_id,
                response_text=text,
                complexity=complexity
            )

            metrics = result['metrics']
            calibration = result.get('calibration_feedback', {}).get('complexity', {})

            reported = calibration.get('reported', complexity)
            derived = calibration.get('derived', 'N/A')

            print(f"Text: {text[:50]:50s}")
            print(f"  Reported: {reported:.2f}")
            print(f"  Derived:  {derived if derived == 'N/A' else f'{derived:.2f}'}")
            print(f"  S value:  {metrics['S']:.4f}")
            print()

        print("="*70)
        print("DIAGNOSIS")
        print("="*70)
        print("\nIf all 'Derived' values are similar (~0.5), then derive_complexity()")
        print("is overriding reported values and returning constant!")
        print()
        print("This would explain why our tests showed zero complexity effect:")
        print("  - You report complexity=0.9")
        print("  - derive_complexity() analyzes text, returns 0.5")
        print("  - Dynamics receive 0.5 (not 0.9)")
        print("  - Metrics evolve based on constant 0.5")
        print()


if __name__ == "__main__":
    asyncio.run(test_complexity_values())
