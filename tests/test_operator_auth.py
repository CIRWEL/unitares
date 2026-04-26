"""
Tests for src/mcp_handlers/identity/operator.py — operator-tier auth helper.

Background: prerequisite for the list_agents UUID redaction PR
(KG 2026-04-20T00:57:45). The helper checks an explicit
``X-Unitares-Operator`` header against an env-var allowlist; the test
matrix here exists so that when the redaction PR lands, the gate it
relies on is already proven correct.
"""

import os
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.mcp_handlers.context import SessionSignals, set_session_signals, reset_session_signals
from src.mcp_handlers.identity.operator import is_operator_caller


def _signals(token=None) -> SessionSignals:
    return SessionSignals(unitares_operator_token=token, transport="mcp")


class TestIsOperatorCaller:

    def test_explicit_signals_arg_match(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "alpha,beta")
        assert is_operator_caller(_signals(token="alpha")) is True
        assert is_operator_caller(_signals(token="beta")) is True

    def test_explicit_signals_arg_miss(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "alpha,beta")
        assert is_operator_caller(_signals(token="gamma")) is False

    def test_no_token_presented(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "alpha")
        assert is_operator_caller(_signals(token=None)) is False
        assert is_operator_caller(_signals(token="")) is False

    def test_empty_allowlist_denies_everything(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "")
        assert is_operator_caller(_signals(token="alpha")) is False

    def test_missing_allowlist_env_denies_everything(self, monkeypatch):
        monkeypatch.delenv("UNITARES_OPERATOR_TOKENS", raising=False)
        assert is_operator_caller(_signals(token="alpha")) is False

    def test_no_signals_no_context_denies(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "alpha")
        # signals=None and no contextvar set → False (in-process callers)
        assert is_operator_caller(None) is False

    def test_reads_from_contextvar_when_signals_omitted(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "alpha")
        token = set_session_signals(_signals(token="alpha"))
        try:
            assert is_operator_caller() is True
        finally:
            reset_session_signals(token)

    def test_csv_whitespace_tolerated(self, monkeypatch):
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "  alpha , beta  ")
        assert is_operator_caller(_signals(token="alpha")) is True
        assert is_operator_caller(_signals(token="beta")) is True

    def test_token_case_sensitive(self, monkeypatch):
        """Tokens are bearer secrets — must match exactly, including case."""
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "AlphaTOKEN")
        assert is_operator_caller(_signals(token="AlphaTOKEN")) is True
        assert is_operator_caller(_signals(token="alphatoken")) is False

    def test_rotation_visible_immediately(self, monkeypatch):
        """Rotating tokens via env without restart should take effect on next call."""
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "old-token")
        sig = _signals(token="old-token")
        assert is_operator_caller(sig) is True
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "new-token")
        assert is_operator_caller(sig) is False
        monkeypatch.setenv("UNITARES_OPERATOR_TOKENS", "old-token,new-token")
        assert is_operator_caller(sig) is True


class TestSessionSignalsField:
    """Plumbing assertion: the new field is reachable through the dataclass."""

    def test_field_default_none(self):
        s = SessionSignals()
        assert s.unitares_operator_token is None

    def test_field_set_explicitly(self):
        s = SessionSignals(unitares_operator_token="x")
        assert s.unitares_operator_token == "x"
