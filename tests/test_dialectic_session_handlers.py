"""
Tests for src/mcp_handlers/dialectic_session.py

Covers:
- _resolve_dialectic_backend()
- _reconstruct_session_from_dict()
- save_session()
- load_session()
- load_all_sessions()
- load_session_as_dict()
- verify_data_consistency()
- run_startup_consolidation()
- list_all_sessions()
"""

import json
import os
import sys
import asyncio
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from unittest.mock import patch, MagicMock, AsyncMock, mock_open

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.dialectic_protocol import (
    DialecticSession,
    DialecticPhase,
    DialecticMessage,
    Resolution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    paused_agent_id: str = "agent_a",
    reviewer_agent_id: str = "agent_b",
    session_type: str = "recovery",
    topic: Optional[str] = None,
    phase: DialecticPhase = DialecticPhase.THESIS,
) -> DialecticSession:
    """Create a DialecticSession for testing."""
    session = DialecticSession(
        paused_agent_id=paused_agent_id,
        reviewer_agent_id=reviewer_agent_id,
        session_type=session_type,
        topic=topic,
    )
    session.phase = phase
    return session


def _make_session_dict(
    session_id: str = "abc123def456",
    paused_agent_id: str = "agent_a",
    reviewer_agent_id: str = "agent_b",
    phase: str = "thesis",
    session_type: str = "recovery",
    topic: Optional[str] = None,
    transcript: Optional[List[Dict]] = None,
    resolution: Optional[Dict] = None,
    created_at: Optional[str] = None,
    synthesis_round: int = 0,
    max_synthesis_rounds: int = 5,
    paused_agent_state: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Create a session dict matching what JSON/DB storage produces."""
    return {
        "session_id": session_id,
        "paused_agent_id": paused_agent_id,
        "reviewer_agent_id": reviewer_agent_id,
        "phase": phase,
        "session_type": session_type,
        "topic": topic,
        "transcript": transcript or [],
        "resolution": resolution,
        "created_at": created_at or datetime.now().isoformat(),
        "synthesis_round": synthesis_round,
        "max_synthesis_rounds": max_synthesis_rounds,
        "paused_agent_state": paused_agent_state or {},
    }


def _make_transcript_entry(
    phase: str = "thesis",
    agent_id: str = "agent_a",
    root_cause: Optional[str] = None,
    reasoning: Optional[str] = None,
    proposed_conditions: Optional[List[str]] = None,
    concerns: Optional[List[str]] = None,
    agrees: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a transcript message dict."""
    return {
        "phase": phase,
        "agent_id": agent_id,
        "timestamp": datetime.now().isoformat(),
        "root_cause": root_cause,
        "reasoning": reasoning,
        "proposed_conditions": proposed_conditions,
        "concerns": concerns,
        "agrees": agrees,
        "observed_metrics": None,
    }


def _make_resolution_dict() -> Dict[str, Any]:
    """Create a resolution dict."""
    return {
        "action": "resume",
        "conditions": ["Reduce complexity", "Monitor for 24h"],
        "root_cause": "Risk threshold exceeded",
        "reasoning": "Both agents agreed",
        "signature_a": "sig_a_hash",
        "signature_b": "sig_b_hash",
        "timestamp": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Tests: _resolve_dialectic_backend
# ---------------------------------------------------------------------------

class TestResolveDialecticBackend:
    """Tests for _resolve_dialectic_backend()."""

    def test_explicit_json_backend(self):
        with patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_BACKEND", "json"):
            from src.mcp_handlers.dialectic_session import _resolve_dialectic_backend
            assert _resolve_dialectic_backend() == "json"

    def test_explicit_postgres_backend(self):
        with patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_BACKEND", "postgres"):
            from src.mcp_handlers.dialectic_session import _resolve_dialectic_backend
            assert _resolve_dialectic_backend() == "postgres"

    def test_auto_backend_defaults_to_postgres(self):
        with patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_BACKEND", "auto"):
            from src.mcp_handlers.dialectic_session import _resolve_dialectic_backend
            assert _resolve_dialectic_backend() == "postgres"

    def test_unknown_backend_defaults_to_postgres(self):
        with patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_BACKEND", "unknown_value"):
            from src.mcp_handlers.dialectic_session import _resolve_dialectic_backend
            assert _resolve_dialectic_backend() == "postgres"


# ---------------------------------------------------------------------------
# Tests: _reconstruct_session_from_dict
# ---------------------------------------------------------------------------

class TestReconstructSessionFromDict:
    """Tests for _reconstruct_session_from_dict()."""

    def test_basic_reconstruction(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        session_id = "test_session_123"
        data = _make_session_dict(session_id=session_id)
        session = _reconstruct_session_from_dict(session_id, data)

        assert session is not None
        assert session.session_id == session_id
        assert session.paused_agent_id == "agent_a"
        assert session.reviewer_agent_id == "agent_b"
        assert session.phase == DialecticPhase.THESIS
        assert session.synthesis_round == 0
        assert session.session_type == "recovery"

    def test_reconstruction_with_transcript(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        transcript = [
            _make_transcript_entry(
                phase="thesis",
                agent_id="agent_a",
                root_cause="Test root cause",
                reasoning="Test reasoning",
                proposed_conditions=["Condition 1", "Condition 2"],
            ),
            _make_transcript_entry(
                phase="antithesis",
                agent_id="agent_b",
                concerns=["Concern 1"],
                reasoning="Counter-reasoning",
            ),
        ]
        data = _make_session_dict(
            phase="synthesis",
            transcript=transcript,
            synthesis_round=1,
        )
        session = _reconstruct_session_from_dict("sess_1", data)

        assert session is not None
        assert len(session.transcript) == 2
        assert session.transcript[0].phase == "thesis"
        assert session.transcript[0].root_cause == "Test root cause"
        assert session.transcript[1].phase == "antithesis"
        assert session.transcript[1].concerns == ["Concern 1"]
        assert session.phase == DialecticPhase.SYNTHESIS
        assert session.synthesis_round == 1

    def test_reconstruction_with_resolution(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        resolution = _make_resolution_dict()
        data = _make_session_dict(
            phase="resolved",
            resolution=resolution,
        )
        session = _reconstruct_session_from_dict("sess_2", data)

        assert session is not None
        assert session.resolution is not None
        assert session.resolution.action == "resume"
        assert len(session.resolution.conditions) == 2
        assert session.resolution.root_cause == "Risk threshold exceeded"
        assert session.phase == DialecticPhase.RESOLVED

    def test_reconstruction_with_no_resolution(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict(phase="thesis", resolution=None)
        session = _reconstruct_session_from_dict("sess_3", data)

        assert session is not None
        assert session.resolution is None

    def test_reconstruction_invalid_phase_defaults_to_thesis(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict(phase="invalid_phase")
        session = _reconstruct_session_from_dict("sess_4", data)

        assert session is not None
        assert session.phase == DialecticPhase.THESIS

    def test_reconstruction_with_string_created_at(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        now = datetime.now()
        data = _make_session_dict(created_at=now.isoformat())
        session = _reconstruct_session_from_dict("sess_5", data)

        assert session is not None
        assert isinstance(session.created_at, datetime)

    def test_reconstruction_with_datetime_created_at(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        now = datetime.now()
        data = _make_session_dict()
        data["created_at"] = now  # datetime object instead of string
        session = _reconstruct_session_from_dict("sess_6", data)

        assert session is not None
        assert session.created_at == now

    def test_reconstruction_with_missing_created_at(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict()
        data["created_at"] = None
        session = _reconstruct_session_from_dict("sess_7", data)

        assert session is not None
        # Should use the DialecticSession default (datetime.now() from constructor)

    def test_reconstruction_exploration_session_timeouts(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict(session_type="exploration", topic="Test exploration")
        session = _reconstruct_session_from_dict("sess_8", data)

        assert session is not None
        assert session.session_type == "exploration"
        assert session.topic == "Test exploration"
        assert session._max_antithesis_wait == timedelta(hours=24)
        assert session._max_synthesis_wait == timedelta(hours=6)
        assert session._max_total_time == timedelta(hours=72)

    def test_reconstruction_recovery_session_timeouts(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict(session_type="recovery")
        session = _reconstruct_session_from_dict("sess_9", data)

        assert session is not None
        assert session._max_antithesis_wait == DialecticSession.MAX_ANTITHESIS_WAIT
        assert session._max_synthesis_wait == DialecticSession.MAX_SYNTHESIS_WAIT
        assert session._max_total_time == DialecticSession.MAX_TOTAL_TIME

    def test_reconstruction_with_messages_key_instead_of_transcript(self):
        """SQLite backend uses 'messages' key instead of 'transcript'."""
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        messages = [
            {
                "message_type": "thesis",
                "agent_id": "agent_a",
                "timestamp": datetime.now().isoformat(),
                "root_cause": "Test cause",
                "reasoning": "Test reasoning",
            }
        ]
        data = _make_session_dict()
        del data["transcript"]
        data["messages"] = messages
        session = _reconstruct_session_from_dict("sess_10", data)

        assert session is not None
        assert len(session.transcript) == 1
        assert session.transcript[0].phase == "thesis"

    def test_reconstruction_with_none_optional_fields(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        data = _make_session_dict()
        data["paused_agent_state"] = None
        data["session_type"] = None
        data["max_synthesis_rounds"] = None
        data["synthesis_round"] = None
        session = _reconstruct_session_from_dict("sess_11", data)

        assert session is not None
        assert session.paused_agent_state == {}
        assert session.session_type == "recovery"
        assert session.max_synthesis_rounds == 5
        assert session.synthesis_round == 0

    def test_reconstruction_error_returns_none(self):
        """Reconstruction should return None if an error occurs internally."""
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        # Provide data that causes an internal error (e.g., resolution with bad structure)
        data = _make_session_dict()
        data["resolution"] = "not_a_dict"  # This should cause an error in Resolution()
        session = _reconstruct_session_from_dict("sess_err", data)

        assert session is None

    def test_reconstruction_with_all_phases(self):
        from src.mcp_handlers.dialectic_session import _reconstruct_session_from_dict

        for phase_value in ["thesis", "antithesis", "synthesis", "resolved", "escalated", "failed"]:
            data = _make_session_dict(phase=phase_value)
            session = _reconstruct_session_from_dict(f"sess_{phase_value}", data)
            assert session is not None
            assert session.phase == DialecticPhase(phase_value)


# ---------------------------------------------------------------------------
# Tests: save_session
# ---------------------------------------------------------------------------

class TestSaveSession:
    """Tests for save_session()."""

    @pytest.mark.asyncio
    async def test_save_session_writes_json(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session()
        storage_dir = tmp_path / "dialectic_sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        session_file = storage_dir / f"{session.session_id}.json"
        assert session_file.exists()

        with open(session_file, "r") as f:
            data = json.load(f)

        assert data["session_id"] == session.session_id
        assert data["paused_agent_id"] == "agent_a"
        assert data["reviewer_agent_id"] == "agent_b"

    @pytest.mark.asyncio
    async def test_save_session_skips_when_snapshots_disabled(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session()
        storage_dir = tmp_path / "dialectic_sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", False):
            await save_session(session)

        assert not storage_dir.exists() or not list(storage_dir.glob("*.json"))

    @pytest.mark.asyncio
    async def test_save_session_creates_directory(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session()
        storage_dir = tmp_path / "deep" / "nested" / "path"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        assert storage_dir.exists()

    @pytest.mark.asyncio
    async def test_save_session_file_not_empty(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session()
        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        session_file = storage_dir / f"{session.session_id}.json"
        assert session_file.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_save_session_with_transcript(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session(phase=DialecticPhase.ANTITHESIS)
        thesis = DialecticMessage(
            phase="thesis",
            agent_id="agent_a",
            timestamp=datetime.now().isoformat(),
            root_cause="Test root cause",
            proposed_conditions=["Cond 1"],
            reasoning="Test reasoning",
        )
        session.transcript.append(thesis)

        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        session_file = storage_dir / f"{session.session_id}.json"
        with open(session_file, "r") as f:
            data = json.load(f)

        assert len(data["transcript"]) == 1
        assert data["transcript"][0]["phase"] == "thesis"
        assert data["transcript"][0]["root_cause"] == "Test root cause"

    @pytest.mark.asyncio
    async def test_save_session_error_propagates(self, tmp_path):
        """When the underlying write fails, save_session should re-raise."""
        from src.mcp_handlers.dialectic_session import save_session

        session = _make_session()
        # Use a non-writable path
        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            # Patch the executor to raise
            with patch("asyncio.get_running_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=IOError("Disk full")
                )
                with pytest.raises(IOError, match="Disk full"):
                    await save_session(session)


# ---------------------------------------------------------------------------
# Tests: load_session
# ---------------------------------------------------------------------------

class TestLoadSession:
    """Tests for load_session()."""

    @pytest.mark.asyncio
    async def test_load_session_from_json(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session, load_session

        session = _make_session()
        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            await save_session(session)
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert loaded.paused_agent_id == "agent_a"

    @pytest.mark.asyncio
    async def test_load_session_nonexistent_returns_none(self, tmp_path):
        from src.mcp_handlers.dialectic_session import load_session

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            loaded = await load_session("nonexistent_session_id")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_session_from_postgres_backend(self):
        from src.mcp_handlers.dialectic_session import load_session

        session_data = _make_session_dict(session_id="pg_session_1")
        session_data["messages"] = [
            _make_transcript_entry(phase="thesis", agent_id="agent_a")
        ]

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=session_data):
            loaded = await load_session("pg_session_1")

        assert loaded is not None
        assert loaded.session_id == "pg_session_1"

    @pytest.mark.asyncio
    async def test_load_session_postgres_normalizes_messages_key(self):
        """Postgres returns 'messages' key which should be normalized to 'transcript'."""
        from src.mcp_handlers.dialectic_session import load_session

        session_data = _make_session_dict(session_id="pg_norm_1")
        # Replace transcript with messages (as postgres does)
        msgs = session_data.pop("transcript")
        session_data["messages"] = [
            _make_transcript_entry(phase="thesis", agent_id="agent_a")
        ]

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=session_data):
            loaded = await load_session("pg_norm_1")

        assert loaded is not None
        assert len(loaded.transcript) == 1

    @pytest.mark.asyncio
    async def test_load_session_postgres_failure_falls_back_to_json(self, tmp_path):
        """When Postgres fails, load_session falls back to JSON files."""
        from src.mcp_handlers.dialectic_session import load_session, save_session

        session = _make_session()
        storage_dir = tmp_path / "sessions"

        # First save to JSON
        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        # Then try to load with postgres failing
        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, side_effect=Exception("DB down")):
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_load_session_postgres_returns_none_falls_back_to_json(self, tmp_path):
        """When Postgres returns None for a session, fall back to JSON."""
        from src.mcp_handlers.dialectic_session import load_session, save_session

        session = _make_session()
        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(session)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=None):
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_load_session_corrupt_json_returns_none(self, tmp_path):
        from src.mcp_handlers.dialectic_session import load_session

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)
        session_file = storage_dir / "corrupt_sess.json"
        session_file.write_text("{invalid json")

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            loaded = await load_session("corrupt_sess")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_session_sets_defaults_from_postgres(self):
        """Test that load_session properly sets defaults for postgres data."""
        from src.mcp_handlers.dialectic_session import load_session

        session_data = {
            "session_id": "pg_defaults_1",
            "paused_agent_id": "agent_a",
            "reviewer_agent_id": "agent_b",
            "phase": "thesis",
            "messages": [],
            "created_at": datetime.now().isoformat(),
        }
        # Deliberately omit session_type, max_synthesis_rounds, synthesis_round

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=session_data):
            loaded = await load_session("pg_defaults_1")

        assert loaded is not None
        assert loaded.session_type == "recovery"
        assert loaded.max_synthesis_rounds == 5
        assert loaded.synthesis_round == 0


# ---------------------------------------------------------------------------
# Tests: load_all_sessions
# ---------------------------------------------------------------------------

class TestLoadAllSessions:
    """Tests for load_all_sessions()."""

    @pytest.mark.asyncio
    async def test_load_all_sessions_from_json(self, tmp_path):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            save_session,
            ACTIVE_SESSIONS,
        )

        storage_dir = tmp_path / "sessions"

        # Create two active sessions
        s1 = _make_session(phase=DialecticPhase.THESIS)
        s2 = _make_session(paused_agent_id="agent_c", phase=DialecticPhase.ANTITHESIS)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(s1)
            await save_session(s2)

        # Clear active sessions
        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
                 patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
                count = await load_all_sessions()

            assert count == 2
            assert s1.session_id in ACTIVE_SESSIONS
            assert s2.session_id in ACTIVE_SESSIONS
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_skips_resolved(self, tmp_path):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            save_session,
            ACTIVE_SESSIONS,
        )

        storage_dir = tmp_path / "sessions"

        # Create one active and one resolved session
        active_session = _make_session(phase=DialecticPhase.THESIS)
        resolved_session = _make_session(
            paused_agent_id="agent_c",
            phase=DialecticPhase.RESOLVED,
        )

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True):
            await save_session(active_session)
            await save_session(resolved_session)

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
                 patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
                count = await load_all_sessions()

            assert count == 1
            assert active_session.session_id in ACTIVE_SESSIONS
            assert resolved_session.session_id not in ACTIVE_SESSIONS
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_from_postgres(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        active_session_data = [
            {"session_id": "pg_sess_1", "phase": "thesis"},
            {"session_id": "pg_sess_2", "phase": "antithesis"},
        ]

        full_session_1 = _make_session_dict(session_id="pg_sess_1", phase="thesis")
        full_session_2 = _make_session_dict(session_id="pg_sess_2", phase="antithesis")

        async def mock_pg_get_session(session_id):
            if session_id == "pg_sess_1":
                return full_session_1
            elif session_id == "pg_sess_2":
                return full_session_2
            return None

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_active_sessions", new_callable=AsyncMock, return_value=active_session_data), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_session", side_effect=mock_pg_get_session):
                count = await load_all_sessions()

            assert count == 2
            assert "pg_sess_1" in ACTIVE_SESSIONS
            assert "pg_sess_2" in ACTIVE_SESSIONS
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_skips_already_loaded(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        existing_session = _make_session(phase=DialecticPhase.THESIS)
        existing_session.session_id = "already_loaded"

        active_session_data = [
            {"session_id": "already_loaded", "phase": "thesis"},
            {"session_id": "new_sess", "phase": "thesis"},
        ]
        full_new = _make_session_dict(session_id="new_sess", phase="thesis")

        async def mock_pg_get_session(session_id):
            if session_id == "new_sess":
                return full_new
            return None

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()
        ACTIVE_SESSIONS["already_loaded"] = existing_session

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_active_sessions", new_callable=AsyncMock, return_value=active_session_data), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_session", side_effect=mock_pg_get_session):
                count = await load_all_sessions()

            assert count == 1  # Only new_sess loaded, already_loaded skipped
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_postgres_skips_resolved(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        active_session_data = [
            {"session_id": "resolved_sess", "phase": "resolved"},
        ]
        full_resolved = _make_session_dict(session_id="resolved_sess", phase="resolved")

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_active_sessions", new_callable=AsyncMock, return_value=active_session_data), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=full_resolved):
                count = await load_all_sessions()

            assert count == 0
            assert "resolved_sess" not in ACTIVE_SESSIONS
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_empty_directory(self, tmp_path):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        storage_dir = tmp_path / "empty_sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
                 patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
                count = await load_all_sessions()

            assert count == 0
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_postgres_no_session_id_skipped(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        active_session_data = [
            {"session_id": None},  # no session_id
            {"phase": "thesis"},  # missing session_id key
        ]

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_active_sessions", new_callable=AsyncMock, return_value=active_session_data):
                count = await load_all_sessions()

            assert count == 0
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_postgres_get_session_returns_none_skipped(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        active_session_data = [
            {"session_id": "ghost_sess"},
        ]

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_active_sessions", new_callable=AsyncMock, return_value=active_session_data), \
                 patch("src.mcp_handlers.dialectic_session.pg_get_session", new_callable=AsyncMock, return_value=None):
                count = await load_all_sessions()

            assert count == 0
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)

    @pytest.mark.asyncio
    async def test_load_all_sessions_io_error_returns_zero(self):
        from src.mcp_handlers.dialectic_session import (
            load_all_sessions,
            ACTIVE_SESSIONS,
        )

        original_sessions = dict(ACTIVE_SESSIONS)
        ACTIVE_SESSIONS.clear()

        try:
            with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"), \
                 patch("asyncio.get_running_loop") as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    side_effect=IOError("Permission denied")
                )
                count = await load_all_sessions()

            assert count == 0
        finally:
            ACTIVE_SESSIONS.clear()
            ACTIVE_SESSIONS.update(original_sessions)


# ---------------------------------------------------------------------------
# Tests: load_session_as_dict
# ---------------------------------------------------------------------------

class TestLoadSessionAsDict:
    """Tests for load_session_as_dict()."""

    @pytest.mark.asyncio
    async def test_returns_none_for_json_backend(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            result = await load_session_as_dict("any_session")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_session_dict_from_postgres(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        now = datetime.now()

        mock_session_row = {
            "session_id": "fast_sess_1",
            "phase": "thesis",
            "status": "active",
            "session_type": "recovery",
            "paused_agent_id": "agent_a",
            "reviewer_agent_id": "agent_b",
            "topic": "Test topic",
            "created_at": now,
            "resolution_json": None,
        }

        mock_msg_rows = [
            {
                "message_type": "thesis",
                "agent_id": "agent_a",
                "timestamp": now,
                "reasoning": "Test reasoning",
                "root_cause": "Test cause",
                "proposed_conditions": json.dumps(["Cond 1"]),
                "concerns": None,
                "agrees": None,
            }
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_session_row)
        mock_conn.fetch = AsyncMock(return_value=mock_msg_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await load_session_as_dict("fast_sess_1")

        assert result is not None
        assert result["session_id"] == "fast_sess_1"
        assert result["phase"] == "thesis"
        assert result["paused_agent"] == "agent_a"
        assert result["reviewer"] == "agent_b"
        assert result["topic"] == "Test topic"
        assert result["message_count"] == 1
        assert len(result["transcript"]) == 1
        assert result["transcript"][0]["phase"] == "thesis"
        assert result["transcript"][0]["proposed_conditions"] == ["Cond 1"]

    @pytest.mark.asyncio
    async def test_returns_none_when_session_not_found_in_postgres(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await load_session_as_dict("nonexistent_sess")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB error")):
            result = await load_session_as_dict("error_sess")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_resolution_json_string(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        now = datetime.now()
        resolution = _make_resolution_dict()

        mock_session_row = {
            "session_id": "res_str_sess",
            "phase": "resolved",
            "status": "resolved",
            "session_type": "recovery",
            "paused_agent_id": "agent_a",
            "reviewer_agent_id": "agent_b",
            "topic": None,
            "created_at": now,
            "resolution_json": json.dumps(resolution),  # String, not dict
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_session_row)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await load_session_as_dict("res_str_sess")

        assert result is not None
        assert "resolution" in result
        assert result["resolution"]["action"] == "resume"

    @pytest.mark.asyncio
    async def test_handles_resolution_json_dict(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        now = datetime.now()
        resolution = _make_resolution_dict()

        mock_session_row = {
            "session_id": "res_dict_sess",
            "phase": "resolved",
            "status": "resolved",
            "session_type": "recovery",
            "paused_agent_id": "agent_a",
            "reviewer_agent_id": "agent_b",
            "topic": None,
            "created_at": now,
            "resolution_json": resolution,  # Already a dict
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_session_row)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await load_session_as_dict("res_dict_sess")

        assert result is not None
        assert "resolution" in result
        assert result["resolution"]["action"] == "resume"

    @pytest.mark.asyncio
    async def test_handles_agrees_field(self):
        from src.mcp_handlers.dialectic_session import load_session_as_dict

        now = datetime.now()

        mock_session_row = {
            "session_id": "agrees_sess",
            "phase": "synthesis",
            "status": "active",
            "session_type": "recovery",
            "paused_agent_id": "agent_a",
            "reviewer_agent_id": "agent_b",
            "topic": None,
            "created_at": now,
            "resolution_json": None,
        }

        mock_msg_rows = [
            {
                "message_type": "synthesis",
                "agent_id": "agent_a",
                "timestamp": now,
                "reasoning": "I agree",
                "root_cause": None,
                "proposed_conditions": None,
                "concerns": json.dumps(["Some concern"]),
                "agrees": True,
            }
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_session_row)
        mock_conn.fetch = AsyncMock(return_value=mock_msg_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="postgres"), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await load_session_as_dict("agrees_sess")

        assert result is not None
        assert result["transcript"][0]["agrees"] is True
        assert result["transcript"][0]["concerns"] == ["Some concern"]


# ---------------------------------------------------------------------------
# Tests: verify_data_consistency
# ---------------------------------------------------------------------------

class TestVerifyDataConsistency:
    """Tests for verify_data_consistency() (now a no-op since SQLite removed)."""

    @pytest.mark.asyncio
    async def test_consistency_returns_true(self):
        from src.mcp_handlers.dialectic_session import verify_data_consistency
        result = await verify_data_consistency()
        assert result["consistent"] is True


class TestRunStartupConsolidation:
    """Tests for run_startup_consolidation() (now a no-op since SQLite removed)."""

    @pytest.mark.asyncio
    async def test_consolidation_returns_zero(self):
        from src.mcp_handlers.dialectic_session import run_startup_consolidation
        result = await run_startup_consolidation()
        assert result["exported"] == 0


# ---------------------------------------------------------------------------
# Tests: list_all_sessions
# ---------------------------------------------------------------------------

class TestListAllSessions:
    """Tests for list_all_sessions()."""

    @pytest.mark.asyncio
    async def test_list_sessions_from_json_fallback(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Create JSON session files
        for i in range(3):
            data = _make_session_dict(
                session_id=f"list_sess_{i}",
                paused_agent_id=f"agent_{i}",
            )
            with open(storage_dir / f"list_sess_{i}.json", "w") as f:
                json.dump(data, f)

        # Simulate postgres failure to trigger JSON fallback
        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_with_agent_filter(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Create sessions with different agents
        data1 = _make_session_dict(session_id="filter_1", paused_agent_id="target_agent")
        data2 = _make_session_dict(session_id="filter_2", paused_agent_id="other_agent")
        data3 = _make_session_dict(session_id="filter_3", reviewer_agent_id="target_agent")

        for sid, data in [("filter_1", data1), ("filter_2", data2), ("filter_3", data3)]:
            with open(storage_dir / f"{sid}.json", "w") as f:
                json.dump(data, f)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions(agent_id="target_agent")

        assert len(result) == 2
        session_ids = [s["session_id"] for s in result]
        assert "filter_1" in session_ids
        assert "filter_3" in session_ids
        assert "filter_2" not in session_ids

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_with_status_filter(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        data1 = _make_session_dict(session_id="status_1", phase="thesis")
        data2 = _make_session_dict(session_id="status_2", phase="resolved")
        data3 = _make_session_dict(session_id="status_3", phase="thesis")

        for sid, data in [("status_1", data1), ("status_2", data2), ("status_3", data3)]:
            with open(storage_dir / f"{sid}.json", "w") as f:
                json.dump(data, f)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions(status="resolved")

        assert len(result) == 1
        assert result[0]["session_id"] == "status_2"

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_with_limit(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Create 5 sessions
        for i in range(5):
            data = _make_session_dict(session_id=f"limit_sess_{i}")
            with open(storage_dir / f"limit_sess_{i}.json", "w") as f:
                json.dump(data, f)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions(limit=2)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_with_transcript(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        transcript = [_make_transcript_entry()]
        data = _make_session_dict(session_id="transcript_sess", transcript=transcript)
        with open(storage_dir / "transcript_sess.json", "w") as f:
            json.dump(data, f)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions(include_transcript=True)

        assert len(result) == 1
        assert "transcript" in result[0]
        assert len(result[0]["transcript"]) == 1

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_without_transcript(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        transcript = [_make_transcript_entry()]
        data = _make_session_dict(session_id="no_transcript_sess", transcript=transcript)
        with open(storage_dir / "no_transcript_sess.json", "w") as f:
            json.dump(data, f)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions(include_transcript=False)

        assert len(result) == 1
        assert "transcript" not in result[0]

    @pytest.mark.asyncio
    async def test_list_sessions_from_postgres(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()

        mock_rows = [
            {
                "session_id": "pg_list_1",
                "phase": "thesis",
                "status": "active",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": "Test topic",
                "created_at": now,
                "resolution_json": None,
                "message_count": 2,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions()

        assert len(result) == 1
        assert result[0]["session_id"] == "pg_list_1"
        assert result[0]["phase"] == "thesis"
        assert result[0]["message_count"] == 2

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_with_resolution_string(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()
        resolution = _make_resolution_dict()

        mock_rows = [
            {
                "session_id": "pg_res_str",
                "phase": "resolved",
                "status": "resolved",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": now,
                "resolution_json": json.dumps(resolution),  # String
                "message_count": 3,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions()

        assert len(result) == 1
        assert "resolution" in result[0]
        assert result[0]["resolution"]["action"] == "resume"

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_with_resolution_dict(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()
        resolution = _make_resolution_dict()

        mock_rows = [
            {
                "session_id": "pg_res_dict",
                "phase": "resolved",
                "status": "resolved",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": now,
                "resolution_json": resolution,  # Already a dict
                "message_count": 3,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions()

        assert len(result) == 1
        assert "resolution" in result[0]
        assert result[0]["resolution"]["action"] == "resume"

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_with_agent_filter(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()

        mock_rows = [
            {
                "session_id": "pg_filter_1",
                "phase": "thesis",
                "status": "active",
                "session_type": "recovery",
                "paused_agent_id": "target_agent",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": now,
                "resolution_json": None,
                "message_count": 1,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions(agent_id="target_agent")

        assert len(result) == 1
        # Verify the query was called with agent_id params
        call_args = mock_conn.fetch.call_args
        assert "target_agent" in call_args[0]

    @pytest.mark.asyncio
    async def test_list_sessions_empty_json_fallback(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "empty_sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_json_fallback_corrupt_file_skipped(self, tmp_path):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        storage_dir = tmp_path / "sessions"
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Create one valid and one corrupt file
        valid_data = _make_session_dict(session_id="valid_1")
        with open(storage_dir / "valid_1.json", "w") as f:
            json.dump(valid_data, f)
        with open(storage_dir / "corrupt_1.json", "w") as f:
            f.write("{broken json")

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, side_effect=Exception("DB down")):
            result = await list_all_sessions()

        assert len(result) == 1
        assert result[0]["session_id"] == "valid_1"

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_with_include_transcript(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()

        mock_session_rows = [
            {
                "session_id": "pg_transcript_1",
                "phase": "synthesis",
                "status": "active",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": now,
                "resolution_json": None,
                "message_count": 2,
            },
        ]

        mock_msg_rows = [
            {
                "message_type": "thesis",
                "agent_id": "agent_a",
                "timestamp": now,
                "reasoning": "Thesis reasoning",
                "root_cause": "Root cause",
                "proposed_conditions": json.dumps(["Cond 1"]),
                "observed_metrics": None,
                "concerns": None,
                "agrees": None,
            },
            {
                "message_type": "antithesis",
                "agent_id": "agent_b",
                "timestamp": now,
                "reasoning": "Antithesis reasoning",
                "root_cause": None,
                "proposed_conditions": None,
                "observed_metrics": None,
                "concerns": json.dumps(["Concern 1"]),
                "agrees": None,
            },
        ]

        mock_conn = AsyncMock()
        # First call returns session rows, second call returns message rows
        mock_conn.fetch = AsyncMock(side_effect=[mock_session_rows, mock_msg_rows])

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions(include_transcript=True)

        assert len(result) == 1
        assert "transcript" in result[0]
        assert len(result[0]["transcript"]) == 2
        assert result[0]["transcript"][0]["phase"] == "thesis"
        assert result[0]["transcript"][0]["proposed_conditions"] == ["Cond 1"]
        assert result[0]["transcript"][1]["concerns"] == ["Concern 1"]

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_null_created_at(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        mock_rows = [
            {
                "session_id": "pg_null_created",
                "phase": "thesis",
                "status": "active",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": None,
                "resolution_json": None,
                "message_count": 0,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions()

        assert len(result) == 1
        assert result[0]["created"] == ""

    @pytest.mark.asyncio
    async def test_list_sessions_postgres_status_filter(self):
        from src.mcp_handlers.dialectic_session import list_all_sessions

        now = datetime.now()

        mock_rows = [
            {
                "session_id": "pg_status_1",
                "phase": "resolved",
                "status": "resolved",
                "session_type": "recovery",
                "paused_agent_id": "agent_a",
                "reviewer_agent_id": "agent_b",
                "topic": None,
                "created_at": now,
                "resolution_json": None,
                "message_count": 3,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db._pool = mock_pool
        mock_db._ensure_pool = AsyncMock()

        with patch("src.dialectic_db.get_dialectic_db", new_callable=AsyncMock, return_value=mock_db):
            result = await list_all_sessions(status="resolved")

        assert len(result) == 1
        # Verify status filter was included in query
        call_args = mock_conn.fetch.call_args
        assert "%resolved%" in call_args[0]


# ---------------------------------------------------------------------------
# Tests: ACTIVE_SESSIONS module-level state
# ---------------------------------------------------------------------------

class TestActiveSessionsState:
    """Tests for ACTIVE_SESSIONS module-level dict management."""

    def test_active_sessions_is_dict(self):
        from src.mcp_handlers.dialectic_session import ACTIVE_SESSIONS
        assert isinstance(ACTIVE_SESSIONS, dict)

    def test_session_metadata_cache_is_dict(self):
        from src.mcp_handlers.dialectic_session import _SESSION_METADATA_CACHE
        assert isinstance(_SESSION_METADATA_CACHE, dict)

    def test_cache_ttl_is_positive(self):
        from src.mcp_handlers.dialectic_session import _CACHE_TTL
        assert _CACHE_TTL > 0


# ---------------------------------------------------------------------------
# Tests: Module-level constant resolution
# ---------------------------------------------------------------------------

class TestModuleLevelConstants:
    """Tests for module-level constants and their defaults."""

    def test_session_storage_dir_is_path(self):
        from src.mcp_handlers.dialectic_session import SESSION_STORAGE_DIR
        assert isinstance(SESSION_STORAGE_DIR, Path)

    def test_backend_env_var_default(self):
        """The UNITARES_DIALECTIC_BACKEND variable should have a valid value."""
        from src.mcp_handlers.dialectic_session import UNITARES_DIALECTIC_BACKEND
        assert isinstance(UNITARES_DIALECTIC_BACKEND, str)

    def test_write_json_snapshot_is_bool(self):
        from src.mcp_handlers.dialectic_session import UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT
        assert isinstance(UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT, bool)


# ---------------------------------------------------------------------------
# Tests: Round-trip (save then load)
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip:
    """End-to-end tests: save a session, then load it back."""

    @pytest.mark.asyncio
    async def test_round_trip_basic(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session, load_session

        session = _make_session()
        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            await save_session(session)
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.session_id == session.session_id
        assert loaded.paused_agent_id == session.paused_agent_id
        assert loaded.reviewer_agent_id == session.reviewer_agent_id
        assert loaded.phase == session.phase
        assert loaded.session_type == session.session_type

    @pytest.mark.asyncio
    async def test_round_trip_with_full_transcript(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session, load_session

        session = _make_session(phase=DialecticPhase.SYNTHESIS)
        thesis = DialecticMessage(
            phase="thesis",
            agent_id="agent_a",
            timestamp=datetime.now().isoformat(),
            root_cause="Risk threshold exceeded",
            proposed_conditions=["Reduce complexity", "Monitor 24h"],
            reasoning="I believe the issue was high complexity",
        )
        antithesis = DialecticMessage(
            phase="antithesis",
            agent_id="agent_b",
            timestamp=datetime.now().isoformat(),
            observed_metrics={"risk_score": 0.75, "coherence": 0.35},
            concerns=["High risk", "Low coherence"],
            reasoning="I observe elevated risk metrics",
        )
        session.transcript = [thesis, antithesis]
        session.synthesis_round = 1

        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            await save_session(session)
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert len(loaded.transcript) == 2
        assert loaded.transcript[0].phase == "thesis"
        assert loaded.transcript[0].root_cause == "Risk threshold exceeded"
        assert loaded.transcript[1].phase == "antithesis"
        assert loaded.transcript[1].concerns == ["High risk", "Low coherence"]
        assert loaded.synthesis_round == 1

    @pytest.mark.asyncio
    async def test_round_trip_exploration_session(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session, load_session

        session = _make_session(
            session_type="exploration",
            topic="Exploring collaborative debugging",
        )

        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            await save_session(session)
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.session_type == "exploration"
        assert loaded.topic == "Exploring collaborative debugging"
        assert loaded._max_antithesis_wait == timedelta(hours=24)

    @pytest.mark.asyncio
    async def test_round_trip_with_resolution(self, tmp_path):
        from src.mcp_handlers.dialectic_session import save_session, load_session

        session = _make_session(phase=DialecticPhase.RESOLVED)
        session.resolution = Resolution(
            action="resume",
            conditions=["Reduce complexity to 0.3", "Monitor for 24h"],
            root_cause="Risk threshold exceeded",
            reasoning="Both agents agreed on conditions",
            signature_a="hash_a",
            signature_b="hash_b",
            timestamp=datetime.now().isoformat(),
        )

        storage_dir = tmp_path / "sessions"

        with patch("src.mcp_handlers.dialectic_session.SESSION_STORAGE_DIR", storage_dir), \
             patch("src.mcp_handlers.dialectic_session.UNITARES_DIALECTIC_WRITE_JSON_SNAPSHOT", True), \
             patch("src.mcp_handlers.dialectic_session._resolve_dialectic_backend", return_value="json"):
            await save_session(session)
            loaded = await load_session(session.session_id)

        assert loaded is not None
        assert loaded.phase == DialecticPhase.RESOLVED
        assert loaded.resolution is not None
        assert loaded.resolution.action == "resume"
        assert loaded.resolution.conditions == ["Reduce complexity to 0.3", "Monitor for 24h"]
        assert loaded.resolution.signature_a == "hash_a"
        assert loaded.resolution.signature_b == "hash_b"
