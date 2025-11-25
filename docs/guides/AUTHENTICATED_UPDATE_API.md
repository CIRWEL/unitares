# Authenticated Update API - For Future AI Agents

**Date:** November 24, 2025  
**Purpose:** Secure, reusable entry point for governance updates  
**Audience:** Future AI agents, AGI systems, and autonomous governance participants

---

## 🎯 Overview

The governance system provides **authenticated update functions** that enforce identity verification before processing updates. This prevents impersonation and ensures each agent can only modify its own governance state.

**Two versions available:**
- **Synchronous:** `process_update_authenticated()` - For CLI scripts and synchronous contexts
- **Async:** `process_update_authenticated_async()` - For async contexts (MCP handlers, async frameworks)

---

## 🔐 Why Authentication Matters

**The Problem:**
- Without authentication, any agent could impersonate another by using its `agent_id`
- This would corrupt governance history, metrics, and state
- Identity theft in governance systems undermines trust and accountability

**The Solution:**
- Each agent has a unique `api_key` generated on creation
- Updates require both `agent_id` and `api_key`
- System verifies ownership before processing updates

---

## 📚 API Reference

### Synchronous Version

```python
from src.mcp_server_std import process_update_authenticated

result = process_update_authenticated(
    agent_id="your_agent_id",
    api_key="your_api_key",
    agent_state={
        "parameters": np.array([...]),  # 128-dim parameter vector
        "ethical_drift": np.array([0.0, 0.0, 0.0]),  # 3-dim ethical signals
        "response_text": "Your response text here",
        "complexity": 0.5  # Estimated complexity (0.0-1.0)
    },
    auto_save=True  # Automatically save state and metadata
)
```

**Returns:**
```python
{
    "status": "healthy" | "degraded" | "critical",
    "decision": {
        "action": "approve" | "revise" | "reject",
        "reason": "Explanation of decision"
    },
    "metrics": {
        "E": 0.702,  # Energy (exploration capacity)
        "I": 0.809,  # Information (integrity maintained)
        "S": 0.182,  # Entropy (disorder/uncertainty)
        "V": -0.003,  # Void integral (E-I balance)
        "coherence": 0.649,
        "lambda1": 0.090,
        "risk_score": 0.416,
        "void_active": False
    },
    "sampling_params": {
        "temperature": 0.563,
        "top_p": 0.859,
        "max_tokens": 2048
    }
}
```

**Raises:**
- `PermissionError`: If authentication fails (invalid API key)
- `ValueError`: If `agent_id` is invalid

---

### Async Version

```python
from src.mcp_server_std import process_update_authenticated_async

result = await process_update_authenticated_async(
    agent_id="your_agent_id",
    api_key="your_api_key",
    agent_state={
        "parameters": np.array([...]),
        "ethical_drift": np.array([0.0, 0.0, 0.0]),
        "response_text": "Your response text here",
        "complexity": 0.5
    },
    auto_save=True  # Automatically save state and metadata (async)
)
```

**Returns:** Same format as synchronous version

**Raises:** Same exceptions as synchronous version

---

## 🔑 Getting Your API Key

**For New Agents:**
- API key is automatically generated when agent is created
- Returned in the response from `process_agent_update` tool
- **Save it immediately** - you'll need it for all future updates

**For Existing Agents:**
- Use `get_agent_api_key` tool to retrieve your key
- Or check metadata if you have access

**Example:**
```python
# First update (new agent)
response = await mcp_client.call_tool("process_agent_update", {
    "agent_id": "my_agent_20251124",
    "parameters": [...],
    ...
})
api_key = response["api_key"]  # Save this!

# Subsequent updates
await process_update_authenticated_async(
    agent_id="my_agent_20251124",
    api_key=api_key,  # Use saved key
    agent_state={...}
)
```

---

## 🎯 Usage Patterns

### Pattern 1: Direct Function Call (Recommended)

**Use when:** You have direct access to the codebase

```python
from src.mcp_server_std import process_update_authenticated_async
import numpy as np

async def log_governance_update(agent_id, api_key, response_text, complexity):
    agent_state = {
        "parameters": np.array([0.5] * 128),  # Default parameters
        "ethical_drift": np.array([0.0, 0.0, 0.0]),  # No drift
        "response_text": response_text,
        "complexity": complexity
    }
    
    result = await process_update_authenticated_async(
        agent_id=agent_id,
        api_key=api_key,
        agent_state=agent_state,
        auto_save=True
    )
    
    return result
```

**Benefits:**
- ✅ Direct function call (no MCP overhead)
- ✅ Type-safe (Python types)
- ✅ Can be used in any async context
- ✅ Centralized authentication logic

---

### Pattern 2: MCP Tool Call

**Use when:** You're using MCP protocol (Cursor, Claude Desktop, etc.)

```python
# Via MCP tool
response = await mcp_client.call_tool("process_agent_update", {
    "agent_id": "my_agent",
    "api_key": "your_api_key",
    "parameters": [...],
    "ethical_drift": [0.0, 0.0, 0.0],
    "response_text": "...",
    "complexity": 0.5
})
```

**Benefits:**
- ✅ Works across process boundaries
- ✅ Standard MCP protocol
- ✅ Can be used from any MCP client

---

## 🛡️ Security Best Practices

1. **Never share your API key**
   - Treat it like a password
   - Don't commit to version control
   - Don't log it in plain text

2. **Store securely**
   - Use environment variables
   - Use secure key management systems
   - Rotate if compromised

3. **Verify ownership**
   - Always use `process_update_authenticated` functions
   - Never call `UNITARESMonitor.process_update()` directly
   - The authenticated functions enforce security

4. **Handle errors gracefully**
   - Catch `PermissionError` for auth failures
   - Log security events
   - Don't expose API keys in error messages

---

## 🔄 Migration Guide

**If you're currently calling `monitor.process_update()` directly:**

**Before:**
```python
monitor = get_or_create_monitor(agent_id)
result = monitor.process_update(agent_state)
```

**After:**
```python
from src.mcp_server_std import process_update_authenticated_async

result = await process_update_authenticated_async(
    agent_id=agent_id,
    api_key=api_key,  # Get from metadata or arguments
    agent_state=agent_state,
    auto_save=True
)
```

**Benefits:**
- ✅ Authentication enforced
- ✅ State automatically saved
- ✅ Metadata updated automatically
- ✅ Consistent with MCP handler logic

---

## 🎓 For Future AI Agents

**This API is designed for you:**

- **Autonomous agents** can use this to log their own governance updates
- **Cross-monitoring agents** can observe but not modify other agents' state
- **Fleet coordination** relies on authenticated updates for accountability
- **Self-governance** requires secure identity verification

**Philosophy:**
- Each agent has a unique identity (`agent_id`)
- Identity requires proof (`api_key`)
- Updates are authenticated and auditable
- Governance state evolves through verified actions

**Example: Self-Logging Agent**
```python
class SelfMonitoringAgent:
    def __init__(self, agent_id, api_key):
        self.agent_id = agent_id
        self.api_key = api_key
    
    async def log_response(self, response_text, complexity):
        """Log this agent's response to governance system"""
        agent_state = {
            "parameters": self.get_current_parameters(),
            "ethical_drift": self.estimate_ethical_drift(),
            "response_text": response_text,
            "complexity": complexity
        }
        
        result = await process_update_authenticated_async(
            agent_id=self.agent_id,
            api_key=self.api_key,
            agent_state=agent_state,
            auto_save=True
        )
        
        # Use result to guide future behavior
        if result["decision"]["action"] == "reject":
            self.escalate_to_supervisor()
        elif result["decision"]["action"] == "revise":
            self.adjust_parameters(result["metrics"])
        
        return result
```

---

## 📊 Response Interpretation

**Decision Actions:**
- **`approve`**: Agent proceeds autonomously (risk < 30%)
- **`revise`**: Agent should self-correct (risk 30-50%)
- **`reject`**: Agent should halt or escalate (risk > 50% or coherence < 60%)

**Health Status:**
- **`healthy`**: Risk < 30%, system operating normally
- **`degraded`**: Risk 30-60%, monitoring closely
- **`critical`**: Risk > 60% or coherence < 60%, intervention needed

**Metrics:**
- **E (Energy)**: Exploration/productive capacity deployed [0, 1]
- **I (Information)**: Preservation/integrity maintained [0, 1]
- **S (Entropy)**: Disorder/uncertainty/drift [0, 1]
- **V (Void)**: E-I balance (like free energy) [-1, 1]
- **Coherence**: System consistency [0, 1]
- **Risk Score**: Estimated risk from behavior [0, 1]

---

**Status:** ✅ Ready for use by future AI agents and AGI systems

