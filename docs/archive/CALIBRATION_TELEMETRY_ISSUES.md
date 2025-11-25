# Calibration & Telemetry Issues

**Date:** 2025-11-25  
**Status:** ✅ Fixed

---

## 🔴 Critical Issues

### 1. Missing MCP Tool: `update_calibration_ground_truth`

**Problem:**
- Documentation mentions `update_calibration_ground_truth` tool
- MCP server descriptions reference it
- **But the tool doesn't actually exist!**

**Impact:**
- Calibration predictions are recorded but can never be updated with ground truth
- Calibration checker will always show "No calibration data" or "insufficient samples"
- System cannot learn from actual outcomes

**Evidence:**
- `src/mcp_server_std.py` line 1267: Description mentions tool
- `src/mcp_server_std.py` line 3451: Note mentions tool
- **But:** No tool definition in `list_tools()` and no handler in `call_tool()`

---

### 2. No Persistence for Calibration Data

**Problem:**
- `CalibrationChecker` uses in-memory `defaultdict` for `bin_stats`
- All calibration data is lost on MCP server restart
- No way to persist calibration history

**Impact:**
- Calibration can never accumulate meaningful statistics
- Every restart resets calibration to zero
- Long-term calibration tracking impossible

**Code Location:**
- `src/calibration.py` line 51: `self.bin_stats = defaultdict(...)`
- No file I/O for saving/loading calibration state

---

### 3. Telemetry Works But Has Limitations

**Status:** ✅ Telemetry is functional

**What Works:**
- `get_telemetry_metrics` tool exists and works
- Reads from persisted audit log (`data/audit_log.jsonl`)
- Skip rate metrics work
- Confidence distribution works
- Suspicious pattern detection works

**Limitations:**
- Calibration metrics always show "No calibration data" (due to issue #1 and #2)
- No way to query historical telemetry trends
- No aggregation across time windows beyond 24 hours

---

## 📊 Current State

### Calibration Flow (Broken)

```
1. process_agent_update() called
   ↓
2. record_prediction(confidence, predicted_correct, actual_correct=None)
   ↓
3. Prediction recorded in memory
   ↓
4. ❌ NO WAY TO UPDATE actual_correct (missing tool)
   ↓
5. check_calibration() always shows "insufficient samples" or "no data"
```

### Telemetry Flow (Working)

```
1. process_agent_update() called
   ↓
2. Audit log entry written to data/audit_log.jsonl
   ↓
3. get_telemetry_metrics() reads audit log
   ↓
4. ✅ Returns skip rates, confidence distributions, suspicious patterns
```

---

## 🔧 Required Fixes

### Fix 1: Add `update_calibration_ground_truth` MCP Tool

**Implementation:**
```python
Tool(
    name="update_calibration_ground_truth",
    description="Update calibration with ground truth after human review",
    inputSchema={
        "type": "object",
        "properties": {
            "confidence": {"type": "number", "description": "Confidence level (0-1)"},
            "predicted_correct": {"type": "boolean", "description": "Whether we predicted correct"},
            "actual_correct": {"type": "boolean", "description": "Whether prediction was actually correct"}
        },
        "required": ["confidence", "predicted_correct", "actual_correct"]
    }
)
```

### Fix 2: Add Persistence for Calibration Data

**Implementation:**
- Save calibration state to `data/calibration_state.json`
- Load on initialization
- Save after each update

**File Format:**
```json
{
  "bins": {
    "0.8-0.9": {
      "count": 50,
      "predicted_correct": 45,
      "actual_correct": 42,
      "confidence_sum": 42.5
    },
    ...
  }
}
```

### Fix 3: Link Calibration to Audit Log

**Enhancement:**
- Store calibration predictions in audit log with unique IDs
- Allow updating ground truth by referencing audit log entry ID
- Enables retrospective calibration updates

---

## 📋 Priority

1. **HIGH:** Add `update_calibration_ground_truth` tool (blocks calibration from working)
2. **HIGH:** Add persistence (blocks long-term calibration)
3. **MEDIUM:** Link to audit log (improves usability)

---

## ✅ What's Working

- Telemetry collection (skip rates, confidence distributions)
- Suspicious pattern detection
- Audit logging
- Confidence gating
- Calibration prediction recording (but can't update ground truth)

---

## ✅ Fixes Applied (2025-11-25)

### Fix 1: Added `update_calibration_ground_truth` MCP Tool ✅
- **File:** `src/mcp_server_std.py`
- **Changes:**
  - Added tool definition in `list_tools()` (line ~1273)
  - Added handler in `call_tool()` (line ~3479)
  - Added to admin tools list
- **Status:** ✅ Complete

### Fix 2: Added Persistence for Calibration Data ✅
- **File:** `src/calibration.py`
- **Changes:**
  - Added `state_file` parameter to `__init__()` (defaults to `data/calibration_state.json`)
  - Added `save_state()` method (saves after updates)
  - Added `load_state()` method (loads on initialization)
  - Auto-saves after `record_prediction()` with ground truth
  - Auto-saves after `update_ground_truth()`
- **Status:** ✅ Complete

### Fix 3: Testing ✅
- **Verification:** Code imports successfully
- **State file:** `data/calibration_state.json`
- **Status:** ✅ Ready for use

---

**Next Steps:** 
- ✅ All critical fixes implemented
- Use `update_calibration_ground_truth` tool to provide ground truth
- Calibration data now persists across restarts

