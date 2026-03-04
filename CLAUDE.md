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

- **ALWAYS run `python3 -m pytest tests/ -q --tb=short -x --ignore=tests/test_admin_handlers.py` before committing**
- Fix any test failures your changes introduce — do not commit broken tests
- If you change a function's behavior or signature, update its tests in the same commit
- If you do a mechanical refactor (renames, import changes), update affected test mocks before committing
- The pre-push hook will block pushes with test failures

## Architecture Patterns

- **LazyMCPServer**: All handler modules use `_LazyMCPServer` for deferred server access (avoids circular imports). Tests patch `{MODULE}.mcp_server` not `get_mcp_server`.
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

## Known Test Exclusions

- `tests/test_admin_handlers.py` — pre-existing `TOOL_PARAM_SCHEMAS` reference to removed code
- `tests/test_knowledge_graph_handlers.py` — some tests require live AGE connection (errors, not failures)

## Service Management

```bash
# Restart governance-mcp
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Logs
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```
