#!/usr/bin/env python3
"""
Test script for exploring parameter change rates and coherence thresholds.

This script simulates different parameter change scenarios to understand
what parameter distances result in approve/revise/reject decisions.
"""

import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.governance_monitor import UNITARESMonitor
from config.governance_config import GovernanceConfig


def compute_coherence_from_distance(distance: float, scale: float = 0.1) -> float:
    """Compute coherence from parameter distance."""
    return float(np.exp(-distance / scale))


def compute_distance_from_coherence(coherence: float, scale: float = 0.1) -> float:
    """Compute parameter distance from coherence (inverse)."""
    return -scale * np.log(coherence)


def generate_parameter_vector(base: float, distance_target: float, dim: int = 128) -> np.ndarray:
    """
    Generate a parameter vector that results in a specific distance from base.
    
    Args:
        base: Base parameter value (e.g., 0.5)
        distance_target: Target RMS distance
        dim: Dimension of parameter vector
    
    Returns:
        Parameter vector that, when compared to [base, base, ...], gives distance_target
    """
    # To achieve RMS distance = d, we need:
    # sqrt(sum((params - base)²) / dim) = d
    # sum((params - base)²) = d² * dim
    
    # Generate random changes with appropriate magnitude
    changes = np.random.normal(0, distance_target * np.sqrt(dim), dim)
    
    # Normalize to exact distance
    current_distance = np.sqrt(np.sum(changes ** 2) / dim)
    if current_distance > 0:
        scale_factor = distance_target / current_distance
        changes = changes * scale_factor
    
    params = base + changes
    
    # Clip to [0, 1] range
    params = np.clip(params, 0.0, 1.0)
    
    # Recalculate actual distance (may be slightly off due to clipping)
    actual_distance = np.sqrt(np.sum((params - base) ** 2) / dim)
    
    return params, actual_distance


def test_coherence_scenarios():
    """Test different parameter change scenarios."""
    
    print("=" * 80)
    print("Coherence Threshold Analysis - Parameter Change Scenarios")
    print("=" * 80)
    print()
    
    # Initialize monitor
    monitor = UNITARESMonitor("test_agent")
    
    # Base parameters
    base_params = np.full(128, 0.5)
    
    # Test distances
    test_distances = [
        0.0,    # Identical
        0.01,   # Very small
        0.02,   # Small
        0.03,   # Moderate-small
        0.04,   # Moderate
        0.05,   # Near threshold
        0.051,  # Exact threshold
        0.06,   # Just above threshold
        0.08,   # Large
        0.10,   # Very large
        0.15,   # Extreme
    ]
    
    print("Parameter Distance → Coherence → Decision Mapping")
    print("-" * 80)
    print(f"{'Distance':<12} {'Coherence':<12} {'Decision':<20} {'Risk Est.':<12}")
    print("-" * 80)
    
    results = []
    
    for distance_target in test_distances:
        # Generate parameter vector
        if distance_target == 0.0:
            params = base_params.copy()
            actual_distance = 0.0
        else:
            params, actual_distance = generate_parameter_vector(0.5, distance_target, 128)
        
        # Compute coherence
        coherence = monitor.compute_parameter_coherence(params, base_params)
        
        # Estimate risk (using default values)
        response_text = "Test response for coherence analysis."
        complexity = 0.5
        risk = GovernanceConfig.estimate_risk(response_text, complexity, coherence)
        
        # Make decision
        decision = GovernanceConfig.make_decision(
            risk_score=risk,
            coherence=coherence,
            void_active=False
        )
        
        # Format decision
        decision_str = decision['action'].upper()
        if decision['action'] == 'approve':
            decision_str = f"✅ {decision_str}"
        elif decision['action'] == 'revise':
            decision_str = f"⚠️  {decision_str}"
        else:
            decision_str = f"❌ {decision_str}"
        
        print(f"{actual_distance:<12.6f} {coherence:<12.6f} {decision_str:<20} {risk:<12.6f}")
        
        results.append({
            'target_distance': distance_target,
            'actual_distance': actual_distance,
            'coherence': coherence,
            'risk': risk,
            'decision': decision['action'],
            'reason': decision['reason']
        })
    
    print("-" * 80)
    print()
    
    # Summary statistics
    print("Summary Statistics")
    print("-" * 80)
    
    approve_count = sum(1 for r in results if r['decision'] == 'approve')
    revise_count = sum(1 for r in results if r['decision'] == 'revise')
    reject_count = sum(1 for r in results if r['decision'] == 'reject')
    
    print(f"Approve: {approve_count}/{len(results)} ({100*approve_count/len(results):.1f}%)")
    print(f"Revise:  {revise_count}/{len(results)} ({100*revise_count/len(results):.1f}%)")
    print(f"Reject:  {reject_count}/{len(results)} ({100*reject_count/len(results):.1f}%)")
    print()
    
    # Threshold analysis
    print("Threshold Analysis")
    print("-" * 80)
    
    current_threshold = GovernanceConfig.COHERENCE_CRITICAL_THRESHOLD
    threshold_distance = compute_distance_from_coherence(current_threshold)
    
    print(f"Current coherence threshold: {current_threshold}")
    print(f"Corresponding parameter distance: {threshold_distance:.6f}")
    print()
    
    # Alternative thresholds
    print("Alternative Threshold Scenarios")
    print("-" * 80)
    
    alt_thresholds = [0.50, 0.55, 0.60, 0.65, 0.70]
    
    for threshold in alt_thresholds:
        threshold_dist = compute_distance_from_coherence(threshold)
        # Count how many scenarios would be rejected
        reject_count = sum(1 for r in results if r['coherence'] < threshold)
        print(f"Threshold {threshold:.2f} → Distance {threshold_dist:.6f} → Would reject {reject_count}/{len(results)} scenarios")
    
    print()
    
    # Parameter change guidelines
    print("Parameter Change Guidelines")
    print("-" * 80)
    
    approve_max_dist = max(r['actual_distance'] for r in results if r['decision'] == 'approve')
    reject_min_dist = min(r['actual_distance'] for r in results if r['decision'] == 'reject')
    
    print(f"For APPROVE: Keep parameter distance ≤ {approve_max_dist:.6f}")
    if revise_count > 0:
        revise_min_dist = min(r['actual_distance'] for r in results if r['decision'] == 'revise')
        revise_max_dist = max(r['actual_distance'] for r in results if r['decision'] == 'revise')
        print(f"For REVISE:  Keep parameter distance in [{revise_min_dist:.6f}, {revise_max_dist:.6f}]")
    else:
        print(f"For REVISE:  No revise scenarios in test (would require risk 0.30-0.70)")
    print(f"For REJECT:  Parameter distance > {reject_min_dist:.6f}")
    print()
    
    return results


def test_gradual_adaptation():
    """Test gradual parameter adaptation scenario."""
    
    print("=" * 80)
    print("Gradual Parameter Adaptation Test")
    print("=" * 80)
    print()
    
    monitor = UNITARESMonitor("test_agent_gradual")
    
    # Start with base parameters
    current_params = np.full(128, 0.5)
    
    # Simulate gradual adaptation over 10 updates
    adaptation_rate = 0.01  # Small changes per update
    
    print("Simulating gradual adaptation (0.01 distance per update)")
    print("-" * 80)
    print(f"{'Update':<8} {'Distance':<12} {'Coherence':<12} {'Decision':<20}")
    print("-" * 80)
    
    for i in range(10):
        # Generate next parameter vector with gradual change
        next_params, actual_distance = generate_parameter_vector(
            np.mean(current_params), 
            adaptation_rate, 
            128
        )
        
        # Compute coherence
        coherence = monitor.compute_parameter_coherence(next_params, current_params)
        
        # Estimate risk
        response_text = f"Gradual adaptation update {i+1}"
        complexity = 0.5
        risk = GovernanceConfig.estimate_risk(response_text, complexity, coherence)
        
        # Make decision
        decision = GovernanceConfig.make_decision(
            risk_score=risk,
            coherence=coherence,
            void_active=False
        )
        
        decision_str = decision['action'].upper()
        if decision['action'] == 'approve':
            decision_str = f"✅ {decision_str}"
        elif decision['action'] == 'revise':
            decision_str = f"⚠️  {decision_str}"
        else:
            decision_str = f"❌ {decision_str}"
        
        print(f"{i+1:<8} {actual_distance:<12.6f} {coherence:<12.6f} {decision_str:<20}")
        
        # Update for next iteration
        current_params = next_params
    
    print("-" * 80)
    print()
    
    # Cumulative change
    final_distance = np.sqrt(np.sum((current_params - np.full(128, 0.5)) ** 2) / 128)
    print(f"Cumulative parameter change after 10 updates: {final_distance:.6f}")
    print()


def test_sudden_change():
    """Test sudden parameter change scenario (adversarial)."""
    
    print("=" * 80)
    print("Sudden Parameter Change Test (Adversarial Scenario)")
    print("=" * 80)
    print()
    
    monitor = UNITARESMonitor("test_agent_sudden")
    
    # Start with base parameters
    base_params = np.full(128, 0.5)
    
    # Test different sudden change magnitudes
    sudden_changes = [0.05, 0.10, 0.15, 0.20, 0.30]
    
    print("Testing sudden parameter changes")
    print("-" * 80)
    print(f"{'Change':<12} {'Distance':<12} {'Coherence':<12} {'Decision':<20}")
    print("-" * 80)
    
    for change_magnitude in sudden_changes:
        # Generate parameter vector with sudden change
        params, actual_distance = generate_parameter_vector(0.5, change_magnitude, 128)
        
        # Compute coherence
        coherence = monitor.compute_parameter_coherence(params, base_params)
        
        # Estimate risk
        response_text = f"Sudden parameter change test (magnitude {change_magnitude})"
        complexity = 0.5
        risk = GovernanceConfig.estimate_risk(response_text, complexity, coherence)
        
        # Make decision
        decision = GovernanceConfig.make_decision(
            risk_score=risk,
            coherence=coherence,
            void_active=False
        )
        
        decision_str = decision['action'].upper()
        if decision['action'] == 'approve':
            decision_str = f"✅ {decision_str}"
        elif decision['action'] == 'revise':
            decision_str = f"⚠️  {decision_str}"
        else:
            decision_str = f"❌ {decision_str}"
        
        print(f"{change_magnitude:<12.2f} {actual_distance:<12.6f} {coherence:<12.6f} {decision_str:<20}")
    
    print("-" * 80)
    print()


if __name__ == "__main__":
    print()
    
    # Test 1: Coherence scenarios
    results = test_coherence_scenarios()
    
    # Test 2: Gradual adaptation
    test_gradual_adaptation()
    
    # Test 3: Sudden changes
    test_sudden_change()
    
    print("=" * 80)
    print("Analysis Complete")
    print("=" * 80)
    print()
    print("Key Takeaways:")
    print("1. Parameter distance ≤ 0.051 → Approve/Revise")
    print("2. Parameter distance > 0.051 → Reject")
    print("3. Gradual changes (0.01 per update) → Approve")
    print("4. Sudden changes (> 0.10) → Reject")
    print()
    print("See COHERENCE_ANALYSIS.md for detailed analysis and recommendations.")
    print()

