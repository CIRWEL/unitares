"""GovernanceAgent — lifecycle base class for long-running UNITARES agents."""

from __future__ import annotations

import asyncio
import logging
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
    parse_continuity_token,
    save_json_state,
    validate_token_uuid,
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
    - Identity resolution (token resume -> name resume -> fresh onboard)
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
        notify_on_error: bool = True,
        timeout: float = 30.0,
    ):
        self.name = name
        self.mcp_url = mcp_url
        self.timeout = timeout
        self.notify_on_error = notify_on_error

        # Defaults based on name
        name_lower = name.lower()
        default_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        self.state_dir = state_dir or default_root / "data" / name_lower
        self.session_file = session_file or default_root / f".{name_lower}_session"

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
        """Three-step identity resolution: token -> name -> onboard."""
        self._load_session()

        # Step 1: Token resume (strong)
        if self.continuity_token:
            if self.agent_uuid and not validate_token_uuid(
                self.continuity_token, self.agent_uuid
            ):
                logger.warning(
                    "%s: stale token detected (wrong agent UUID) — discarding",
                    self.name,
                )
                if self.notify_on_error:
                    notify(self.name, "Stale token detected (wrong agent UUID)")
                self.continuity_token = None
            else:
                # If no UUID yet, extract from token to set expectation
                payload = parse_continuity_token(self.continuity_token)
                if payload and payload.get("aid") and not self.agent_uuid:
                    self.agent_uuid = payload["aid"]

                try:
                    result = await client.identity(
                        continuity_token=self.continuity_token, resume=True
                    )
                    self._sync_from_client(client)
                    self._save_session()
                    logger.info("%s: resumed via token", self.name)
                    return
                except IdentityDriftError as e:
                    # Token HMAC may have failed (e.g., server secret rotated),
                    # causing server to resolve a different identity via fallback.
                    # Discard stale token and fall through to name resume.
                    logger.warning(
                        "%s: token resume caused identity drift "
                        "(expected %s, got %s) — discarding token, trying name resume",
                        self.name, e.expected_uuid[:12], e.received_uuid[:12],
                    )
                    self.continuity_token = None
                    client.agent_uuid = self.agent_uuid  # restore expected UUID
                except Exception as e:
                    logger.warning("%s: token resume failed: %s", self.name, e)

        # Step 2: Name resume (weak)
        try:
            result = await client.identity(name=self.name, resume=True)
            self._sync_from_client(client)
            self._save_session()
            logger.info("%s: resumed via name", self.name)
            return
        except IdentityDriftError:
            raise
        except Exception as e:
            logger.warning("%s: name resume failed: %s", self.name, e)

        # Step 3: Fresh onboard
        result = await client.onboard(self.name)
        self._sync_from_client(client)
        self._save_session()
        logger.info("%s: onboarded fresh", self.name)

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
        """Load session state from disk."""
        saved = load_json_state(self.session_file)
        if saved.get("client_session_id"):
            self.client_session_id = saved["client_session_id"]
        if saved.get("continuity_token"):
            self.continuity_token = saved["continuity_token"]
        if saved.get("agent_uuid"):
            self.agent_uuid = saved["agent_uuid"]

    def _save_session(self) -> None:
        """Persist session state to disk."""
        data: dict[str, Any] = {}
        if self.client_session_id:
            data["client_session_id"] = self.client_session_id
        if self.continuity_token:
            data["continuity_token"] = self.continuity_token
        if self.agent_uuid:
            data["agent_uuid"] = self.agent_uuid
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
