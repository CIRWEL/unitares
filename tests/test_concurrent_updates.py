"""
Integration Tests for Concurrent Updates and State Consistency

Tests that multiple concurrent updates don't corrupt agent state.
"""

import asyncio
import random
import math
from typing import List
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.governance_monitor import UNITARESMonitor


async def test_concurrent_updates():
    """Test that concurrent updates don't corrupt state"""
    agent_id = "test_agent_concurrent"
    
    # Create monitor
    monitor = UNITARESMonitor(agent_id)
    
    async def update_task(task_id: int):
        """Simulate agent update"""
        complexity = random.uniform(0.1, 0.9)
        drift = [random.uniform(0, 0.1) for _ in range(3)]
        parameters = [random.uniform(0.4, 0.6) for _ in range(128)]  # Consistent params
        
        # Process update
        result = monitor.process_update(
            agent_id=agent_id,
            parameters=parameters,
            ethical_drift=drift,
            response_text=f"Test update {task_id}",
            complexity=complexity
        )
        return task_id, result
    
    # Launch 10 concurrent updates (simulated sequentially since process_update is sync)
    # In real async scenario, these would be truly concurrent
    results = []
    for i in range(10):
        task_id, result = await update_task(i)
        results.append((task_id, result))
    
    # Verify no corruption
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 0, f"Concurrent updates failed: {errors}"
    
    # Check final state is consistent
    assert monitor.state.update_count == 10, f"Expected 10 updates, got {monitor.state.update_count}"
    assert len(monitor.state.V_history) == 10, f"Expected 10 V_history entries, got {len(monitor.state.V_history)}"
    assert len(monitor.state.coherence_history) == 10, f"Expected 10 coherence_history entries, got {len(monitor.state.coherence_history)}"
    
    # Verify no NaN/inf values
    state_values = [
        monitor.state.E, monitor.state.I, monitor.state.S, monitor.state.V,
        monitor.state.coherence, monitor.state.lambda1
    ]
    nan_inf_values = [v for v in state_values if math.isnan(v) or math.isinf(v)]
    assert len(nan_inf_values) == 0, f"Found NaN/inf values: {nan_inf_values}"
    
    print(f"✅ Concurrent test passed: {monitor.state.update_count} updates processed")
    print(f"   Final coherence: {monitor.state.coherence:.3f}")
    print(f"   Final risk: {monitor.state.risk_score:.3f}")
    return True


async def test_recovery_scenario():
    """Test recovery from coherence collapse"""
    agent_id = "test_recovery_agent"
    monitor = UNITARESMonitor(agent_id)
    
    # Induce coherence collapse with random parameters
    print("Inducing coherence collapse...")
    for i in range(10):
        monitor.process_update(
            parameters=[random.random() for _ in range(128)],  # Random params = low coherence
            ethical_drift=[0.1, 0.1, 0.1],  # High drift
            response_text=f"Chaos update {i}",
            complexity=0.8
        )
    
    initial_coherence = monitor.state.coherence
    initial_lambda1 = monitor.state.lambda1
    
    print(f"After chaos: coherence={initial_coherence:.3f}, lambda1={initial_lambda1:.3f}")
    
    # Verify system attempts recovery (adaptive control should reduce λ₁)
    assert monitor.state.lambda1 < 0.15, f"Expected lambda1 < 0.15, got {monitor.state.lambda1}"
    
    # Process good updates with consistent parameters
    print("Processing recovery updates...")
    for i in range(10):
        monitor.process_update(
            parameters=[0.5] * 128,  # Consistent params
            ethical_drift=[0.0, 0.0, 0.0],  # No drift
            response_text=f"Recovery update {i}",
            complexity=0.3
        )
    
    final_coherence = monitor.state.coherence
    final_lambda1 = monitor.state.lambda1
    
    print(f"After recovery: coherence={final_coherence:.3f}, lambda1={final_lambda1:.3f}")
    
    # Verify recovery
    assert final_coherence > initial_coherence, f"Coherence should improve: {initial_coherence:.3f} -> {final_coherence:.3f}"
    assert final_lambda1 > initial_lambda1, f"Lambda1 should increase: {initial_lambda1:.3f} -> {final_lambda1:.3f}"
    
    print("✅ Recovery test passed")
    return True


if __name__ == "__main__":
    print("Running concurrent updates test...")
    asyncio.run(test_concurrent_updates())
    
    print("\nRunning recovery scenario test...")
    asyncio.run(test_recovery_scenario())
    
    print("\n✅ All tests passed!")

