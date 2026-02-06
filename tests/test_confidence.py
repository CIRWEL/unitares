"""
Tests for src/confidence.py - Confidence derivation from EISV state.

derive_confidence is nearly pure, just needs mock for tool_usage_tracker.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.confidence import derive_confidence


@dataclass
class MockState:
    """Minimal mock of GovernanceState."""
    coherence: float = 0.5
    I: float = 0.5
    S: float = 0.1
    V: float = 0.0


class TestDeriveConfidenceBasic:

    def test_returns_tuple(self):
        state = MockState()
        result = derive_confidence(state)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_confidence_is_float(self):
        state = MockState()
        confidence, metadata = derive_confidence(state)
        assert isinstance(confidence, float)

    def test_metadata_is_dict(self):
        state = MockState()
        confidence, metadata = derive_confidence(state)
        assert isinstance(metadata, dict)

    def test_bounded_output(self):
        """Confidence clamped to [0.05, 0.95]"""
        state = MockState()
        confidence, _ = derive_confidence(state)
        assert 0.05 <= confidence <= 0.95


class TestDeriveConfidenceEISV:

    def test_high_coherence_high_integrity(self):
        """High coherence + high I → high confidence"""
        state = MockState(coherence=0.9, I=0.9, S=0.05, V=0.0)
        confidence, _ = derive_confidence(state)
        assert confidence > 0.6

    def test_low_coherence_low_integrity(self):
        """Low coherence + low I → low confidence"""
        state = MockState(coherence=0.1, I=0.1, S=0.5, V=0.3)
        confidence, _ = derive_confidence(state)
        assert confidence < 0.3

    def test_high_entropy_reduces_confidence(self):
        """Higher S → lower confidence (entropy penalty)"""
        state_low_s = MockState(coherence=0.7, I=0.7, S=0.1, V=0.0)
        state_high_s = MockState(coherence=0.7, I=0.7, S=0.8, V=0.0)
        conf_low, _ = derive_confidence(state_low_s)
        conf_high, _ = derive_confidence(state_high_s)
        assert conf_low > conf_high

    def test_high_void_reduces_confidence(self):
        """Higher |V| → lower confidence (void penalty)"""
        state_low_v = MockState(coherence=0.7, I=0.7, S=0.1, V=0.0)
        state_high_v = MockState(coherence=0.7, I=0.7, S=0.1, V=0.5)
        conf_low, _ = derive_confidence(state_low_v)
        conf_high, _ = derive_confidence(state_high_v)
        assert conf_low > conf_high

    def test_void_penalty_monotonic(self):
        """Larger void → strictly more penalty"""
        confs = []
        for v in [0.0, 0.1, 0.3, 0.5]:
            state = MockState(coherence=0.7, I=0.7, S=0.1, V=v)
            c, _ = derive_confidence(state)
            confs.append(c)
        # Should be monotonically decreasing
        for i in range(1, len(confs)):
            assert confs[i] <= confs[i-1]


class TestDeriveConfidenceNullState:

    def test_none_state(self):
        """None state → default EISV confidence"""
        confidence, metadata = derive_confidence(None)
        assert 0.05 <= confidence <= 0.95

    def test_none_state_source(self):
        confidence, metadata = derive_confidence(None)
        assert 'source' in metadata


class TestDeriveConfidenceMetadata:

    def test_eisv_metadata_present(self):
        state = MockState(coherence=0.7, I=0.6, S=0.2, V=0.1)
        _, metadata = derive_confidence(state)
        assert 'eisv' in metadata
        assert 'coherence' in metadata['eisv']
        assert 'void_penalty' in metadata['eisv']
        assert 'entropy_penalty' in metadata['eisv']

    def test_source_is_eisv_only(self):
        state = MockState()
        _, metadata = derive_confidence(state)
        assert metadata['source'] == 'eisv_only'

    def test_confidence_in_metadata(self):
        state = MockState()
        confidence, metadata = derive_confidence(state)
        assert metadata['confidence'] == confidence


class TestDeriveConfidenceNeverPerfect:

    def test_never_reaches_1_0(self):
        """Even perfect state → capped at 0.95"""
        state = MockState(coherence=1.0, I=1.0, S=0.0, V=0.0)
        confidence, _ = derive_confidence(state)
        assert confidence <= 0.95

    def test_never_reaches_0_0(self):
        """Even worst state → floored at 0.05"""
        state = MockState(coherence=0.0, I=0.0, S=1.0, V=1.0)
        confidence, _ = derive_confidence(state)
        assert confidence >= 0.05
