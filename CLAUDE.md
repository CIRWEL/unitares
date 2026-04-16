# CLAUDE.md — unitares

## Project

UNITARES governance MCP server. Thermodynamic governance framework for AI agents (EISV state vectors, coherence tracking, dialectic resolution, knowledge graph).

## Stack

- Python 3.12+, asyncio
- PostgreSQL@17 + AGE 1.7.0 (Apache Graph Extension) via Homebrew
- Redis (optional session cache)
- Pydantic v2 for parameter validation
- MCP (Model Context Protocol) server

## Setup

1. Install PostgreSQL@17 with AGE extension
2. Create a `governance` database
3. Install dependencies: `pip install -e .`
4. Copy `scripts/ops/com.unitares.governance-mcp.plist` to `~/Library/LaunchAgents/` and fill in paths/tokens (see template comments)
5. Start: `python src/mcp_server.py --port 8767`

## Before Committing

- **ALWAYS run `./scripts/test-cache.sh` before committing** (tree-hash cache — skips if tests already passed against this exact working tree; use `--fresh` to force a re-run)
- Fix any test failures your changes introduce — do not commit broken tests
- If you change a function's behavior or signature, update its tests in the same commit
- If you do a mechanical refactor (renames, import changes), update affected test mocks before committing
- The pre-push hook will block pushes with test failures

## Architecture Patterns

- **governance_core is an external compiled package** — there is NO `governance_core/` directory in this repo. The EISV dynamics engine is in a separate private repo and installed as a compiled `.so` wheel. Code in `src/` imports it as `from governance_core import X`. Do not try to create or recreate `governance_core/`.
- **LazyMCPServer**: All handler modules import `lazy_mcp_server as mcp_server` from `shared.py` (single definition, no per-file copies). Tests patch `{MODULE}.mcp_server` not `get_mcp_server`.
- **Pydantic validation**: Parameter validation uses Pydantic schemas in `src/mcp_handlers/schemas/`. Legacy `validate_and_coerce_params` is removed.
- **Handler modules**: Each in `src/mcp_handlers/`, decorated with `@mcp_tool`.

## Database

- PostgreSQL@17 on port 5432 with AGE graph extension
- Requires `brew services start postgresql@17`
- Check connectivity: `pg_isready -h localhost -p 5432`
- Do NOT create additional PostgreSQL instances, databases, or migration layers

## Git Rules

- Do not force-push
- Do not run destructive git commands without explicit user approval
- Do not run DROP/TRUNCATE/DELETE on the governance database without explicit user approval
- Do not include Co-Authored-By lines in commit messages

## Known Issue: anyio-asyncio Conflict

The MCP SDK's anyio task group conflicts with asyncpg/Redis async operations. MCP tool handlers that `await` DB calls can deadlock.

**Mitigated (Option F):** `health_check` reads a cached snapshot produced by a background probe task. No DB calls in the handler path. Any *new* MCP handler that needs DB access must either read cached data or use `run_in_executor` with a sync client.

## Known Test Notes

- Knowledge graph AGE tests require a live AGE connection (errors, not failures, when unavailable)

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
