# Contributing to UNITARES

Thanks for your interest in contributing to UNITARES. This guide covers the practical setup for getting a development environment running and submitting changes.

## Development Setup

### Prerequisites

- Python 3.12 or newer
- PostgreSQL 16+ with Apache AGE + pgvector (examples below use PostgreSQL 17)
- Redis (optional, for session caching)

### Clone and Install

```bash
git clone https://github.com/CIRWEL/unitares.git
cd unitares
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-core.txt   # lean dev/test deps
# or: pip install -r requirements-full.txt   # also needed to run the MCP server
```

Use `requirements-core.txt` for working on tests and handler code; use `requirements-full.txt` if you also want to run the MCP + HTTP stack locally (see the root [README](README.md) for the server start command).

### Database

UNITARES uses PostgreSQL 16+ with the [Apache AGE](https://github.com/apache/age) graph extension for the knowledge graph, and pgvector for embeddings.

See `db/postgres/README.md` for full setup instructions (Homebrew PostgreSQL 17 + AGE + pgvector).

Two databases are involved:

```bash
# Runtime database — what the server connects to
psql "$DB_POSTGRES_URL"

# Test database — a separate `governance_test` DB the integration tests use.
# Without it, the live-DB tests skip rather than fail.
createdb governance_test
```

## Running Tests

The preferred pre-commit gate matches what the pre-push hook runs — a tree-hash-cached wrapper that skips when tests have already passed against this exact working tree:

```bash
./scripts/dev/test-cache.sh            # use this before opening a PR
./scripts/dev/test-cache.sh --fresh    # force re-run
```

For inner-loop iteration (`pyproject.toml` `addopts` force coverage + verbose output, so bare `pytest` prints a lot — suppress with `--no-cov` and keep output tight):

```bash
python3 -m pytest tests/test_governance_monitor.py --no-cov --tb=short -q | tail -40
```

Tests use a separate `governance_test` database and mock external services. Most tests run without any live infrastructure — only a few integration tests in `test_knowledge_graph_handlers.py` require a running AGE instance.

### Known Notes

- Knowledge graph AGE tests require a live AGE connection (errors, not failures, when unavailable)

## Project Structure

| Path | Purpose |
|------|---------|
| `src/` | Production MCP server, handler modules, database backends, middleware |
| `src/mcp_handlers/` | Individual tool handlers, each decorated with `@mcp_tool` |
| `src/mcp_handlers/schemas/` | Pydantic v2 parameter schemas for validation |
| `src/db/` | PostgreSQL + AGE database backend |
| `dashboard/` | Web dashboard (vanilla JS + Chart.js) |
| `tests/` | Test suite, mirroring source structure |
| `unitares-core` (external wheel) | EISV dynamics engine — ODE solvers, coherence, risk scoring. Installed via `requirements-core.txt`; source lives in a separate private repo (see [Core Engine Dependency](#core-engine-dependency)). |

The companion paper lives in its own repo: [CIRWEL/unitares-paper-v6](https://github.com/CIRWEL/unitares-paper-v6).

## Code Style

- **Python 3.12+**, asyncio throughout the server and handler code
- **Pydantic v2** for all parameter validation — schemas live in `src/mcp_handlers/schemas/`
- **Handler pattern**: Each tool handler in `src/mcp_handlers/` uses the `@mcp_tool` decorator and `_LazyMCPServer` for deferred server access (avoids circular imports)
- **Core engine is external**: `governance_core` is a compiled dependency (unitares-core, private repo)
- **Tests mirror source**: A handler in `src/mcp_handlers/foo.py` has tests in `tests/test_foo_handlers.py`
- **No mock leakage**: Tests patch `{module}.mcp_server`, not `get_mcp_server` directly

## Core Engine Dependency

The EISV dynamics engine (`governance_core`) is distributed as a compiled package (`unitares-core`). It's listed in `requirements-core.txt` and installed automatically. The source lives in a separate private repository.

**For CI:** The GitHub Actions workflow checks out `unitares-core` using the `UNITARES_CORE_TOKEN` secret and builds it from source. Fork PRs will not have access to this token — a maintainer will run CI on your behalf.

**For local development with source:** If you have access to the core engine source and want to modify it, symlink your checkout into the repo root:
```bash
pip uninstall unitares-core -y
ln -sf /path/to/your/unitares-core/governance_core governance_core
```

(Adjust the path to wherever you cloned `unitares-core`.)

## Pull Requests

1. Create a feature branch from `master`
2. Make your changes with clear, focused commits
3. Run the full test suite — it must pass with no new failures
4. Open a PR with a description explaining **what** changed and **why**

The pre-push hook runs the test suite automatically and blocks pushes with failing tests.

## Areas for Contribution

Some areas where contributions would be particularly welcome:

- **Domain-specific parameter tuning** — The EISV dynamics use general-purpose defaults. How should thresholds differ for code generation agents vs. customer service agents vs. trading agents?
- **Horizontal scaling** — The current architecture handles hundreds of agents on a single node. Work toward multi-node deployments.
- **Outcome correlation** — Building the evidence base for whether EISV instability predicts bad task outcomes.
- **Dashboard improvements** — The web dashboard is functional but minimal. Better visualization of agent trajectories and knowledge graph structure.

## Questions?

Open an issue on GitHub or check the [documentation](README.md#documentation) for guides on specific topics.
