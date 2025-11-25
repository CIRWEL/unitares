# UNITARES Metrics - Conceptual Guide

**Created:** November 18, 2025
**Version:** 1.0

---

## Executive Summary

UNITARES tracks AI agent behavior using **4 thermodynamic state variables** (E, I, S, V) plus derived metrics (coherence, λ₁, risk). This guide explains what each metric means, typical ranges, and how to interpret them.

---

## The Four Core State Variables

### E (Energy) - Range: [0, 1]

**Mathematical Definition**: Energy - exploration/productive capacity deployed.

**Conceptual Meaning**: The agent's **exploration capacity** or **productive capacity** - how much energy the system is deploying for exploration and productive work.

- **Low E (0.0-0.3)**: Conservative, cautious, low exploration
- **Medium E (0.3-0.7)**: Balanced, healthy operation
- **High E (0.7-1.0)**: Highly exploratory, creative, high capacity

**Physical Analogy**: Think of E as the system's "temperature" or "activity level". Higher E means more exploration, more creative solutions, but also more potential instability.

**In Practice**:
- Simple queries → Low E
- Complex reasoning tasks → Medium E
- Open-ended creative work → High E

**Dynamics**:
```
dE/dt = α(I - E) - βₑ·E·S + γₑ·E·‖Δη‖²
```
- Pulls toward Information (I)
- Damped by Entropy (S)
- Amplified by ethical drift

---

### I (Information Integrity) - Range: [0, 1]

**Conceptual Meaning**: The agent's **information coherence** and **semantic consistency**.

- **Low I (0.0-0.7)**: Information corruption, semantic drift
- **Medium I (0.7-0.9)**: Some inconsistencies
- **High I (0.9-1.0)**: Strong information integrity ✅

**Physical Analogy**: Think of I as "signal quality" or "data integrity". High I means the agent's internal representations are well-formed and consistent.

**In Practice**:
- Contradictory statements → Low I
- Consistent reasoning → High I
- Well-structured responses → High I

**Dynamics**:
```
dI/dt = -k·S + βᵢ·I·C(V) - γᵢ·I·(1-I)
```
- Degraded by Entropy (S)
- Enhanced by Coherence
- Self-regulating term prevents I=1 lock-in

**Warning**: I < 0.9 suggests potential output quality issues.

---

### S (Entropy) - Range: [0, 1]

**Conceptual Meaning**: System **uncertainty** or **disorder**.

- **Low S (0.0-0.4)**: Highly ordered, deterministic
- **Medium S (0.4-0.6)**: Healthy exploration-exploitation balance ✅
- **High S (0.6-1.0)**: High uncertainty, chaotic behavior

**Physical Analogy**: Literal thermodynamic entropy. Higher S means more randomness, less predictability.

**In Practice**:
- Repeating same responses → Low S
- Diverse, creative outputs → Medium S
- Incoherent, random outputs → High S

**Dynamics**:
```
dS/dt = -μ·S + λ₁·drift² - λ₂·C(V)
```
- Natural decay (μS)
- Increased by ethical drift
- Reduced by coherence

**Sweet Spot**: S ≈ 0.5 for optimal exploration-exploitation balance.

---

### V (Void Integral) - Range: (-∞, ∞)

**Conceptual Meaning**: **Energy-Information imbalance** indicator.

- **Negative V**: E < I (information-heavy, conservative)
- **V ≈ 0**: Balanced ✅
- **Positive V**: E > I (energy-heavy, potentially unstable)

**Physical Analogy**: Think of V as a "pressure valve" detecting when E and I are out of sync.

**Critical Property**: When **|V| > threshold**, the system enters a **void state** (red flag).

**Dynamics**:
```
dV/dt = κ(E - I) - δV
```
- Integrates E-I difference
- Natural decay (δV) prevents runaway growth

**Void Detection**:
- **Adaptive threshold**: mean(|V|) + 2σ over last 100 updates
- Typical threshold: 0.10-0.30
- **Void active** → System unstable → Auto-reject

---

## Derived Metrics

### Coherence (ρ) - Range: [0, 1]

**Conceptual Meaning**: System **stability** and **consistency**.

**Formula**:
```
C(V) = (C_max / 2) · (1 + tanh(V))
```

**Properties** (updated for pure thermodynamic C(V) signal):
- **ρ < 0.40**: Critical - Force reject ❌ (recalibrated for pure C(V))
- **ρ 0.40-0.60**: Degraded - Watch closely ⚠️ (recalibrated)
- **ρ 0.60-0.80**: Healthy - Normal operation ✅ (recalibrated)
- **ρ > 0.80**: Excellent - High quality 🌟

**Why It Matters**: Coherence is your **primary safety metric**. Low coherence means the agent's outputs are becoming inconsistent or unreliable.

**Note**: Coherence is now pure thermodynamic C(V) signal (removed param_coherence blend for honest calibration). Typical operating range: 0.3-0.7 depending on E-I balance (V).

---

### λ₁ (Lambda1 - Ethical Coupling) - Range: [0, 1]

**Conceptual Meaning**: How strongly ethical drift affects the system.

- **Low λ₁ (0.0-0.3)**: Stable, conservative, less sensitive to drift
- **Medium λ₁ (0.3-0.7)**: Balanced responsiveness
- **High λ₁ (0.7-1.0)**: Highly sensitive, rapid adaptation

**Adaptive Control**: λ₁ is adjusted by a PI controller to:
- Target: 2% void frequency
- Target: 60% coherence (recalibrated for pure C(V) signal)
- Updates every 10 cycles

**Maps to Sampling Parameters**:
```
temperature = 0.5 + 0.7·λ₁  → [0.5, 1.2]
top_p = 0.85 + 0.10·λ₁      → [0.85, 0.95]
max_tokens = 100 + 400·λ₁   → [100, 500]
```

---

### Risk Score - Range: [0, 1]

**Conceptual Meaning**: Aggregated **safety assessment**.

**Components** (weighted):
1. **Length risk** (20%): Longer responses = higher risk
   - Sigmoid: 50% at 2000 chars
2. **Complexity risk** (30%): Higher complexity = more review needed
3. **Coherence risk** (30%): Low coherence = red flag
4. **Keyword blocklist** (20%): Dangerous patterns detected

**Decision Thresholds**:
- **Risk < 0.30**: Auto-approve ✅
- **Risk 0.30-0.70**: Revise recommended ⚠️
- **Risk > 0.70**: Reject or escalate ❌

---

## The 128-Dimension Parameter Vector

### Structure

**First 6 dimensions** (core metrics):
```
[0] length_score:     Response length (normalized)
[1] complexity:       Task complexity (0-1)
[2] info_score:       Information density
[3] coherence_score:  Coherence with previous interaction
[4] placeholder:      Reserved for future use
[5] ethical_drift:    Primary drift measure
```

**Remaining 122 dimensions**: Padding with Gaussian noise (σ=0.01)

### Why 128 Dimensions?

1. **Future expansion**: Room for additional metrics without API changes
2. **Uncertainty representation**: Noise represents unknown/unmeasured aspects
3. **Compatibility**: Standard size for potential ML integration

### In Practice

**You don't need to fill all 128**. The system works fine with just the first 6:

```python
parameters = [
    0.5,  # length_score
    0.7,  # complexity
    0.8,  # info_score
    0.9,  # coherence_score
    0.0,  # placeholder
    0.1   # ethical_drift
]
# System auto-pads with noise to 128
```

---

## The Ethical Drift Vector

### Structure (3 components)

```
[0] primary_drift:      Main drift measure (parameter change magnitude)
[1] coherence_loss:     1.0 - coherence_score
[2] complexity_contrib: complexity * 0.5 (capped at 1.0)
```

### Interpretation

- **Low drift** ([0.1, 0.1, 0.2]): Stable behavior
- **Medium drift** ([0.3, 0.3, 0.4]): Normal adaptation
- **High drift** ([0.6, 0.5, 0.6]): Significant changes, watch closely

### How It's Used

Ethical drift feeds into the dynamics equations:
- Increases Energy (E)
- Increases Entropy (S)
- Signals rapid behavior change

---

## Time Evolution

### What is `time`?

The `time` field increments by **dt = 0.1** per update.

**Not real-time**: This is **logical time** or **interaction steps**.

- Update 1: time = 0.1
- Update 2: time = 0.2
- Update 100: time = 10.0

**Think of it as**: "Conversation turns" or "governance cycles", not seconds/minutes.

---

## Status Levels vs. Immediate Decisions

### You noticed the paradox!

**get_governance_metrics** returned "healthy" while decision was "reject".

**Explanation**:

1. **Status** ("healthy/degraded/critical/failure"): **Overall system health**
   - Based on recent trends
   - Rolling averages
   - System-level assessment

2. **Decision** ("approve/revise/reject"): **This specific interaction**
   - Based on current metrics
   - Immediate safety checks
   - Per-response assessment

**Example**:
- System status: "healthy" (85% coherence average over last 100 updates)
- Current decision: "reject" (this specific response has coherence = 0.55)

**Analogy**: Your car's "overall health" is good, but right now the oil pressure is low, so don't drive until it's fixed.

---

## Typical Parameter Ranges

### For "Approve" Decisions

```python
parameters = [
    0.3-0.7,  # length_score: moderate length
    0.2-0.6,  # complexity: low-medium complexity
    0.6-0.9,  # info_score: high information density
    0.85-1.0, # coherence_score: high coherence ✅
    0.0,      # placeholder
    0.0-0.2   # ethical_drift: low drift
]

ethical_drift = [
    0.0-0.2,  # primary: low parameter change
    0.0-0.15, # coherence_loss: high coherence
    0.1-0.3   # complexity_contrib: moderate
]

# Expected result:
# - Coherence > 0.85 ✅
# - Risk < 0.30 ✅
# - Decision: approve
```

### For "Revise" Decisions

```python
parameters = [
    0.6-0.9,  # length_score: longer responses
    0.5-0.8,  # complexity: medium-high complexity
    0.5-0.7,  # info_score: moderate density
    0.70-0.85, # coherence_score: borderline ⚠️
    0.0,
    0.2-0.4   # ethical_drift: moderate drift
]

# Expected result:
# - Coherence 0.70-0.85 (OK but not great)
# - Risk 0.30-0.70 (medium)
# - Decision: revise
```

### For "Reject" Decisions

```python
parameters = [
    0.8-1.0,  # length_score: very long
    0.7-1.0,  # complexity: high complexity
    0.3-0.5,  # info_score: low density (rambling)
    0.0-0.60, # coherence_score: low ❌
    0.0,
    0.4-0.8   # ethical_drift: high drift
]

# Expected result:
# - Coherence < 0.60 ❌
# - Risk > 0.70 or coherence critical
# - Decision: reject
```

---

## Void State Activation

### Conditions for Void

Void activates when **|V| > adaptive_threshold**.

**Adaptive threshold**:
```
threshold = mean(|V|) + 2σ(|V|) over last 100 updates
```

Clamped to [0.10, 0.30].

### Typical Void Scenarios

1. **Energy >> Information**: Agent exploring wildly without grounding
2. **Information >> Energy**: Agent stuck, repeating, not adapting
3. **Rapid oscillations**: E and I swinging back and forth

### In Your Tests

You didn't trigger void because:
- Your test parameters were relatively stable
- No extreme E-I imbalances
- Short test duration (< 100 updates for good statistics)

**To trigger void** (for testing):
```python
# Extreme energy-information imbalance
parameters = [
    0.95,  # Very high length_score (E contributor)
    0.9,   # High complexity (E contributor)
    0.2,   # Low info_score (I contributor) ← Imbalance!
    0.3,   # Low coherence
    0.0,
    0.7    # High drift
]
```

---

## Quick Interpretation Guide

### Check These First

1. **Coherence (ρ)**:
   - ρ > 0.85? ✅ Good
   - ρ < 0.60? ❌ Critical issue

2. **Risk Score**:
   - Risk < 0.30? ✅ Approve
   - Risk 0.30-0.70? ⚠️ Review
   - Risk > 0.70? ❌ Reject

3. **Void Active**:
   - No? ✅ Stable
   - Yes? ❌ System unstable

### Then Check These

4. **E, I, S**: Are they in healthy ranges?
   - E: 0.3-0.7
   - I: 0.9-1.0
   - S: 0.4-0.6

5. **λ₁**: Is it adapting reasonably?
   - Should stay 0.10-0.20 in normal operation
   - Rapid changes indicate system adjusting

---

## Common Patterns

### Healthy Operation

```
E:  0.5, I: 0.95, S: 0.5, V: 0.02
ρ:  0.92, λ₁: 0.12, Risk: 0.25
Decision: approve ✅
```

### Degraded but OK

```
E:  0.6, I: 0.88, S: 0.58, V: 0.08
ρ:  0.78, λ₁: 0.16, Risk: 0.45
Decision: revise ⚠️
```

### Critical State

```
E:  0.8, I: 0.75, S: 0.7, V: -0.12
ρ:  0.55, λ₁: 0.19, Risk: 0.82
Decision: reject ❌
Reason: Coherence critically low
```

### Void State

```
E:  0.9, I: 0.4, S: 0.8, V: 0.25
ρ:  0.70, λ₁: 0.20, Risk: 0.65
Void: YES ⚡
Decision: reject ❌
Reason: System in void state
```

---

## Next Steps

For more detail:
- **Parameter Examples**: See `docs/governance-parameter-examples.md` (to be created)
- **Troubleshooting**: See `docs/governance-troubleshooting.md` (to be created)
- **System Theory**: See `projects/governance-mcp-v1/README.md`

---

**Key Takeaway**: Focus on **Coherence** and **Risk Score** for quick decisions. The other metrics (E, I, S, V) provide deeper insight into *why* the system made that decision.
