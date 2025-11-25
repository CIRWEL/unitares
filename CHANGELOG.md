# Changelog

All notable changes to the UNITARES Governance Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.0] - 2025-11-25

### Added - Auto-Healing Infrastructure 🛡️

#### Enhanced State Locking System
- **Automatic stale lock detection** - `is_process_alive()` checks for dead processes
- **Smart lock cleanup** - `_check_and_clean_stale_lock()` removes locks from crashed processes
- **Exponential backoff retry** - 3 attempts with 0.2s * 2^attempt wait times
- **Process health checking** - Validates PIDs before lock cleanup
- **Self-recovering** - No manual intervention needed for lock contention

#### Loop Detection & Prevention
- **Activity tracking** - New AgentMetadata fields:
  - `recent_update_timestamps: list[str]` - Track update timing
  - `recent_decisions: list[str]` - Track decision patterns
  - `loop_detected_at: str` - Timestamp of loop detection
  - `loop_cooldown_until: str` - Block updates until this time
- **Pattern detection** - Identifies infinite update loops
- **Automatic cooldown** - Enforces waiting period when loops detected

#### Agent Hierarchy & Spawning
- **Parent/child tracking** - New AgentMetadata fields:
  - `parent_agent_id: str` - Which agent spawned this one
  - `spawn_reason: str` - Why agent was spawned (e.g., "new_domain")
  - `api_key: str` - Unique authentication key per agent
- **Multi-agent support** - Track lineage and dependencies
- **Security** - API keys prevent unauthorized agent impersonation

#### Modular Handler Architecture
- **Handler registry pattern** - Organized 29 handlers into `src/mcp_handlers/`
- **Category organization**:
  - `core.py` - Core governance operations
  - `config.py` - Configuration management
  - `observability.py` - Monitoring and metrics
  - `lifecycle.py` - Agent lifecycle management
  - `export.py` - Data export functionality
  - `knowledge.py` - Knowledge layer operations
  - `admin.py` - Administrative tools
  - `dialectic.py` - Dialectic protocol
  - `utils.py` - Common utilities
- **Standardized error handling** - `require_agent_id()`, `success_response()`, `error_response()`

#### New Tools & Scripts
- `/Users/cirwel/scripts/fix_cursor_freeze.sh` - One-command recovery tool for Cursor/IDE freezes
- `/Users/cirwel/scripts/test_enhanced_locking.py` - Comprehensive lock system test suite (4 tests)
- `/Users/cirwel/scripts/test_mcp_json_rpc.py` - MCP protocol verification tool
- `/Users/cirwel/scripts/diagnose_cursor_mcp.sh` - Complete system diagnostic script

### Changed

#### Increased Capacity
- **MAX_KEEP_PROCESSES** - Increased from 36 to 72 (doubled)
- **Better concurrency** - Support for Cursor + Claude Desktop + other MCP clients simultaneously

#### Enhanced Reliability
- **Lock acquisition** - Now includes automatic stale lock cleanup before retry
- **Error messages** - More detailed, actionable error messages with recovery suggestions
- **Async support** - Added optional `aiofiles` support with graceful fallback

### Fixed

#### Critical Fixes
- **Cursor freeze issue** - Auto-healing locks prevent lock contention from duplicate servers
- **Dialectic protocol bug** - Fixed `'str' object is not a mapping` error (AgentMetadata → dict conversion)
- **JSON-RPC protocol** - All debug output redirected to stderr (was breaking Claude Desktop)
- **Lock cleanup** - Automatic cleanup on MCP server startup (5-minute staleness threshold)

#### Previous Session Fixes (Pre-v2.1)
- **Process cleanup** - Zombie process detection and cleanup on startup
- **Agent archival** - Auto-archive test agents after 7 days
- **Metadata locking** - Enhanced file-based locking during reads/writes

### Documentation

#### Updated
- **README.md** - Added v2.1 feature section
- **QUICK_REFERENCE.md** - Added troubleshooting section for Cursor freezes and new tools
- **CHANGELOG.md** - Created comprehensive changelog (this file)

#### Created
- `/Users/cirwel/scripts/cursor_implementations_summary.md` - Complete v2.1 feature documentation
- `/Users/cirwel/scripts/session_final_status.md` - Session summary and status

#### Consolidated
- Archived 5 redundant session documentation files to `/Users/cirwel/scripts/Archive/session_docs_20251125/`
- Kept 2 comprehensive docs: `cursor_implementations_summary.md` and `session_final_status.md`

### Testing

#### Test Results
- **Enhanced Locking Tests**: 4/4 passed ✅
  - Process health check ✅
  - Lock acquisition ✅
  - Stale lock cleanup ✅
  - Retry logic ✅
- **MCP JSON-RPC Tests**: 2/2 passed ✅
  - Governance MCP ✅
  - Date Context MCP ✅
- **System Health**: All checks pass ✅

### Git Statistics
- **Commit**: 921bde6
- **Files changed**: 157
- **Insertions**: +32,856 lines
- **Deletions**: -2,969 lines
- **Net change**: +29,887 lines

---

## [2.0.0] - 2025-11-24

### Added - Complete System Implementation

#### Elegant Handler Architecture
- Refactored MCP server from 1,700+ line elif chain to clean handler registry (~30 lines)
- 29 handlers organized by category
- Zero elif branches - maintainable and testable

#### All 5 Decision Points Implemented
1. **λ₁ → Sampling Parameters** - Linear transfer function
2. **Risk Estimator** - Multi-factor risk scoring
3. **Void Detection Threshold** - Adaptive threshold (mean + 2σ)
4. **PI Controller** - Concrete gains (K_p=0.5, K_i=0.05)
5. **Decision Logic** - Risk-based approve/revise/reject

#### UNITARES Framework
- Complete thermodynamic governance implementation
- E (Engagement), I (Integrity), S (Safety), V (Void) metrics
- Coherence tracking and health monitoring
- State persistence and history

#### CLI Tools
- `agent_self_log.py` - CLI logging with full state persistence
- `register_agent.py` - Simple agent registration
- `claude_code_bridge.py` - Bridge for Claude Code integration

### Changed
- Project structure reorganized for clarity
- Documentation consolidated and updated
- Tests expanded and verified

### Documentation
- Complete README with architecture overview
- ONBOARDING.md for new users
- Multiple guides in docs/ directory
- README_FOR_FUTURE_CLAUDES.md

---

## [1.0.0] - 2025-11-20

### Initial Release
- Core UNITARES framework
- Basic MCP server implementation
- Agent metadata tracking
- File-based state persistence
- Simple decision logic

---

## Upgrade Guide

### From v2.0 to v2.1

**No breaking changes.** Simply pull the latest code:

```bash
git pull
```

**New features automatically enabled:**
- Auto-healing locks (no configuration needed)
- Loop detection (automatically tracks agents)
- Enhanced capacity (MAX_KEEP_PROCESSES already increased)

**Optional - Install new tools:**
```bash
chmod +x /Users/cirwel/scripts/fix_cursor_freeze.sh
chmod +x /Users/cirwel/scripts/diagnose_cursor_mcp.sh
```

**If experiencing Cursor freezes:**
```bash
/Users/cirwel/scripts/fix_cursor_freeze.sh
```

**To test new locking system:**
```bash
python3 /Users/cirwel/scripts/test_enhanced_locking.py
```

---

## Known Issues

### v2.1
- Lock cleanup import warning on startup (non-blocking, fallback works)
- Sampling parameters returning 0.000 (calculation needs review)
- State persistence occasionally shows zeros (under investigation)

### Workarounds
All known issues have fallback behavior and don't block functionality.

---

## Future Roadmap

### Planned for v2.2
- Fix sampling parameter calculation
- Investigate state persistence edge cases
- Add cron job for periodic health monitoring
- Implement server process singleton pattern
- Add alerting for duplicate server detection

### Under Consideration
- Web-based dashboard for fleet monitoring
- Real-time coherence visualization
- Agent spawning UI
- Performance profiling and optimization

---

**Maintained by:** UNITARES Development Team
**License:** See LICENSE file
**Repository:** governance-mcp-v1
