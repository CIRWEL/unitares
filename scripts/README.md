# Scripts Directory

**⚠️ IMPORTANT: Scripts are for CLI-only interfaces only**

**If you have MCP access (Cursor, Claude Desktop, etc.):**
- ✅ **Use MCP tools directly** - Don't use scripts
- ✅ **Use `list_tools()`** - Shows all 77 available tools
- ✅ **Full tool suite available** - Scripts are only for CLI-only interfaces

**If you DON'T have MCP access (CLI-only):**
- ⚠️ **Use scripts below** - Only for CLI-only interfaces
- ⚠️ **Limited functionality** - Scripts only provide basic bridge functionality

---

**Purpose:** Utility scripts for CLI-only interfaces and system maintenance

**Total Scripts:** 12 active scripts (6 automation + 6 utilities), 31 archived

---

## Core Scripts (Essential Only)

### Integration (1 script)
- **`claude_code_bridge.py`** - CLI bridge for non-MCP interfaces
  - Only script needed for CLI-only interfaces
  - Logs governance updates from Claude Code
  - Handles authentication automatically
  - Usage: `python3 scripts/claude_code_bridge.py --log "summary"`

### Maintenance (3 scripts)
- **`auto_archive_metadata.py`** - Automatic agent metadata archival
  - Keeps metadata.json lean
  - Usage: `python3 scripts/auto_archive_metadata.py` (or cron)

- **`archive_old_markdowns.py`** - Markdown file archival
  - Archives completed work and old files
  - Usage: `python3 scripts/archive_old_markdowns.py --dry-run`

- **`audit_markdown_proliferation.py`** - Markdown audit tool
  - Analyzes markdown file proliferation
  - Usage: `python3 scripts/audit_markdown_proliferation.py --stats`

### Validation (1 script)
- **`validate_all.py`** - Consolidated validation (replaces 2 scripts)
  - Validates project docs and layer consistency
  - Usage: `python3 scripts/validate_all.py`
  - Options: `--docs-only`, `--layers-only`

---

## Utility Scripts (As-Needed)

### Bug Management
- **`bugbot.py`** - Bug tracking bot (specialized)
- **`generate_bug_summary.py`** - Generate bug summaries
- **`update_bug_statuses.py`** - Update bug statuses
- **`resolve_recently_fixed_bugs.py`** - ⚠️ ARCHIVED - One-off script (moved to archive/)

### Migration Scripts (Archived)
- **Archived to `scripts/archive/`:**
  - `migrate_agent_api_keys.py` - Completed migration
  - `migrate_to_knowledge_graph.py` - Completed migration
  - `migrate_docs_to_knowledge.py` - Deprecated (knowledge layer deprecated)

### Export/Diagnostics
- **`export_claude_code.py`** - Export Claude Code data
- **`dashboard_simple.py`** - Simple dashboard
- **`diagnose_mcp_concurrency.py`** - MCP concurrency diagnosis
- **`smoke_test.py`** - Smoke tests

### Documentation Utilities
- **`check_small_markdowns.py`** - Check for small markdown files
- **`cleanup_docs.py`** - Documentation cleanup

### Registration
- **`register_claude_code.py`** - Register Claude Code agents

---

## Test Scripts

**Location:** `tests/` directory (moved from scripts/)

- `test_coherence_scenarios.py` - Coherence scenario tests (moved Nov 29)
- `test_critical_fixes.py` - Critical fix tests (moved Nov 29)
- `smoke_test.py` - Smoke tests (moved Nov 29)
- `test_organization.py` - Organization tests (previously moved)
- `test_organization_functional.py` - Functional organization tests (previously moved)

---

## Archived Scripts

**Location:** `scripts/archive/`

**Old Version Scripts:**
- `process_update_3.py` - Specific update #3 (one-off)
- `process_update_4.py` - Specific update #4 (one-off)
- `process_claude_code_update.py` - Old version
- `process_claude_code_update2.py` - Old version 2

**One-Off Fix Scripts:**
- `resolve_health_status_bug.py` - Completed bug fix
- `resolve_loop_detection_gap_bug.py` - Completed bug fix

**Session Scripts:**
- `process_architecture_session.py` - One-off session
- `finalize_claude_code_session.py` - One-off session
- `export_and_archive_agent.py` - One-off script (Sakamoto's redundant script)
- `finalize_agent_session.py` - One-off script
- `record_session_discoveries.py` - One-off script (archived Nov 29)

---

## Script Lifecycle

**Active Scripts:** Core integration, maintenance, validation  
**Utility Scripts:** As-needed tools, specialized functions  
**Archived Scripts:** Obsolete, one-off, completed migrations  
**Test Scripts:** Moved to `tests/` directory

---

## Adding New Scripts

**Before creating a new script:**

1. ❓ **Is it a test?** → Put in `tests/` directory
2. ❓ **Is it one-off?** → Plan to archive after use
3. ❓ **Is it documented?** → Add to this README
4. ❓ **Is it deprecated?** → Add deprecation notice

**Default:** Document in this README, plan for archival if one-off.

---

**Last Updated:** February 3, 2026
**Status:** 12 active scripts, 31 archived, 5 moved to tests/

**Key Change:** Most functionality provided by 77 MCP tools. Scripts only needed for CLI-only interfaces.

