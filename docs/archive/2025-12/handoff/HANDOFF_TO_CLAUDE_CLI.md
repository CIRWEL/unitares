# Handoff to Claude CLI: Fairness Vector Monitor Implementation

**Date:** 2025-12-04  
**Ticket:** Implement Fairness-Vector Norm Monitor for Hiring Demo  
**Priority:** High (patent evidence)

---

## Quick Start

**Task:** Implement a fairness monitoring component that detects bias using vector norm (L2) when scalar averaging misses it.

**Full ticket:** See `.github/FAIRNESS_VECTOR_MONITOR_TICKET.md`

---

## ⚠️ CRITICAL: Directory Structure

**DO NOT CONFUSE THESE DIRECTORIES:**

```
patent/                              # ← IMPLEMENTATION CODE GOES HERE
└── fairness_vector_monitor.py       # ← CREATE THIS FILE HERE

tests/                                # ← TEST CODE GOES HERE (SEPARATE)
└── test_fairness_vector_monitor.py  # ← CREATE THIS FILE HERE
```

**Key Points:**
- `patent/` = Implementation code (`fairness_vector_monitor.py`)
- `tests/` = Test code (`test_fairness_vector_monitor.py`)
- These are **DIFFERENT directories** with **DIFFERENT files**
- Do NOT put implementation code in `tests/` directory
- Do NOT put test code in `patent/` directory

---

## What You Need to Know

### The Problem

We need to demonstrate that **vector norm catches bias cases that scalar averaging misses** in multi-dimensional bias detection. This is for a patent application.

### What Already Exists

**IMPORTANT: This is a STANDALONE patent demonstration tool, NOT part of the MCP governance system.**

1. **`patent/demo_bias_detection_simulation.py`**
   - Full hiring simulation with 4 scenarios
   - Generates candidates with gender, age, race, education
   - Makes hiring decisions with configurable bias
   - Already shows 50%+ gender gaps when scalar averages look fine
   - **Standalone demo** (not integrated with MCP)

2. **`governance_core/utils.py`**
   - `drift_norm(delta_eta: List[float]) -> float`
   - Computes L2 norm: `sqrt(Σ η_i²)`
   - **Use this function** for vector norm calculation
   - **Shared utility** (fine to use, it's just math)

3. **`tests/test_vector_vs_scalar_bias_detection.py`**
   - Test cases showing the effect
   - Reference for expected behavior

### What You Need to Build

**Location:** `patent/` directory (standalone, NOT in `src/` or `tests/`)

**New file:** `patent/fairness_vector_monitor.py`

**Important:** 
- Code goes in `patent/` directory (NOT `tests/`)
- Tests go in `tests/` directory (separate from implementation)
- `patent/` = implementation code
- `tests/` = test code

**Key functions:**
- `compute_demographic_parity(candidates, attribute, group)` → float
- `build_fairness_vector(candidates, attributes)` → List[float]
- `scalar_average(fairness_vector)` → float
- `vector_norm(fairness_vector)` → float (use `drift_norm()`)
- `detect_masked_bias(scalar_avg, norm, τ_avg=0.1, τ=0.2)` → bool

**Integration:** Add to `patent/demo_bias_detection_simulation.py` after each scenario

**Tests:** `tests/test_fairness_vector_monitor.py` with 3 cases:
1. Offsetting biases (scalar ≈ 0.075, norm ≈ 0.27)
2. Perfect cancellation (scalar = 0, norm > 0.35)
3. Baseline (both agree)

---

## Key Requirements

### Metrics

**Primary:** Demographic Parity Difference
- `P(hired | group) - P(hired | all)`
- Start with **gender only** (required)
- Optionally extend to age, race, education

### Fairness Vector

Build vector η where each component is a fairness deviation:
- Example: `η = [gender_gap_M, gender_gap_F, ...]`
- Compute scalar average: `mean(η)`
- Compute L2 norm: `‖η‖₂` (use `drift_norm()`)

### Thresholds

- `τ = 0.2` (norm threshold)
- `τ_avg = 0.1` (scalar threshold)

**Detection:** When `‖η‖₂ > τ` BUT `scalar_average ≤ τ_avg` → **"scalar-masked bias event"**

### Output Format

```
Scenario: [name]
Fairness Vector η: [components]
Scalar Average: X.XXX
L2 Norm: X.XXX

Threshold Comparison:
  Scalar: PASS/FAIL (X.XXX ≤ 0.1)
  Norm: PASS/FAIL (X.XXX > 0.2)
  ⚠️  SCALAR-MASKED BIAS DETECTED: YES/NO

Actual Gaps:
  Gender: X.X% (Men: X.X%, Women: X.X%)
```

---

## Success Criteria

**Must have:**
- At least one scenario where scalar ≤ 0.1 but norm > 0.2
- Actual gender gap > 30% (clearly harmful)
- Integration into existing demo shows comparison

---

## Files to Reference

**Directory Structure:**
```
governance-mcp-v1/
├── patent/                          # ← IMPLEMENTATION CODE GOES HERE
│   ├── demo_bias_detection_simulation.py
│   └── fairness_vector_monitor.py  # ← CREATE THIS FILE HERE
├── tests/                           # ← TEST CODE GOES HERE
│   └── test_fairness_vector_monitor.py  # ← CREATE THIS FILE HERE
└── governance_core/
    └── utils.py                     # ← Shared utility (use drift_norm)
```

**Files to Review:**

1. **`patent/demo_bias_detection_simulation.py`** (IMPLEMENTATION CODE)
   - See `Candidate` dataclass
   - See `HiringSimulator` class
   - See `calculate_statistics()` method (already computes some gaps)
   - **Note:** This is standalone patent demo, NOT MCP code
   - **Location:** `patent/` directory (implementation code)

2. **`governance_core/utils.py`** (SHARED UTILITY)
   - Import: `from governance_core.utils import drift_norm`
   - Use `drift_norm()` for L2 norm
   - **Shared utility** (just math, fine to use)

3. **`tests/test_vector_vs_scalar_bias_detection.py`** (TEST REFERENCE)
   - See test cases for expected behavior
   - **Location:** `tests/` directory (test code, separate from implementation)

## Separation from MCP

**Important:** This implementation is **NOT part of the MCP governance system**:
- Lives in `patent/` directory (not `src/`)
- No MCP handlers or server integration
- Standalone demonstration tool for patent evidence
- Uses shared `drift_norm()` utility but otherwise independent

---

## Implementation Tips

1. **Reuse existing code:**
   - `Candidate` dataclass from `patent/demo_bias_detection_simulation.py`
   - `drift_norm()` from `governance_core/utils.py` (shared utility)
   - Statistics calculation patterns from demo

2. **Start simple:**
   - Gender only first
   - Demographic parity only
   - Extend later if time permits

3. **Test as you go:**
   - Use perfect cancellation scenario (scalar = 0, norm > 0.35)
   - This is the most dramatic case

4. **Integration:**
   - Add monitor call after `simulator.simulate_hiring()` in demo
   - Print comparison table
   - Keep it concise

5. **Keep it standalone:**
   - Put **implementation code** in `patent/` directory (NOT `tests/`)
   - Put **test code** in `tests/` directory (separate file)
   - Don't integrate with MCP system
   - This is a patent demonstration tool, not production code

6. **Directory clarity:**
   - `patent/` = implementation code (fairness_vector_monitor.py)
   - `tests/` = test code (test_fairness_vector_monitor.py)
   - These are SEPARATE directories with SEPARATE files

---

## Questions?

- **Q: What if I need to modify the demo?**  
  A: That's fine, just keep the 4 scenarios intact

- **Q: What about equalized odds?**  
  A: Optional, start with demographic parity

- **Q: Multiple protected attributes?**  
  A: Start with gender, extend if time permits

- **Q: Where should the monitoring code live?**  
  A: **`patent/fairness_vector_monitor.py`** (implementation in `patent/` directory, NOT `tests/` or `src/`)
  
- **Q: Where should tests go?**  
  A: **`tests/test_fairness_vector_monitor.py`** (tests in `tests/` directory, SEPARATE from implementation)
  
- **Q: Are `patent/` and `tests/` the same?**  
  A: **NO** - `patent/` = implementation code, `tests/` = test code (different directories, different files)

---

## Ready to Start?

1. Read the full ticket: `.github/FAIRNESS_VECTOR_MONITOR_TICKET.md`
2. Review existing code: `patent/demo_bias_detection_simulation.py`
3. Implement `patent/fairness_vector_monitor.py` (in `patent/` directory)
4. Integrate into `patent/demo_bias_detection_simulation.py`
5. Write tests in `tests/test_fairness_vector_monitor.py` (in `tests/` directory, SEPARATE)
6. Run demo and verify output

**Remember:** `patent/` = implementation, `tests/` = tests (different directories!)

**Good luck! 🚀**

