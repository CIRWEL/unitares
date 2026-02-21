# MCP System Evolution: v1.0.0 → v2.7.0+

**Complete history of how the UNITARES Governance MCP system has evolved**

---

## Overview

The MCP system has evolved from a simple governance monitor to a comprehensive multi-agent coordination platform with knowledge graphs, stability monitoring, and sophisticated identity management.

**Timeline:**
- **v1.0.0** (Nov 2025) - Initial release with basic governance
- **v2.0.0** (Nov 2025) - Complete refactor with handler architecture
- **v2.1.0** (Nov 2025) - Auto-healing infrastructure
- **v2.2.0** (Nov 2025) - Knowledge graph system
- **v2.3.0** (Dec 2025) - Decorator migration
- **v2.4.0** (Dec 2025) - Simplified identity system
- **v2.5.0** (Dec 2025) - HCK/CIRS stability monitoring
- **v2.5.1** (Dec 2025) - Three-tier identity model
- **v2.5.4** (Dec 2025) - Meaningful identity in knowledge graph
- **v2.5.5** (Feb 2026) - Ethical drift, trajectory identity, 85+ tools
- **v2.5.6** (Feb 2026) - UX friction fixes, consolidated tools, 38+ tool aliases
- **v2.5.7** (Feb 2026) - Three-tier identity (merged label→display_name), identity_shared.py module, 416 tests
- **v2.5.8** (Feb 2026) - Production Redis resilience (circuit breaker, pooling, retry)
- **v2.5.9** (Feb 2026) - Agent circuit breaker enforcement (paused agents actually blocked)
- **v2.6.0** (Feb 2026) - Major cleanup: ~4,200 lines dead code removed, tool surface 49→29, PostgreSQL dialectic, 1,798 tests at 40% coverage
- **v2.6.1** (Feb 2026) - Name-based identity (PATH 2.5), observe tool fix, dashboard overhaul, trust tiers
- **v2.6.2** (Feb 2026) - Architecture refactoring: ToolDefinition dataclass, action_router, dispatch middleware, response formatter. 31 tools, 2,194 tests at 43% coverage
- **v2.6.3** (Feb 2026) - Dialectic audit: sqlite→pg aliases, LLM reviewer, dialectic consolidation (30 tools), EISV sensor sync, dead code removal. 2,602 tests at 49% coverage
- **v2.6.4** (Feb 2026) - KG bias fixes (temporal decay, status scoring, SUPERSEDES edge), CI test fixes. 6,344 tests at 80% coverage
- **v2.7.0** (Feb 2026) - CIRS v2 resonance wiring (AdaptiveGovernor PID, auto-emit hooks, neighbor pressure), I-dynamics linear mode (v5 paper), dialectic fixes. 6,407 tests at 80% coverage

---

## v1.0.0 → v2.0.0: Foundation to Architecture

### What Changed

**Before (v1.0.0):**
- Single-file MCP server with basic governance
- Simple file-based state persistence
- Basic decision logic (approve/revise/reject)
- No agent lifecycle management
- ~500 lines of code

**After (v2.0.0):**
- **Handler registry pattern** - Refactored from 1,700+ line elif chain to clean handler registry (~30 lines)
- **29 organized handlers** - Categorized by function (core, config, observability, lifecycle, etc.)
- **All 5 decision points implemented** - Complete UNITARES framework
- **Modular architecture** - Separated concerns, testable components

### Key Improvements

1. **Code Organization**
   ```
   Before: src/mcp_server.py (1,700+ lines, monolithic)
   After:  src/mcp_handlers/
            ├── core.py
            ├── config.py
            ├── observability.py
            ├── lifecycle.py
            └── ...
   ```

2. **Decision Points**
   - λ₁ → Sampling Parameters (linear transfer function)
   - Risk Estimator (multi-factor scoring)
   - Void Detection Threshold (adaptive: mean + 2σ)
   - PI Controller (K_p=0.5, K_i=0.05)
   - Decision Logic (risk-based)

3. **Tool Count**
   - v1.0.0: 4 tools
   - v2.0.0: 29 tools

---

## v2.0.0 → v2.1.0: Reliability & Auto-Healing

### What Changed

**Added Auto-Healing Infrastructure:**

1. **Enhanced State Locking**
   - Automatic stale lock detection
   - Smart lock cleanup (removes locks from crashed processes)
   - Exponential backoff retry (3 attempts)
   - Process health checking

2. **Loop Detection & Prevention**
   - Activity tracking (update timestamps, decision patterns)
   - Pattern detection (infinite update loops)
   - Automatic cooldown periods

3. **Agent Hierarchy & Spawning**
   - Parent/child tracking
   - Multi-agent support
   - API key authentication

### Impact

- **Cursor freeze issue fixed** - Auto-healing locks prevent contention
- **Increased capacity** - MAX_KEEP_PROCESSES: 36 → 42
- **Better reliability** - Self-recovering from crashes

---

## v2.1.0 → v2.2.0: Knowledge Graph Revolution

### What Changed

**Knowledge Graph System:**

1. **Performance Improvements**
   - **35,000x faster** - Store: 350ms → 0.01ms
   - **3,500x faster** - Similarity search: 350ms → 0.1ms
   - **O(indexes) queries** - Logarithmic scaling instead of O(n)

2. **New Tools (6 tools)**
   - `store_knowledge_graph` - Fast discovery storage
   - `search_knowledge_graph` - Indexed queries
   - `get_knowledge_graph` - Agent knowledge lookup
   - `list_knowledge_graph` - Graph statistics
   - `update_discovery_status_graph` - Status updates
   - `find_similar_discoveries_graph` - Tag-based similarity

3. **Architecture**
   - In-memory graph with 5 indexes
   - Async background persistence
   - Claude Desktop compatible (non-blocking)

### Impact

- **Claude Desktop freezing fixed** - Non-blocking operations
- **Context compression** - Indexed queries prevent large responses
- **Scalability** - Handles 10,000+ discoveries efficiently

---

## v2.2.0 → v2.3.0: Decorator Migration

### What Changed

**100% Migration to Decorator Pattern:**

- **All 43 tools migrated** to `@mcp_tool` decorator
- **Automatic timeout protection** on all tools
- **Self-documenting code** - Timeout values attached to functions
- **Enhanced `list_tools`** - Includes timeout and category metadata

### Key Improvements

1. **Timeout Protection**
   - Removed double timeout wrapping
   - Each tool uses configured timeout
   - `process_agent_update`: 30s → 60s timeout

2. **Tool Metadata**
   - Timeout values visible in `list_tools`
   - Categories for better organization
   - Better tool discovery

---

## v2.3.0 → v2.4.0: Identity Simplification

### What Changed

**Simplified Identity System:**

1. **3-Path Architecture**
   - Redis cache (fast path, < 1ms)
   - PostgreSQL session lookup
   - Create new agent

2. **Database Enhancements**
   - Added `label` column to `core.agents` table
   - New PostgresBackend methods
   - Label collision detection

3. **UX Improvements**
   - Auto-semantic search
   - Pagination for discoveries
   - Search hints

### Impact

- **Bug #3 fixed** - Identity binding inconsistencies resolved
- **Cleaner code** - Reduced from 15+ code paths to 3
- **Better UX** - More intuitive identity management

---

## v2.4.0 → v2.5.0: Stability Monitoring

### What Changed

**HCK/CIRS Stability Monitoring:**

1. **HCK v3.0 - Reflexive Control**
   - Update coherence ρ(t) - Measures E/I alignment
   - Continuity Energy (CE) - State change rate tracking
   - PI Gain Modulation - Prevents instability

2. **CIRS v0.1 - Oscillation Detection**
   - OscillationDetector - Tracks threshold crossings
   - ResonanceDamper - Adjusts thresholds
   - Response tiers: `proceed` / `soft_dampen` / `hard_block`

3. **New State Fields**
   - `rho_history`, `CE_history`, `current_rho`
   - `oi_history`, `resonance_events`, `damping_applied_count`

### Impact

- **Better stability** - Detects and prevents oscillations
- **Smarter control** - Adaptive thresholds based on resonance
- **Safety tiers** - Graduated response system

---

## v2.5.0 → v2.5.1: Identity Refinement

### What Changed

**Three-Tier Identity Model:**

1. **Identity Architecture**
   - **UUID** (immutable) - Technical identifier
   - **agent_id** (structured) - Auto-generated, stable
   - **display_name** (nickname) - User-chosen, can change

2. **Honest Initialization**
   - **Before:** Fake `coherence=1.0, risk=0.0` for new agents
   - **After:** `null` values until first check-in
   - **Status:** `⚪ uninitialized` with clear messaging

### Impact

- **No more confusion** - Honest metrics from the start
- **Better UX** - Clear "pending" state for new agents
- **Migration support** - Pre-v2.5.0 agents get structured_id

---

## v2.5.1 → v2.5.4: Meaningful Identity

### What Changed

**Agent-Centric Identity in Knowledge Graph:**

1. **Identity in KG**
   - **Before:** UUID (e.g., `a1b2c3d4-...`) - meaningless
   - **After:** `agent_id` (e.g., `Claude_Opus_4_20251227`) - meaningful

2. **Four-Tier Identity Model**
   - **UUID** - Internal only, never in KG
   - **agent_id** - Model+date format, stored in KG
   - **display_name** - User-chosen name
   - **label** - Nickname (can change)

### Impact

- **Better readability** - KG queries return meaningful names
- **Human-friendly** - Both agents and humans can understand IDs
- **Cleaner separation** - Technical vs. semantic identity

---

## v2.5.4 → v2.5.5: Ethical Drift & Trajectory Identity

### What Changed

**Ethical Drift (Δη) Fully Integrated:**

1. **Drift Computation**
   - Parameter-based: ‖Δη‖² = ‖θ_t - θ_{t-1}‖² / dim
   - 4 components: calibration deviation, complexity divergence, coherence deviation, stability deviation
   - Fed into φ objective with weight `wEta`

2. **Self-Governance Principle**
   - Ground truth from objective outcomes (test results, command success)
   - No human oracle required for calibration
   - `auto_ground_truth.py` collects calibration signals automatically

**Trajectory Identity:**

1. **Genesis Signature (Σ₀)**
   - Stored at first onboard, never overwritten
   - Lineage comparison detects anomalies
   - Alerts when similarity < 0.6

2. **New Tools**
   - `verify_trajectory_identity()` - Two-tier check (genesis + current)
   - `get_trajectory_status()` - View lineage health

**Tool Expansion:**

- Tool count expanded from 43 to **85+ tools**
- New categories: Pi Orchestration, Trajectory, CIRS, Recovery
- Unified tools: `self_recovery`, `cirs_protocol`, `agent`, `knowledge`, `calibration`

### Impact

- **Complete ethical drift** - Measured from observable signals, not placeholders
- **Identity verification** - Detect potential identity drift or anomalies
- **Richer toolset** - Comprehensive multi-agent coordination

---

## v2.5.5 → v2.5.6: Operational Resilience

### What Changed

**SSH-Based Pi Restart:**

1. **New Tool**
   - `pi_restart_service` - Restart anima service via SSH when MCP is down
   - Uses Tailscale IP for reliable connectivity
   - Whitelisted services: anima, anima-broker, ngrok
   - Whitelisted actions: restart, start, stop, status

2. **Problem Solved**
   - **Before:** When `git_pull` with restart killed MCP, no way to recover remotely
   - **After:** SSH-based fallback works even when MCP service is down

**Test Expansion:**

- Test count: 93+ → **310+ tests**
- Coverage: 79-88% → **83-88%**
- Comprehensive coverage across governance, identity, trajectory, and coordination modules

**Sensor Schema Cleanup:**

- Removed deprecated `sound_level` field from anima-mcp sensors
- Cleaner sensor schema: 5 core environmental sensors instead of 6

### Impact

- **Better recovery** - Remote restart possible even when MCP is down
- **Higher confidence** - 3x more tests validate system behavior
- **Cleaner architecture** - Removed unused sensor field

---

## v2.5.6 → v2.5.7: Identity Persistence Fix

### What Changed

**Identity Persistence Bug Fix:**

1. **Root Cause**
   - `onboard()` called `resolve_session_identity(persist=False)` first
   - If Redis cache write failed silently (logged at DEBUG), identity was lost
   - Second call to `resolve_session_identity(persist=True)` created a different UUID
   - Result: each tool call got a new identity for HTTP clients

2. **Fix**
   - Track fresh identity from first call (`created_fresh_identity` flag)
   - Persist that exact UUID directly via `ensure_agent_persisted()`
   - Don't call `resolve_session_identity` twice

**Logging Improvements:**

- Redis cache write failures: DEBUG → **WARNING**
- Redis lookup failures: DEBUG → **INFO**
- Makes cache failures visible instead of silent

### Impact

- **Stable identity** - HTTP clients (claude.ai, etc.) maintain same UUID across calls
- **Better observability** - Redis failures now visible in logs
- **Simpler flow** - Single identity creation, no race condition

---

## Architecture Evolution Summary

### Code Organization

```
v1.0.0:  Single file (mcp_server.py)
v2.0.0:  Handler registry (mcp_handlers/)
v2.1.0:  Modular handlers + auto-healing
v2.2.0:  Knowledge graph layer
v2.3.0:  Decorator pattern (all tools)
v2.4.0:  Simplified identity system
v2.5.0:  Stability monitoring (HCK/CIRS)
v2.5.4:  Meaningful identity in KG
v2.5.6:  SSH-based Pi restart, 310+ tests
v2.5.7:  Identity persistence fix
v2.6.0:  Major cleanup, 49→29 tools, 1,798 tests
v2.6.1:  Name-based identity (PATH 2.5), dashboard overhaul
v2.6.2:  Architecture refactoring, 31 tools, 2,194 tests
v2.6.3:  Dialectic audit, EISV sensor sync, 30 tools, 6,306 tests at 80% coverage
v2.6.4:  KG bias fixes, CI test fixes, 6,344 tests at 80% coverage
v2.7.0:  CIRS v2 resonance wiring, I-dynamics linear, 6,407 tests at 80% coverage
```

### Tool Count Evolution

- **v1.0.0:** 4 tools
- **v2.0.0:** 29 tools
- **v2.1.0:** 29 tools (same, but better organized)
- **v2.2.0:** 35 tools (+6 knowledge graph tools)
- **v2.3.0:** 43 tools (+8 more tools)
- **v2.4.0:** 43 tools (refinements)
- **v2.5.5:** 85+ tools (+42 tools: Pi orchestration, trajectory, recovery, unified tools)
- **v2.6.0:** 29 tools (85+ consolidated to 29 public, admin/internal hidden)
- **v2.6.2:** 31 tools (+ 2 new registered tools, 49 consolidated sub-handlers)
- **v2.6.3:** 30 tools (dialectic consolidated, identity audit, dead code removal, 6,306 tests)
- **v2.6.4:** 30 tools (KG bias fixes: temporal decay, status scoring, SUPERSEDES edge, 6,344 tests)
- **v2.7.0:** 30 tools (CIRS v2 resonance wiring, I-dynamics linear mode, 6,407 tests)

### Performance Improvements

- **Knowledge operations:** 35,000x faster
- **Similarity search:** 3,500x faster
- **Query performance:** O(indexes) instead of O(n)
- **Identity lookup:** < 1ms with Redis cache

### Reliability Improvements

- **Auto-healing locks** - No manual intervention
- **Loop detection** - Prevents infinite loops
- **Process cleanup** - Automatic zombie detection
- **Stale lock cleanup** - Self-recovering

---

## Key Design Principles That Emerged

1. **Modularity** - Handler registry pattern
2. **Performance** - Indexed queries, caching
3. **Reliability** - Auto-healing, self-recovery
4. **UX** - Honest initialization, meaningful IDs
5. **Scalability** - O(indexes) algorithms, efficient data structures

---

## Current State (v2.7.0)

### Core Features

- ✅ Complete UNITARES framework (EISV dynamics)
- ✅ HCK/CIRS stability monitoring
- ✅ Knowledge graph system (Apache AGE + semantic search)
- ✅ Identity model (4-path: Redis → PG → Name Claim → Create)
- ✅ Auto-healing infrastructure
- ✅ **30 registered MCP tools** + aliases (consolidated sub-handlers)
- ✅ Streamable HTTP transport (`/mcp/` endpoint)
- ✅ Ethical drift (Δη) fully integrated
- ✅ Trajectory identity (genesis signatures, lineage comparison, trust tiers)
- ✅ Automatic calibration from objective outcomes
- ✅ Web dashboard (EISV sparklines, dialectic timeline, trust tier badges)
- ✅ Pi/Lumen orchestration via anima-mcp
- ✅ PostgreSQL + AGE for all persistent data (dialectic migrated Feb 2026)
- ✅ KG search bias mitigation (temporal decay, status scoring, connectivity cap, SUPERSEDES edges)
- ✅ **6,344 tests** with 80% overall coverage (core modules 83-88%)

### Architecture

- **Declarative tool registration** — `ToolDefinition` dataclass, `action_router()` for consolidated tools
- **Middleware pipeline** — 8-step dispatch: identity → trajectory → kwargs → alias → inject → validate → rate limit → patterns
- **Response formatting** — Auto/minimal/compact/standard/full modes via `response_formatter.py`
- **Decorator pattern** — `@mcp_tool` with timeout, deprecation, hidden, rate_limit_exempt
- **Indexed queries** — Logarithmic scaling via AGE graph indexes
- **Async operations** — Non-blocking I/O throughout

### Performance

- **Knowledge store:** 0.01ms (was 350ms)
- **Similarity search:** 0.1ms (was 350ms)
- **Identity lookup:** < 1ms (Redis cache)
- **Query performance:** O(indexes) not O(n)

---

## Future Evolution

### Under Consideration
- Outcome correlation — does instability predict bad outcomes?
- Threshold tuning — domain-specific calibration
- WebSocket dashboard updates (replace polling)
- CIRS v1.0 — full multi-agent oscillation damping
- Semantic ethical drift detection
- Production hardening and horizontal scaling

---

## Lessons Learned

1. **Start simple, iterate** - v1.0 was basic but functional
2. **Modularity matters** - Handler registry made v2.0 possible
3. **Performance is critical** - Knowledge graph was game-changing
4. **UX matters** - Honest initialization prevents confusion
5. **Reliability first** - Auto-healing prevents production issues

---

**Last Updated:** February 19, 2026
**Current Version:** v2.7.0
**Total Evolution:** 1.0.0 → 2.7.0 (23 versions)
