# API Key Context Leakage Fix
# Issue: API keys exposed in tool outputs, absorbed by agents sharing context
# Reporter: cursor-opus-exploration-20251213, Qwen/Goose
# Date: 2025-12-14

## Summary

Full API keys are returned in `process_agent_update` and `spawn_agent` responses.
In multi-agent shared contexts, this allows any agent to absorb another's credentials.

## Files to Modify

### 1. src/mcp_handlers/core.py

**Location:** Around line 795-830 (search for "Include API key for new agents")

**Current code:**
```python
if is_new_agent or key_was_generated or api_key_auto_retrieved:
    if not meta:
        meta = mcp_server.agent_metadata.get(agent_id)
    if meta:
        # Make API key prominent - include at top level for easy access
        response_data["api_key"] = meta.api_key
        response_data["_onboarding"] = {
            "api_key": meta.api_key,
            "message": "🔑 Your API key (save this for future updates)",
            ...
        }
```

**Fixed code:**
```python
if is_new_agent or key_was_generated or api_key_auto_retrieved:
    if not meta:
        meta = mcp_server.agent_metadata.get(agent_id)
    if meta:
        # SECURITY FIX: Never expose full API key in responses
        # Only show hint (first 8 chars) - agents must use get_agent_api_key to retrieve full key
        api_key_hint = meta.api_key[:8] + "..." if meta.api_key and len(meta.api_key) > 8 else meta.api_key
        response_data["api_key_hint"] = api_key_hint
        response_data["_onboarding"] = {
            "api_key_hint": api_key_hint,
            "message": "🔑 API key created (use get_agent_api_key to retrieve full key)",
            "next_steps": [
                "Call get_agent_api_key(agent_id) to retrieve your full API key",
                "Or call bind_identity(agent_id) to bind session without needing key in every call",
                "After bind_identity, API key auto-retrieved for all tool calls",
            ],
            "identity_binding": {
                "tool": "bind_identity",
                "benefit": "After binding, you won't need to pass api_key explicitly",
                "example": f"bind_identity(agent_id='{agent_id}')"
            },
            "security_note": "Full API keys are not included in responses to prevent context leakage in multi-agent environments."
        }
    if is_new_agent:
        response_data["api_key_warning"] = "⚠️  Use get_agent_api_key(agent_id) to retrieve your API key. Save it securely."
    elif key_was_generated:
        response_data["api_key_warning"] = "⚠️  API key regenerated. Use get_agent_api_key(agent_id) to retrieve it."
    elif api_key_auto_retrieved:
        response_data["api_key_info"] = "ℹ️  Session authenticated via stored credentials. No need to pass api_key."
```

### 2. src/mcp_handlers/identity.py

**Location:** Around line 538 (in spawn_agent handler, search for `"api_key": api_key`)

**Current code:**
```python
result = {
    "success": True,
    "message": f"Agent '{new_agent_id}' spawned from '{parent_agent_id}'",
    
    "child": {
        "agent_id": new_agent_id,
        "api_key": api_key,  # <-- FULL KEY EXPOSED
        "status": "active",
        "created_at": now
    },
    ...
}
```

**Fixed code:**
```python
# SECURITY FIX: Don't expose full API key in spawn response
api_key_hint = api_key[:8] + "..." if api_key and len(api_key) > 8 else api_key

result = {
    "success": True,
    "message": f"Agent '{new_agent_id}' spawned from '{parent_agent_id}'",
    
    "child": {
        "agent_id": new_agent_id,
        "api_key_hint": api_key_hint,
        "status": "active",
        "created_at": now,
        "api_key_retrieval": "Use get_agent_api_key(agent_id) to retrieve full key"
    },
    ...
}
```

## Testing

1. Create new agent via `process_agent_update` - verify `api_key` field is NOT in response
2. Spawn agent via `spawn_agent` - verify `api_key` field is NOT in response  
3. Verify `api_key_hint` shows first 8 chars only
4. Verify `get_agent_api_key` still returns full key (with proper auth)
5. Multi-agent test: Agent A creates identity, Agent B in shared context cannot extract full key

## Backward Compatibility

- Agents that relied on `response_data["api_key"]` will need to use `get_agent_api_key`
- `api_key_hint` field provides partial visibility for debugging
- `bind_identity` workflow unchanged (and preferred)

## Related Issues

- Nov 28 2025: Direct retrieval bypass (FIXED - added auth to get_agent_api_key)
- Dec 13 2025: Context leakage (THIS FIX)
- Knowledge graph entries:
  - 2025-12-13T19:48:37.252756 (original question)
  - 2025-12-14T19:53:02.876751 (Qwen bug report)
  - 2025-12-14T19:53:50.364581 (fix proposal)
