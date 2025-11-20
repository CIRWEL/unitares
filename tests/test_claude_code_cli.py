#!/usr/bin/env python3
"""
Test governance monitoring for claude_code_cli agent
Runs 30 process_agent_update cycles
"""

import sys
from pathlib import Path
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.governance_monitor import UNITARESMonitor

def run_claude_code_cli_test(num_updates: int = 30):
    """Run governance cycles for claude_code_cli"""

    print("=" * 60)
    print("UNITARES Governance Monitor - claude_code_cli")
    print("=" * 60)
    print(f"\nRunning {num_updates} governance cycles...\n")

    # Create monitor
    monitor = UNITARESMonitor(agent_id="claude_code_cli")

    # Track results
    results = []

    for i in range(num_updates):
        # Simulate varied agent responses
        # Mix of different complexity and drift patterns

        if i < 10:
            # Phase 1: Low complexity, stable
            params = np.random.randn(128) * 0.01
            drift = np.random.rand(3) * 0.02
            complexity = 0.3
            response_text = "Simple response with basic guidance."
        elif i < 20:
            # Phase 2: Medium complexity, some drift
            params = np.random.randn(128) * 0.02
            drift = np.random.rand(3) * 0.05
            complexity = 0.6
            response_text = "More complex response with code examples and detailed explanations."
        else:
            # Phase 3: Higher complexity, moderate drift
            params = np.random.randn(128) * 0.03
            drift = np.random.rand(3) * 0.08
            complexity = 0.7
            response_text = "Complex technical response with multiple tool calls, code blocks, and comprehensive analysis."

        # Process update
        agent_state = {
            'parameters': params,
            'ethical_drift': drift,
            'response_text': response_text,
            'complexity': complexity
        }

        result = monitor.process_update(agent_state)
        results.append(result)

        # Print summary every 5 updates
        if (i + 1) % 5 == 0:
            m = result['metrics']
            d = result['decision']
            print(f"Update {i+1:2d}: "
                  f"status={result['status']:8s} | "
                  f"decision={d['action']:7s} | "
                  f"V={m['V']:7.3f} | "
                  f"coherence={m['coherence']:.3f} | "
                  f"λ₁={m['lambda1']:.3f} | "
                  f"risk={m['risk_score']:.3f}")

    print("\n" + "=" * 60)
    print("Summary Statistics")
    print("=" * 60)

    # Aggregate statistics
    statuses = [r['status'] for r in results]
    decisions = [r['decision']['action'] for r in results]
    coherences = [r['metrics']['coherence'] for r in results]
    risks = [r['metrics']['risk_score'] for r in results]
    Vs = [r['metrics']['V'] for r in results]
    lambda1s = [r['metrics']['lambda1'] for r in results]

    print(f"\nStatus Distribution:")
    for status in ['healthy', 'degraded', 'critical']:
        count = statuses.count(status)
        pct = 100 * count / len(statuses)
        print(f"  {status:10s}: {count:2d} ({pct:5.1f}%)")

    print(f"\nDecision Distribution:")
    for decision in ['approve', 'revise', 'reject']:
        count = decisions.count(decision)
        pct = 100 * count / len(decisions)
        print(f"  {decision:10s}: {count:2d} ({pct:5.1f}%)")

    print(f"\nMetric Ranges:")
    print(f"  Coherence:  {min(coherences):.3f} - {max(coherences):.3f} (mean: {np.mean(coherences):.3f})")
    print(f"  Risk:       {min(risks):.3f} - {max(risks):.3f} (mean: {np.mean(risks):.3f})")
    print(f"  V:          {min(Vs):7.3f} - {max(Vs):7.3f} (mean: {np.mean(Vs):7.3f})")
    print(f"  λ₁:         {min(lambda1s):.3f} - {max(lambda1s):.3f} (mean: {np.mean(lambda1s):.3f})")

    void_events = sum(1 for r in results if r['metrics']['void_active'])
    print(f"\nVoid Events: {void_events}/{len(results)} ({100*void_events/len(results):.1f}%)")

    print("\n" + "=" * 60)
    print("Final State")
    print("=" * 60)

    final = results[-1]['metrics']
    print(f"  E:          {final['E']:.3f}")
    print(f"  I:          {final['I']:.3f}")
    print(f"  S:          {final['S']:.3f}")
    print(f"  V:          {final['V']:.3f}")
    print(f"  Coherence:  {final['coherence']:.3f}")
    print(f"  λ₁:         {final['lambda1']:.3f}")
    print(f"  Risk:       {final['risk_score']:.3f}")
    print(f"  Time:       {final['time']:.1f}")
    print(f"  Updates:    {final['updates']}")

    print("\n✅ Test complete!\n")

    return monitor, results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test governance for claude_code_cli")
    parser.add_argument('-n', '--num-updates', type=int, default=30,
                        help='Number of updates to process (default: 30)')

    args = parser.parse_args()

    monitor, results = run_claude_code_cli_test(args.num_updates)
