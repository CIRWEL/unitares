# December 2025 Archive Index

**Archive Date**: December 20, 2025 (initial), December 22, 2025 (update)
**Archived By**: Cleanup automation + Claude Code agent
**Reason**: Root directory cleanup and historical doc organization

---

## December 22 Additions (Historical Troubleshooting & Implementation Docs)

Archived as completed/historical work:

- **CURSOR_FIX.md** (from root)
  - Troubleshooting guide for Cursor MCP configuration
  - Fixed: ngrok URL → local server configuration
  - Historical fix documentation

- **TRANSPORT_MIGRATION_STATUS.md** (from root)
  - Migration status snapshot: SSE → Streamable HTTP
  - Dual transport implementation complete
  - Date: December 20, 2025

- **CONTEXT_BLOAT_ANALYSIS.md** (from docs/guides/)
  - Analysis of context usage in MCP server
  - Identified issues with knowledge graph queries, state objects
  - Implementation fixes completed

- **CLAUDE_DESKTOP_FREEZE_MITIGATION.md** (from docs/guides/)
  - Solutions for Claude Desktop freezing during blocking operations
  - Async I/O implementation complete
  - Historical implementation guide

---

## Business Documents (Moved, Not Archived)

These were moved to `docs/business/` as they're current but not technical documentation:

- **TECH_PROFORMA.md** → `docs/business/TECH_PROFORMA.md`
  - Technical assessment for investor/partner due diligence
  - DeepTech AI Governance Platform overview
  - Date: December 20, 2025

- **FINANCIAL_PROFORMA_ANALYSIS.md** → `docs/business/FINANCIAL_PROFORMA_ANALYSIS.md`
  - Pre-seed round analysis ($2.25M, 24-month runway)
  - Burn rate calculations and runway math
  - Date: December 20, 2025

---

## Architecture Documents (Moved to Architecture)

These were moved to `docs/architecture/` as they document implemented systems:

- **TOOL_STABILITY_SYSTEM.md** → `docs/architecture/TOOL_STABILITY_SYSTEM.md`
  - Tool stability tier system (STABLE/BETA/EXPERIMENTAL)
  - Automatic aliases and migration helpers
  - Implementation: `src/mcp_handlers/tool_stability.py`
  - Date: December 20, 2025

---

## Analysis Documents (Archived - Point-in-Time)

These were archived to `docs/archive/2025-12/analysis/` as historical analysis:

- **TOOL_CONSOLIDATION_ANALYSIS.md**
  - Tool consolidation incoherence analysis
  - Dialectic tools consolidation (5+ → 2)
  - 37 total tools, ~15+ deprecated
  - Date: December 20, 2025

- **TOOL_CONSOLIDATION_FIXES.md**
  - Implementation notes for tool consolidation
  - Fixes and adjustments made during consolidation
  - Date: December 20, 2025

---

## What Was NOT Archived

After verification against source code, these specs remain **ACTIVE** and were kept in place:

- ❌ **POSTGRES_AGE_MIGRATION.md** - PostgreSQL/AGE backend is actively used (21 files)
- ❌ **UNITARES_V41_INTEGRATION.md** - v4.1 params profile actively used in code
- ❌ **UNITARES_V41_FIXES.md** - v4.1 features still current

---

## Archive Statistics

**Before Cleanup**:
- Root directory: 7 markdown files
- Total markdown files: 97

**After Cleanup**:
- Root directory: 2 markdown files (README.md, CHANGELOG.md) ✅
- Total markdown files: 97 (reorganized, not deleted)

**Reduction**: 71% root directory cleanup

---

## Verification Methodology

All moves were verified against source code to ensure:
1. No active code dependencies
2. No breaking changes to imports
3. Documentation remains accessible

**Lesson Learned**: Always verify specs against actual implementation - "migration complete" docs may describe active systems!
