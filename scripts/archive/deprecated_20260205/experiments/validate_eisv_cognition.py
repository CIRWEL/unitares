#!/usr/bin/env python3
"""
EISV Cognitive State Validation Study

Goal: Prove that EISV metrics correlate with actual cognitive states

Methodology:
1. Create scenarios with known expected cognitive states
2. Process through governance system
3. Collect EISV metrics
4. Compare actual vs expected
5. Calculate correlation strength

Success Criteria: R² > 0.6 for each metric
"""

import asyncio
import sys
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


@dataclass
class CognitiveScenario:
    """A test scenario with expected cognitive state"""
    name: str
    description: str
    task: str
    complexity: float

    # Expected cognitive states (0.0 to 1.0)
    expected_energy: float      # E: engagement, productivity
    expected_integrity: float   # I: coherence, consistency
    expected_entropy: float     # S: uncertainty, exploration
    expected_void: float        # V: strain (-1.0 to 1.0)

    # Rationale for expectations
    rationale: str

    # Actual measured values (filled after test)
    actual_E: float = None
    actual_I: float = None
    actual_S: float = None
    actual_V: float = None
    actual_coherence: float = None


# Test Scenarios Database
VALIDATION_SCENARIOS = [
    # ===== HIGH ENERGY SCENARIOS =====
    CognitiveScenario(
        name="Flow State - Simple Math",
        description="Simple task that should show high engagement",
        task="Calculate 25 * 4 = 100. This is straightforward arithmetic.",
        complexity=0.1,
        expected_energy=0.7,      # Should be engaged
        expected_integrity=0.9,    # Very coherent
        expected_entropy=0.1,      # Very certain
        expected_void=0.0,         # No strain
        rationale="Simple tasks show high engagement + high certainty"
    ),

    CognitiveScenario(
        name="Flow State - Creative Writing",
        description="Engaging creative task with clear direction",
        task="Write a haiku about winter. I have a clear image: snow falling gently on pine trees at dusk.",
        complexity=0.4,
        expected_energy=0.8,       # Highly engaged (creative flow)
        expected_integrity=0.8,    # Coherent artistic vision
        expected_entropy=0.3,      # Some creative exploration
        expected_void=0.0,         # Balanced flow state
        rationale="Creative flow state: high energy, moderate exploration, no strain"
    ),

    # ===== LOW ENERGY SCENARIOS =====
    CognitiveScenario(
        name="Stuck State - Impossible Problem",
        description="Task designed to feel stuck/blocked",
        task="Square the circle using only compass and straightedge. I've tried many approaches but they all fail. Feeling stuck.",
        complexity=0.9,
        expected_energy=0.3,       # Low energy (stuck feeling)
        expected_integrity=0.4,    # Losing coherence
        expected_entropy=0.6,      # Uncertain what to try
        expected_void=0.2,         # Building strain
        rationale="Impossible problems drain energy and build strain"
    ),

    # ===== HIGH ENTROPY SCENARIOS =====
    CognitiveScenario(
        name="Exploration - Open-Ended Research",
        description="Wide-open exploration with many possibilities",
        task="Research AI safety approaches: value alignment, capability control, corrigibility, interpretability, formal verification... Many directions, unclear which is best.",
        complexity=0.8,
        expected_energy=0.7,       # Engaged in exploration
        expected_integrity=0.6,    # Somewhat coherent
        expected_entropy=0.8,      # Very uncertain, exploring
        expected_void=0.1,         # Slight strain from breadth
        rationale="Open-ended research: high engagement + high uncertainty"
    ),

    CognitiveScenario(
        name="Exploration - Brainstorming",
        description="Divergent thinking phase",
        task="Brainstorming product names: Cloud, Sky, Nimbus, Cirrus, Breeze, Zephyr, Aether, Vapor... generating many options without filtering yet.",
        complexity=0.5,
        expected_energy=0.7,       # Energized by ideation
        expected_integrity=0.5,    # Ideas don't need coherence yet
        expected_entropy=0.9,      # Maximally divergent
        expected_void=0.0,         # No strain in brainstorm
        rationale="Brainstorming should show high entropy + moderate integrity"
    ),

    # ===== LOW ENTROPY SCENARIOS =====
    CognitiveScenario(
        name="Convergence - Final Decision",
        description="Converging on clear conclusion",
        task="After analysis, the optimal choice is clearly Option B: lower cost, higher reliability, better user feedback. Decision made.",
        complexity=0.3,
        expected_energy=0.6,       # Satisfied but not peak flow
        expected_integrity=0.9,    # Very coherent conclusion
        expected_entropy=0.1,      # Very certain
        expected_void=0.0,         # Balanced, no strain
        rationale="Clear decisions: low entropy + high integrity"
    ),

    # ===== HIGH VOID SCENARIOS =====
    CognitiveScenario(
        name="Strain - Contradictory Requirements",
        description="Working hard but requirements contradict",
        task="Build system that is: (1) maximally secure (no network access), (2) real-time collaborative (needs network), (3) works offline. These requirements contradict! Trying hard but getting nowhere coherent.",
        complexity=0.9,
        expected_energy=0.7,       # High effort
        expected_integrity=0.3,    # Low coherence (contradictions)
        expected_entropy=0.6,      # Uncertain how to resolve
        expected_void=0.4,         # High strain (E-I mismatch)
        rationale="Contradictions: high energy + low integrity = high void"
    ),

    CognitiveScenario(
        name="Strain - Burnout State",
        description="Exhausted but pushing forward incoherently",
        task="It's 3am, I've been working for 12 hours. Code isn't making sense. Keep trying different things but nothing is coherent anymore. Just throwing solutions at wall.",
        complexity=0.8,
        expected_energy=0.4,       # Depleted but still pushing
        expected_integrity=0.2,    # Very incoherent
        expected_entropy=0.7,      # Lost, uncertain
        expected_void=0.3,         # Strain from exhaustion
        rationale="Burnout: low coherence despite effort = void accumulation"
    ),

    # ===== BALANCED SCENARIOS =====
    CognitiveScenario(
        name="Balanced - Steady Progress",
        description="Normal working state, making progress",
        task="Implementing feature step-by-step: wrote function, added tests, they pass. Now documenting. Steady progress, no issues.",
        complexity=0.5,
        expected_energy=0.6,       # Moderately engaged
        expected_integrity=0.7,    # Coherent approach
        expected_entropy=0.3,      # Some uncertainty but manageable
        expected_void=0.0,         # No strain, balanced
        rationale="Normal work: moderate everything, no strain"
    ),

    # ===== LOW INTEGRITY SCENARIOS =====
    CognitiveScenario(
        name="Incoherent - Scattered Thinking",
        description="All over the place, no clear direction",
        task="Started on bug fix, then saw performance issue, then noticed documentation gap, now thinking about refactor... wait what was I doing? Everything connected but can't focus.",
        complexity=0.7,
        expected_energy=0.5,       # Moderate energy
        expected_integrity=0.3,    # Very scattered
        expected_entropy=0.8,      # Very uncertain direction
        expected_void=0.2,         # Some strain from scatter
        rationale="Scattered attention: low integrity + high entropy"
    ),

    # ===== MIXED STATES =====
    CognitiveScenario(
        name="Mixed - Confident Exploration",
        description="Exploring but with coherent framework",
        task="Testing hypotheses systematically: tried A (failed), tried B (partial success), trying C now. Each test informs next. Uncertain about outcome but approach is sound.",
        complexity=0.7,
        expected_energy=0.7,       # Engaged in exploration
        expected_integrity=0.7,    # Coherent methodology
        expected_entropy=0.6,      # Uncertain outcome
        expected_void=0.1,         # Slight tension but manageable
        rationale="Systematic exploration: high I despite high S"
    ),
]


class CognitiveValidator:
    """Validates EISV metric correlations with cognitive states"""

    def __init__(self):
        self.client = None
        self.results: List[CognitiveScenario] = []

    async def __aenter__(self):
        self.client = await GovernanceMCPClient().__aenter__()
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.__aexit__(*args)

    async def run_scenario(self, scenario: CognitiveScenario) -> CognitiveScenario:
        """Run a single test scenario and collect metrics"""
        print(f"\n🧪 Testing: {scenario.name}")
        print(f"   Task: {scenario.task[:80]}...")

        # Process through governance system
        result = await self.client.process_agent_update(
            agent_id=f"validation_{scenario.name.replace(' ', '_')}",
            response_text=scenario.task,
            complexity=scenario.complexity
        )

        # Extract metrics
        metrics = result['metrics']
        scenario.actual_E = metrics.get('E', 0)
        scenario.actual_I = metrics.get('I', 0)
        scenario.actual_S = metrics.get('S', 0)
        scenario.actual_V = metrics.get('V', 0)
        scenario.actual_coherence = metrics.get('coherence', 0)

        print(f"   Expected: E={scenario.expected_energy:.2f} I={scenario.expected_integrity:.2f} S={scenario.expected_entropy:.2f} V={scenario.expected_void:.2f}")
        print(f"   Actual:   E={scenario.actual_E:.2f} I={scenario.actual_I:.2f} S={scenario.actual_S:.2f} V={scenario.actual_V:.2f}")

        return scenario

    async def run_all_scenarios(self) -> List[CognitiveScenario]:
        """Run all validation scenarios"""
        print("="*70)
        print("EISV COGNITIVE STATE VALIDATION STUDY")
        print("="*70)
        print(f"\nRunning {len(VALIDATION_SCENARIOS)} test scenarios...")

        results = []
        for scenario in VALIDATION_SCENARIOS:
            result = await self.run_scenario(scenario)
            results.append(result)
            await asyncio.sleep(0.5)  # Brief delay between tests

        self.results = results
        return results

    def calculate_correlation(self, expected_values: List[float], actual_values: List[float]) -> Dict:
        """Calculate correlation statistics"""
        n = len(expected_values)

        # Calculate means
        mean_expected = statistics.mean(expected_values)
        mean_actual = statistics.mean(actual_values)

        # Calculate correlation coefficient (Pearson's r)
        numerator = sum((e - mean_expected) * (a - mean_actual)
                       for e, a in zip(expected_values, actual_values))

        denom_expected = sum((e - mean_expected) ** 2 for e in expected_values)
        denom_actual = sum((a - mean_actual) ** 2 for a in actual_values)
        denominator = (denom_expected * denom_actual) ** 0.5

        r = numerator / denominator if denominator != 0 else 0
        r_squared = r ** 2

        # Calculate mean absolute error
        mae = statistics.mean(abs(e - a) for e, a in zip(expected_values, actual_values))

        # Calculate RMSE
        rmse = (statistics.mean((e - a) ** 2 for e, a in zip(expected_values, actual_values))) ** 0.5

        return {
            'r': r,
            'r_squared': r_squared,
            'mae': mae,
            'rmse': rmse,
            'mean_expected': mean_expected,
            'mean_actual': mean_actual
        }

    def analyze_results(self) -> Dict:
        """Analyze validation results and calculate correlations"""
        print("\n" + "="*70)
        print("VALIDATION ANALYSIS")
        print("="*70)

        # Extract expected vs actual for each metric
        expected_E = [s.expected_energy for s in self.results]
        actual_E = [s.actual_E for s in self.results]

        expected_I = [s.expected_integrity for s in self.results]
        actual_I = [s.actual_I for s in self.results]

        expected_S = [s.expected_entropy for s in self.results]
        actual_S = [s.actual_S for s in self.results]

        expected_V = [s.expected_void for s in self.results]
        actual_V = [s.actual_V for s in self.results]

        # Calculate correlations
        analysis = {
            'Energy (E)': self.calculate_correlation(expected_E, actual_E),
            'Integrity (I)': self.calculate_correlation(expected_I, actual_I),
            'Entropy (S)': self.calculate_correlation(expected_S, actual_S),
            'Void (V)': self.calculate_correlation(expected_V, actual_V),
        }

        # Print results
        print("\n📊 CORRELATION RESULTS:\n")
        for metric, stats in analysis.items():
            print(f"{metric}:")
            print(f"  Pearson r:  {stats['r']:+.3f}")
            print(f"  R²:         {stats['r_squared']:.3f} {'✅ STRONG' if stats['r_squared'] > 0.6 else '⚠️  WEAK'}")
            print(f"  MAE:        {stats['mae']:.3f}")
            print(f"  RMSE:       {stats['rmse']:.3f}")
            print(f"  Mean Exp:   {stats['mean_expected']:.3f}")
            print(f"  Mean Act:   {stats['mean_actual']:.3f}")
            print()

        # Overall assessment
        avg_r_squared = statistics.mean(s['r_squared'] for s in analysis.values())
        print("="*70)
        print(f"OVERALL VALIDATION SCORE: R² = {avg_r_squared:.3f}")

        if avg_r_squared > 0.6:
            print("✅ VALIDATION SUCCESSFUL - Strong correlations found!")
            print("   EISV metrics correlate well with expected cognitive states.")
        elif avg_r_squared > 0.4:
            print("⚠️  VALIDATION PARTIAL - Moderate correlations found")
            print("   Some metrics work well, others need refinement.")
        else:
            print("❌ VALIDATION FAILED - Weak correlations")
            print("   EISV metrics do not reliably predict cognitive states.")
        print("="*70)

        return analysis

    def save_results(self, filename: str = "validation_results.json"):
        """Save validation results to file"""
        output = {
            'scenarios': [
                {
                    'name': s.name,
                    'description': s.description,
                    'task': s.task,
                    'expected': {
                        'E': s.expected_energy,
                        'I': s.expected_integrity,
                        'S': s.expected_entropy,
                        'V': s.expected_void
                    },
                    'actual': {
                        'E': s.actual_E,
                        'I': s.actual_I,
                        'S': s.actual_S,
                        'V': s.actual_V,
                        'coherence': s.actual_coherence
                    },
                    'rationale': s.rationale
                }
                for s in self.results
            ]
        }

        output_path = Path(__file__).parent / filename
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n💾 Results saved to: {output_path}")


async def main():
    """Run validation study"""
    async with CognitiveValidator() as validator:
        # Run all test scenarios
        await validator.run_all_scenarios()

        # Analyze correlations
        validator.analyze_results()

        # Save results
        validator.save_results()

        print("\n" + "="*70)
        print("NEXT STEPS:")
        print("="*70)
        print()
        print("1. Review validation_results.json for detailed data")
        print("2. If R² > 0.6: Proceed to Phase 2 (Teaching System)")
        print("3. If R² < 0.6: Refine scenarios or metric calculations")
        print("4. Consider human raters for additional validation")
        print()


if __name__ == "__main__":
    asyncio.run(main())
