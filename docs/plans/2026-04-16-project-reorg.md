# Project Directory Reorganization — Handoff Spec

**Date:** 2026-04-16
**Context:** Repo is heading public. Top-level is cluttered, stale artifacts linger, `src/` has 85 flat files, docs are scattered across 11 subdirectories. Goal: clean, navigable structure for external contributors.

## Phase 1: Delete stale artifacts (safe, no references)

```
rm .governance_session .kimi_governance_session .mcp_session
rm coverage.xml
rm -rf htmlcov/
rm -rf site/
rm data/mcp_server_sse_autostart.log data/mcp_server_sse.log
```

Add to `.gitignore` if not already: `htmlcov/`, `coverage.xml`, `site/`.

## Phase 2: Top-level cleanup

Move to `docs/`:
- `CASE_STUDY.md` → `docs/CASE_STUDY.md`
- `CONTRIBUTING.md` → `docs/CONTRIBUTING.md` (symlink at root if needed for GitHub)
- `CHANGELOG.md` → `docs/CHANGELOG.md`

Keep at root (GitHub convention):
- `README.md`, `CLAUDE.md`, `CODEX_START.md`, `LICENSE`, `Makefile`, `VERSION`
- `pyproject.toml`, `requirements-*.txt`, `uv.lock`

## Phase 3: `docs/` flatten

Current structure has 11 subdirectories, some with 1-2 files. Proposed:

```
docs/
  guides/          # START_HERE, TROUBLESHOOTING (keep)
  operations/      # OPERATOR_RUNBOOK, DEFINITIVE_PORTS (keep)
  dev/             # TOOL_REGISTRATION (keep)
  architecture/    # UNIFIED_ARCHITECTURE, database_architecture, CIRCUIT_BREAKER_DIALECTIC, CANONICAL_SOURCES
  handoffs/        # session handoff specs (keep)
  plans/           # implementation plans (keep, merge superpowers/plans/ into here)
  specs/           # design specs (merge superpowers/specs/ into here)
  assets/          # images, diagrams
```

Remove/archive:
- `docs/meta/` (1 file: MARKDOWN_PROLIFERATION_POLICY — move to docs/ root or archive)
- `docs/engineering/` (merge into plans/ or handoffs/)
- `docs/superpowers/` (dissolve — specs/ and plans/ move up)
- `docs/queries/` (just a README — remove or merge)
- `docs/DATA_NOTES.md`, `docs/DEPLOYMENT_DATA_CAVEAT.md` — move to `docs/operations/` or archive

## Phase 4: `scripts/` organize

Current: 15 files flat + subdirectories. Group by purpose:

```
scripts/
  ops/             # launchd plists, backup, restart (exists, keep)
  analysis/        # eisv_pca_analysis, count_tools (exists, keep)
  migration/       # db migration scripts (exists, keep)
  dev/             # test-cache.sh, bump_epoch, version_manager, doc_audit
  client/          # session_cache, onboard_helper (exists, keep)
```

Move loose files into appropriate subdirectory. Update any shell scripts that reference moved paths.

## Phase 5: `src/` modularize (LARGE — separate PR)

85 `.py` files flat in `src/`. The `monitor_*.py` files (10 files) and `agent_*.py` files (10 files) are obvious module candidates:

```
src/
  monitors/        # monitor_calibration, monitor_cirs, monitor_decision, etc.
  agent/           # agent_lifecycle, agent_metadata_model, agent_storage, etc.
  identity/        # already exists as src/mcp_handlers/identity/
  services/        # already exists
  storage/         # already exists
  cache/           # already exists
  db/              # already exists
```

**WARNING:** This changes import paths project-wide. Every `from src.monitor_risk import ...` becomes `from src.monitors.risk import ...`. Requires updating all imports in `src/`, `tests/`, `agents/`, and any external callers. Use a tool like `rope` or do it mechanically with grep+sed. Run full test suite after.

This is the riskiest phase. Consider doing it as a separate branch/PR with careful review.

## Phase 6: `data/` cleanup

```
data/
  logs/            # mcp_server.log, error logs (keep)
  agents/          # per-agent runtime state (keep)
  agents_archived/ # archived agent state (keep)
  watcher/         # watcher state (keep, gitignored)
  exports/         # governance exports (keep)
  knowledge/       # KG data (keep)
  calibration_state.json  # keep
  audit_log.jsonl         # keep
```

Remove:
- `data/mcp_server_sse.log`, `data/mcp_server_sse_autostart.log` (Phase 1)
- `data/test_files/` — move to `tests/fixtures/` if still needed
- `data/gov-data-preserve/` — archive or remove if contents are in backups
- `data/server_restart.log` — stale

## Execution order

1. Phase 1 (deletions) — safe, no dependencies
2. Phase 2 (top-level) — low risk, update any internal links
3. Phase 3 (docs/) — low risk, update cross-references
4. Phase 4 (scripts/) — medium risk, update shell script paths
5. Phase 6 (data/) — low risk, mostly cleanup
6. Phase 5 (src/) — HIGH risk, separate PR, full test suite validation

Phases 1-4 can be done by subagents in parallel (no overlapping files). Phase 5 needs careful sequential execution with tests after each move.
