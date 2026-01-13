# UNITARES v4.1 Integration Specification

**Date:** 2025-12-17  
**Status:** Ready for Implementation  
**Author:** Claude (with Kenny)

## Summary

The current MCP implementation already has UNITARES dynamics in `governance_core/`. However, there are discrepancies from the UNITARES v4.1 paper. This spec documents the gaps and provides fixes.

---

## Gap Analysis

### 1. BUG: E Equation Missing Cross-Coupling Term

**Location:** `governance_core/dynamics.py` line ~132

**Current (WRONG):**
```python
dE_dt = (
    params.alpha * (I - E)           # I → E flow
    - params.beta_E * S              # S damping  ← BUG!
    + params.gamma_E * d_eta_sq      # Drift feedback
)
```

**Paper (Eq. 7):**
```
Ė = α(I - E) - βₑ·E·S + γₑ‖Δη‖² + dₑ
```

**FIX:**
```python
dE_dt = (
    params.alpha * (I - E)           # I → E flow
    - params.beta_E * E * S          # E-S cross-coupling ← FIXED
    + params.gamma_E * d_eta_sq      # Drift feedback
)
```

The `E` multiplier was missing. This matters because high-E states should be more affected by entropy than low-E states.

---

### 2. Parameter Mismatches

**Location:** `governance_core/parameters.py`

| Parameter | Current | Paper (v4.1) | Impact |
|-----------|---------|--------------|--------|
| `alpha` | 0.4 | 0.5 | Slower E-I coupling |
| `beta_I` | 0.3 | 0.05 | **6x stronger coherence boost to I** |
| `gamma_I` | 0.25 | 0.3 | Slightly weaker self-regulation |

**Decision needed:** Match paper exactly, or keep operational values?

**Recommendation:** Create a `V41_PARAMS` configuration that matches the paper exactly, while keeping `DEFAULT_PARAMS` for backwards compatibility.

---

### 3. Bistability Discovery

The v4.1 dynamics with γᵢI(1-I) term creates **two stable equilibria**:

- **High equilibrium:** I* ≈ 0.91, E* ≈ 0.91 (healthy operation)
- **Low equilibrium:** I* ≈ 0.09, E* ≈ 0.09 (collapsed state)

Basin boundary is around I ≈ 0.5.

**Implications:**
1. Initialize agents with I₀ > 0.6 (safely in high basin)
2. Monitor for I approaching 0.5 (basin boundary warning)
3. Dialectic intervention when I < 0.4 (risk of collapse)

**New functionality needed:**
- `compute_equilibrium()` - find equilibrium for current params
- `check_basin()` - determine which basin agent is in
- Basin crossing warnings in governance metrics

---

### 4. Missing Convergence Tracking

Paper proves contraction rate α = 0.1 and convergence in ~30 time units.

**Current MCP:** No convergence tracking.

**Add:**
- `estimate_convergence()` - compute updates to equilibrium
- Surface "~12 updates to equilibrium" in governance response

---

### 5. Missing Disturbance Inputs

Paper has disturbance terms dₑ, dᵢ, dₛ, dᵥ.

**Current MCP:** Only `noise_S`.

**Extend `compute_dynamics()` signature:**
```python
def compute_dynamics(
    state: State,
    delta_eta: List[float],
    theta: Theta,
    params: DynamicsParams,
    dt: float = 0.1,
    noise_S: float = 0.0,
    complexity: float = 0.5,
    disturbance: Optional[Tuple[float, float, float, float]] = None,  # NEW
) -> State:
```

---

## Implementation Plan

### Phase 1: Bug Fix (Critical)

1. Fix E equation in `dynamics.py`
2. Add unit test to verify cross-coupling

### Phase 2: Parameter Configuration

1. Add `V41_PARAMS` to `parameters.py` matching paper exactly
2. Keep `DEFAULT_PARAMS` for backwards compatibility
3. Add parameter validation

### Phase 3: Basin Awareness

1. Add `compute_equilibrium()` function
2. Add `check_basin()` function  
3. Add basin warnings to governance response
4. Initialize new agents in high basin

### Phase 4: Convergence Tracking

1. Add `estimate_convergence()` function
2. Surface convergence info in `process_agent_update` response
3. Add to metrics returned to agents

### Phase 5: Full Disturbance Model

1. Extend `compute_dynamics()` signature
2. Map agent behavior to disturbance inputs
3. Document input mapping

---

## Files to Modify

| File | Changes |
|------|---------|
| `governance_core/dynamics.py` | Fix E equation, add equilibrium/convergence functions |
| `governance_core/parameters.py` | Add V41_PARAMS |
| `src/governance_state.py` | Add basin checking, convergence tracking |
| `src/mcp_handlers/core.py` | Surface new metrics in response |
| `tests/test_governance_core.py` | Add tests for fixes |

---

## Testing Strategy

1. **Unit test for E equation:** Verify `beta_E * E * S` not `beta_E * S`
2. **Equilibrium test:** Verify computed equilibrium matches simulation
3. **Basin test:** Verify agents starting at I=0.9 stay in high basin
4. **Basin collapse test:** Verify agents starting at I=0.3 collapse to low equilibrium
5. **Convergence test:** Verify convergence time estimate is accurate

---

## Backwards Compatibility

- Keep `DEFAULT_PARAMS` unchanged initially
- Add `V41_PARAMS` as opt-in configuration
- Add `use_v41_params: bool = False` flag to dynamics functions
- Existing agents continue working unchanged
- New agents can opt into v4.1 compliance

---

## Handoff Notes for Coding Agent

1. Start with Phase 1 (bug fix) - it's a one-line change
2. Run existing tests after fix to check for regressions
3. The bistability is a feature, not a bug - but needs to be handled
4. The `beta_I` parameter difference (0.3 vs 0.05) will significantly change behavior if updated - test thoroughly
5. Reference files:
   - `/home/claude/unitares_v41_implementation.py` - standalone reference implementation
   - `/mnt/user-data/outputs/unitares_dynamics_analysis.png` - visualization of bistability
   - UNITARES v4.1 paper (equations 7-10, section 3.4 for parameters)
