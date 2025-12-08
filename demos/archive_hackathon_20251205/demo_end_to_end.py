#!/usr/bin/env python3
"""
End-to-End Governance System Demo

Demonstrates the complete flow:
1. Initialize agent with metadata
2. Run governance updates (with varying confidence)
3. Show governance decisions and metrics
4. Display accumulated metadata
5. Export final state

Shows how updates flow through the system and metadata accumulates.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import json
from datetime import datetime
from src.governance_monitor import UNITARESMonitor
from src.mcp_server_std import (
    monitors,
    agent_metadata,
    AgentMetadata,
    save_metadata,
    load_metadata,
    get_or_create_monitor
)


def print_section(title: str):
    """Print formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def initialize_agent(agent_id: str):
    """Initialize agent with metadata"""
    print_section("STEP 1: Initialize Agent")
    
    # Load existing metadata
    load_metadata()
    
    # Create monitor
    monitor = get_or_create_monitor(agent_id)
    
    # Initialize metadata if new
    if agent_id not in agent_metadata:
        agent_metadata[agent_id] = AgentMetadata(
            agent_id=agent_id,
            status="active",
            created_at=datetime.now().isoformat(),
            last_update=datetime.now().isoformat(),
            version="v2.0",
            total_updates=0,
            tags=["demo", "end-to-end"],
            notes="End-to-end governance system demonstration"
        )
        agent_metadata[agent_id].add_lifecycle_event("created", "Demo initialization")
        save_metadata()
        print(f"✅ Created new agent: {agent_id}")
    else:
        print(f"✅ Loaded existing agent: {agent_id}")
        print(f"   Total updates so far: {agent_metadata[agent_id].total_updates}")
    
    return monitor


def run_updates(monitor: UNITARESMonitor, agent_id: str, num_updates: int = 15):
    """Run governance updates with varying confidence"""
    print_section(f"STEP 2: Run {num_updates} Governance Updates")
    
    results = []
    
    # Different scenarios with different confidence levels
    scenarios = [
        ("Normal operation", 0.3, 0.9, 1.0),      # High confidence
        ("Complex task", 0.7, 0.85, 0.9),         # High confidence
        ("Uncertain metrics", 0.5, 0.7, 0.6),     # Low confidence - will skip lambda1
        ("Recovery", 0.4, 0.9, 0.95),             # High confidence
        ("Low confidence test", 0.6, 0.8, 0.5),   # Low confidence - will skip lambda1
    ]
    
    print(f"\nRunning updates with varying confidence levels...\n")
    print(f"{'Update':<8} {'Conf':<6} {'Status':<10} {'Decision':<10} {'E':<6} {'I':<6} {'V':<8} {'λ₁':<6} {'Attn':<6}")
    print("-" * 70)
    
    for i in range(num_updates):
        scenario = scenarios[i % len(scenarios)]
        scenario_name, complexity, target_coherence, confidence = scenario
        
        # Create agent state
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.random.rand(3) * 0.05,
            "response_text": f"Update {i}: {scenario_name}",
            "complexity": complexity
        }
        
        # Process update with confidence
        result = monitor.process_update(agent_state, confidence=confidence)
        
        # Update metadata
        meta = agent_metadata[agent_id]
        meta.last_update = datetime.now().isoformat()
        meta.total_updates += 1
        if hasattr(monitor.state, 'lambda1_skipped_count'):
            meta.lambda1_skips = monitor.state.lambda1_skipped_count
        save_metadata()
        
        # Store result
        results.append({
            "update": i,
            "confidence": confidence,
            "scenario": scenario_name,
            "result": result
        })
        
        # Print summary
        metrics = result['metrics']
        attention = metrics.get('attention_score', metrics.get('risk_score', 0))
        print(f"{i:<8} {confidence:<6.2f} {result['status']:<10} "
              f"{result['decision']['action']:<10} "
              f"{metrics['E']:<6.3f} {metrics['I']:<6.3f} "
              f"{metrics['V']:<+8.3f} {metrics['lambda1']:<6.3f} "
              f"{attention:<6.3f}")
        
        # Show lambda1 skip if it happened
        if i % 10 == 9 and confidence < 0.8:
            skips = getattr(monitor.state, 'lambda1_skipped_count', 0)
            if skips > 0:
                print(f"         ⚠️  Lambda1 update skipped (confidence {confidence:.2f} < 0.80)")
    
    return results


def show_governance_metrics(monitor: UNITARESMonitor):
    """Display current governance metrics"""
    print_section("STEP 3: Current Governance Metrics")
    
    metrics = monitor.get_metrics()
    
    print("\nThermodynamic State:")
    print(f"  E (Energy):           {metrics['state']['E']:.4f}")
    print(f"  I (Information):      {metrics['state']['I']:.4f}")
    print(f"  S (Entropy):          {metrics['state']['S']:.4f}")
    print(f"  V (Void):             {metrics['state']['V']:+.4f}")
    print(f"  Coherence:            {metrics['state']['coherence']:.4f}")
    print(f"  Lambda1:              {metrics['state']['lambda1']:.4f}")
    print(f"  Void Active:          {metrics['state']['void_active']}")
    
    print("\nAdaptive Control:")
    print(f"  Update Count:         {metrics['state']['update_count']}")
    if hasattr(monitor.state, 'lambda1_skipped_count'):
        print(f"  Lambda1 Skips:        {monitor.state.lambda1_skipped_count}")
    
    print("\nHealth Status:")
    print(f"  Status:               {metrics.get('status', 'unknown')}")
    if 'decision_statistics' in metrics:
        stats = metrics['decision_statistics']
        print(f"  Decisions:            {stats.get('approve', 0)} approve, "
              f"{stats.get('revise', 0)} revise, {stats.get('reject', 0)} reject")


def show_metadata(agent_id: str):
    """Display accumulated metadata"""
    print_section("STEP 4: Agent Metadata")
    
    if agent_id not in agent_metadata:
        print("❌ Agent not found in metadata")
        return
    
    meta = agent_metadata[agent_id]
    
    print("\nBasic Info:")
    print(f"  Agent ID:             {meta.agent_id}")
    print(f"  Status:               {meta.status}")
    print(f"  Version:              {meta.version}")
    print(f"  Created:              {meta.created_at}")
    print(f"  Last Update:          {meta.last_update}")
    print(f"  Total Updates:       {meta.total_updates}")
    print(f"  Lambda1 Skips:       {getattr(meta, 'lambda1_skips', 0)}")
    
    print("\nTags:")
    if meta.tags:
        print(f"  {', '.join(meta.tags)}")
    else:
        print("  (none)")
    
    print("\nLifecycle Events:")
    if meta.lifecycle_events:
        for event in meta.lifecycle_events[-5:]:  # Show last 5
            print(f"  [{event['timestamp']}] {event['event']}")
            if event.get('reason'):
                print(f"    Reason: {event['reason']}")
    else:
        print("  (none)")
    
    if meta.notes:
        print("\nNotes:")
        print(f"  {meta.notes[:200]}..." if len(meta.notes) > 200 else f"  {meta.notes}")


def export_final_state(monitor: UNITARESMonitor, agent_id: str, results: list):
    """Export final state to file"""
    print_section("STEP 5: Export Final State")
    
    export_data = {
        "agent_id": agent_id,
        "exported_at": datetime.now().isoformat(),
        "metadata": agent_metadata[agent_id].to_dict(),
        "final_metrics": monitor.get_metrics(),
        "update_summary": [
            {
                "update": r["update"],
                "confidence": r["confidence"],
                "scenario": r["scenario"],
                "status": r["result"]["status"],
                "decision": r["result"]["decision"]["action"],
                "metrics": r["result"]["metrics"]
            }
            for r in results
        ]
    }
    
    export_file = Path(__file__).parent.parent / "data" / f"{agent_id}_end_to_end_demo.json"
    export_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(export_file, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    print(f"✅ Exported to: {export_file}")
    print(f"   File size: {export_file.stat().st_size} bytes")


def main():
    """Run complete end-to-end demo"""
    agent_id = "demo_end_to_end"
    
    try:
        # Step 1: Initialize
        monitor = initialize_agent(agent_id)
        
        # Step 2: Run updates
        results = run_updates(monitor, agent_id, num_updates=15)
        
        # Step 3: Show metrics
        show_governance_metrics(monitor)
        
        # Step 4: Show metadata
        show_metadata(agent_id)
        
        # Step 5: Export
        export_final_state(monitor, agent_id, results)
        
        # Summary
        print_section("SUMMARY")
        print("\n✅ Complete governance flow demonstrated:")
        print(f"   • {len(results)} updates processed")
        print(f"   • Governance decisions made")
        print(f"   • Metrics tracked and evolved")
        print(f"   • Metadata accumulated")
        print(f"   • Lambda1 skips: {getattr(monitor.state, 'lambda1_skipped_count', 0)}")
        print(f"   • Final status: {monitor.get_metrics().get('status', 'unknown')}")
        print("\n🎯 The system works end-to-end!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

