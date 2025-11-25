# Track() Implementation - Required Fixes

**Date:** 2025-11-23  
**Status:** Pre-implementation review fixes

## Critical Fixes Needed

### 1. PI Controller Gating Location

**Issue:** ChatGPT's gating logic assumes risk-based update, but actual code uses `suggest_theta_update()`.

**Fix:** Gate at call site in `process_update()`, not inside `update_lambda1()`:

```python
# In governance_monitor.py, process_update() method (around line 506):
if self.state.update_count % 10 == 0:
    confidence = getattr(self, 'current_confidence', 1.0)
    if confidence >= config.CONTROLLER_CONFIDENCE_THRESHOLD:
        self.update_lambda1()
    else:
        logger.warning("[UNITARES] Skipping λ1 update: confidence %.2f < threshold %.2f", 
                       confidence, config.CONTROLLER_CONFIDENCE_THRESHOLD)
        # Track skip metrics
        if not hasattr(self.state, 'lambda1_update_skips'):
            self.state.lambda1_update_skips = 0
        self.state.lambda1_update_skips += 1
```

**Add to config:**
```python
# In governance_config.py
CONTROLLER_CONFIDENCE_THRESHOLD = 0.8  # Gate PI controller updates
```

### 2. Confidence Flow Through process_update()

**Issue:** `process_update()` doesn't accept confidence parameter.

**Fix:** Store confidence as instance variable before calling:

```python
# In mcp_server_std.py track() endpoint:
monitor.current_confidence = tracking_metadata.get('confidence', 1.0)
result = monitor.process_update(agent_state)
```

### 3. Preserve timestamp in TrackResponse

**Fix:** TrackResponse should preserve `timestamp` from governance_result:

```python
class TrackResponse:
    def __init__(self, governance_result: Dict[str, Any], tracking_metadata: Dict[str, Any]):
        # ... existing fields ...
        self.timestamp = governance_result.get("timestamp") or tracking_metadata.get("timestamp", time.time())
```

### 4. Enhanced infer_eisv_from_artifacts()

**Fix:** Add basic confidence formula (not just binary):

```python
def infer_eisv_from_artifacts(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    test_parity = float(artifacts.get("test_parity", 0.0))
    files_changed = len(artifacts.get("files_changed", []))
    commits = len(artifacts.get("commits", []))
    diff_size = int(artifacts.get("diff_size", 0))
    
    # Basic confidence: requires multiple signals
    artifact_coverage = min(1.0, (commits + files_changed) / 4.0)
    test_signal = test_parity
    completeness = min(1.0, artifact_coverage * 0.6 + test_signal * 0.4)
    
    confidence = completeness if (commits > 0 or files_changed > 0) else 0.3
    
    eisv = {
        "E": 0.5,
        "I": 0.9 if test_parity == 1.0 else 0.6,
        "S": 0.1 if test_parity == 1.0 else 0.4,
        "V": 0.0,
        "coherence": 0.85 if test_parity == 1.0 else 0.6,
        "confidence": confidence,
        "source": "artifact_analysis"
    }
    return eisv
```

### 5. Add EISV Validation

**Fix:** Validate EISV values are in expected ranges:

```python
def eisv_to_parameters(eisv: Dict[str, Any]) -> np.ndarray:
    # Validate and clip to expected ranges
    E = float(np.clip(eisv.get("E", 0.5), 0.0, 1.0))
    I = float(np.clip(eisv.get("I", 0.8), 0.0, 1.0))
    S = float(np.clip(eisv.get("S", 0.2), 0.0, 2.0))
    V = float(np.clip(eisv.get("V", 0.0), -2.0, 2.0))
    coherence = float(np.clip(eisv.get("coherence", 0.7), 0.0, 1.0))
    # ... rest of function
```

### 6. Document Parameter Mapping

**Fix:** Add docstring explaining parameter vector mapping:

```python
def eisv_to_parameters(eisv: Dict[str, Any]) -> np.ndarray:
    """
    Map EISV state to 128-dim parameter vector.
    
    Mapping (documented for auditability):
    - params[0] = E (Energy) [0, 1]
    - params[1] = S (Entropy) [0, 2]
    - params[2] = I (Information Integrity) [0, 1]
    - params[3] = coherence [0, 1]
    - params[4] = reserved
    - params[5] = |V| (Void magnitude) [0, 2]
    - params[126] = confidence [0, 1]
    - params[127] = 1 - confidence [0, 1]
    - All other params = 0.0 (unused dimensions)
    
    This mapping preserves EISV provenance while fitting into
    the existing 128-dim parameter vector structure.
    """
```

## Implementation Order

1. ✅ Add `CONTROLLER_CONFIDENCE_THRESHOLD` to config
2. ✅ Fix PI controller gating location (call site, not method)
3. ✅ Add confidence flow (instance variable)
4. ✅ Fix TrackResponse timestamp preservation
5. ✅ Enhance `infer_eisv_from_artifacts()` confidence
6. ✅ Add EISV validation
7. ✅ Document parameter mapping

## Testing Checklist

- [ ] Unit test: `update_lambda1()` skipped when confidence < threshold
- [ ] Unit test: `update_lambda1()` runs when confidence >= threshold
- [ ] Unit test: `normalize_track_to_agent_state()` with explicit EISV
- [ ] Unit test: `normalize_track_to_agent_state()` with artifacts
- [ ] Unit test: `normalize_track_to_agent_state()` summary-only
- [ ] Integration test: `track()` → `process_update()` → `TrackResponse` preserves all fields
- [ ] Integration test: Confidence flows through to PI controller gating

