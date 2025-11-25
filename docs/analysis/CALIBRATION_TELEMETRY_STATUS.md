# Calibration & Telemetry Status

**Date:** 2025-11-25  
**Status:** ✅ Fully Functional

---

## 📊 Summary

**Calibration:** ✅ Working (was broken, now fixed)  
**Telemetry:** ✅ Working (was already functional)

---

## ✅ What Was Fixed

### 1. Missing MCP Tool: `update_calibration_ground_truth`
- **Problem:** Tool was documented but didn't exist
- **Fix:** Added tool definition and handler
- **Impact:** Can now provide ground truth for calibration

### 2. No Persistence for Calibration Data
- **Problem:** Calibration data was in-memory only (lost on restart)
- **Fix:** Added `save_state()` and `load_state()` methods
- **Impact:** Calibration data persists in `data/calibration_state.json`

---

## 🔧 How It Works Now

### Calibration Flow

```
1. process_agent_update() called
   ↓
2. record_prediction(confidence, predicted_correct, actual_correct=None)
   ↓
3. Prediction recorded in memory + saved to file
   ↓
4. ✅ update_calibration_ground_truth() tool available
   ↓
5. User provides ground truth via tool
   ↓
6. update_ground_truth() updates stats + saves to file
   ↓
7. check_calibration() shows accurate metrics
```

### Telemetry Flow (Unchanged)

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

## 📝 Usage Examples

### Check Calibration Status

```python
# MCP tool call
check_calibration()

# Returns:
{
  "success": true,
  "is_calibrated": false,
  "metrics": {
    "is_calibrated": false,
    "issues": ["Bin 0.8-0.9: insufficient samples (5 < 10)"],
    "bins": {
      "0.8-0.9": {
        "count": 5,
        "accuracy": 0.80,
        "expected_accuracy": 0.85,
        "calibration_error": 0.05
      }
    }
  }
}
```

### Update Ground Truth

```python
# MCP tool call
update_calibration_ground_truth(
    confidence=0.85,
    predicted_correct=True,
    actual_correct=True  # From human review
)

# Returns:
{
  "success": true,
  "message": "Ground truth updated successfully",
  "pending_updates": 12
}
```

### Get Telemetry Metrics

```python
# MCP tool call
get_telemetry_metrics(agent_id="my_agent", window_hours=24)

# Returns:
{
  "success": true,
  "skip_rate_metrics": {
    "total_skips": 15,
    "total_updates": 100,
    "skip_rate": 0.15
  },
  "confidence_distribution": {
    "mean": 0.75,
    "low_confidence_rate": 0.30,
    "high_confidence_rate": 0.70
  },
  "calibration": {
    "is_calibrated": false,
    "issues": [...]
  },
  "suspicious_patterns": [...]
}
```

---

## 📁 Files Modified

1. **`src/mcp_server_std.py`**
   - Added `update_calibration_ground_truth` tool definition
   - Added tool handler
   - Added to admin tools list

2. **`src/calibration.py`**
   - Added `state_file` parameter to `__init__()`
   - Added `save_state()` method
   - Added `load_state()` method
   - Auto-saves after updates

3. **`data/calibration_state.json`** (created on first use)
   - Stores calibration bin statistics
   - Persists across MCP server restarts

---

## 🎯 Key Features

### Calibration
- ✅ Records predictions with confidence levels
- ✅ Bins predictions by confidence (5 bins: 0.0-0.5, 0.5-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0)
- ✅ Tracks predicted vs actual correctness
- ✅ Detects miscalibration (large calibration error > 0.2)
- ✅ Persists data across restarts
- ✅ Can update ground truth after human review

### Telemetry
- ✅ Skip rate metrics (from audit log)
- ✅ Confidence distribution statistics
- ✅ Suspicious pattern detection:
  - Low skip rate + low confidence = agreeableness
  - High skip rate + high confidence = over-conservatism
- ✅ Calibration status included in telemetry

---

## 🔍 Monitoring Health

**Use `get_telemetry_metrics()` to monitor:**
1. **Skip rates** - Are we skipping too many/few updates?
2. **Confidence distribution** - Are we over/under-confident?
3. **Calibration** - Do confidence estimates match reality?
4. **Suspicious patterns** - Are we being too agreeable or conservative?

---

## 📊 Calibration Bins

| Bin Range | Confidence Level | Expected Accuracy |
|-----------|------------------|-------------------|
| 0.0 - 0.5 | Low | ~25% |
| 0.5 - 0.7 | Medium-low | ~60% |
| 0.7 - 0.8 | Medium-high | ~75% |
| 0.8 - 0.9 | High | ~85% |
| 0.9 - 1.0 | Very high | ~95% |

**Calibration Error:** |actual_accuracy - expected_accuracy|  
**Miscalibrated if:** error > 0.2 OR (high confidence bin but accuracy < 0.7)

---

## ✅ Status: Ready for Production

Both calibration and telemetry are now fully functional and ready for use!

