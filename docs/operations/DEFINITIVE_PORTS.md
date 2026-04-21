# Definitive Ports

Status: thin operational registry. Keep this file small and factual.

## Standard Assignments

| Port | Service | Host | Canonical source |
|------|---------|------|------------------|
| `8766` | Anima MCP | Pi / Lumen host | `anima-mcp` service config |
| `8767` | UNITARES governance | Mac / governance host | `src/mcp_server.py` default |

## Current Usage

- Anima MCP: `http://<pi-host>:8766/mcp/`
- Governance MCP: `http://127.0.0.1:8767/mcp/`
- Governance health: `http://127.0.0.1:8767/health`

## Files That Must Stay Aligned

- `src/mcp_server.py`
- `src/mcp_handlers/observability/pi_orchestration.py`
- Pi-side anima service configuration

## Verification

```bash
lsof -i :8767
curl http://127.0.0.1:8767/health
```

If anima connectivity is relevant, verify the Pi-side port separately against the running service and deployment config.

## Read Next

- [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md): operator workflow and failure handling
- [../dev/CANONICAL_SOURCES.md](../dev/CANONICAL_SOURCES.md): authority ordering

**Last Updated:** 2026-04-04 (reduced to thin operational registry)
