"""
Unit tests for confidence gating in governance monitor.

Tests that lambda1 updates are properly gated based on confidence threshold.
"""

import pytest
import numpy as np
from src.governance_monitor import UNITARESMonitor
from config.governance_config import config


class TestConfidenceGating:
    """Tests for confidence-based lambda1 update gating"""
    
    def test_high_confidence_updates_lambda1(self):
        """Test that high confidence allows lambda1 updates"""
        monitor = UNITARESMonitor("test_agent")
        initial_lambda1 = monitor.state.lambda1
        
        # Create valid agent state
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Run enough updates to trigger lambda1 update cycle (every 10 updates)
        # Use high confidence
        for i in range(10):
            result = monitor.process_update(agent_state, confidence=0.9)
        
        # Lambda1 should have been updated (may be same or different value)
        # Just verify no skip occurred
        assert not hasattr(monitor.state, 'lambda1_skipped_count') or \
               getattr(monitor.state, 'lambda1_skipped_count', 0) == 0
    
    def test_low_confidence_skips_lambda1(self):
        """Test that low confidence skips lambda1 updates"""
        monitor = UNITARESMonitor("test_agent")
        initial_lambda1 = monitor.state.lambda1
        
        # Create valid agent state
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Run enough updates to trigger lambda1 update cycle
        # Use low confidence (< threshold)
        for i in range(10):
            result = monitor.process_update(agent_state, confidence=0.5)
        
        # Should have skipped lambda1 update
        assert hasattr(monitor.state, 'lambda1_skipped_count')
        assert monitor.state.lambda1_skipped_count > 0
    
    def test_confidence_at_threshold_updates(self):
        """Test that confidence exactly at threshold allows updates"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Use confidence exactly at threshold
        threshold = config.CONTROLLER_CONFIDENCE_THRESHOLD
        
        for i in range(10):
            result = monitor.process_update(agent_state, confidence=threshold)
        
        # Should allow update (>= threshold)
        assert not hasattr(monitor.state, 'lambda1_skipped_count') or \
               getattr(monitor.state, 'lambda1_skipped_count', 0) == 0
    
    def test_confidence_just_below_threshold_skips(self):
        """Test that confidence just below threshold skips updates"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Use confidence just below threshold
        threshold = config.CONTROLLER_CONFIDENCE_THRESHOLD
        low_confidence = threshold - 0.01
        
        for i in range(10):
            result = monitor.process_update(agent_state, confidence=low_confidence)
        
        # Should skip
        assert hasattr(monitor.state, 'lambda1_skipped_count')
        assert monitor.state.lambda1_skipped_count > 0
    
    def test_backward_compatibility_default_confidence(self):
        """Test that default confidence (1.0) allows updates (backward compatibility)"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Call without confidence parameter (should default to 1.0)
        for i in range(10):
            result = monitor.process_update(agent_state)
        
        # Should work normally (no skips)
        assert not hasattr(monitor.state, 'lambda1_skipped_count') or \
               getattr(monitor.state, 'lambda1_skipped_count', 0) == 0
    
    def test_skip_counter_increments(self):
        """Test that skip counter increments correctly"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # First 10 updates (should trigger skip)
        for i in range(10):
            monitor.process_update(agent_state, confidence=0.5)
        
        skips_after_first = getattr(monitor.state, 'lambda1_skipped_count', 0)
        assert skips_after_first == 1  # Should have skipped once
        
        # Next 10 updates (should trigger another skip)
        for i in range(10):
            monitor.process_update(agent_state, confidence=0.5)
        
        skips_after_second = getattr(monitor.state, 'lambda1_skipped_count', 0)
        assert skips_after_second == 2  # Should have skipped twice
    
    def test_mixed_confidence_updates(self):
        """Test mixed confidence values (some updates, some skips)"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Mix of high and low confidence
        confidences = [0.9, 0.5, 0.9, 0.5, 0.9, 0.5, 0.9, 0.5, 0.9, 0.5]
        
        for conf in confidences:
            monitor.process_update(agent_state, confidence=conf)
        
        # Should have skipped 5 times (every other update cycle)
        skips = getattr(monitor.state, 'lambda1_skipped_count', 0)
        assert skips == 5
    
    def test_process_update_returns_normal_result(self):
        """Test that process_update returns normal result regardless of confidence"""
        monitor = UNITARESMonitor("test_agent")
        
        agent_state = {
            "parameters": np.random.randn(128) * 0.01,
            "ethical_drift": np.array([0.0, 0.0, 0.0]),
            "response_text": "Test update",
            "complexity": 0.5
        }
        
        # Low confidence
        result_low = monitor.process_update(agent_state, confidence=0.5)
        
        # High confidence
        result_high = monitor.process_update(agent_state, confidence=0.9)
        
        # Both should return normal result structure
        assert "status" in result_low
        assert "decision" in result_low
        assert "metrics" in result_low
        assert "sampling_params" in result_low
        
        assert "status" in result_high
        assert "decision" in result_high
        assert "metrics" in result_high
        assert "sampling_params" in result_high

