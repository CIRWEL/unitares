#!/usr/bin/env python3
"""
Demo: AI-Powered Governance Features

Shows how ngrok.ai enhances the governance MCP with:
1. Semantic dialectic synthesis
2. Knowledge graph semantic search
3. Agent behavior analysis

Usage:
    # Set up environment
    export NGROK_AI_ENDPOINT="https://unitares-ai.ngrok.ai/v1"
    export NGROK_API_KEY="your_ngrok_api_key"

    # Or use direct OpenAI
    export OPENAI_API_KEY="your_openai_key"

    # Run demo
    python examples/demo_ai_features.py
"""

import sys
import os
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai_synthesis import create_dialectic_ai
from src.ai_knowledge_search import create_semantic_search
from src.ai_behavior_analysis import create_behavior_analyzer
from src.knowledge_graph import DiscoveryNode


def demo_dialectic_synthesis():
    """Demo 1: AI-powered dialectic synthesis"""
    print("\n" + "="*60)
    print("DEMO 1: Semantic Dialectic Synthesis")
    print("="*60)

    ai = create_dialectic_ai()
    if not ai:
        print("❌ DialecticAI not available (missing API key)")
        return

    # Simulate thesis and antithesis
    thesis = {
        "root_cause": "Agent was processing too many concurrent requests",
        "proposed_conditions": ["Limit concurrent requests to 5"],
        "reasoning": "I was overwhelmed by task switching overhead"
    }

    antithesis = {
        "observed_metrics": {"risk_score": 0.68, "concurrent_tasks": 15},
        "concerns": ["5 is too restrictive", "May cause request queuing"],
        "reasoning": "Dropping to 5 immediately could hurt throughput"
    }

    print("\n📝 Thesis (Agent's proposal):")
    print(f"   Root cause: {thesis['root_cause']}")
    print(f"   Conditions: {thesis['proposed_conditions']}")

    print("\n📝 Antithesis (Reviewer's concerns):")
    print(f"   Concerns: {antithesis['concerns']}")

    print("\n🤖 AI is synthesizing...\n")

    result = ai.suggest_synthesis(thesis, antithesis)

    if "error" in result:
        print(f"❌ Synthesis failed: {result['error']}")
        return

    print("✅ AI-Generated Synthesis:")
    print(f"   Conditions: {result.get('suggested_conditions', [])}")
    print(f"   Root Cause: {result.get('merged_root_cause', '')}")
    print(f"   Confidence: {result.get('confidence', 0):.2%}")
    print(f"   Model Used: {result.get('model_used', 'unknown')}")

    if result.get('safety_concerns'):
        print(f"   ⚠️  Safety Concerns: {result['safety_concerns']}")


def demo_semantic_search():
    """Demo 2: Semantic knowledge search"""
    print("\n" + "="*60)
    print("DEMO 2: Semantic Knowledge Search")
    print("="*60)

    search = create_semantic_search()
    if not search:
        print("❌ SemanticSearch not available")
        return

    # Create sample discoveries
    discoveries = [
        DiscoveryNode(
            id="d1",
            agent_id="agent_a",
            type="bug_found",
            summary="API rate limit exceeded during batch processing",
            details="OpenAI API returned 429 errors when processing 100 requests",
            tags=["api", "rate-limit"]
        ),
        DiscoveryNode(
            id="d2",
            agent_id="agent_b",
            type="insight",
            summary="Authentication token expired causing login failures",
            details="JWT tokens have 1 hour expiry, causing user sessions to drop",
            tags=["auth", "tokens"]
        ),
        DiscoveryNode(
            id="d3",
            agent_id="agent_c",
            type="bug_found",
            summary="Database connection pool exhausted under high load",
            details="Connection pool size of 10 insufficient for 50 concurrent users",
            tags=["database", "performance"]
        ),
        DiscoveryNode(
            id="d4",
            agent_id="agent_a",
            type="improvement",
            summary="Implemented request throttling to prevent API overload",
            details="Added exponential backoff with max 5 retries",
            tags=["api", "improvement"]
        )
    ]

    print(f"\n📚 Indexed {len(discoveries)} discoveries")

    # Index them
    for d in discoveries:
        search.index_discovery(d)

    # Natural language query
    query = "What issues did we have with APIs?"
    print(f"\n🔍 Query: '{query}'")
    print("\n📊 Results:\n")

    results = search.search(query, discoveries, top_k=3, min_score=0.3)

    for i, result in enumerate(results, 1):
        print(f"{i}. Score: {result.relevance_score:.2f}")
        print(f"   {result.discovery.summary}")
        print(f"   Tags: {result.discovery.tags}")
        print()

    print("💡 Notice: Found both rate-limit AND throttling solution")
    print("   Even though query was just 'API issues'")


def demo_behavior_analysis():
    """Demo 3: Agent behavior analysis"""
    print("\n" + "="*60)
    print("DEMO 3: Agent Behavior Analysis")
    print("="*60)

    analyzer = create_behavior_analyzer()
    if not analyzer:
        print("❌ BehaviorAnalyzer not available")
        return

    # Simulate agent history
    agent_history = [
        {"timestamp": "2025-12-20T10:00:00", "risk_score": 0.25, "coherence": 0.75},
        {"timestamp": "2025-12-20T11:00:00", "risk_score": 0.30, "coherence": 0.72},
        {"timestamp": "2025-12-20T12:00:00", "risk_score": 0.42, "coherence": 0.65},
        {"timestamp": "2025-12-20T13:00:00", "risk_score": 0.58, "coherence": 0.55},
        {"timestamp": "2025-12-20T14:00:00", "risk_score": 0.65, "coherence": 0.48},
        {"timestamp": "2025-12-20T14:30:00", "risk_score": 0.72, "coherence": 0.42},
    ]

    print(f"\n📈 Analyzing agent with {len(agent_history)} updates")
    print("   Risk score trend: 0.25 → 0.72 (increasing)")
    print("   Coherence trend: 0.75 → 0.42 (degrading)")

    print("\n🤖 AI is analyzing patterns...\n")

    patterns = analyzer.analyze_agent_trajectory(
        agent_id="demo_agent",
        history=agent_history
    )

    if patterns:
        print("✅ Detected Patterns:\n")
        for i, pattern in enumerate(patterns, 1):
            print(f"{i}. [{pattern.severity.upper()}] {pattern.pattern_type}")
            print(f"   {pattern.description}")
            print(f"   Evidence: {pattern.evidence}")
            print(f"   Recommendation: {pattern.recommendation}")
            print(f"   Confidence: {pattern.confidence:.2%}\n")
    else:
        print("⚠️  No patterns detected (or analysis failed)")

    # Circuit breaker prediction
    print("\n🔮 Predicting circuit breaker trigger...")

    current_metrics = agent_history[-1]
    prediction = analyzer.predict_circuit_breaker(
        current_metrics=current_metrics,
        recent_trend=agent_history
    )

    if "error" in prediction:
        print(f"❌ Prediction failed: {prediction['error']}")
    else:
        will_trigger = prediction.get("will_trigger", False)
        print(f"\n{'🚨' if will_trigger else '✅'} Will trigger: {will_trigger}")
        if will_trigger:
            print(f"   Time estimate: {prediction.get('estimated_time', 'unknown')}")
        print(f"   Confidence: {prediction.get('confidence', 0):.2%}")

        if prediction.get('preventive_actions'):
            print("\n💡 Preventive Actions:")
            for action in prediction['preventive_actions']:
                print(f"   - {action}")


def main():
    """Run all demos"""
    print("\n" + "🤖 "*20)
    print("AI-Powered Governance Features Demo")
    print("🤖 "*20)

    # Check if API key is set
    ngrok_key = os.getenv("NGROK_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if ngrok_key:
        endpoint = os.getenv("NGROK_AI_ENDPOINT", "not set")
        print(f"\n✅ Using ngrok.ai gateway: {endpoint}")
    elif openai_key:
        print("\n✅ Using direct OpenAI connection")
        print("   (For full features, set up ngrok.ai)")
    else:
        print("\n❌ No API key found!")
        print("\nSet one of:")
        print("   export NGROK_API_KEY='your_key'")
        print("   export OPENAI_API_KEY='your_key'")
        return

    try:
        demo_dialectic_synthesis()
        demo_semantic_search()
        demo_behavior_analysis()

        print("\n" + "="*60)
        print("✅ Demo Complete!")
        print("="*60)
        print("\nNext steps:")
        print("1. Set up ngrok.ai at https://dashboard.ngrok.com/ai-gateway")
        print("2. Configure provider failover (OpenAI → Claude → DeepSeek)")
        print("3. Integrate features into your MCP tools")
        print("4. Monitor costs and performance in ngrok dashboard")

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
