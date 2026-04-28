import pytest

from scripts.ops import identity_damage_control as dc


class FakeConn:
    def __init__(self):
        self.ids = []
        self.snapshots = {}
        self.executed = []
        self.session_result = "UPDATE 0"

    async def fetch(self, query, *args):
        prefix = args[0].removesuffix("%")
        return [{"id": agent_id} for agent_id in self.ids if agent_id.startswith(prefix)]

    async def fetchrow(self, query, *args):
        return self.snapshots.get(args[0])

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "UPDATE core.sessions" in query:
            return self.session_result
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_resolve_agent_hint_requires_unique_prefix():
    conn = FakeConn()
    conn.ids = [
        "366a5c42-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "366a5c42-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]

    with pytest.raises(dc.ResolutionError, match="ambiguous prefix"):
        await dc.resolve_agent_hint(conn, "366a5c42")


@pytest.mark.asyncio
async def test_restore_label_dry_run_does_not_write():
    conn = FakeConn()
    agent_id = "f92dcea8-0000-0000-0000-000000000000"
    conn.snapshots[agent_id] = {
        "agent_id": agent_id,
        "label": "Mnemos_f92dcea8",
        "agent_status": "active",
        "identity_status": "active",
        "tags": ["persistent"],
        "has_substrate_claim": True,
    }

    result = await dc.restore_label(
        conn,
        agent_id=agent_id,
        label="Sentinel",
        reason="incident",
        apply=False,
    )

    assert result["before_label"] == "Mnemos_f92dcea8"
    assert result["after_label"] == "Sentinel"
    assert conn.executed == []


@pytest.mark.asyncio
async def test_archive_agent_refuses_resident_by_default():
    conn = FakeConn()
    agent_id = "f92dcea8-0000-0000-0000-000000000000"
    conn.snapshots[agent_id] = {
        "agent_id": agent_id,
        "label": "Sentinel",
        "agent_status": "active",
        "identity_status": "active",
        "tags": ["persistent"],
        "has_substrate_claim": True,
    }

    with pytest.raises(dc.ResolutionError, match="refuses to archive"):
        await dc.archive_agent(
            conn,
            agent_id=agent_id,
            reason="incident",
            apply=True,
            allow_resident_archive=False,
        )

    assert conn.executed == []


@pytest.mark.asyncio
async def test_archive_agent_applies_agent_identity_and_session_updates():
    conn = FakeConn()
    conn.session_result = "UPDATE 3"
    agent_id = "366a5c42-0000-0000-0000-000000000000"
    conn.snapshots[agent_id] = {
        "agent_id": agent_id,
        "label": "orphan",
        "agent_status": "active",
        "identity_status": "active",
        "tags": ["ephemeral"],
        "has_substrate_claim": False,
    }

    result = await dc.archive_agent(
        conn,
        agent_id=agent_id,
        reason="Hermes incident",
        apply=True,
        allow_resident_archive=False,
    )

    assert result["sessions_deactivated"] == 3
    assert len(conn.executed) == 3
    assert "UPDATE core.agents" in conn.executed[0][0]
    assert "UPDATE core.identities" in conn.executed[1][0]
    assert "UPDATE core.sessions" in conn.executed[2][0]


def test_main_reports_unexpected_errors_without_traceback(monkeypatch, capsys):
    async def boom(args):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(dc, "_run", boom)
    monkeypatch.setattr(
        "sys.argv",
        ["identity_damage_control.py", "--archive", "366a5c42"],
    )

    assert dc.main() == 1
    captured = capsys.readouterr()
    assert "database unavailable" in captured.err
    assert "Traceback" not in captured.err
