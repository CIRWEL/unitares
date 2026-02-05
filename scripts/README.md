# Scripts Directory

**Last Updated:** 2026-02-04

> **Note:** Most functionality is available via MCP tools. Scripts are for CLI-only interfaces, operations, and maintenance.

**Active Scripts:** 67 | **Archived:** 49+

---

## CLI Tools

| Script | Description |
|--------|-------------|
| `unitares` | Main CLI wrapper for MCP calls |
| `unitares_lite.py` | Lightweight Python CLI |
| `mcp` | MCP CLI tool (governance_cli.sh symlinks here) |
| `mcp_call.py` | Direct MCP tool caller |
| `mcp_agent.py` | Autonomous MCP agent |
| `mcp_sse_client.py` | SSE client (legacy, use Streamable HTTP) |
| `operator_agent.py` | Operator-level agent with elevated permissions |

## Operations

| Script | Description |
|--------|-------------|
| `start_unitares.sh` | Start the governance MCP server |
| `stop_unitares.sh` | Stop the governance MCP server |
| `start_server.sh` | Alternative server start |
| `start_with_deps.sh` | Start with dependencies |
| `deploy_ngrok.sh` | Deploy ngrok tunnel |
| `monitor_health.sh` | Health monitoring |
| `watchdog.sh` | Process watchdog |
| `check_health.sh` | Quick health check |

## Database & Connections

| Script | Description |
|--------|-------------|
| `check_databases.sh` | Check database status |
| `emergency_fix_postgres.sh` | Emergency Postgres fixes |
| `fix_database_connections.sh` | Fix connection issues |
| `cleanup_stale_connections.sh` | Clean stale connections |
| `kill_idle_connections.sh` | Kill idle DB connections |

## Cleanup & Maintenance

| Script | Description |
|--------|-------------|
| `cleanup_stale.sh` | General stale data cleanup |
| `cleanup_mcp_servers.sh` | Clean zombie MCP processes |
| `cleanup_zombie_mcp_servers.sh` | Alternative zombie cleanup |
| `cleanup_knowledge_graph.py` | Knowledge graph cleanup |
| `cleanup_migration_summaries.py` | Clean migration summaries |
| `archive_old_markdowns.py` | Archive old markdown files |
| `archive_outdated_discoveries.py` | Archive old discoveries |
| `auto_archive_metadata.py` | Auto-archive agent metadata |

## Validation & Auditing

| Script | Description |
|--------|-------------|
| `validate_all.py` | Consolidated validation |
| `validate_doc_dates.sh` | Validate document dates |
| `validate_markdown_formatting.py` | Markdown format validation |
| `validate_theoretical_foundations.py` | Theory validation |
| `validate_tool_modes.py` | Tool mode validation |
| `validate_tool_registration.py` | Tool registration check |
| `audit_markdown_proliferation.py` | Markdown audit |
| `audit_tool_categories.py` | Tool category audit |
| `audit_error_messages.py` | Error message audit |

## Calibration & Analysis

| Script | Description |
|--------|-------------|
| `backfill_calibration.py` | Backfill calibration data |
| `report_calibration.py` | Generate calibration report |
| `reset_calibration.py` | Reset calibration |
| `analyze_drift.py` | Analyze EISV drift |
| `check_eisv_completeness.py` | EISV completeness check |
| `check_test_coverage.py` | Test coverage report |

## Backfill & Sync

| Script | Description |
|--------|-------------|
| `backfill_age_edges.py` | Backfill AGE graph edges |
| `backfill_embeddings.py` | Regenerate embeddings |
| `regenerate_embeddings.py` | Regenerate embeddings (alt) |
| `sync_discoveries_to_age.py` | Sync discoveries to AGE |
| `sync_bridge_with_mcp.py` | Sync bridge with MCP |

## Documentation & Tools

| Script | Description |
|--------|-------------|
| `generate_tool_docs.py` | Generate tool documentation |
| `update_changelog.py` | Update changelog |
| `update_readme_metadata.py` | Update README metadata |
| `update_docs_tool_count.py` | Update tool counts in docs |
| `doc_tools.py` | Documentation utilities |
| `count_tools.py` | Count registered tools |
| `version_manager.py` | Version management |

## Diagnostics

| Script | Description |
|--------|-------------|
| `diagnose_unresponsive_agents.py` | Diagnose stuck agents |
| `diagnose_date_context_connection.py` | Date context MCP debug |
| `test_date_context_connection.py` | Test date context connection |
| `verify_gpu_acceleration.py` | Verify GPU setup |
| `self_monitor.py` | Self-monitoring script |

## Specialized

| Script | Description |
|--------|-------------|
| `notion_bridge.py` | Notion integration bridge |
| `stdio-proxy-ngrok.py` | STDIO proxy for ngrok |
| `answer_lumen_questions.py` | Answer Lumen's questions |
| `process_current_session.py` | Process current session |
| `process_dialectic_synthesis.py` | Process dialectic synthesis |
| `repair_identity_agent_links.py` | Repair identity links |

## Git Hooks

| Script | Description |
|--------|-------------|
| `install_git_hooks.sh` | Install git hooks |
| `pre-commit-combined` | Combined pre-commit hook |
| `pre-commit-docs` | Docs pre-commit hook |
| `pre_commit_tool_count_check.sh` | Tool count check hook |
| `git-hooks/` | Git hooks directory |

---

## Subdirectories

### `age/`
AGE (Apache Graph Extension) utilities:
- `docker-compose.age.yml` - Docker config for AGE
- `bootstrap.sql` - AGE initialization
- `export_knowledge_sqlite_to_age.py` - Export to AGE
- `sample_queries.sql` - Sample Cypher queries
- `philosophical_queries.sql` - Advanced queries
- `HANDOFF_CLI.md` - CLI handoff documentation

### `archive/`
Archived scripts organized by type:
- `migrations_completed_202602/` - Completed migrations (SQLite to Postgres)
- `deprecated_20251210/` - Deprecated CLI tools
- One-off session scripts
- Completed bug fixes
- Old process scripts

### `safeguards/`
Safety-related scripts

---

## Adding New Scripts

1. **Is it a test?** Put in `tests/` directory
2. **Is it one-off?** Plan to archive after use
3. **Document it** in this README
4. **Consider MCP** - Can this be an MCP tool instead?

---

## Launchd Service

The plist for launchd is at:
- `com.unitares.governance-mcp.plist` (copy in this dir)
- Installed at: `~/Library/LaunchAgents/com.unitares.governance-mcp.plist`

```bash
# Restart service
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```
