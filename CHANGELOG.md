# Changelog

All notable changes to the UNITARES Governance Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.5.5] - 2026-02-04

### Added - Trajectory Identity & Test Coverage

#### Trajectory Identity Framework
- **Genesis signature (Σ₀)** stored at first onboard, immutable thereafter
- **Lineage comparison** on each update - similarity to genesis tracked
- **Anomaly detection** when similarity drops below 0.6
- New functions: `store_genesis_signature()`, `update_current_signature()`, `verify_trajectory_identity()`, `get_trajectory_status()`

#### Model-Based agent_id Fix
- `agent_id` now properly uses model type when provided
- Format: `{Model}_{Version}_{Date}` (e.g., `Claude_Opus_4_5_20260204`)
- Fixed bug where `handle_onboard_v2` was ignoring properly generated `agent_id`

#### Test Coverage Expansion
- **93+ tests passing** (up from 25)
- `governance_monitor.py`: 79% coverage (63 tests)
- `trajectory_identity.py`: 88% coverage (19 tests)
- `identity_v2.py`: 11% coverage (11 tests)

#### New Test Classes
- `TestGainModulation` - HCK v3.0 PI gain modulation
- `TestEthicalDrift` - ‖Δη‖² computation
- `TestStatePersistence` - Save/load state
- `TestVoidFrequency` - Void frequency calculation
- `TestLambda1Update` - PI controller bounds
- `TestSimulateUpdate` - Dry-run without mutation
- `TestTrajectorySignature` - Dataclass serialization
- `TestGenesisStorage` - Immutable genesis
- `TestLineageComparison` - Similarity detection
- `TestVerifyIdentity` - Two-tier verification

### Changed
- Documentation updated to reflect actual system state
- "Ethical drift" section now correctly describes implemented functionality
- Roadmap updated with completed items

### Files Changed
- `src/mcp_handlers/identity_v2.py` - Fixed agent_id bug at lines 1446-1460
- `src/anima_mcp/unitares_bridge.py` - Wired trajectory signature to UNITARES
- `tests/test_governance_monitor_core.py` - 63 new tests
- `tests/test_trajectory_integration.py` - 19 new tests
- `tests/test_identity_agent_id.py` - 11 new tests
- `README.md` - Updated to reflect current state

---

## [2.5.4] - 2025-12-27

### Changed - Meaningful Identity in Knowledge Graph

#### Agent-Centric Identity (v2.5.4)
Agents find meaningful names more useful than UUID strings. This update shifts KG attribution from technical UUIDs to human-and-agent-readable identifiers.

#### Identity in Knowledge Graph
- **Before:** KG stored UUID (e.g., `a1b2c3d4-...`) - meaningless to agents and humans
- **After:** KG stores `agent_id` (e.g., `Claude_Opus_4_20251227`) - meaningful to both

#### Implementation
- `require_registered_agent()` now returns `agent_id` (model+date) for KG storage
- UUID kept internal via `_agent_uuid` for session binding only
- `_resolve_agent_display()` helper resolves agent_id to display info without exposing UUID
- Display names included in KG query responses for human readability

#### Four-Tier Identity Model (Refined)
1. **UUID** - Immutable technical identifier (internal only, never in KG)
2. **agent_id** - Model+date format (e.g., `Claude_Opus_4_20251227`) - stored in KG
3. **display_name** - User-chosen name ("birth certificate")
4. **label** - Nickname (can change)

### Files Changed
- `src/mcp_handlers/utils.py` - `require_registered_agent()` returns agent_id instead of UUID
- `src/mcp_handlers/knowledge_graph.py` - Added `_resolve_agent_display()` helper

---

## [2.5.1] - 2025-12-26

### Added - Three-Tier Identity Model

#### Identity Architecture
- **UUID** (immutable) - Technical identifier, never changes
- **agent_id** (structured) - Auto-generated on creation, stable (format: `{interface}_{date}`)
- **display_name** (nickname) - User-chosen via `identity(name=...)`, can change

#### New Fields
- `structured_id` field in `AgentMetadata` class
- `generate_structured_id()` function in `naming_helpers.py`

#### Response Updates
- `onboard()` and `identity()` now return all three tiers
- `compute_agent_signature()` includes `agent_id` in response
- Legacy fields (`agent_uuid`, `label`) preserved for compatibility

#### Migration Support
- Pre-v2.5.0 agents get `structured_id` generated on first `identity(name=...)` call

### Fixed - Honest Initialization for New Agents

#### Problem
New agents showed `coherence=1.0, risk=0.0` before their first check-in, then values "dropped" to ~0.55 after first `process_agent_update()`. This felt jarring - like something broke.

#### Solution
- Return `null` for computed metrics (`coherence`, `risk_score`) until first governance cycle
- Show `status: "uninitialized"` with clear messaging
- Display `⚪ pending (first check-in required)` instead of fake values

#### Before/After
**Before (misleading):**
```
coherence: 1.0  ← fake placeholder
risk: 0.0       ← fake placeholder
```

**After (honest):**
```
status: ⚪ uninitialized
coherence: null (pending)
risk: null (pending)
next_action: 📝 Call process_agent_update() to start governance tracking
```

### Files Changed
- `src/mcp_server_std.py` - Added `structured_id` field to AgentMetadata
- `src/mcp_handlers/naming_helpers.py` - Added `generate_structured_id()` function
- `src/mcp_handlers/identity.py` - Three-tier model in responses
- `src/mcp_handlers/identity_v2.py` - Three-tier model + migration
- `src/mcp_handlers/utils.py` - Updated `compute_agent_signature()`
- `src/governance_monitor.py` - Return `null` for metrics when `update_count == 0`
- `src/mcp_handlers/core.py` - Show "uninitialized" status with helpful messaging

---

## [2.5.0] - 2025-12-26

### Added - HCK/CIRS Stability Monitoring

#### HCK v3.0 - Reflexive Control
- **Update coherence ρ(t)** - Measures directional alignment between E and I updates
  - ρ ≈ 1: Coherent updates (E and I moving together)
  - ρ ≈ 0: Misaligned or unstable
  - ρ < 0: Adversarial movement (E and I diverging)
- **Continuity Energy (CE)** - Tracks state change rate ("work required to maintain consistency")
- **PI Gain Modulation** - When ρ is low, controller gains are reduced to prevent instability

#### CIRS v0.1 - Oscillation Detection & Resonance Damping
- **New `src/cirs.py`** - Complete CIRS implementation
- **OscillationDetector** - Tracks threshold crossings via EMA of sign transitions
  - Oscillation Index (OI) = EMA(sign(Δcoherence)) + EMA(sign(Δrisk))
  - Flip counting for decision/route changes
- **ResonanceDamper** - Adjusts thresholds when resonance detected
- **Response tiers:**
  - `proceed` - Normal operation
  - `soft_dampen` - Resonance detected but not critical
  - `hard_block` - Critical safety pause

#### New State Fields
- `rho_history`, `CE_history`, `current_rho` - HCK tracking
- `oi_history`, `resonance_events`, `damping_applied_count` - CIRS tracking

### Fixed

#### Session Identity Bug
- **Issue:** `onboard` created agent X, but `process_agent_update(client_session_id=...)` used different agent Y
- **Root cause:** `onboard`/`identity` only registered binding in memory, not Redis; `identity_v2` couldn't find it
- **Fix:** Added Redis caching in `identity.py` after stable session binding registration
- **Location:** `mcp_handlers/identity.py:1355-1365` and `mcp_handlers/identity.py:1559-1566`

### Changed

#### Governance Output
- `process_agent_update` now includes `hck` and `cirs` sections in response
- `get_metrics` includes HCK/CIRS metrics
- New response tier field indicates `proceed`/`soft_dampen`/`hard_block`

### Documentation
- Updated `.agent-guides/DEVELOPER_AGENTS.md` with HCK/CIRS architecture
- Updated `.agent-guides/FUTURE_CLAUDE_CODE_AGENTS.md` with v2.5.0 reference
- Updated `.agent-guides/SSE_SERVER_INFO.md` with correct script reference

---

## [2.4.0] - 2025-12-25

### Added - Simplified Identity System (identity_v2)

#### 3-Path Architecture
- **New `identity_v2.py`** - Replaces complex 15+ code path identity system
- **Three resolution paths only:**
  1. Redis cache (fast path, < 1ms)
  2. PostgreSQL session lookup
  3. Create new agent
- **Cleaner separation of concerns:**
  - `resolve_session_identity()` → "Who am I?" (session → UUID)
  - `get_agent_metadata()` → "Who is agent X?" (lookup by UUID/label)

#### Database Enhancements
- **Added `label` column** to `core.agents` table
- **New PostgresBackend methods:**
  - `get_agent()` - Full agent record retrieval
  - `get_agent_label()` - Fast label lookup
  - `find_agent_by_label()` - Label collision detection
  - Extended `update_agent_fields()` with `label` parameter

### Changed

#### Identity Tool
- **`identity()` tool** now uses simplified v2 handler
- **Label is just metadata** - Not an identity mechanism (reduces confusion)
- **Consistent UUID** - Same session always returns same UUID (fixes Bug #3)

#### UX Improvements
- **Auto-semantic search** - Multi-word queries auto-use semantic search when available
- **Pagination for discoveries** - `get_discovery_details` now supports `offset`/`length`
- **Search hints** - Helpful suggestions when substring search returns no results

### Fixed
- **Bug #2:** `get_agent_metadata` UnboundLocalError (`attention_score` → `risk_score`)
- **Bug #3:** Identity binding inconsistencies causing UUID confusion

### Deprecated
- **Old identity.py handler** - `@mcp_tool` decorator commented out, kept for reference
- **`hello()`/`status()` pattern** - Use `identity()` instead (aliases still work)

---

## [2.3.0] - 2025-12-01

### Added - Complete Decorator Migration 🎯

#### 100% Migration to Decorator Pattern
- **All 43 tools migrated** to `@mcp_tool` decorator pattern
- **Automatic timeout protection** on all tools
- **Self-documenting code** - timeout values attached to functions
- **Enhanced `list_tools`** - Now includes timeout and category metadata

#### Final Migrations
- `process_agent_update` (60s timeout) - Most complex handler
- `simulate_update` (30s timeout)
- `health_check` (10s timeout)
- `get_workspace_health` (30s timeout)
- `delete_agent` (15s timeout)

### Changed

#### Timeout Protection
- **Removed double timeout wrapping** - `dispatch_tool()` no longer wraps with 30s timeout
- **Decorator timeouts now effective** - Each tool uses its configured timeout
- **Critical improvement:** `process_agent_update` now uses 60s timeout (was 30s)

#### UX Improvements
- **Reframed pause messages** - More supportive and collaborative language
  - "High complexity detected" → "Complexity is building - let's pause and regroup"
  - "safety pause required" → "safety pause suggested"
  - Added: "This is a helpful pause, not a judgment"

#### Tool Metadata
- **Enhanced `list_tools` output** - Now includes timeout values and categories
- **Better tool discovery** - Agents can see timeout requirements when discovering tools

### Technical Improvements
- **Consistent pattern** - Single decorator pattern across all 43 tools
- **Less boilerplate** - Auto-registration reduces manual dict entries
- **Better error handling** - Standardized timeout error responses

---

## [2.2.0] - 2025-11-28

### Added - Knowledge Graph System 🚀

#### Fast, Indexed Knowledge Storage
- **Knowledge Graph Engine** (`src/knowledge_graph.py`) - Complete in-memory graph implementation
  - O(1) inserts with automatic index updates
  - O(indexes) queries (not O(n)) - scales logarithmically
  - Tag-based similarity search (no brute force scanning)
  - Async background persistence (non-blocking)
  - Claude Desktop compatible (no blocking I/O)

#### New MCP Tools (6 tools)
- `store_knowledge_graph` - Store discoveries (35,000x faster than file-based)
- `search_knowledge_graph` - Search by tags, type, agent, severity (indexed queries)
- `get_knowledge_graph` - Get agent's knowledge (fast index lookup)
- `list_knowledge_graph` - Get graph statistics (full transparency)
- `update_discovery_status_graph` - Update discovery status (open/resolved/archived)
- `find_similar_discoveries_graph` - Find similar by tag overlap (3,500x faster)

#### Migration Tool
- `scripts/migrate_to_knowledge_graph.py` - One-time migration from file-based to graph
- Preserves all relationships and metadata
- Converts existing 252 discoveries automatically

### Changed

#### Performance Improvements
- **Knowledge operations**: 35,000x faster (`store_knowledge`: 350ms → 0.01ms)
- **Similarity search**: 3,500x faster (`find_similar`: 350ms → 0.1ms)
- **Query performance**: O(indexes) instead of O(n) file scans
- **Claude Desktop compatibility**: All operations non-blocking

#### File Organization
- **Root directory cleanup** - Moved 7 markdown files to organized locations:
  - `ARCHITECTURE.md` → `docs/architecture/`
  - `ONBOARDING.md` → `docs/guides/`
  - `USAGE_GUIDE.md` → `docs/guides/`
  - `SYSTEM_SUMMARY.md` → `docs/reference/`
  - `METRICS_REPORTING.md` → `docs/guides/`
  - `ARCHIVAL_SUMMARY_20251128.md` → `docs/archive/`
  - `HARD_REMOVAL_SUMMARY_20251128.md` → `docs/archive/`
- **Root directory**: Now contains only `README.md`, `CHANGELOG.md`, and `requirements-mcp.txt`

### Fixed

#### Knowledge Layer Issues
- **Claude Desktop freezing** - Fixed blocking I/O with async graph operations
- **Context compression** - Indexed queries prevent large response issues
- **Performance bottlenecks** - Graph-based approach eliminates O(n×m) scans

### Documentation

#### Created
- `docs/proposals/KNOWLEDGE_GRAPH_DESIGN.md` - Complete design proposal
- `docs/guides/KNOWLEDGE_GRAPH_USAGE.md` - Usage guide with examples
- `docs/guides/KNOWLEDGE_GRAPH_INTEGRATION_COMPLETE.md` - Integration summary
- `docs/analysis/KNOWLEDGE_GRAPH_IMPLEMENTATION_SUMMARY.md` - Implementation details
- `docs/analysis/KNOWLEDGE_GRAPH_USAGE_VERIFICATION.md` - Verification results
- `docs/proposals/KNOWLEDGE_GRAPH_TRANSPARENCY.md` - Transparency design
- `docs/analysis/KNOWLEDGE_GRAPH_FINAL_APPROACH.md` - Final approach documentation
- `docs/analysis/MODEL_CLIENT_STRATEGY.md` - Model/client strategy analysis
- `docs/ROOT_FILE_ORGANIZATION.md` - Root file organization guide

#### Updated
- `docs/DOC_MAP.md` - Updated paths for moved files
- `docs/README.md` - Updated root file references
- `docs/DOCUMENTATION_GUIDELINES.md` - Updated onboarding path
- `src/tool_usage_tracker.py` - Updated archive summary path
- `scripts/check_small_markdowns.py` - Updated file list
- `scripts/validate_project_docs.py` - Updated validation paths

### Technical Details

#### Architecture
- **Graph structure**: Nodes (discoveries) with 5 indexes (agent, tag, type, tag, type, severity, status)
- **Persistence**: Single JSON file (`data/knowledge_graph.json`) with async background saves
- **Debouncing**: 100ms delay for rapid writes (efficient batching)
- **Error handling**: Graceful degradation (starts empty if load fails)

#### Integration
- **Handler registry**: All 6 tools registered in `src/mcp_handlers/__init__.py`
- **MCP server**: All tools defined with complete schemas in `src/mcp_server_std.py`
- **Tool list**: Included in `list_tools()` for runtime introspection

### Performance Metrics

- **Store operation**: ~0.01ms (vs 350ms file-based) - **35,000x faster**
- **Similarity search**: ~0.1ms (vs 350ms file-based) - **3,500x faster**
- **Query performance**: O(indexes) not O(n) - **scales logarithmically**
- **Memory usage**: ~1MB for 252 discoveries, scales to 10,000+ efficiently

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
- **MAX_KEEP_PROCESSES** - Increased from 36 to 42
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

### From v2.1 to v2.2

**New features automatically available:**
- Knowledge graph tools ready to use
- Migration tool available for existing data
- All operations non-blocking (Claude Desktop compatible)

**Optional - Migrate existing knowledge:**
```bash
python3 scripts/migrate_to_knowledge_graph.py
```

**New tools available:**
- `store_knowledge_graph` - Fast discovery storage
- `search_knowledge_graph` - Indexed knowledge queries
- `get_knowledge_graph` - Get agent knowledge
- `list_knowledge_graph` - Graph statistics
- `update_discovery_status_graph` - Update discovery status
- `find_similar_discoveries_graph` - Find similar discoveries

**No breaking changes.** Old file-based knowledge layer archived but preserved.

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

### v2.5.5
- None known - all systems operational ✅

### Workarounds
All known issues have fallback behavior and don't block functionality.

---

## Future Roadmap

### In Progress
- Outcome correlation — does high instability actually predict bad outcomes?
- Threshold tuning — domain-specific drift thresholds need real-world calibration

### Under Consideration
- Semantic ethical drift detection (beyond parameter changes)
- Multi-agent coordination protocols
- Web-based dashboard for fleet monitoring
- Production hardening

---

**Maintained by:** UNITARES Development Team
**License:** See LICENSE file
**Repository:** governance-mcp-v1
