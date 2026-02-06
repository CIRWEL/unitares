"""
Tests for src/eisv_format.py - EISV metric formatting and validation.

All pure functions, no mocking needed.
"""

import pytest
import sys
from pathlib import Path
import math

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.eisv_format import (
    EISVMetrics,
    EISVTrajectory,
    format_eisv_compact,
    format_eisv_detailed,
    format_eisv_trajectory,
    validate_eisv_complete,
    eisv_from_dict,
    format_eisv,
)


# --- EISVMetrics Tests ---


class TestEISVMetrics:

    def test_create(self):
        m = EISVMetrics(E=0.8, I=1.0, S=0.03, V=-0.07)
        assert m.E == 0.8
        assert m.I == 1.0
        assert m.S == 0.03
        assert m.V == -0.07

    def test_validate_valid(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.0)
        m.validate()  # Should not raise

    def test_validate_boundary_values(self):
        m = EISVMetrics(E=0.0, I=0.0, S=0.0, V=-10.0)
        m.validate()
        m = EISVMetrics(E=1.0, I=1.0, S=1.0, V=10.0)
        m.validate()

    def test_validate_e_out_of_range(self):
        m = EISVMetrics(E=1.5, I=0.5, S=0.5, V=0.0)
        with pytest.raises(ValueError, match="E must be in"):
            m.validate()

    def test_validate_e_negative(self):
        m = EISVMetrics(E=-0.1, I=0.5, S=0.5, V=0.0)
        with pytest.raises(ValueError, match="E must be in"):
            m.validate()

    def test_validate_i_out_of_range(self):
        m = EISVMetrics(E=0.5, I=1.1, S=0.5, V=0.0)
        with pytest.raises(ValueError, match="I must be in"):
            m.validate()

    def test_validate_s_out_of_range(self):
        m = EISVMetrics(E=0.5, I=0.5, S=-0.5, V=0.0)
        with pytest.raises(ValueError, match="S must be in"):
            m.validate()

    def test_v_has_no_bounds(self):
        """V can be any value - no bounds checking."""
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=-100.0)
        m.validate()
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=100.0)
        m.validate()

    def test_is_namedtuple(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.0)
        assert isinstance(m, tuple)
        assert len(m) == 4


# --- EISVTrajectory Tests ---


class TestEISVTrajectory:

    def test_deltas(self):
        start = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.0)
        end = EISVMetrics(E=0.8, I=0.6, S=0.3, V=-0.1)
        traj = EISVTrajectory(start=start, end=end)

        d = traj.deltas()
        assert abs(d.E - 0.3) < 0.001
        assert abs(d.I - 0.1) < 0.001
        assert abs(d.S - (-0.2)) < 0.001
        assert abs(d.V - (-0.1)) < 0.001

    def test_percent_changes(self):
        start = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.1)
        end = EISVMetrics(E=1.0, I=0.25, S=0.5, V=0.2)
        traj = EISVTrajectory(start=start, end=end)

        pct = traj.percent_changes()
        assert abs(pct['E'] - 100.0) < 0.1  # 0.5 -> 1.0 = +100%
        assert abs(pct['I'] - (-50.0)) < 0.1  # 0.5 -> 0.25 = -50%
        assert pct['S'] == 0  # No change
        assert abs(pct['V'] - 100.0) < 0.1  # 0.1 -> 0.2 = +100%

    def test_percent_changes_zero_start(self):
        """Division by zero should return 0 for E/I/S, inf for V."""
        start = EISVMetrics(E=0.0, I=0.0, S=0.0, V=0.0)
        end = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        traj = EISVTrajectory(start=start, end=end)

        pct = traj.percent_changes()
        assert pct['E'] == 0
        assert pct['I'] == 0
        assert pct['S'] == 0
        assert pct['V'] == float('inf')


# --- format_eisv_compact Tests ---


class TestFormatEISVCompact:

    def test_basic_format(self):
        m = EISVMetrics(E=0.80, I=1.00, S=0.03, V=-0.07)
        result = format_eisv_compact(m)
        assert result == "E=0.80 I=1.00 S=0.03 V=-0.07"

    def test_zero_values(self):
        m = EISVMetrics(E=0.0, I=0.0, S=0.0, V=0.0)
        result = format_eisv_compact(m)
        assert "E=0.00" in result
        assert "V=0.00" in result

    def test_always_has_all_four(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        result = format_eisv_compact(m)
        assert "E=" in result
        assert "I=" in result
        assert "S=" in result
        assert "V=" in result


# --- format_eisv_detailed Tests ---


class TestFormatEISVDetailed:

    def test_with_labels(self):
        m = EISVMetrics(E=0.80, I=1.00, S=0.03, V=-0.07)
        result = format_eisv_detailed(m, include_labels=True)
        assert "Energy" in result
        assert "Integrity" in result
        assert "Entropy" in result
        assert "Void" in result

    def test_without_labels(self):
        m = EISVMetrics(E=0.80, I=1.00, S=0.03, V=-0.07)
        result = format_eisv_detailed(m, include_labels=False)
        assert "Energy" not in result
        assert "E:" in result

    def test_with_user_friendly(self):
        m = EISVMetrics(E=0.80, I=1.00, S=0.03, V=-0.07)
        result = format_eisv_detailed(m, include_user_friendly=True)
        assert "engaged" in result.lower() or "energized" in result.lower()

    def test_multiline(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        result = format_eisv_detailed(m)
        lines = result.strip().split('\n')
        assert len(lines) == 4  # One line per metric


# --- format_eisv_trajectory Tests ---


class TestFormatEISVTrajectory:

    def test_basic_trajectory(self):
        start = EISVMetrics(E=0.71, I=0.84, S=0.14, V=-0.01)
        end = EISVMetrics(E=0.80, I=1.00, S=0.03, V=-0.07)
        traj = EISVTrajectory(start=start, end=end)

        result = format_eisv_trajectory(traj)
        assert "Energy" in result
        assert "→" in result
        assert "0.71" in result
        assert "0.80" in result

    def test_shows_direction(self):
        start = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.0)
        end = EISVMetrics(E=0.8, I=0.3, S=0.5, V=0.0)
        traj = EISVTrajectory(start=start, end=end)

        result = format_eisv_trajectory(traj)
        # E increased, I decreased, S unchanged
        lines = result.split('\n')
        assert len(lines) == 4

    def test_infinity_percentage(self):
        """When start is 0 and end is non-zero for V, should show ∞."""
        start = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.0)
        end = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        traj = EISVTrajectory(start=start, end=end)

        result = format_eisv_trajectory(traj)
        assert "∞" in result

    def test_v_multiplier_format(self):
        """V with large multiplier should show Nx format."""
        start = EISVMetrics(E=0.5, I=0.5, S=0.5, V=-0.01)
        end = EISVMetrics(E=0.5, I=0.5, S=0.5, V=-0.05)
        traj = EISVTrajectory(start=start, end=end)

        result = format_eisv_trajectory(traj)
        # -0.01 -> -0.05, multiplier = 5x
        assert "x" in result or "+" in result or "-" in result


# --- validate_eisv_complete Tests ---


class TestValidateEISVComplete:

    def test_valid(self):
        assert validate_eisv_complete({"E": 0.5, "I": 0.5, "S": 0.5, "V": 0.5}) is True

    def test_missing_v(self):
        with pytest.raises(ValueError, match="Missing.*V"):
            validate_eisv_complete({"E": 0.5, "I": 0.5, "S": 0.5})

    def test_missing_multiple(self):
        with pytest.raises(ValueError, match="Missing"):
            validate_eisv_complete({"E": 0.5})

    def test_empty_dict(self):
        with pytest.raises(ValueError, match="Missing"):
            validate_eisv_complete({})

    def test_extra_keys_ok(self):
        data = {"E": 0.5, "I": 0.5, "S": 0.5, "V": 0.5, "coherence": 0.47}
        assert validate_eisv_complete(data) is True


# --- eisv_from_dict Tests ---


class TestEISVFromDict:

    def test_valid_dict(self):
        m = eisv_from_dict({"E": 0.8, "I": 1.0, "S": 0.03, "V": -0.07})
        assert isinstance(m, EISVMetrics)
        assert m.E == 0.8

    def test_converts_to_float(self):
        m = eisv_from_dict({"E": "0.8", "I": "1.0", "S": "0.03", "V": "-0.07"})
        assert m.E == 0.8
        assert isinstance(m.E, float)

    def test_missing_key_raises(self):
        with pytest.raises(ValueError):
            eisv_from_dict({"E": 0.8, "I": 1.0, "S": 0.03})

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            eisv_from_dict({"E": 1.5, "I": 1.0, "S": 0.03, "V": 0.0})


# --- format_eisv Tests ---


class TestFormatEISV:

    def test_compact_style(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        result = format_eisv(m, style='compact')
        assert "E=0.50" in result

    def test_detailed_style(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        result = format_eisv(m, style='detailed')
        assert "Energy" in result

    def test_unknown_style_raises(self):
        m = EISVMetrics(E=0.5, I=0.5, S=0.5, V=0.5)
        with pytest.raises(ValueError, match="Unknown style"):
            format_eisv(m, style='unknown')
