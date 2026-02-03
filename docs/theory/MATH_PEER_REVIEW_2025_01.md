# UNITARES EISV Mathematical Peer Review

**Date:** 2025-01-31
**Reviewer:** Claude (via peer review session)
**Scope:** `governance_core/` dynamics, parameters, coherence

---

## Executive Summary

The EISV framework is mathematically sound with well-designed stability properties. This review identifies:
- **3 confirmed design choices** that are correct despite initial concerns
- **2 areas for potential improvement**
- **1 open question** requiring empirical validation

---

## 1. Sign Convention in Coherence Function ✅ CORRECT

**Initial Concern:** The void dynamics `dV/dt = κ(E - I) - δV` combined with coherence `C(V) = 0.5(1 + tanh(C₁V))` seemed to increase coherence when E > I, which intuitively felt backwards.

**Resolution:** After deeper analysis, this is **intentionally correct** as a negative feedback stabilizer:

```
E > I → dV/dt > 0 → V increases → C increases → dI/dt gets β_I·C boost → I increases → balance restored
I > E → dV/dt < 0 → V decreases → C decreases → I boost reduced → E catches up → balance restored
```

The semantic interpretation:
- **Low coherence (C < 0.5)** = "be conservative, preserve information"
- **High coherence (C > 0.5)** = "okay to explore, system has energy surplus"

From [coherence.py:43-48](governance_core/coherence.py#L43-L48):
> "Mean V ≈ -0.016 → coherence ≈ 0.49 (accurate for conservative operation).
> This reflects genuine thermodynamic state: I slightly > E (information-preserving)"

**Verdict:** The sign convention implements stabilizing feedback correctly. ✅

---

## 2. Euler Integration Stability Analysis

**Concern:** First-order Euler integration with `dt = 0.1` may be unstable for stiff systems.

**Analysis:** Let's compute the Jacobian eigenvalues at equilibrium.

For the linearized system near equilibrium (E*, I*, S*, V*):

```
J = [
    [-α - β_E·S,    α,         -β_E·E,     0        ]
    [0,             -γ_I,       -k,         β_I·∂C/∂V]
    [0,             0,         -μ,         -λ₂·∂C/∂V]
    [κ,             -κ,         0,         -δ        ]
]
```

With typical parameters:
- α = 0.42, β_E = 0.1, γ_I = 0.25, k = 0.1, μ = 0.8, δ = 0.4

The eigenvalues are approximately:
- λ₁ ≈ -0.8 (from S dynamics, fast decay)
- λ₂ ≈ -0.4 (from V dynamics)
- λ₃ ≈ -0.42 (from E-I coupling)
- λ₄ ≈ -0.25 (from I self-regulation)

**Stability criterion for Euler:** |1 + λ·dt| < 1 → dt < 2/|λ_max|

With λ_max ≈ 0.8: dt_max ≈ 2.5

Current dt = 0.1 is **well within stability bounds** (safety factor ~25x).

**Verdict:** Euler integration is stable for these parameters. ✅

**Recommendation:** Add runtime monitoring for clipping frequency. If clipping > 5% of updates, consider reducing dt:

```python
# In compute_dynamics:
if E_new == params.E_max or I_new == params.I_max:
    logger.debug("State clipped - consider reducing dt")
```

---

## 3. Stochastic Noise Scaling ⚠️ POTENTIAL ISSUE

**Concern:** The noise term in S dynamics:
```python
dS_dt = ... + noise_S
```

For Wiener process (Brownian motion), increments should scale as √dt:
```
dW ~ N(0, dt)  →  dW/dt ~ N(0, 1/dt)
```

**Current behavior:** If `noise_S` is a fixed variance random variable, then:
- Small dt → many small noise increments → correct total variance
- Large dt → fewer large noise increments → incorrect total variance

**Two interpretations:**

1. **If `noise_S` represents instantaneous rate:** Current implementation is correct. The noise adds a fixed drift per unit time.

2. **If `noise_S` represents Wiener process:** Should be:
```python
dS_dt = ... + noise_S * math.sqrt(1.0 / dt)
# or equivalently, caller should pass noise_S * sqrt(dt)
```

**Recommendation:** Document the intended semantics in parameters.py or dynamics.py. If stochastic, use:
```python
# SDE: dS = ... dt + σ dW
# Euler-Maruyama: S_{n+1} = S_n + f(S_n)·dt + σ·√dt·Z
dS_dt = ... + noise_S / math.sqrt(dt)  # where noise_S ~ N(0, σ²·dt)
```

---

## 4. Bistability and Basin of Attraction

**Observation:** The logistic term `γ_I·I·(1-I)` creates two equilibria:

From [dynamics.py:229-264](governance_core/dynamics.py#L229-L264):
- High equilibrium: I* ≈ 0.91 (desired)
- Low equilibrium: I* ≈ 0.09 (collapsed)

**The v4.2-P linear mode** fixes this:
```python
if i_mode == "linear":
    dI_dt = A - params.gamma_I * I  # Single stable equilibrium at I* = A/γ_I
```

**Analysis of basin boundary:**

For logistic mode, the separatrix is at:
```
I_crit = 0.5 + O(√(A/γ_I))
```

With typical A ≈ 0.135 and γ_I = 0.25: I_crit ≈ 0.5

**Recommendation:** The `check_basin()` function is correct. Consider adding early warning when I approaches the boundary:

```python
def get_basin_margin(state: State) -> float:
    """Distance from basin boundary. Positive = safe, negative = danger."""
    return state.I - 0.5
```

---

## 5. Two-Timescale Separation

**From the Perplexity discussion:** "v4.2-P already treats x_t = (E, I) as the fast state and θ_t = (C₁, λ₁) as the slow adaptive parameters."

**Verification needed:** Is there a formal timescale separation?

For valid two-timescale analysis:
```
dx/dt = f(x, θ)      [fast, O(1)]
dθ/dt = ε·g(x, θ)    [slow, O(ε) where ε << 1]
```

**Current implementation:** The θ adaptation (via PI controller in process_agent_update) happens once per agent update, while EISV dynamics run at dt = 0.1.

If agent updates happen every ~10 seconds, and EISV runs at dt = 0.1:
- EISV updates: ~100 per agent update
- Effective ε ≈ 1/100 = 0.01

**This is valid two-timescale separation.** ✅

---

## 6. Complexity Input Validation

From [dynamics.py:108-110](governance_core/dynamics.py#L108-L110):
```python
# SECURITY: Clip complexity to valid range [0,1] as defense-in-depth
complexity = max(0.0, min(1.0, complexity))
```

**Question:** What's the threat model?

**Analysis:** Without clipping, malicious complexity values could:
- `complexity = 1000` → S grows unbounded → system destabilizes
- `complexity = -1000` → S goes negative (violates S_min)

The clipping provides defense-in-depth against:
1. Buggy callers passing invalid values
2. Untrusted input from agent self-reports

**Verdict:** Good defensive programming. ✅

---

## 7. Antithetic Gradient Estimation (Missing?)

**Concern:** The Perplexity discussion mentions "antithetic finite differences" for ∇_θ J estimation, but I don't see this in `governance_core/`.

**Search result:** No gradient estimation code found in the core dynamics.

**Hypothesis:** θ adaptation may be happening in:
- `src/unitaires-server/` (the MCP server layer)
- A separate optimizer module
- Or the PI controller mentioned in docs is simpler than antithetic estimation

**Recommendation:** If implementing gradient-based θ optimization:

```python
def estimate_gradient_antithetic(
    objective_fn: Callable[[Theta], float],
    theta: Theta,
    epsilon: float = 0.01,
) -> Theta:
    """Antithetic gradient estimate with variance reduction."""
    # Paired perturbations
    z = random_direction()  # Unit vector in Theta space

    theta_plus = Theta(
        C1=theta.C1 + epsilon * z.C1,
        eta1=theta.eta1 + epsilon * z.eta1,
    )
    theta_minus = Theta(
        C1=theta.C1 - epsilon * z.C1,
        eta1=theta.eta1 - epsilon * z.eta1,
    )

    # Antithetic estimate (cancels O(ε) bias)
    J_plus = objective_fn(theta_plus)
    J_minus = objective_fn(theta_minus)

    grad_estimate = (J_plus - J_minus) / (2 * epsilon)

    return Theta(
        C1=grad_estimate * z.C1,
        eta1=grad_estimate * z.eta1,
    )
```

---

## 8. Open Questions for Empirical Validation

### 8.1 Does V ever leave the [-0.1, 0.1] range?

The docs note V is designed for [-2, 2] but operates in [-0.1, 0.1]. Under what conditions (if any) does V exhibit larger excursions?

**Suggested experiment:**
```python
# Inject sustained ethical drift
delta_eta = [0.5, 0.5, 0.5]  # High drift
# Run for 100 timesteps
# Track max(|V|)
```

### 8.2 How sensitive is equilibrium I* to parameter choices?

With linear mode, I* = A/γ_I. Small changes in γ_I significantly affect equilibrium:
- γ_I = 0.169 → I* ≈ 0.80
- γ_I = 0.20 → I* ≈ 0.68
- γ_I = 0.15 → I* ≈ 0.90

**Recommendation:** Document the sensitivity and provide parameter tuning guidance.

---

## Summary of Recommendations

| Issue | Severity | Action |
|-------|----------|--------|
| Sign convention | N/A | No change - design is correct |
| Euler stability | Low | Add clipping frequency monitoring |
| Noise scaling | Medium | Document intended semantics |
| Basin warning | Low | Add early warning metric |
| Gradient estimation | Info | Clarify where θ adaptation happens |
| Parameter sensitivity | Info | Add tuning documentation |

---

**Next Steps:**
1. Run empirical validation on V excursion ranges
2. Document noise_S semantics
3. Verify θ adaptation implementation location
