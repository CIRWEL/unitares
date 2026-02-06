"""
Tests for src/mcp_handlers/condition_parser.py - Natural language condition parsing.

parse_condition and _normalize_target are pure functions. apply_condition skipped (needs mocking).
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.condition_parser import ParsedCondition, parse_condition, _normalize_target


class TestParsedCondition:

    def test_create(self):
        pc = ParsedCondition(action="set", target="complexity", value=0.3, unit=None)
        assert pc.action == "set"
        assert pc.target == "complexity"
        assert pc.value == 0.3

    def test_to_dict(self):
        pc = ParsedCondition(action="monitor", target="monitoring_duration", value=24, unit="hours")
        pc.original = "Monitor for 24 hours"
        d = pc.to_dict()
        assert d["action"] == "monitor"
        assert d["target"] == "monitoring_duration"
        assert d["value"] == 24
        assert d["unit"] == "hours"
        assert d["original"] == "Monitor for 24 hours"

    def test_default_original_empty(self):
        pc = ParsedCondition(action="set", target="x")
        assert pc.original == ""


class TestNormalizeTarget:

    def test_complexity(self):
        assert _normalize_target("complexity") == "complexity"

    def test_risk_to_risk_score(self):
        assert _normalize_target("risk") == "risk_score"

    def test_risk_score_unchanged(self):
        assert _normalize_target("risk_score") == "risk_score"

    def test_coherence(self):
        assert _normalize_target("coherence") == "coherence"

    def test_monitoring_aliases(self):
        assert _normalize_target("monitoring") == "monitoring_duration"
        assert _normalize_target("monitor") == "monitoring_duration"
        assert _normalize_target("duration") == "monitoring_duration"
        assert _normalize_target("time") == "monitoring_duration"

    def test_unknown_passes_through(self):
        assert _normalize_target("something_else") == "something_else"

    def test_case_insensitive(self):
        assert _normalize_target("Complexity") == "complexity"
        assert _normalize_target("RISK") == "risk_score"


class TestParseConditionReduceIncrease:

    def test_reduce_complexity(self):
        result = parse_condition("Reduce complexity to 0.3")
        assert result.action == "reduce"
        assert result.target == "complexity"
        assert result.value == 0.3

    def test_lower_alias(self):
        result = parse_condition("Lower complexity to 0.2")
        assert result.action == "reduce"

    def test_increase_coherence(self):
        result = parse_condition("Increase coherence to 0.8")
        assert result.action == "increase"
        assert result.target == "coherence"
        assert result.value == 0.8

    def test_raise_alias(self):
        result = parse_condition("Raise coherence to 0.9")
        assert result.action == "increase"

    def test_set_risk_threshold(self):
        result = parse_condition("Set risk to 0.4")
        assert result.action == "set"
        assert result.target == "risk_score"
        assert result.value == 0.4

    def test_preserves_original(self):
        original = "Reduce complexity to 0.5"
        result = parse_condition(original)
        assert result.original == original


class TestParseConditionMonitor:

    def test_monitor_hours(self):
        result = parse_condition("Monitor for 24 hours")
        assert result.action == "monitor"
        assert result.target == "monitoring_duration"
        assert result.value == 24
        assert result.unit == "hours"

    def test_monitor_hour_singular(self):
        result = parse_condition("Monitor for 1 hour")
        assert result.unit == "hours"

    def test_monitor_h_shorthand(self):
        result = parse_condition("Monitor for 12h")
        assert result.value == 12
        assert result.unit == "hours"

    def test_monitor_minutes(self):
        result = parse_condition("Monitor for 30 minutes")
        assert result.action == "monitor"
        assert result.value == 30
        assert result.unit == "minutes"

    def test_monitor_m_shorthand(self):
        result = parse_condition("Monitor for 45m")
        assert result.value == 45
        assert result.unit == "minutes"


class TestParseConditionKeep:

    def test_keep_below(self):
        result = parse_condition("Keep complexity below 0.5")
        assert result.action == "limit"
        assert result.target == "complexity"
        assert result.value == 0.5
        assert result.unit == "below"

    def test_keep_under(self):
        result = parse_condition("Keep risk under 0.6")
        assert result.action == "limit"
        assert result.unit == "below"

    def test_keep_above(self):
        result = parse_condition("Keep coherence above 0.7")
        assert result.action == "limit"
        assert result.target == "coherence"
        assert result.value == 0.7
        assert result.unit == "above"

    def test_keep_over(self):
        result = parse_condition("Keep coherence over 0.8")
        assert result.unit == "above"


class TestParseConditionLimit:

    def test_limit_to(self):
        result = parse_condition("Limit complexity to 0.4")
        assert result.action == "limit"
        assert result.target == "complexity"
        assert result.value == 0.4


class TestParseConditionSetSimple:

    def test_set_without_to(self):
        result = parse_condition("Set complexity 0.3")
        assert result.action == "set"
        assert result.target == "complexity"
        assert result.value == 0.3


class TestParseConditionUnknown:

    def test_unparseable_returns_unknown(self):
        result = parse_condition("Do something vague and mysterious")
        assert result.action == "unknown"
        assert result.target == "unknown"
        assert result.original == "Do something vague and mysterious"

    def test_empty_string(self):
        result = parse_condition("")
        assert result.action == "unknown"


class TestParseConditionCaseInsensitive:

    def test_uppercase(self):
        result = parse_condition("REDUCE COMPLEXITY TO 0.5")
        assert result.action == "reduce"
        assert result.value == 0.5

    def test_mixed_case(self):
        result = parse_condition("Keep Risk Below 0.6")
        assert result.action == "limit"
        assert result.unit == "below"
