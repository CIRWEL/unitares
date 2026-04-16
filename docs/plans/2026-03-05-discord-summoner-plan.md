# Discord Summoner Implementation Plan

> **Note:** This plan is specific to the reference UNITARES deployment (specific machine IPs, paths, and credentials). It is not general-purpose documentation — it documents one deployment's architecture for reproducibility.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Discord bot that summons Claude Code agents on a remote Mac, with Lumen ambient presence.

**Architecture:** Cloud VPS runs a discord.py bot. On `/summon`, it wakes the Mac via WoL over Tailscale, SSHs in, runs `claude -p --worktree` in tmux, captures the PR URL, posts it to Discord. Lumen sensor data polled from Pi over Tailscale.

**Tech Stack:** Python 3.12+, discord.py 2.6+, asyncio, asyncssh, httpx, wakeonlan

---

## Task 0: Project Scaffolding

**Files:**
- Create: `discord-summoner/pyproject.toml`
- Create: `discord-summoner/src/summoner/__init__.py`
- Create: `discord-summoner/src/summoner/config.py`
- Create: `discord-summoner/.env.example`
- Create: `discord-summoner/.gitignore`
- Create: `discord-summoner/tests/__init__.py`

**Step 1: Create the repo directory and pyproject.toml**

```bash
mkdir -p /Users/cirwel/projects/discord-summoner/src/summoner
mkdir -p /Users/cirwel/projects/discord-summoner/tests
cd /Users/cirwel/projects/discord-summoner && git init
```

Write `pyproject.toml`:

```toml
[project]
name = "discord-summoner"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "discord.py>=2.4",
    "asyncssh>=2.14",
    "httpx>=0.27",
    "wakeonlan>=3.1",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[project.scripts]
summoner = "summoner.bot:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Step 2: Write config.py**

```python
"""Environment configuration loader."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # Discord
    discord_token: str
    guild_id: int

    # Mac (Tailscale)
    mac_tailscale_ip: str
    mac_ssh_user: str
    mac_wol_mac: str  # MAC address for Wake-on-LAN

    # Pi / Lumen (Tailscale)
    pi_tailscale_ip: str
    anima_mcp_port: int = 8766

    # Repos (on Mac)
    default_repo: str = "governance-mcp-v1"
    repo_base_path: str = "/Users/cirwel/projects"

    # Timeouts (seconds)
    mac_wake_timeout: int = 120
    mac_idle_sleep_timeout: int = 300
    lumen_poll_interval: int = 300


def load_config() -> Config:
    return Config(
        discord_token=os.environ["DISCORD_BOT_TOKEN"],
        guild_id=int(os.environ["DISCORD_GUILD_ID"]),
        mac_tailscale_ip=os.environ["MAC_TAILSCALE_IP"],
        mac_ssh_user=os.environ.get("MAC_SSH_USER", "cirwel"),
        mac_wol_mac=os.environ["MAC_WOL_MAC"],
        pi_tailscale_ip=os.environ.get("PI_TAILSCALE_IP", "100.79.215.83"),
        anima_mcp_port=int(os.environ.get("ANIMA_MCP_PORT", "8766")),
        default_repo=os.environ.get("DEFAULT_REPO", "governance-mcp-v1"),
        repo_base_path=os.environ.get("REPO_BASE_PATH", "/Users/cirwel/projects"),
        mac_wake_timeout=int(os.environ.get("MAC_WAKE_TIMEOUT", "120")),
        mac_idle_sleep_timeout=int(os.environ.get("MAC_IDLE_SLEEP_TIMEOUT", "300")),
        lumen_poll_interval=int(os.environ.get("LUMEN_POLL_INTERVAL", "300")),
    )
```

**Step 3: Write .env.example and .gitignore**

`.env.example`:
```bash
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_GUILD_ID=your-guild-id-here
MAC_TAILSCALE_IP=100.96.201.46
MAC_SSH_USER=cirwel
MAC_WOL_MAC=84:2f:57:a7:69:cd
PI_TAILSCALE_IP=100.79.215.83
ANIMA_MCP_PORT=8766
DEFAULT_REPO=governance-mcp-v1
REPO_BASE_PATH=/Users/cirwel/projects
MAC_WAKE_TIMEOUT=120
MAC_IDLE_SLEEP_TIMEOUT=300
LUMEN_POLL_INTERVAL=300
```

`.gitignore`:
```
.env
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
data/
```

**Step 4: Write empty __init__.py files and install**

```python
# src/summoner/__init__.py
"""Discord Summoner — summon Claude Code from Discord."""
```

```bash
cd /Users/cirwel/projects/discord-summoner
pip install -e ".[dev]"
```

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: project scaffolding — pyproject, config, .env.example"
```

---

## Task 1: Mac Lifecycle (Wake / Health Check / Sleep)

**Files:**
- Create: `src/summoner/mac.py`
- Create: `tests/test_mac.py`

This is the foundation — everything else depends on being able to wake and reach the Mac.

**Step 1: Write the failing tests**

```python
# tests/test_mac.py
"""Tests for Mac wake/sleep lifecycle."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from summoner.mac import MacLifecycle


@pytest.fixture
def mac():
    return MacLifecycle(
        tailscale_ip="100.96.201.46",
        ssh_user="cirwel",
        wol_mac="84:2f:57:a7:69:cd",
        wake_timeout=5,
        idle_sleep_timeout=10,
    )


class TestIsAwake:
    async def test_returns_true_when_ssh_succeeds(self, mac):
        with patch.object(mac, "_ssh_ping", new_callable=AsyncMock, return_value=True):
            assert await mac.is_awake() is True

    async def test_returns_false_when_ssh_fails(self, mac):
        with patch.object(mac, "_ssh_ping", new_callable=AsyncMock, return_value=False):
            assert await mac.is_awake() is False


class TestWake:
    async def test_sends_wol_then_waits_for_ssh(self, mac):
        with (
            patch("summoner.mac.send_magic_packet") as mock_wol,
            patch.object(
                mac, "is_awake", new_callable=AsyncMock, side_effect=[False, False, True]
            ),
        ):
            result = await mac.wake()
            assert result is True
            mock_wol.assert_called_once_with("84:2f:57:a7:69:cd")

    async def test_returns_false_on_timeout(self, mac):
        with (
            patch("summoner.mac.send_magic_packet"),
            patch.object(mac, "is_awake", new_callable=AsyncMock, return_value=False),
        ):
            mac.wake_timeout = 1  # 1 second timeout for fast test
            result = await mac.wake()
            assert result is False


class TestRunSSH:
    async def test_runs_command_and_returns_stdout(self, mac):
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.exit_status = 0

        with patch("summoner.mac.asyncssh.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn.return_value)
            mock_conn.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_conn.return_value.run = AsyncMock(return_value=mock_result)

            stdout, exit_code = await mac.run_ssh("echo hello")
            assert stdout == "hello\n"
            assert exit_code == 0


class TestSleep:
    async def test_sends_pmset_sleepnow(self, mac):
        with patch.object(mac, "run_ssh", new_callable=AsyncMock, return_value=("", 0)):
            await mac.sleep()
            mac.run_ssh.assert_called_once_with("sudo pmset sleepnow")
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/cirwel/projects/discord-summoner
pytest tests/test_mac.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'summoner.mac'`

**Step 3: Write mac.py**

```python
"""Mac wake/sleep lifecycle management via Tailscale."""

import asyncio
import logging

import asyncssh
from wakeonlan import send_magic_packet

log = logging.getLogger(__name__)


class MacLifecycle:
    def __init__(
        self,
        tailscale_ip: str,
        ssh_user: str,
        wol_mac: str,
        wake_timeout: int = 120,
        idle_sleep_timeout: int = 300,
    ):
        self.tailscale_ip = tailscale_ip
        self.ssh_user = ssh_user
        self.wol_mac = wol_mac
        self.wake_timeout = wake_timeout
        self.idle_sleep_timeout = idle_sleep_timeout
        self._idle_task: asyncio.Task | None = None

    async def _ssh_ping(self) -> bool:
        """Check if Mac is reachable via SSH."""
        try:
            async with asyncssh.connect(
                self.tailscale_ip,
                username=self.ssh_user,
                known_hosts=None,
                connect_timeout=5,
            ) as conn:
                await conn.run("true", timeout=5)
            return True
        except Exception:
            return False

    async def is_awake(self) -> bool:
        return await self._ssh_ping()

    async def wake(self) -> bool:
        """Send WoL and wait for SSH to become available."""
        log.info("Sending Wake-on-LAN to %s", self.wol_mac)
        send_magic_packet(self.wol_mac)

        deadline = asyncio.get_event_loop().time() + self.wake_timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.is_awake():
                log.info("Mac is awake")
                self.cancel_idle_sleep()
                return True
            await asyncio.sleep(3)

        log.warning("Mac did not wake within %ds", self.wake_timeout)
        return False

    async def run_ssh(self, command: str) -> tuple[str, int]:
        """Run a command on the Mac via SSH. Returns (stdout, exit_code)."""
        async with asyncssh.connect(
            self.tailscale_ip,
            username=self.ssh_user,
            known_hosts=None,
        ) as conn:
            result = await conn.run(command)
            return result.stdout or "", result.exit_status or 0

    async def sleep(self) -> None:
        """Put the Mac to sleep."""
        log.info("Sending Mac to sleep")
        await self.run_ssh("sudo pmset sleepnow")

    def start_idle_sleep_timer(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start a timer that sleeps the Mac after idle timeout."""
        self.cancel_idle_sleep()

        async def _idle_sleep():
            await asyncio.sleep(self.idle_sleep_timeout)
            log.info("Idle timeout reached, sleeping Mac")
            await self.sleep()

        self._idle_task = loop.create_task(_idle_sleep())

    def cancel_idle_sleep(self) -> None:
        """Cancel pending idle sleep timer."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mac.py -v
```

Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add src/summoner/mac.py tests/test_mac.py
git commit -m "feat: Mac lifecycle — wake-on-LAN, SSH, sleep management"
```

---

## Task 2: Executor (SSH → Claude Code → PR URL)

**Files:**
- Create: `src/summoner/executor.py`
- Create: `tests/test_executor.py`

The core — invoke Claude Code on the Mac and get back a PR URL.

**Step 1: Write the failing tests**

```python
# tests/test_executor.py
"""Tests for Claude Code executor."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from summoner.executor import Executor, SessionState


@pytest.fixture
def mac():
    mock = MagicMock()
    mock.run_ssh = AsyncMock()
    mock.wake = AsyncMock(return_value=True)
    mock.is_awake = AsyncMock(return_value=True)
    mock.start_idle_sleep_timer = MagicMock()
    return mock


@pytest.fixture
def executor(mac):
    return Executor(
        mac=mac,
        default_repo="governance-mcp-v1",
        repo_base_path="/Users/cirwel/projects",
    )


class TestSummon:
    async def test_rejects_when_busy(self, executor):
        executor._state = SessionState.RUNNING
        result = await executor.summon("fix bug")
        assert result.error == "Already running a session"

    async def test_wakes_mac_if_asleep(self, executor, mac):
        mac.is_awake.return_value = False
        mac.wake.return_value = True
        mac.run_ssh.return_value = (
            "https://github.com/cirwel/governance-mcp-v1/pull/42\n",
            0,
        )

        result = await executor.summon("fix bug")
        mac.wake.assert_called_once()
        assert result.pr_url == "https://github.com/cirwel/governance-mcp-v1/pull/42"

    async def test_returns_error_when_mac_wont_wake(self, executor, mac):
        mac.is_awake.return_value = False
        mac.wake.return_value = False

        result = await executor.summon("fix bug")
        assert "wake" in result.error.lower()

    async def test_extracts_pr_url_from_stdout(self, executor, mac):
        mac.run_ssh.return_value = (
            "Working on task...\nCreated branch fix-bug\n"
            "https://github.com/cirwel/governance-mcp-v1/pull/42\n",
            0,
        )

        result = await executor.summon("fix bug")
        assert result.pr_url == "https://github.com/cirwel/governance-mcp-v1/pull/42"

    async def test_handles_no_pr_url_in_output(self, executor, mac):
        mac.run_ssh.return_value = ("Some output but no PR\n", 0)

        result = await executor.summon("fix bug")
        assert result.pr_url is None
        assert result.stdout == "Some output but no PR\n"

    async def test_uses_specified_repo(self, executor, mac):
        mac.run_ssh.return_value = ("https://github.com/x/y/pull/1\n", 0)

        await executor.summon("fix bug", repo="anima-mcp")
        cmd = mac.run_ssh.call_args[0][0]
        assert "anima-mcp" in cmd


class TestCancel:
    async def test_kills_tmux_session(self, executor, mac):
        executor._state = SessionState.RUNNING
        executor._tmux_session = "summoner-abc123"
        mac.run_ssh.return_value = ("", 0)

        await executor.cancel()
        cmd = mac.run_ssh.call_args[0][0]
        assert "tmux kill-session" in cmd
        assert executor._state == SessionState.IDLE
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_executor.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write executor.py**

```python
"""Claude Code executor — SSH to Mac, run claude, capture PR."""

import enum
import logging
import re
import uuid
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

PR_URL_PATTERN = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


class SessionState(enum.Enum):
    IDLE = "idle"
    WAKING = "waking"
    RUNNING = "running"


@dataclass
class SummonResult:
    pr_url: str | None = None
    stdout: str = ""
    error: str = ""
    exit_code: int = 0


class Executor:
    def __init__(self, mac, default_repo: str, repo_base_path: str):
        self.mac = mac
        self.default_repo = default_repo
        self.repo_base_path = repo_base_path
        self._state = SessionState.IDLE
        self._tmux_session: str | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    async def summon(self, task: str, repo: str | None = None) -> SummonResult:
        """Dispatch Claude Code to work on a task. Returns a SummonResult."""
        if self._state == SessionState.RUNNING:
            return SummonResult(error="Already running a session")

        repo = repo or self.default_repo
        repo_path = f"{self.repo_base_path}/{repo}"

        # Wake Mac if needed
        if not await self.mac.is_awake():
            self._state = SessionState.WAKING
            if not await self.mac.wake():
                self._state = SessionState.IDLE
                return SummonResult(error="Could not wake Mac")

        self._state = SessionState.RUNNING
        session_id = f"summoner-{uuid.uuid4().hex[:8]}"
        self._tmux_session = session_id

        try:
            prompt = (
                f"You are working on {repo} at {repo_path}. "
                f"Task: {task}. "
                "Create a git worktree, do the work, run tests, open a PR with gh. "
                "Output the PR URL as the last line of your response."
            )

            # Escape single quotes in prompt
            safe_prompt = prompt.replace("'", "'\\''")

            cmd = (
                f"caffeinate -i tmux new-session -d -s {session_id} "
                f"\"cd {repo_path} && claude -p '{safe_prompt}' "
                f"--allowedTools 'Edit,Write,Bash,Read,Grep,Glob' "
                f"> /tmp/{session_id}.out 2>&1; "
                f"echo __DONE__ >> /tmp/{session_id}.out\""
            )

            await self.mac.run_ssh(cmd)

            # Poll for completion
            stdout = await self._poll_for_completion(session_id)
            pr_url = self._extract_pr_url(stdout)

            return SummonResult(pr_url=pr_url, stdout=stdout, exit_code=0)

        except Exception as e:
            log.exception("Executor error")
            return SummonResult(error=str(e))
        finally:
            self._state = SessionState.IDLE
            self._tmux_session = None

    async def _poll_for_completion(self, session_id: str) -> str:
        """Poll the output file until __DONE__ marker appears."""
        import asyncio

        deadline = 600  # 10 minute max
        elapsed = 0
        interval = 10

        while elapsed < deadline:
            await asyncio.sleep(interval)
            elapsed += interval

            stdout, _ = await self.mac.run_ssh(f"cat /tmp/{session_id}.out 2>/dev/null || true")
            if "__DONE__" in stdout:
                return stdout.replace("__DONE__", "").strip()

        # Timeout — return what we have
        stdout, _ = await self.mac.run_ssh(f"cat /tmp/{session_id}.out 2>/dev/null || true")
        return stdout.replace("__DONE__", "").strip()

    def _extract_pr_url(self, stdout: str) -> str | None:
        """Extract the last GitHub PR URL from stdout."""
        matches = PR_URL_PATTERN.findall(stdout)
        return matches[-1] if matches else None

    async def cancel(self) -> None:
        """Kill the current Claude Code session."""
        if self._tmux_session:
            await self.mac.run_ssh(f"tmux kill-session -t {self._tmux_session}")
            await self.mac.run_ssh(f"rm -f /tmp/{self._tmux_session}.out")
        self._state = SessionState.IDLE
        self._tmux_session = None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_executor.py -v
```

Expected: All 7 tests PASS.

Note: The `test_wakes_mac_if_asleep` and some others will need adjustment because `summon` now polls asynchronously via tmux. The mock for `run_ssh` needs to return the done marker on the polling read. Update the fixture:

```python
# In test_executor.py, update the mac fixture's run_ssh for tests that check stdout:
async def test_extracts_pr_url_from_stdout(self, executor, mac):
    # First call: tmux launch. Second call: poll output file.
    mac.run_ssh.side_effect = [
        ("", 0),  # tmux launch
        ("Working on task...\nhttps://github.com/cirwel/governance-mcp-v1/pull/42\n__DONE__\n", 0),  # poll
    ]

    result = await executor.summon("fix bug")
    assert result.pr_url == "https://github.com/cirwel/governance-mcp-v1/pull/42"
```

Adjust all summon tests similarly to account for the two-call pattern (tmux launch + poll).

**Step 5: Commit**

```bash
git add src/summoner/executor.py tests/test_executor.py
git commit -m "feat: Claude Code executor — summon, poll, extract PR URL"
```

---

## Task 3: Discord Bot + Slash Commands

**Files:**
- Create: `src/summoner/bot.py`
- Create: `tests/test_bot.py`

Wire up Discord slash commands to the executor.

**Step 1: Write the failing tests**

```python
# tests/test_bot.py
"""Tests for Discord bot commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summoner.bot import SummonerBot
from summoner.executor import SummonResult, SessionState


@pytest.fixture
def executor():
    mock = MagicMock()
    mock.summon = AsyncMock()
    mock.cancel = AsyncMock()
    mock.state = SessionState.IDLE
    return mock


@pytest.fixture
def mac():
    mock = MagicMock()
    mock.is_awake = AsyncMock(return_value=True)
    mock.start_idle_sleep_timer = MagicMock()
    return mock


@pytest.fixture
def bot(executor, mac):
    return SummonerBot(executor=executor, mac=mac, guild_id=123456)


class TestSummonCommand:
    async def test_calls_executor_with_task(self, bot, executor):
        executor.summon.return_value = SummonResult(
            pr_url="https://github.com/x/y/pull/1"
        )
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()

        await bot._handle_summon(interaction, task="fix bug", repo=None)
        executor.summon.assert_called_once_with("fix bug", repo=None)

    async def test_posts_pr_url_on_success(self, bot, executor):
        executor.summon.return_value = SummonResult(
            pr_url="https://github.com/x/y/pull/1"
        )
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()

        await bot._handle_summon(interaction, task="fix bug", repo=None)

        sent_text = interaction.followup.send.call_args[1].get(
            "content", interaction.followup.send.call_args[0][0]
        )
        assert "pull/1" in sent_text

    async def test_posts_error_on_failure(self, bot, executor):
        executor.summon.return_value = SummonResult(error="Could not wake Mac")
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()

        await bot._handle_summon(interaction, task="fix bug", repo=None)

        sent_text = interaction.followup.send.call_args[1].get(
            "content", interaction.followup.send.call_args[0][0]
        )
        assert "wake" in sent_text.lower()


class TestStatusCommand:
    async def test_reports_idle(self, bot, executor, mac):
        executor.state = SessionState.IDLE
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await bot._handle_status(interaction)
        interaction.response.send_message.assert_called_once()


class TestCancelCommand:
    async def test_cancels_running_session(self, bot, executor):
        executor.state = SessionState.RUNNING
        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await bot._handle_cancel(interaction)
        executor.cancel.assert_called_once()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_bot.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write bot.py**

```python
"""Discord bot — slash commands for summoning Claude Code."""

import asyncio
import logging

import discord
from discord import app_commands

from summoner.config import Config, load_config
from summoner.executor import Executor, SessionState, SummonResult
from summoner.mac import MacLifecycle

log = logging.getLogger(__name__)


class SummonerBot:
    def __init__(self, executor: Executor, mac: MacLifecycle, guild_id: int):
        self.executor = executor
        self.mac = mac
        self.guild_id = guild_id

        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

        self._register_commands()
        self._register_events()

    def _register_commands(self):
        guild = discord.Object(id=self.guild_id)

        @self.tree.command(name="summon", description="Summon Claude Code to work on a task", guild=guild)
        @app_commands.describe(task="What should Claude Code do?", repo="Target repo (default: governance-mcp-v1)")
        async def summon(interaction: discord.Interaction, task: str, repo: str | None = None):
            await self._handle_summon(interaction, task, repo)

        @self.tree.command(name="status", description="Check Mac and session status", guild=guild)
        async def status(interaction: discord.Interaction):
            await self._handle_status(interaction)

        @self.tree.command(name="cancel", description="Cancel the current Claude Code session", guild=guild)
        async def cancel(interaction: discord.Interaction):
            await self._handle_cancel(interaction)

    def _register_events(self):
        @self.client.event
        async def on_ready():
            await self.tree.sync(guild=discord.Object(id=self.guild_id))
            log.info("Summoner bot ready as %s", self.client.user)

        @self.client.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
            if user.bot:
                return
            await self._handle_reaction(reaction, user)

    async def _handle_summon(self, interaction: discord.Interaction, task: str, repo: str | None):
        """Handle /summon command."""
        await interaction.response.defer()

        result = await self.executor.summon(task, repo=repo)

        if result.error:
            await interaction.followup.send(f"Failed: {result.error}")
            return

        if result.pr_url:
            await interaction.followup.send(
                f"**PR opened:** {result.pr_url}\n"
                f"React \U0001f44d to merge \u00b7 \U0001f44e to close"
            )
            self.mac.start_idle_sleep_timer(asyncio.get_event_loop())
        else:
            summary = result.stdout[-500:] if len(result.stdout) > 500 else result.stdout
            await interaction.followup.send(
                f"Session completed but no PR was created.\n```\n{summary}\n```"
            )
            self.mac.start_idle_sleep_timer(asyncio.get_event_loop())

    async def _handle_status(self, interaction: discord.Interaction):
        """Handle /status command."""
        mac_awake = await self.mac.is_awake()
        state = self.executor.state.value

        await interaction.response.send_message(
            f"**Mac:** {'awake' if mac_awake else 'sleeping'}\n"
            f"**Session:** {state}"
        )

    async def _handle_cancel(self, interaction: discord.Interaction):
        """Handle /cancel command."""
        if self.executor.state != SessionState.RUNNING:
            await interaction.response.send_message("No active session to cancel.")
            return

        await self.executor.cancel()
        await interaction.response.send_message("Session cancelled.")

    async def _handle_reaction(self, reaction: discord.Reaction, user: discord.User):
        """Handle merge/close reactions on PR messages."""
        msg = reaction.message
        if msg.author != self.client.user:
            return
        if "PR opened:" not in (msg.content or ""):
            return

        # Extract PR URL from message
        import re
        match = re.search(r"https://github\.com/[^\s]+/pull/\d+", msg.content)
        if not match:
            return

        pr_url = match.group()
        # Extract owner/repo/number from URL
        parts = pr_url.split("/")
        repo_slug = f"{parts[3]}/{parts[4]}"
        pr_number = parts[-1]

        if str(reaction.emoji) == "\U0001f44d":
            stdout, _ = await self.mac.run_ssh(
                f"cd /Users/cirwel/projects && gh pr merge {pr_number} --repo {repo_slug} --squash --delete-branch"
            )
            await msg.reply(f"Merged and branch deleted.")
            self.mac.start_idle_sleep_timer(asyncio.get_event_loop())

        elif str(reaction.emoji) == "\U0001f44e":
            stdout, _ = await self.mac.run_ssh(
                f"cd /Users/cirwel/projects && gh pr close {pr_number} --repo {repo_slug}"
            )
            await msg.reply("PR closed.")
            self.mac.start_idle_sleep_timer(asyncio.get_event_loop())


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = load_config()

    mac = MacLifecycle(
        tailscale_ip=config.mac_tailscale_ip,
        ssh_user=config.mac_ssh_user,
        wol_mac=config.mac_wol_mac,
        wake_timeout=config.mac_wake_timeout,
        idle_sleep_timeout=config.mac_idle_sleep_timeout,
    )

    executor = Executor(
        mac=mac,
        default_repo=config.default_repo,
        repo_base_path=config.repo_base_path,
    )

    bot = SummonerBot(executor=executor, mac=mac, guild_id=config.guild_id)
    bot.client.run(config.discord_token)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bot.py -v
```

Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add src/summoner/bot.py tests/test_bot.py
git commit -m "feat: Discord bot — /summon, /status, /cancel, reaction merge"
```

---

## Task 4: Lumen Presence

**Files:**
- Create: `src/summoner/lumen.py`
- Create: `tests/test_lumen.py`

Ambient Lumen data in #lumen channel.

**Step 1: Write the failing tests**

```python
# tests/test_lumen.py
"""Tests for Lumen presence poller."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summoner.lumen import LumenPoller


@pytest.fixture
def poller():
    return LumenPoller(
        pi_tailscale_ip="100.79.215.83",
        anima_mcp_port=8766,
        poll_interval=5,
    )


class TestFetchState:
    async def test_returns_state_on_success(self, poller):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {"content": [{"text": '{"warmth": 0.6, "clarity": 0.7}'}]}
        }

        with patch("summoner.lumen.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            state = await poller.fetch_state()
            assert state == {"warmth": 0.6, "clarity": 0.7}

    async def test_returns_none_on_connection_error(self, poller):
        with patch("summoner.lumen.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            state = await poller.fetch_state()
            assert state is None


class TestOfflineDetection:
    async def test_reports_offline_once(self, poller):
        # First failure: should report offline
        assert poller.should_report_offline() is True
        poller.mark_offline_reported()
        # Second failure: should NOT report again
        assert poller.should_report_offline() is False

    async def test_reports_recovery(self, poller):
        poller.mark_offline_reported()
        assert poller.should_report_recovery() is True
        poller.mark_online()
        assert poller.should_report_recovery() is False
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_lumen.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write lumen.py**

```python
"""Lumen presence — poll Pi for sensor data and drawings."""

import json
import logging

import httpx

log = logging.getLogger(__name__)


class LumenPoller:
    def __init__(self, pi_tailscale_ip: str, anima_mcp_port: int, poll_interval: int = 300):
        self.base_url = f"http://{pi_tailscale_ip}:{anima_mcp_port}"
        self.poll_interval = poll_interval
        self._is_offline = False
        self._offline_reported = False

    async def fetch_state(self) -> dict | None:
        """Fetch Lumen state from anima-mcp. Returns None if unreachable."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/mcp/",
                    json={"method": "tools/call", "params": {"name": "get_state", "arguments": {}}},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["result"]["content"][0]["text"]
                    self._is_offline = False
                    return json.loads(text) if isinstance(text, str) else text
        except Exception as e:
            log.debug("Lumen unreachable: %s", e)
            self._is_offline = True
        return None

    def should_report_offline(self) -> bool:
        return self._is_offline and not self._offline_reported

    def mark_offline_reported(self) -> None:
        self._offline_reported = True

    def should_report_recovery(self) -> bool:
        return not self._is_offline and self._offline_reported

    def mark_online(self) -> None:
        self._offline_reported = False

    def format_state(self, state: dict) -> str:
        """Format Lumen state for Discord display."""
        lines = []
        for key, val in state.items():
            if isinstance(val, float):
                lines.append(f"**{key}:** {val:.2f}")
            else:
                lines.append(f"**{key}:** {val}")
        return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_lumen.py -v
```

Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/summoner/lumen.py tests/test_lumen.py
git commit -m "feat: Lumen poller — fetch state, offline detection"
```

---

## Task 5: Wire Lumen Polling into Bot

**Files:**
- Modify: `src/summoner/bot.py` — add background lumen polling loop and `/lumen` command

**Step 1: Add test for /lumen command**

Add to `tests/test_bot.py`:

```python
class TestLumenCommand:
    async def test_returns_sensor_data(self, bot):
        bot.lumen = MagicMock()
        bot.lumen.fetch_state = AsyncMock(return_value={"warmth": 0.6, "clarity": 0.7})
        bot.lumen.format_state = MagicMock(return_value="**warmth:** 0.60\n**clarity:** 0.70")

        interaction = MagicMock()
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await bot._handle_lumen(interaction)
        interaction.response.send_message.assert_called_once()
        call_text = interaction.response.send_message.call_args[0][0]
        assert "warmth" in call_text
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_bot.py::TestLumenCommand -v
```

Expected: FAIL — `_handle_lumen` not defined

**Step 3: Add /lumen command and background poller to bot.py**

Add to `SummonerBot.__init__`:
```python
self.lumen = None  # Set externally or via config
self._lumen_channel_id = None
```

Add to `_register_commands`:
```python
@self.tree.command(name="lumen", description="Current Lumen sensor snapshot", guild=guild)
async def lumen(interaction: discord.Interaction):
    await self._handle_lumen(interaction)
```

Add method:
```python
async def _handle_lumen(self, interaction: discord.Interaction):
    """Handle /lumen command."""
    if not self.lumen:
        await interaction.response.send_message("Lumen poller not configured.")
        return
    state = await self.lumen.fetch_state()
    if state is None:
        await interaction.response.send_message("Lumen is offline.")
        return
    await interaction.response.send_message(self.lumen.format_state(state))
```

Update `main()` to create and attach the LumenPoller.

**Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/summoner/bot.py tests/test_bot.py
git commit -m "feat: /lumen command and Lumen poller wiring"
```

---

## Task 6: Dockerfile and Deployment Config

**Files:**
- Create: `Dockerfile`
- Create: `fly.toml`

**Step 1: Write Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install tailscale
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://tailscale.com/install.sh | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

# Tailscale + bot startup script
COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
```

**Step 2: Write start.sh**

```bash
#!/bin/bash
set -e

# Start tailscale in userspace mode
tailscaled --tun=userspace-networking --socks5-server=localhost:1055 &
sleep 2
tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname=discord-summoner
sleep 2

# Start the bot
exec python -m summoner.bot
```

**Step 3: Write fly.toml**

```toml
app = "discord-summoner"
primary_region = "ord"  # Chicago — close to nothing, but cheap

[build]

[env]
  PYTHONUNBUFFERED = "1"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

**Step 4: Commit**

```bash
git add Dockerfile start.sh fly.toml
git commit -m "chore: Dockerfile and fly.io deployment config"
```

---

## Task 7: Discord Server Setup + First Deploy

This task is manual — no code, just infrastructure.

**Step 1: Create Discord Application**

1. Go to https://discord.com/developers/applications
2. New Application → name it "Summoner"
3. Bot tab → create bot, copy token → save as `DISCORD_BOT_TOKEN`
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands`
5. Bot Permissions: Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Use Slash Commands
6. Copy invite URL → open in browser → add to your server

**Step 2: Create Discord Server**

1. Create server named "SUMMONER" (or use existing)
2. Create channels: `#lumen`, `#agents`, `#audit`
3. Create roles: `summoner`, `observer`
4. Assign yourself `summoner` role
5. Copy Guild ID → save as `DISCORD_GUILD_ID`

**Step 3: Create Tailscale auth key**

1. Go to https://login.tailscale.com/admin/settings/keys
2. Generate auth key (reusable, ephemeral)
3. Save as `TAILSCALE_AUTHKEY`

**Step 4: Deploy to fly.io**

```bash
cd /Users/cirwel/projects/discord-summoner

# Set secrets
fly secrets set DISCORD_BOT_TOKEN=...
fly secrets set DISCORD_GUILD_ID=...
fly secrets set TAILSCALE_AUTHKEY=...
fly secrets set MAC_TAILSCALE_IP=100.96.201.46
fly secrets set MAC_SSH_USER=cirwel
fly secrets set MAC_WOL_MAC=84:2f:57:a7:69:cd
fly secrets set PI_TAILSCALE_IP=100.79.215.83

# Deploy
fly launch  # first time
fly deploy   # subsequent
```

**Step 5: Verify**

1. Check bot comes online in Discord
2. Run `/status` — should show Mac status
3. Try `/summon echo test` on a throwaway repo
4. Check `/lumen` — should show sensor data or "Lumen offline"

**Step 6: Commit any adjustments**

```bash
git add -A
git commit -m "chore: deployment adjustments from first run"
```

---

## Task 8: SSH Key Setup for VPS → Mac

**Step 1: Generate SSH key on VPS (or in Dockerfile)**

The fly.io container needs an SSH key that the Mac trusts. Two options:

**Option A: Tailscale SSH (preferred — no keys needed)**

If Tailscale SSH is enabled on the Mac, the VPS can SSH directly using Tailscale identity. Check:

```bash
# On Mac
tailscale status
# Verify "SSH" is listed
```

Enable if needed:
```bash
# On Mac
sudo tailscale set --ssh
```

The Dockerfile `asyncssh.connect()` call needs to use Tailscale's SSH agent. Update `mac.py` to use `known_hosts=None` and rely on Tailscale SSH auth.

**Option B: Manual SSH key**

1. Generate key: `ssh-keygen -t ed25519 -f summoner_key -N ""`
2. Add public key to Mac's `~/.ssh/authorized_keys`
3. Store private key as fly.io secret: `fly secrets set SSH_PRIVATE_KEY="$(cat summoner_key)"`
4. Write key to file in `start.sh` before starting bot

**Step 2: Test SSH from VPS to Mac**

```bash
# From VPS (via fly ssh console)
ssh cirwel@100.96.201.46 "echo hello"
```

Expected: `hello`

**Step 3: Commit any changes**

```bash
git add -A
git commit -m "chore: SSH auth setup for VPS to Mac"
```

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 0 | Scaffolding | pyproject.toml, config.py, .env | — |
| 1 | Mac lifecycle | mac.py | 5 |
| 2 | Executor | executor.py | 7 |
| 3 | Discord bot | bot.py | 5 |
| 4 | Lumen poller | lumen.py | 4 |
| 5 | Wire Lumen into bot | bot.py (modify) | 1 |
| 6 | Dockerfile + deploy config | Dockerfile, fly.toml | — |
| 7 | Discord setup + first deploy | Manual | — |
| 8 | SSH key setup | mac.py or start.sh | — |

**Total: ~6 source files, ~22 tests, 8 tasks.**

Build order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (mostly sequential, 4 can parallel with 2-3).
