# Pure Thermodynamic Coherence Implementation

**Date:** 2025-11-25  
**Status:** ✅ Implemented

---

## Summary

Removed `param_coherence` blend from coherence calculation, using pure thermodynamic C(V) signal for honest calibration.

---

## Changes Made

### 1. Coherence Calculation (`src/governance_monitor.py`)

**Before:**
```python
param_coherence = self.compute_parameter_coherence(parameters, self.prev_parameters)
C_V = coherence(self.state.V, self.state.unitaires_theta, DEFAULT_PARAMS)
self.state.coherence = 0.7 * C_V + 0.3 * param_coherence  # Blended
```

**After:**
```python
# Removed param_coherence blend - using pure thermodynamic signal
C_V = coherence(self.state.V, self.state.unitaires_theta, DEFAULT_PARAMS)
self.state.coherence = C_V  # Pure thermodynamic
```

**Impact:**
- Coherence now ranges 0.3-0.7 (typical) depending on E-I balance (V)
- No fake signal from placeholder parameters
- More honest calibration

### 2. Threshold Recalibration

**Coherence Critical Threshold** (`config/governance_config.py`):
- **Before:** 0.60 (for blended coherence)
- **After:** 0.40 (for pure C(V))

**Health Thresholds** (`src/health_thresholds.py`):
- **Before:** 
  - `coherence_healthy_min = 0.85`
  - `coherence_degraded_min = 0.60`
- **After:**
  - `coherence_healthy_min = 0.60` (recalibrated)
  - `coherence_degraded_min = 0.40` (recalibrated)

### 3. Documentation Updates

**Updated:**
- `docs/guides/METRICS_GUIDE.md` - Coherence thresholds and ranges
- `docs/analysis/128_PARAMETER_INVESTIGATION.md` - Documents the change

---

## Rationale

### Why Remove param_coherence?

1. **Fake Signal Problem**: When parameters are identical (`[0.5]*128`), `param_coherence = 1.0`, masking real thermodynamic signal
2. **Signal Quality**: Only 34% real signal (C(V) ≈ 0.49), 66% fake signal (param_coherence = 1.0)
3. **Calibration Masking**: Fake signal masked calibration issues - if param_coherence were real (~0.6), coherence would drop to 0.52 (below old threshold)
4. **No Real Extraction**: Parameter extraction not implemented - just placeholders/noise

### Why Pure C(V)?

1. **Honest Calibration**: Pure thermodynamic signal, no fake components
2. **Simpler**: One source of truth
3. **Mathematically Rigorous**: Based on UNITARES framework
4. **Advisory-Only**: System is advisory-only, doesn't need parameter-based signal

---

## Testing Results

**Test Run:**
```
Update 1: coherence=0.4985, V=-0.0030
Update 2: coherence=0.4970, V=-0.0061
Update 3: coherence=0.4954, V=-0.0093
Update 4: coherence=0.4937, V=-0.0125
Update 5: coherence=0.4921, V=-0.0158
```

**Observations:**
- Coherence values are pure C(V) (no param_coherence blend)
- Typical range: 0.3-0.7 depending on V value
- Values around 0.49-0.50 are normal for typical E-I balance

---

## Impact on System Behavior

### Decision Making

**Before:** Coherence threshold 0.60 (blended signal)
- Many agents would pass threshold due to fake param_coherence = 1.0
- Masked calibration issues

**After:** Coherence threshold 0.40 (pure C(V))
- More honest assessment
- Catches truly low coherence (< 0.40)
- Typical operating range: 0.3-0.7

### Health Status

**Before:** 
- Healthy: coherence ≥ 0.85
- Degraded: coherence ≥ 0.60

**After:**
- Healthy: coherence ≥ 0.60 (recalibrated)
- Degraded: coherence ≥ 0.40 (recalibrated)

---

## Future Considerations

### Option B: Real Parameter Extraction (For Local Models)

If building for local models with embedding extraction:
- Implement real parameter extraction from embeddings
- Restore param_coherence blend with real signal
- Recalibrate thresholds accordingly

**Not recommended for advisory-only systems** - adds complexity without benefit.

---

## Related Documents

- `docs/analysis/128_PARAMETER_INVESTIGATION.md` - Investigation of 128-dim parameter vector
- `docs/analysis/COHERENCE_ANALYSIS.md` - Original coherence analysis (references old blended approach)
- `docs/guides/METRICS_GUIDE.md` - Updated coherence thresholds

---

## Status

✅ **Complete** - Pure thermodynamic coherence implemented and tested.

