# Housekeeping Notes

**Last Updated:** November 19, 2025

## Current Status

✅ **MCP Server:** Fixed and working (`src/mcp_server_std.py`)  
✅ **Config:** Valid JSON in `~/.cursor/mcp.json`  
✅ **Dependencies:** MCP SDK installed  
✅ **Documentation:** Complete  
✅ **Housekeeping:** Completed Nov 19, 2025

## Files Status

### Active Files
- `src/mcp_server_std.py` - **Main MCP server** (use this one)
- `src/governance_monitor.py` - Core governance framework
- `src/mcp_server.py` - JSON-RPC wrapper (for bridges)
- `scripts/claude_code_bridge.py` - Claude Code integration

### Legacy Files
- `src/mcp_server_entry.py` - Old entry point (superseded by `mcp_server_std.py`, kept for compatibility)

### Documentation
- `MCP_SETUP.md` - Setup guide ✅
- `MCP_FIX_SUMMARY.md` - Fix documentation ✅
- `README.md` - Main documentation ✅
- `QUICKSTART.md` - Quick start guide ✅

## Completed Cleanup (Nov 19, 2025)

✅ **Removed:** `test_mcp_tools.py` - Old test script  
✅ **Archived:** Old export files moved to `data_isolated/archived_exports_20251119/`  
✅ **Archived Agents:** `test_agent_001`, `test_coherence_check` (Nov 18 test agents)

### Data Directory Status
- **Active:** `agent_metadata.json` (essential)
- **Current Exports:** Latest `composer_cursor` recovery session exports (JSON + CSV)
- **Archived:** Old test exports moved to `data_isolated/`

### Agent Status
- **Active:** 5 agents (`composer_cursor`, `composer`, `claude_opus_4.1`, `who_governs_the_governors`, `cursor_ide`)
- **Archived:** 2 agents (`test_agent_001`, `test_coherence_check`)
- **Deleted:** 1 agent (`test_lifecycle_agent`)

## Notes

1. **`mcp_server_entry.py`** - Old entry point, kept for backward compatibility. New code should use `mcp_server_std.py`.

2. **`__pycache__`** - Python cache files (normal, can be ignored or cleaned with `.gitignore`)

3. **Config Location** - Cursor uses `~/.cursor/mcp.json` (not the Library path)

4. **Export Files** - Old test exports archived to `data_isolated/archived_exports_20251119/`. Only latest session exports kept in `data/`.

## Next Steps

1. ✅ MCP server fixed and working
2. ✅ Config file updated
3. ✅ Housekeeping completed (Nov 19, 2025)
4. ⏭️ Monitor agent activity and archive stale agents periodically

---

**Status:** All systems operational! 🚀

