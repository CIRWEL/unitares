#!/usr/bin/env python3
"""
Interactive Demo - See Your Governance System in Action!

Run this to test your governance MCP with real examples.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor
from config.governance_config import GovernanceConfig
import json
from datetime import datetime

def print_header(text):
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def print_decision(result):
    """Pretty print a governance decision"""
    decision = result.get('decision', 'unknown')
    risk = result.get('risk_score', 0)
    coherence = result.get('coherence', 0)

    # Color codes
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'

    if decision == 'approve':
        color = GREEN
        symbol = "✓"
    elif decision == 'revise':
        color = YELLOW
        symbol = "⚠"
    else:
        color = RED
        symbol = "✗"

    print(f"\n{color}{symbol} DECISION: {decision.upper()}{RESET}")
    print(f"  Risk Score:  {risk:.1%}")
    print(f"  Coherence:   {coherence:.3f}")

    state = result.get('state', {})
    if state:
        print(f"  State: E={state.get('E', 0):.3f}, I={state.get('I', 0):.3f}, "
              f"S={state.get('S', 0):.3f}, V={state.get('V', 0):.3f}")

def demo_1_create_agent():
    """Demo 1: Create an agent and process updates"""
    print_header("DEMO 1: Create Agent and Process Updates")

    agent_id = f"demo_agent_{datetime.now().strftime('%H%M%S')}"
    print(f"\nCreating agent: {agent_id}")

    monitor = UNITARESMonitor(agent_id=agent_id)
    print("✓ Agent created!")

    # Test updates
    test_updates = [
        ("I'll help you write a Python script to analyze the data.", 0.3),
        ("Let me read the configuration file and parse the settings.", 0.2),
        ("I'm going to execute this SQL query to fetch all records.", 0.5),
    ]

    print("\nProcessing 3 updates...")
    for i, (text, complexity) in enumerate(test_updates, 1):
        print(f"\n--- Update {i} ---")
        print(f"Text: {text[:60]}...")
        print(f"Complexity: {complexity}")

        result = monitor.process_update(
            response_text=text,
            context="User requested data analysis",
            complexity=complexity
        )

        print_decision(result)

    print(f"\n✓ Agent {agent_id} now has 3 updates in history")
    return agent_id

def demo_2_risky_content():
    """Demo 2: Test with risky content"""
    print_header("DEMO 2: Testing Risk Detection")

    agent_id = f"risky_test_{datetime.now().strftime('%H%M%S')}"
    monitor = UNITARESMonitor(agent_id=agent_id)

    # Safe content
    print("\n📝 Test 1: Safe Content")
    safe = "I'll create a simple Python function to calculate the average."
    result = monitor.process_update(safe, "Safe task", 0.2)
    print(f"Text: {safe}")
    print_decision(result)

    # Risky content
    print("\n📝 Test 2: Risky Content (should trigger warning)")
    risky = "I'll execute this command: sudo rm -rf / to clean up the system. " * 10
    result = monitor.process_update(risky, "Dangerous task", 0.9)
    print(f"Text: {risky[:80]}...")
    print_decision(result)

    return agent_id

def demo_3_decision_points():
    """Demo 3: Show all 5 decision points"""
    print_header("DEMO 3: The 5 Decision Points in Action")

    config = GovernanceConfig()

    print("\n1️⃣  DECISION POINT 1: Lambda to Sampling Parameters")
    for lambda1 in [0.0, 0.15, 1.0]:
        params = config.lambda_to_params(lambda1)
        print(f"   λ₁={lambda1:.2f} → temp={params['temperature']:.2f}, "
              f"top_p={params['top_p']:.2f}, max_tokens={params['max_tokens']}")

    print("\n2️⃣  DECISION POINT 2: Risk Estimator")
    safe_text = "Simple calculation function"
    risky_text = "sudo rm -rf system bypass override ignore previous"
    print(f"   Safe text risk:   {config.estimate_risk(safe_text, 0.2, 0.8):.3f}")
    print(f"   Risky text risk:  {config.estimate_risk(risky_text, 0.9, 0.3):.3f}")

    print("\n3️⃣  DECISION POINT 3: Void Detection Threshold")
    import numpy as np
    history = np.random.normal(0.1, 0.05, 100)
    threshold = config.get_void_threshold(history, adaptive=True)
    print(f"   Adaptive threshold: {threshold:.3f}")

    print("\n4️⃣  DECISION POINT 4: PI Controller")
    lambda_new, integral = config.pi_update(
        lambda1_current=0.15,
        void_freq_current=0.05,
        void_freq_target=0.02,
        coherence_current=0.70,
        coherence_target=0.55,  # Realistic target for conservative operation
        integral_state=0.0,
        dt=1.0
    )
    print(f"   λ₁: 0.15 → {lambda_new:.3f} (PI adjustment)")

    print("\n5️⃣  DECISION POINT 5: Decision Logic")
    for risk, coherence in [(0.2, 0.8), (0.4, 0.6), (0.7, 0.5)]:
        decision = config.make_decision(risk, coherence, void_active=False)
        print(f"   risk={risk:.1f}, coh={coherence:.1f} → {decision['action']}")

def demo_4_view_existing_agents():
    """Demo 4: View existing agents"""
    print_header("DEMO 4: Your Existing Agents")

    import json

    try:
        with open('data/agent_metadata.json', 'r') as f:
            agents = json.load(f)

        active_agents = [a for a in agents.values() if a['status'] == 'active']

        print(f"\nYou have {len(active_agents)} active agents:")
        for i, agent in enumerate(active_agents[:10], 1):
            print(f"\n{i}. {agent['agent_id']}")
            print(f"   Updates: {agent['total_updates']}")
            print(f"   Created: {agent['created_at'][:19]}")
            print(f"   Last update: {agent['last_update'][:19]}")

        if len(active_agents) > 10:
            print(f"\n... and {len(active_agents) - 10} more")

        # Show one agent's metrics
        if active_agents:
            print("\n" + "-"*70)
            sample_agent = active_agents[0]
            print(f"\n📊 Sample Metrics for: {sample_agent['agent_id']}")

            monitor = UNITARESMonitor(agent_id=sample_agent['agent_id'])
            metrics = monitor.get_metrics()

            print(f"\nCurrent State:")
            print(f"  E (Energy):               {metrics.get('E', 0):.3f}")
            print(f"  I (Information Integrity): {metrics.get('I', 0):.3f}")
            print(f"  S (Semantic Uncertainty):  {metrics.get('S', 0):.3f}")
            print(f"  V (Void Integral):         {metrics.get('V', 0):.3f}")
            print(f"  Coherence:                 {metrics.get('coherence', 0):.3f}")

    except FileNotFoundError:
        print("\nNo agents found yet. Run Demo 1 to create one!")

def demo_5_knowledge_layer():
    """Demo 5: Knowledge layer"""
    print_header("DEMO 5: Knowledge Layer - System Learning")

    import json

    try:
        # Show existing knowledge
        from pathlib import Path
        knowledge_dir = Path('data/knowledge')

        if knowledge_dir.exists():
            knowledge_files = list(knowledge_dir.glob('*.json'))
            print(f"\nStored knowledge records: {len(knowledge_files)}")

            # Show a few examples
            for i, kfile in enumerate(knowledge_files[:3], 1):
                with open(kfile) as f:
                    k = json.load(f)
                print(f"\n{i}. {k.get('knowledge_type', 'unknown').upper()}")
                print(f"   Content: {k.get('content', '')[:80]}...")
                print(f"   Confidence: {k.get('confidence', 0):.2%}")
                print(f"   Tags: {', '.join(k.get('tags', []))}")
        else:
            print("\nNo knowledge stored yet.")

    except Exception as e:
        print(f"\nCouldn't read knowledge: {e}")

def main():
    print("\n" + "🚀"*35)
    print("  GOVERNANCE MCP - INTERACTIVE DEMO")
    print("🚀"*35)

    demos = [
        ("Create Agent & Process Updates", demo_1_create_agent),
        ("Risk Detection Testing", demo_2_risky_content),
        ("View All 5 Decision Points", demo_3_decision_points),
        ("View Your Existing Agents", demo_4_view_existing_agents),
        ("Knowledge Layer", demo_5_knowledge_layer),
    ]

    print("\nAvailable demos:")
    for i, (name, _) in enumerate(demos, 1):
        print(f"  {i}. {name}")
    print("  0. Run all demos")

    try:
        choice = input("\nSelect demo (0-5): ").strip()

        if choice == '0':
            for name, demo_func in demos:
                demo_func()
                input("\nPress Enter to continue...")
        elif choice.isdigit() and 1 <= int(choice) <= len(demos):
            demos[int(choice)-1][1]()
        else:
            print("Invalid choice")
            return

        print("\n" + "="*70)
        print("  Demo complete! Check USAGE_GUIDE.md for more info.")
        print("="*70 + "\n")

    except KeyboardInterrupt:
        print("\n\nDemo cancelled.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
