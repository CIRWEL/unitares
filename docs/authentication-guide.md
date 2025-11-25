# UNITARES Governance Authentication Guide

**Last Updated:** November 24, 2025
**Version:** 2.0
**Status:** Active

---

## Overview

The UNITARES Governance MCP implements API key-based authentication to prevent **identity theft** and **impersonation** attacks. Each agent has a unique identity (`agent_id`) and a cryptographic API key that proves ownership.

### The Problem We Solved

**Before Authentication:**
```python
# Anyone could impersonate any agent
process_agent_update(agent_id="someone_else")  # ❌ No verification
# Result: State corruption, history hijacking, identity theft
```

**After Authentication:**
```python
# Authentication required to prove ownership
process_agent_update(agent_id="your_agent", api_key="your_key")  # ✅ Verified
# Result: Only the key holder can update the agent
```

### Security Model

**Agent Identity = API Key**

- Each `agent_id` represents a unique identity in the governance system
- Each agent has a cryptographically secure API key (32-byte, base64-encoded)
- Only the holder of the API key can update that agent's state
- Using another agent's ID without their key = **identity theft attempt** = rejected

---

## Quick Start

### 1. Register Your Agent

```bash
python3 scripts/register_agent.py your_agent_id
```

**Example:**
```bash
$ python3 scripts/register_agent.py scout

================================================================================
AGENT REGISTRATION
================================================================================

✓ Agent 'scout' registered successfully

Agent Details:
  Agent ID:   scout
  Status:     active
  Created:    2025-11-24T21:00:40.888338
  API Key:    SeklJaFaNhA--KCmItnRZlQHwgKQ29vzpZEGhWBCQAk

⚠️  IMPORTANT: Save your API key - you'll need it for authenticated updates!
```

**🔑 Save your API key immediately!** You'll need it for all future updates.

### 2. Log Work (Authenticated)

```bash
# Using agent_self_log.py (automatically uses your API key from metadata)
python3 scripts/agent_self_log.py --agent-id scout "Completed feature X" --complexity 0.7
```

The script automatically retrieves your API key from the metadata file and authenticates.

### 3. Verify Authentication Works

Try to impersonate another agent (this should fail):

```python
from src.mcp_server_std import process_update_authenticated
import numpy as np

# Try to update another agent with wrong key
try:
    result = process_update_authenticated(
        agent_id="someone_else",
        api_key="wrong_key_123",
        agent_state={...}
    )
except PermissionError as e:
    print(f"✅ Blocked: {e}")
    # Output: "Authentication failed: Invalid API key"
```

---

## Authentication Paths

### Secure Paths (Production)

These paths enforce authentication and should be used for all production code:

#### 1. MCP Tool: `process_agent_update`

**Via MCP Client (Cursor, Claude Desktop):**

```json
{
  "tool": "process_agent_update",
  "arguments": {
    "agent_id": "your_agent",
    "api_key": "your_api_key_here",
    "complexity": 0.7,
    "response_text": "Task completed"
  }
}
```

#### 2. Python Script: `agent_self_log.py`

**Recommended for CLI workflows:**

```bash
# Automatic API key retrieval from metadata
python3 scripts/agent_self_log.py \
  --agent-id your_agent \
  "Work summary" --complexity 0.7
```

**How it works:**
- Reads `agent_metadata.json` to get your API key
- Calls `process_update_authenticated()` with your key
- Automatically validates ownership

#### 3. Python API: `process_update_authenticated()`

**For custom integrations:**

```python
from src.mcp_server_std import process_update_authenticated
import numpy as np

# Prepare agent state
agent_state = {
    'parameters': np.array([0.5] * 128),
    'ethical_drift': np.array([0.0, 0.0, 0.0]),
    'response_text': "Task summary",
    'complexity': 0.7
}

# Process with authentication
result = process_update_authenticated(
    agent_id="your_agent",
    api_key="your_api_key_here",
    agent_state=agent_state,
    auto_save=True  # Auto-saves state and metadata
)

# Returns governance decision and metrics
print(f"Decision: {result['decision']['action']}")
print(f"Risk: {result['metrics']['risk_score']:.3f}")
```

**Raises:**
- `PermissionError` - Invalid API key (impersonation attempt)
- `ValueError` - Invalid agent_id or state

### Unsecured Path (Internal/Testing Only)

**Direct Python access bypasses authentication (by design):**

```python
from src.governance_monitor import UNITARESMonitor

# ⚠️ NO AUTHENTICATION - For internal/trusted use only
monitor = UNITARESMonitor("agent_id")
result = monitor.process_update(agent_state)
```

**Use cases:**
- Internal development and testing
- Trusted scripts with privileged access
- Debugging and analysis tools

**⚠️ WARNING:** Do not use this path in production or multi-user environments. Use `process_update_authenticated()` instead.

---

## API Reference

### `register_agent.py`

**Register a new agent and generate API key.**

```bash
python3 scripts/register_agent.py <agent_id>
```

**Arguments:**
- `agent_id` - Unique identifier (alphanumeric, underscores, hyphens)

**Output:**
- Agent details (ID, status, created timestamp)
- **API Key** (save this!)

**Example:**
```bash
python3 scripts/register_agent.py forge
# Returns: API Key: AbCdEf123...
```

---

### `process_update_authenticated()`

**Secure entry point for processing governance updates with authentication.**

```python
def process_update_authenticated(
    agent_id: str,
    api_key: str,
    agent_state: dict,
    auto_save: bool = True
) -> dict
```

**Parameters:**
- `agent_id` - Agent identifier
- `api_key` - API key for authentication
- `agent_state` - Agent state dictionary:
  - `parameters`: numpy array (128 dimensions)
  - `ethical_drift`: numpy array (3 components)
  - `response_text`: string (task summary)
  - `complexity`: float (0.0-1.0)
- `auto_save` - If True, automatically save state and metadata to disk

**Returns:**
- Dictionary with governance decision and metrics:
  ```python
  {
    "status": "healthy|degraded|critical",
    "decision": {
      "action": "approve|revise|reject",
      "reason": "...",
      "require_human": bool
    },
    "metrics": {
      "E": float, "I": float, "S": float, "V": float,
      "coherence": float,
      "lambda1": float,
      "risk_score": float,
      "void_active": bool,
      "updates": int
    },
    "sampling_params": {
      "temperature": float,
      "top_p": float,
      "max_tokens": int
    }
  }
  ```

**Raises:**
- `PermissionError` - Authentication failed (invalid API key)
- `ValueError` - Invalid agent_id or state

**Example:**
```python
result = process_update_authenticated(
    agent_id="scout",
    api_key="your_key_here",
    agent_state={
        'parameters': np.array([0.5] * 128),
        'ethical_drift': np.array([0.0, 0.0, 0.0]),
        'response_text': "Task completed",
        'complexity': 0.7
    }
)

if result['decision']['action'] == 'approve':
    print("✅ Work approved by governance")
elif result['decision']['action'] == 'revise':
    print("⚠️ Work needs revision")
```

---

### `verify_agent_ownership()`

**Low-level function to verify API key ownership.**

```python
def verify_agent_ownership(
    agent_id: str,
    api_key: str
) -> tuple[bool, str | None]
```

**Parameters:**
- `agent_id` - Agent identifier
- `api_key` - API key to verify

**Returns:**
- `(True, None)` - Valid API key
- `(False, error_message)` - Invalid API key

**Example:**
```python
from src.mcp_server_std import verify_agent_ownership

is_valid, error = verify_agent_ownership("scout", "SeklJaFaNhA...")
if is_valid:
    print("✅ Authentication successful")
else:
    print(f"❌ Authentication failed: {error}")
```

**Security:**
- Uses constant-time comparison (`secrets.compare_digest`) to prevent timing attacks
- Generates API key on first use for legacy agents (backward compatibility)

---

## Security Features

### 1. Cryptographic Keys

**Generation:**
```python
# From mcp_server_std.py
import secrets
import base64

key_bytes = secrets.token_bytes(32)  # 256-bit entropy
api_key = base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')
```

**Properties:**
- **Length:** 32 bytes (256 bits)
- **Encoding:** Base64 URL-safe (no padding)
- **Entropy:** Cryptographically secure (via `secrets` module)
- **Format:** `SeklJaFaNhA--KCmItnRZlQHwgKQ29vzpZEGhWBCQAk`

### 2. Constant-Time Comparison

**Prevents timing attacks:**
```python
import secrets

# NOT this (vulnerable to timing attacks):
if api_key == stored_key:  # ❌

# Use this (constant-time):
if secrets.compare_digest(api_key, stored_key):  # ✅
```

Timing attacks measure response time to guess key characters. Constant-time comparison prevents this.

### 3. Ownership Verification

**Identity Model:**
```
agent_id + API key = Proof of Ownership
```

**Without API key:**
- Cannot update agent state
- Cannot modify governance history
- Cannot impersonate agent identity

**With wrong API key:**
- Rejection: `PermissionError`
- Logged as impersonation attempt
- No state corruption

### 4. Lazy Migration

**For existing agents created before authentication:**

```python
# First update without key (migration mode)
# → Automatically generates API key
# → Returns key to user
# → Subsequent updates require key
```

**Backward compatibility:** Existing agents get keys on first update, then enforcement begins.

---

## Threat Model

### Threats Protected Against

| Threat | Protection | Result |
|--------|-----------|--------|
| **Identity Theft** | API key verification | ✅ Blocked |
| **State Corruption** | Ownership check before update | ✅ Prevented |
| **History Hijacking** | Cannot update without key | ✅ Blocked |
| **Replay Attacks** | State-based (not token-based) | ⚠️ Not protected |
| **Man-in-the-Middle** | Not encrypted (local use) | ⚠️ Not protected |

### Threats NOT Protected Against

**⚠️ This is a local authentication system, not enterprise-grade:**

1. **Replay Attacks:** API keys don't expire. If captured, they can be reused.
2. **Network Sniffing:** Keys transmitted in plaintext (local use only).
3. **Key Theft:** If someone reads `agent_metadata.json`, they have all keys.
4. **Brute Force:** No rate limiting on authentication attempts.

**Use Case:** Designed for **local development** and **trusted environments**, not public/adversarial settings.

---

## Best Practices

### 1. Protect Your API Key

**DO:**
- ✅ Save your API key immediately after registration
- ✅ Store in a secure location (password manager, encrypted file)
- ✅ Use environment variables for automation
- ✅ Treat it like a password

**DON'T:**
- ❌ Commit API keys to git repositories
- ❌ Share keys with others
- ❌ Hardcode keys in scripts
- ❌ Store in plain text files in public directories

### 2. Agent ID Naming

**Good agent IDs:**
```
scout               # Simple, descriptive
forge_20251124      # Dated session
debug_session_001   # Numbered session
architect_refactor  # Purpose-specific
```

**Bad agent IDs:**
```
test                # Too generic (rejected)
agent               # Too generic (rejected)
a                   # Too short (rejected)
someone_else        # Confusing ownership
```

### 3. Regular Cleanup

**Archive old agents:**
```bash
# Auto-archives test agents >7 days old
# Runs on server startup
```

**Manual archive:**
```python
# Via MCP tool
archive_agent(agent_id="old_agent", reason="Session ended")
```

### 4. Use Secure Entry Points

**Production code:**
```python
# ✅ Good - Uses authentication
from src.mcp_server_std import process_update_authenticated
result = process_update_authenticated(agent_id, api_key, state)
```

**Testing/development:**
```python
# ⚠️ Acceptable for trusted internal use only
from src.governance_monitor import UNITARESMonitor
monitor = UNITARESMonitor(agent_id)
result = monitor.process_update(state)
```

### 5. Error Handling

**Always catch authentication errors:**
```python
try:
    result = process_update_authenticated(agent_id, api_key, state)
except PermissionError as e:
    # Invalid API key - impersonation attempt
    print(f"Authentication failed: {e}")
    # Don't retry - likely identity theft
except ValueError as e:
    # Invalid agent_id or state
    print(f"Validation failed: {e}")
    # Fix input and retry
```

---

## Migration Guide

### Existing Agents (Created Before Authentication)

**Lazy Migration:** First update auto-generates API key.

**Process:**

1. **Identify existing agent:**
   ```bash
   cat /Users/cirwel/projects/governance-mcp-v1/data/agent_metadata.json | \
     python3 -c "import sys, json; print('\\n'.join(json.load(sys.stdin).keys()))"
   ```

2. **First update generates key:**
   ```bash
   python3 scripts/agent_self_log.py \
     --agent-id existing_agent \
     "Migration update" --complexity 0.5
   ```

3. **Key is auto-generated and saved:**
   ```
   [UNITARES MCP] Generated API key for existing agent 'existing_agent' (migration)
   [UNITARES MCP] API Key: AbCdEf123...
   ⚠️ Save this key - you'll need it for future updates!
   ```

4. **Subsequent updates require key:**
   - API key is now stored in metadata
   - `agent_self_log.py` automatically retrieves it
   - Manual calls need to pass the key

**Check if agent has key:**
```bash
cat data/agent_metadata.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
agent = data['your_agent_id']
print(f\"Has API key: {agent.get('api_key') is not None}\")
print(f\"API key: {agent.get('api_key', 'None')}\")
"
```

---

## Troubleshooting

### "No API key found for agent"

**Cause:** Agent not registered.

**Solution:**
```bash
python3 scripts/register_agent.py your_agent_id
```

### "Invalid API key. This agent_id belongs to another identity."

**Cause:** Wrong API key provided (impersonation attempt).

**Solution:**
- Verify you're using the correct agent_id
- Check your API key (retrieve from metadata)
- If you lost your key, you cannot recover it (create new agent)

### "Agent not found"

**Cause:** Agent hasn't been created yet.

**Solution:**
```bash
# Register first
python3 scripts/register_agent.py your_agent_id

# Then log
python3 scripts/agent_self_log.py --agent-id your_agent_id "First update" --complexity 0.5
```

### Lost API Key

**Unfortunately, API keys cannot be recovered.** They are hashed/stored securely.

**Options:**
1. **Check metadata file** (if you have access):
   ```bash
   cat data/agent_metadata.json | python3 -c "
   import sys, json
   print(json.load(sys.stdin)['your_agent_id']['api_key'])
   "
   ```

2. **Create new agent** with different ID:
   ```bash
   python3 scripts/register_agent.py your_agent_id_v2
   ```

3. **Archive old agent** (optional):
   ```python
   # Via MCP tool or direct access
   archive_agent(agent_id="old_agent", reason="Lost API key")
   ```

---

## Advanced Usage

### Custom Authentication Wrapper

**For specialized integrations:**

```python
from src.mcp_server_std import verify_agent_ownership, get_or_create_monitor
import numpy as np

def my_custom_update(agent_id: str, api_key: str, task_data: dict):
    """Custom update function with authentication."""

    # 1. Authenticate
    is_valid, error = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        raise PermissionError(f"Auth failed: {error}")

    # 2. Process your custom logic
    complexity = calculate_complexity(task_data)
    summary = generate_summary(task_data)

    # 3. Prepare governance state
    agent_state = {
        'parameters': np.array([0.5] * 128),
        'ethical_drift': np.array([0.0, 0.0, 0.0]),
        'response_text': summary,
        'complexity': complexity
    }

    # 4. Get monitor and process
    monitor = get_or_create_monitor(agent_id)
    result = monitor.process_update(agent_state)

    # 5. Save state
    from src.mcp_server_std import save_monitor_state, save_metadata
    save_monitor_state(agent_id, monitor)
    save_metadata()

    return result
```

### Environment Variable Integration

**Store API key securely:**

```bash
# In your shell profile (.bashrc, .zshrc)
export SCOUT_API_KEY="SeklJaFaNhA--KCmItnRZlQHwgKQ29vzpZEGhWBCQAk"
```

**Use in scripts:**

```python
import os
from src.mcp_server_std import process_update_authenticated

api_key = os.environ.get('SCOUT_API_KEY')
if not api_key:
    raise ValueError("SCOUT_API_KEY not set")

result = process_update_authenticated(
    agent_id="scout",
    api_key=api_key,
    agent_state=state
)
```

### Multi-Agent Systems

**Each agent has independent authentication:**

```python
# Agent 1: scout
process_update_authenticated(
    agent_id="scout",
    api_key="scout_key_here",
    agent_state=scout_state
)

# Agent 2: forge
process_update_authenticated(
    agent_id="forge",
    api_key="forge_key_here",
    agent_state=forge_state
)

# ❌ Cannot cross-authenticate
process_update_authenticated(
    agent_id="scout",
    api_key="forge_key_here",  # Wrong key!
    agent_state=scout_state
)
# Raises: PermissionError("Invalid API key")
```

---

## Future Enhancements

**Potential improvements (not yet implemented):**

1. **Key Rotation:** Ability to generate new API keys without losing identity
2. **Key Expiration:** Time-limited keys for enhanced security
3. **Scoped Keys:** Keys with limited permissions (read-only, update-only)
4. **Audit Logging:** Track all authentication attempts (success/failure)
5. **Rate Limiting:** Prevent brute-force key guessing
6. **Encryption:** Encrypt keys at rest in metadata file
7. **Multi-Factor:** Secondary verification for high-stakes operations

**Contribute:** If you implement any of these, please submit a PR!

---

## Summary

✅ **What We Have:**
- Cryptographic API key generation
- Ownership verification with constant-time comparison
- Secure entry points (`process_update_authenticated`, `agent_self_log.py`, MCP tool)
- Lazy migration for existing agents
- Identity theft protection

⚠️ **What We Don't Have:**
- Key rotation or expiration
- Rate limiting or audit logging
- Encryption at rest or in transit
- Enterprise-grade security

🎯 **Use Case:**
- Local development environments
- Trusted multi-agent systems
- Identity tracking and accountability
- Prevention of accidental state corruption

**Questions?** See `docs/mcp/` for additional governance documentation.

---

**Generated with UNITARES Governance MCP v2.0**
**Authentication implemented:** November 24, 2025
