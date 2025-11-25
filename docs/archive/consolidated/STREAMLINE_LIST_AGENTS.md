# Streamline `list_agents` Tool - Proposal

## Problem

The current `list_agents` tool returns inconsistent structures:
- **Loaded agents:** Full metrics, health status, monitor timestamps
- **Unloaded agents:** No metrics, "unknown" health, metadata timestamps  
- **Error cases:** Different error fields
- **Notes:** Only present if non-empty (inconsistent)

This makes it hard to:
- Parse programmatically
- Display consistently
- Compare agents
- Understand agent state at a glance

## Proposed Solution

### Standardized Agent Object Structure

Every agent should have the **same core fields**, with consistent null/empty defaults:

```json
{
  "agent_id": "string",
  "lifecycle_status": "active|paused|archived|deleted",
  "health_status": "healthy|degraded|critical|unknown|error",
  "summary": {
    "updates": 17,
    "last_activity": "2025-11-23T17:13:45",
    "age_days": 3,
    "primary_tags": ["process-management", "zombie-cleanup"]
  },
  "metrics": {
    "risk_score": 27.48,
    "coherence": 0.589,
    "void_active": false,
    "E": 0.757,
    "I": 0.937,
    "S": 0.047,
    "V": -0.044
  } | null,
  "metadata": {
    "created": "2025-11-20T01:19:25",
    "last_update": "2025-11-23T17:13:45",
    "version": "v1.0",
    "total_updates": 17,
    "tags": ["process-management", "zombie-cleanup"],
    "notes_preview": "Process management implementation session..." // First 100 chars
  },
  "state": {
    "loaded_in_process": true|false,
    "metrics_available": true|false,
    "error": null | "error message"
  }
}
```

### Key Improvements

1. **Always-present fields:** Every agent has same structure
2. **Standardized summary:** Quick scan fields (updates, age, tags)
3. **Consistent nulls:** Metrics null if unavailable (not missing)
4. **Notes preview:** First 100 chars instead of full notes
5. **State indicator:** Clear loaded/unloaded/error state

### Grouped Output Format

```json
{
  "success": true,
  "summary": {
    "total": 25,
    "by_status": {
      "active": 17,
      "archived": 6,
      "paused": 1,
      "deleted": 1
    },
    "by_health": {
      "healthy": 12,
      "degraded": 3,
      "critical": 2,
      "unknown": 8
    },
    "loaded_count": 5
  },
  "agents": {
    "active": [...],
    "archived": [...],
    "paused": [...],
    "deleted": [...]
  }
}
```

### Benefits

1. **Consistent parsing:** Same structure for all agents
2. **Easy filtering:** Group by status/health
3. **Quick scanning:** Summary fields show key info
4. **Clear state:** Know if metrics are available
5. **Better UX:** Grouped by status for readability

## Implementation Plan

1. Create `AgentSummary` dataclass for consistent structure
2. Add helper function to generate standardized agent info
3. Update `list_agents` to use standardized format
4. Add grouping by status option
5. Add notes preview truncation
6. Ensure all fields always present (null if unavailable)

## Example Output

```json
{
  "success": true,
  "summary": {
    "total": 17,
    "by_status": {"active": 17},
    "by_health": {"healthy": 5, "degraded": 8, "critical": 4},
    "loaded_count": 3
  },
  "agents": {
    "active": [
      {
        "agent_id": "cursor_process_management_20251120",
        "lifecycle_status": "active",
        "health_status": "degraded",
        "summary": {
          "updates": 17,
          "last_activity": "2025-11-23T17:13:45",
          "age_days": 3,
          "primary_tags": ["process-management", "zombie-cleanup"]
        },
        "metrics": {
          "risk_score": 27.48,
          "coherence": 0.589,
          "void_active": false,
          "E": 0.757,
          "I": 0.937,
          "S": 0.047,
          "V": -0.044
        },
        "metadata": {
          "created": "2025-11-20T01:19:25",
          "last_update": "2025-11-23T17:13:45",
          "version": "v1.0",
          "total_updates": 17,
          "tags": ["process-management", "zombie-cleanup", "governance-testing"],
          "notes_preview": "Process management implementation session. Demonstrated coherence collapse and recovery..."
        },
        "state": {
          "loaded_in_process": true,
          "metrics_available": true,
          "error": null
        }
      }
    ]
  }
}
```

## Backward Compatibility

- Keep existing parameters (`summary_only`, `status_filter`, etc.)
- Add new optional parameter `grouped=true` for grouped output
- Add new optional parameter `standardized=true` for standardized format
- Default to standardized format for new calls

