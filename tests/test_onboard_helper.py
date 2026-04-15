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

    def test_trajectory_required_surfaces_error_without_retry(self, tmp_path: Path) -> None:
        """Per 718ccd3: never auto-force_new. Surface the error instead."""
        result, poster, cache_path = self._call(
            tmp_path, [_trajectory_required_response()]
        )

        assert result["status"] == "trajectory_required"
        assert "trajectory" in result["error"].lower()
        assert result["recovery_reason"] == "trajectory_required"
        # Must NOT have retried — only one call
        assert len(poster.calls) == 1
        # Must NOT have written cache
        assert not cache_path.exists()

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
        assert len(poster.calls) == 1
        assert not cache_path.exists()

    def test_failure_preserves_existing_cache(self, tmp_path: Path) -> None:
        initial = {
            "uuid": "previous-uuid",
            "agent_id": "Prev",
            "client_session_id": "agent-prev",
            "continuity_token": "v1.prev",
        }
        responses = [_trajectory_required_response()]
        result, _, cache_path = self._call(
            tmp_path, responses, initial_cache=initial
        )

        assert result["status"] == "trajectory_required"
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

    def test_explicit_force_new_skips_cache_and_sends_flag(self, tmp_path: Path) -> None:
        """force_new=True is only set by explicit operator opt-in (--force-new)."""
        initial = {
            "continuity_token": "v1.cached-token",
            "client_session_id": "agent-cached",
        }
        cache_dir = tmp_path / ".unitares"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "session.json").write_text(json.dumps(initial))

        poster = FakePoster([_success_response()])
        result = run_onboard(
            server_url="http://fake",
            agent_name="acme",
            model_type="claude-code",
            workspace=tmp_path,
            force_new=True,
            post_json=poster,
        )
        assert result["status"] == "ok"
        sent_args = poster.calls[0][1]["arguments"]
        assert sent_args["force_new"] is True
        # When force_new is set, cached token should NOT be sent
        assert "continuity_token" not in sent_args
        assert "client_session_id" not in sent_args


# --- per-process slot isolation --------------------------------------------

class TestSlotIsolation:
    """Slot key (typically Claude Code session_id) isolates parallel processes
    so they don't collide on a single per-workspace cache file. Resolves the
    "multiple Claude agents sharing UUID" symptom flagged 2026-04-14.
    """

    def _call(
        self,
        tmp_path: Path,
        responses: list[dict],
        *,
        slot: str | None,
        initial_files: dict[str, dict] | None = None,
    ) -> tuple[dict, FakePoster, Path]:
        cache_dir = tmp_path / ".unitares"
        if initial_files:
            cache_dir.mkdir(parents=True, exist_ok=True)
            for filename, payload in initial_files.items():
                (cache_dir / filename).write_text(json.dumps(payload))
        poster = FakePoster(responses)
        result = run_onboard(
            server_url="http://fake",
            agent_name="acme",
            model_type="claude-code",
            workspace=tmp_path,
            slot=slot,
            post_json=poster,
        )
        from scripts.client.onboard_helper import _slot_filename
        return result, poster, cache_dir / _slot_filename(slot)

    def test_slot_writes_to_distinct_file(self, tmp_path: Path) -> None:
        result, _, cache_path = self._call(
            tmp_path, [_success_response(uuid="u-A", session_id="agent-A")],
            slot="claude-session-aaa",
        )
        assert result["status"] == "ok"
        assert cache_path.name == "session-claude-session-aaa.json"
        assert cache_path.exists()
        # Default cache file must NOT be touched.
        assert not (tmp_path / ".unitares" / "session.json").exists()

    def test_two_slots_do_not_collide(self, tmp_path: Path) -> None:
        # Process A
        result_a, _, path_a = self._call(
            tmp_path, [_success_response(uuid="u-A", session_id="agent-A")],
            slot="aaa",
        )
        # Process B starts in same workspace, different slot — must not see A's cache
        result_b, poster_b, path_b = self._call(
            tmp_path, [_success_response(uuid="u-B", session_id="agent-B")],
            slot="bbb",
        )
        assert result_a["uuid"] == "u-A"
        assert result_b["uuid"] == "u-B"
        assert path_a != path_b
        # Process B onboarded fresh — it didn't pick up A's continuity token.
        sent_args_b = poster_b.calls[0][1]["arguments"]
        assert "continuity_token" not in sent_args_b
        assert "client_session_id" not in sent_args_b

    def test_slot_falls_back_to_legacy_cache_if_no_slot_file_yet(self, tmp_path: Path) -> None:
        # A pre-existing unslotted cache (from before this change) should still
        # provide continuity to a slotted run on first start. Slotted writes
        # then own that slot going forward.
        legacy = {
            "continuity_token": "v1.legacy-token",
            "client_session_id": "agent-legacy",
        }
        result, poster, cache_path = self._call(
            tmp_path, [_success_response(uuid="u-resumed", session_id="agent-resumed")],
            slot="first-run",
            initial_files={"session.json": legacy},
        )
        assert result["status"] == "ok"
        sent_args = poster.calls[0][1]["arguments"]
        # Resumed via legacy cache
        assert sent_args["continuity_token"] == "v1.legacy-token"
        # New write went to the slotted file, not back to session.json
        assert cache_path.name == "session-first-run.json"
        # Legacy file is untouched
        legacy_path = tmp_path / ".unitares" / "session.json"
        assert legacy_path.exists()
        assert json.loads(legacy_path.read_text()) == legacy

    def test_unsanitized_slot_filename_chars_are_replaced(self, tmp_path: Path) -> None:
        # Slot keys come from external input (Claude Code session_id) — must
        # not allow path traversal via "../" or weird chars.
        from scripts.client.onboard_helper import _slot_filename
        assert _slot_filename("normal-id-123") == "session-normal-id-123.json"
        assert _slot_filename("../../etc/passwd") == "session-______etc_passwd.json"
        assert "/" not in _slot_filename("a/b/c")
        # Cap length so attackers can't fill the disk with a giant filename.
        long = "x" * 500
        assert len(_slot_filename(long)) <= len("session-.json") + 64

    def test_no_slot_uses_legacy_path_unchanged(self, tmp_path: Path) -> None:
        # Backward-compat: when slot is None, the cache path is the original
        # session.json — same as the pre-slotted behavior.
        from scripts.client.onboard_helper import _slot_filename
        assert _slot_filename(None) == "session.json"
        assert _slot_filename("") == "session.json"

