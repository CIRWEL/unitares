"""Tests for the client-side onboard helper.

Covers the behavior described in `scripts/client/onboard_helper.py`:

* successful onboard writes a fresh cache and returns ok
* ``trajectory_required`` from the server triggers one retry with
  ``force_new=true``
* a failure (including a failed retry) leaves the existing cache untouched
* missing ``uuid`` in the response counts as a failure, not success
* response unwrapping handles both the native MCP envelope and the REST-direct
  shape
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.client.onboard_helper import (
    is_successful_onboard,
    run_onboard,
    trajectory_required,
    unwrap_tool_response,
)


class FakePoster:
    """Callable that records each call and returns a queued response."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float, token: str | None) -> dict:
        self.calls.append((url, payload))
        if not self._responses:
            return {}
        return self._responses.pop(0)


def _success_response(
    *, uuid: str = "uuid-ok", agent_id: str = "Claude_Code_X",
    session_id: str = "agent-ok", display_name: str = "acme"
) -> dict:
    return {
        "name": "onboard",
        "result": {
            "success": True,
            "uuid": uuid,
            "agent_id": agent_id,
            "display_name": display_name,
            "client_session_id": session_id,
            "continuity_token": "v1.token-ok",
            "session_resolution_source": "explicit_client_session_id_scoped",
            "continuity_token_supported": True,
        },
    }


def _trajectory_required_response() -> dict:
    return {
        "name": "onboard",
        "result": {
            "success": False,
            "error": "Identity 'acme' has an established trajectory.",
            "recovery": {"reason": "trajectory_required"},
            "agent_signature": {"uuid": None},
        },
    }


# --- unwrap_tool_response --------------------------------------------------

class TestUnwrapToolResponse:
    def test_rest_direct_shape(self) -> None:
        raw = {"result": {"uuid": "abc", "success": True}}
        assert unwrap_tool_response(raw) == {"uuid": "abc", "success": True}

    def test_native_mcp_envelope(self) -> None:
        raw = {
            "result": {
                "content": [{"type": "text", "text": json.dumps({"uuid": "abc"})}]
            }
        }
        assert unwrap_tool_response(raw) == {"uuid": "abc"}

    def test_missing_result_uses_top_level(self) -> None:
        assert unwrap_tool_response({"uuid": "abc"}) == {"uuid": "abc"}

    def test_non_dict_returns_empty(self) -> None:
        assert unwrap_tool_response(None) == {}  # type: ignore[arg-type]
        assert unwrap_tool_response("oops") == {}  # type: ignore[arg-type]

    def test_invalid_inner_json_returns_empty(self) -> None:
        raw = {"result": {"content": [{"text": "not-json"}]}}
        assert unwrap_tool_response(raw) == {}


# --- predicates ------------------------------------------------------------

class TestPredicates:
    def test_success_requires_uuid(self) -> None:
        assert is_successful_onboard({"success": True, "uuid": "abc"})
        assert not is_successful_onboard({"success": True})
        assert not is_successful_onboard({"success": False, "uuid": "abc"})

    def test_trajectory_required_detects_recovery_reason(self) -> None:
        parsed = {"success": False, "recovery": {"reason": "trajectory_required"}}
        assert trajectory_required(parsed)

    def test_trajectory_required_only_on_failure(self) -> None:
        assert not trajectory_required({"success": True, "uuid": "abc"})

    def test_trajectory_required_ignores_unknown_reasons(self) -> None:
        parsed = {"success": False, "recovery": {"reason": "something_else"}}
        assert not trajectory_required(parsed)


# --- run_onboard -----------------------------------------------------------

class TestRunOnboard:
    def _call(
        self,
        tmp_path: Path,
        responses: list[dict],
        *,
        initial_cache: dict | None = None,
    ) -> tuple[dict, FakePoster, Path]:
        if initial_cache is not None:
            cache_dir = tmp_path / ".unitares"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "session.json").write_text(json.dumps(initial_cache))
        poster = FakePoster(responses)
        result = run_onboard(
            server_url="http://fake",
            agent_name="acme",
            model_type="claude-code",
            workspace=tmp_path,
            post_json=poster,
        )
        return result, poster, tmp_path / ".unitares" / "session.json"

    def test_success_writes_cache(self, tmp_path: Path) -> None:
        result, poster, cache_path = self._call(tmp_path, [_success_response()])

        assert result["status"] == "ok"
        assert result["used_force_new"] is False
        assert result["uuid"] == "uuid-ok"

        assert len(poster.calls) == 1
        sent_args = poster.calls[0][1]["arguments"]
        assert sent_args["name"] == "acme"
        assert "force_new" not in sent_args

        written = json.loads(cache_path.read_text())
        assert written["uuid"] == "uuid-ok"
        assert written["client_session_id"] == "agent-ok"
        assert written["continuity_token"] == "v1.token-ok"

    def test_cache_continuity_token_passed_on_resume(self, tmp_path: Path) -> None:
        initial = {
            "continuity_token": "v1.cached-token",
            "client_session_id": "agent-cached",
        }
        _, poster, _ = self._call(
            tmp_path, [_success_response()], initial_cache=initial
        )
        sent_args = poster.calls[0][1]["arguments"]
        assert sent_args["continuity_token"] == "v1.cached-token"
        assert "client_session_id" not in sent_args

    def test_cache_session_id_fallback(self, tmp_path: Path) -> None:
        initial = {"continuity_token": "", "client_session_id": "agent-only"}
        _, poster, _ = self._call(
            tmp_path, [_success_response()], initial_cache=initial
        )
        sent_args = poster.calls[0][1]["arguments"]
        assert sent_args["client_session_id"] == "agent-only"
        assert "continuity_token" not in sent_args

    def test_trajectory_required_retries_with_force_new(self, tmp_path: Path) -> None:
        responses = [_trajectory_required_response(), _success_response()]
        result, poster, cache_path = self._call(tmp_path, responses)

        assert result["status"] == "ok"
        assert result["used_force_new"] is True
        assert len(poster.calls) == 2

        retry_args = poster.calls[1][1]["arguments"]
        assert retry_args["force_new"] is True
        assert retry_args["name"] == "acme"

        written = json.loads(cache_path.read_text())
        assert written["uuid"] == "uuid-ok"

    def test_non_trajectory_failure_does_not_retry(self, tmp_path: Path) -> None:
        failure = {
            "name": "onboard",
            "result": {
                "success": False,
                "error": "Something else broke",
                "recovery": {"reason": "database_unreachable"},
            },
        }
        result, poster, cache_path = self._call(tmp_path, [failure])

        assert result["status"] == "onboard_failed"
        assert result["used_force_new"] is False
        assert len(poster.calls) == 1
        assert not cache_path.exists()

    def test_failure_preserves_existing_cache(self, tmp_path: Path) -> None:
        initial = {
            "uuid": "previous-uuid",
            "agent_id": "Prev",
            "client_session_id": "agent-prev",
            "continuity_token": "v1.prev",
        }
        responses = [_trajectory_required_response(), _trajectory_required_response()]
        result, _, cache_path = self._call(
            tmp_path, responses, initial_cache=initial
        )

        assert result["status"] == "onboard_failed"
        preserved = json.loads(cache_path.read_text())
        assert preserved == initial, "cache must not be overwritten on failure"

    def test_server_unreachable_no_cache_write(self, tmp_path: Path) -> None:
        # Poster returns {} to simulate network failure.
        result, _, cache_path = self._call(tmp_path, [{}])

        assert result["status"] == "onboard_failed"
        assert not cache_path.exists()

    def test_success_without_uuid_is_failure(self, tmp_path: Path) -> None:
        # This is the specific bug that caused the prod incident:
        # success field missing, uuid missing, but fields silently extracted.
        weird = {"name": "onboard", "result": {"agent_signature": {"uuid": None}}}
        result, _, cache_path = self._call(tmp_path, [weird])
        assert result["status"] == "onboard_failed"
        assert not cache_path.exists()
