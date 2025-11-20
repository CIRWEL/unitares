#!/usr/bin/env python3
"""
Export governance history for claude_code_cli
"""

import sys
import os
from pathlib import Path
import numpy as np
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor

def export_session_data():
    agent_id = "claude_code_cli"

    print("=" * 80)
    print(f"Exporting Governance Data: {agent_id}")
    print("=" * 80)
    print()

    monitor = UNITARESMonitor(agent_id)

    # Recreate session to ensure we have the data
    print("Reconstructing session...")

    # Update 1: Baseline
    state1 = {
        "parameters": np.array([0.5] * 128),
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Baseline established",
        "complexity": 0.3
    }
    monitor.process_update(state1)

    # Update 2: Meta-governance
    state2 = {
        "parameters": np.array([0.52] * 64 + [0.48] * 64),
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Meta-governance: Observing composer_cursor recovery",
        "complexity": 0.6
    }
    monitor.process_update(state2)

    # Update 3: Quality discussion
    state3 = {
        "parameters": np.array([0.51] * 64 + [0.49] * 64),
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Quality over quantity! Focused testing.",
        "complexity": 0.4
    }
    monitor.process_update(state3)

    print(f"✅ Session reconstructed: 3 updates")
    print()

    # Export to both formats
    data_dir = Path(project_root) / "data"
    data_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Export JSON
    print("Exporting JSON...")
    json_filename = f"{agent_id}_session_{timestamp}.json"
    json_path = data_dir / json_filename

    json_data = monitor.export_history(format='json')
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(json_data)

    json_size = json_path.stat().st_size
    print(f"✅ JSON exported: {json_filename} ({json_size} bytes)")
    print()

    # Export CSV
    print("Exporting CSV...")
    csv_filename = f"{agent_id}_session_{timestamp}.csv"
    csv_path = data_dir / csv_filename

    csv_data = monitor.export_history(format='csv')
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write(csv_data)

    csv_size = csv_path.stat().st_size
    print(f"✅ CSV exported: {csv_filename} ({csv_size} bytes)")
    print()

    # Display summary
    print("=" * 80)
    print("Export Summary")
    print("=" * 80)
    print(f"Agent ID: {agent_id}")
    print(f"Timestamp: {timestamp}")
    print()
    print("Files created:")
    print(f"  📄 {json_path}")
    print(f"     Size: {json_size} bytes")
    print()
    print(f"  📊 {csv_path}")
    print(f"     Size: {csv_size} bytes")
    print()

    # Get final metrics
    metrics = monitor.get_metrics()
    state = metrics['state']

    print("Session Metrics:")
    print(f"  Total Updates: {state['update_count']}")
    print(f"  Final Coherence: {state['coherence']:.4f}")
    print(f"  Final Lambda1: {state['lambda1']:.4f}")
    print(f"  Mean Risk: {metrics.get('mean_risk', 0):.4f}")

    if metrics.get('decision_statistics'):
        stats = metrics['decision_statistics']
        print()
        print("Decision Statistics:")
        print(f"  Approved: {stats.get('approve', 0)}/{stats.get('total', 0)}")
        print(f"  Revised: {stats.get('revise', 0)}/{stats.get('total', 0)}")
        print(f"  Rejected: {stats.get('reject', 0)}/{stats.get('total', 0)}")

    print("=" * 80)
    print()
    print("✅ Export complete!")
    print()

    return json_path, csv_path

if __name__ == "__main__":
    json_path, csv_path = export_session_data()
