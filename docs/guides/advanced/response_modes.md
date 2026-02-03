# Response Modes (v2 API)

## Overview

The `process_agent_update` tool now supports multiple response modes to reduce cognitive load and improve usability. Instead of always returning a wall of metrics, you can choose the level of detail you need.

## Available Modes

### `auto` (Recommended - Adaptive verbosity)
Automatically adjusts response detail based on health status.

**When to use:** Set-and-forget mode that gives you the right level of detail when you need it.

**Adaptive Logic:**
- `healthy` → Returns `compact` mode (minimal detail, low cognitive load)
- `moderate` → Returns `standard` mode (human-readable interpretation)
- `at_risk` / `critical` → Returns `full` mode (all diagnostics for debugging)

**Example Request:**
```json
{
  "tool": "process_agent_update",
  "arguments": {
    "agent_id": "my_agent",
    "response_text": "Implemented new feature X",
    "response_mode": "auto"
  }
}
```

**Example Response (when healthy):**
```json
{
  "success": true,
  "agent_id": "my_agent",
  "status": "approved",
  "health_status": "healthy",
  "decision": {
    "action": "proceed",
    "reason": "...",
    "require_human": false
  },
  "metrics": {
    "E": 0.71,
    "I": 0.83,
    "coherence": 0.64,
    "risk_score": 0.22
  },
  "summary": "proceed | health=healthy | coherence=0.64 | risk_score=0.22",
  "_mode": "compact",
  "_resolved_from": "auto"
}
```

**Example Response (when at_risk):**
```json
{
  "success": true,
  "agent_id": "my_agent",
  "status": "paused",
  "decision": {...},
  "metrics": {...},
  "history": {...},
  "sampling_params": {...},
  "calibration": {...},
  "learning_context": {...},
  "_mode": "full",
  "_resolved_from": "auto"
}
```

---

### `standard` (Recommended for most users)
Human-readable interpretation with actionable guidance.

**When to use:** Daily development work, when you want clear feedback without metric overload.

**Example Request:**
```json
{
  "tool": "process_agent_update",
  "arguments": {
    "agent_id": "my_agent",
    "response_text": "Implemented new feature X",
    "response_mode": "standard"
  }
}
```

**Example Response:**
```json
{
  "success": true,
  "agent_id": "my_agent",
  "decision": "proceed",
  "state": {
    "health": "healthy",
    "basin": "high",
    "mode": "building_alone",
    "trajectory": "stable",
    "guidance": null,
    "borderline": null
  },
  "metrics": {
    "E": 0.71,
    "I": 0.83,
    "S": 0.17,
    "V": -0.009,
    "coherence": 0.64,
    "risk_score": 0.22
  },
  "sampling_params": {...},
  "_mode": "standard",
  "_raw_available": "Use response_mode='full' to see complete metrics"
}
```

**State Fields Explained:**
- `health`: Overall system health (`healthy`, `moderate`, `at_risk`, `critical`)
- `basin`: Which attractor basin (`high`, `low`, `transitional`)
- `mode`: Operational pattern:
  - `building_alone` - High E, high I, low S (productive solo work)
  - `collaborating` - High E, high I, high S (team exploration + building)
  - `exploring_alone` - High E, low I, low S (learning/research solo)
  - `executing_alone` - Low E, high I, low S (implementing known solution)
  - `exploring_together` - High E, low I, high S (collaborative exploration)
  - `executing_together` - Low E, high I, high S (team implementation)
  - `drifting_together` - Low E, low I, high S (unproductive social)
  - `stalled` - Low E, low I, low S (blocked or inactive)
- `trajectory`: What's changing (`stable`, `improving`, `declining`, `stuck`)
- `guidance`: Actionable suggestion or `null` if none needed
- `borderline`: Metrics near threshold (hysteresis tracking)

---

### `compact` / `minimal` / `lite`
Essential metrics only, minimal token usage.

**When to use:** High-frequency updates, token-constrained environments, or when you only care about decision + summary.

**Example Response:**
```json
{
  "success": true,
  "agent_id": "my_agent",
  "status": "approved",
  "health_status": "healthy",
  "decision": {
    "action": "proceed",
    "reason": "...",
    "require_human": false
  },
  "metrics": {
    "E": 0.71,
    "I": 0.83,
    "S": 0.17,
    "V": -0.009,
    "coherence": 0.64,
    "risk_score": 0.22,
    "phi": 0.45,
    "verdict": "continue",
    "lambda1": 0.52
  },
  "sampling_params": {...},
  "summary": "proceed | health=healthy | coherence=0.64 | risk_score=0.22",
  "_mode": "compact"
}
```

---

### `full` (Default - backward compatible)
Complete metrics, history, diagnostics, and all internal state.

**When to use:** Debugging, analysis, research, or when you need complete context.

**Example Response:**
```json
{
  "success": true,
  "agent_id": "my_agent",
  "status": "approved",
  "decision": {
    "action": "proceed",
    "reason": "...",
    "require_human": false,
    "confidence": 0.95,
    "risk_score": 0.22
  },
  "metrics": {
    "E": 0.71,
    "I": 0.83,
    "S": 0.17,
    "V": -0.009,
    "coherence": 0.64,
    "lambda1": 0.52,
    "phi": 0.45,
    "void_active": false,
    "regime": "CONVERGENCE",
    "risk_score": 0.22,
    "verdict": "continue",
    "health_status": "healthy"
  },
  "history": {
    "E_history": [...],
    "I_history": [...],
    "decision_history": [...],
    ...
  },
  "sampling_params": {...},
  "calibration": {...},
  "learning_context": {...}
}
```

---

## Configuration

### Per-Call Override
```json
{
  "tool": "process_agent_update",
  "arguments": {
    "agent_id": "my_agent",
    "response_mode": "standard"  // <-- Override
  }
}
```

### Environment Variable
```bash
export UNITARES_PROCESS_UPDATE_RESPONSE_MODE=standard
```

This sets the default for all calls that don't specify `response_mode`.

---

## Migration Guide

### From Full → Standard

**Before:**
You had to parse this yourself:
```json
{
  "metrics": {
    "E": 0.71,
    "I": 0.83,
    "S": 0.17,
    "V": -0.009,
    "coherence": 0.64,
    "risk_score": 0.22,
    ...
  }
}
```

**After:**
You get interpreted state:
```json
{
  "state": {
    "health": "healthy",
    "mode": "building_alone",
    "guidance": null
  }
}
```

### Backward Compatibility

- `response_mode` defaults to `"full"` - **no breaking changes**
- All existing code continues to work as before
- Opt-in to `standard` or `compact` when ready

---

## Guidance Examples

When `guidance` is present, it provides actionable suggestions:

```json
{
  "guidance": "Low S + High I = might benefit from dialectic to sanity-check approach."
}
```

```json
{
  "guidance": "Value trajectory negative. Simplify approach or seek input."
}
```

```json
{
  "guidance": "E=0.48 (borderline). Pattern may be shifting to executing_alone."
}
```

```json
{
  "guidance": null  // Healthy state, no action needed
}
```

---

## Decision Matrix

| Use Case | Recommended Mode |
|----------|------------------|
| **Default / Set-and-forget** | `auto` |
| Daily development | `standard` or `auto` |
| High-frequency monitoring | `compact` |
| Debugging/analysis | `full` |
| Token-constrained LLM | `compact` or `auto` |
| First-time user | `auto` |
| Research/paper | `full` |

---

## Technical Details

### Hysteresis

The interpretation layer includes hysteresis to prevent mode flapping. If you're in `building_alone` mode with E=0.52, the threshold to flip to `executing_alone` is E=0.45 (not 0.50). This prevents oscillation near boundaries.

Borderline values are tracked in the `borderline` field:

```json
{
  "borderline": {
    "E": {
      "value": 0.48,
      "threshold": 0.5,
      "status": "low",
      "note": "Near threshold (0.5±0.10)"
    }
  }
}
```

### Performance

- `standard`: ~5% slower than `full` (negligible - adds interpretation layer)
- `compact`: ~10% faster than `full` (strips unused fields)
- `full`: Baseline

All modes use the same governance engine - only response formatting differs.

---

## Examples in Context

### Scenario 1: Agent exploring codebase

**Response (standard mode):**
```json
{
  "decision": "proceed",
  "state": {
    "health": "healthy",
    "mode": "exploring_alone",
    "guidance": "High exploration, low integration. Consider consolidating findings."
  }
}
```

### Scenario 2: Agent stuck in loop

**Response (standard mode):**
```json
{
  "decision": "pause",
  "state": {
    "health": "at_risk",
    "mode": "stalled",
    "trajectory": "stuck",
    "guidance": "Multiple pauses detected. Try a different approach or request dialectic."
  }
}
```

### Scenario 3: Healthy productive work

**Response (standard mode):**
```json
{
  "decision": "proceed",
  "state": {
    "health": "healthy",
    "basin": "high",
    "mode": "building_alone",
    "trajectory": "stable",
    "guidance": null
  }
}
```

---

## Next Steps

1. Try `response_mode="standard"` in your next `process_agent_update` call
2. Compare output to `"full"` mode to see the difference
3. Set `UNITARES_PROCESS_UPDATE_RESPONSE_MODE=standard` to make it default
4. Give feedback on what works / what doesn't

---

**Implementation Status:** ✅ Live as of 2025-12-17
**Backward Compatible:** Yes (defaults to `"full"`)
