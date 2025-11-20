#!/usr/bin/env python3
"""
Process second update for claude_code_cli to demonstrate coherence tracking.
"""

import sys
import os
from pathlib import Path
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor

def process_two_updates():
    """Process two sequential updates to show coherence tracking."""

    agent_id = "claude_code_cli"

    print("=" * 80)
    print(f"Sequential Update Test: {agent_id}")
    print("=" * 80)
    print()

    # Initialize monitor
    monitor = UNITARESMonitor(agent_id)

    # Update 1: Baseline
    print("Update 1: Establishing baseline")
    print("-" * 80)

    params1 = np.array([0.5] * 128)
    state1 = {
        "parameters": params1,
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Baseline: Registered for governance monitoring.",
        "complexity": 0.3
    }

    result1 = monitor.process_update(state1)
    print(f"✅ Baseline: Coherence {result1['metrics']['coherence']:.4f}, "
          f"Decision: {result1['decision']['action']}")
    print()

    # Update 2: Small gradual change (should approve)
    print("Update 2: Meta-governance analysis (gradual change)")
    print("-" * 80)

    params2 = np.array([0.52] * 64 + [0.48] * 64)  # Small change
    state2 = {
        "parameters": params2,
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Meta-governance: Observing composer_cursor recovery from coherence collapse.",
        "complexity": 0.6
    }

    # Calculate expected distance
    distance = np.sqrt(np.sum((params2 - params1) ** 2) / len(params1))
    print(f"Expected parameter distance: {distance:.6f}")
    print(f"Expected coherence: {np.exp(-distance / 0.1):.4f}")
    print()

    result2 = monitor.process_update(state2)

    # Display results
    decision = result2['decision']
    metrics = result2['metrics']

    status = "✅" if decision['action'] == 'approve' else "❌"

    print(f"{status} Decision: {decision['action'].upper()}")
    print(f"   Reason: {decision['reason']}")
    print()

    print("Metrics:")
    print(f"  Coherence: {metrics['coherence']:.4f} (threshold: 0.60)")
    print(f"  Risk Score: {metrics['risk_score']:.4f}")
    print(f"  E: {metrics['E']:.4f}, I: {metrics['I']:.4f}, "
          f"S: {metrics['S']:.4f}, V: {metrics['V']:.4f}")
    print(f"  Lambda1: {metrics['lambda1']:.4f}")
    print(f"  Status: {result2['status']}")
    print()

    # Decision statistics
    full_metrics = monitor.get_metrics()
    if full_metrics.get('decision_statistics'):
        stats = full_metrics['decision_statistics']
        print("Decision History:")
        print(f"  Total Updates: {stats.get('total', 0)}")
        print(f"  Approved: {stats.get('approve', 0)}")
        print(f"  Rejected: {stats.get('reject', 0)}")
        print(f"  Approval Rate: {(stats.get('approve', 0) / max(1, stats.get('total', 0))) * 100:.1f}%")

    print("=" * 80)
    print()

    # Verification
    print("Verification:")
    print(f"  Parameter distance: {distance:.6f}")
    print(f"  Within threshold (≤ 0.051): {'✅ Yes' if distance <= 0.051 else '❌ No'}")
    print(f"  Coherence > 0.60: {'✅ Yes' if metrics['coherence'] > 0.60 else '❌ No'}")
    print(f"  Expected: {'APPROVE' if distance <= 0.051 else 'REJECT/REVISE'}")
    print(f"  Actual: {decision['action'].upper()}")
    print()

    return result2, monitor

if __name__ == "__main__":
    result, monitor = process_two_updates()
