# Tool Consolidation Audit - 2026-02-04

**Current state:** 89 registered tools (too many!)
**Target:** ~25-30 tools (unified + essential)

## Analysis by Category

### ✅ Already Consolidated (Keep as-is)
| Unified Tool | Replaces | Status |
|--------------|----------|--------|
| `agent` | list_agents, get_agent_metadata, update_agent_metadata, archive_agent, delete_agent | ✅ Done |
| `knowledge` | store_knowledge_graph, search_knowledge_graph, get_knowledge_graph, list_knowledge_graph, update_discovery_status_graph, get_discovery_details, leave_note, cleanup_knowledge_graph, get_lifecycle_stats | ✅ Done |
| `calibration` | check_calibration, update_calibration_ground_truth, backfill_calibration_from_dialectic, rebuild_calibration | ✅ Done |
| `cirs_protocol` | void_alert, state_announce, coherence_report, boundary_contract, governance_action | ✅ Done |
| `self_recovery` | check_recovery_options, quick_resume | ✅ Done |

### 🔴 Redundant Tools (Should Hide/Deprecate)

**Agent Lifecycle (5 redundant):**
- `list_agents` → use `agent(action='list')`
- `get_agent_metadata` → use `agent(action='get')`
- `update_agent_metadata` → use `agent(action='update')`
- `archive_agent` → use `agent(action='archive')`
- `delete_agent` → use `agent(action='delete')`

**Calibration (4 redundant):**
- `check_calibration` → use `calibration(action='check')`
- `update_calibration_ground_truth` → use `calibration(action='update')`
- `backfill_calibration_from_dialectic` → use `calibration(action='backfill')`
- `rebuild_calibration` → use `calibration(action='rebuild')`

**Knowledge Graph (8 redundant):**
- `store_knowledge_graph` → use `knowledge(action='store')`
- `search_knowledge_graph` → use `knowledge(action='search')` (but keep for discoverability)
- `get_knowledge_graph` → use `knowledge(action='get')`
- `list_knowledge_graph` → use `knowledge(action='list')`
- `update_discovery_status_graph` → use `knowledge(action='update')`
- `get_discovery_details` → use `knowledge(action='details')`
- `cleanup_knowledge_graph` → use `knowledge(action='cleanup')`
- `get_lifecycle_stats` → use `knowledge(action='stats')`

**Recovery (3 redundant):**
- `check_recovery_options` → use `self_recovery(action='check')`
- `quick_resume` → use `self_recovery(action='resume')`
- `direct_resume_if_safe` → DEPRECATED, remove

### 🟡 Needs New Consolidated Tool

**Pi Orchestration (12 tools → 1 `pi` tool):**
```
pi(action='health')      # pi_health
pi(action='context')     # pi_get_context
pi(action='sync_eisv')   # pi_sync_eisv
pi(action='display')     # pi_display
pi(action='say')         # pi_say
pi(action='message')     # pi_post_message
pi(action='qa')          # pi_lumen_qa
pi(action='query')       # pi_query
pi(action='workflow')    # pi_workflow
pi(action='git_pull')    # pi_git_pull
pi(action='power')       # pi_system_power
pi(action='tools')       # pi_list_tools
```

**Observability (5 tools → 1 `observe` tool):**
```
observe(action='agent')      # observe_agent
observe(action='compare')    # compare_agents
observe(action='similar')    # compare_me_to_similar
observe(action='anomalies')  # detect_anomalies
observe(action='aggregate')  # aggregate_metrics
```

**Dialectic (4 tools → 1 `dialectic` tool):**
```
dialectic(action='request')  # request_dialectic_review
dialectic(action='get')      # get_dialectic_session
dialectic(action='list')     # list_dialectic_sessions
dialectic(action='llm')      # llm_assisted_dialectic
```

**Config (2 tools → 1 `config` tool):**
```
config(action='get')  # get_thresholds
config(action='set')  # set_thresholds
```

**Export (2 tools → 1 `export` tool):**
```
export(action='history')  # get_system_history
export(action='file')     # export_to_file
```

**Trajectory (2 tools → fold into `identity`):**
```
identity(action='trajectory')  # get_trajectory_status
identity(action='verify')      # verify_trajectory_identity
```

### ✅ Essential Tools (Keep Standalone)

| Tool | Reason |
|------|--------|
| `onboard` | Portal tool - must be obvious |
| `identity` | Core identity - must be obvious |
| `process_agent_update` | Primary workflow tool |
| `get_governance_metrics` | Primary status tool |
| `list_tools` | Discovery - must be obvious |
| `describe_tool` | Discovery companion |
| `health_check` | System health - obvious name |
| `call_model` | LLM access - obvious name |
| `leave_note` | Quick notes - convenient shortcut |
| `search_knowledge_graph` | Common operation - keep for discoverability |

### 🟢 Specialized (Keep Hidden/Separate)

| Tool | Reason |
|------|--------|
| `archive_old_test_agents` | Batch admin operation |
| `archive_orphan_agents` | Batch admin operation |
| `detect_stuck_agents` | Specialized detection |
| `operator_resume_agent` | Operator-only |
| `simulate_update` | Testing tool |
| `get_telemetry_metrics` | Separate from calibration |
| `get_workspace_health` | Comprehensive health |
| `debug_request_context` | Debug tool |

---

## Proposed Target Tool Set (~30 tools)

### Tier 1: Essential (10 tools)
1. `onboard` - Portal
2. `identity` - Identity management
3. `process_agent_update` - Log work
4. `get_governance_metrics` - Check state
5. `agent` - Agent lifecycle
6. `knowledge` - Knowledge graph
7. `list_tools` - Discovery
8. `describe_tool` - Tool details
9. `health_check` - System health
10. `call_model` - LLM access

### Tier 2: Common (10 tools)
11. `search_knowledge_graph` - Direct search (alias to knowledge)
12. `leave_note` - Quick notes
13. `self_recovery` - Recovery
14. `pi` - Pi orchestration (NEW)
15. `observe` - Observability (NEW)
16. `dialectic` - Dialectic (NEW)
17. `calibration` - Calibration
18. `config` - Config (NEW)
19. `export` - Export (NEW)
20. `cirs_protocol` - Multi-agent coordination

### Tier 3: Admin/Specialized (10 tools)
21. `simulate_update` - Testing
22. `detect_stuck_agents` - Detection
23. `archive_old_test_agents` - Batch cleanup
24. `archive_orphan_agents` - Batch cleanup
25. `operator_resume_agent` - Operator
26. `get_telemetry_metrics` - Telemetry
27. `get_workspace_health` - Workspace health
28. `debug_request_context` - Debug
29. `get_roi_metrics` - ROI tracking
30. `validate_file_path` - Anti-proliferation

---

## Implementation Plan

### Phase 1: Create New Consolidated Tools
1. Create `pi` tool (consolidate 12 pi_* tools)
2. Create `observe` tool (consolidate 5 observability tools)
3. Create `dialectic` tool (consolidate 4 dialectic tools)
4. Create `config` tool (consolidate 2 threshold tools)
5. Create `export` tool (consolidate 2 export tools)

### Phase 2: Hide Redundant Individual Tools
1. Add `hidden=True` to all redundant tools covered by consolidated versions
2. Keep handlers functional for backward compatibility
3. Update tool_stability.py with aliases

### Phase 3: Update Documentation
1. Update START_HERE.md with new tool names
2. Update GETTING_STARTED_SIMPLE.md
3. Update list_tools output to show consolidated tools first

---

## Summary

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Total registered | 89 | 90 | +1 (consolidated tools) |
| **Visible in lite mode** | 50+ | **18** | **64%** |
| Cognitive load | High | **Low** | ✅ |

## Implementation Complete ✅

**New consolidated tools created:**
- `pi` - 12 Pi tools → 1
- `observe` - 5 observability tools → 1
- `dialectic` - 4 dialectic tools → 1
- `config` - 2 config tools → 1
- `export` - 2 export tools → 1

**Previously consolidated (already working):**
- `agent` - 5 agent lifecycle tools → 1
- `knowledge` - 9 knowledge graph tools → 1
- `calibration` - 4 calibration tools → 1

**Total: 43 individual tools → 8 consolidated tools**

**Hidden tools:** 35+ individual tools now have `hidden=True`
- Still functional for backward compatibility
- Not shown in `list_tools` by default
