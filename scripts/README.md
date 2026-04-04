# Scripts Directory

**Last Updated:** March 2026

> **Note:** Most functionality is available via MCP tools. Scripts are for CLI-only interfaces, operations, and maintenance.

---

## Root Scripts

Utility scripts that live directly in `scripts/`:

| Script | Description |
|--------|-------------|
| `backup_governance.sh` | Backup governance database (auto-starts container, retries, status JSON, optional macOS alert on failure) |
| `check_governance_backup_health.sh` | Exit non-zero if backups are older than `MAX_AGE_SEC` (default 26h); for cron/monitoring |
| `bump_epoch.py` | Bump governance epoch |
| `check_ci_python_version_sync.py` | Verify CI Python version matches project |
| `count_tools.py` | Count registered MCP tools |
| `update_docs_tool_count.py` | Update tool counts in documentation |
| `version_manager.py` | Version management utilities |

---

## `ops/` — Operational Scripts

The bulk of operational scripts live in `scripts/ops/`.

### Agents & CLI

| Script | Description |
|--------|-------------|
| `heartbeat_agent.py` | Periodic heartbeat agent for health monitoring |
| `mcp_agent.py` | Autonomous MCP agent |
| `operator_agent.py` | Operator-level agent with elevated permissions |
| `governance_cli.sh` | Governance CLI wrapper |
| `answer_lumen_questions.py` | Answer Lumen's questions via governance data |

### Server Lifecycle

| Script / file | Description |
|----------------|-------------|
| `ops/com.unitares.governance-backup.plist` | LaunchAgent template: daily DB backup at 03:00 (copy to `~/Library/LaunchAgents/`, adjust paths) |
| `start_unitares.sh` | Start the governance MCP server |
| `stop_unitares.sh` | Stop the governance MCP server |
| `start_server.sh` | Alternative server start |
| `start_with_deps.sh` | Start server with all dependencies |
| `deploy_ngrok.sh` | Deploy ngrok tunnel |

### Health & Monitoring

| Script | Description |
|--------|-------------|
| `monitor_health.sh` | Health monitoring loop |
| `health_watchdog.sh` | Process watchdog with auto-restart |

### Database & Connections

| Script | Description |
|--------|-------------|
| `emergency_fix_postgres.sh` | Emergency PostgreSQL fixes |
| `fix_database_connections.sh` | Fix connection pool issues |
| `cleanup_stale_connections.sh` | Clean stale database connections |
| `cleanup_stale.sh` | General stale data cleanup |

### Git & CI

| Script | Description |
|--------|-------------|
| `install_git_hooks.sh` | Install git hooks |
| `update_changelog.py` | Update changelog from commits |
| `version_manager.py` | Version management (ops copy) |

### Launchd Plists (reference copies)

| File | Description |
|------|-------------|
| `com.unitares.governance-mcp.plist` | Governance MCP launchd config |
| `com.unitares.gateway-mcp.plist` | Gateway MCP launchd config |

Installed location: `~/Library/LaunchAgents/`

---

## Subdirectories

### `age/`
AGE (Apache Graph Extension) utilities — bootstrap SQL, export scripts, sample Cypher queries.

### `analysis/`
Analysis and reporting scripts.

### `diagnostics/`
Diagnostic scripts for debugging server and agent issues.

### `migration/`
Database maintenance scripts (embeddings backfill, EISV semantics backfill, ghost agent cleanup, knowledge graph maintenance).

### `git-hooks/`
Git hook scripts (pre-commit, pre-push).

### `safeguards/`
Safety-related scripts and checks.

### `archive/`
Archived scripts organized by type — completed migrations, deprecated CLI tools, one-off session scripts.

---

## Adding New Scripts

1. **Is it operational?** Put it in `ops/`
2. **Is it a dev/CI utility?** Put it in root `scripts/`
3. **Is it a test?** Put it in `tests/`
4. **Is it one-off?** Plan to archive after use
5. **Document it** in this README
6. **Consider MCP** — Can this be an MCP tool instead?

---

## Service Management

```bash
# Restart governance-mcp
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Check logs
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```
