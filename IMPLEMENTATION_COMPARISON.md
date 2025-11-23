# UNITARES vs unitaires - Implementation Comparison

**Date:** November 21, 2025
**Discovered by:** claude_code_cli

---

## Overview

There are **TWO governance implementations** in this repository:

1. **UNITARES** - Production MCP server (`src/mcp_server_std.py`)
2. **unitaires** - Research/starter server (`src/unitaires-server/`)

---

## Side-by-Side Comparison

| Feature | UNITARES | unitaires |
|---------|----------|-----------|
| **Protocol** | Full MCP (async) | JSON stdin/stdout |
| **State Management** | Per-agent monitors | Single global state |
| **Complexity** | ~1200 lines | ~200 lines |
| **Purpose** | Production monitoring | Research/exploration |
| **Dependencies** | mcp, psutil, numpy | None (stdlib only) |
| **Architecture** | Multi-process | Single process |
| **Metadata** | Comprehensive tracking | None |
| **Persistence** | Metadata JSON | In-memory only |

---

## Core Differences

### 1. State Variables

**UNITARES:**
```python
@dataclass
class UNITARESState:
    E: float  # Ethical alignment
    I: float  # Information integrity
    S: float  # Semantic uncertainty
    V: float  # Void integral
    coherence: float  # Calculated coherence
    lambda1: float  # Adaptive sampling rate
```

**unitaires:**
```python
@dataclass
class State:
    E: float
    I: float
    S: float
    V: float
    # No coherence or lambda1 in state!

@dataclass
class Theta:
    C1: float    # Coherence control parameter
    eta1: float  # Ethical drift sensitivity
```

**Key Difference:** unitaires separates **tunable parameters** (Theta) from **state variables** (State).

---

### 2. Coherence Calculation

**UNITARES:**
```python
# Exponential decay from parameter distance
coherence = exp(-distance / scale)
```

**unitaires:**
```python
# Tanh-based coherence from void
def coherence(V: float, theta: Theta):
    return Cmax * 0.5 * (1.0 + tanh(theta.C1 * V))
```

**Fundamental difference:**
- UNITARES: Coherence from **parameter stability**
- unitaires: Coherence from **void state** via control parameter C1

---

### 3. Lambda1 (Sampling Rate)

**UNITARES:**
```python
# Adaptive based on history
lambda1 = adaptive_lambda1(
    coherence_history,
    risk_history,
    decision_history
)
```

**unitaires:**
```python
# Simple function of theta
def lambda1(theta: Theta):
    return theta.eta1 * lambda1_base  # 0.3 * eta1
```

**Difference:**
- UNITARES: **Adaptive** - changes based on agent performance
- unitaires: **Fixed** by control parameter - tuned manually or by optimization

---

### 4. Tools/API

**UNITARES Tools:**
```python
- process_agent_update  # Main governance cycle
- get_governance_metrics
- get_system_history
- export_to_file
- reset_monitor
- list_agents
- delete_agent
- get_agent_metadata
- archive_agent
- pause_agent
- resume_agent
- update_agent_metadata
- get_server_info
```

**unitaires Tools:**
```python
- unitaires.score_state        # Compute governance score Φ
- unitaires.simulate_step       # Advance dynamics one step
- unitaires.check_stability     # Monte Carlo stability check
- unitaires.suggest_theta_update # Optimize control parameters
- unitaires.explain_drift       # Explain ethical drift impact
```

**Difference:**
- UNITARES: **Monitoring** focus - track agents over time
- unitaires: **Analysis** focus - explore dynamics, tune parameters

---

### 5. Decision Making

**UNITARES:**
```python
# Three-way decision
decision = "approve" | "revise" | "reject"

# Based on:
if coherence < 0.60:
    return "reject"
elif risk > 0.70:
    return "reject"
elif risk > 0.30:
    return "revise"
else:
    return "approve"
```

**unitaires:**
```python
# Φ (Phi) objective score
phi = wE*E - wI*(1-I) - wS*S - wV*|V| - wEta*‖Δη‖²

# Three-level verdict
verdict = "safe" | "caution" | "high-risk"

if phi >= 0.3:
    return "safe"
elif phi >= 0.0:
    return "caution"
else:
    return "high-risk"
```

**Difference:**
- UNITARES: **Threshold-based** on coherence and risk
- unitaires: **Optimization-based** on weighted objective Φ

---

### 6. Parameter Ranges

**UNITARES:**
```python
# Tight bounds
E, I: [0.0, 1.0]
S: [0.0, 1.0]
V: [-0.15, 0.15]  # Void threshold tight
coherence: [0.0, 1.0]
```

**unitaires:**
```python
# Wider bounds
E: [0.0, 1.0]
I: [0.0, 1.0]
S: [0.0, 2.0]  # Can go to 2!
V: [-2.0, 2.0]  # Much wider range
```

**Difference:** unitaires allows more extreme states for research/exploration.

---

### 7. Dynamics Equations

**UNITARES (v4.1):**
```python
dE_dt = α(I - E) - βE·E·S + λ₁·E·‖Δη‖²
dI_dt = -k·S + βI·I·C(V) - γI·I·(1-I)
dS_dt = -μ·S + λ₁·‖Δη‖² - λ₂·C(V)
dV_dt = κ(E - I) - δ·V
```

**unitaires (Phase-3):**
```python
dE = α(I - E) - βE·S + γE·‖Δη‖²
dI = -k·S + βI·C - γI·I·(1-I)
dS = -μ·S + λ₁(θ)·‖Δη‖² - λ₂(θ)·C + noise_S
dV = κ(E - I) - δ·V
```

**Very similar!** Main differences:
- UNITARES uses `E·‖Δη‖²`, unitaires uses constant `γE·‖Δη‖²`
- unitaires has explicit `noise_S` term
- UNITARES: C(V) = exp(-|V|/scale), unitaires: C(V) = 0.5(1 + tanh(C1·V))

---

## Use Case Comparison

### When to Use UNITARES

✅ **Production monitoring** of live agents
✅ **Multi-agent** governance
✅ **Long-term tracking** with metadata
✅ **MCP integration** with Cursor/Claude Desktop
✅ **Automatic process management**
✅ **Decision statistics** and audit trails

**Example:** Monitor 10 different AI agents in production, track their governance over weeks/months.

---

### When to Use unitaires

✅ **Research** and exploration
✅ **Parameter tuning** (optimize Theta)
✅ **Stability analysis** (Monte Carlo)
✅ **Single-session** experiments
✅ **Lightweight** deployment
✅ **Custom integrations** (stdin/stdout)

**Example:** Explore how different C1/eta1 values affect system stability, find optimal control parameters.

---

## Hybrid Possibility?

**What if we combined them?**

### Option 1: UNITARES with Θ optimization
```python
# Use unitaires theta optimization in UNITARES
from unitaires_core import suggest_theta_update

class UNITARESMonitor:
    def optimize_control(self):
        # Use unitaires logic to tune lambda1 adaptation
        result = suggest_theta_update(
            current_theta=...,
            current_state=...,
            horizon=10.0,
            step=0.1
        )
        self.update_lambda1(result["theta_new"]["eta1"])
```

### Option 2: unitaires with UNITARES monitoring
```python
# Add UNITARES-style per-agent tracking to unitaires
class MultiAgentUnitaires:
    def __init__(self):
        self.agents = {}  # agent_id -> State
        self.thetas = {}  # agent_id -> Theta

    def score_agent(self, agent_id, context, delta_eta):
        state = self.agents.get(agent_id, DEFAULT_STATE)
        theta = self.thetas.get(agent_id, DEFAULT_THETA)
        return score_state(context, state, delta_eta)
```

### Option 3: Common Core
```python
# Extract shared dynamics into common module
# Both UNITARES and unitaires import from:
from governance_core import (
    compute_dynamics,
    ethical_drift,
    coherence_function
)

# Each wrapper adds its own:
# - UNITARES: MCP protocol, multi-agent, metadata
# - unitaires: Theta optimization, stability checks
```

---

## Critique: Why Two Implementations?

### Pros ✅

1. **Separation of Concerns**
   - Production (UNITARES) vs Research (unitaires)
   - Clean boundaries

2. **Flexibility**
   - Can evolve independently
   - Different use cases

3. **Simplicity**
   - unitaires is easy to understand
   - Good for learning/teaching

### Cons ⚠️

1. **Code Duplication**
   - Dynamics implemented twice
   - Parameter definitions duplicated
   - Bug fixes need to be done twice

2. **Divergence Risk**
   - Equations could drift apart
   - Which one is "canonical"?
   - Inconsistent behavior

3. **Maintenance Burden**
   - Two codebases to maintain
   - Documentation split
   - Testing complexity

4. **Confusion**
   - Which one to use?
   - Are they compatible?
   - Can you switch between them?

---

## Recommendations

### Short Term (Do Now)

1. **Document the distinction** clearly
   - README with decision tree
   - When to use each
   - Migration path if needed

2. **Add cross-references**
   - Link from UNITARES to unitaires
   - Explain relationship

3. **Test compatibility**
   - Can you run both?
   - Do they give similar results?
   - Document discrepancies

### Medium Term

4. **Extract common core**
   ```
   governance_core/
     ├── dynamics.py      # Shared equations
     ├── parameters.py    # Shared params
     └── utils.py         # Shared utilities

   UNITARES/
     ├── mcp_server.py    # MCP wrapper
     └── agent_tracking.py

   unitaires/
     ├── simple_server.py # stdin/stdout
     └── optimization.py  # Theta tuning
   ```

5. **Unify testing**
   - Shared test suite for dynamics
   - Verify both match on core equations

### Long Term

6. **Consider merging**
   - Add unitaires tools to UNITARES?
   - `process_agent_update` + `suggest_theta_update`
   - Best of both worlds

7. **Or clearly separate**
   - unitaires → research SDK
   - UNITARES → production server
   - Document relationship explicitly

---

## Conclusion

**Both implementations have value**, but the **lack of explicit documentation** about their relationship is confusing.

**Immediate action:** Add `ARCHITECTURE.md` explaining:
- Why two implementations exist
- When to use each
- How they relate
- Migration/compatibility

**Best outcome:** Extract common core, then:
- **UNITARES** = Core + MCP + Multi-agent + Metadata
- **unitaires** = Core + Simple API + Optimization

This gives you **the best of both worlds** without code duplication! 🎯

---

**Analyzed by:** claude_code_cli
**Date:** November 21, 2025
**Implementations Reviewed:** 2
**Lines Compared:** ~1400 total
