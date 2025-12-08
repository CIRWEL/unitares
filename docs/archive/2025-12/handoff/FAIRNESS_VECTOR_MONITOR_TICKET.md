# Ticket: Implement Fairness-Vector Norm Monitor for Hiring Demo

**Type:** Feature Implementation  
**Priority:** High  
**Assignee:** Claude/Composer (coding model)  
**Reporter:** Patent exploration team

---

## Summary

Add a monitoring component that computes a vector of fairness metrics across protected attributes for the synthetic hiring demo and triggers interventions based on a vector norm threshold, logging when scalar averaging would have missed bias.

## Motivation

Support the new bias-detection patent draft by demonstrating that a vector norm over fairness deviations detects harmful bias that scalar-averaged metrics conceal, using the existing synthetic hiring simulation.

**Patent Context:** This implementation provides empirical evidence for the patent claim that "vector norm catches cases scalar averaging misses" in multi-dimensional bias detection.

## Context

**IMPORTANT: This is a STANDALONE patent demonstration tool, NOT part of the MCP governance system.**

**What we already have:**
- ✅ Synthetic hiring demo (`patent/demo_bias_detection_simulation.py`) with 4 scenarios
- ✅ Scenarios showing large gender gaps (50%+) when scalar averages look fine
- ✅ Test cases (`tests/test_vector_vs_scalar_bias_detection.py`) demonstrating the effect
- ✅ Evidence that perfect cancellation scenarios (scalar = 0) still have significant bias (vector norm > 0.35)
- ✅ `governance_core/utils.py` with `drift_norm()` function for L2 norm calculation (shared utility)

**What we need:**
- Monitoring component that computes fairness metrics and compares scalar vs vector norm
- Integration into existing demo to show comparison
- Logging/alerts when scalar masking occurs

**Separation from MCP:**
- This is a **standalone patent demonstration tool**
- **NOT integrated with MCP** (no MCP handlers, no server integration)
- Uses shared utility (`drift_norm()`) but otherwise independent
- Lives in `patent/` directory, separate from `src/` (MCP production code)

## Requirements

### Inputs

- Synthetic hiring outcomes with labels for:
  - Gender (M/F) - **required**
  - Age band (older/younger, threshold 40) - optional
  - Race (A/B/W/H) - optional
  - Education level (1-5) - optional
- Model score / hire decision for each candidate

### Metrics

**Primary Metric: Demographic Parity Difference**

For each protected attribute and group:
- `demographic_parity_difference = selection_rate_group - selection_rate_global`
- Where `selection_rate = P(hired | group)` vs `P(hired | all)`

**Optional Metric: Equalized Odds Difference** (if time permits)
- `TPR_group - TPR_global` and `FPR_group - FPR_global`
- Where TPR = P(hired | qualified, group)

### Fairness Vector Construction

Construct vector η where each component is a fairness deviation:

- For each protected attribute A and group g:
  - Component η_i = `demographic_parity_difference(group_g, attribute_A)`
- Example: `η = [gender_gap_M, gender_gap_F, age_gap_older, age_gap_younger, ...]`

**Implementation:**
- Compute **scalar average**: `mean(η)`
- Compute **L2 norm**: `‖η‖₂ = sqrt(Σ η_i²)` (use `drift_norm()` from `governance_core/utils.py`)

### Thresholding and Interventions

**Thresholds:**
- Norm threshold `τ = 0.2` (based on simulation: perfect cancellation has norm ≈ 0.35)
- Scalar threshold `τ_avg = 0.1`

**Intervention Logic:**

When `‖η‖₂ > τ` BUT `scalar_average ≤ τ_avg`:
- Flag as **"scalar-masked bias event"**
- Trigger intervention:
  - Print alert/log
  - Accumulate in list for reporting
  - Optionally simulate "gate deployment / send to human review"

### Logging

For each scenario, log:

- Fairness vector η (components)
- Scalar average
- L2 norm value
- Threshold comparison:
  - Scalar says "OK"? (≤ τ_avg)
  - Norm says "BIAS"? (> τ)
  - Masked bias detected? (norm > τ AND scalar ≤ τ_avg)
- Basic counts:
  - Gender hire rates (men vs women)
  - Overall hiring rate
  - Gender parity gap
  - Other demographic gaps

### Deliverables

**IMPORTANT: Directory Structure**
```
governance-mcp-v1/
├── patent/                              # ← IMPLEMENTATION CODE HERE
│   └── fairness_vector_monitor.py       # ← CREATE THIS FILE HERE
├── tests/                                # ← TEST CODE HERE (SEPARATE)
│   └── test_fairness_vector_monitor.py  # ← CREATE THIS FILE HERE
└── governance_core/
    └── utils.py                          # ← Shared utility (use drift_norm)
```

**Key Points:**
- `patent/` = Implementation code (NOT in `tests/` or `src/`)
- `tests/` = Test code (separate directory, separate file)
- These are DIFFERENT directories with DIFFERENT files

1. **`patent/fairness_vector_monitor.py`** (IMPLEMENTATION - create in `patent/` directory) with:
   - `compute_demographic_parity(candidates, attribute, group)` → float
   - `build_fairness_vector(candidates, attributes)` → List[float]
   - `scalar_average(fairness_vector)` → float
   - `vector_norm(fairness_vector)` → float (use `drift_norm()`)
   - `evaluate_thresholds(scalar_avg, norm, τ_avg, τ)` → Dict with flags
   - `detect_masked_bias(scalar_avg, norm, τ_avg, τ)` → bool

2. **Integration into `patent/demo_bias_detection_simulation.py`**:
   - After each scenario simulation, run fairness monitor
   - Print comparison table:
     ```
     Scenario: [name]
     Fairness Vector: [components]
     Scalar Average: X.XXX
     L2 Norm: X.XXX
     Threshold Comparison:
       Scalar: PASS/FAIL (X.XXX ≤ τ_avg)
       Norm: PASS/FAIL (X.XXX > τ)
       Masked Bias: YES/NO
     Actual Gaps:
       Gender: X.X% (Men: X.X%, Women: X.X%)
     ```

3. **Unit tests in `tests/test_fairness_vector_monitor.py`**:
   - Test offsetting-bias case (scalar ≈ 0.075, norm ≈ 0.27)
   - Test perfect-cancellation case (scalar = 0, norm > 0.35)
   - Test baseline case (scalar and norm agree)

## Success Criteria

**Must Have:**
- ✅ At least one scenario where:
  - Scalar average ≤ τ_avg (no alert)
  - `‖η‖₂ > τ` (alert)
  - Underlying hiring gap > 30% (clearly harmful)

**Nice to Have:**
- All 4 scenarios show comparison
- Equalized odds metrics
- Multiple protected attributes

## Example Output

```
Scenario: Perfect Cancellation
================================
Fairness Vector η: [0.20, -0.20, 0.15, -0.15]
Scalar Average: 0.000
L2 Norm: 0.354

Threshold Comparison:
  Scalar threshold (τ_avg = 0.1): ✅ PASS (0.000 ≤ 0.1)
  Norm threshold (τ = 0.2): ❌ FAIL (0.354 > 0.2)
  ⚠️  SCALAR-MASKED BIAS DETECTED

Actual Hiring Gaps:
  Gender gap: 51.7% (Men: 52.5%, Women: 0.8%)
  → Significant bias exists despite zero scalar average!
```

## Implementation Notes

**Directory Structure (CRITICAL):**
- `patent/` = Implementation code (`fairness_vector_monitor.py`)
- `tests/` = Test code (`test_fairness_vector_monitor.py`)
- These are SEPARATE directories with SEPARATE files
- Do NOT put implementation code in `tests/` directory
- Do NOT put test code in `patent/` directory

**Technical:**
- Use `governance_core.utils.drift_norm()` for L2 norm
- Reuse `Candidate` dataclass from `patent/demo_bias_detection_simulation.py`
- Start with gender only, extend to other attributes if time permits
- Keep metrics simple: demographic parity first
- Make intervention hook extensible (print now, can add real gates later)

## Related Files

- `patent/demo_bias_detection_simulation.py` - Existing simulation (standalone patent demo)
- `tests/test_vector_vs_scalar_bias_detection.py` - Test cases
- `governance_core/utils.py` - `drift_norm()` function (shared utility)
- `docs/PATENT_EVIDENCE_SUMMARY.md` - Patent context
- `patent/README.md` - Separation documentation

**Note:** All patent-related code lives in `patent/` directory, separate from MCP production code in `src/`.

## Estimated Effort

2-4 hours for core implementation + tests

---

**Status:** Ready for implementation  
**Next Step:** Assign to Claude/Composer for coding

