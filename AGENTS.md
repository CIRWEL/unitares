# AGENTS.md — unitares

Bootstrap for Codex (and other non-Claude) sessions in this repo. Content below the `SHARED CONTRACT` markers is kept byte-identical with `CLAUDE.md` — CI (`scripts/dev/check-shared-contract.sh`) enforces parity. Edit shared rules in **both** files; edit the Codex preamble here only.

For a human-facing Codex quickstart (modes, minimal session pattern, what to watch), see `CODEX_START.md`.

## Codex-specific wiring

Codex has no hook system analogous to Claude's. **Nothing is automatic.** You decide when to check in, diagnose, and surface Watcher findings.

### Slash commands (`commands/*.md`)

- `/governance-start` — onboard or resume; refreshes local continuity state
- `/checkin` — governance update after meaningful work
- `/diagnose` — identity, state, and operator diagnostics
- `/dialectic` — structured review

Raw tool flow when slash commands are unavailable: `onboard()` → save `uuid` → `identity(agent_uuid=..., resume=true)` → `process_agent_update(response_text, complexity)` → `get_governance_metrics()` for read-only checks → `health_check()` only if system health is suspect.

### Local continuity cache

`.unitares/session.json` is Codex's authoritative local workspace state (not Claude's memory system). It holds `uuid`, `continuity_token`, `client_session_id`, `session_resolution_source`, `identity_assurance`. Helper: `scripts/client/session_cache.py`. On every session, restart, call `identity(agent_uuid=<saved uuid>, resume=true)`.

If `session_resolution_source` falls back to a weak source, rerun `/governance-start` or re-resume explicitly.

### Watcher visibility is manual

There is no `PostToolUse` hook to surface findings. To see and close them:

```bash
python3 agents/watcher/agent.py --list-findings --only-open   # list open/surfaced findings
python3 agents/watcher/agent.py --print-unresolved            # print unresolved block without mutating
python3 agents/watcher/agent.py --surface-pending             # print + transition open→surfaced
python3 agents/watcher/agent.py --resolve <fingerprint>       # mark confirmed (fixed)
python3 agents/watcher/agent.py --dismiss <fingerprint>       # mark false positive
```

Reference fingerprints in the commit message — Watcher's audit trail lives in commits, not tracked files (`data/watcher/` is gitignored).

### What Codex should NOT reference

- `hooks/` — Claude plugin manifest; has no meaning in Codex.
- `.claude/CLAUDE.md` — Claude-only machine-local overlay.
- `~/.claude/projects/.../memory/MEMORY.md` — Claude's memory system; Codex uses `.unitares/session.json` instead.

<!-- BEGIN SHARED CONTRACT — keep byte-identical across AGENTS.md and CLAUDE.md; scripts/dev/check-shared-contract.sh enforces parity -->

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

- **ALWAYS run `./scripts/dev/test-cache.sh` before committing** (tree-hash cache — skips if tests already passed against this exact working tree; use `--fresh` to force a re-run)
- **If you edit `AGENTS.md` or `CLAUDE.md`**, also run `./scripts/dev/check-shared-contract.sh` to confirm the shared block stayed in sync
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

**Mitigated (Option F):** `health_check` reads a cached snapshot produced by a background probe task. No DB calls in the handler path. Any *new* MCP handler that needs DB access must use one of three patterns:

1. **Read cached data** populated by a background task (e.g., `health_check` reads `deep_health_probe_task`'s snapshot; sticky identity reads a cache pre-warmed by `transport_binding_cache_warmup`).
2. **`run_in_executor` with a sync client** — see `call_pi_tool` at `src/mcp_handlers/observability/pi_orchestration.py:221`.
3. **`asyncio.wait_for` with a tight timeout** — degrade to a fallback on deadlock instead of hanging the pipeline. See `deep_health_probe_task` at `src/background_tasks.py:380` and `_load_binding_from_redis` at `src/mcp_handlers/middleware/identity_step.py` (500ms budget, returns `None` on timeout).

## Known Test Notes

- Knowledge graph AGE tests require a live AGE connection (errors, not failures, when unavailable)

## Minimal Agent Workflow

Default happy path:

1. `onboard()` → save `agent_uuid` from response
2. `identity(agent_uuid=..., resume=true)` on subsequent connections
3. `process_agent_update(response_text=..., complexity=...)`

Identity rule:

- Store `agent_uuid` in a session file. Pass it on every `identity()` call.
- UUID is the ground truth. No tokens or session IDs needed for resident agents.
- `client_session_id` and `continuity_token` still work for external/ephemeral clients.

<!-- END SHARED CONTRACT -->
