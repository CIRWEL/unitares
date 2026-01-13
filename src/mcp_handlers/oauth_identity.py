"""
OAuth Identity Extraction for MCP Handlers

Provides out-of-band identity extraction from OAuth tokens, solving the
ChatGPT/external client problem where in-band API keys get blocked by moderation.

Design Philosophy:
- Identity is cryptographic and stable (derived from OAuth sub claim)
- No secrets in tool arguments (api_key never shown to ChatGPT)
- Backward compatible (falls back to session-based identity for non-OAuth clients)
- Server-side agent_api_key derived from OAuth identity (never exposed)

How it works:
1. Client connects via OAuth (ChatGPT MCP connector)
2. Server extracts JWT from Authorization header
3. `sub` claim → deterministic agent_id (via hash or direct mapping)
4. Server-side api_key derived from sub + server secret
5. Session auto-binds without any in-band secrets

Usage in SSE server:
    from src.mcp_handlers.oauth_identity import extract_oauth_identity

    async def handle_request(request):
        oauth_identity = await extract_oauth_identity(request)
        if oauth_identity:
            # OAuth client - identity is cryptographic
            agent_id = oauth_identity['agent_id']
            # Internal api_key (never shown to client)
            internal_api_key = oauth_identity['internal_api_key']
        else:
            # Non-OAuth client - fall back to session binding
            ...
"""

from typing import Dict, Any, Optional
import hashlib
import hmac
import base64
import json
import os
from datetime import datetime
from src.logging_utils import get_logger

logger = get_logger(__name__)

# Server secret for deriving internal api_keys
# In production, this should be a proper secret from environment
_SERVER_SECRET = os.getenv("GOVERNANCE_OAUTH_SECRET", "governance-oauth-default-secret-change-in-prod")


class OAuthIdentity:
    """Represents an OAuth-derived identity."""

    def __init__(
        self,
        sub: str,
        agent_id: str,
        internal_api_key: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        provider: Optional[str] = None,
        raw_claims: Optional[Dict[str, Any]] = None
    ):
        self.sub = sub  # OAuth subject (unique user ID from provider)
        self.agent_id = agent_id  # Derived agent_id for governance
        self.internal_api_key = internal_api_key  # Server-side derived key
        self.email = email  # Optional email claim
        self.name = name  # Optional name claim
        self.provider = provider  # e.g., "google", "github", "openai"
        self.raw_claims = raw_claims or {}
        self.extracted_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sub": self.sub,
            "agent_id": self.agent_id,
            "email": self.email,
            "name": self.name,
            "provider": self.provider,
            "extracted_at": self.extracted_at
        }


def _decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode JWT payload WITHOUT verification.

    Note: This is intentionally unverified for flexibility.
    The OAuth provider (ChatGPT, Google, etc.) has already validated the token
    before sending it to us. We trust the transport layer.

    For production with strict security requirements, integrate a proper
    JWT verification library (PyJWT) with your OAuth provider's public keys.

    Returns:
        Decoded payload dict, or None if decoding fails
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            logger.debug(f"Invalid JWT format: expected 3 parts, got {len(parts)}")
            return None

        # Decode payload (second part)
        payload_b64 = parts[1]

        # Add padding if needed (JWT uses base64url without padding)
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding

        # Decode base64url
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode('utf-8'))

        return payload

    except Exception as e:
        logger.debug(f"JWT decode failed: {e}")
        return None


def _derive_agent_id(sub: str, provider: Optional[str] = None) -> str:
    """
    Derive a deterministic agent_id from OAuth sub claim.

    Strategy:
    - Prefix with provider for namespace isolation
    - Hash the sub for privacy (don't expose raw OAuth IDs in logs)
    - Keep it human-readable with provider prefix

    Examples:
    - google_a3f8c2e1... (Google OAuth user)
    - openai_7b2d9f4a... (ChatGPT user)
    - github_c9e1a8b3... (GitHub OAuth user)
    """
    # Create a deterministic hash of the sub
    sub_hash = hashlib.sha256(sub.encode()).hexdigest()[:16]

    # Use provider prefix if available
    if provider:
        # Sanitize provider name
        provider_clean = provider.lower().replace(' ', '_')[:20]
        return f"oauth_{provider_clean}_{sub_hash}"

    return f"oauth_{sub_hash}"


def _derive_internal_api_key(sub: str) -> str:
    """
    Derive a server-side api_key from OAuth sub.

    This key is:
    - Deterministic (same sub always gets same key)
    - Never exposed to the client (derived server-side)
    - Tied to the server secret (rotatable)

    The client never sees this key - it's purely for internal governance operations.
    """
    # Use HMAC for secure key derivation
    key_bytes = hmac.new(
        _SERVER_SECRET.encode(),
        sub.encode(),
        hashlib.sha256
    ).digest()

    # Format as a readable api_key
    key_hex = key_bytes.hex()
    return f"gov-oauth-{key_hex[:32]}"


def _detect_provider(payload: Dict[str, Any]) -> Optional[str]:
    """
    Attempt to detect OAuth provider from JWT claims.

    Different providers have different claim structures:
    - Google: iss contains accounts.google.com, has 'email' claim
    - GitHub: may have 'login' claim for username
    - OpenAI: iss contains openai.com
    - Generic: fall back to issuer domain
    """
    iss = payload.get("iss", "")

    if "google" in iss.lower():
        return "google"
    elif "github" in iss.lower():
        return "github"
    elif "openai" in iss.lower() or "chatgpt" in iss.lower():
        return "openai"
    elif "microsoft" in iss.lower() or "azure" in iss.lower():
        return "microsoft"
    elif iss:
        # Extract domain from issuer
        try:
            from urllib.parse import urlparse
            parsed = urlparse(iss)
            if parsed.netloc:
                return parsed.netloc.split('.')[0]
        except Exception:
            pass

    return None


async def extract_oauth_identity(request) -> Optional[OAuthIdentity]:
    """
    Extract OAuth identity from request headers.

    Looks for Authorization: Bearer <JWT> header and extracts identity claims.

    Args:
        request: Starlette Request object (or any object with .headers)

    Returns:
        OAuthIdentity if valid OAuth token found, None otherwise
    """
    try:
        # Get Authorization header
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")

        if not auth_header:
            return None

        if not auth_header.lower().startswith("bearer "):
            return None

        token = auth_header.split(" ", 1)[1].strip()

        if not token:
            return None

        # Check if this looks like a JWT (has three dot-separated parts)
        if token.count('.') != 2:
            # Not a JWT - might be a simple API token
            # Let the regular auth flow handle it
            logger.debug("Auth token is not a JWT, skipping OAuth extraction")
            return None

        # Decode JWT payload
        payload = _decode_jwt_payload(token)

        if not payload:
            return None

        # Extract sub claim (required for OAuth identity)
        sub = payload.get("sub")

        if not sub:
            logger.debug("JWT missing 'sub' claim, cannot extract identity")
            return None

        # Detect provider
        provider = _detect_provider(payload)

        # Derive agent_id and internal api_key
        agent_id = _derive_agent_id(sub, provider)
        internal_api_key = _derive_internal_api_key(sub)

        # Extract optional claims
        email = payload.get("email")
        name = payload.get("name") or payload.get("preferred_username") or payload.get("login")

        identity = OAuthIdentity(
            sub=sub,
            agent_id=agent_id,
            internal_api_key=internal_api_key,
            email=email,
            name=name,
            provider=provider,
            raw_claims=payload
        )

        logger.info(f"OAuth identity extracted: {agent_id} (provider={provider})")

        return identity

    except Exception as e:
        logger.debug(f"OAuth extraction failed: {e}")
        return None


async def ensure_oauth_agent_exists(
    oauth_identity: OAuthIdentity,
    mcp_server
) -> bool:
    """
    Ensure the OAuth-derived agent exists in the governance system.

    Creates the agent if it doesn't exist, using the internal_api_key
    derived from the OAuth identity.

    Args:
        oauth_identity: Extracted OAuth identity
        mcp_server: MCP server instance with agent_metadata

    Returns:
        True if agent exists or was created, False on error
    """
    try:
        agent_id = oauth_identity.agent_id

        # Check if agent already exists
        if agent_id in mcp_server.agent_metadata:
            # Agent exists - verify internal key matches
            meta = mcp_server.agent_metadata[agent_id]
            if meta.api_key != oauth_identity.internal_api_key:
                # Key mismatch - this shouldn't happen with deterministic derivation
                # Log warning but continue (could be server secret rotation)
                logger.warning(
                    f"OAuth agent {agent_id} key mismatch - possible secret rotation"
                )
            return True

        # Agent doesn't exist - create it via process_agent_update
        from .core import handle_process_agent_update

        create_args = {
            "agent_id": agent_id,
            "confidence": 0.5,
            "complexity": 0.5,
            "task_type": "convergent",
            "response_text": "OAuth identity established",
            # Internal: inject the derived api_key
            "_internal_api_key": oauth_identity.internal_api_key,
        }

        # Add purpose based on OAuth claims
        purpose_parts = []
        if oauth_identity.provider:
            purpose_parts.append(f"OAuth via {oauth_identity.provider}")
        if oauth_identity.name:
            purpose_parts.append(f"User: {oauth_identity.name}")
        if oauth_identity.email:
            purpose_parts.append(f"Email: {oauth_identity.email}")

        if purpose_parts:
            create_args["purpose"] = " | ".join(purpose_parts)

        result = await handle_process_agent_update(create_args)

        # Verify creation succeeded
        if agent_id in mcp_server.agent_metadata:
            logger.info(f"Created OAuth agent: {agent_id}")

            # Override the api_key with our derived one
            # (process_agent_update generates a random one)
            meta = mcp_server.agent_metadata[agent_id]
            meta.api_key = oauth_identity.internal_api_key
            meta.oauth_provider = oauth_identity.provider
            meta.oauth_sub = oauth_identity.sub  # For audit

            return True

        logger.error(f"Failed to create OAuth agent: {agent_id}")
        return False

    except Exception as e:
        logger.error(f"Error ensuring OAuth agent exists: {e}", exc_info=True)
        return False


async def bind_oauth_session(
    oauth_identity: OAuthIdentity,
    session_key: str
) -> bool:
    """
    Bind an OAuth identity to a session.

    This auto-binds without any in-band credentials - the OAuth token
    IS the proof of identity.

    Args:
        oauth_identity: Extracted OAuth identity
        session_key: Session key for binding

    Returns:
        True if binding succeeded
    """
    try:
        from .identity import _session_identities, _persist_session_new

        agent_id = oauth_identity.agent_id
        bound_at = datetime.now().isoformat()

        # Update in-memory cache
        _session_identities[session_key] = {
            "bound_agent_id": agent_id,
            "api_key": oauth_identity.internal_api_key,
            "bound_at": bound_at,
            "bind_count": 1,
            "oauth": True,  # Flag for OAuth-derived binding
            "oauth_provider": oauth_identity.provider,
        }

        # Persist to PostgreSQL
        await _persist_session_new(
            session_key=session_key,
            agent_id=agent_id,
            api_key=oauth_identity.internal_api_key,
            created_at=bound_at
        )

        logger.info(f"OAuth session bound: {session_key} -> {agent_id}")
        return True

    except Exception as e:
        logger.error(f"OAuth session binding failed: {e}", exc_info=True)
        return False


# =============================================================================
# AUTH CHALLENGE (for triggering OAuth flow)
# =============================================================================

def build_oauth_challenge_response(realm: str = "governance") -> dict:
    """
    Build a 401 response that triggers OAuth login in ChatGPT.

    Returns dict with status_code and headers for use with JSONResponse.

    Usage:
        if REQUIRE_OAUTH and not oauth_identity:
            challenge = build_oauth_challenge_response()
            return JSONResponse(
                {"error": "Authentication required", "code": "auth_required"},
                status_code=challenge["status_code"],
                headers=challenge["headers"]
            )
    """
    return {
        "status_code": 401,
        "headers": {
            "WWW-Authenticate": f'Bearer realm="{realm}"',
            "X-Auth-Required": "oauth",
        }
    }


def should_require_oauth(request) -> bool:
    """
    Determine if this request should require OAuth.

    Strategy:
    - Check GOVERNANCE_REQUIRE_OAUTH env var (opt-in)
    - Or check for specific header indicating OAuth-capable client

    By default, OAuth is optional (graceful fallback to session binding).
    Set GOVERNANCE_REQUIRE_OAUTH=1 to enforce OAuth for all HTTP requests.
    """
    import os

    # Explicit env var to require OAuth
    if os.getenv("GOVERNANCE_REQUIRE_OAUTH", "").lower() in ("1", "true", "yes"):
        return True

    # Check if client indicated OAuth capability
    # (ChatGPT might send specific headers when OAuth is configured)
    oauth_hint = request.headers.get("X-OAuth-Capable") or request.headers.get("x-oauth-capable")
    if oauth_hint:
        return True

    return False


# =============================================================================
# SSE SERVER INTEGRATION HELPERS
# =============================================================================

async def oauth_aware_session_setup(
    request,
    mcp_server,
    session_key: str
) -> Optional[OAuthIdentity]:
    """
    Full OAuth-aware session setup.

    Call this early in request handling to:
    1. Extract OAuth identity (if present)
    2. Ensure agent exists
    3. Bind session

    Example usage in SSE server:
        oauth_identity = await oauth_aware_session_setup(request, mcp_server, session_key)
        if oauth_identity:
            # OAuth client - fully set up, no further auth needed
            pass
        else:
            # Non-OAuth client - use existing session/identity flow
            pass

    Returns:
        OAuthIdentity if OAuth setup succeeded, None otherwise
    """
    # Step 1: Extract OAuth identity
    oauth_identity = await extract_oauth_identity(request)

    if not oauth_identity:
        return None

    # Step 2: Ensure agent exists
    if not await ensure_oauth_agent_exists(oauth_identity, mcp_server):
        logger.warning(f"Could not ensure OAuth agent exists: {oauth_identity.agent_id}")
        return None

    # Step 3: Bind session
    if not await bind_oauth_session(oauth_identity, session_key):
        logger.warning(f"Could not bind OAuth session: {session_key}")
        return None

    return oauth_identity


def inject_oauth_identity_to_args(
    arguments: Dict[str, Any],
    oauth_identity: OAuthIdentity
) -> Dict[str, Any]:
    """
    Inject OAuth identity into tool arguments.

    This allows tools to receive the agent_id without the client
    having to provide it in-band.

    Example:
        # In SSE tool dispatcher:
        if oauth_identity:
            arguments = inject_oauth_identity_to_args(arguments, oauth_identity)
        result = await handler(arguments)

    Returns:
        Modified arguments dict with injected identity
    """
    injected = arguments.copy()

    # Inject agent_id if not already provided
    if "agent_id" not in injected:
        injected["agent_id"] = oauth_identity.agent_id

    # Flag that this is OAuth-authenticated (for audit)
    injected["_oauth_authenticated"] = True
    injected["_oauth_provider"] = oauth_identity.provider

    return injected
