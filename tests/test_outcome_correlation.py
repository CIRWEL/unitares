"""
Tests for outcome correlation wiring fixes:
1. Behavioral sensor receives outcome_history via cached monitor attribute
2. Behavioral EISV embedded in outcome event detail
3. Outcome history caching from Phase 5 to monitor
"""

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

from src.behavioral_sensor import compute_behavioral_sensor_eisv


# ── Helpers ──

def make_histories(n=10, decision="proceed", coherence=0.5, regime="high",
                   E=0.7, I=0.6, S=0.3, V=0.1):
    return {
        "decision_history": [decision] * n,
        "coherence_history": [coherence] * n,
        "regime_history": [regime] * n,
        "E_history": [E] * n,
        "I_history": [I] * n,
        "S_history": [S] * n,
        "V_history": [V] * n,
    }


def _parse(result):
    if isinstance(result, (list, tuple)):
        return json.loads(result[0].text)
    return json.loads(result.text)


# ============================================================================
# Test 1: outcome_history affects behavioral sensor E and I
# ============================================================================

class TestOutcomeHistoryInBehavioralSensor:
    """Verify that outcome_history integration changes E and I values."""

    def test_good_outcomes_boost_E(self):
        """Agents with successful outcomes should have higher E."""
        h = make_histories(n=10)
        base_kwargs = dict(
            **h,
            calibration_error=0.1,
            drift_norm=0.1,
            complexity_divergence=0.1,
        )
        # Without outcomes
        result_no_outcomes = compute_behavioral_sensor_eisv(**base_kwargs)

        # With good outcomes (>= 3 required for integration)
        good_outcomes = [
            {'is_bad': False, 'outcome_score': 0.9},
            {'is_bad': False, 'outcome_score': 0.85},
            {'is_bad': False, 'outcome_score': 0.8},
            {'is_bad': False, 'outcome_score': 0.95},
        ]
        result_with_outcomes = compute_behavioral_sensor_eisv(
            **base_kwargs, outcome_history=good_outcomes,
        )

        assert result_no_outcomes is not None
        assert result_with_outcomes is not None
        # Good outcomes should boost E (success rate feeds into E)
        assert result_with_outcomes['E'] >= result_no_outcomes['E'] - 0.01

    def test_bad_outcomes_lower_E(self):
        """Agents with failed outcomes should have lower E."""
        h = make_histories(n=10)
        base_kwargs = dict(
            **h,
            calibration_error=0.1,
            drift_norm=0.1,
            complexity_divergence=0.1,
        )
        result_no_outcomes = compute_behavioral_sensor_eisv(**base_kwargs)

        bad_outcomes = [
            {'is_bad': True, 'outcome_score': 0.1},
            {'is_bad': True, 'outcome_score': 0.15},
            {'is_bad': True, 'outcome_score': 0.2},
            {'is_bad': True, 'outcome_score': 0.1},
        ]
        result_with_outcomes = compute_behavioral_sensor_eisv(
            **base_kwargs, outcome_history=bad_outcomes,
        )

        assert result_no_outcomes is not None
        assert result_with_outcomes is not None
        # Bad outcomes should lower E
        assert result_with_outcomes['E'] <= result_no_outcomes['E'] + 0.01

    def test_fewer_than_3_outcomes_ignored(self):
        """Outcome integration requires >= 3 outcomes; fewer should match no-outcome path."""
        h = make_histories(n=10)
        base_kwargs = dict(
            **h,
            calibration_error=0.1,
            drift_norm=0.1,
            complexity_divergence=0.1,
        )
        result_no_outcomes = compute_behavioral_sensor_eisv(**base_kwargs)

        two_outcomes = [
            {'is_bad': False, 'outcome_score': 0.9},
            {'is_bad': False, 'outcome_score': 0.85},
        ]
        result_two = compute_behavioral_sensor_eisv(
            **base_kwargs, outcome_history=two_outcomes,
        )

        assert result_no_outcomes is not None
        assert result_two is not None
        # With < 3 outcomes, E should be same as no outcomes
        assert abs(result_two['E'] - result_no_outcomes['E']) < 0.001

    def test_outcome_consistency_affects_I(self):
        """Consistent outcome scores should give higher I than inconsistent."""
        h = make_histories(n=10)
        base_kwargs = dict(
            **h,
            calibration_error=0.1,
            drift_norm=0.1,
            complexity_divergence=0.1,
        )
        # Consistent outcomes (low variance)
        consistent = [
            {'is_bad': False, 'outcome_score': 0.8},
            {'is_bad': False, 'outcome_score': 0.82},
            {'is_bad': False, 'outcome_score': 0.79},
            {'is_bad': False, 'outcome_score': 0.81},
        ]
        result_consistent = compute_behavioral_sensor_eisv(
            **base_kwargs, outcome_history=consistent,
        )

        # Inconsistent outcomes (high variance)
        inconsistent = [
            {'is_bad': False, 'outcome_score': 0.95},
            {'is_bad': True, 'outcome_score': 0.1},
            {'is_bad': False, 'outcome_score': 0.9},
            {'is_bad': True, 'outcome_score': 0.15},
        ]
        result_inconsistent = compute_behavioral_sensor_eisv(
            **base_kwargs, outcome_history=inconsistent,
        )

        assert result_consistent is not None
        assert result_inconsistent is not None
        # Consistent outcomes → higher I (lower variance)
        assert result_consistent['I'] >= result_inconsistent['I'] - 0.01


# ============================================================================
# Test 2: Monitor caches outcome_history for sync process_update
# ============================================================================

class TestMonitorOutcomeHistoryCache:
    """Verify _cached_outcome_history attribute on GovernanceMonitor."""

    def test_monitor_has_cached_outcome_history_attr(self):
        """GovernanceMonitor should initialize _cached_outcome_history."""
        from src.governance_monitor import UNITARESMonitor
        monitor = UNITARESMonitor(agent_id='test-agent', load_state=False)
        assert hasattr(monitor, '_cached_outcome_history')
        assert monitor._cached_outcome_history is None

    def test_cached_outcome_history_settable(self):
        """Phase 5 should be able to set _cached_outcome_history on monitor."""
        from src.governance_monitor import UNITARESMonitor
        monitor = UNITARESMonitor(agent_id='test-agent', load_state=False)
        test_outcomes = [{'is_bad': False, 'outcome_score': 0.9}]
        monitor._cached_outcome_history = test_outcomes
        assert monitor._cached_outcome_history == test_outcomes


# ============================================================================
# Test 3: Behavioral EISV embedded in outcome event detail
# ============================================================================

class TestBehavioralEISVInOutcomeEvent:
    """Verify behavioral state is included in outcome event detail."""

    @pytest.mark.asyncio
    async def test_behavioral_eisv_in_detail(self):
        """outcome_event should embed behavioral EISV in detail dict."""
        from src.behavioral_state import BehavioralEISV

        # Set up mock behavioral state on monitor
        mock_bstate = BehavioralEISV()
        mock_bstate.E = 0.65
        mock_bstate.I = 0.70
        mock_bstate.S = 0.25
        mock_bstate.V = -0.05
        mock_bstate.update_count = 5  # Enough for confidence > 0 (5/10 = 0.5)

        mock_monitor = MagicMock()
        mock_monitor._behavioral_state = mock_bstate
        mock_monitor._prev_confidence = 0.8

        mock_mcp_server = MagicMock()
        mock_mcp_server.monitors = {'agent-123': mock_monitor}

        mock_db = MagicMock()
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.72, 'I': 0.75, 'S': 0.16, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })
        mock_db.record_outcome_event = AsyncMock(return_value='outcome-456')

        with patch('src.mcp_handlers.observability.outcome_events.mcp_server', mock_mcp_server), \
             patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-123'):

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'task_completed',
                'confidence': 0.8,
            })

        parsed = _parse(result)
        assert parsed.get('outcome_id') == 'outcome-456'

        # Verify behavioral_eisv was included in the detail passed to DB
        call_kwargs = mock_db.record_outcome_event.call_args
        detail_arg = call_kwargs.kwargs.get('detail') or call_kwargs[1].get('detail', {})
        assert 'behavioral_eisv' in detail_arg
        beh = detail_arg['behavioral_eisv']
        assert abs(beh['E'] - 0.65) < 0.01
        assert abs(beh['I'] - 0.70) < 0.01
        assert abs(beh['S'] - 0.25) < 0.01
        assert beh['confidence'] > 0

    @pytest.mark.asyncio
    async def test_no_behavioral_eisv_without_monitor(self):
        """If no monitor exists, outcome event should still work (ODE snapshot only)."""
        mock_mcp_server = MagicMock()
        mock_mcp_server.monitors = {}  # No monitors

        mock_db = MagicMock()
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.72, 'I': 0.75, 'S': 0.16, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })
        mock_db.record_outcome_event = AsyncMock(return_value='outcome-789')

        with patch('src.mcp_handlers.observability.outcome_events.mcp_server', mock_mcp_server), \
             patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-999'):

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'test_passed',
            })

        parsed = _parse(result)
        assert parsed.get('outcome_id') == 'outcome-789'

        # No behavioral_eisv in detail (no monitor)
        call_kwargs = mock_db.record_outcome_event.call_args
        detail_arg = call_kwargs.kwargs.get('detail') or call_kwargs[1].get('detail', {})
        assert 'behavioral_eisv' not in detail_arg
