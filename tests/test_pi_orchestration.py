"""
Tests for Pi orchestration EISV mapping and sync.

Pi orchestration lives in the ``unitares-pi-plugin`` package as of the
Phase B1 extraction (docs/specs/2026-04-17-lumen-decoupling-design.md).
These tests are skipped when the plugin isn't installed.
"""

import pytest
from unittest.mock import AsyncMock, patch

_plugin = pytest.importorskip("unitares_pi_plugin.handlers")
map_anima_to_eisv = _plugin.map_anima_to_eisv


class TestMapAnimaToEisv:
    """Tests for the map_anima_to_eisv function."""

    def test_basic_mapping(self):
        """Test basic anima-to-EISV mapping without pre-computed EISV."""
        anima = {"warmth": 0.7, "clarity": 0.6, "stability": 0.8, "presence": 0.9}
        eisv = map_anima_to_eisv(anima)

        assert eisv["E"] == pytest.approx(0.7)
        assert eisv["I"] == pytest.approx(0.6)
        assert eisv["S"] == pytest.approx(0.2)  # 1.0 - 0.8
        assert eisv["V"] == pytest.approx(0.03)  # (1.0 - 0.9) * 0.3

    def test_void_scaling_matches_pi(self):
        """Void should be scaled by 0.3 to match Pi's eisv_mapper."""
        anima = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}
        eisv = map_anima_to_eisv(anima)
        # Pi formula: V = (1 - presence) * 0.3
        assert eisv["V"] == pytest.approx((1.0 - 0.5) * 0.3)

    def test_void_zero_presence(self):
        """V at zero presence should be 0.3, not 1.0."""
        anima = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.0}
        eisv = map_anima_to_eisv(anima)
        assert eisv["V"] == pytest.approx(0.3)

    def test_void_full_presence(self):
        """V at full presence should be 0.0."""
        anima = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 1.0}
        eisv = map_anima_to_eisv(anima)
        assert eisv["V"] == pytest.approx(0.0)

    def test_pre_computed_eisv_preferred(self):
        """Pre-computed EISV from Pi should be used when available."""
        anima = {"warmth": 0.7, "clarity": 0.6, "stability": 0.8, "presence": 0.9}
        pi_eisv = {"E": 0.42, "I": 0.55, "S": 0.2, "V": 0.08}

        eisv = map_anima_to_eisv(anima, pre_computed_eisv=pi_eisv)

        assert eisv["E"] == pytest.approx(0.42)
        assert eisv["I"] == pytest.approx(0.55)
        assert eisv["S"] == pytest.approx(0.2)
        assert eisv["V"] == pytest.approx(0.08)

    def test_pre_computed_eisv_incomplete_falls_back(self):
        """Incomplete pre-computed EISV should fall back to anima mapping."""
        anima = {"warmth": 0.7, "clarity": 0.6, "stability": 0.8, "presence": 0.9}
        incomplete_eisv = {"E": 0.42, "I": 0.55}  # Missing S and V

        eisv = map_anima_to_eisv(anima, pre_computed_eisv=incomplete_eisv)

        # Should use fallback, not the incomplete pre-computed values
        assert eisv["E"] == pytest.approx(0.7)
        assert eisv["V"] == pytest.approx((1.0 - 0.9) * 0.3)

    def test_pre_computed_eisv_none(self):
        """None pre-computed EISV should use fallback mapping."""
        anima = {"warmth": 0.7, "clarity": 0.6, "stability": 0.8, "presence": 0.9}
        eisv = map_anima_to_eisv(anima, pre_computed_eisv=None)
        assert eisv["E"] == pytest.approx(0.7)

    def test_defaults_when_keys_missing(self):
        """Missing anima keys should default to 0.5."""
        eisv = map_anima_to_eisv({})
        assert eisv["E"] == pytest.approx(0.5)
        assert eisv["I"] == pytest.approx(0.5)
        assert eisv["S"] == pytest.approx(0.5)
        assert eisv["V"] == pytest.approx(0.15)  # (1.0 - 0.5) * 0.3

    def test_pre_computed_returns_copy(self):
        """Pre-computed EISV should be returned as a copy, not a reference."""
        pi_eisv = {"E": 0.42, "I": 0.55, "S": 0.2, "V": 0.08}
        eisv = map_anima_to_eisv({}, pre_computed_eisv=pi_eisv)
        eisv["E"] = 999
        assert pi_eisv["E"] == 0.42  # Original unchanged
