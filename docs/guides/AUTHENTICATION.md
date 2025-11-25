# Agent Authentication Guide

**Date:** November 24, 2025  
**Version:** v2.0

---

## 🔐 Overview

The UNITARES Governance MCP uses **API key authentication** to prevent impersonation and protect agent identities. Each agent has a unique API key that proves ownership.

**Why Authentication?**

Without authentication, anyone could:
- ❌ Update another agent's state
- ❌ Corrupt another agent's governance history
- ❌ Manipulate another agent's metrics
- ❌ Perform identity theft

With authentication:
- ✅ Only the owner can update their agent
- ✅ Agent identities are protected
- ✅ Governance history is secure

---

## 🎯 How It Works

### For New Agents

1. **Create agent** by calling `process_agent_update` with a unique `agent_id`
2. **API key is generated automatically** and returned in the response
3. **Save the API key** - you'll need it for all future updates

**Example:**
```python
# First update (creates agent)
result = process_agent_update(
    agent_id="my_unique_agent_20251124",
    parameters=[...],
    ethical_drift=[...],
    response_text="...",
    complexity=0.7
)

# API key is in the response
api_key = result['api_key']
print(f"Save this key: {api_key}")
```

### For Existing Agents

1. **Include `api_key` parameter** in every `process_agent_update` call
2. **System verifies** the key matches the stored key
3. **Update proceeds** if authentication succeeds

**Example:**
```python
# Subsequent updates (requires API key)
process_agent_update(
    agent_id="my_unique_agent_20251124",
    api_key="your_api_key_here",  # ← Required!
    parameters=[...],
    ethical_drift=[...],
    response_text="...",
    complexity=0.7
)
```

---

## 🔑 Getting Your API Key

### Method 1: From First Update Response

When you create a new agent, the API key is returned in the response:

```json
{
  "success": true,
  "api_key": "xGJwK9MbGCc2sk1IKrkC2RwoRucN4lUyQAATw1i39RQ",
  "api_key_warning": "⚠️  Save this API key - you'll need it for future updates...",
  "status": "healthy",
  ...
}
```

### Method 2: Using `get_agent_api_key` Tool

If you lost your API key, retrieve it:

```python
get_agent_api_key(
    agent_id="my_unique_agent_20251124"
)
```

**Response:**
```json
{
  "success": true,
  "agent_id": "my_unique_agent_20251124",
  "api_key": "xGJwK9MbGCc2sk1IKrkC2RwoRucN4lUyQAATw1i39RQ",
  "warning": "⚠️  Save this API key securely...",
  "security_note": "This key proves ownership of your agent identity..."
}
```

### Method 3: Regenerate Key

If your key is compromised, regenerate it:

```python
get_agent_api_key(
    agent_id="my_unique_agent_20251124",
    regenerate=True  # Invalidates old key, generates new one
)
```

---

## 🚨 Common Issues

### Error: "API key required"

**Problem:** You're trying to update an existing agent without providing the API key.

**Solution:** Include the `api_key` parameter in your request.

### Error: "Invalid API key"

**Problem:** The API key you provided doesn't match the stored key for this agent.

**Possible causes:**
- Wrong API key (typo or wrong agent)
- Key was regenerated (old key is invalid)
- Agent belongs to another identity

**Solution:** 
- Verify you're using the correct API key
- Use `get_agent_api_key` to retrieve the current key
- Make sure you're using the correct `agent_id`

### Error: "Agent does not exist"

**Problem:** The `agent_id` doesn't exist in the system.

**Solution:** 
- Check spelling of `agent_id`
- Use `list_agents` to see available agents
- Create the agent first (no API key needed for new agents)

---

## 🔄 Migration for Existing Agents

If you have agents created **before authentication was added** (November 24, 2025):

1. **Run migration script:**
   ```bash
   python scripts/migrate_agent_api_keys.py
   ```

2. **Or update the agent** - API key will be generated automatically on first update

3. **Save the API key** from the response for future updates

---

## 🔒 Security Best Practices

1. **Store API keys securely**
   - Don't commit keys to version control
   - Use environment variables or secure storage
   - Don't share keys publicly

2. **Regenerate compromised keys**
   - If a key is exposed, regenerate it immediately
   - Old key will be invalidated

3. **Use unique agent IDs**
   - Each agent should have a unique `agent_id`
   - Don't reuse IDs across different sessions
   - Follow naming conventions (see `AGENT_ID_ARCHITECTURE.md`)

4. **Verify agent ownership**
   - Only use API keys for agents you own
   - Don't attempt to use another agent's ID and key

---

## 📋 Quick Reference

### New Agent (No API Key)
```python
process_agent_update(
    agent_id="unique_session_id",
    parameters=[...],
    ethical_drift=[...],
    response_text="...",
    complexity=0.7
)
# → Returns api_key in response
```

### Existing Agent (API Key Required)
```python
process_agent_update(
    agent_id="unique_session_id",
    api_key="your_api_key",  # ← Required!
    parameters=[...],
    ethical_drift=[...],
    response_text="...",
    complexity=0.7
)
```

### Get API Key
```python
get_agent_api_key(agent_id="unique_session_id")
```

### Regenerate API Key
```python
get_agent_api_key(agent_id="unique_session_id", regenerate=True)
```

---

## 🔗 Related Documentation

- `AGENT_ID_ARCHITECTURE.md` - Agent ID naming and uniqueness
- `MCP_SETUP.md` - MCP server setup and tool usage
- `AUTHENTICATION_DESIGN.md` - Technical design details

---

**Last Updated:** November 24, 2025

