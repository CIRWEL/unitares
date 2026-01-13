# MCP Agent Shorthand (`mcp_agent.py`)

Eliminate the "wrapper tax" for AI agents interacting with the Governance MCP system.

## The Problem
Agents (like Claude Code, Gemini CLI, etc.) often struggle to interface with MCP servers because:
1.  **Boilerplate:** Connecting to SSE/HTTP requires 20+ lines of `asyncio`/`httpx` code.
2.  **Syntax Errors:** Agents frequently make mistakes with f-string escaping (`{{}}`) when writing Python scripts.
3.  **Session Loss:** Ephemeral scripts lose the `client_session_id`, breaking identity continuity.

## The Solution
`scripts/mcp_agent.py` is a zero-boilerplate CLI tool designed for agents.

- **Pre-installed:** Always available in the repo.
- **Robust:** Handles connection, session saving/loading, and error parsing.
- **Simple:** Input `key=value` or `--json`. Output `JSON`.

## Usage

### 1. Basic Tool Call
Call a tool with simple string/number arguments.

```bash
python3 scripts/mcp_agent.py identity
python3 scripts/mcp_agent.py process_agent_update response_text="Working on feature" complexity=0.5
```

### 2. Complex Arguments (JSON)
For nested objects or lists, use `--json`.

```bash
python3 scripts/mcp_agent.py store_knowledge_graph --json '{
  "discovery_type": "insight",
  "summary": "Found a pattern in the data",
  "tags": ["pattern", "analysis"],
  "severity": "medium"
}'
```

### 3. List Tools
See what's available.

```bash
python3 scripts/mcp_agent.py list_tools
```

### 4. Explicit URL
Target a specific server (defaults to `http://localhost:8765/sse` or `/mcp/`).

```bash
python3 scripts/mcp_agent.py identity --url http://localhost:8765/mcp/
```

## Features for Agents

- **Session Continuity:** Automatically saves `client_session_id` to `.mcp_session` and injects it into future calls. You don't need to track it manually.
- **Smart Transport:** Auto-detects Streamable HTTP (`/mcp`) vs SSE (`/sse`).
- **Clean Output:** Returns valid JSON. If the tool fails, returns `{"success": False, "error": "..."}`.

## Example Workflow

```bash
# 1. Onboard (creates identity + saves session)
python3 scripts/mcp_agent.py onboard

# 2. Work (session ID injected automatically)
python3 scripts/mcp_agent.py process_agent_update response_text="Analyzed logs" complexity=0.8

# 3. Store Knowledge
python3 scripts/mcp_agent.py leave_note text="System is stable" tags='["status"]'
```