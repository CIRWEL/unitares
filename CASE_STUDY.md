# UNITARES Case Study

Status: specialized project case study. Use this when evaluating the project scope, engineering decisions, and evidence in the repo rather than the runtime docs alone.

## One-Line Summary

UNITARES is a production runtime governance system for AI agents: an MCP/HTTP server that turns agent check-ins into shared state, verdicts, calibration signals, recovery workflows, and knowledge-graph-backed memory.

## Why This Project Matters

This is not a toy wrapper around an API. It is a fairly complete systems project with:

- a transport layer for MCP and REST clients
- stateful identity, session, and continuity handling
- concurrent update protection with per-agent locks
- behavioral scoring and verdict logic
- PostgreSQL + Apache AGE persistence
- a dashboard and operator surface
- CI and a large automated test suite

This repo is strongest when read as a systems project: a runtime service with multiple interfaces, persistent state, operational behavior, and a broad automated test surface.

## Problem

Most agent tooling focuses on output quality after the fact: was the answer correct, safe, or useful?

That leaves an operational gap. Teams still need a way to answer questions like:

- Is this agent stable right now?
- Is it getting riskier or less coherent over time?
- Should it keep going, get guidance, pause, or hand off?
- Can different agents share a readable state language without scraping logs by hand?

UNITARES addresses that gap by making agent condition legible at runtime.

## What The System Does

At a high level, the server accepts agent check-ins, derives an EISV state vector from observable behavior, persists that trajectory, and returns governance feedback.

Core capabilities:

- `onboard()` establishes identity and continuity material
- `process_agent_update()` records work and returns a verdict
- `get_governance_metrics()` exposes current state
- lifecycle, dialectic, observability, and knowledge tools support recovery and collaboration

For the project overview, see [README.md](README.md). For architecture truth, see [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md) and [docs/CANONICAL_SOURCES.md](docs/CANONICAL_SOURCES.md).

## Engineering Scope

- **Systems design:** The repo combines protocol design, backend logic, persistence, concurrency, observability, and product surface rather than stopping at a single script or model call.
- **Backend/API engineering:** The code supports MCP, REST, health endpoints, CLI usage, and structured tool dispatch across a large handler surface.
- **Stateful runtime thinking:** Identity continuity, session recovery, per-agent locking, and long-run trajectories are first-class concerns.
- **Reliability discipline:** The project includes GitHub Actions CI, smoke tests, coverage reporting, and a large regression suite.
- **Data modeling:** PostgreSQL, Apache AGE, and optional Redis are used for runtime state, knowledge graph storage, and session support.
- **Product sense:** The repo includes a dashboard, operator docs, troubleshooting, and a paper-level framing for the core idea.

## Concrete Evidence In The Repo

- Project framing and live status: [README.md](README.md)
- Canonical architecture summary: [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md)
- Source surface: `src/` with ~225 files
- Test surface: `tests/` with ~198 top-level files
- CI workflow: [.github/workflows/tests.yml](.github/workflows/tests.yml)
- Packaging and test configuration: [pyproject.toml](pyproject.toml)
- Dashboard implementation: [dashboard/index.html](dashboard/index.html), [dashboard/dashboard.js](dashboard/dashboard.js), [dashboard/styles.css](dashboard/styles.css)

## How To Evaluate It Quickly

If you want to evaluate the project quickly:

1. Start with the problem: agents need runtime state legibility, not only output evaluation.
2. Show the default flow in [README.md](README.md): onboard, process update, read metrics.
3. Point to [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md) to show the system is deliberate, not improvised.
4. Point to [.github/workflows/tests.yml](.github/workflows/tests.yml) and [pyproject.toml](pyproject.toml) to show discipline.
5. Point to the dashboard and Raspberry Pi/Lumen integration to show the system is actually deployed and used.

## Possible Documentation Improvements

The codebase itself is already substantial. Remaining improvements are mostly packaging:

- add a short demo video or GIF
- add one or two architecture screenshots near the top of the README
- keep the README top section outcome-oriented
- keep this case study factual and aligned with the canonical runtime docs
