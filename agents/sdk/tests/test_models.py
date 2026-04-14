"""Tests for Pydantic response models."""

import pytest

from unitares_sdk.errors import GovernanceError, IdentityDriftError, VerdictError
from unitares_sdk.models import (
    CheckinResult,
    IdentityResult,
    ModelResult,
    OnboardResult,
    SearchResult,
)


# --- OnboardResult ---


def test_onboard_minimal():
    r = OnboardResult(success=True, client_session_id="sid-1")
    assert r.success is True
    assert r.client_session_id == "sid-1"
    assert r.uuid is None
    assert r.verdict == "proceed"


def test_onboard_full():
    r = OnboardResult(
        success=True,
        client_session_id="sid-1",
        uuid="u-123",
        continuity_token="v1.tok.sig",
        continuity_token_supported=True,
        is_new=True,
        verdict="proceed",
        session_resolution_source="explicit",
        welcome="Hello",
    )
    assert r.uuid == "u-123"
    assert r.continuity_token_supported is True


def test_onboard_extra_fields_ignored():
    """Server may return extra fields we don't model — they should not break parsing."""
    r = OnboardResult(
        success=True,
        client_session_id="sid-1",
        unknown_future_field="surprise",
        thread_context={"some": "data"},
    )
    assert r.success is True
    assert not hasattr(r, "unknown_future_field")


# --- CheckinResult ---


def test_checkin_with_metrics():
    r = CheckinResult(
        success=True,
        verdict="proceed",
        coherence=0.85,
        risk=0.1,
        metrics={"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.0, "coherence": 0.85},
    )
    assert r.verdict == "proceed"
    assert r.metrics["E"] == 0.7


def test_checkin_guide_verdict():
    r = CheckinResult(
        success=True,
        verdict="guide",
        guidance="Entropy rising, reduce complexity",
        margin="tight",
    )
    assert r.verdict == "guide"
    assert r.margin == "tight"


# --- IdentityResult ---


def test_identity_result():
    r = IdentityResult(
        client_session_id="sid-1",
        uuid="u-123",
        continuity_token="v1.tok.sig",
        resolution_source="continuity_token",
    )
    assert r.uuid == "u-123"


# --- SearchResult ---


def test_search_result_empty():
    r = SearchResult()
    assert r.results == []


def test_search_result_with_items():
    r = SearchResult(
        results=[
            {"id": "d1", "summary": "Bug found", "tags": ["watcher"]},
            {"id": "d2", "summary": "Test pass", "tags": ["vigil"]},
        ]
    )
    assert len(r.results) == 2


# --- ModelResult ---


def test_model_result():
    r = ModelResult(success=True, response="The code looks correct.")
    assert r.response == "The code looks correct."


# --- Error hierarchy ---


def test_errors_inherit_from_base():
    assert issubclass(IdentityDriftError, GovernanceError)
    assert issubclass(VerdictError, GovernanceError)


def test_identity_drift_error_message():
    e = IdentityDriftError("uuid-aaaa", "uuid-bbbb")
    assert "uuid-aaaa" in str(e)
    assert "uuid-bbbb" in str(e)
    assert e.expected_uuid == "uuid-aaaa"
    assert e.received_uuid == "uuid-bbbb"


def test_verdict_error_message():
    e = VerdictError("pause", "Entropy too high")
    assert "pause" in str(e)
    assert "Entropy too high" in str(e)
    assert e.verdict == "pause"
    assert e.guidance == "Entropy too high"


def test_verdict_error_no_guidance():
    e = VerdictError("reject")
    assert "reject" in str(e)
    assert e.guidance is None
