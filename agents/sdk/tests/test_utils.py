"""Tests for SDK utilities."""

import base64
import json

import pytest

from unitares_sdk.utils import (
    atomic_write,
    load_json_state,
    notify,
    parse_continuity_token,
    save_json_state,
    validate_token_uuid,
)


# --- atomic_write ---


def test_atomic_write_creates_file(tmp_path):
    path = tmp_path / "test.json"
    atomic_write(path, '{"key": "value"}')
    assert path.read_text() == '{"key": "value"}'


def test_atomic_write_overwrites_existing(tmp_path):
    path = tmp_path / "test.json"
    path.write_text("old")
    atomic_write(path, "new")
    assert path.read_text() == "new"


def test_atomic_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "sub" / "dir" / "test.json"
    atomic_write(path, "data")
    assert path.read_text() == "data"


# --- load_json_state / save_json_state ---


def test_load_missing_file(tmp_path):
    assert load_json_state(tmp_path / "nope.json") == {}


def test_load_corrupt_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    assert load_json_state(path) == {}


def test_load_dict_format(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"client_session_id": "abc123", "continuity_token": "tok"}')
    result = load_json_state(path)
    assert result["client_session_id"] == "abc123"
    assert result["continuity_token"] == "tok"


def test_load_legacy_bare_string(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('"abc123"')
    result = load_json_state(path)
    assert result == {"client_session_id": "abc123"}


def test_load_legacy_plain_text(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("abc123")
    result = load_json_state(path)
    assert result == {"client_session_id": "abc123"}


def test_load_rejects_list(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]")
    assert load_json_state(path) == {}


def test_load_rejects_null(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("null")
    assert load_json_state(path) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    save_json_state(path, {"client_session_id": "s1", "continuity_token": "t1"})
    result = load_json_state(path)
    assert result["client_session_id"] == "s1"
    assert result["continuity_token"] == "t1"


# --- parse_continuity_token ---


def _make_token(payload: dict, version: str = "v1") -> str:
    """Build a fake v1.<payload>.<sig> token for testing."""
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{version}.{encoded}.fakesig"


def test_parse_valid_token():
    payload = {"aid": "uuid-1234", "model": "test", "exp": 9999999999}
    token = _make_token(payload)
    result = parse_continuity_token(token)
    assert result is not None
    assert result["aid"] == "uuid-1234"
    assert result["model"] == "test"


def test_parse_malformed_token():
    assert parse_continuity_token("not.a.valid.token") is None
    assert parse_continuity_token("v2.abc.def") is None
    assert parse_continuity_token("v1.!!!.sig") is None
    assert parse_continuity_token("garbage") is None
    assert parse_continuity_token("") is None


def test_parse_non_dict_payload():
    encoded = base64.urlsafe_b64encode(b'"just a string"').decode().rstrip("=")
    token = f"v1.{encoded}.sig"
    assert parse_continuity_token(token) is None


# --- validate_token_uuid ---


def test_validate_matching_uuid():
    token = _make_token({"aid": "uuid-1234"})
    assert validate_token_uuid(token, "uuid-1234") is True


def test_validate_mismatched_uuid():
    token = _make_token({"aid": "uuid-1234"})
    assert validate_token_uuid(token, "uuid-5678") is False


def test_validate_no_aid_in_token():
    token = _make_token({"model": "test"})
    assert validate_token_uuid(token, "uuid-1234") is False


def test_validate_malformed_token():
    assert validate_token_uuid("garbage", "uuid-1234") is False


# --- notify ---


def test_notify_does_not_raise():
    """notify is best-effort; should never raise regardless of platform."""
    notify("Test", "This is a test notification")
