# Agent Identity Authentication Design

**Date:** November 24, 2025  
**Issue:** System has identities but no authentication - anyone can impersonate any agent  
**Status:** 🔴 Critical Security Flaw - Design Phase

---

## 🚨 The Problem

**Current State:**
```python
process_agent_update(agent_id="tron_grid_governance_20251124", ...)
# ✅ Updates the agent
# ❌ No check that caller IS tron_grid_governance_20251124
```

**Vulnerability:**
- Anyone can call `process_agent_update` with any `agent_id`
- They can corrupt another agent's state, history, and metrics
- No verification that caller owns the identity

**Impact:**
- Identity theft (impersonation)
- State corruption
- History tampering
- Governance record manipulation

---

## 🎯 Design Goals

1. **Prevent Impersonation**: Only the owner can update their identity
2. **Backward Compatible**: Existing agents should still work
3. **Simple to Use**: Minimal friction for legitimate users
4. **MCP-Compatible**: Works with stdio-based MCP protocol
5. **Secure**: Cryptographic verification

---

## 🔐 Proposed Solution: API Key Authentication

### Architecture

```
Agent Creation:
1. Generate unique API key (32-byte random, base64 encoded)
2. Store key in agent metadata
3. Return key to caller (one-time display)

Agent Updates:
1. Require api_key parameter
2. Verify key matches stored key
3. Reject if mismatch
```

### Implementation

**1. API Key Generation**

```python
import secrets
import base64

def generate_api_key() -> str:
    """Generate secure 32-byte API key"""
    key_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')
```

**2. Metadata Storage**

```python
@dataclass
class AgentMetadata:
    agent_id: str
    api_key: str  # ← NEW: Stored on creation
    created_at: str
    # ... rest of fields
```

**3. Authentication Check**

```python
def verify_agent_ownership(agent_id: str, api_key: str) -> bool:
    """Verify caller owns the agent_id"""
    if agent_id not in agent_metadata:
        return False  # Agent doesn't exist
    
    stored_key = agent_metadata[agent_id].api_key
    return secrets.compare_digest(api_key, stored_key)  # Constant-time comparison
```

**4. Tool Update**

```python
process_agent_update(
    agent_id="tron_grid_governance_20251124",
    api_key="<required>",  # ← NEW: Required parameter
    ...
)
```

---

## 🔄 Migration Strategy

### Phase 1: Add API Keys (Backward Compatible)

- New agents: Generate API key on creation
- Existing agents: Generate API key on first update (lazy migration)
- Optional `api_key` parameter (warn if missing for existing agents)

### Phase 2: Enforce Authentication

- Require `api_key` for all updates
- Reject updates without valid key
- Provide key recovery mechanism

---

## 🛡️ Security Considerations

**1. Key Storage**
- ✅ Stored in `agent_metadata.json` (local file)
- ⚠️  Not encrypted (local-only system)
- ✅ Future: Could encrypt with user's keychain

**2. Key Transmission**
- ✅ MCP stdio (local process communication)
- ⚠️  If MCP goes over network, need TLS
- ✅ Future: Use environment variables instead of parameters

**3. Key Recovery**
- Provide `get_agent_api_key` tool (requires proof of identity)
- Or: Regenerate key (invalidates old key)

**4. Key Rotation**
- Allow key regeneration
- Invalidate old key
- Update metadata

---

## 📋 Alternative Approaches Considered

### Option 1: Session Tokens
- ✅ Temporary, expires
- ❌ Requires session management
- ❌ More complex

### Option 2: Cryptographic Signatures
- ✅ Most secure
- ❌ Requires key management
- ❌ Complex for MCP context

### Option 3: Process-Based
- ✅ Simple
- ❌ Not secure across network
- ❌ Can be spoofed

### Option 4: API Keys (Chosen)
- ✅ Simple
- ✅ Secure enough for local use
- ✅ Easy to implement
- ✅ Backward compatible

---

## 🚀 Implementation Plan

1. **Add API key generation** (`agent_id_manager.py`)
2. **Update metadata schema** (`agent_id_manager.py`)
3. **Add authentication check** (`mcp_server_std.py`)
4. **Update `process_agent_update`** to require `api_key`
5. **Add key recovery tool** (`get_agent_api_key`)
6. **Migration script** for existing agents

---

## 📝 API Changes

### New Parameter

```python
process_agent_update(
    agent_id: str,  # Required
    api_key: str,   # NEW: Required (optional during migration)
    parameters: List[float],
    ethical_drift: List[float],
    ...
)
```

### New Tool

```python
get_agent_api_key(
    agent_id: str,
    proof_of_identity: str  # e.g., creation timestamp or recovery token
) -> str
```

---

**Next Steps:**
1. Implement API key generation
2. Add authentication verification
3. Update tool signatures
4. Test with existing agents
5. Document migration path

