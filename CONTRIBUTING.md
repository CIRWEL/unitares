# Contributing to UNITARES

Thanks for your interest in contributing to UNITARES. This guide covers the practical setup for getting a development environment running and submitting changes.

## Development Setup

### Prerequisites

- Python 3.12 or newer
- Docker (for PostgreSQL + AGE)
- Redis (optional, for session caching)

### Clone and Install

```bash
git clone https://github.com/CIRWEL/unitares.git
cd unitares
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-core.txt
```

### Database

UNITARES uses PostgreSQL 16+ with the [Apache AGE](https://github.com/apache/age) graph extension for the knowledge graph, and pgvector for embeddings. The easiest way to get both running:

```bash
docker compose -f scripts/age/docker-compose.age.yml up -d
```

This starts a `postgres-age` container on port 5432 with both extensions pre-installed. The governance database and test database are created automatically on first run.

**Important:** Always access the database through Docker, not bare `psql`:

```bash
docker exec postgres-age psql -U postgres -d governance
```

Bare `psql` may connect to a different PostgreSQL instance on the host and give misleading results.

## Running Tests

The test suite has 5,700+ tests covering ~80% of the codebase:

```bash
# Full suite (recommended before PRs)
python3 -m pytest tests/ -x -q

# Specific test file
python3 -m pytest tests/test_governance_monitor.py -v

# With coverage report
python3 -m pytest tests/ --cov=src --cov-report=term-missing
```

Tests use a separate `governance_test` database and mock external services. Most tests run without any live infrastructure — only a few integration tests in `test_knowledge_graph_handlers.py` require a running AGE instance.

### Known Notes

- Knowledge graph AGE tests require a live AGE connection (errors, not failures, when unavailable)

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `governance_core` (external) | Pure mathematics — ODE solvers, coherence functions, risk scoring. Distributed as a compiled package (unitares-core, private). |
| `src/` | Production MCP server, handler modules, database backends, middleware |
| `src/mcp_handlers/` | Individual tool handlers, each decorated with `@mcp_tool` |
| `src/mcp_handlers/schemas/` | Pydantic v2 parameter schemas for validation |
| `src/db/` | PostgreSQL + AGE database backend |
| `dashboard/` | Web dashboard (vanilla JS + Chart.js) |
| `papers/` | Academic paper with contraction proofs and stability analysis |
| `tests/` | Test suite, mirroring source structure |

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

**For local development with source:** If you need to modify the core engine, symlink the source:
```bash
pip uninstall unitares-core -y
ln -sf ~/projects/unitares-core/governance_core governance_core
```

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
