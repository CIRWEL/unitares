# CLAUDE.md — unitares

## Project

UNITARES governance MCP server. Thermodynamic governance framework for AI agents (EISV state vectors, coherence tracking, dialectic resolution, knowledge graph).

## Stack

- Python 3.12+, asyncio
- PostgreSQL@17 + AGE 1.7.0 (Apache Graph Extension) via Homebrew on port 5432
- Redis (optional session cache, port 6379)
- Pydantic v2 for parameter validation
- MCP (Model Context Protocol) server on port 8767

### MCP listen defaults (security)

- **Default bind:** `127.0.0.1` unless `UNITARES_BIND_ALL_INTERFACES=1` (then `0.0.0.0`) or `UNITARES_MCP_HOST` is set.
- **Transport allowlists:** localhost always; add `UNITARES_MCP_ALLOWED_HOSTS` and `UNITARES_MCP_ALLOWED_ORIGINS` (comma-separated) for LAN/Cloudflare tunnel Host headers. Optional: `UNITARES_HTTP_CORS_EXTRA_ORIGINS`, `UNITARES_MCP_ALLOW_NULL_ORIGIN` (default on for `file://`).
- LaunchAgent `scripts/ops/com.unitares.governance-mcp.plist` sets bind-all + example allowlists for this machine.

## Before Committing

- **ALWAYS run `python3 -m pytest tests/ agents/ -q --tb=short -x` before committing**
- Fix any test failures your changes introduce — do not commit broken tests
- If you change a function's behavior or signature, update its tests in the same commit
- If you do a mechanical refactor (renames, import changes), update affected test mocks before committing
- The pre-push hook will block pushes with test failures

## Architecture Patterns

- **governance_core is an external compiled package** — there is NO `governance_core/` directory in this repo. The EISV dynamics engine (ODEs, coherence, scoring, ethical drift) is in a separate private repo (`unitares-core`) and installed as a compiled `.so` wheel. Code in `src/` imports it as `from governance_core import X` — these resolve to the installed package in site-packages, not a local directory. Do not try to create or recreate `governance_core/`. Do not try to read its source — it's compiled. To work with source: `ln -sf ~/projects/unitares-core/governance_core governance_core`
- **LazyMCPServer**: All handler modules import `lazy_mcp_server as mcp_server` from `shared.py` (single definition, no per-file copies). Tests patch `{MODULE}.mcp_server` not `get_mcp_server`.
- **Pydantic validation**: Parameter validation uses Pydantic schemas in `src/mcp_handlers/schemas/`. Legacy `validate_and_coerce_params` is removed.
- **Handler modules**: Each in `src/mcp_handlers/`, decorated with `@mcp_tool`.

## Database

- **ONE database**: Homebrew PostgreSQL@17 on port 5432 (`postgresql://postgres:postgres@localhost:5432/governance`)
- Requires `brew services start postgresql@17`. If governance crashes with "Connect call failed", check `pg_isready -h localhost -p 5432`.
- Access: `psql -h localhost -U postgres -d governance`
- Backups: `/Users/cirwel/backups/governance/` (daily pg_dump via launchd)
- Do NOT create additional PostgreSQL instances, databases, or migration layers. One database, one location.

## Git Rules

- Do not force-push
- Do not run destructive git commands without explicit user approval
- Do not run DROP/TRUNCATE/DELETE on the governance database without explicit user approval
- Do not include Co-Authored-By lines in commit messages

## Known Issue: anyio-asyncio Conflict

The MCP SDK's anyio task group conflicts with asyncpg/Redis async operations. MCP tool handlers that `await` DB calls can deadlock.

**Mitigated (Option F — shipped):** `health_check` now reads a cached snapshot produced by `deep_health_probe_task` on the main event loop. No DB calls in the handler path. REST endpoints: `/health/live`, `/health/ready`, `/health/deep`. See `docs/handoffs/2026-04-10-option-f-spec.md`.

**Remaining workarounds:** `call_pi_tool` uses sync httpx in executor thread. Any *new* MCP handler that needs DB access must either read cached data or use `run_in_executor` with a sync client — do not `await` asyncpg directly from a handler.

## Known Test Notes

- Knowledge graph AGE tests require a live AGE connection (errors, not failures, when unavailable)

## Service Management

```bash
# Restart governance-mcp
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Logs
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```

## Minimal Agent Workflow

Default happy path:

1. `onboard()`
2. Save `client_session_id`
3. `process_agent_update(response_text=..., complexity=..., client_session_id=...)`
4. `get_governance_metrics(client_session_id=...)`

Continuity rule:

- If `continuity_token_supported=true`, prefer `continuity_token` for resume
- Otherwise pass `client_session_id` in every call
- If `session_resolution_source="ip_ua_fingerprint"`, continuity is weak and explicit continuity values should be passed on every call
