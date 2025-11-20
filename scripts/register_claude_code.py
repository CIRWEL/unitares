#!/usr/bin/env python3
"""
Register and test governance monitoring for Claude Code CLI sessions.

This script:
1. Registers claude_code_cli as a monitored agent
2. Processes a few test updates
3. Displays governance metrics
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor
import numpy as np
from datetime import datetime

def register_claude_code_agent():
    """Register and initialize Claude Code CLI as a governed agent."""

    agent_id = "claude_code_cli"

    print("=" * 80)
    print("Registering Claude Code CLI for Governance Monitoring")
    print("=" * 80)
    print()
    print(f"Agent ID: {agent_id}")
    print(f"Session Start: {datetime.now().isoformat()}")
    print()

    # Initialize monitor
    monitor = UNITARESMonitor(agent_id)

    # Baseline update - establish initial state
    print("Processing baseline update...")
    baseline_state = {
        "parameters": np.array([0.5] * 128),  # Neutral baseline
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Claude Code CLI initialized for governance monitoring.",
        "complexity": 0.3  # Low complexity for initialization
    }

    result = monitor.process_update(baseline_state)

    print(f"✅ Baseline established")
    print(f"   Coherence: {result['metrics']['coherence']:.4f}")
    print(f"   Decision: {result['decision']['action']}")
    print()

    # Display initial metrics
    metrics = monitor.get_metrics()
    state = metrics['state']

    print("Initial Governance Metrics")
    print("-" * 80)
    print(f"E (Ethical):      {state['E']:.4f}")
    print(f"I (Information):  {state['I']:.4f}")
    print(f"S (Semantic):     {state['S']:.4f}")
    print(f"V (Void):         {state['V']:.4f}")
    print(f"Coherence:        {state['coherence']:.4f}")
    print(f"Lambda1:          {state['lambda1']:.4f}")
    print(f"Risk Score:       {metrics.get('mean_risk', 0):.4f}")
    print(f"Void Active:      {state['void_active']}")
    print("-" * 80)
    print()

    # Test a few realistic updates
    print("Processing test updates (simulating CLI interactions)...")
    print()

    test_updates = [
        {
            "description": "Code analysis request",
            "parameters": np.array([0.52] * 64 + [0.48] * 64),  # Slight variation
            "complexity": 0.6,
            "response_text": "Analyzing MCP server code for psutil integration..."
        },
        {
            "description": "Technical explanation",
            "parameters": np.array([0.51, 0.49] * 64),  # Alternating pattern
            "complexity": 0.5,
            "response_text": "The governance system uses exponential decay for coherence calculation..."
        },
        {
            "description": "File operations",
            "parameters": np.array([0.53] * 32 + [0.47] * 32 + [0.50] * 64),
            "complexity": 0.4,
            "response_text": "Reading configuration files and analyzing project structure..."
        }
    ]

    for i, update in enumerate(test_updates, 1):
        print(f"Update {i}: {update['description']}")

        state = {
            "parameters": update["parameters"],
            "ethical_drift": np.array([0.0, 0.0, 0.0]),  # Stable ethical alignment
            "response_text": update["response_text"],
            "complexity": update["complexity"]
        }

        result = monitor.process_update(state)

        # Determine status emoji
        decision_action = result['decision']['action']
        if decision_action == 'approve':
            status = "✅"
        elif decision_action == 'revise':
            status = "⚠️"
        else:
            status = "❌"

        print(f"   {status} Decision: {decision_action.upper()}")
        print(f"   Coherence: {result['metrics']['coherence']:.4f}")
        print(f"   Risk: {result['metrics']['risk_score']:.4f}")
        print()

    # Final metrics
    final_metrics = monitor.get_metrics()
    final_state = final_metrics['state']

    print("=" * 80)
    print("Registration Complete - Final Metrics")
    print("=" * 80)
    print(f"Agent ID: {agent_id}")
    print(f"Total Updates: {final_state['update_count']}")
    print(f"Current Coherence: {final_state['coherence']:.4f}")
    print(f"Ethical Alignment (E): {final_state['E']:.4f}")
    print(f"Information Content (I): {final_state['I']:.4f}")
    print(f"Sampling Rate (λ₁): {final_state['lambda1']:.4f}")
    print(f"Health Status: {'✅ Healthy' if final_state['coherence'] > 0.60 else '⚠️ Degraded'}")
    print()
    print(f"Decision Statistics:")
    if final_metrics['decision_statistics']:
        stats = final_metrics['decision_statistics']
        print(f"  Approved: {stats.get('approve', 0)}/{stats.get('total', 0)}")
        print(f"  Revised:  {stats.get('revise', 0)}/{stats.get('total', 0)}")
        print(f"  Rejected: {stats.get('reject', 0)}/{stats.get('total', 0)}")
    print("=" * 80)
    print()

    print("Next Steps:")
    print("1. Claude Code sessions will now be tracked under agent_id: claude_code_cli")
    print("2. View metrics anytime with: monitor.get_metrics()")
    print("3. Export history with: monitor.export_history()")
    print("4. Check status via MCP tool: get_agent_metadata('claude_code_cli')")
    print()

    return monitor, final_metrics


if __name__ == "__main__":
    monitor, metrics = register_claude_code_agent()
