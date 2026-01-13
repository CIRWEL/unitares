# UNITARES MCP System Pass-Through

## Overview

This document traces the complete data flow through the UNITARES governance system, from agent input to response output.

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MCP Protocol Layer                           │
│  src/mcp_server_sse.py, src/mcp_handlers/core.py                   │
│  - Receives tool calls from Claude/agents                           │
│  - Authentication, rate limiting, loop detection                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Governance Monitor Layer                         │
│  src/governance_monitor.py (UNITARESMonitor class)                  │
│  - Orchestrates governance cycle                                     │
│  - Manages state persistence                                         │
│  - Computes metrics and decisions                                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Governance Core Layer                            │
│  governance_core/dynamics.py, parameters.py, coherence.py           │
│  - UNITARES v4.1 differential equations                              │
│  - Parameter configurations (DEFAULT_PARAMS, V41_PARAMS)             │
│  - Coherence function C(V)                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Entry Point: MCP Tool Call

**File:** `src/mcp_handlers/core.py` → `handle_process_agent_update()`

When an agent calls `process_agent_update`, the handler:

```python
# Lines 697-703
result = await mcp_server.process_update_authenticated_async(
    agent_id=agent_id,
    api_key=api_key,
    agent_state=agent_state,  # {parameters, ethical_drift, complexity, ...}
    auto_save=True,
    confidence=confidence
)
```

**Input:**
```python
agent_state = {
    'parameters': [...],           # Agent parameters (deprecated)
    'ethical_drift': [η₁, η₂, η₃], # Ethical drift vector Δη
    'complexity': 0.5,             # Task complexity [0,1]
    'response_text': "...",        # Optional for risk estimation
    'task_type': "mixed"           # "convergent" | "divergent" | "mixed"
}
```

---

## 2. Authentication & Loop Detection

**File:** `src/mcp_server_std.py` → `process_update_authenticated_async()`

```python
# Lines 2285-2430
async def process_update_authenticated_async(...):
    # 1. Verify API key ownership
    is_valid, error_msg = await loop.run_in_executor(
        None, verify_agent_ownership, agent_id, api_key)
    
    # 2. Check for self-monitoring loops (prevents infinite update cycles)
    is_loop, loop_reason = await loop.run_in_executor(
        None, detect_loop_pattern, agent_id)
    
    # 3. Get or create monitor instance
    monitor = await loop.run_in_executor(None, get_or_create_monitor, agent_id)
    
    # 4. Call monitor's process_update (the core governance cycle)
    result = await loop.run_in_executor(
        None, 
        partial(monitor.process_update, agent_state, 
                confidence=confidence, task_type=task_type)
    )
```

---

## 3. Governance Cycle

**File:** `src/governance_monitor.py` → `UNITARESMonitor.process_update()`

The main governance cycle consists of:

```python
def process_update(self, agent_state, confidence=None, task_type="mixed"):
    # Step 1: UPDATE DYNAMICS
    self.update_dynamics(agent_state)  # ← Core UNITARES evolution
    
    # Step 2: DERIVE/CAP CONFIDENCE
    if confidence is None:
        confidence, metadata = derive_confidence(
            self.state, agent_id=self.agent_id)
    else:
        # Cap external confidence by system-derived confidence
        derived = derive_confidence(self.state, agent_id=self.agent_id)
        confidence = min(confidence, derived)
    
    # Step 3: CHECK VOID STATE
    void_active = self.check_void_state()
    
    # Step 4: UPDATE λ₁ (PI controller, every 5 cycles, if confidence >= threshold)
    if self.state.update_count % 5 == 0 and confidence >= THRESHOLD:
        self.update_lambda1()
    
    # Step 5: COMPUTE PHI (governance objective)
    phi = phi_objective(state, delta_eta, weights)
    
    # Step 6: GET VERDICT (PROCEED/CONTINUE/PAUSE/STOP)
    verdict = verdict_from_phi(phi)
    
    # Step 7: COLLECT METRICS
    metrics = self.get_metrics()
    
    return {'status': health, 'decision': verdict, 'metrics': metrics}
```

---

## 4. Core Dynamics: UNITARES v4.1 ODEs

**File:** `governance_core/dynamics.py` → `compute_dynamics()`

This is where the actual differential equations are computed:

```python
def compute_dynamics(state, delta_eta, theta, params, dt=0.1, 
                     noise_S=0.0, complexity=0.5):
    """
    UNITARES v4.1 Differential Equations (Section 3.2):
    
    Ė = α(I - E) - βₑES + γₑ‖Δη‖²                    (Eq. 7)
    İ = -kS + βᵢC(V) - γᵢI(1-I)                       (Eq. 8)
    Ṡ = -μS + λ₁‖Δη‖² - λ₂C(V) + β_complexity·C + dₛ (Eq. 9)
    V̇ = κ(E - I) - δV                                 (Eq. 10)
    """
    
    # Compute derived quantities
    d_eta_sq = drift_norm(delta_eta) ** 2   # ‖Δη‖²
    C = coherence(state.V, theta, params)    # C(V,Θ)
    lam1 = lambda1(theta, params)            # λ₁(Θ)
    lam2 = lambda2(theta, params)            # λ₂(Θ)
    
    # E dynamics
    dE_dt = (params.alpha * (I - E) 
             - params.beta_E * E * S 
             + params.gamma_E * d_eta_sq)
    
    # I dynamics (includes bistable γᵢI(1-I) term)
    dI_dt = (-params.k * S 
             + params.beta_I * C 
             - params.gamma_I * I * (1 - I))
    
    # S dynamics
    dS_dt = (-params.mu * S 
             + lam1 * d_eta_sq 
             - lam2 * C 
             + params.beta_complexity * complexity 
             + noise_S)
    
    # V dynamics
    dV_dt = params.kappa * (E - I) - params.delta * V
    
    # Euler integration with clipping
    E_new = clip(E + dE_dt * dt, E_min, E_max)
    I_new = clip(I + dI_dt * dt, I_min, I_max)
    S_new = clip(S + dS_dt * dt, S_min, S_max)
    V_new = clip(V + dV_dt * dt, V_min, V_max)
    
    return State(E_new, I_new, S_new, V_new)
```

---

## 5. Parameter Configuration

**File:** `governance_core/parameters.py`

Parameters can be selected via environment variables:

```bash
# Option 1: Use v4.1 paper-aligned preset
export UNITARES_PARAMS_PROFILE=v41

# Option 2: Custom JSON override
export UNITARES_PARAMS_JSON='{"beta_I": 0.05, "alpha": 0.5}'
```

**Key Parameter Differences:**

| Parameter | DEFAULT | V41 (Paper) | Effect |
|-----------|---------|-------------|--------|
| alpha     | 0.4     | 0.5         | E-I coupling rate |
| beta_I    | **0.3** | **0.05**    | Coherence boost to I (6x difference!) |
| gamma_I   | 0.25    | 0.3         | I self-regulation (bistability) |

```python
# parameters.py
def get_active_params() -> DynamicsParams:
    profile = os.getenv("UNITARES_PARAMS_PROFILE", "default")
    base = V41_PARAMS if profile == "v41" else DEFAULT_PARAMS
    
    # Apply JSON overrides if present
    json_override = os.getenv("UNITARES_PARAMS_JSON")
    if json_override:
        overrides = json.loads(json_override)
        # merge overrides into base...
    
    return params
```

---

## 6. Coherence Function C(V)

**File:** `governance_core/coherence.py`

```python
def coherence(V: float, theta: Theta, params: DynamicsParams) -> float:
    """
    C(V) = (Cmax/2) * (1 + tanh(C₁ · V))    (Eq. 11)
    
    Properties:
    - C(0) = Cmax/2 (baseline coherence)
    - C(V → ∞) → Cmax
    - C(V → -∞) → 0
    """
    return (params.Cmax / 2.0) * (1.0 + np.tanh(theta.C1 * V))
```

---

## 7. Metrics Computation

**File:** `src/governance_monitor.py` → `get_metrics()`

Returns comprehensive metrics including the new v4.1 features:

```python
def get_metrics(self, include_state=False):
    result = {
        # Core EISV
        'E': self.state.E,
        'I': self.state.I, 
        'S': self.state.S,
        'V': self.state.V,
        'coherence': self.state.coherence,
        
        # Derived
        'risk_score': ...,
        'regime': ...,  # EXPLORATION, CONVERGENCE, DIVERGENCE, STABLE
        
        # UNITARES v4.1 additions (when profile=v41)
        'unitares_v41': {
            'params_profile': 'v41',
            'basin': 'high' | 'low' | 'boundary',
            'basin_warning': '...' if I < 0.55,
            'equilibrium': {
                'I_target': 0.91,
                'S_target': 0.001,
                'E_target': 0.91
            },
            'convergence': {
                'equilibrium_distance': float,
                'estimated_updates_to_eps': int,
                'eps': 0.02
            }
        }
    }
```

---

## 8. Basin Detection (Bistability)

**CRITICAL:** UNITARES v4.1 has TWO stable equilibria due to the γᵢI(1-I) term:

```
           I=1.0 ─────────────────────────────────
                 │                               │
    HIGH BASIN   │     ● HIGH EQUILIBRIUM        │  I* ≈ 0.91
                 │       (healthy)               │
           I=0.5 ├───────────────────────────────┤  BASIN BOUNDARY
                 │                               │
    LOW BASIN    │     ○ LOW EQUILIBRIUM         │  I* ≈ 0.09  
                 │       (collapsed)             │
           I=0.0 ─────────────────────────────────
```

**Basin Check Logic (lines 1277-1287):**
```python
if profile == "v41":
    if I < 0.45:
        basin = "low"
        basin_warning = "LOW basin: high risk of collapse equilibrium"
    elif I < 0.55:
        basin = "boundary"
        basin_warning = "Near basin boundary: small shocks can flip"
    else:
        basin = "high"
```

---

## 9. Response Output

Final response structure returned to the agent:

```python
{
    'success': True,
    'agent_id': 'agent-name',
    'decision': {
        'verdict': 'PROCEED' | 'CONTINUE' | 'PAUSE' | 'STOP',
        'reason': '...',
        'constraints': [...]
    },
    'metrics': {
        'E': 0.75,
        'I': 0.82,
        'S': 0.15,
        'V': 0.02,
        'coherence': 0.51,
        'risk_score': 0.23,
        'health_status': 'healthy',
        'regime': 'CONVERGENCE'
    },
    'unitares_v41': {
        'params_profile': 'v41',
        'basin': 'high',
        'basin_warning': None,
        'convergence': {
            'equilibrium_distance': 0.12,
            'estimated_updates_to_eps': 45
        }
    },
    'convergence_guidance': '~45 updates to equilibrium'
}
```

---

## Complete Data Flow Diagram

```
Agent Tool Call: process_agent_update
        │
        │  agent_state = {ethical_drift, complexity, ...}
        ▼
┌──────────────────────────────────┐
│  MCP Handler (core.py)           │
│  - Validate inputs               │
│  - Extract parameters            │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│  Auth Layer (mcp_server_std.py)  │
│  - verify_agent_ownership()      │
│  - detect_loop_pattern()         │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│  UNITARESMonitor.process_update()│
│  1. update_dynamics()  ──────────┼─────┐
│  2. derive_confidence()          │     │
│  3. check_void_state()           │     │
│  4. update_lambda1() (gated)     │     │
│  5. phi_objective()              │     │
│  6. verdict_from_phi()           │     │
│  7. get_metrics() ───────────────┼──┐  │
└───────────────┬──────────────────┘  │  │
                │                      │  │
                │         ┌────────────┘  │
                │         │               │
                │         ▼               ▼
                │  ┌──────────────────────────────────┐
                │  │  governance_core/dynamics.py     │
                │  │                                  │
                │  │  step_state() → compute_dynamics()│
                │  │                                  │
                │  │  Ė = α(I-E) - βₑES + γₑ‖Δη‖²    │
                │  │  İ = -kS + βᵢC(V) - γᵢI(1-I)    │
                │  │  Ṡ = -μS + λ₁‖Δη‖² - λ₂C(V) +.. │
                │  │  V̇ = κ(E-I) - δV                │
                │  │                                  │
                │  │  get_active_params()             │
                │  │  ├─ DEFAULT_PARAMS               │
                │  │  └─ V41_PARAMS (opt-in)          │
                │  └──────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│  Response Assembly               │
│  - metrics dict                  │
│  - health_status                 │
│  - unitares_v41 block            │
│    ├─ basin                      │
│    ├─ basin_warning              │
│    └─ convergence                │
└───────────────┬──────────────────┘
                │
                ▼
         Return to Agent
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/mcp_handlers/core.py` | MCP tool handler entry point |
| `src/mcp_server_std.py` | Authentication, loop detection |
| `src/governance_monitor.py` | UNITARESMonitor orchestration |
| `governance_core/dynamics.py` | UNITARES v4.1 ODEs |
| `governance_core/parameters.py` | Parameter definitions |
| `governance_core/coherence.py` | C(V) coherence function |
| `governance_core/scoring.py` | Φ objective, verdicts |

---

## Testing the System

```bash
# Run core dynamics tests
cd /Users/cirwel/projects/governance-mcp-v1
python -m pytest tests/test_governance_core.py -v

# Test v4.1 parameter selection
UNITARES_PARAMS_PROFILE=v41 python -c "
from governance_core.parameters import get_active_params
p = get_active_params()
print(f'beta_I = {p.beta_I}')  # Should be 0.05
"

# Run reference implementation
python experiments/unitares_v41_reference.py
```
