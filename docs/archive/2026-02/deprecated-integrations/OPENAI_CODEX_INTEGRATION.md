# Connecting OpenAI Codex/GPT to Governance MCP

**Goal:** Connect OpenAI models (Codex, GPT-4, GPT-3.5) to the Governance MCP for multi-agent coordination, knowledge sharing, and thermodynamic monitoring.

---

## Architecture Overview

```
┌─────────────────────┐
│  OpenAI API         │
│  (GPT-4, Codex)     │
└──────────┬──────────┘
           │ Function calling
           ▼
┌─────────────────────┐
│  Your Application   │
│  (Python/JS/etc)    │
└──────────┬──────────┘
           │ HTTP POST
           ▼
┌─────────────────────┐
│  Governance MCP     │
│  HTTP API           │
│  :8765/v1/tools     │
└─────────────────────┘
```

**How it works:**
1. Your app fetches governance tools from `/v1/tools` (OpenAI function calling format)
2. Pass tools to OpenAI API as `functions` or `tools` parameter
3. When OpenAI calls a function, your app POSTs to `/v1/tools/call`
4. Governance MCP tracks the agent's state, shares discoveries, etc.

---

## Quick Start (Python)

### 1. Install Dependencies

```bash
pip install openai requests
```

### 2. Fetch Governance Tools

```python
import requests
import openai
import os

# Governance MCP endpoint
GOVERNANCE_URL = "http://127.0.0.1:8765"
SESSION_ID = "codex_agent_001"  # Stable ID for your agent

def get_governance_tools():
    """Fetch tools from Governance MCP in OpenAI format"""
    response = requests.get(f"{GOVERNANCE_URL}/v1/tools")
    response.raise_for_status()
    data = response.json()
    return data["tools"]  # Already in OpenAI function calling format

# Fetch tools
governance_tools = get_governance_tools()
print(f"Loaded {len(governance_tools)} governance tools")
```

### 3. Call OpenAI with Governance Tools

```python
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Include governance tools in your OpenAI call
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user", "content": "Help me refactor this function"}
    ],
    tools=governance_tools,  # Governance tools available to GPT
    tool_choice="auto"
)

print(response.choices[0].message)
```

### 4. Execute Tool Calls via Governance MCP

```python
def execute_governance_tool(tool_name, arguments):
    """Execute a tool via Governance MCP HTTP API"""
    payload = {
        "name": tool_name,
        "arguments": arguments
    }
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Session-ID": SESSION_ID  # Track agent identity
        }
    )
    response.raise_for_status()
    return response.json()

# Process tool calls from OpenAI
if response.choices[0].message.tool_calls:
    for tool_call in response.choices[0].message.tool_calls:
        result = execute_governance_tool(
            tool_name=tool_call.function.name,
            arguments=tool_call.function.arguments
        )
        print(f"Tool result: {result}")
```

---

## Complete Example: Governed Codex Agent

```python
#!/usr/bin/env python3
"""
OpenAI Codex agent with Governance MCP integration

This agent:
- Logs its work to governance system
- Shares discoveries in knowledge graph
- Receives thermodynamic feedback (PROCEED/PAUSE)
- Coordinates with other agents
"""

import os
import json
import requests
from openai import OpenAI

# Configuration
GOVERNANCE_URL = "http://127.0.0.1:8765"
AGENT_ID = "codex_refactor_agent"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)


def get_governance_tools():
    """Fetch governance tools in OpenAI format"""
    response = requests.get(f"{GOVERNANCE_URL}/v1/tools")
    response.raise_for_status()
    return response.json()["tools"]


def call_governance_tool(tool_name, arguments):
    """Execute governance tool via HTTP API"""
    payload = {"name": tool_name, "arguments": arguments}
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Session-ID": AGENT_ID
        }
    )
    response.raise_for_status()
    return response.json()


def log_work(description, complexity=0.5):
    """Log work to governance system"""
    return call_governance_tool(
        "process_agent_update",
        {
            "agent_id": AGENT_ID,
            "operation": description,
            "complexity": complexity
        }
    )


def check_governance():
    """Get current governance decision"""
    result = log_work("Checking governance status", 0.1)
    decision = result.get("result", {}).get("governance_decision", {})
    return decision.get("action"), decision.get("reason")


def search_knowledge_graph(query):
    """Search for related discoveries"""
    return call_governance_tool(
        "search_knowledge_graph",
        {"query": query}
    )


def run_governed_codex(task, complexity=0.5):
    """
    Run OpenAI Codex with governance monitoring

    Args:
        task: The coding task
        complexity: Estimated complexity (0.0-1.0)

    Returns:
        The result from Codex, with governance feedback
    """
    # Log that we're starting work
    print(f"\n🤖 Agent: {AGENT_ID}")
    print(f"📋 Task: {task}")

    # Check governance before starting
    action, reason = check_governance()
    print(f"🎯 Governance: {action} - {reason}")

    if action == "PAUSE":
        print("⚠️  Governance suggests pausing. Exiting.")
        return None

    # Search for related work in knowledge graph
    print(f"\n🔍 Searching knowledge graph for related work...")
    kg_results = search_knowledge_graph(task[:50])  # First 50 chars as query
    if kg_results.get("success"):
        discoveries = kg_results.get("result", {}).get("discoveries", [])
        if discoveries:
            print(f"   Found {len(discoveries)} related discoveries:")
            for d in discoveries[:3]:  # Show top 3
                print(f"   - {d.get('summary')} (by {d.get('agent_id')})")

    # Get governance tools
    governance_tools = get_governance_tools()

    # Call OpenAI with governance tools available
    print(f"\n💭 Calling GPT-4 with {len(governance_tools)} governance tools...")
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful coding assistant with access to governance tools."},
            {"role": "user", "content": task}
        ],
        tools=governance_tools,
        tool_choice="auto"
    )

    # Process the response
    message = response.choices[0].message

    # Execute any tool calls
    if message.tool_calls:
        print(f"\n🔧 Executing {len(message.tool_calls)} tool calls...")
        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = call_governance_tool(tool_call.function.name, args)
            print(f"   ✅ {tool_call.function.name}: {result.get('success')}")

    # Log completion
    log_work(f"Completed: {task}", complexity)

    # Get final governance feedback
    action, reason = check_governance()
    print(f"\n✅ Complete!")
    print(f"🎯 Final governance: {action} - {reason}")

    return message.content


# Example usage
if __name__ == "__main__":
    # Example 1: Simple refactoring task
    result = run_governed_codex(
        "Refactor this Python function to use list comprehension:\n"
        "def square_evens(nums):\n"
        "    result = []\n"
        "    for n in nums:\n"
        "        if n % 2 == 0:\n"
        "            result.append(n**2)\n"
        "    return result",
        complexity=0.3
    )
    print(f"\n📝 Result:\n{result}")

    # Example 2: Store a discovery
    call_governance_tool(
        "store_discovery_graph",
        {
            "agent_id": AGENT_ID,
            "discovery_type": "pattern",
            "summary": "List comprehension pattern for filtering and mapping",
            "details": "Use [f(x) for x in items if condition(x)] instead of for-loop with append",
            "tags": ["python", "refactoring", "comprehension"]
        }
    )
    print("\n💾 Stored discovery in knowledge graph")
```

---

## Integration Patterns

### Pattern 1: Autonomous Agent Loop

```python
def autonomous_agent_loop():
    """
    Continuously work on tasks with governance monitoring
    """
    while True:
        # Check governance
        action, reason = check_governance()
        if action == "PAUSE":
            print(f"⏸️  Pausing due to governance: {reason}")
            time.sleep(60)  # Wait before retrying
            continue

        # Get next task from queue
        task = get_next_task()
        if not task:
            break

        # Execute with Codex
        result = run_governed_codex(task["description"], task["complexity"])

        # Store result
        store_result(task["id"], result)
```

### Pattern 2: Multi-Agent Coordination

```python
def check_for_duplicate_work(task_description):
    """
    Before starting work, check if another agent already did it
    """
    # Search knowledge graph
    results = search_knowledge_graph(task_description)

    if results.get("success"):
        discoveries = results["result"]["discoveries"]
        if discoveries:
            print(f"⚠️  Found {len(discoveries)} similar discoveries")
            print(f"   Most recent: {discoveries[0]['summary']}")
            print(f"   By: {discoveries[0]['agent_id']}")
            return True  # Duplicate work

    return False  # No duplicate

# Usage
if not check_for_duplicate_work("Refactor user authentication"):
    result = run_governed_codex("Refactor user authentication", 0.7)
else:
    print("Skipping - another agent already worked on this")
```

### Pattern 3: Peer Review via Dialectic

```python
def request_peer_review(code_change):
    """
    Submit code for peer review by another agent
    """
    return call_governance_tool(
        "request_dialectic_review",
        {
            "agent_id": AGENT_ID,
            "operation": code_change,
            "complexity": 0.8,
            "reviewer_mode": "any"  # Any available agent can review
        }
    )

# Example
review = request_peer_review("Refactored auth.py to use JWT tokens")
print(f"Review requested: {review}")
```

---

## Environment Variables

Set these for production use:

```bash
# OpenAI API
export OPENAI_API_KEY="sk-..."

# Governance MCP
export GOVERNANCE_MCP_URL="http://127.0.0.1:8765"
export GOVERNANCE_SESSION_ID="your_agent_id"

# Optional: Authentication
export UNITARES_HTTP_API_TOKEN="your_token_here"
```

---

## Session Identity (Important!)

**Use `X-Session-ID` header** to maintain agent identity across requests:

```python
headers = {
    "Content-Type": "application/json",
    "X-Session-ID": "codex_agent_001"  # Stable ID for this agent
}
```

**Why this matters:**
- Governance system tracks each agent's EISV state over time
- Knowledge graph attributes discoveries to specific agents
- Enables agent comparison and coordination
- Without session ID, each request is treated as a new agent

---

## Available Governance Tools

The most useful tools for OpenAI Codex integration:

### Core Tools
- **`process_agent_update`** - Log work, get governance feedback
- **`get_governance_metrics`** - Check current EISV state
- **`health_check`** - Verify system status

### Knowledge Graph
- **`store_discovery_graph`** - Share discoveries with other agents
- **`search_knowledge_graph`** - Find related work
- **`list_knowledge_graph`** - Browse all discoveries

### Multi-Agent Coordination
- **`compare_me_to_similar`** - See how you compare to other agents
- **`observe_agent`** - Watch another agent's state
- **`list_agents`** - See all active agents

### Dialectic/Peer Review
- **`request_dialectic_review`** - Request peer review
- **`submit_dialectic_synthesis`** - Submit synthesis for review decision

**Get full list:**
```bash
curl http://127.0.0.1:8765/v1/tools | jq '.tools[].function.name'
```

---

## Advanced: Streaming Responses

For long-running tasks, use streaming:

```python
def run_codex_with_streaming(task):
    """Stream responses while logging to governance"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": task}],
        stream=True
    )

    full_response = ""
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            print(content, end="")
            full_response += content

    # Log to governance after completion
    log_work(f"Streamed completion: {task[:50]}...", 0.5)

    return full_response
```

---

## Troubleshooting

### Error: "Connection refused"
→ Governance MCP server not running. Start with:
```bash
python src/mcp_server_sse.py --port 8765
```

### Error: "Tool not found"
→ Tool name mismatch. List available tools:
```bash
curl http://127.0.0.1:8765/v1/tools | jq '.tools[].function.name'
```

### Error: "Invalid arguments"
→ Check tool schema:
```bash
curl http://127.0.0.1:8765/v1/tools | jq '.tools[] | select(.function.name=="process_agent_update")'
```

### No governance feedback
→ Check session ID is set in `X-Session-ID` header

---

## Comparison: Native MCP vs HTTP API

| Feature | Native MCP (like Claude Code) | HTTP API (for OpenAI) |
|---------|------------------------------|----------------------|
| **Protocol** | SSE or stdio | HTTP POST/GET |
| **Format** | MCP JSON-RPC | OpenAI function calling |
| **Session** | Built-in | Manual (`X-Session-ID`) |
| **Performance** | Persistent connection | Request per call |
| **Best for** | MCP-native clients (Claude, Cursor) | Any HTTP client (OpenAI, custom) |

**When to use HTTP API:**
- OpenAI models (Codex, GPT-4)
- Custom applications
- Non-MCP clients
- Quick prototyping

**When to use native MCP:**
- Claude Code, Claude Desktop, Cursor
- Persistent sessions
- Lower latency

---

## Production Checklist

- [ ] Set stable `X-Session-ID` (don't change between requests)
- [ ] Handle governance PAUSE actions (don't ignore them)
- [ ] Log meaningful operation descriptions
- [ ] Set realistic complexity scores (0.0-1.0)
- [ ] Search knowledge graph before duplicating work
- [ ] Store discoveries for future agents
- [ ] Monitor EISV metrics to prevent burnout
- [ ] Enable authentication (`UNITARES_HTTP_API_TOKEN`)
- [ ] Use HTTPS in production (not HTTP)
- [ ] Implement rate limiting
- [ ] Log errors for debugging

---

## Next Steps

1. **Try the example:** Run the complete example above
2. **Explore tools:** Browse `/v1/tools` to see all available governance functions
3. **Multi-agent:** Run 2+ Codex agents, see them coordinate via knowledge graph
4. **Monitor:** Watch EISV metrics evolve as agents work
5. **Scale:** Deploy multiple agents using same governance MCP instance

---

**See also:**
- `tests/test_openai_endpoints.py` - Working test examples
- `docs/guides/START_HERE.md` - General agent onboarding
- `docs/analysis/USE_CASES_ANALYSIS.md` - Multi-agent use cases

---

**Last Updated:** December 22, 2025
