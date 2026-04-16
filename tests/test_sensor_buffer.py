"""Tests for the Pi sensor reading buffer."""
import time
import pytest
from src.sensor_buffer import get_latest_sensor_eisv, update_sensor_eisv


def test_buffer_starts_empty():
    """Buffer returns None before any data is written."""
    from src.sensor_buffer import _buffer
    _buffer["eisv"] = None
    _buffer["anima"] = None
    _buffer["timestamp"] = None
    assert get_latest_sensor_eisv() is None


def test_update_and_read():
    """Written EISV is readable."""
    eisv = {"E": 0.6, "I": 0.7, "S": 0.3, "V": -0.1}
    anima = {"warmth": 0.6, "clarity": 0.7, "stability": 0.7, "presence": 0.5}
    update_sensor_eisv(eisv, anima)
    result = get_latest_sensor_eisv()
    assert result is not None
    assert result["eisv"] == eisv
    assert result["anima"] == anima
    assert isinstance(result["timestamp"], float)


def test_staleness_check():
    """Data older than max_age_seconds is not returned."""
    eisv = {"E": 0.5, "I": 0.5, "S": 0.2, "V": 0.0}
    update_sensor_eisv(eisv, {})
    from src.sensor_buffer import _buffer
    _buffer["timestamp"] = time.time() - 700  # 11+ minutes old
    assert get_latest_sensor_eisv(max_age_seconds=600) is None


def test_overwrite():
    """Latest write wins."""
    update_sensor_eisv({"E": 0.1, "I": 0.1, "S": 0.1, "V": 0.0}, {})
    update_sensor_eisv({"E": 0.9, "I": 0.9, "S": 0.9, "V": 0.0}, {})
    result = get_latest_sensor_eisv()
    assert result["eisv"]["E"] == 0.9
