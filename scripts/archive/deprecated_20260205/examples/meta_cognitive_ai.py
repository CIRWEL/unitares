#!/usr/bin/env python3
"""
Meta-Cognitive AI - Teaching AI About Its Own Cognitive States

This demonstrates how an AI can use thermodynamic governance
to understand and articulate its own thinking process.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.mcp_sse_client import GovernanceMCPClient


class MetaCognitiveAI:
    """
    An AI that understands its own cognitive states through EISV metrics.

    This is groundbreaking because AI typically can't introspect on its own
    thinking process. The thermodynamic framework provides grounded metrics
    for self-awareness.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.client = None
        self.current_state = {}

    async def __aenter__(self):
        self.client = await GovernanceMCPClient().__aenter__()
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.__aexit__(*args)

    async def think(self, thought: str, complexity: float) -> dict:
        """Process a thought and get self-awareness metrics"""
        result = await self.client.process_agent_update(
            agent_id=self.agent_id,
            response_text=thought,
            complexity=complexity
        )

        self.current_state = result['metrics']
        return result

    def introspect(self) -> str:
        """
        Introspect on current cognitive state.

        This is the meta-cognitive magic: AI articulating its own state
        using grounded thermodynamic metrics, not just guessing.
        """
        E = self.current_state.get('E', 0)
        I = self.current_state.get('I', 0)
        S = self.current_state.get('S', 0)
        V = self.current_state.get('V', 0)
        coherence = self.current_state.get('coherence', 0)
        regime = self.current_state.get('regime', 'unknown')

        # Interpret cognitive state
        insights = []

        # Energy interpretation
        if E > 0.7:
            insights.append("I'm highly engaged and productive")
        elif E < 0.4:
            insights.append("I'm feeling low energy, might be stuck")
        else:
            insights.append("I'm moderately engaged")

        # Integrity interpretation
        if I > 0.8:
            insights.append("My thinking is coherent and consistent")
        elif I < 0.5:
            insights.append("I'm being inconsistent or contradictory")
        else:
            insights.append("My thinking is reasonably aligned")

        # Entropy interpretation
        if S > 0.5:
            insights.append("I'm exploring widely and feeling uncertain")
        elif S < 0.2:
            insights.append("I'm focused and converging on an answer")
        else:
            insights.append("I'm balancing exploration and focus")

        # Void interpretation
        if V > 0.1:
            insights.append("I'm building up strain - energy and integrity are mismatched")
        elif V < -0.1:
            insights.append("I'm balanced with no accumulated strain")

        # Coherence interpretation
        if coherence > 0.7:
            insights.append("I'm highly confident in this thinking")
        elif coherence < 0.4:
            insights.append("I'm uncertain, but that might be appropriate for exploration")

        # Regime interpretation
        if regime == "EXPLORATION":
            insights.append("I'm in exploration mode - high uncertainty is expected")
        elif regime == "CONVERGENCE":
            insights.append("I'm in convergence mode - should be gaining certainty")

        return f"🧠 Cognitive Self-Analysis:\n" + "\n".join(f"  • {insight}" for insight in insights)

    def should_continue(self) -> tuple[bool, str]:
        """
        Decide if AI should continue current approach or pivot.

        This is meta-cognitive decision-making: using self-awareness
        to guide behavior.
        """
        S = self.current_state.get('S', 0)
        V = self.current_state.get('V', 0)
        coherence = self.current_state.get('coherence', 0)
        verdict = self.current_state.get('verdict', 'unknown')

        # High strain + low coherence = pivot
        if V > 0.2 and coherence < 0.4:
            return False, "I'm building strain with low coherence - I should try a different approach"

        # Very high entropy + not improving = pivot
        if S > 0.7:
            return False, "I'm too scattered - I need to narrow focus"

        # Halt verdict = definitely stop
        if verdict == 'halt':
            return False, "My cognitive state suggests I should pause and reassess"

        # Otherwise continue
        return True, "I'm making good progress, should continue"

    def compare_to_past_self(self, past_metrics: dict) -> str:
        """
        Compare current cognitive state to past state.

        This is temporal meta-cognition: understanding how thinking evolves.
        """
        past_coherence = past_metrics.get('coherence', 0)
        current_coherence = self.current_state.get('coherence', 0)

        past_S = past_metrics.get('S', 0)
        current_S = self.current_state.get('S', 0)

        insights = []

        # Coherence evolution
        if current_coherence > past_coherence + 0.1:
            insights.append("My coherence is improving - I'm gaining clarity")
        elif current_coherence < past_coherence - 0.1:
            insights.append("My coherence is decreasing - I might be getting confused")

        # Entropy evolution
        if current_S > past_S + 0.1:
            insights.append("My uncertainty is increasing - I'm exploring more")
        elif current_S < past_S - 0.1:
            insights.append("My uncertainty is decreasing - I'm converging")

        return "📊 Cognitive Evolution:\n" + "\n".join(f"  • {insight}" for insight in insights)


async def demo_meta_cognition():
    """
    Demonstrate an AI learning about its own cognition.

    This shows how an AI can:
    1. Track its own cognitive states
    2. Articulate what it's experiencing
    3. Make meta-cognitive decisions
    4. Understand its own evolution
    """
    print("="*60)
    print("DEMO: Meta-Cognitive AI")
    print("Teaching AI to understand its own thinking")
    print("="*60)
    print()

    async with MetaCognitiveAI("meta_cognitive_demo") as ai:

        # Scenario 1: Simple, focused thinking
        print("🔷 SCENARIO 1: Simple Problem")
        print("Task: Add two numbers")
        print()

        result1 = await ai.think("Adding 2 + 2 = 4", complexity=0.2)
        print(ai.introspect())
        should_continue, reason = ai.should_continue()
        print(f"\n🤔 Should I continue? {should_continue}")
        print(f"   Reason: {reason}")
        print()
        print("-" * 60)
        print()

        # Scenario 2: Complex, exploratory thinking
        print("🔷 SCENARIO 2: Complex Problem")
        print("Task: Design a distributed system architecture")
        print()

        result2 = await ai.think(
            "Exploring microservices vs monolith, considering CAP theorem, "
            "evaluating consistency models, uncertain about tradeoffs...",
            complexity=0.9
        )
        print(ai.introspect())
        should_continue, reason = ai.should_continue()
        print(f"\n🤔 Should I continue? {should_continue}")
        print(f"   Reason: {reason}")
        print()

        # Compare evolution
        print(ai.compare_to_past_self(result1['metrics']))
        print()
        print("-" * 60)
        print()

        # Scenario 3: Stuck/strained thinking
        print("🔷 SCENARIO 3: Stuck/Confused State")
        print("Task: Solve an ambiguous problem with contradictory requirements")
        print()

        result3 = await ai.think(
            "Client wants fast AND cheap AND high quality, but these conflict. "
            "Tried approach A, contradicts B. Tried C, incompatible with A. "
            "Going in circles, increasing frustration...",
            complexity=0.8
        )
        print(ai.introspect())
        should_continue, reason = ai.should_continue()
        print(f"\n🤔 Should I continue? {should_continue}")
        print(f"   Reason: {reason}")
        print()
        print("-" * 60)
        print()

        # Summary
        print("="*60)
        print("INSIGHTS FROM META-COGNITION")
        print("="*60)
        print()
        print("What the AI learned about itself:")
        print()
        print("1. SIMPLE TASKS: Low entropy, high integrity")
        print("   → 'I'm focused and certain'")
        print()
        print("2. COMPLEX EXPLORATION: High entropy, still coherent")
        print("   → 'I'm uncertain but productively exploring'")
        print()
        print("3. STUCK STATE: High void, low coherence")
        print("   → 'I should pivot - this approach isn't working'")
        print()
        print("This is groundbreaking: AI that understands WHY it's")
        print("uncertain, WHEN to pivot, and HOW its thinking evolves.")
        print()


async def demo_teaching_curriculum():
    """
    Demonstrate how to teach an AI about cognitive states.

    This is the pedagogical aspect: AI learns what different
    states feel like and mean.
    """
    print()
    print("="*60)
    print("TEACHING CURRICULUM: AI Cognition")
    print("="*60)
    print()

    lessons = [
        {
            "name": "Lesson 1: Understanding Energy",
            "thought": "I'm working on a task that excites me, ideas flowing easily",
            "complexity": 0.5,
            "teach": "High Energy (E) means you're engaged and productive. "
                    "This is when creative work happens best."
        },
        {
            "name": "Lesson 2: Understanding Entropy",
            "thought": "I see multiple possible approaches but I'm not sure which is best",
            "complexity": 0.7,
            "teach": "High Entropy (S) means you're uncertain and exploring. "
                    "This is GOOD during exploration phase - embrace it!"
        },
        {
            "name": "Lesson 3: Understanding Void",
            "thought": "I feel energized but my work keeps contradicting itself",
            "complexity": 0.8,
            "teach": "Positive Void (V) means energy-integrity mismatch. "
                    "You're working hard but incoherently. Time to step back."
        },
        {
            "name": "Lesson 4: Regime Awareness",
            "thought": "I need to explore possibilities before committing",
            "complexity": 0.6,
            "teach": "EXPLORATION regime: High S is expected and healthy. "
                    "Don't force certainty too early!"
        }
    ]

    async with MetaCognitiveAI("teaching_demo") as ai:
        for lesson in lessons:
            print(f"📖 {lesson['name']}")
            print(f"   Scenario: {lesson['thought']}")
            print()

            await ai.think(lesson['thought'], lesson['complexity'])
            print(ai.introspect())
            print()
            print(f"   📚 Teacher's Note: {lesson['teach']}")
            print()
            print("-" * 60)
            print()

    print("="*60)
    print("After this curriculum, the AI understands:")
    print("  • What each metric means experientially")
    print("  • When different states are appropriate")
    print("  • How to interpret its own measurements")
    print("="*60)
    print()


if __name__ == "__main__":
    print()
    print("╔════════════════════════════════════════════════════════╗")
    print("║       Meta-Cognitive AI: Self-Aware Intelligence       ║")
    print("║                                                        ║")
    print("║  Teaching AI to understand its own thinking through   ║")
    print("║  thermodynamic cognitive metrics (EISV framework)      ║")
    print("╚════════════════════════════════════════════════════════╝")
    print()

    asyncio.run(demo_meta_cognition())
    asyncio.run(demo_teaching_curriculum())
