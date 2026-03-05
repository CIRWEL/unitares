"""
Session key derivation, fingerprinting, and onboard pin operations.

Leaf module — no imports from other identity_* sub-modules.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
import os
import hashlib

from src.logging_utils import get_logger

logger = get_logger(__name__)

_PIN_TTL = 1800  # 30 minutes — refresh on use


async def derive_session_key(
    signals: "Optional[SessionSignals]" = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> str:
    """Single source of truth for session key derivation.

    Priority (highest to lowest):
    1. arguments["client_session_id"]  — explicit from caller
    2. MCP protocol session ID         — stable, no pin needed
    3. Explicit HTTP session header     — stable, no pin needed
    4. OAuth client identity            — stable, no pin needed
    5. Explicit client ID header        — stable-ish
    6. IP:UA fingerprint + pin lookup   — unstable, needs pin
    7. Contextvars fallback             — backward compat (remove once all callers pass signals)
    8. stdio fallback                   — single-user / Claude Desktop
    """
    from .context import SessionSignals  # type hint import

    arguments = arguments or {}

    # 1. Explicit from arguments (highest priority)
    if arguments.get("client_session_id"):
        return str(arguments["client_session_id"])

    # 2. MCP protocol session ID (stable, no pin needed)
    if signals and signals.mcp_session_id:
        return f"mcp:{signals.mcp_session_id}"

    # 3. Explicit HTTP session header (stable, no pin needed)
    if signals and signals.x_session_id:
        return signals.x_session_id

    # 4. OAuth client identity (stable, no pin needed)
    if signals and signals.oauth_client_id:
        return signals.oauth_client_id

    # 5. Explicit client ID header
    if signals and signals.x_client_id:
        return signals.x_client_id

    # 6. IP:UA fingerprint with integrated pin lookup
    if signals and signals.ip_ua_fingerprint:
        base_fp = _extract_base_fingerprint(signals.ip_ua_fingerprint)
        if base_fp:
            pinned = await lookup_onboard_pin(base_fp)
            if pinned:
                return pinned
        return signals.ip_ua_fingerprint

    # 7. Fallback: contextvars (for callers without signals)
    # Backward compat — remove once all callers pass signals
    try:
        from .context import get_mcp_session_id, get_context_session_key
        mcp_sid = get_mcp_session_id()
        if mcp_sid:
            return f"mcp:{mcp_sid}"
        ctx_key = get_context_session_key()
        if ctx_key:
            return str(ctx_key)
    except Exception:
        pass

    # 8. stdio fallback
    return f"stdio:{os.getpid()}"


def _extract_base_fingerprint(session_key: str) -> Optional[str]:
    """Extract stable base fingerprint from a session key.

    For HTTP transports, session keys follow the pattern IP:UA_hash or
    IP:UA_hash:random_suffix. Claude.ai's proxy pool rotates IPs per
    request, so we pin by UA_hash ONLY — the UA string is stable across
    requests from the same conversation/model.

    Returns None for keys that already provide stable identity (mcp:*,
    stdio:*, agent-*) since those don't need onboard pinning.
    """
    if not session_key:
        return None
    # Keys with stable identity don't need pinning
    if session_key.startswith(("mcp:", "stdio:", "agent-", "oauth:")):
        logger.debug(f"[ONBOARD_PIN] Skipping stable key: {session_key[:30]}...")
        return None
    # Pattern: IP:UA_hash or IP:UA_hash:random_suffix or IP:UA_hash:model_hint
    # Pin by UA_hash only (parts[1]) — IP rotates across Claude.ai proxy pool
    parts = session_key.split(":")
    if len(parts) >= 2:
        ua_hash = parts[1]
        logger.debug(f"[ONBOARD_PIN] extract_fp: raw={session_key!r} ({len(parts)} parts) -> ua_hash={ua_hash!r}")
        return f"ua:{ua_hash}"
    # Single-part key (unusual) — return as-is
    logger.debug(f"[ONBOARD_PIN] extract_fp: raw={session_key!r} (single part) -> as-is")
    return session_key


def ua_hash_from_header(user_agent: str) -> Optional[str]:
    """Compute the canonical UA hash from a raw User-Agent string.

    This is the SINGLE SOURCE OF TRUTH for UA hash computation.
    Both REST and MCP paths must use this to ensure pin keys match.

    Returns: "ua:{md5_prefix}" or None if no user_agent.
    """
    if not user_agent:
        return None
    ua_hash = hashlib.md5(user_agent.encode()).hexdigest()[:6]
    return f"ua:{ua_hash}"


async def lookup_onboard_pin(base_fingerprint: str, *, refresh_ttl: bool = True) -> Optional[str]:
    """Look up a pinned client_session_id from a recent onboard.

    Shared by REST path (_extract_client_session_id) and MCP dispatcher
    (dispatch_tool) to eliminate duplication and divergence risk.

    Args:
        base_fingerprint: Output of _extract_base_fingerprint() or ua_hash_from_header(),
                          e.g. "ua:d20c2f"
        refresh_ttl: Whether to extend the pin's TTL on successful lookup (default True)

    Returns: The pinned client_session_id, or None.
    """
    if not base_fingerprint:
        return None
    try:
        from src.cache.redis_client import get_redis
        import json as _json
        raw_redis = await get_redis()
        if not raw_redis:
            return None
        pin_key = f"recent_onboard:{base_fingerprint}"
        pin_data = await raw_redis.get(pin_key)
        if not pin_data:
            logger.debug(f"[ONBOARD_PIN] No pin at {pin_key}")
            return None
        pin = _json.loads(pin_data if isinstance(pin_data, str) else pin_data.decode())
        pinned_session_id = pin.get("client_session_id")
        if pinned_session_id and refresh_ttl:
            await raw_redis.expire(pin_key, _PIN_TTL)
        return pinned_session_id
    except Exception as e:
        logger.debug(f"[ONBOARD_PIN] Pin lookup failed: {e}")
        return None


async def set_onboard_pin(base_fingerprint: str, agent_uuid: str, client_session_id: str) -> bool:
    """Set a pin mapping a transport fingerprint to an onboarded agent.

    Called by handle_onboard_v2() after successful onboard.

    Args:
        base_fingerprint: Output of _extract_base_fingerprint(), e.g. "ua:d20c2f"
        agent_uuid: The newly onboarded agent's UUID
        client_session_id: The stable session ID to inject on subsequent calls

    Returns: True if the pin was set successfully.
    """
    if not base_fingerprint:
        logger.debug("[ONBOARD_PIN] No fingerprint — skip pin-set")
        return False
    try:
        from src.cache.redis_client import get_redis
        import json as _json
        raw_redis = await get_redis()
        if not raw_redis:
            logger.warning("[ONBOARD_PIN] Redis not available for pin-setting")
            return False
        pin_key = f"recent_onboard:{base_fingerprint}"
        pin_data = _json.dumps({
            "agent_uuid": agent_uuid,
            "client_session_id": client_session_id,
        })
        await raw_redis.setex(pin_key, _PIN_TTL, pin_data)
        logger.info(f"[ONBOARD_PIN] Set {pin_key} -> {agent_uuid[:8]}...")
        return True
    except Exception as e:
        logger.warning(f"[ONBOARD_PIN] Could not set pin: {e}")
        return False
