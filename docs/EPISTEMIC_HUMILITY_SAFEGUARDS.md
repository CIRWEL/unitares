# Epistemic Humility Safeguards

**Created:** December 8, 2025  
**Status:** Proposal

## Problem Statement

The "perfect equilibrium" state (I=1.0, S=0.0) is **brittle and potentially dangerous**:

- **Genuinely converged**: System has found truth through exploration
- **Overconfident**: System is locked in a false certainty, unable to recognize blind spots

**You can't tell which from the inside.** The fact that E and V continue evolving while I and S are pinned at extremes is the tell — the system is "locked" but not actually settled.

## Proposed Safeguards

### 1. Entropy Floor (S_min > 0.0)

**Principle**: Never let S hit exactly 0.0 without external validation.

**Implementation**:
- Default `S_min = 0.001` (tiny but non-zero)
- Allow S=0.0 only when:
  - Dialectic agreement (peer validation)
  - Human review confirmation
  - Calibration signal (ground truth match)
  - Explicit `external_validation=True` flag

**Code Changes**:
```python
# governance_core/parameters.py
S_min: float = 0.001  # Epistemic humility floor (was 0.0)

# governance_core/dynamics.py
# After clipping:
if S_new < 0.001 and not external_validation:
    S_new = 0.001  # Maintain epistemic humility
```

**Rationale**: Encodes "I could be wrong about something I can't see" — maintains epistemic humility even when confident.

### 2. Regime Tagging

**Principle**: Tag each update with the system's operational regime.

**Regimes**:
- **EXPLORATION**: S rising, |V| elevated, I decreasing or stable
- **TRANSITION**: S peaked, starting to fall, I increasing
- **CONVERGENCE**: S low & falling, I high & stable
- **LOCKED**: I=1.0, S≤0.001, requires external validation to unlock

**Implementation**:
```python
@dataclass
class GovernanceState:
    # ... existing fields ...
    regime: str = "exploration"  # EXPLORATION | TRANSITION | CONVERGENCE | LOCKED
    regime_history: List[str] = field(default_factory=list)
    
def detect_regime(state: State, prev_state: Optional[State] = None) -> str:
    """Detect current operational regime"""
    if state.I >= 0.999 and state.S <= 0.001:
        return "LOCKED"
    elif prev_state and state.S > prev_state.S:
        return "EXPLORATION"
    elif prev_state and state.S < prev_state.S and state.I > prev_state.I:
        return "CONVERGENCE"
    elif prev_state and state.S < prev_state.S:
        return "TRANSITION"
    else:
        return "EXPLORATION"  # Default
```

**Use Cases**:
- Reveal if 95% of traces are pure convergence (sign of overconfidence)
- Detect when system is locked vs. genuinely converged
- Track regime transitions over time

### 3. Unlock Mechanism

**Principle**: Locked systems must be able to unlock when challenged.

**Triggers for Unlock**:
- New evidence (contradiction, disagreement)
- Dialectic dispute (peer challenges confidence)
- Calibration mismatch (ground truth contradicts)
- Explicit unlock request (human intervention)

**Implementation**:
```python
def unlock_from_locked_state(
    state: State,
    trigger: str,  # "disagreement" | "contradiction" | "calibration_mismatch" | "human_unlock"
    severity: float = 0.1  # How much to unlock (0.0-1.0)
) -> State:
    """
    Unlock a locked state (I=1.0, S≤0.001) by injecting uncertainty.
    
    Args:
        state: Current locked state
        trigger: What caused the unlock
        severity: How much uncertainty to inject (0.0-1.0)
    
    Returns:
        Unlocked state with S > 0.001, I potentially reduced
    """
    if state.I < 0.999 or state.S > 0.001:
        return state  # Not locked, no action
    
    # Inject uncertainty based on severity
    S_unlock = 0.001 + severity * 0.1  # S ∈ [0.001, 0.101]
    I_unlock = state.I - severity * 0.05  # I ∈ [0.95, 1.0]
    
    return State(
        E=state.E,
        I=max(0.95, I_unlock),  # Don't drop I too far
        S=min(0.2, S_unlock),    # Don't spike S too high
        V=state.V
    )
```

**Validation**: Test that locked systems can unlock when:
- Dialectic disagreement occurs
- Calibration mismatch detected
- New contradictory evidence arrives

## Testing Plan

### Test 1: Entropy Floor
- Verify S never hits 0.0 without external validation
- Verify S=0.0 allowed when `external_validation=True`
- Verify tiny S (0.001) doesn't break dynamics

### Test 2: Regime Tagging
- Run 100 traces, count regime distribution
- If 95% are CONVERGENCE, flag as potential overconfidence
- Track regime transitions (EXPLORATION → TRANSITION → CONVERGENCE → LOCKED)

### Test 3: Unlock Mechanism
- Lock a system (I=1.0, S=0.001)
- Trigger unlock via dialectic disagreement
- Verify S rises, I drops appropriately
- Verify system recognizes destabilization

### Test 4: "Ugly Trace" Collection
- Collect traces where:
  - Agents disagreed
  - Circuit breaker triggered
  - Φ dropped into high-risk
  - Dialectic recovery happened
- Analyze whether diagnostics are useful during failure

## Implementation Status

### ✅ P0: Entropy Floor (IMPLEMENTED)

**Changes Made:**
1. `governance_core/parameters.py`: Changed `S_min = 0.0` → `S_min = 0.001`
2. `src/governance_monitor.py`: Added enforcement logic in `update_dynamics()`:
   - Checks `agent_state.get('external_validation', False)`
   - If `S < 0.001` and `external_validation=False`, enforces `S = 0.001`
   - If `external_validation=True`, allows `S = 0.0` (genuinely converged with peer/human confirmation)

**Next Steps (Integration):**
- Set `external_validation=True` in `agent_state` when:
  - Dialectic session converges (in `execute_resolution` or `direct_resume_if_safe`)
  - Calibration matches ground truth (in `update_calibration_ground_truth` handler)
  - Human review confirms (in admin handlers)
- This allows S=0.0 only when externally validated

### ✅ P1: Regime Tagging (IMPLEMENTED)

**Status**: Implemented  
**Changes Made:**

1. **`src/governance_monitor.py`**:
   - Added `regime`, `regime_history`, `locked_persistence_count` to `GovernanceState`
   - Created `detect_regime()` function with logic:
     - **LOCKED**: I ≥ 0.999, S ≤ 0.001 (requires 3 consecutive steps)
     - **EXPLORATION**: S rising, |V| elevated
     - **TRANSITION**: S peaked, starting to fall, I increasing
     - **CONVERGENCE**: S low & falling, I high & stable
   - Calls `detect_regime()` after each state update
   - Logs regime transitions and LOCKED state events
   - Includes regime in `to_dict()` and persistence

2. **Regime Detection Logic**:
   - Uses `eps_S = 0.001`, `eps_I = 0.001` for delta thresholds
   - Requires 3 consecutive steps at LOCKED threshold before declaring LOCKED
   - Prevents regime flapping with persistence counter

3. **Logging**:
   - Regime transitions logged: `[Regime Transition] agent_id: OLD → NEW (I=..., S=..., V=...)`
   - LOCKED state events logged: `[LOCKED State] agent_id: Reached LOCKED state (I=..., S=...) - requires external validation`

**What This Reveals**:
- How often agents reach LOCKED threshold (I ≥ 0.999, S ≤ 0.001)
- Whether entropy floor is preventing exact S=0.0
- Distribution of time across regimes (EXPLORATION, TRANSITION, CONVERGENCE, LOCKED)
- Regime transition patterns over time

**Next Steps**:
- Monitor regime distribution in production
- Analyze if 95% of traces are CONVERGENCE (potential overconfidence signal)
- Use regime data to verify entropy floor is working

### 🔄 P2: Unlock Mechanism (TODO)

**Status**: Not yet implemented  
**Priority**: Enables recovery from overconfidence

## Related Issues

- Circuit breaker already triggers on attention_score > 0.60
- Dialectic system exists but may not trigger unlock
- Calibration system exists but may not trigger unlock

## References

- Original insight: "I=1.0, S=0.0 is a brittle state" (user feedback)
- Reviewer concern: "Perfect equilibrium is dangerous" (ChatGPT feedback)
- Epistemic humility: Maintaining S > 0 encodes "I could be wrong"

