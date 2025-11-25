# Confidence Gating & Calibration System

**Date:** 2025-11-24  
**Status:** ✅ Implemented

## Overview

Comprehensive confidence gating, calibration checking, audit logging, and hold-out validation framework to prevent agreeableness and ensure governance reliability.

---

## 1. Conservative Defaults + Gating ✅

### Lambda1 Updates
- **Gating:** Skip λ₁ updates when `confidence < 0.8`
- **Threshold:** `CONTROLLER_CONFIDENCE_THRESHOLD = 0.8`
- **Behavior:** Conservative - only update controller when confident

### Auto-Attestation Gating
- **Requirement:** `CI pass + confidence ≥ 0.8`
- **Behavior:** Only auto-approve when both conditions met
- **Prevents:** Agreeableness (auto-approving everything)

**Implementation:**
```python
# In process_update()
if decision['action'] == 'approve' and not decision.get('require_human', False):
    auto_attest_allowed = ci_passed and confidence >= 0.8
    if not auto_attest_allowed:
        decision['action'] = 'revise'  # Escalate to human review
        decision['require_human'] = True
```

---

## 2. Calibration Checks ✅

### System: `src/calibration.py`

**Bins predictions by confidence and measures real accuracy:**

- **Bins:**
  - [0.0, 0.5]: Low confidence
  - [0.5, 0.7]: Medium-low confidence
  - [0.7, 0.8]: Medium-high confidence
  - [0.8, 0.9]: High confidence
  - [0.9, 1.0]: Very high confidence

**Calibration Detection:**
- If 0.8→0.9 bin is only 50% accurate → **miscalibrated**
- Large calibration error (>0.2) → **needs rework**

**Usage:**
```python
from src.calibration import calibration_checker

# Record predictions
calibration_checker.record_prediction(
    confidence=0.85,
    predicted_correct=True,
    actual_correct=True  # From ground truth
)

# Check calibration
is_calibrated, metrics = calibration_checker.check_calibration()
```

**MCP Tool:** `check_calibration`

---

## 3. Audit Log & Skip Telemetry ✅

### System: `src/audit_log.py`

**Records:**
- Every skipped λ₁ update (with confidence, threshold, reason)
- Every auto-attestation (with CI status, risk, decision)
- Calibration check results

**Format:** JSONL (one entry per line)

**Location:** `data/audit_log.jsonl`

**Metrics:**
- Skip rate (skips / total updates)
- Average confidence
- Suspicious pattern detection:
  - Low skip rate + low confidence = **agreeableness**
  - High skip rate + high confidence = **over-conservatism**

**MCP Tool:** `get_telemetry_metrics`

**Example:**
```json
{
  "skip_rate": {
    "total_skips": 15,
    "total_updates": 100,
    "skip_rate": 0.15,
    "avg_confidence": 0.75,
    "suspicious": true
  },
  "confidence_distribution": {
    "mean": 0.75,
    "low_confidence_rate": 0.30,
    "high_confidence_rate": 0.70
  },
  "suspicious_patterns": [
    {
      "pattern": "low_skip_low_confidence",
      "severity": "high",
      "description": "Low skip rate but low average confidence suggests agreeableness"
    }
  ]
}
```

---

## 4. Hold-Out Validation ✅

### System: `src/holdout_validation.py`

**Purpose:** Reserve repos/agents as blind test sets (never tune on them)

**Features:**
- Add/remove agents from hold-out set
- Add/remove repos from hold-out set
- Enable/disable hold-out validation
- Get statistics

**Location:** `data/holdout_config.json`

**MCP Tool:** `manage_holdout_validation`

**Usage:**
```python
from src.holdout_validation import holdout_validator

# Add agent to hold-out set
holdout_validator.add_holdout_agent("test_agent_holdout")

# Check if agent is hold-out
if holdout_validator.is_holdout_agent(agent_id):
    # Don't tune on this agent
    pass
```

---

## 5. Integration Points

### `process_agent_update` Tool
- **New parameter:** `ci_passed` (boolean, default: False)
- **Behavior:** Gates auto-attestation

### `governance_monitor.py`
- **Audit logging:** Every skip and auto-attestation
- **Calibration recording:** Every prediction
- **Auto-attestation gating:** CI + confidence check

---

## 6. New MCP Tools

1. **`get_telemetry_metrics`**
   - Skip rates, confidence distributions
   - Suspicious pattern detection
   - Calibration status

2. **`check_calibration`**
   - Bin-by-bin accuracy analysis
   - Miscalibration detection
   - Calibration error metrics

3. **`manage_holdout_validation`**
   - Add/remove hold-out agents/repos
   - Enable/disable validation
   - Get statistics

---

## 7. Configuration

### Confidence Thresholds
```python
CONTROLLER_CONFIDENCE_THRESHOLD = 0.8  # Gate lambda1 updates
AUTO_ATTEST_CONFIDENCE_THRESHOLD = 0.8  # Gate auto-attestation
```

### Calibration Bins
- Default: 5 bins (0.0-0.5, 0.5-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0)
- Configurable via `CalibrationChecker(bins=...)`

---

## 8. Suspicious Pattern Detection

**Pattern 1: Low Skip Rate + Low Confidence**
- **Indicates:** Agreeableness (auto-approving everything)
- **Severity:** High
- **Threshold:** skip_rate < 0.1 AND avg_confidence < 0.7

**Pattern 2: High Skip Rate + High Confidence**
- **Indicates:** Over-conservatism
- **Severity:** Medium
- **Threshold:** skip_rate > 0.5 AND avg_confidence > 0.85

---

## 9. Files Created

1. **`src/audit_log.py`** - Audit logging infrastructure
2. **`src/calibration.py`** - Calibration checking system
3. **`src/telemetry.py`** - Telemetry and metrics collection
4. **`src/holdout_validation.py`** - Hold-out validation framework

---

## 10. Usage Examples

### Check Telemetry
```python
# Get system-wide metrics
get_telemetry_metrics()

# Get agent-specific metrics
get_telemetry_metrics(agent_id="my_agent")
```

### Check Calibration
```python
# Run calibration check
check_calibration(min_samples_per_bin=10)
```

### Manage Hold-Out Sets
```python
# Add agent to hold-out
manage_holdout_validation(action="add_agent", agent_id="test_agent")

# Enable hold-out validation
manage_holdout_validation(action="enable")
```

---

## 11. Benefits

✅ **Prevents agreeableness** - Auto-attestation gating  
✅ **Detects miscalibration** - Bin-by-bin accuracy analysis  
✅ **Full audit trail** - Every skip and attestation logged  
✅ **Suspicious pattern detection** - Automated anomaly detection  
✅ **Hold-out validation** - Blind test sets for reliability  

---

**Status:** ✅ All features implemented and tested

