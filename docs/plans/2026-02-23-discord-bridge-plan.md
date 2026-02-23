# UNITARES Discord Bridge — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Discord bot that surfaces UNITARES governance events, agent presence, Lumen's physical state, and human-in-the-loop governance as a living Discord server.

**Architecture:** Standalone Python repo (`unitares-discord-bridge`) that polls governance-mcp (`/api/events`, tool calls) and anima-mcp (`/state`, `/gallery`) via HTTP, then forwards formatted embeds to Discord channels. Local SQLite cache tracks cursors and channel mappings. The bridge is read-heavy, write-light — it never modifies governance state unprompted.

**Tech Stack:** Python 3.12+, discord.py 2.x, httpx (async HTTP), aiosqlite, pytest

**Design Doc:** `docs/plans/2026-02-23-discord-bridge-design.md`

---

## Phase 0: Upstream Prerequisite

### Task 0.1: Add Event IDs and `?since=` to governance-mcp `/api/events`

The event detector's ring buffer has no stable IDs. The bridge needs to resume from where it left off after restarts.

**Files:**
- Modify: `/Users/cirwel/projects/governance-mcp-v1/src/event_detector.py`
- Modify: `/Users/cirwel/projects/governance-mcp-v1/src/mcp_server.py` (lines ~2334-2362)
- Create: `/Users/cirwel/projects/governance-mcp-v1/tests/test_event_cursor.py`

**Step 1: Write the failing test**

```python
# tests/test_event_cursor.py
import pytest
from src.event_detector import GovernanceEventDetector


def test_events_have_sequential_ids():
    detector = GovernanceEventDetector()
    # Simulate adding events
    detector._recent_events.append({
        "type": "agent_new",
        "severity": "info",
        "message": "test",
        "agent_id": "a1",
        "agent_name": "test",
        "timestamp": "2026-02-23T00:00:00Z"
    })
    detector._recent_events.append({
        "type": "agent_idle",
        "severity": "warning",
        "message": "test2",
        "agent_id": "a2",
        "agent_name": "test2",
        "timestamp": "2026-02-23T00:01:00Z"
    })
    events = detector.get_recent_events(limit=10)
    assert all("event_id" in e for e in events)
    assert events[0]["event_id"] != events[1]["event_id"]


def test_since_filter_returns_only_newer_events():
    detector = GovernanceEventDetector()
    # Add 3 events
    for i in range(3):
        detector._recent_events.append({
            "type": "agent_new",
            "severity": "info",
            "message": f"event {i}",
            "agent_id": f"a{i}",
            "agent_name": f"test{i}",
            "timestamp": f"2026-02-23T00:0{i}:00Z"
        })
    all_events = detector.get_recent_events(limit=10)
    cursor = all_events[1]["event_id"]  # second event
    newer = detector.get_recent_events(limit=10, since=cursor)
    assert len(newer) == 1
    assert newer[0]["message"] == "event 2"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_event_cursor.py -v`
Expected: FAIL — `get_recent_events` doesn't accept `since` param, events have no `event_id`

**Step 3: Implement event IDs and since filter**

In `src/event_detector.py`, add an auto-incrementing counter:

```python
# In __init__:
self._event_counter: int = 0

# In detect_events(), where events are appended to _recent_events:
self._event_counter += 1
event["event_id"] = self._event_counter
```

In `get_recent_events()`, add `since` parameter:

```python
def get_recent_events(self, limit=50, agent_id=None, event_type=None, since=None):
    events = list(self._recent_events)
    if since is not None:
        events = [e for e in events if e.get("event_id", 0) > since]
    if agent_id:
        events = [e for e in events if e.get("agent_id") == agent_id]
    if event_type:
        events = [e for e in events if e.get("type") == event_type]
    return events[-limit:]
```

**Step 4: Update the HTTP endpoint**

In `src/mcp_server.py`, the `/api/events` handler (~line 2340):

```python
async def http_events(request):
    limit = int(request.query_params.get("limit", 50))
    agent_id = request.query_params.get("agent_id")
    event_type = request.query_params.get("type")
    since = request.query_params.get("since")
    if since is not None:
        since = int(since)

    events = event_detector.get_recent_events(
        limit=limit,
        agent_id=agent_id,
        event_type=event_type,
        since=since
    )
    return JSONResponse({
        "success": True,
        "events": events,
        "count": len(events)
    })
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_event_cursor.py -v`
Expected: PASS

**Step 6: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/event_detector.py src/mcp_server.py tests/test_event_cursor.py
git commit -m "feat: add event IDs and ?since= cursor to /api/events for Discord bridge"
```

---

## Phase 1: Foundation

### Task 1.1: Create repo and project skeleton

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/pyproject.toml`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/__init__.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/bot.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/config.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/.env.example`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/.gitignore`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/__init__.py`

**Step 1: Create project directory and initialize git**

```bash
mkdir -p /Users/cirwel/projects/unitares-discord-bridge/src/bridge
mkdir -p /Users/cirwel/projects/unitares-discord-bridge/tests
cd /Users/cirwel/projects/unitares-discord-bridge && git init
```

**Step 2: Write pyproject.toml**

```toml
[project]
name = "unitares-discord-bridge"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "discord.py>=2.4",
    "httpx>=0.27",
    "aiosqlite>=0.20",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[project.scripts]
unitares-bridge = "bridge.bot:main"
```

**Step 3: Write config.py**

```python
# src/bridge/config.py
import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0"))

GOVERNANCE_URL = os.environ.get("GOVERNANCE_MCP_URL", "http://localhost:8767")
ANIMA_URL = os.environ.get("ANIMA_MCP_URL", "http://100.79.215.83:8766")

EVENT_POLL_INTERVAL = int(os.environ.get("EVENT_POLL_INTERVAL", "10"))
HUD_UPDATE_INTERVAL = int(os.environ.get("HUD_UPDATE_INTERVAL", "30"))
SENSOR_POLL_INTERVAL = int(os.environ.get("SENSOR_POLL_INTERVAL", "300"))

DB_PATH = os.environ.get("BRIDGE_DB_PATH", "data/bridge.db")
```

**Step 4: Write .env.example**

```
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_GUILD_ID=your-guild-id-here
GOVERNANCE_MCP_URL=http://localhost:8767
ANIMA_MCP_URL=http://100.79.215.83:8766
```

**Step 5: Write .gitignore**

```
.env
data/
__pycache__/
*.egg-info/
.venv/
```

**Step 6: Write bot.py skeleton**

```python
# src/bridge/bot.py
import asyncio
import discord
from discord.ext import commands
from bridge.config import DISCORD_TOKEN, GUILD_ID


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bridge online as {bot.user}")
    if GUILD_ID:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            print(f"Connected to: {guild.name}")


def main():
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
```

**Step 7: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add -A
git commit -m "feat: initial project skeleton with config and bot entry point"
```

---

### Task 1.2: SQLite state cache

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/cache.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_cache.py`

**Step 1: Write the failing test**

```python
# tests/test_cache.py
import pytest
import asyncio
from bridge.cache import BridgeCache


@pytest.fixture
def cache(tmp_path):
    db_path = str(tmp_path / "test.db")
    return BridgeCache(db_path)


@pytest.mark.asyncio
async def test_event_cursor_default_zero(cache):
    async with cache:
        cursor = await cache.get_event_cursor()
        assert cursor == 0


@pytest.mark.asyncio
async def test_event_cursor_set_and_get(cache):
    async with cache:
        await cache.set_event_cursor(42)
        assert await cache.get_event_cursor() == 42


@pytest.mark.asyncio
async def test_channel_mapping(cache):
    async with cache:
        await cache.set_agent_channel("agent-123", 98765)
        assert await cache.get_agent_channel("agent-123") == 98765
        assert await cache.get_agent_channel("nonexistent") is None


@pytest.mark.asyncio
async def test_hud_message(cache):
    async with cache:
        await cache.set_hud_message(111, 222)
        channel_id, message_id = await cache.get_hud_message()
        assert channel_id == 111
        assert message_id == 222
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_cache.py -v`
Expected: FAIL — module not found

**Step 3: Implement BridgeCache**

```python
# src/bridge/cache.py
import aiosqlite


class BridgeCache:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._init_tables()
        return self

    async def __aexit__(self, *args):
        if self._db:
            await self._db.close()

    async def _init_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_channels (
                agent_id TEXT PRIMARY KEY,
                channel_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS dialectic_posts (
                dialectic_id TEXT PRIMARY KEY,
                post_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS knowledge_posts (
                discovery_id TEXT PRIMARY KEY,
                post_id INTEGER
            );
        """)
        await self._db.commit()

    async def get_event_cursor(self) -> int:
        async with self._db.execute(
            "SELECT value FROM kv WHERE key = 'event_cursor'"
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def set_event_cursor(self, cursor: int):
        await self._db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('event_cursor', ?)",
            (str(cursor),)
        )
        await self._db.commit()

    async def get_agent_channel(self, agent_id: str) -> int | None:
        async with self._db.execute(
            "SELECT channel_id FROM agent_channels WHERE agent_id = ?",
            (agent_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_agent_channel(self, agent_id: str, channel_id: int):
        await self._db.execute(
            "INSERT OR REPLACE INTO agent_channels (agent_id, channel_id) VALUES (?, ?)",
            (agent_id, channel_id)
        )
        await self._db.commit()

    async def get_hud_message(self) -> tuple[int, int] | None:
        async with self._db.execute(
            "SELECT value FROM kv WHERE key = 'hud_channel_id'"
        ) as cur:
            ch_row = await cur.fetchone()
        async with self._db.execute(
            "SELECT value FROM kv WHERE key = 'hud_message_id'"
        ) as cur:
            msg_row = await cur.fetchone()
        if ch_row and msg_row:
            return int(ch_row[0]), int(msg_row[0])
        return None

    async def set_hud_message(self, channel_id: int, message_id: int):
        await self._db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('hud_channel_id', ?)",
            (str(channel_id),)
        )
        await self._db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES ('hud_message_id', ?)",
            (str(message_id),)
        )
        await self._db.commit()
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_cache.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/cache.py tests/test_cache.py
git commit -m "feat: SQLite state cache for event cursors and channel mappings"
```

---

### Task 1.3: MCP HTTP client

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/mcp_client.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_mcp_client.py`

**Step 1: Write the failing test**

```python
# tests/test_mcp_client.py
import pytest
import json
from unittest.mock import AsyncMock, patch
from bridge.mcp_client import GovernanceClient, AnimaClient


@pytest.mark.asyncio
async def test_governance_fetch_events():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "events": [
            {"event_id": 1, "type": "agent_new", "severity": "info",
             "message": "New agent", "agent_id": "a1", "agent_name": "test",
             "timestamp": "2026-02-23T00:00:00Z"}
        ],
        "count": 1
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = GovernanceClient("http://localhost:8767")
        events = await client.fetch_events(since=0)
        assert len(events) == 1
        assert events[0]["event_id"] == 1


@pytest.mark.asyncio
async def test_governance_fetch_events_server_down():
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        client = GovernanceClient("http://localhost:8767")
        events = await client.fetch_events(since=0)
        assert events == []
        assert client.consecutive_failures == 1


@pytest.mark.asyncio
async def test_anima_fetch_state():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "warmth": 0.7, "clarity": 0.6, "stability": 0.8, "presence": 0.5,
        "cpu_temp": 55.0, "ambient_temp": 23.0, "humidity": 40.0,
        "pressure": 827.0, "light": 100.0,
        "neural": {"delta": 0.8, "theta": 0.3, "alpha": 0.6, "beta": 0.5, "gamma": 0.4}
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = AnimaClient("http://100.79.215.83:8766")
        state = await client.fetch_state()
        assert state["warmth"] == 0.7


@pytest.mark.asyncio
async def test_anima_fetch_gallery():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "drawings": [
            {"filename": "lumen_drawing_20260223_140000.png",
             "timestamp": 1740312000, "size": 5000, "manual": False, "era": "geometric"}
        ],
        "total": 1, "has_more": False
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        client = AnimaClient("http://100.79.215.83:8766")
        gallery = await client.fetch_gallery(limit=1)
        assert len(gallery["drawings"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_mcp_client.py -v`
Expected: FAIL — module not found

**Step 3: Implement MCP clients**

```python
# src/bridge/mcp_client.py
import httpx
import logging

log = logging.getLogger(__name__)


class GovernanceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.consecutive_failures = 0

    async def fetch_events(self, since: int = 0, limit: int = 50) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/api/events",
                    params={"since": since, "limit": limit}
                )
                resp.raise_for_status()
                data = resp.json()
                self.consecutive_failures = 0
                return data.get("events", [])
        except Exception as e:
            self.consecutive_failures += 1
            log.warning(f"governance fetch_events failed ({self.consecutive_failures}): {e}")
            return []

    async def fetch_health(self) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/health")
                resp.raise_for_status()
                self.consecutive_failures = 0
                return resp.json()
        except Exception:
            self.consecutive_failures += 1
            return None

    async def call_tool(self, tool_name: str, arguments: dict) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/tools/call",
                    json={"name": tool_name, "arguments": arguments}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            log.warning(f"governance call_tool({tool_name}) failed: {e}")
            return None


class AnimaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.is_online = True

    async def fetch_state(self) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/state")
                resp.raise_for_status()
                self.is_online = True
                return resp.json()
        except Exception:
            self.is_online = False
            return None

    async def fetch_gallery(self, limit: int = 5) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/gallery",
                    params={"limit": limit}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None

    async def fetch_drawing_image(self, filename: str) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.base_url}/gallery/{filename}")
                resp.raise_for_status()
                return resp.content
        except Exception:
            return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_mcp_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: HTTP clients for governance-mcp and anima-mcp"
```

---

### Task 1.4: Discord server setup (manual + bot channel creation)

This task is partially manual (creating the Discord application and server) and partially automated (bot creates channels/roles on startup).

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/server_setup.py`

**Step 1: Manual — Create Discord application and bot**

1. Go to https://discord.com/developers/applications
2. Click "New Application" → name: "UNITARES Bridge"
3. Go to "Bot" tab → click "Reset Token" → copy token to `.env`
4. Enable: "Message Content Intent", "Server Members Intent"
5. Go to "OAuth2" → URL Generator → select "bot" + "applications.commands"
6. Bot permissions: Manage Channels, Manage Roles, Send Messages, Embed Links,
   Attach Files, Read Message History, Use Slash Commands, Create Public Threads,
   Manage Threads
7. Copy invite URL → open → select/create "UNITARES" server
8. Copy Guild ID (right-click server → Copy Server ID) → add to `.env`

**Step 2: Write server_setup.py — bot auto-creates channels on startup**

```python
# src/bridge/server_setup.py
import discord
import logging

log = logging.getLogger(__name__)

CHANNEL_STRUCTURE = {
    "GOVERNANCE": {
        "events": {"type": "text", "topic": "All governance events — verdicts, risk, drift"},
        "alerts": {"type": "text", "topic": "Critical only — pause, reject, risk > 70%"},
        "dialectic-forum": {"type": "forum", "topic": "Governance dialectics — thesis, antithesis, synthesis"},
        "governance-hud": {"type": "text", "topic": "Auto-updating system status"},
    },
    "AGENTS": {
        "agent-lobby": {"type": "text", "topic": "New agent announcements"},
        "resonance": {"type": "text", "topic": "CIRS resonance events between agents"},
    },
    "LUMEN": {
        "lumen-stream": {"type": "text", "topic": "Lumen's inner voice and presence"},
        "lumen-art": {"type": "text", "topic": "Lumen's drawings"},
        "lumen-sensors": {"type": "text", "topic": "Environmental sensor readings"},
    },
    "KNOWLEDGE": {
        "discoveries": {"type": "forum", "topic": "Knowledge graph entries"},
        "knowledge-search": {"type": "text", "topic": "Search the knowledge graph"},
    },
    "CONTROL": {
        "commands": {"type": "text", "topic": "Slash commands for governance actions"},
        "audit-log": {"type": "text", "topic": "All bot actions logged here"},
    },
}

ROLES = {
    "governance-council": discord.Colour.gold(),
    "observer": discord.Colour.light_grey(),
    "agent-active": discord.Colour.green(),
    "agent-boundary": discord.Colour.orange(),
    "agent-degraded": discord.Colour.red(),
    "lumen": discord.Colour.blue(),
}


async def ensure_server_structure(guild: discord.Guild) -> dict[str, discord.abc.GuildChannel]:
    """Create missing categories, channels, and roles. Returns channel name → channel mapping."""
    channels = {}

    # Ensure roles exist
    existing_roles = {r.name: r for r in guild.roles}
    for role_name, colour in ROLES.items():
        if role_name not in existing_roles:
            await guild.create_role(name=role_name, colour=colour)
            log.info(f"Created role: {role_name}")

    # Ensure categories and channels exist
    existing_categories = {c.name: c for c in guild.categories}
    existing_channels = {c.name: c for c in guild.channels if not isinstance(c, discord.CategoryChannel)}

    for category_name, channel_defs in CHANNEL_STRUCTURE.items():
        # Create category if missing
        category = existing_categories.get(category_name)
        if not category:
            category = await guild.create_category(category_name)
            log.info(f"Created category: {category_name}")

        # Create channels if missing
        for ch_name, ch_def in channel_defs.items():
            if ch_name in existing_channels:
                channels[ch_name] = existing_channels[ch_name]
                continue

            if ch_def["type"] == "forum":
                ch = await guild.create_forum(
                    name=ch_name, category=category, topic=ch_def.get("topic", "")
                )
            else:
                ch = await guild.create_text_channel(
                    name=ch_name, category=category, topic=ch_def.get("topic", "")
                )
            channels[ch_name] = ch
            log.info(f"Created channel: #{ch_name}")

    # Backfill channels that already existed
    for c in guild.channels:
        if hasattr(c, "name") and c.name not in channels:
            channels[c.name] = c

    return channels
```

**Step 3: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/server_setup.py
git commit -m "feat: auto-create Discord server structure on bot startup"
```

---

### Task 1.5: Event poller and embed formatting

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/embeds.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/event_poller.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_embeds.py`

**Step 1: Write the failing test**

```python
# tests/test_embeds.py
import discord
from bridge.embeds import event_to_embed


def test_verdict_change_embed():
    event = {
        "event_id": 5,
        "type": "verdict_change",
        "severity": "warning",
        "message": "Verdict changed from proceed to guide",
        "agent_id": "abc-123",
        "agent_name": "opus_hikewa",
        "timestamp": "2026-02-23T14:32:00Z",
        "from": "proceed",
        "to": "guide",
    }
    embed = event_to_embed(event)
    assert isinstance(embed, discord.Embed)
    assert "Verdict Change" in embed.title
    assert embed.colour == discord.Colour.orange()


def test_agent_new_embed():
    event = {
        "event_id": 1,
        "type": "agent_new",
        "severity": "info",
        "message": "New agent registered: test_agent",
        "agent_id": "abc",
        "agent_name": "test_agent",
        "timestamp": "2026-02-23T10:00:00Z",
    }
    embed = event_to_embed(event)
    assert isinstance(embed, discord.Embed)
    assert embed.colour == discord.Colour.blue()


def test_critical_severity_is_red():
    event = {
        "event_id": 10,
        "type": "risk_threshold",
        "severity": "critical",
        "message": "Risk above 70%",
        "agent_id": "abc",
        "agent_name": "test",
        "timestamp": "2026-02-23T10:00:00Z",
        "threshold": 0.7,
        "direction": "up",
        "value": 0.75,
    }
    embed = event_to_embed(event)
    assert embed.colour == discord.Colour.red()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_embeds.py -v`
Expected: FAIL

**Step 3: Implement embeds.py**

```python
# src/bridge/embeds.py
import discord

SEVERITY_COLOURS = {
    "info": discord.Colour.blue(),
    "warning": discord.Colour.orange(),
    "critical": discord.Colour.red(),
}

EVENT_TITLES = {
    "agent_new": "New Agent",
    "verdict_change": "Verdict Change",
    "risk_threshold": "Risk Threshold",
    "drift_alert": "Drift Alert",
    "drift_oscillation": "Drift Oscillation",
    "trajectory_adjustment": "Trajectory Adjustment",
    "agent_idle": "Agent Idle",
}


def event_to_embed(event: dict) -> discord.Embed:
    severity = event.get("severity", "info")
    event_type = event.get("type", "unknown")
    colour = SEVERITY_COLOURS.get(severity, discord.Colour.greyple())

    title = EVENT_TITLES.get(event_type, event_type.replace("_", " ").title())

    embed = discord.Embed(
        title=title,
        description=event.get("message", ""),
        colour=colour,
        timestamp=discord.utils.parse_time(event.get("timestamp", "")),
    )

    embed.add_field(name="Agent", value=event.get("agent_name", "unknown"), inline=True)
    embed.add_field(name="Severity", value=severity, inline=True)

    # Type-specific fields
    if event_type == "verdict_change":
        embed.add_field(
            name="Transition",
            value=f"{event.get('from', '?')} → {event.get('to', '?')}",
            inline=False,
        )
    elif event_type == "risk_threshold":
        embed.add_field(name="Risk", value=f"{event.get('value', 0):.0%}", inline=True)
        embed.add_field(name="Direction", value=event.get("direction", "?"), inline=True)
    elif event_type == "drift_alert":
        embed.add_field(name="Axis", value=event.get("axis", "?"), inline=True)
        embed.add_field(name="Value", value=f"{event.get('value', 0):.2f}", inline=True)

    embed.set_footer(text=f"Event #{event.get('event_id', '?')}")
    return embed


def is_critical_event(event: dict) -> bool:
    """Should this event also be posted to #alerts?"""
    if event.get("severity") == "critical":
        return True
    if event.get("type") == "verdict_change" and event.get("to") in ("pause", "reject"):
        return True
    return False
```

**Step 4: Implement event_poller.py**

```python
# src/bridge/event_poller.py
import asyncio
import logging
import discord
from bridge.mcp_client import GovernanceClient
from bridge.cache import BridgeCache
from bridge.embeds import event_to_embed, is_critical_event

log = logging.getLogger(__name__)


class EventPoller:
    def __init__(
        self,
        gov_client: GovernanceClient,
        cache: BridgeCache,
        events_channel: discord.TextChannel,
        alerts_channel: discord.TextChannel,
        interval: int = 10,
    ):
        self.gov = gov_client
        self.cache = cache
        self.events_channel = events_channel
        self.alerts_channel = alerts_channel
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())
        asyncio.create_task(self._send_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            try:
                cursor = await self.cache.get_event_cursor()
                events = await self.gov.fetch_events(since=cursor)

                for event in events:
                    embed = event_to_embed(event)
                    await self._message_queue.put((self.events_channel, embed))

                    if is_critical_event(event):
                        await self._message_queue.put((self.alerts_channel, embed))

                if events:
                    last_id = max(e.get("event_id", 0) for e in events)
                    await self.cache.set_event_cursor(last_id)

                # Warn if governance is unreachable
                if self.gov.consecutive_failures == 3:
                    warn = discord.Embed(
                        title="Governance MCP Unreachable",
                        description=f"Failed to reach governance-mcp {self.gov.consecutive_failures} times",
                        colour=discord.Colour.dark_red(),
                    )
                    await self._message_queue.put((self.alerts_channel, warn))

            except Exception as e:
                log.error(f"Event poll error: {e}")

            await asyncio.sleep(self.interval)

    async def _send_loop(self):
        """Drain message queue with rate limit spacing."""
        while True:
            channel, embed = await self._message_queue.get()
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                log.warning(f"Discord send failed: {e}")
            await asyncio.sleep(0.15)  # ~6.6 msgs/sec, well within limits
```

**Step 5: Run tests**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_embeds.py -v`
Expected: PASS

**Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/embeds.py src/bridge/event_poller.py tests/test_embeds.py
git commit -m "feat: event poller with embed formatting and rate-limited send queue"
```

---

### Task 1.6: HUD updater

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/hud.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_hud.py`

**Step 1: Write the failing test**

```python
# tests/test_hud.py
import discord
from bridge.hud import build_hud_embed


def test_hud_embed_with_agents():
    agents = [
        {"id": "a1", "label": "opus_hikewa", "updates": 47},
        {"id": "a2", "label": "sonnet_review", "updates": 12},
    ]
    metrics = {
        "a1": {"E": 0.74, "I": 0.71, "S": 0.42, "V": 0.08, "verdict": "proceed"},
        "a2": {"E": 0.61, "I": 0.58, "S": 0.89, "V": 0.31, "verdict": "guide"},
    }
    embed = build_hud_embed(agents, metrics)
    assert isinstance(embed, discord.Embed)
    assert "opus_hikewa" in embed.description
    assert "sonnet_review" in embed.description


def test_hud_embed_empty():
    embed = build_hud_embed([], {})
    assert isinstance(embed, discord.Embed)
    assert "No active agents" in embed.description
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_hud.py -v`
Expected: FAIL

**Step 3: Implement hud.py**

```python
# src/bridge/hud.py
import asyncio
import logging
from datetime import datetime, timezone
import discord
from bridge.mcp_client import GovernanceClient
from bridge.cache import BridgeCache

log = logging.getLogger(__name__)

VERDICT_EMOJI = {
    "proceed": "\U0001f7e2",   # green circle
    "guide": "\U0001f7e1",     # yellow circle
    "pause": "\U0001f534",     # red circle
    "reject": "\u26d4",        # no entry
}


def build_hud_embed(agents: list[dict], metrics: dict[str, dict]) -> discord.Embed:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    embed = discord.Embed(
        title="UNITARES Governance — Live",
        colour=discord.Colour.dark_embed(),
    )

    if not agents:
        embed.description = "No active agents"
        embed.set_footer(text=f"Updated {now}")
        return embed

    lines = []
    paused = 0
    boundary = 0
    for agent in agents:
        aid = agent["id"]
        m = metrics.get(aid, {})
        verdict = m.get("verdict", "?")
        emoji = VERDICT_EMOJI.get(verdict, "\u2753")
        e, i, s, v = m.get("E", 0), m.get("I", 0), m.get("S", 0), m.get("V", 0)
        name = agent.get("label", agent.get("id", "?"))[:20]
        lines.append(f"{emoji} **{name}**  E={e:.2f} I={i:.2f} S={s:.2f} V={v:.2f}")
        if verdict == "pause":
            paused += 1
        if verdict == "guide":
            boundary += 1

    embed.description = "\n".join(lines)
    embed.set_footer(text=(
        f"{len(agents)} agents | {paused} paused | {boundary} boundary | Updated {now}"
    ))
    return embed


class HUDUpdater:
    def __init__(
        self,
        gov_client: GovernanceClient,
        cache: BridgeCache,
        hud_channel: discord.TextChannel,
        interval: int = 30,
    ):
        self.gov = gov_client
        self.cache = cache
        self.hud_channel = hud_channel
        self.interval = interval
        self._message: discord.Message | None = None
        self._task: asyncio.Task | None = None

    async def start(self):
        # Restore or create the HUD message
        cached = await self.cache.get_hud_message()
        if cached:
            try:
                self._message = await self.hud_channel.fetch_message(cached[1])
            except discord.NotFound:
                self._message = None

        if not self._message:
            embed = build_hud_embed([], {})
            self._message = await self.hud_channel.send(embed=embed)
            await self.cache.set_hud_message(self.hud_channel.id, self._message.id)

        self._task = asyncio.create_task(self._update_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _update_loop(self):
        while True:
            try:
                # Fetch agent list
                result = await self.gov.call_tool("list_agents", {"lite": True, "status_filter": "active"})
                agents = []
                if result:
                    # Parse tool result
                    import json
                    content = result.get("result", {}).get("content", [])
                    if content:
                        data = json.loads(content[0].get("text", "{}"))
                        agents = data.get("agents", [])

                # Fetch metrics per agent
                metrics = {}
                for agent in agents[:10]:  # cap to avoid rate limit burst
                    m = await self.gov.call_tool("get_governance_metrics", {"agent_id": agent["id"]})
                    if m:
                        content = m.get("result", {}).get("content", [])
                        if content:
                            metrics[agent["id"]] = json.loads(content[0].get("text", "{}"))

                embed = build_hud_embed(agents, metrics)
                await self._message.edit(embed=embed)

            except Exception as e:
                log.error(f"HUD update error: {e}")

            await asyncio.sleep(self.interval)
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_hud.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/hud.py tests/test_hud.py
git commit -m "feat: HUD embed builder and auto-updating HUD"
```

---

### Task 1.7: Wire everything together in bot.py

**Files:**
- Modify: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/bot.py`

**Step 1: Update bot.py to connect all components**

```python
# src/bridge/bot.py
import asyncio
import logging
import os
import discord
from discord.ext import commands
from bridge.config import (
    DISCORD_TOKEN, GUILD_ID, GOVERNANCE_URL, ANIMA_URL,
    EVENT_POLL_INTERVAL, HUD_UPDATE_INTERVAL, DB_PATH,
)
from bridge.cache import BridgeCache
from bridge.mcp_client import GovernanceClient, AnimaClient
from bridge.server_setup import ensure_server_structure
from bridge.event_poller import EventPoller
from bridge.hud import HUDUpdater

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Clients
gov_client = GovernanceClient(GOVERNANCE_URL)
anima_client = AnimaClient(ANIMA_URL)

# State
cache: BridgeCache | None = None
event_poller: EventPoller | None = None
hud_updater: HUDUpdater | None = None


@bot.event
async def on_ready():
    global cache, event_poller, hud_updater

    log.info(f"Bridge online as {bot.user}")
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        log.error(f"Guild {GUILD_ID} not found")
        return

    # Ensure channels and roles exist
    channels = await ensure_server_structure(guild)
    log.info(f"Server structure ready: {len(channels)} channels")

    # Open cache
    os.makedirs(os.path.dirname(DB_PATH) or "data", exist_ok=True)
    cache = BridgeCache(DB_PATH)
    await cache.__aenter__()

    # Start event poller
    events_ch = channels.get("events")
    alerts_ch = channels.get("alerts")
    if events_ch and alerts_ch:
        event_poller = EventPoller(gov_client, cache, events_ch, alerts_ch, EVENT_POLL_INTERVAL)
        await event_poller.start()
        log.info("Event poller started")

    # Start HUD
    hud_ch = channels.get("governance-hud")
    if hud_ch:
        hud_updater = HUDUpdater(gov_client, cache, hud_ch, HUD_UPDATE_INTERVAL)
        await hud_updater.start()
        log.info("HUD updater started")

    log.info("Phase 1 ready — events flowing, HUD updating")


def main():
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
```

**Step 2: Test manually**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
pip install -e ".[dev]"
# Ensure .env is populated with real tokens
python -m bridge.bot
```

Expected: Bot comes online, creates channels, events start flowing, HUD updates.

**Step 3: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/bot.py
git commit -m "feat: wire event poller and HUD into bot startup — Phase 1 complete"
```

---

## Phase 2: Agent Presence

### Task 2.1: Presence manager

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/presence.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_presence.py`

**Step 1: Write the failing test**

```python
# tests/test_presence.py
from bridge.presence import verdict_to_role_name


def test_verdict_to_role():
    assert verdict_to_role_name("proceed") == "agent-active"
    assert verdict_to_role_name("guide") == "agent-boundary"
    assert verdict_to_role_name("pause") == "agent-degraded"
    assert verdict_to_role_name("reject") == "agent-degraded"
    assert verdict_to_role_name("unknown") == "agent-active"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_presence.py -v`
Expected: FAIL

**Step 3: Implement presence.py**

```python
# src/bridge/presence.py
import asyncio
import logging
from datetime import datetime, timezone
import discord
from bridge.mcp_client import GovernanceClient
from bridge.cache import BridgeCache

log = logging.getLogger(__name__)

VERDICT_ROLES = {
    "proceed": "agent-active",
    "guide": "agent-boundary",
    "pause": "agent-degraded",
    "reject": "agent-degraded",
}

MAX_AGENT_CHANNELS = 20
IDLE_ARCHIVE_HOURS = 24


def verdict_to_role_name(verdict: str) -> str:
    return VERDICT_ROLES.get(verdict, "agent-active")


class PresenceManager:
    def __init__(
        self,
        gov_client: GovernanceClient,
        cache: BridgeCache,
        guild: discord.Guild,
        agents_category: discord.CategoryChannel,
        lobby_channel: discord.TextChannel,
        interval: int = 30,
    ):
        self.gov = gov_client
        self.cache = cache
        self.guild = guild
        self.agents_category = agents_category
        self.lobby_channel = lobby_channel
        self.interval = interval
        self._known_agents: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def handle_new_agent(self, event: dict):
        """Called by event poller when agent_new fires."""
        agent_id = event.get("agent_id", "")
        agent_name = event.get("agent_name", "unknown")

        # Announce in lobby
        embed = discord.Embed(
            title="Agent Online",
            description=f"**{agent_name}** has joined the system",
            colour=discord.Colour.green(),
        )
        await self.lobby_channel.send(embed=embed)

        # Create channel if not exists and under limit
        existing = await self.cache.get_agent_channel(agent_id)
        if not existing:
            active_count = len(self.agents_category.channels)
            if active_count < MAX_AGENT_CHANNELS:
                ch = await self.guild.create_text_channel(
                    name=f"agent-{agent_name[:30]}",
                    category=self.agents_category,
                    topic=f"Check-ins for {agent_name} ({agent_id[:8]}...)",
                )
                await self.cache.set_agent_channel(agent_id, ch.id)
                log.info(f"Created channel for {agent_name}")

    async def post_checkin(self, agent_id: str, checkin_data: dict):
        """Post a check-in embed to the agent's channel."""
        channel_id = await self.cache.get_agent_channel(agent_id)
        if not channel_id:
            return

        ch = self.guild.get_channel(channel_id)
        if not ch:
            return

        verdict = checkin_data.get("verdict", "?")
        embed = discord.Embed(
            title=f"Check-in",
            description=checkin_data.get("response_text", ""),
            colour=discord.Colour.green() if verdict == "proceed" else discord.Colour.orange(),
        )
        eisv = checkin_data.get("eisv", {})
        if eisv:
            embed.add_field(
                name="EISV",
                value=f"E={eisv.get('E', 0):.2f} I={eisv.get('I', 0):.2f} S={eisv.get('S', 0):.2f} V={eisv.get('V', 0):.2f}",
                inline=False,
            )
        embed.add_field(name="Verdict", value=verdict, inline=True)
        embed.add_field(name="Complexity", value=f"{checkin_data.get('complexity', 0):.1f}", inline=True)
        embed.add_field(name="Confidence", value=f"{checkin_data.get('confidence', 0):.1f}", inline=True)

        await ch.send(embed=embed)

    async def _poll_loop(self):
        """Periodic cleanup of idle agent channels."""
        while True:
            try:
                # Future: archive channels for agents idle > 24h
                pass
            except Exception as e:
                log.error(f"Presence poll error: {e}")
            await asyncio.sleep(self.interval * 10)  # cleanup runs less often
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_presence.py -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/presence.py tests/test_presence.py
git commit -m "feat: agent presence manager with channel creation and check-in embeds"
```

---

### Task 2.2: Wire presence into event poller and bot

**Files:**
- Modify: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/event_poller.py`
- Modify: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/bot.py`

**Step 1: Add presence hooks to event_poller.py**

Add `presence_manager` parameter to EventPoller. In `_poll_loop`, after posting each event, check if it's `agent_new` and call `presence_manager.handle_new_agent(event)`.

**Step 2: Add PresenceManager startup to bot.py on_ready**

After server structure is ensured, find the AGENTS category and agent-lobby channel, create PresenceManager, start it.

**Step 3: Test manually — trigger a governance check-in and verify Discord shows it**

**Step 4: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/event_poller.py src/bridge/bot.py
git commit -m "feat: wire presence manager into event flow — Phase 2 complete"
```

---

## Phase 3: Lumen

### Task 3.1: Lumen poller

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/lumen.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/tests/test_lumen.py`

**Step 1: Write the failing test**

```python
# tests/test_lumen.py
import discord
from bridge.lumen import build_sensor_embed, build_drawing_embed


def test_sensor_embed():
    state = {
        "ambient_temp": 24.3, "humidity": 38.0, "pressure": 827.0,
        "light": 142.0, "cpu_temp": 62.0, "memory_percent": 41.0,
        "neural": {"delta": 0.8, "theta": 0.3, "alpha": 0.6, "beta": 0.5, "gamma": 0.4},
    }
    embed = build_sensor_embed(state)
    assert isinstance(embed, discord.Embed)
    assert "24.3" in embed.description
    assert "827" in embed.description


def test_drawing_embed():
    drawing = {
        "filename": "lumen_drawing_20260223_140000.png",
        "era": "geometric",
        "manual": False,
    }
    embed = build_drawing_embed(drawing)
    assert isinstance(embed, discord.Embed)
    assert "geometric" in embed.description.lower() or "geometric" in str(embed.fields)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_lumen.py -v`
Expected: FAIL

**Step 3: Implement lumen.py**

```python
# src/bridge/lumen.py
import asyncio
import io
import logging
from datetime import datetime, timezone
import discord
from bridge.mcp_client import AnimaClient

log = logging.getLogger(__name__)


def build_sensor_embed(state: dict) -> discord.Embed:
    neural = state.get("neural", {})
    embed = discord.Embed(
        title="Lumen Environment",
        colour=discord.Colour.teal(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.description = (
        f"**Temp:** {state.get('ambient_temp', '?')}°C  "
        f"**Humidity:** {state.get('humidity', '?')}%\n"
        f"**Pressure:** {state.get('pressure', '?')} hPa  "
        f"**Light:** {state.get('light', '?')} lux\n"
        f"**CPU:** {state.get('cpu_temp', '?')}°C  "
        f"**Memory:** {state.get('memory_percent', '?')}%\n\n"
        f"**Neural:** "
        f"\u03b4={neural.get('delta', 0):.1f} "
        f"\u03b8={neural.get('theta', 0):.1f} "
        f"\u03b1={neural.get('alpha', 0):.1f} "
        f"\u03b2={neural.get('beta', 0):.1f} "
        f"\u03b3={neural.get('gamma', 0):.1f}"
    )

    # Anima dimensions
    embed.add_field(name="Warmth", value=f"{state.get('warmth', 0):.2f}", inline=True)
    embed.add_field(name="Clarity", value=f"{state.get('clarity', 0):.2f}", inline=True)
    embed.add_field(name="Stability", value=f"{state.get('stability', 0):.2f}", inline=True)
    embed.add_field(name="Presence", value=f"{state.get('presence', 0):.2f}", inline=True)

    embed.set_footer(text="Colorado")
    return embed


def build_drawing_embed(drawing: dict) -> discord.Embed:
    embed = discord.Embed(
        title="Drawing Complete",
        colour=discord.Colour.purple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.description = f"Era: **{drawing.get('era', 'unknown')}**"
    embed.add_field(name="Manual", value="Yes" if drawing.get("manual") else "No", inline=True)
    return embed


class LumenPoller:
    def __init__(
        self,
        anima_client: AnimaClient,
        stream_channel: discord.TextChannel,
        art_channel: discord.TextChannel,
        sensor_channel: discord.TextChannel,
        sensor_interval: int = 300,
    ):
        self.anima = anima_client
        self.stream_ch = stream_channel
        self.art_ch = art_channel
        self.sensor_ch = sensor_channel
        self.sensor_interval = sensor_interval
        self._last_drawing: str | None = None
        self._task_sensors: asyncio.Task | None = None
        self._task_drawings: asyncio.Task | None = None

    async def start(self):
        self._task_sensors = asyncio.create_task(self._sensor_loop())
        self._task_drawings = asyncio.create_task(self._drawing_loop())

    async def stop(self):
        for t in (self._task_sensors, self._task_drawings):
            if t:
                t.cancel()

    async def _sensor_loop(self):
        while True:
            try:
                state = await self.anima.fetch_state()
                if state:
                    embed = build_sensor_embed(state)
                    await self.sensor_ch.send(embed=embed)
                elif not self.anima.is_online:
                    embed = discord.Embed(
                        title="Lumen Offline",
                        description="Cannot reach anima-mcp",
                        colour=discord.Colour.dark_grey(),
                    )
                    await self.sensor_ch.send(embed=embed)
            except Exception as e:
                log.error(f"Sensor poll error: {e}")
            await asyncio.sleep(self.sensor_interval)

    async def _drawing_loop(self):
        while True:
            try:
                gallery = await self.anima.fetch_gallery(limit=1)
                if gallery and gallery.get("drawings"):
                    latest = gallery["drawings"][0]
                    filename = latest["filename"]
                    if filename != self._last_drawing:
                        self._last_drawing = filename
                        # Fetch the image
                        image_data = await self.anima.fetch_drawing_image(filename)
                        if image_data:
                            embed = build_drawing_embed(latest)
                            file = discord.File(io.BytesIO(image_data), filename=filename)
                            embed.set_image(url=f"attachment://{filename}")
                            await self.art_ch.send(embed=embed, file=file)
            except Exception as e:
                log.error(f"Drawing poll error: {e}")
            await asyncio.sleep(60)  # check every minute
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/unitares-discord-bridge && python3 -m pytest tests/test_lumen.py -v`
Expected: PASS

**Step 5: Wire into bot.py on_ready — add LumenPoller startup with lumen channels**

**Step 6: Commit**

```bash
cd /Users/cirwel/projects/unitares-discord-bridge
git add src/bridge/lumen.py tests/test_lumen.py src/bridge/bot.py
git commit -m "feat: Lumen poller — sensors, drawings, offline detection — Phase 3 complete"
```

---

## Phase 4: Dialectic Forum

### Task 4.1: Dialectic sync

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/dialectic.py`

This is more complex — the bridge watches for dialectic-related events and maps them to Discord forum posts. Implementation depends on the exact event structure emitted during dialectics (thesis_submitted, antithesis_submitted, synthesis_complete).

**Key logic:**
1. Watch events for `request_dialectic_review` → create forum post
2. Watch for thesis/antithesis submissions → add replies to the post
3. Collect human replies from the forum thread
4. When synthesis is ready, use `call_model()` to summarize human input
5. Post synthesis result and tag post as `resolved`

**Step 1: Implement dialectic.py with forum post creation and reply tracking**
**Step 2: Add event hooks in event_poller for dialectic events**
**Step 3: Add `on_message` handler in bot.py for human replies in dialectic forum**
**Step 4: Test with a real dialectic flow**
**Step 5: Commit**

---

## Phase 5: Knowledge Bridge

### Task 5.1: Knowledge sync and search command

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/knowledge.py`
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/commands.py`

**Key logic:**
1. `KnowledgeSync` periodically calls `search_knowledge_graph()` for recent entries
2. New entries → forum posts in #discoveries with tags
3. `/search` slash command calls `search_knowledge_graph()` and formats results

**Step 1: Implement knowledge.py with forum sync**
**Step 2: Implement commands.py with discord app_commands for /search, /status, /agent, /health**
**Step 3: Register slash commands in bot.py**
**Step 4: Test with real knowledge graph data**
**Step 5: Commit**

---

## Phase 6: Human Governance

### Task 6.1: Poll manager

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/polls.py`

**Key logic:**
1. When `verdict_change` to pause/reject fires → create Discord poll in #alerts
2. Track poll with expiry in SQLite cache
3. On poll completion (15min or majority reached) → call `operator_resume_agent()` or log the decision
4. Post result to #audit-log

**Step 1: Implement polls.py with poll creation, vote tracking, result forwarding**
**Step 2: Wire into event_poller for pause/reject events**
**Step 3: Add audit logging to #audit-log channel**
**Step 4: Test with a simulated pause event**
**Step 5: Commit**

---

## Phase 7: Resonance & Polish

### Task 7.1: Resonance threads

**Files:**
- Create: `/Users/cirwel/projects/unitares-discord-bridge/src/bridge/resonance.py`

**Key logic:**
1. Watch for CIRS `RESONANCE_ALERT` events → create thread in #resonance
2. Interleave both agents' state updates in the thread
3. On `STABILITY_RESTORED` → archive thread with summary

**Step 1: Implement resonance.py**
**Step 2: Wire into event_poller**
**Step 3: Test with simulated resonance events**
**Step 4: Commit**

### Task 7.2: Final polish

- Review all embed formatting for consistency
- Add logging throughout
- Test error recovery (kill governance-mcp, restart, verify bridge recovers)
- Test Discord rate limit behavior under load

---

## Summary

| Phase | Tasks | What's Working After |
|-------|-------|---------------------|
| 0 | 1 | Event cursors in governance-mcp |
| 1 | 7 | Bot online, events flowing, HUD updating |
| 2 | 2 | Agent channels, check-in embeds, role colors |
| 3 | 1 | Lumen sensors, drawings, offline detection |
| 4 | 1 | Dialectic forum posts with human participation |
| 5 | 1 | Knowledge search, discovery forum posts |
| 6 | 1 | Governance polls, audit logging |
| 7 | 2 | Resonance threads, error recovery, polish |
