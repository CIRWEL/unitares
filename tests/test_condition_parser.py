"""
Tests for src/mcp_handlers/condition_parser.py - Dialectic condition parsing.

Tests pure parsing functions only (parse_condition, _normalize_target, ParsedCondition).
Does NOT test apply_condition (requires mcp_server runtime).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.condition_parser import (
    ParsedCondition,
    parse_condition,
    _normalize_target,
)


# ============================================================================
# ParsedCondition
# ============================================================================

class TestParsedCondition:

    def test_creation(self):
        pc = ParsedCondition(action="set", target="complexity", value=0.3)
        assert pc.action == "set"
        assert pc.target == "complexity"
        assert pc.value == 0.3
        assert pc.unit is None
        assert pc.original == ""

    def test_to_dict(self):
        pc = ParsedCondition(action="monitor", target="monitoring_duration", value=24, unit="hours")
        pc.original = "Monitor for 24 hours"
        d = pc.to_dict()
        assert d["action"] == "monitor"
        assert d["target"] == "monitoring_duration"
        assert d["value"] == 24
        assert d["unit"] == "hours"
        assert d["original"] == "Monitor for 24 hours"


# ============================================================================
# _normalize_target
# ============================================================================

class TestNormalizeTarget:

    def test_complexity(self):
        assert _normalize_target("complexity") == "complexity"

    def test_risk(self):
        assert _normalize_target("risk") == "risk_score"

    def test_risk_score(self):
        assert _normalize_target("risk_score") == "risk_score"

    def test_risk_threshold(self):
        assert _normalize_target("risk_threshold") == "risk_threshold"

    def test_coherence(self):
        assert _normalize_target("coherence") == "coherence"

    def test_coherence_threshold(self):
        assert _normalize_target("coherence_threshold") == "coherence_threshold"

    def test_monitoring(self):
        assert _normalize_target("monitoring") == "monitoring_duration"

    def test_monitor(self):
        assert _normalize_target("monitor") == "monitoring_duration"

    def test_duration(self):
        assert _normalize_target("duration") == "monitoring_duration"

    def test_time(self):
        assert _normalize_target("time") == "monitoring_duration"

    def test_unknown(self):
        assert _normalize_target("foobar") == "foobar"

    def test_case_insensitive(self):
        assert _normalize_target("COMPLEXITY") == "complexity"


# ============================================================================
# parse_condition - Pattern 1: Reduce/Increase/Set X to Y
# ============================================================================

class TestParseConditionPattern1:

    def test_reduce(self):
        result = parse_condition("Reduce complexity to 0.3")
        assert result.action == "reduce"
        assert result.target == "complexity"
        assert result.value == 0.3

    def test_increase(self):
        result = parse_condition("Increase coherence to 0.8")
        assert result.action == "increase"
        assert result.target == "coherence"
        assert result.value == 0.8

    def test_set(self):
        result = parse_condition("Set risk to 0.4")
        assert result.action == "set"
        assert result.target == "risk_score"
        assert result.value == 0.4

    def test_lower_alias(self):
        result = parse_condition("Lower complexity to 0.2")
        assert result.action == "reduce"
        assert result.value == 0.2

    def test_raise_alias(self):
        result = parse_condition("Raise coherence to 0.9")
        assert result.action == "increase"
        assert result.value == 0.9

    def test_case_insensitive(self):
        result = parse_condition("REDUCE COMPLEXITY TO 0.5")
        assert result.action == "reduce"
        assert result.target == "complexity"
        assert result.value == 0.5

    def test_preserves_original(self):
        result = parse_condition("Reduce complexity to 0.3")
        assert result.original == "Reduce complexity to 0.3"


# ============================================================================
# parse_condition - Pattern 2: Monitor for X hours/minutes
# ============================================================================

class TestParseConditionPattern2:

    def test_hours(self):
        result = parse_condition("Monitor for 24 hours")
        assert result.action == "monitor"
        assert result.target == "monitoring_duration"
        assert result.value == 24
        assert result.unit == "hours"

    def test_minutes(self):
        result = parse_condition("Monitor for 30 minutes")
        assert result.action == "monitor"
        assert result.value == 30
        assert result.unit == "minutes"

    def test_h_abbreviation(self):
        result = parse_condition("Monitor for 2h")
        assert result.action == "monitor"
        assert result.value == 2
        assert result.unit == "hours"

    def test_m_abbreviation(self):
        result = parse_condition("Monitor for 45m")
        assert result.action == "monitor"
        assert result.value == 45
        assert result.unit == "minutes"

    def test_hour_singular(self):
        result = parse_condition("Monitor for 1 hour")
        assert result.action == "monitor"
        assert result.value == 1
        assert result.unit == "hours"

    def test_minute_singular(self):
        result = parse_condition("Monitor for 1 minute")
        assert result.action == "monitor"
        assert result.value == 1
        assert result.unit == "minutes"


# ============================================================================
# parse_condition - Pattern 3: Keep X below/above Y
# ============================================================================

class TestParseConditionPattern3:

    def test_below(self):
        result = parse_condition("Keep complexity below 0.5")
        assert result.action == "limit"
        assert result.target == "complexity"
        assert result.value == 0.5
        assert result.unit == "below"

    def test_above(self):
        result = parse_condition("Keep coherence above 0.3")
        assert result.action == "limit"
        assert result.target == "coherence"
        assert result.value == 0.3
        assert result.unit == "above"

    def test_under(self):
        result = parse_condition("Keep risk under 0.6")
        assert result.action == "limit"
        assert result.unit == "below"

    def test_over(self):
        result = parse_condition("Keep coherence over 0.4")
        assert result.action == "limit"
        assert result.unit == "above"


# ============================================================================
# parse_condition - Pattern 4: Limit X to Y
# ============================================================================

class TestParseConditionPattern4:

    def test_complexity(self):
        result = parse_condition("Limit complexity to 0.3")
        assert result.action == "limit"
        assert result.target == "complexity"
        assert result.value == 0.3

    def test_risk(self):
        result = parse_condition("Limit risk to 0.5")
        assert result.action == "limit"
        assert result.target == "risk_score"
        assert result.value == 0.5


# ============================================================================
# parse_condition - Pattern 5: Set X Y (without "to")
# ============================================================================

class TestParseConditionPattern5:

    def test_set_complexity(self):
        result = parse_condition("Set complexity 0.3")
        assert result.action == "set"
        assert result.target == "complexity"
        assert result.value == 0.3


# ============================================================================
# parse_condition - Unknown patterns
# ============================================================================

class TestParseConditionUnknown:

    def test_unrecognized(self):
        result = parse_condition("Do something weird")
        assert result.action == "unknown"
        assert result.target == "unknown"

    def test_empty(self):
        result = parse_condition("")
        assert result.action == "unknown"
