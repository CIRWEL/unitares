"""Tests for _resolve_resident_labels precedence.

The dashboard's /v1/residents endpoint resolves which agents to surface as
residents. Precedence (operator override wins):
    1. UNITARES_RESIDENT_AGENTS env var (comma-separated labels) → source "env"
    2. agent_metadata[*].resident == True                        → source "metadata"
    3. KNOWN_RESIDENT_LABELS ∩ labels present in agent_metadata  → source "known-residents"
    4. otherwise empty                                           → source "none"

Path 3 is the auto-detect fallback: the known-resident list already exists
in src/grounding/class_indicator.KNOWN_RESIDENT_LABELS for calibration class
assignment, so the dashboard reuses it instead of requiring a duplicated env
var. We intersect with the current fleet so a fresh install doesn't advertise
residents that aren't running.
"""
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.http_api import _resolve_resident_labels


def _meta(label=None, resident=False):
    return SimpleNamespace(label=label, display_name=label, resident=resident)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("UNITARES_RESIDENT_AGENTS", raising=False)


class TestResolveResidentLabels:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("UNITARES_RESIDENT_AGENTS", "Alpha, Beta ,Gamma")
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Vigil"),  # would match path 3, ignored
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == ["Alpha", "Beta", "Gamma"]
        assert source == "env"

    def test_metadata_resident_flag(self):
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Custom", resident=True),
            "a2": _meta("Vigil", resident=False),
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == ["Custom"]
        assert source == "metadata"

    def test_known_residents_intersected_with_fleet(self):
        # Vigil, Sentinel present; Steward/Watcher/Lumen absent → only present ones surface.
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Vigil"),
            "a2": _meta("Sentinel"),
            "a3": _meta("some-random-agent"),  # not a known resident, ignored
        })
        labels, source = _resolve_resident_labels(server)
        assert set(labels) == {"Vigil", "Sentinel"}
        assert source == "known-residents"

    def test_known_residents_preserves_canonical_order(self):
        # Order should be canonical (Vigil, Sentinel, Watcher, Steward,
        # Chronicler, Lumen), not metadata-dict insertion order, so the
        # dashboard layout is stable.
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Lumen"),
            "a2": _meta("Vigil"),
            "a3": _meta("Watcher"),
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == ["Vigil", "Watcher", "Lumen"]
        assert source == "known-residents"

    def test_chronicler_sorts_between_steward_and_lumen(self):
        # Chronicler is a daily scraper resident; it belongs with the other
        # background residents, before Lumen (which is the embodied agent).
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Lumen"),
            "a2": _meta("Chronicler"),
            "a3": _meta("Steward"),
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == ["Steward", "Chronicler", "Lumen"]
        assert source == "known-residents"

    def test_empty_when_fleet_has_no_known_residents(self):
        # Fresh install — no residents in fleet, no env, no metadata flag.
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("ad-hoc-session-agent"),
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == []
        assert source == "none"

    def test_empty_when_metadata_empty(self):
        server = SimpleNamespace(agent_metadata={})
        labels, source = _resolve_resident_labels(server)
        assert labels == []
        assert source == "none"

    def test_metadata_flag_beats_known_residents(self):
        # If an operator flags an agent resident=True, that wins over the
        # auto-detect path even if known-resident labels are also present.
        server = SimpleNamespace(agent_metadata={
            "a1": _meta("Vigil"),
            "a2": _meta("Custom", resident=True),
        })
        labels, source = _resolve_resident_labels(server)
        assert labels == ["Custom"]
        assert source == "metadata"
