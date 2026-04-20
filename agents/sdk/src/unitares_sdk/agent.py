"""GovernanceAgent — lifecycle base class for long-running UNITARES agents.

First-time resident bootstrap:
    UNITARES_FIRST_RUN=1 python3 -m agents.vigil  # or sentinel, watcher
This is the ONLY path that mints a new UUID for a resident with
refuse_fresh_onboard=True. Every other path must resume the stored
anchor UUID.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unitares_sdk.client import GovernanceClient
from unitares_sdk.errors import (
    GovernanceConnectionError,
    GovernanceTimeoutError,
    IdentityDriftError,
    VerdictError,
)
from unitares_sdk.utils import (
    load_json_state,
    notify,
    save_json_state,
)

logger = logging.getLogger(__name__)


@dataclass
class CycleResult:
    """Structured return from GovernanceAgent.run_cycle().

    Carries everything the base class needs for the post-cycle check-in.
    """

    summary: str
    complexity: float = 0.3
    confidence: float = 0.7
    response_mode: str = "compact"
    notes: list[tuple[str, list[str]]] | None = None

    @classmethod
    def simple(cls, summary: str) -> CycleResult:
        """Convenience: create a CycleResult with defaults for everything except summary."""
        return cls(summary=summary)


class GovernanceAgent:
    """Base class for long-running governance agents.

    Handles:
    - MCP connection lifecycle (per-cycle connect/disconnect)
    - Identity resolution (UUID from file -> server lookup, or fresh onboard)
    - Session persistence (atomic file writes)
    - Check-in after each cycle
    - Heartbeat when idle
    - Graceful shutdown via SIGTERM/SIGINT

    Subclass and implement ``run_cycle()``::

        class MyAgent(GovernanceAgent):
            async def run_cycle(self, client: GovernanceClient) -> CycleResult | None:
                # do work
                return CycleResult.simple("processed 5 items")
    """

    def __init__(
        self,
        name: str,
        mcp_url: str = "http://127.0.0.1:8767/mcp/",
        state_dir: Path | None = None,
        session_file: Path | None = None,
        legacy_session_file: Path | None = None,
        notify_on_error: bool = True,
        timeout: float = 30.0,
        parent_agent_id: str | None = None,
        spawn_reason: str | None = None,
        persistent: bool = False,
        refuse_fresh_onboard: bool = False,
    ):
        self.name = name
        self.mcp_url = mcp_url
        self.timeout = timeout
        self.notify_on_error = notify_on_error
        # When True, stamp the "persistent" tag after fresh onboard so
        # auto_archive_orphan_agents (is_agent_protected in agent_lifecycle.py)
        # skips this identity. Resident agents (Vigil, Sentinel, etc.) should
        # set this to True to avoid sweep false-positives.
        self.persistent = persistent
        # Residents (Vigil, Sentinel, Watcher) set this True. When True,
        # _ensure_identity refuses to fresh-onboard if the anchor is
        # missing; the operator must set UNITARES_FIRST_RUN=1 to bootstrap
        # a new identity. Prevents the 2026-04-19 rotation-wipe silent-fork
        # class. See docs/superpowers/plans/2026-04-19-anchor-resilience-series.md
        self.refuse_fresh_onboard = refuse_fresh_onboard

        # Defaults based on name
        name_lower = name.lower()
        default_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        self.state_dir = state_dir or default_root / "data" / name_lower
        # Host-scoped anchor default: one identity per role per host, shared
        # across every git worktree or install path (Watcher/Vigil/Sentinel
        # previously minted a new UUID per install-path-relative session
        # file). Subclasses override session_file+legacy_session_file pair.
        self.session_file = session_file or (
            Path.home() / ".unitares" / "anchors" / f"{name_lower}.json"
        )
        self.legacy_session_file = legacy_session_file

        # Opt-in lineage: when set, forwarded to the server on fresh onboard
        # so spawned agents are distinguishable from unrelated siblings.
        self.parent_agent_id = parent_agent_id
        self.spawn_reason = spawn_reason

        # Runtime state
        self.running = True
        self.client_session_id: str | None = None
        self.continuity_token: str | None = None
        self.agent_uuid: str | None = None
        self._last_checkin_time: float = 0.0

    # --- Subclass interface ---

    async def run_cycle(self, client: GovernanceClient) -> CycleResult | None:
        """One unit of work. Return CycleResult for check-in, or None to skip."""
        raise NotImplementedError

    # --- Lifecycle ---

    async def run_once(self) -> None:
        """Single cycle: connect -> ensure_identity -> run_cycle -> checkin -> disconnect."""
        async with GovernanceClient(mcp_url=self.mcp_url, timeout=self.timeout) as client:
            await self._ensure_identity(client)
            result = await self.run_cycle(client)
            await self._handle_cycle_result(client, result)

    async def run_forever(
        self, interval: int = 60, heartbeat_interval: int = 1800
    ) -> None:
        """Loop: run_cycle repeatedly with heartbeat when idle."""
        self._install_signal_handlers()
        self._last_checkin_time = time.monotonic()

        while self.running:
            try:
                async with GovernanceClient(
                    mcp_url=self.mcp_url, timeout=self.timeout
                ) as client:
                    await self._ensure_identity(client)
                    result = await self.run_cycle(client)
                    await self._handle_cycle_result(client, result)

                    # Heartbeat if idle too long
                    elapsed = time.monotonic() - self._last_checkin_time
                    if elapsed >= heartbeat_interval and result is None:
                        await self._send_heartbeat(client)

            except (GovernanceConnectionError, GovernanceTimeoutError) as e:
                logger.warning("%s: governance unavailable: %s", self.name, e)
                if self.notify_on_error:
                    notify(self.name, f"Governance unavailable: {e}")
            except VerdictError as e:
                logger.warning("%s: verdict %s — %s", self.name, e.verdict, e.guidance)
                if self.notify_on_error:
                    notify(self.name, f"Verdict: {e.verdict}")
            except IdentityDriftError as e:
                logger.error("%s: %s", self.name, e)
                if self.notify_on_error:
                    notify(self.name, str(e))
            except Exception as e:
                logger.error("%s: unexpected error: %s", self.name, e, exc_info=True)
                if self.notify_on_error:
                    notify(self.name, f"Error: {e}")

            if self.running:
                await asyncio.sleep(interval)

    # --- Identity resolution ---

    async def _ensure_identity(self, client: GovernanceClient) -> None:
        """Identity resolution: UUID lookup (fast) or fresh onboard."""
        self._load_session()

        # Fast path: we know who we are — just tell the server
        if self.agent_uuid:
            # Identity Honesty Part C: server's PATH 0 now requires
            # continuity_token alongside agent_uuid. Copy the saved token to
            # the client so call_tool auto-injects it on this first request.
            if self.continuity_token and not client.continuity_token:
                client.continuity_token = self.continuity_token
            try:
                await client.identity(agent_uuid=self.agent_uuid, resume=True)
                self._sync_from_client(client)
                self._save_session()
                logger.info("%s: resumed via UUID %s", self.name, self.agent_uuid[:12])
                return
            except Exception as e:
                logger.error(
                    "%s: UUID lookup failed for %s: %s — refusing to create ghost",
                    self.name, self.agent_uuid[:12], e,
                )
                raise

        # First run — onboard, get a UUID, save it
        if self.refuse_fresh_onboard and os.environ.get("UNITARES_FIRST_RUN") != "1":
            from .errors import IdentityBootstrapRefused
            raise IdentityBootstrapRefused(
                f"{self.name}: anchor missing at {self.session_file}, and "
                "refuse_fresh_onboard=True. Either restore the anchor from a "
                "rotation backup, or run this agent once with UNITARES_FIRST_RUN=1 "
                "to explicitly bootstrap a new identity. Never silent-swap."
            )

        onboard_kwargs: dict[str, Any] = {}
        if self.parent_agent_id is not None:
            onboard_kwargs["parent_agent_id"] = self.parent_agent_id
        if self.spawn_reason is not None:
            onboard_kwargs["spawn_reason"] = self.spawn_reason
        await client.onboard(self.name, **onboard_kwargs)
        self._sync_from_client(client)
        self._save_session()
        logger.info("%s: onboarded fresh (UUID %s)", self.name, self.agent_uuid[:12] if self.agent_uuid else "?")

        if self.persistent and self.agent_uuid:
            try:
                await client.call_tool(
                    "update_agent_metadata",
                    {"agent_id": self.agent_uuid, "tags": ["persistent"]},
                )
                logger.info(
                    "%s: stamped 'persistent' tag to protect from orphan sweep",
                    self.name,
                )
            except Exception as e:
                # Non-fatal. The agent still runs; it's just vulnerable to
                # archive_orphan_agents until someone tags it manually.
                logger.warning(
                    "%s: failed to stamp 'persistent' tag: %s "
                    "(will retry on next fresh onboard; manual tagging may be needed)",
                    self.name, e,
                )

    # --- Check-in handling ---

    async def _handle_cycle_result(
        self, client: GovernanceClient, result: CycleResult | None
    ) -> None:
        """Process a cycle result: check in and post notes."""
        if result is None:
            return

        checkin_result = await client.checkin(
            response_text=result.summary,
            complexity=result.complexity,
            confidence=result.confidence,
            response_mode=result.response_mode,
        )
        self._last_checkin_time = time.monotonic()

        # Post any notes
        if result.notes:
            for summary, tags in result.notes:
                try:
                    await client.leave_note(summary=summary, tags=tags)
                except Exception as e:
                    logger.warning("%s: failed to leave note: %s", self.name, e)

        # Surface verdict
        verdict = checkin_result.verdict
        if verdict in ("pause", "reject"):
            raise VerdictError(verdict, checkin_result.guidance)

    async def _send_heartbeat(self, client: GovernanceClient) -> None:
        """Send a lightweight heartbeat check-in."""
        try:
            await client.checkin(
                response_text="heartbeat",
                complexity=0.05,
                confidence=0.9,
                response_mode="compact",
            )
            self._last_checkin_time = time.monotonic()
            logger.debug("%s: heartbeat sent", self.name)
        except Exception as e:
            logger.warning("%s: heartbeat failed: %s", self.name, e)

    # --- Session persistence ---

    def _load_session(self) -> None:
        """Load session state, migrating from legacy location if needed."""
        if (
            not self.session_file.exists()
            and self.legacy_session_file
            and self.legacy_session_file.exists()
        ):
            try:
                legacy_data = load_json_state(self.legacy_session_file)
                if legacy_data:
                    self.session_file.parent.mkdir(parents=True, exist_ok=True)
                    save_json_state(self.session_file, legacy_data)
                    logger.info(
                        "%s: migrated session from %s to %s",
                        self.name, self.legacy_session_file, self.session_file,
                    )
            except Exception as e:
                logger.warning("%s: legacy session migration failed: %s", self.name, e)

        saved = load_json_state(self.session_file)
        if saved.get("client_session_id"):
            self.client_session_id = saved["client_session_id"]
        if saved.get("continuity_token"):
            self.continuity_token = saved["continuity_token"]
        if saved.get("agent_uuid"):
            self.agent_uuid = saved["agent_uuid"]

    def _save_session(self) -> None:
        """Persist session state to the anchor."""
        data: dict[str, Any] = {}
        if self.client_session_id:
            data["client_session_id"] = self.client_session_id
        if self.continuity_token:
            data["continuity_token"] = self.continuity_token
        if self.agent_uuid:
            data["agent_uuid"] = self.agent_uuid
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        save_json_state(self.session_file, data)

    def _sync_from_client(self, client: GovernanceClient) -> None:
        """Copy identity state from client after successful identity/onboard."""
        if client.client_session_id:
            self.client_session_id = client.client_session_id
        if client.continuity_token:
            self.continuity_token = client.continuity_token
        if client.agent_uuid:
            if self.agent_uuid and client.agent_uuid != self.agent_uuid:
                raise IdentityDriftError(self.agent_uuid, client.agent_uuid)
            self.agent_uuid = client.agent_uuid

    # --- State persistence ---

    def load_state(self) -> dict:
        """Load agent-specific cross-cycle state from state_dir."""
        return load_json_state(self.state_dir / "state.json")

    def save_state(self, state: dict) -> None:
        """Save agent-specific cross-cycle state to state_dir."""
        save_json_state(self.state_dir / "state.json", state)

    # --- Signal handlers ---

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

    def _handle_signal(self, sig: int | signal.Signals) -> None:
        sig_name = sig.name if hasattr(sig, "name") else str(sig)
        logger.info("%s: received %s, shutting down gracefully", self.name, sig_name)
        self.running = False
