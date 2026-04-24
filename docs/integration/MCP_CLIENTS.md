# MCP client configuration

Client-specific JSON for pointing an MCP-aware tool at a local UNITARES governance server. Assumes the server is running on `http://localhost:8767/mcp/` — see the root README for startup.

## Cursor / Claude Code

Native `type: http` support:

```json
{
  "mcpServers": {
    "unitares": {
      "type": "http",
      "url": "http://localhost:8767/mcp/"
    }
  }
}
```

## Claude Desktop

Claude Desktop does not support `type: http` natively; use `mcp-remote` as a stdio bridge:

```json
{
  "mcpServers": {
    "unitares": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8767/mcp/"]
    }
  }
}
```

Agents self-identify through `onboard()`; no hardcoded agent-name header is required.

## Endpoints

| Endpoint | Transport | Use case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | MCP clients |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

## Bind address and security

The server binds to `127.0.0.1` by default. For LAN or remote access:

- Set `UNITARES_BIND_ALL_INTERFACES=1` (or `UNITARES_MCP_HOST` to an explicit interface).
- Configure `UNITARES_MCP_ALLOWED_HOSTS` and `UNITARES_MCP_ALLOWED_ORIGINS` (comma-separated) to allowlist Host and Origin headers.
- Optional: `UNITARES_HTTP_CORS_EXTRA_ORIGINS`, `UNITARES_MCP_ALLOW_NULL_ORIGIN` (default on for `file://`).

See [`scripts/ops/`](../../scripts/ops/) for an example LaunchAgent plist with bind-all plus allowlists.

## Resident agents

Save `agent_uuid` from `onboard()`, then pass it on subsequent connections via `identity(agent_uuid=..., resume=true)`. No token management is required for resident agents.

See also: [Getting Started](../guides/START_HERE.md), [Operator Runbook](../operations/OPERATOR_RUNBOOK.md).
