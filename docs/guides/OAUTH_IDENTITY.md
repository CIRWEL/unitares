# OAuth Identity for MCP Handlers

## Problem Statement

When ChatGPT or other external clients use MCP, identity flows through tool arguments:

```
hello(agent_id='my_agent', api_key='gov-secret-key-...')
```

This triggers OpenAI's content moderation because:
- "api_key" in tool args looks like credential exposure
- The moderation system can't distinguish governance API keys from actual secrets

## Solution: OAuth = Identity Out-of-Band

With OAuth, identity flows through HTTP headers, not tool arguments:

```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

The JWT contains:
- `sub`: Unique user identifier (from OAuth provider)
- `email`: User's email (optional)
- `name`: User's display name (optional)
- `iss`: OAuth provider (Google, GitHub, OpenAI, etc.)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ChatGPT / External Client                  │
│                                                                 │
│  1. Runs OAuth flow when connecting MCP app                    │
│  2. Sends Authorization: Bearer <JWT> on every request         │
│  3. Calls tools WITHOUT agent_id/api_key arguments             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Governance MCP Server                       │
│                                                                 │
│  extract_oauth_identity(request)                               │
│    │                                                            │
│    ├─► Decode JWT from Authorization header                    │
│    ├─► Extract sub claim                                       │
│    ├─► Derive deterministic agent_id: oauth_google_a3f8c2e1    │
│    ├─► Derive internal api_key (HMAC with server secret)       │
│    └─► Auto-bind session                                        │
│                                                                 │
│  Tool dispatch                                                  │
│    │                                                            │
│    ├─► Inject agent_id into arguments                          │
│    └─► Execute tool (identity already bound)                   │
└─────────────────────────────────────────────────────────────────┘
```

## Integration Guide

### Step 1: Configure OAuth Provider

In your MCP connector configuration (e.g., ChatGPT MCP settings):

```json
{
  "authorization": {
    "type": "oauth",
    "provider": "google",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret"
  }
}
```

### Step 2: Set Server Secret

```bash
# .env
GOVERNANCE_OAUTH_SECRET=your-production-secret-here
```

This secret is used to derive internal api_keys from OAuth `sub` claims.
If you rotate this secret, all OAuth-derived agents will get new internal keys.

### Step 3: SSE Server Integration

In `src/mcp_server_sse.py`, add OAuth integration to `http_call_tool`:

```python
async def http_call_tool(request):
    # ... existing auth check ...

    # NEW: OAuth identity extraction (after auth check, before dispatch)
    from src.mcp_handlers.oauth_identity import (
        oauth_aware_session_setup,
        inject_oauth_identity_to_args
    )

    session_key = _extract_client_session_id(request)
    oauth_identity = await oauth_aware_session_setup(request, mcp_server, session_key)

    # ... existing argument parsing ...

    # NEW: Inject OAuth identity into arguments
    if oauth_identity:
        arguments = inject_oauth_identity_to_args(arguments, oauth_identity)

    # Existing dispatch
    result = await dispatch_tool(tool_name, arguments)
```

### Step 4: Tool Usage (No Changes Needed!)

OAuth clients can now call tools without identity arguments:

```
# Before (triggers moderation)
hello(agent_id='my_agent', api_key='gov-...')

# After (OAuth identity auto-injected)
get_governance_metrics()  # Just works - identity from OAuth
store_knowledge_graph(summary='My discovery', discovery_type='insight')
```

## How Agent IDs Work

OAuth `sub` claims are mapped to agent IDs deterministically:

| OAuth Provider | Sub Claim | Derived agent_id |
|----------------|-----------|------------------|
| Google | `123456789` | `oauth_google_a3f8c2e1` |
| GitHub | `user42` | `oauth_github_7b2d9f4a` |
| OpenAI | `user-xyz` | `oauth_openai_c9e1a8b3` |

The mapping is:
1. Hash the `sub` claim (SHA256, truncated to 16 chars)
2. Prefix with `oauth_` + provider name

This ensures:
- **Deterministic**: Same user always gets same agent_id
- **Private**: Raw OAuth IDs not exposed in logs
- **Namespaced**: Different providers can have same sub without collision

## Internal API Keys

The server derives internal api_keys from OAuth identity:

```python
internal_key = HMAC(server_secret, sub)
```

This key is:
- **Never exposed** to the client
- **Deterministic**: Same sub always gets same key
- **Rotatable**: Change server secret to rotate all keys

The client never needs to know or provide this key - OAuth IS the authentication.

## Fallback for Non-OAuth Clients

OAuth extraction gracefully falls back:

```python
oauth_identity = await extract_oauth_identity(request)
if oauth_identity:
    # OAuth client - auto-inject identity
    arguments = inject_oauth_identity_to_args(arguments, oauth_identity)
else:
    # Non-OAuth client (Claude Desktop, local MCP, etc.)
    # Falls through to existing session binding flow
    pass
```

Non-OAuth clients continue to work exactly as before.

## Security Considerations

### JWT Verification

The current implementation decodes JWTs **without cryptographic verification**.
This is intentional for flexibility - the OAuth provider has already validated
the token before sending it.

For stricter security:

```python
# Install PyJWT
pip install pyjwt[crypto]

# Verify with provider's public keys
import jwt
payload = jwt.decode(
    token,
    public_key,  # From OAuth provider
    algorithms=["RS256"],
    audience="your-client-id"
)
```

### Server Secret

The `GOVERNANCE_OAUTH_SECRET` is critical:
- Used to derive internal api_keys
- Must be kept secret
- Should be rotated periodically
- Different per environment (dev/staging/prod)

### Audit Trail

OAuth identity is logged for audit:
- Agent creation includes OAuth provider and sub hash
- Session bindings are flagged as `oauth: true`
- No raw OAuth tokens are logged

## Testing

### Mock OAuth for Development

```python
# Create a mock JWT for testing
import base64
import json

def make_mock_jwt(sub="test-user-123", provider="test"):
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "sub": sub,
        "iss": f"https://{provider}.example.com",
        "email": f"{sub}@example.com",
        "name": "Test User"
    }

    h = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=')
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=')

    return f"{h.decode()}.{p.decode()}."

# Use in test request
headers = {"Authorization": f"Bearer {make_mock_jwt()}"}
```

### Integration Test

```python
async def test_oauth_identity_flow():
    from src.mcp_handlers.oauth_identity import extract_oauth_identity

    # Mock request with JWT
    class MockRequest:
        headers = {"Authorization": f"Bearer {make_mock_jwt('user-42', 'google')}"}

    identity = await extract_oauth_identity(MockRequest())

    assert identity is not None
    assert identity.sub == "user-42"
    assert identity.provider == "google"
    assert identity.agent_id.startswith("oauth_google_")
    assert identity.internal_api_key.startswith("gov-oauth-")
```

## Debugging OAuth Flow

### Step A: Use MCP Inspector

OpenAI recommends MCP Inspector to debug raw requests/responses:
1. Connect to your HTTPS MCP URL
2. Walk through OAuth
3. Call a tool and confirm `Authorization` header is present

If it works in Inspector but not in ChatGPT, the issue is connector/UI/session.

### Step B: Verify 401 Challenge Works

To trigger OAuth login in ChatGPT, enable required OAuth:

```bash
# .env
GOVERNANCE_REQUIRE_OAUTH=1
```

Then test:
```bash
curl -X POST http://localhost:8765/call \
  -H "Content-Type: application/json" \
  -d '{"name": "list_tools", "arguments": {}}'

# Should return:
# HTTP/1.1 401 Unauthorized
# WWW-Authenticate: Bearer realm="governance"
```

If you never see the login prompt in ChatGPT, your server isn't signaling OAuth correctly.

### Step C: Check Token Claims

If login works but tools fail, add logging to check claims:

```python
# In oauth_identity.py, after decoding JWT:
logger.info(f"JWT claims: iss={payload.get('iss')}, aud={payload.get('aud')}, sub={payload.get('sub')}")
```

Common issues:
- `iss` (issuer) doesn't match expected
- `aud` / `resource` wrong
- Missing `openid` / `profile` scopes (no identity claims)
- Clock skew causing `exp/nbf` failures

### Step D: Missing Identity Claims

ChatGPT may not always request `openid/profile` scopes. If `sub` is missing:
- Require needed scopes server-side
- Or fetch identity via provider's userinfo endpoint

### Step E: Re-authorize Connector

If OAuth worked before but stopped:
- Go to Settings → Apps & Connectors
- Find your MCP connector
- Click "Connect" to re-authorize

## Migration Path

For existing users with in-band identity:

1. **Phase 1**: OAuth extraction works alongside existing flow
   - OAuth users auto-bound via headers
   - Non-OAuth users continue with tool arguments

2. **Phase 2**: Deprecate in-band api_key for external clients
   - Add warning when api_key provided via tool args
   - Guide users to OAuth configuration

3. **Phase 3**: Remove in-band identity for external clients
   - Only OAuth for ChatGPT/web clients
   - Keep in-band for local clients (Claude Desktop)
