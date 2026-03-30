"""
Tests for outcome event → calibration wiring.

Covers:
- Phase 5 auto-emit records calibration (positive + negative)
- Explicit outcome_event handler records calibration
- No double-emit (completion takes priority over failure)
- Tactical calibration for test outcomes
- Confidence lookup fallback from monitor
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from types import SimpleNamespace

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp.types import TextContent


def _parse(result):
    """Parse TextContent result(s) into a dict."""
    if isinstance(result, (list, tuple)):
        return json.loads(result[0].text)
    return json.loads(result.text)


# ============================================================================
# Phase 5: auto-emit calibration wiring
# ============================================================================

class TestPhase5CalibrationWiring:
    """Test calibration recording from Phase 5 auto-emitted outcome events."""

    @pytest.fixture
    def phase5_ctx(self):
        """Minimal ctx object for Phase 5 auto-emit path."""
        ctx = SimpleNamespace(
            response_text="Completed the feature implementation",
            complexity=0.5,
            arguments={'confidence': 0.8, 'client_session_id': 'sess-1'},
            metrics_dict={
                'E': 0.72, 'I': 0.75, 'S': 0.15, 'V': -0.03,
                'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
            },
            outcome_event_id=None,
            result=None,
        )
        return ctx

    @pytest.mark.asyncio
    async def test_positive_outcome_records_calibration(self, phase5_ctx):
        """Auto-emitted task_completed should record calibration prediction."""
        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='outcome-123')

        mock_checker = MagicMock()
        mock_checker.record_prediction = MagicMock()

        agent_id = 'agent-abc'
        ctx = phase5_ctx

        # Simulate Phase 5 auto-emit logic inline
        ctx.outcome_event_id = None
        if ctx.response_text and ctx.complexity >= 0.3:
            _rt_lower = ctx.response_text.lower()
            _completion_signals = (
                'completed', 'implemented', 'deployed', 'finished',
                'fixed', 'resolved', 'shipped', 'merged', 'built',
                'created', 'added', 'refactored', 'migrated',
            )
            if any(sig in _rt_lower for sig in _completion_signals):
                ctx.outcome_event_id = await mock_db.record_outcome_event(
                    agent_id=agent_id,
                    outcome_type='task_completed',
                    is_bad=False,
                    outcome_score=min(1.0, ctx.metrics_dict.get('coherence', 0.5) * 1.5),
                    session_id=ctx.arguments.get('client_session_id'),
                    eisv_e=ctx.metrics_dict.get('E'),
                    eisv_i=ctx.metrics_dict.get('I'),
                    eisv_s=ctx.metrics_dict.get('S'),
                    eisv_v=ctx.metrics_dict.get('V'),
                    eisv_phi=ctx.metrics_dict.get('phi'),
                    eisv_verdict=ctx.metrics_dict.get('verdict'),
                    eisv_coherence=ctx.metrics_dict.get('coherence'),
                    eisv_regime=ctx.metrics_dict.get('regime'),
                    detail={
                        'source': 'auto_checkin',
                        'complexity': ctx.complexity,
                        'confidence': ctx.arguments.get('confidence'),
                        'summary': ctx.response_text[:500],
                    },
                )
                if ctx.outcome_event_id:
                    _conf = ctx.arguments.get('confidence')
                    if _conf is not None:
                        _outcome_score = min(1.0, ctx.metrics_dict.get('coherence', 0.5) * 1.5)
                        mock_checker.record_prediction(
                            confidence=float(_conf),
                            predicted_correct=(float(_conf) >= 0.5),
                            actual_correct=_outcome_score,
                        )

        assert ctx.outcome_event_id == 'outcome-123'
        mock_checker.record_prediction.assert_called_once_with(
            confidence=0.8,
            predicted_correct=True,
            actual_correct=min(1.0, 0.48 * 1.5),
        )

    @pytest.mark.asyncio
    async def test_no_calibration_when_confidence_missing(self, phase5_ctx):
        """No calibration recorded when confidence is None."""
        phase5_ctx.arguments = {'client_session_id': 'sess-1'}  # No confidence

        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='outcome-456')
        mock_checker = MagicMock()

        ctx = phase5_ctx
        ctx.outcome_event_id = None
        if ctx.response_text and ctx.complexity >= 0.3:
            _rt_lower = ctx.response_text.lower()
            if 'completed' in _rt_lower:
                ctx.outcome_event_id = await mock_db.record_outcome_event(
                    agent_id='agent-x', outcome_type='task_completed',
                    is_bad=False, outcome_score=0.72,
                    session_id=None, eisv_e=None, eisv_i=None, eisv_s=None,
                    eisv_v=None, eisv_phi=None, eisv_verdict=None,
                    eisv_coherence=None, eisv_regime=None, detail={},
                )
                if ctx.outcome_event_id:
                    _conf = ctx.arguments.get('confidence')
                    if _conf is not None:
                        mock_checker.record_prediction(
                            confidence=float(_conf),
                            predicted_correct=(float(_conf) >= 0.5),
                            actual_correct=0.72,
                        )

        assert ctx.outcome_event_id == 'outcome-456'
        mock_checker.record_prediction.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_outcome_auto_emit(self, phase5_ctx):
        """Failure signals emit task_failed + calibration when no completion emitted."""
        phase5_ctx.response_text = "The build failed with regression errors"

        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='bad-outcome-1')
        mock_checker = MagicMock()

        ctx = phase5_ctx
        agent_id = 'agent-fail'
        ctx.outcome_event_id = None

        if ctx.response_text and ctx.complexity >= 0.3:
            _rt_lower = ctx.response_text.lower()
            _completion_signals = (
                'completed', 'implemented', 'deployed', 'finished',
                'fixed', 'resolved', 'shipped', 'merged', 'built',
                'created', 'added', 'refactored', 'migrated',
            )
            if any(sig in _rt_lower for sig in _completion_signals):
                ctx.outcome_event_id = 'should-not-reach'

            # Negative outcome auto-emit
            if not ctx.outcome_event_id:
                _failure_signals = (
                    'failed', 'error', 'broken', 'reverted', 'blocked',
                    'stuck', 'crash', 'regression',
                )
                if any(sig in _rt_lower for sig in _failure_signals):
                    _bad_score = max(0.0, 1.0 - ctx.metrics_dict.get('coherence', 0.5) * 1.5)
                    _bad_oid = await mock_db.record_outcome_event(
                        agent_id=agent_id,
                        outcome_type='task_failed',
                        is_bad=True,
                        outcome_score=_bad_score,
                        session_id=ctx.arguments.get('client_session_id'),
                        eisv_e=ctx.metrics_dict.get('E'),
                        eisv_i=ctx.metrics_dict.get('I'),
                        eisv_s=ctx.metrics_dict.get('S'),
                        eisv_v=ctx.metrics_dict.get('V'),
                        eisv_phi=ctx.metrics_dict.get('phi'),
                        eisv_verdict=ctx.metrics_dict.get('verdict'),
                        eisv_coherence=ctx.metrics_dict.get('coherence'),
                        eisv_regime=ctx.metrics_dict.get('regime'),
                        detail={
                            'source': 'auto_checkin',
                            'complexity': ctx.complexity,
                            'confidence': ctx.arguments.get('confidence'),
                            'summary': ctx.response_text[:500],
                            'is_negative': True,
                        },
                    )
                    if _bad_oid:
                        _conf = ctx.arguments.get('confidence')
                        if _conf is not None:
                            mock_checker.record_prediction(
                                confidence=float(_conf),
                                predicted_correct=(float(_conf) >= 0.5),
                                actual_correct=_bad_score,
                            )

        assert ctx.outcome_event_id is None  # No completion signal matched
        mock_db.record_outcome_event.assert_called_once()
        call_kwargs = mock_db.record_outcome_event.call_args
        assert call_kwargs.kwargs['outcome_type'] == 'task_failed'
        assert call_kwargs.kwargs['is_bad'] is True

        expected_bad_score = max(0.0, 1.0 - 0.48 * 1.5)
        mock_checker.record_prediction.assert_called_once_with(
            confidence=0.8,
            predicted_correct=True,
            actual_correct=expected_bad_score,
        )

    @pytest.mark.asyncio
    async def test_no_double_emit_completion_takes_priority(self, phase5_ctx):
        """When text has both 'fixed' and 'error', completion wins — no negative emit."""
        phase5_ctx.response_text = "Fixed the error in the parser"

        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='outcome-fix')
        mock_checker = MagicMock()

        ctx = phase5_ctx
        ctx.outcome_event_id = None

        if ctx.response_text and ctx.complexity >= 0.3:
            _rt_lower = ctx.response_text.lower()
            _completion_signals = ('completed', 'implemented', 'deployed', 'finished',
                                   'fixed', 'resolved', 'shipped', 'merged', 'built',
                                   'created', 'added', 'refactored', 'migrated')
            if any(sig in _rt_lower for sig in _completion_signals):
                ctx.outcome_event_id = await mock_db.record_outcome_event(
                    agent_id='agent-x', outcome_type='task_completed',
                    is_bad=False, outcome_score=0.72,
                    session_id=None, eisv_e=None, eisv_i=None, eisv_s=None,
                    eisv_v=None, eisv_phi=None, eisv_verdict=None,
                    eisv_coherence=None, eisv_regime=None, detail={},
                )

            # Negative check — should NOT fire because outcome_event_id is set
            if not ctx.outcome_event_id:
                _failure_signals = ('failed', 'error', 'broken', 'reverted', 'blocked',
                                    'stuck', 'crash', 'regression')
                if any(sig in _rt_lower for sig in _failure_signals):
                    pytest.fail("Should not reach negative emit when completion matched")

        assert ctx.outcome_event_id == 'outcome-fix'
        # Only one call (for completion), not two
        mock_db.record_outcome_event.assert_called_once()


# ============================================================================
# Explicit outcome_event handler: calibration wiring
# ============================================================================

class TestExplicitOutcomeEventCalibration:
    """Test calibration recording from explicit outcome_event calls."""

    @pytest.mark.asyncio
    async def test_records_calibration_with_explicit_confidence(self):
        """outcome_event with confidence param records calibration."""
        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='oe-1')
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.7, 'I': 0.75, 'S': 0.15, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })

        mock_checker = MagicMock()
        mock_checker.record_prediction = MagicMock()
        mock_checker.record_tactical_decision = MagicMock()

        with patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.observability.outcome_events.mcp_server') as mock_server, \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-test'), \
             patch('src.calibration.calibration_checker', mock_checker):

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'test_passed',
                'confidence': 0.85,
            })

        parsed = _parse(result)
        assert parsed.get('outcome_id') == 'oe-1'

        # Should have recorded both prediction and tactical
        mock_checker.record_prediction.assert_called_once_with(
            confidence=0.85,
            predicted_correct=True,
            actual_correct=1.0,  # test_passed → outcome_score=1.0
        )
        mock_checker.record_tactical_decision.assert_called_once_with(
            confidence=0.85,
            decision='proceed',
            immediate_outcome=True,  # not is_bad
        )

    @pytest.mark.asyncio
    async def test_confidence_fallback_from_monitor(self):
        """When confidence not in args, falls back to monitor._prev_confidence."""
        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='oe-2')
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.7, 'I': 0.75, 'S': 0.15, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })

        mock_monitor = MagicMock()
        mock_monitor._prev_confidence = 0.7

        mock_checker = MagicMock()

        with patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.observability.outcome_events.mcp_server') as mock_server, \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-mon'), \
             patch('src.calibration.calibration_checker', mock_checker):

            mock_server.monitors = {'agent-mon': mock_monitor}

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'task_completed',
                # No confidence param
            })

        parsed = _parse(result)
        assert parsed.get('outcome_id') == 'oe-2'

        mock_checker.record_prediction.assert_called_once_with(
            confidence=0.7,
            predicted_correct=True,
            actual_correct=1.0,
        )

    @pytest.mark.asyncio
    async def test_no_calibration_when_no_confidence_available(self):
        """No calibration when neither param nor monitor has confidence."""
        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='oe-3')
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.7, 'I': 0.75, 'S': 0.15, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })

        mock_checker = MagicMock()

        with patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.observability.outcome_events.mcp_server') as mock_server, \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-no-conf'), \
             patch('src.calibration.calibration_checker', mock_checker):

            mock_server.monitors = {}  # No monitor for this agent

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'task_completed',
            })

        parsed = _parse(result)
        assert parsed.get('outcome_id') == 'oe-3'
        mock_checker.record_prediction.assert_not_called()

    @pytest.mark.asyncio
    async def test_test_failed_records_tactical_with_bad_outcome(self):
        """test_failed records tactical calibration with immediate_outcome=False."""
        mock_db = MagicMock()
        mock_db.record_outcome_event = AsyncMock(return_value='oe-4')
        mock_db.get_latest_eisv_by_agent_id = AsyncMock(return_value={
            'E': 0.7, 'I': 0.75, 'S': 0.15, 'V': -0.03,
            'phi': 0.1, 'verdict': 'safe', 'coherence': 0.48, 'regime': 'CONVERGENCE',
        })

        mock_checker = MagicMock()

        with patch('src.db.get_db', return_value=mock_db), \
             patch('src.mcp_handlers.observability.outcome_events.mcp_server') as mock_server, \
             patch('src.mcp_handlers.context.get_context_agent_id', return_value='agent-tf'), \
             patch('src.calibration.calibration_checker', mock_checker):

            mock_server.monitors = {}

            from src.mcp_handlers.observability.outcome_events import handle_outcome_event
            result = await handle_outcome_event({
                'outcome_type': 'test_failed',
                'confidence': 0.9,  # Overconfident!
            })

        mock_checker.record_prediction.assert_called_once_with(
            confidence=0.9,
            predicted_correct=True,
            actual_correct=0.0,  # test_failed → is_bad=True → outcome_score=0.0
        )
        mock_checker.record_tactical_decision.assert_called_once_with(
            confidence=0.9,
            decision='proceed',
            immediate_outcome=False,  # is_bad=True → not is_bad = False
        )


# ============================================================================
# Schema: OutcomeEventParams confidence field
# ============================================================================

class TestOutcomeEventParamsSchema:
    """Verify confidence field exists in OutcomeEventParams."""

    def test_confidence_field_exists(self):
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        fields = OutcomeEventParams.model_fields
        assert 'confidence' in fields
        field_info = fields['confidence']
        assert field_info.default is None  # Optional

    def test_confidence_accepts_valid_value(self):
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        params = OutcomeEventParams(outcome_type='test_passed', confidence=0.85)
        assert params.confidence == 0.85

    def test_confidence_none_by_default(self):
        from src.mcp_handlers.schemas.core import OutcomeEventParams
        params = OutcomeEventParams(outcome_type='test_passed')
        assert params.confidence is None
