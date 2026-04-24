"""
Session key derivation, fingerprinting, and onboard pin operations.

Leaf module — no imports from other identity_* sub-modules.
"""

from __future__ import annotations

from typing import Optional, Dict, Any
import os
import hashlib
import base64
import hmac
import json
import time

from src.logging_utils import get_logger

logger = get_logger(__name__)

_S1_DEPRECATION_SUNSET = "2026-Q4"  # operator-set placeholder; see s1 doc §11
_PIN_TTL = 1800  # 30 minutes — refresh on use
# S1-a (2026-04-24): shrunk from 30 days to 1 hour as part of continuity_token
# retirement-via-narrowing. See docs/ontology/s1-continuity-token-retirement.md §4.1.
# TTL-only is not process-instance binding; this is honestly "performative, narrowed".
# A′ (PID/nonce binding) is the follow-on for actual earned process-scope.
_CONTINUITY_TTL = 3600  # 1 hour
_OWNERSHIP_PROOF_VERSION = 1  # bump to 2 when A′ lands; to 3 when R1-composite ships


def continuity_token_support_status() -> Dict[str, Any]:
    """Return continuity token support details for diagnostics."""
    if os.getenv("UNITARES_CONTINUITY_TOKEN_SECRET"):
        return {
            "enabled": True,
            "secret_source": "UNITARES_CONTINUITY_TOKEN_SECRET",
            "ownership_proof_version": _OWNERSHIP_PROOF_VERSION,
        }
    if os.getenv("UNITARES_HTTP_API_TOKEN"):
        return {
            "enabled": True,
            "secret_source": "UNITARES_HTTP_API_TOKEN",
            "ownership_proof_version": _OWNERSHIP_PROOF_VERSION,
        }
    if os.getenv("UNITARES_API_TOKEN"):
        return {
            "enabled": True,
            "secret_source": "UNITARES_API_TOKEN",
            "ownership_proof_version": _OWNERSHIP_PROOF_VERSION,
        }
    return {"enabled": False, "secret_source": None}


def build_token_deprecation_block(
    *,
    used_token_for_resume: bool,
    token_issued_at: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Return a deprecation-warning dict for cross-instance resume, or None.

    S1-a (2026-04-24): onboard() called with continuity_token (without
    force_new=true) is the retired cross-process-instance resume path. During
    the grace period the server still accepts these but emits a warning in
    the response so callers can migrate.

    Intra-session uses (mid-session identity() rebind, request auth via
    continuity_token on process_agent_update, etc.) are NOT deprecated —
    they're role (3) from s1 doc §1, the anti-hijack proof-of-ownership
    surface that Part-C relies on.

    Args:
        used_token_for_resume: True iff onboard was called with
            continuity_token and without force_new=true.
        token_issued_at: Token's `iat` claim. Optional; carried through for
            grace-period telemetry if the caller has it handy.
    """
    if not used_token_for_resume:
        return None
    block: Dict[str, Any] = {
        "field": "continuity_token",
        "severity": "warning",
        "message": (
            "cross-process-instance resume via continuity_token is deprecated; "
            "declare lineage via parent_agent_id on force_new=true. "
            "See docs/ontology/s1-continuity-token-retirement.md."
        ),
        "sunset": _S1_DEPRECATION_SUNSET,
    }
    if token_issued_at is not None:
        block["token_issued_at"] = int(token_issued_at)
    return block


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_continuity_secret() -> Optional[bytes]:
    """Get the HMAC secret used for continuity tokens."""
    secret = (
        os.getenv("UNITARES_CONTINUITY_TOKEN_SECRET")
        or os.getenv("UNITARES_HTTP_API_TOKEN")
        or os.getenv("UNITARES_API_TOKEN")
    )
    if not secret:
        return None
    return secret.encode()


def create_continuity_token(
    agent_uuid: str,
    client_session_id: str,
    *,
    model_type: Optional[str] = None,
    client_hint: Optional[str] = None,
    ttl_seconds: int = _CONTINUITY_TTL,
) -> Optional[str]:
    """Create a signed continuity token for robust session resumption."""
    secret = _get_continuity_secret()
    if not secret or not client_session_id or not agent_uuid:
        return None

    now = int(time.time())
    payload = {
        "v": 1,
        "opv": _OWNERSHIP_PROOF_VERSION,  # S1-a: forward-compat ownership-proof schema version
        "sid": str(client_session_id),
        "aid": str(agent_uuid),
        "mf": _normalize_pin_model_type(model_type),
        "ch": _normalize_pin_client_hint(client_hint),
        "iat": now,
        "exp": now + max(60, int(ttl_seconds)),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64 = _b64url_encode(payload_json)
    sig_b64 = _b64url_encode(hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest())
    return f"v1.{payload_b64}.{sig_b64}"


def extract_token_iat(token: str) -> Optional[int]:
    """Extract the `iat` (issued-at) claim from a continuity token.

    Signature-verified like `extract_token_agent_uuid`; does NOT check expiry.
    Returned for grace-period telemetry under S1-a (docs/ontology/
    s1-continuity-token-retirement.md §6) — callers need `iat` to compute
    token lifetime at accept-time.
    """
    if not token or not isinstance(token, str):
        return None
    secret = _get_continuity_secret()
    if not secret:
        return None
    try:
        version, payload_b64, sig_b64 = token.split(".", 2)
        if version != "v1":
            return None
        expected_sig = _b64url_encode(hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected_sig, sig_b64):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        iat = payload.get("iat")
        if iat is None:
            return None
        return int(iat)
    except Exception:
        return None


def extract_token_agent_uuid(token: str) -> Optional[str]:
    """Extract agent UUID from a continuity token after signature verification.

    Unlike resolve_continuity_token, this does NOT check expiry — an expired
    token still proves identity. Used for direct agent lookup when session
    bindings have expired but the agent still exists.

    Rationale (PR #42 Part C): a resident whose process has been idle 30+ days
    should still be able to resume with their stale token, since re-onboarding
    would fork identity and lose continuity. Signature verification alone is
    sufficient proof of ownership for this path — freshness is not required.

    If a future caller needs true freshness, add a separate
    `verify_token_fresh(token)` rather than tightening this function. Callers
    that rely on resume-after-long-idle will regress silently if `exp` starts
    being enforced here.
    """
    if not token or not isinstance(token, str):
        return None
    secret = _get_continuity_secret()
    if not secret:
        return None
    try:
        version, payload_b64, sig_b64 = token.split(".", 2)
        if version != "v1":
            return None
        expected_sig = _b64url_encode(hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected_sig, sig_b64):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        aid = payload.get("aid")
        if not aid or not isinstance(aid, str):
            return None
        return aid
    except Exception:
        return None


def resolve_continuity_token(
    token: str,
    *,
    model_type: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[str]:
    """Verify and resolve continuity token to client_session_id."""
    if not token or not isinstance(token, str):
        return None
    secret = _get_continuity_secret()
    if not secret:
        return None

    try:
        version, payload_b64, sig_b64 = token.split(".", 2)
        if version != "v1":
            return None

        expected_sig = _b64url_encode(hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected_sig, sig_b64):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None

        sid = payload.get("sid")
        if not sid or not isinstance(sid, str):
            return None

        expected_model = _normalize_pin_model_type(model_type, user_agent)
        token_model = payload.get("mf")
        if expected_model and token_model and token_model != expected_model:
            return None

        return sid
    except Exception:
        return None


def _normalize_pin_client_hint(client_hint: Optional[str]) -> Optional[str]:
    """Normalize client hint for scoped pin keys."""
    if not client_hint:
        return None
    normalized = str(client_hint).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _normalize_pin_model_type(
    model_type: Optional[str],
    user_agent: Optional[str] = None,
) -> Optional[str]:
    """Normalize model family for scoped pin keys.

    Falls back to coarse user-agent inference when explicit model_type is absent.
    """
    raw = (model_type or "").strip().lower()

    # Coarse UA fallback keeps pinning deterministic without importing identity resolution.
    if not raw and user_agent:
        ua = user_agent.lower()
        if "codex" in ua or "chatgpt" in ua or "openai" in ua or "gpt" in ua:
            raw = "gpt"
        elif "claude" in ua or "anthropic" in ua:
            raw = "claude"
        elif "gemini" in ua or "google" in ua:
            raw = "gemini"
        elif "llama" in ua:
            raw = "llama"

    if not raw:
        return None

    normalized = raw.replace("-", "_").replace(".", "_")
    if "claude" in normalized:
        return "claude"
    if "gemini" in normalized:
        return "gemini"
    if "gpt" in normalized or "chatgpt" in normalized or "codex" in normalized or "openai" in normalized:
        return "gpt"
    if "llama" in normalized:
        return "llama"
    if "composer" in normalized or "cursor" in normalized:
        return "composer"
    return normalized


def _build_pin_fingerprint_candidates(
    base_fingerprint: str,
    *,
    client_hint: Optional[str] = None,
    model_type: Optional[str] = None,
    user_agent: Optional[str] = None,
    include_unscoped_fallback: bool = True,
) -> list[str]:
    """Build pin-key candidates ordered from most to least specific."""
    if not base_fingerprint:
        return []

    client = _normalize_pin_client_hint(client_hint)
    model = _normalize_pin_model_type(model_type, user_agent)
    candidates: list[str] = []

    if client and model:
        candidates.append(f"{base_fingerprint}|{client}|{model}")
    if client:
        candidates.append(f"{base_fingerprint}|{client}")
    if model:
        candidates.append(f"{base_fingerprint}|{model}")
    if include_unscoped_fallback:
        candidates.append(base_fingerprint)

    # Preserve order while deduplicating
    seen = set()
    ordered = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


async def derive_session_key(
    signals: "Optional[SessionSignals]" = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> str:
    """Single source of truth for session key derivation.

    Priority (highest to lowest):
    1. arguments["continuity_token"]   — signed resume token (preferred)
    2. arguments["client_session_id"]  — explicit from caller
    3. MCP protocol session ID         — stable, no pin needed
    4. Explicit HTTP session header     — stable, no pin needed
    5. OAuth client identity            — stable, no pin needed
    6. Explicit client ID header        — stable-ish
    7. IP:UA fingerprint + pin lookup   — unstable, needs pin
    8. Contextvars fallback             — backward compat (remove once all callers pass signals)
    9. stdio fallback                   — single-user / Claude Desktop
    """
    from ..context import SessionSignals  # type hint import

    arguments = arguments or {}

    def _mark(source: str) -> None:
        try:
            from ..context import set_session_resolution_source
            set_session_resolution_source(source)
        except Exception:
            pass

    # 1. Signed continuity token (preferred over raw IDs when provided)
    if arguments.get("continuity_token"):
        resolved = resolve_continuity_token(
            str(arguments["continuity_token"]),
            model_type=arguments.get("model_type"),
            user_agent=signals.user_agent if signals else None,
        )
        if resolved:
            _mark("continuity_token")
            return resolved
        _mark("continuity_token_invalid")

    # 2. Explicit from arguments
    if arguments.get("client_session_id"):
        explicit = str(arguments["client_session_id"])
        # agent-{uuid} IDs are globally unique by construction — skip model-
        # family scoping.  Appending ":claude" creates a key mismatch between
        # REST-onboarded sessions (curl UA → no suffix) and MCP lookups
        # (Claude UA → ":claude" suffix), breaking bind_session.
        if explicit.startswith("agent-"):
            _mark("explicit_client_session_id")
            return explicit
        explicit_model = _normalize_pin_model_type(
            arguments.get("model_type"),
            signals.user_agent if signals else None,
        )
        # Harden against cross-model identity bleed when a caller reuses the
        # same client_session_id across multiple model families.
        if explicit_model:
            if explicit.endswith(f":{explicit_model}"):
                _mark("explicit_client_session_id")
                return explicit
            _mark("explicit_client_session_id_scoped")
            return f"{explicit}:{explicit_model}"
        _mark("explicit_client_session_id")
        return explicit

    # 3. MCP protocol session ID (stable, no pin needed)
    if signals and signals.mcp_session_id:
        _mark("mcp_session_id")
        return f"mcp:{signals.mcp_session_id}"

    # 4. Explicit HTTP session header (stable, no pin needed)
    if signals and signals.x_session_id:
        _mark("x_session_id")
        return signals.x_session_id

    # 5. OAuth client identity (stable, no pin needed)
    if signals and signals.oauth_client_id:
        _mark("oauth_client_id")
        return signals.oauth_client_id

    # 6. Explicit client ID header
    if signals and signals.x_client_id:
        _mark("x_client_id")
        return signals.x_client_id

    # 7. IP:UA fingerprint with integrated pin lookup
    if signals and signals.ip_ua_fingerprint:
        base_fp = _extract_base_fingerprint(signals.ip_ua_fingerprint)
        if base_fp:
            hint = (arguments.get("client_hint") or signals.client_hint) if arguments else signals.client_hint
            model = arguments.get("model_type") if arguments else None
            scoped_candidates = _build_pin_fingerprint_candidates(
                base_fp,
                client_hint=hint,
                model_type=model,
                user_agent=signals.user_agent,
                # If we have scope signals, do NOT fall back to unscoped pin to
                # avoid cross-model/session identity bleed.
                include_unscoped_fallback=not bool(hint or model),
            )
            for candidate in scoped_candidates:
                pinned = await lookup_onboard_pin(candidate)
                if pinned:
                    _mark("pinned_onboard_session")
                    return pinned
        _mark("ip_ua_fingerprint")
        return signals.ip_ua_fingerprint

    # 8. Fallback: contextvars (for callers without signals)
    # Backward compat — remove once all callers pass signals
    try:
        from ..context import get_mcp_session_id, get_context_session_key
        mcp_sid = get_mcp_session_id()
        if mcp_sid:
            _mark("context_mcp_session_id")
            return f"mcp:{mcp_sid}"
        ctx_key = get_context_session_key()
        if ctx_key:
            _mark("context_session_key")
            return str(ctx_key)
    except Exception:
        pass

    # 9. stdio fallback
    _mark("stdio_fallback")
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


async def set_onboard_pin(
    base_fingerprint: str,
    agent_uuid: str,
    client_session_id: str,
    *,
    client_hint: Optional[str] = None,
    model_type: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
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
        candidates = _build_pin_fingerprint_candidates(
            base_fingerprint,
            client_hint=client_hint,
            model_type=model_type,
            user_agent=user_agent,
            # If we can scope by model/client, avoid writing unscoped pin to
            # prevent collisions across mixed-model traffic sharing one UA hash.
            include_unscoped_fallback=not bool(client_hint or model_type),
        )
        if not candidates:
            return False

        pin_data = _json.dumps({
            "agent_uuid": agent_uuid,
            "client_session_id": client_session_id,
        })
        for fp in candidates:
            pin_key = f"recent_onboard:{fp}"
            await raw_redis.setex(pin_key, _PIN_TTL, pin_data)
            logger.info(f"[ONBOARD_PIN] Set {pin_key} -> {agent_uuid[:8]}...")
        return True
    except Exception as e:
        logger.warning(f"[ONBOARD_PIN] Could not set pin: {e}")
        return False
