# CLAUDE.md — governance-mcp-v1

## Project

UNITARES governance MCP server. Thermodynamic governance framework for AI agents (EISV state vectors, coherence tracking, dialectic resolution, knowledge graph).

## Stack

- Python 3.12+, asyncio
- PostgreSQL + AGE (Apache Graph Extension) via Docker (`postgres-age` on port 5432)
- Redis (optional session cache, port 6379)
- Pydantic v2 for parameter validation
- MCP (Model Context Protocol) server on port 8767

## Before Committing

- **ALWAYS run `python3 -m pytest tests/ -q --tb=short -x` before committing**
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

- **ONE database**: Docker `postgres-age` on port 5432 (`postgresql://postgres:postgres@localhost:5432/governance`)
- Test database: `governance_test` on same server
- **Never use bare `psql`** — always `docker exec postgres-age psql -U postgres -d governance`
- Homebrew PostgreSQL on port 5433 is a different project — do not use it

## Git Rules

- Do not force-push
- Do not run destructive git commands without explicit user approval
- Do not run DROP/TRUNCATE/DELETE on the governance database without explicit user approval
- Do not include Co-Authored-By lines in commit messages

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
