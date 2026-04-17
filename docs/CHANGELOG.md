# Changelog

All notable changes to the UNITARES Governance Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Removed

- **Neighbor coupling** (2026-04-17) — deleted `AdaptiveGovernor.apply_neighbor_pressure` / `decay_neighbor_pressure` and the `neighbor_pressure` / `agents_in_resonance` state fields from `unitares-core`. Deleted `cirs.hooks.maybe_apply_neighbor_pressure`, `auto_emit_coherence_reports`, `_lookup_similarity` and all re-exports. The production call site has been disabled since the `phases.py:1005` comment landed; this commit removes the dormant scaffolding so the code reflects actual runtime behavior. Rationale: agent-to-agent threshold coupling undermined independent per-agent judgment and produced correlated EISV drift that confounded fleet anomaly detection. Forward-compatible: persisted `GovernorState` snapshots carrying `neighbor_pressure` keys continue to load (unknown keys ignored).

---

## [2.11.0] - 2026-04-07

### Added

- **Sentinel agent** — continuous independent observer that monitors governance in real-time via WebSocket. Detects fleet-wide anomalies (coordinated degradation, entropy outliers, verdict shifts), correlates incidents across typed events, and generates template-based situation reports from the audit trail. Runs as a launchd-managed persistent service alongside Vigil. (`scripts/ops/sentinel_agent.py`)
- **Broadcaster event bus** — typed event emission (`lifecycle_*`, `identity_*`, `knowledge_*`, `circuit_breaker_*`) with a queryable in-memory ring buffer (2000 events, ~6h). Foundation for Sentinel and future dashboard consumers.
- **Behavioral baseline persistence** — Welford stats (mean, variance, count per signal) now persist to PostgreSQL (`core.agent_behavioral_baselines` table) via fire-and-forget async writes. Baselines survive server restarts instead of resetting.
- **KG confidence cross-check** — discovery confidence is clamped to `agent_coherence + 0.3` on write. Annotates provenance with `confidence_clamped: true` and broadcasts `knowledge_confidence_clamped` event.
- **Circuit breaker telemetry** — trip timestamp ring buffers on both governance and Redis circuit breakers. Exposed via `get_governance_metrics()` as `circuit_breakers` section with `trips_1h`, `trips_24h`, `last_trip`.
- **Trajectory drift alerts** — emits `trajectory_drift` audit event and `identity_drift` broadcast when lineage similarity drops below 0.6. Also broadcasts `identity_assurance_change` on trust tier transitions.
- **Agent silence detection** — background task (every 10 min) monitors persistent agents (Vigil, Lumen, Sentinel) for missed check-ins. Alerts at 2x expected interval, critical alert at 5x. Deduplicates alerts, clears on recovery.

### Fixed

- **CI doc drift check** — removed stale reference to deleted `docs/guides/NGROK_DEPLOYMENT.md` that caused `FileNotFoundError` in CI.

---

## [2.10.0] - 2026-04-04

### Breaking

- **Docker removed** — Docker Compose and `postgres-age` container retired. All services now run via Homebrew PostgreSQL@17 on port 5432 with AGE 1.7.0. Migration scripts and Docker-era docs cleaned up.

### Added

- **Process marker self-healing** — the HTTP server now recreates missing `data/.mcp_server.pid` and `.mcp_server.lock` markers while running, reducing false-negative local health checks after interrupted stop/start sequences.
- **Direct HTTP identity resolution** — the HTTP request layer now resolves bound identity from `client_session_id` or `continuity_token` before direct tools run, so request-scoped tools can reuse the same session continuity path as MCP callers.
- **Pydantic schemas** for `outcome_correlation` and `reassign_reviewer` tools.
- **Doc health checker** added to pre-push pipeline.
- **Grounded outcome study utilities** — added exogenous-vs-endogenous outcome classification, data-quality reporting, grouped regression helpers, and an analysis script for outcome-correlation validation.

### Changed

- **Behavioral EISV promoted to primary** — ODE dynamics demoted to diagnostic. Pattern analysis now uses behavioral EISV histories for trend detection.
- **Operator-facing state views** — dashboard, metrics, and persisted state now expose explicit `primary_eisv`, `behavioral_eisv`, `ode_eisv`, `ode_diagnostics`, and shared state semantics instead of overloading one flat EISV view.
- **Self-relative behavioral baselines** — per-agent Welford mean/std after ~30 updates; assessment uses z-score deviation from agent's own operating point instead of fixed thresholds. Absolute safety floors (E<0.30, I<0.30, S>0.70, |V|>0.50) always apply regardless of baseline.
- **Behavioral coherence for outcomes** — outcome events now feed behavioral EISV directly, closing the loop between governance verdicts and observable results.
- Renamed internal "DNA/genotyping" terminology to standard ML terms (behavioral baseline, warmup, self-relative scoring). Persistence backward-compatible with old `dna_stats` key.
- **HTTP boundary cleanup** — core read tools (`health_check`, `get_governance_metrics`) now use transport-neutral service/data helpers, and direct HTTP responses preserve multi-block/non-text MCP content instead of collapsing everything to the first text block.
- **Identity response shaping** — `identity()` and `onboard()` now consistently expose compact operator diagnostics (`session_resolution_source`, `continuity_token_supported`, `identity_status`, `bound_identity`) across the main and early-return paths.
- **Process update orchestration** — `process_agent_update` response assembly and workflow sequencing now live in dedicated service modules, reducing handler/transport coupling.
- **Ops scripts** — `start_unitares.sh` and `stop_unitares.sh` now wait for processes to exit and avoid unlinking marker files from a freshly restarted server.
- **Tool surface reduction** — `TOOL_MODE` enforced at FastMCP registration, reducing exposed tools from 40 to 20.
- **Trajectory identity aligned** with paper's six-component signature.
- **KG search** — default multi-term queries use OR; redundant FTS per-term fallback removed.

### Security

- **MCP listen defaults** — Default bind address is `127.0.0.1`. Opt in to `0.0.0.0` with `UNITARES_BIND_ALL_INTERFACES=1` or `UNITARES_MCP_HOST`. LAN/ngrok `Host` / Origin allowlists are no longer hard-coded in source: use `UNITARES_MCP_ALLOWED_HOSTS` and `UNITARES_MCP_ALLOWED_ORIGINS` (comma-separated). See `src/mcp_listen_config.py` and `CLAUDE.md`. LaunchAgent and `start_unitares.sh` set the previous bind-all + example allowlists for existing deployments.
- **Secrets removed from git** — Docker services bound to localhost.

### Fixed

- **Resident-agent resume safety** — strong continuity-token resume is now required for Vigil-style resident agents, and rejected identity-claim paths return structured errors instead of falling through into accidental forks.
- **Timezone mismatch in auto-archive** — `_auto_archive_ephemeral_agents` used `datetime.now(timezone.utc)` for cutoff but timestamps were stored as naive local time, causing agents in non-UTC timezones to appear hours older than reality and get instantly archived.
- **Content→details param mapping** — `content` parameter passed to `store_knowledge_graph` was not persisting to the `details` field due to Pydantic `model_dump()` populating all Optional fields as `None`, which defeated `dst_key not in arguments` guards in `action_router`.
- **Search NoneType crash** — `limit=None` from Pydantic caused `NoneType * int` error in search handler.
- **Identity continuity precedence** — explicit stable session continuity now wins over name-claim recovery, preventing `identity(client_session_id=..., name=...)` from silently jumping to an older named identity.
- **Durable stable session binding** — `onboard()` now persists the returned stable `client_session_id` through the normal session-bind path, so a Redis miss no longer causes a fresh UUID to be created on later resume.
- **HTTP work logging continuity** — `process_agent_update(client_session_id=...)` and `process_agent_update(continuity_token=...)` now resolve the correct bound identity on fresh HTTP requests instead of requiring the caller to pass the raw UUID manually.
- **HTTP metrics continuity** — `get_governance_metrics(client_session_id=...)` now resolves the real bound agent instead of materializing an unrelated auto-generated identity on the HTTP path.
- **AGE discovery durability** and drift checks hardened.
- **Tags preserved** on knowledge updates when omitted.
- **High-severity KG updates** and anonymous note writes tightened.
- **Dialectic reviewer selection**, Vigil signals, and convergence guidance fixes.
- **Lock timeouts** classified as system errors.
- **Missing agent rows** repaired during lazy persistence.
- **Pre-existing test failures** resolved (circular import in `_generate_contextual_reflection`, identity adapter name claim path).
- **Doc health drift** — stale file references, stale counts, and false-positive doc-health warnings cleaned up.

### Removed

- Docker Compose and `postgres-age` container setup.
- Completed migration scripts archived.
- Unused exceptions module.

---

## [2.9.0] - 2026-03-29

### Breaking — Epoch Bump (1 → 2)

- **DB epoch bumped to 2** — Behavioral EISV replaces ODE dynamics. Existing state data computed under the old model is incompatible. Old data (epoch 1) remains in the database but is excluded from active queries. All agents start fresh in epoch 2 on next check-in.

### Added — Identity & Session Management

- **`bind_session` tool** — bridges the identity gap between REST hooks (which onboard via curl) and MCP Streamable HTTP (which uses a different session key). One call at session start syncs both namespaces to the same agent.
- **Thread-based identity** with honest forking — agents acknowledge fresh sessions instead of falsely claiming continuity. Epistemic context feeds into EISV dynamics.

### Added — Behavioral EISV (Non-Embodied Agents)

- **Behavioral sensor EISV** — non-embodied agents (Claude, Cursor) get synthetic EISV seeds derived from behavioral signals (response latency, error rates, task complexity patterns) instead of physical sensors.
- **Behavioral trajectory identity** — trajectory fingerprinting for non-embodied agents using behavioral patterns rather than sensor readings.
- **Coherence differentiation** — reduced V damping, wired behavioral signals into coherence calculation, adaptive delta for basin edge detection.

### Added — Sensor EISV & Spring Coupling (Lumen)

- **Sensor spring coupling** in EISV ODE — Lumen's physical sensor readings (temperature, humidity, light) now couple into the ODE as spring terms, grounding dynamics in physical state.
- **Normalized spring coupling** by dimension range width for consistent cross-dimension influence.
- Hardened sensor EISV: clip to physical bounds, removed dead code.

### Changed — Soft Barrier Dynamics (governance-core)

- **Soft barrier replaces hard clamping** in EISV ODE — cubic barrier potential in `_derivatives()` smoothly repels state away from bounds (C² continuous, zero in interior). Hard `clip()` in integrators demoted to safety net. Preserves Jacobian continuity for contraction/Lyapunov analysis.
- **Barrier parameters** added to `DynamicsParams`: `barrier_strength=2.0`, `barrier_margin=0.05`. Margins scaled proportionally for S (×2.0) and V (×4.0) ranges.
- **Analytical Jacobian** updated with barrier diagonal terms in `stability.py`.
- **Removed redundant V bounds clip** in `governance_monitor.py` post-ODE block — barrier handles it; S floor and coherence recalc retained.

### Added — EISV Dynamics & Governance

- **State velocity feedback** — rate-of-change of EISV dimensions feeds back into dynamics, enabling faster response to rapid drift.
- **Adaptive lambda2** via `theta.eta2` — coherence damping on entropy is now state-dependent.
- **Coherence reports** auto-emitted for neighbor pressure detection in multi-agent scenarios.
- **Dialectic condition enforcement** at tier-1 with genesis reseed fix.
- **Closed feedback loops** — calibration deviation, ethical drift, and behavioral patterns now feed back into governance decisions via CIRS oscillation detection.
- **Persistent AdaptiveGovernor state** — governor parameters survive server restarts.
- Tuned thresholds for coding agents (beta_default 0.60 → 0.70), fixed recovery loop spiral.

### Added — Knowledge Graph

- **System version in discoveries** — `system_version` auto-populated in provenance at store time. Surfaced as top-level field in search results. Pre-v2.8.0 entries show `null`.
- **Staleness warnings** — KG search flags open entries >60 days old or 2+ minor versions behind current with `staleness_warning` per discovery.
- **Concept extraction** — background task automatically extracts concepts from agent check-ins and creates knowledge graph entries with spawned edges linking related discoveries.
- **Spawned edges** — knowledge graph entries can now track provenance via `SPAWNED_BY` edges and tag-based queries.
- **Pool guard improvements** — connection pool health checks prevent stale connections from corrupting KG operations.

### Added — Infrastructure

- **Database hygiene** — automated retention policy, batch queries, and periodic maintenance tasks.
- **Docker Compose** — top-level `docker-compose.yml` for one-liner setup of PostgreSQL+AGE and Redis.
- **Gateway MCP server** — simplified 6-tool proxy on port 8768 for weak external clients (Cursor, etc.).
- **LLM-assisted dialectic recovery** when no peers are available for review.
- **Agent baselines** persisted to PostgreSQL for cross-session calibration tracking.

### Added — EISV Analysis Tools

- **Monte Carlo basin estimation** (`scripts/basin_estimation.py`) — maps safe operating region by sampling 10K random perturbations and integrating forward via `compute_dynamics()`. Confirmed global attractivity under linear I-dynamics mode (100% convergence across full state space).
- **Contraction analysis verifier** (`scripts/contraction_analysis.py`) — numerically computes the EISV Jacobian (analytical + numerical cross-validation to 5×10⁻¹⁰), verifies all eigenvalues negative, optimizes diagonal contraction metric. Bare rate: 0.046, optimized rate: 0.113. All Theta values contracting (400-point sweep).
- **Compositionality metrics** (`scripts/compositionality_metrics.py`) — measures topographic similarity and region consistency of Lumen's primitive language. Supports real data from Pi SQLite DB or synthetic data mode for development.
- **Analysis test suite** (`tests/test_analysis_tools.py`) — 36 tests covering all three tools.
- `analysis` optional dependency group in pyproject.toml (scipy, matplotlib, editdistance).

### Changed — Major Refactoring (5-Phase Module Split)

Decomposed monolithic files into focused modules for maintainability:

1. **Phase 1**: Extracted `tool_descriptions` to JSON
2. **Phase 2**: Split `utils.py` into 5 focused modules
3. **Phase 3**: Split `agent_state.py` into 7 focused modules
4. **Phase 4**: Split `identity_v2.py` into 3 focused modules
5. **Phase 5**: Split `cirs_protocol.py` into 9 focused modules

Additional refactors:
- Extracted `mcp_server.py` and `governance_monitor.py` into focused modules
- Extracted background tasks, flattened `lifecycle_stuck`, renamed `response_formatting`
- **LazyMCPServer singleton** — deduplicated `_LazyMCPServer` into `shared.lazy_mcp_server`, Pydantic runtime validation, `ConnectionTracker` extraction
- Deleted dead code, organized scripts, decoupled transport, split `admin.py`

### Changed — First Check-in Guidance

- **Convergence guidance suppressed for early check-ins** — When `update_count ≤ 3`, EISV-derived guidance replaced with honest "Not enough data yet" message. Prevents misleading advice based on initialization defaults.
- **Restorative block suppressed for early check-ins** — Same threshold, prevents false complexity divergence alerts on new agents.

### Changed — Agent-Facing Response Trimming

- **`health_check` lite mode** (default `lite=true`) — returns only component status without nested info/stats blocks, reducing context window usage. Use `lite=false` for full diagnostic detail.
- **KG `health_check()` lightweight** — runs 3 COUNT queries instead of full `get_stats()` census. Eliminates per-agent/per-tag breakdowns from every health check. `get_stats()` unchanged for admin use.
- **Uninitialized agent verdict** — agents with zero check-ins now get `verdict: 'uninitialized'` with `guidance: 'Call process_agent_update to activate governance'` instead of a generic `caution` verdict.

### Fixed

- **Health check CI timeout flake** — mocked Pi connectivity in all health_check tests to prevent real network calls timing out in GitHub Actions.
- **`compute_equilibrium()` linear mode bug** — was using logistic quadratic formula regardless of I-dynamics mode, returning I*=1.0 instead of correct I*=A/γ_I≈0.85. Now checks `get_i_dynamics_mode()` and uses correct formula. Also includes `beta_complexity * complexity` term in S* and computes E* = αI*/(α + βₑS*) instead of E* ≈ I*.
- **Inverted `is_bad` default** and unguarded NaN in outcome scores
- **Coherence margin always "tight"** — str/float coercion and recovery tau noise fixes
- **Behavioral sensor E saturation** and adaptive margin baseline drift
- **Silent binding to archived agents** — prevented, with KG search degradation surfaced
- **Metadata loaded before orphan cleanup** on startup
- Inline validation for `discovery_type`, `severity`, and `response_to` in KG single-store and leave_note paths
- Preserved schema metadata (descriptions, enums) in MCP tool aliases
- Missing `sanitize_agent_name` function in validators
- `anyOf` JSON schema handling in wrapper generator

### Docs

- Discord summoner design and implementation plan
- README rewrite with production validation data, architecture diagrams, and figures
- CLAUDE.md project instructions
- Archived completed plans, fixed stale doc references

## [2.8.0] - 2026-02-26

### Added — Dashboard Redesign

Major dashboard overhaul — Alpine.js + htmx interactive architecture replacing static HTML.

- **Slide panel component** with agent detail view, EISV trend charts, and quick action buttons
- **Alpine.js identity store** with "Me mode" — AI agents see themselves highlighted in the dashboard
- **Hash-based router** for deep-linking to agents, sessions, and discoveries
- **Scoped search** with agents/all toggle and debounced input
- **Keyboard shortcuts** (vim-style navigation) with tooltip directive and help store
- **Loading skeletons** and smart empty states for all data-fetching panels
- **Error handling wrapper** and connection health checker
- **Expandable agent cards** with accordion, inline IDs, and hover actions
- **Bold visual redesign** — accent-tinted cards, colored EISV values, stronger badges, panel identity
- **help.json** terminology database for contextual tooltips
- **EISV history + incidents endpoints** for htmx fragment rendering
- **Event IDs + `?since=` cursor** on `/api/events` for Discord bridge polling
- **Discovery expand-on-click** with expandable details in list items
- Removed redundant Activity Timeline panel (duplicated Agents list)
- Removed Lumen sensor panel from governance dashboard

### Added — Outcome Events Infrastructure

- **Outcome event tracking** for EISV validation — correlate governance state with actual results
- **Auto-emit outcome events** from check-ins, enabling calibration feedback loops
- `outcome_event()` tool for manual event recording

### Added — Stuck Agent Improvements

- **Cross-referencing** stuck agents with recent activity across knowledge graph
- **Unstick action** in dashboard with one-click recovery button
- **Zombie prevention** — prevent archived agents from resurrecting via auto-resume
- **Auto-unarchive** on onboard reconnect for legitimately returning agents
- **Dedup recovery notes** in knowledge graph to reduce noise

### Added — Knowledge Graph Lifecycle

- **Ephemeral notes** with automatic expiration
- **Periodic cleanup** for stale KG entries
- **`last_referenced` tracking** for discovery recency
- **Improved search UX** with better result formatting

### Added — Developer Documentation

- Developer guide for repo protection from agent damage
- Dashboard redesign design document and implementation plan
- Unified DB architecture design doc and implementation plan

### Changed — Streamable HTTP Migration

- **Primary transport migrated from SSE to Streamable HTTP** (`/mcp/` endpoint)
- Removed dead SSE code paths from server and pi_orchestration
- Network trust bypass for HTTP auth (local network clients)
- System health metrics added to dashboard

### Changed — Dialectic Protocol Hardening

- **Simplified convergence** — `agrees=True` resolves directly, no fourth phase needed
- **UUID alignment** via `require_registered_agent` — dialectic sessions use onboard identity
- **Synthesizer attribution** displayed in session transcripts
- **Reviewer auto-persist** and AGE tag normalization
- **Reviewer auto-assign** fix for empty string default
- **Mediator hijack prevention** (audit round 2)
- **`finalize_resolution` fallback** to thesis `root_cause` when synthesis missing
- **Ownership check removed** from archive/delete — dashboard can manage sessions
- **Agent UUID → label resolution** in dialectic panel
- Removed dead convergence code, fixed `agrees` coercion
- 7 correctness bugs found and fixed via protocol audit
- `DialecticDB` detects closed pool and auto-refreshes from backend

### Changed — Identity Consolidation

- **Unified `derive_session_key()`** — consolidated 6 separate derivation sites
- Removed deprecated `_derive_session_key` (underscore-prefixed)
- Fixed `get_bound_agent_id` import (identity_shared, not identity)
- Clarified agent_id vs UUID terminology in comments and docs
- Updated AGI-forward spec for identity_v2 current state
- Fixed identity churn, display dispatch, and tag normalization (audit)

### Changed — Lifecycle Module Refactoring

- **Split `lifecycle.py` monolith** — extracted `lifecycle_resume.py` (142 lines) and `lifecycle_stuck.py` (557 lines) into focused modules
- Lifecycle handler reduced from ~720 lines to focused orchestration

### Changed — Dashboard Performance & Accessibility

- **CSS containment** for render optimization
- **`requestAnimationFrame`** for chart updates, EISV chart capped at 60 data points
- **Debounced search** inputs, removed duplicate listeners
- **CONFIG object** with timing constants, replaced magic numbers
- **Semantic color CSS variables** and section headers for CSS navigation
- **ARIA labels**, modal roles, skip link, focus management, and focus trap
- Fixed heading hierarchy for perfect a11y score
- Removed 4 unused component classes
- JSDoc added to core dashboard functions

### Changed — Database & Backend

- Removed SQLite backend and dual-write entirely (complement to v2.7.0 cleanup)
- `normalize_tags` for knowledge graph entries
- Connection pool release and `acquire_compat` safety
- Cross-event-loop DB corruption fix with system health tracking
- Batch update counter persistence to prevent DB contention
- Update count regression prevention on server restart

### Fixed

- **httpx client leak** in `pi_orchestration` — unclosed async client
- **datetime shadowing bug** broke dashboard agent listing
- **False-positive stuck agent detection** and dashboard noise eliminated
- **Leave_note limit** raised from 500 → 6,000 chars, split into summary+details
- **Reject out-of-range** complexity/confidence, guard `observe(compare)` NoneType
- **Knowledge `content→details` param_map** for store action (alias fix)
- **Self-recovery** — allow archived agents to self-restore via `self_recovery(quick)`
- **UUID validation + auth checks** on dashboard fragment endpoints
- 7 dogfood friction issues from Sonnet 4.6 Web session
- 15 audit fixes + 8 audit round 2 fixes
- 3 CI failures (async calibration tests + observability mock)
- 2 pre-existing test failures resolved
- Async metadata loading and handler improvements

### Removed

- SQLite backend and all related test files (final cleanup)
- Dead SSE transport code
- Lumen sensor panel from dashboard
- Activity Timeline panel (redundant)
- 4 unused dashboard component classes
- Dead convergence code from dialectic protocol

### Tests

- 5,654 tests collected, 80% coverage target
- Test updates for async metadata, dialectic phase, KG truncation limits

---

## [2.7.0] - 2026-02-20

### Added — CIRS v2 Resonance Wiring
- **AdaptiveGovernor** PID controller: phase-aware tau/beta thresholds, oscillation detection (OI + flip counting)
- **Resonance → CIRS protocol loop**: `maybe_emit_resonance_signal()` emits RESONANCE_ALERT / STABILITY_RESTORED on state transitions
- **Neighbor pressure**: `maybe_apply_neighbor_pressure()` reads peer resonance alerts, applies defensive threshold tightening via coherence similarity
- **`was_resonant` tracking**: GovernorState tracks previous cycle for transition detection
- 13 new tests (3 governor + 4 signal + 5 pressure + 1 integration), 6,407 tests total at 80% coverage

### Changed — I-Channel Dynamics (v5 Paper Alignment)
- Default I-dynamics mode flipped from logistic to linear (`UNITARES_I_DYNAMICS=linear`)
- Linear mode prevents boundary saturation (m_sat = -1.23 under logistic), stable equilibrium at I* ≈ 0.80
- Auto-applies γ_I = 0.169 (V42P tuning) when using linear mode + default profile
- Dialectic protocol: added `design_review` session type with 7-day/30-day timeouts
- Dialectic protocol: self-review shortcut (single agrees=True sufficient when paused_agent == reviewer)
- Condition normalization: fixed to keep 2-char words, handle mixed-case, added "it"/"its" to filler list

### Changed — Database Architecture
- **Removed SQLite backend** — deleted `sqlite_backend.py` (1,116 lines), `dual_backend.py` (697 lines), and test files (2,299 lines). PostgreSQL is the sole backend.
- Removed `DB_BACKEND` environment variable — no more sqlite/postgres/dual switching
- Simplified `db/__init__.py` to always return `PostgresBackend`
- Removed SQLite paths from `audit_log.py`, `calibration.py`, `mcp_server.py`, `mcp_server_std.py`
- Total: **4,697 lines deleted**, 79 lines added

### Changed — Version Governance
- Bumped all version references from 2.6.x to 2.7.0

---

## [2.6.4] - 2026-02-08

### Added — KG Search Bias Fixes

Knowledge graph searches were biased toward old, heavily-linked philosophical entries from Dec 2025.
New agents would reflect on them, adding more links, creating a positive feedback loop. Four fixes:

- **Temporal decay** — 90-day half-life applied to blended search scores. Old entries still surface
  if semantically relevant, but don't dominate by default.
- **Status-aware scoring** — Archived entries scored at 0.3x, resolved at 0.6x, disputed at 0.5x.
  Open entries unaffected.
- **Connectivity dampening** — Capped effective connectivity input at 50 (was unbounded). Prevents
  heavily-linked entries from monopolizing search results.
- **Default archived filtering** — `semantic_search()` excludes archived entries by default.
  Callers can opt in with `include_archived=True`.
- **SUPERSEDES edge type** — New AGE edge for marking entries that replace others. Superseded
  entries get halved connectivity scores. Available via `knowledge(action='supersede')`.

### Fixed — CI Test Failures (55 tests)

- **test_model_inference.py** (45 failures) — `openai` package not in CI dependencies. Fixed by
  ensuring `OpenAI` attribute exists on module for patching. Skip `TestCreateModelInferenceClient`
  when `openai` not installed.
- **test_auto_ground_truth.py** (10 failures) — Fragile module-reload mocking broke when run
  alongside other tests. Root cause: `import src.X as Y` resolves via parent package `__dict__`,
  not just `sys.modules`. Fixed by patching both `sys.modules` AND parent package attributes.

### Tests
- 6,344 tests passing, 80% coverage

### Files Changed
- `src/storage/knowledge_graph_age.py` — Temporal decay, status multiplier, connectivity cap, SUPERSEDES edge
- `src/mcp_handlers/knowledge_graph.py` — Default archived filtering, supersede action
- `tests/test_model_inference.py` — CI fix for missing openai package
- `tests/test_auto_ground_truth.py` — CI fix for module import resolution in mocks

---

## [2.6.3] - 2026-02-06

### Changed — Dialectic Audit & Cleanup

- **Fixed 16 misleading `sqlite_*` import aliases** → `pg_*` across 3 dialectic handler files
  (backend has been PostgreSQL-only since Feb 2026)
- **Made `llm_assisted_dialectic` reachable** via `request_dialectic_review(reviewer_mode='llm')`
- **Consolidated `get_dialectic_session` + `list_dialectic_sessions`** into
  `dialectic(action='get/list')` via action_router — 31 → 30 registered tools
- **Implemented EISV governance update** from Pi anima sensor sync:
  `pi(action='sync_eisv', update_governance=true)` now feeds sensor state into governance engine
- **Removed dead SSE code** — 3 deprecated functions (~80 lines) from mcp_server.py
- **Fixed stale comments/metadata** across tool_schemas, admin, tool_modes, tool_stability

### Tests
- 2,602 tests passing, 0 failures, 49% coverage

### Files Changed
- `src/mcp_handlers/dialectic.py` — pg_ aliases, LLM reviewer, register=False for get/list
- `src/mcp_handlers/dialectic_session.py` — pg_ aliases
- `src/mcp_handlers/dialectic_reviewer.py` — pg_ aliases
- `src/mcp_handlers/consolidated.py` — Added dialectic action_router
- `src/mcp_handlers/pi_orchestration.py` — EISV sync governance update
- `src/mcp_handlers/tool_stability.py` — Dialectic aliases, stability tiers
- `src/tool_schemas.py` — Dialectic consolidated schema, LLM enum, stale refs
- `src/tool_modes.py` — Dialectic categorization update
- `src/mcp_server.py` — Removed dead SSE code

---

## [2.6.2] - 2026-02-06

### Changed — Architecture Refactoring (4 Refactors)

Four internal refactors to reduce boilerplate, improve clarity, and make the tool system
more maintainable. No breaking changes — all 30 tools, aliases, and behaviors preserved.

#### Refactor 1: Unified ToolDefinition Registry
- **Replaced 4 separate dicts** (`_TOOL_REGISTRY`, `_TOOL_TIMEOUTS`, `_TOOL_DESCRIPTIONS`,
  `_TOOL_METADATA`) with a single `ToolDefinition` dataclass + `_TOOL_DEFINITIONS` registry
- Backward-compatible accessor functions preserved (`get_tool_registry()`, etc.)
- **File:** `src/mcp_handlers/decorators.py`

#### Refactor 2: Declarative Action Router
- **New `action_router()`** function creates consolidated tools from `actions: Dict[str, Callable]`
- Supports `default_action`, `param_maps` (per-action parameter remapping), and `examples`
- Rewrote all 7 consolidated handlers (knowledge, agent, calibration, config, export, observe, pi)
- **`consolidated.py` reduced from 479 → 245 lines** — no more if/elif chains
- **Files:** `src/mcp_handlers/decorators.py`, `src/mcp_handlers/consolidated.py`

#### Refactor 3: Dispatch Middleware Pipeline
- **Extracted `dispatch_tool()`** from 440-line monolith into 8 composable middleware steps
- Each step: `async (name, arguments, ctx) → (name, arguments, ctx) | list[TextContent]`
- Steps: resolve_identity → verify_trajectory → unwrap_kwargs → resolve_alias →
  inject_identity → validate_params → check_rate_limit → track_patterns
- `DispatchContext` dataclass carries state between steps
- **`dispatch_tool()` reduced from ~440 → ~50 lines**
- **Files:** `src/mcp_handlers/middleware.py` (NEW), `src/mcp_handlers/__init__.py`

#### Refactor 4: Response Formatter Extraction
- **Extracted response mode branching** (auto/minimal/compact/standard/full) from `core.py`
- `format_response()` function handles all mode filtering and context stripping
- **~190 lines removed from `core.py`**, replaced with 10-line function call
- **Files:** `src/mcp_handlers/response_formatter.py` (NEW), `src/mcp_handlers/core.py`

### Added — UX Friction Fixes (v2.6.1 session)
- **Dashboard overhaul** — live EISV sparklines, dialectic timeline, trust tier badges
- **Name-based identity resolution** (PATH 2.5) — agents reconnect by name, not session key
- **Observe tool fix** — `target_agent_id` supports labels, proper schema

### Tests
- 2,194 tests passing, 0 failures, 43% coverage

### Files Changed
- `src/mcp_handlers/decorators.py` — ToolDefinition dataclass + action_router
- `src/mcp_handlers/consolidated.py` — Rewritten with action_router (479→245 lines)
- `src/mcp_handlers/middleware.py` — NEW: 8-step dispatch pipeline
- `src/mcp_handlers/__init__.py` — Simplified dispatch_tool (~440→~50 lines)
- `src/mcp_handlers/response_formatter.py` — NEW: response mode filtering
- `src/mcp_handlers/core.py` — Response formatting extracted

---

## [2.6.1] - 2026-02-06

### Added — Name-Based Identity Resolution (PATH 2.5)

Every new HTTP session was creating a new agent UUID. 1650+ ghost agents existed because
session keys rotate per request. PATH 2.5 adds name-based identity claim: before creating
a new UUID, the server checks if the agent is claiming an existing name via label lookup
in PostgreSQL.

```
PATH 1: Redis cache by session_key       → found? use it
PATH 2: PostgreSQL session by session_key → found? use it
PATH 2.5: PostgreSQL agent by name claim  → found? bind + use it  ← NEW
PATH 3: Create new UUID                  → last resort
```

#### Identity Resolution
- **`resolve_by_name_claim()`** — New function in `identity_v2.py`. Looks up agent by
  label in PG, optionally verifies trajectory signature (anti-impersonation, rejects if
  lineage_similarity < 0.6), binds session in Redis + PG.
- **`resolve_session_identity()`** — New parameters `agent_name` and `trajectory_signature`.
  PATH 2.5 inserted before PATH 3.
- **`handle_identity_adapter()`** — Name claim runs before STEP 1 session resolution,
  preventing dispatch-created ephemerals from polluting the cache.
- **`handle_onboard_v2()`** — When `name` is provided and `not force_new`, tries
  `resolve_by_name_claim()` first before session-based lookup.
- **Dispatch (`__init__.py`)** — Extracts `agent_name` (check-in) or `name` (identity/onboard)
  and passes to `resolve_session_identity()`.
- **Schema (`tool_schemas.py`)** — Added `agent_name` parameter to `process_agent_update`.

#### Observe Tool Fix
- **Schema** — Added proper `inputSchema` for consolidated `observe` tool (was empty
  `properties: {}`, causing Pydantic typed wrapper to drop all parameters).
- **`target_agent_id`** — Renamed from `agent_id` to avoid clash with session-bound caller
  identity. Supports both UUID and label (e.g. `target_agent_id="Lumen"`).
- **Label resolution** — `handle_observe_agent()` resolves labels to UUIDs via
  `_find_agent_by_label()`, bypasses `require_agent_id`'s session-override behavior.

### Fixed
- Ghost agent proliferation: named agents reconnect instead of forking
- `observe_agent` alias dropping all parameters except `action`
- Session mismatch error when observing other agents
- `agent_name` parameter not extracted for identity/onboard tools in dispatch

### Database
- Added partial index: `idx_agents_label ON core.agents(label) WHERE label IS NOT NULL`
- Cleaned up test ghost agents (Tessera_* suffixed entries)

### Tests
- 1,907 tests passing, 0 failures, 41% coverage (at time of release; see v2.6.2 for latest)

### Files Changed
- `src/mcp_handlers/identity_v2.py` — +162 lines (resolve_by_name_claim + PATH 2.5 wiring)
- `src/mcp_handlers/__init__.py` — +19 lines (agent_name extraction in dispatch)
- `src/mcp_handlers/observability.py` — +57 lines (target_agent_id + label resolution)
- `src/tool_schemas.py` — +70 lines (observe schema + agent_name parameter)

---

## [2.6.0] - 2026-02-05

### Major Cleanup & Consolidation

This release removes ~4,200 lines of dead code, migrates dialectic sessions fully to PostgreSQL,
and expands test coverage from ~25% to 40% (1,798 tests passing).

### Removed - Dead Code (~4,200 lines)
- `identity.py` (v1) — Replaced by `identity_v2.py`
- `oauth_identity.py` — Never imported
- `governance_db.py` — Old SQLite backend, replaced by `postgres_backend.py`
- `knowledge_db_postgres.py` — Old PG backend, replaced by AGE graph
- `agent_id_manager.py`, `api_key_manager.py` — Unused
- `ai_behavior_analysis.py`, `ai_knowledge_search.py`, `ai_synthesis.py` — Replaced by `call_model`
- `mcp_server_compat.py`, `monitoring/`, `dual_log/INTEGRATION.py` — Unused

### Changed - Handler Refactoring
- **Tool surface reduced**: 49 → 29 registered tools (admin/internal tools hidden)
- **Dialectic backend**: Fully migrated from SQLite to PostgreSQL
- **Reviewer selection**: Simplified to random selection (user-facilitated model)
- **Consolidated handlers**: New `export()` and `observe()` unified tools
- **Deprecation**: `direct_resume_if_safe` → `quick_resume`/`self_recovery`
- **Tool schemas**: Added `client_session_id` parameter support

### Added - Dashboard & Infrastructure
- `dashboard/styles.css` — Extracted CSS for dashboard
- `scripts/migrate_dialectic_to_postgres.py` — Migration script (72 sessions migrated)
- `skills/unitares-governance/SKILL.md` — Agent onboarding guide
- System audit documentation

### Tests
- **43 new test files** covering pure logic, validators, helpers, integrations
- **1,798 tests passing**, 40% coverage (up from 458 tests, 25%)
- Cleanup fixture for `test_kwargs_unwrapping` to prevent ghost agent proliferation

### Fixed
- Dashboard `styles.css` now served (added to static file allowlist)
- Dialectic session listing uses PostgreSQL instead of stale SQLite
- Lumen governance check-ins restored (ngrok basic auth support in bridge)
- `_resolve_dialectic_backend()` now recognizes `postgres` as valid value

---

## [2.5.9] - 2026-02-05

### Added - Agent Circuit Breaker Enforcement

The agent "pause" status now actually blocks operations. Previously, setting `meta.status = "paused"` was purely cosmetic - agents could continue calling tools. Now it's enforced.

#### Enforcement Points
- **`process_agent_update`** — Paused agents cannot submit work updates
- **`store_knowledge_graph`** — Paused agents cannot store discoveries
- **`leave_note`** — Paused agents cannot leave notes

#### New Helper Function
- **`check_agent_can_operate(agent_uuid)`** — Reusable enforcement function
  - Returns `None` if agent can operate
  - Returns error `TextContent` if blocked (paused/archived)
  - Includes recovery guidance in error response

#### Recovery Path
- Paused agents receive clear error with recovery instructions
- Error includes: `self_recovery(action='resume')` or wait for auto-dialectic
- Error code: `AGENT_PAUSED` or `AGENT_ARCHIVED`

### Tests
- **9 new tests** for circuit breaker enforcement (`tests/test_circuit_breaker_enforcement.py`)
- Tests verify enforcement in handlers via source inspection
- Tests verify `check_agent_can_operate` blocks correctly

### Files Changed
- `src/mcp_handlers/core.py` — Added enforcement to `handle_process_agent_update`
- `src/mcp_handlers/knowledge_graph.py` — Added enforcement to `handle_store_knowledge_graph`, `handle_leave_note`
- `src/mcp_handlers/utils.py` — Added `check_agent_can_operate()` helper
- `tests/test_circuit_breaker_enforcement.py` — New test file

---

## [2.5.8] - 2026-02-05

### Added - Production-Grade Redis Resilience

#### Circuit Breaker Pattern
- **Fast failure when Redis is down** — Stops hammering Redis after 5 consecutive failures
- **Auto-recovery testing** — Transitions to HALF_OPEN after 30s to test if Redis recovered
- **State machine** — CLOSED → OPEN → HALF_OPEN → CLOSED lifecycle

#### Connection Pooling
- **Efficient connection management** — Default pool size of 10 connections
- **Configurable via env** — `REDIS_POOL_SIZE` environment variable

#### Retry with Exponential Backoff
- **Transient failure handling** — 3 retry attempts with exponential backoff
- **Configurable delays** — Base delay 0.1s, max delay 2.0s
- **Connection error detection** — Auto-reconnect on connection failures

#### Periodic Health Check
- **Reduced overhead** — Background health check every 30s instead of ping-per-call
- **Proactive failure detection** — Detects Redis failures before operations fail

#### Fallback Metrics
- **Comprehensive visibility** — Tracks operations, retries, fallbacks, connections
- **`get_redis_metrics()`** — Export metrics for monitoring dashboards
- **Success rate tracking** — Know when system is degraded

#### Redis Sentinel Support (HA)
- **High availability deployments** — Connect via Sentinel for automatic failover
- **`REDIS_SENTINEL_HOSTS`** — Comma-separated sentinel hosts
- **`REDIS_SENTINEL_MASTER`** — Master name for Sentinel discovery

### New Classes
- `CircuitBreaker` — Reusable circuit breaker pattern
- `RedisConfig` — Configuration dataclass with env var support
- `RedisMetrics` — Metrics collection and export
- `ResilientRedisClient` — Main client with all resilience features

### New Functions
- `get_redis_metrics()` — Get comprehensive health status
- `get_circuit_breaker()` — Access circuit breaker for monitoring
- `with_redis_fallback()` — Decorator for operations with fallback

### Environment Variables
```
REDIS_URL                      # Connection URL (default: redis://localhost:6379/0)
REDIS_ENABLED                  # Enable/disable Redis (default: 1)
REDIS_POOL_SIZE                # Connection pool size (default: 10)
REDIS_RETRY_ATTEMPTS           # Max retry attempts (default: 3)
REDIS_CIRCUIT_BREAKER_THRESHOLD # Failures before circuit opens (default: 5)
REDIS_CIRCUIT_BREAKER_TIMEOUT  # Seconds before retry after open (default: 30)
REDIS_SENTINEL_HOSTS           # Sentinel hosts (e.g., "host1:26379,host2:26379")
REDIS_SENTINEL_MASTER          # Sentinel master name (default: "mymaster")
```

### Tests
- **27 new tests** for Redis resilience (`tests/test_redis_resilience.py`)
- **449 tests passing** (up from 416)
- **31% coverage** maintained

### Files Changed
- `src/cache/redis_client.py` — Complete rewrite with resilience features (670 lines)
- `src/cache/__init__.py` — Updated exports for new classes/functions
- `tests/test_redis_resilience.py` — New comprehensive test suite

---

## [2.5.7] - 2026-02-05

### Changed - Identity Simplification & Code Organization

#### Three-Tier Identity Model
- **Simplified from four-tier to three-tier**:
  - `UUID` — Immutable internal identifier (primary key)
  - `agent_id` — Model+date format (e.g., `Claude_Opus_20251227`) for tracking
  - `display_name` — User-chosen name (merged with former `label` tier)
- `label` kept as backward-compat alias pointing to `display_name`
- Updated docstrings to document v2.5.3 three-tier model

#### Identity Module Refactoring
- **New `identity_shared.py`** — Shared utilities extracted from identity.py:
  - Session cache (`_session_identities`, `_uuid_prefix_index`)
  - Session key functions (`_get_session_key`, `make_client_session_id`)
  - Identity lookup (`get_bound_agent_id`, `is_session_bound`)
  - Permissions (`require_write_permission`)
  - Lineage utilities (`_get_lineage`, `_get_lineage_depth`)
- **Slimmed `identity.py`** — Now imports shared utilities, contains only async DB functions
- **Cleaner imports** — All modules now import from `identity_shared.py` for shared state

### Files Changed
- `src/mcp_handlers/identity_shared.py` — New shared module (280 lines)
- `src/mcp_handlers/identity_v2.py` — Updated to three-tier, uses identity_shared
- `src/mcp_handlers/identity.py` — Slimmed down, imports from identity_shared
- `src/mcp_handlers/__init__.py` — Updated imports
- `src/mcp_handlers/admin.py`, `lifecycle.py`, `knowledge_graph.py`, `oauth_identity.py` — Updated imports

### Tests
- **416 tests passing** (all existing tests still pass)
- **31% coverage** maintained

---

## [2.5.6] - 2026-02-05

### Added - UX Friction Fixes & Consolidated Tools

#### UX Friction Fixes (9 of 12 implemented)
- **Error code auto-inference** — `error_response()` now auto-infers error codes from message patterns (DATABASE_ERROR, TIMEOUT, NOT_FOUND, etc.)
- **Tool alias action injection** — Deprecated tool names automatically inject the correct `action` parameter when routing to consolidated tools
- **Parameter coercion reporting** — `_param_coercions` field shows what type conversions were applied
- **Lite response mode** — `lite_response=True` reduces output verbosity by excluding agent_signature
- **Error message sanitization** — Stack traces and internal paths stripped from error messages

#### Consolidated Tools
- **`config` tool** — Unified get/set thresholds (replaces `get_thresholds`, `set_thresholds`)
- **38+ tool aliases** — All legacy tool names map to consolidated tools with action injection
- **Better error guidance** — Unknown actions return `valid_actions` list with examples

#### LLM Delegation
- **`llm_delegation.py`** — Delegate tasks to smaller local/remote models
- **Ollama support** — Local model inference for knowledge synthesis
- **OpenAI fallback** — Remote model support when local unavailable

#### Dashboard Improvements
- **Modular components** — `components.js` for reusable UI elements
- **Shared utilities** — `utils.js` for common functions
- **Better structure** — Dashboard code reorganized for maintainability

#### Migration Cleanup
- **13 migration scripts archived** — Moved to `scripts/archive/migrations_completed_202602/`
- **Telemetry data ignored** — `data/telemetry/*.jsonl` added to `.gitignore`

### Changed
- Test suite expanded to **358 tests** (from 310+)
- Coverage at **30%** overall (core modules higher)
- Documentation updated with port configuration guides
- LICENSE updated with correct repository URL

### Fixed
- **Tool 'config' not found** — Added missing consolidated config tool
- **Alias injection not working** — Added `inject_action` field to `ToolAlias` dataclass
- **Test assertions** — Fixed test messages to match actual error patterns

### Files Changed
- `src/mcp_handlers/consolidated.py` — Added `config` tool
- `src/mcp_handlers/tool_stability.py` — Added `inject_action` to ToolAlias
- `src/mcp_handlers/utils.py` — Added `_infer_error_code_and_category()`, `_sanitize_error_message()`
- `src/mcp_handlers/validators.py` — Added coercion tracking
- `tests/test_ux_fixes.py` — 48 new tests for UX fixes
- `docs/TOOL_AUDIT_2026-02-04.md` — Tool audit documentation

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

### v2.6.2
- `test_get_governance_metrics` flaky when run with full suite (test ordering issue)
- Knowledge graph doesn't close loops well — resolve or archive discoveries manually

### Workarounds
All known issues have fallback behavior and don't block functionality.

---

## Future Roadmap

### In Progress
- Outcome correlation — does high instability actually predict bad outcomes?
- Threshold tuning — domain-specific drift thresholds need real-world calibration

### Under Consideration
- WebSocket dashboard updates (replace polling)
- CIRS v1.0 — full multi-agent oscillation damping
- Semantic ethical drift detection (beyond parameter changes)
- Production hardening and horizontal scaling

---

**Maintained by:** UNITARES Development Team
**License:** See LICENSE file
**Repository:** governance-mcp-v1
