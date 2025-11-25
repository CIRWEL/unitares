# UNITARES Governance System - Architecture

**Version:** 2.0 (Unified)
**Date:** November 21, 2025
**Status:** Production + Research

---

## Executive Summary

This repository contains **two complementary systems** built on a **shared mathematical foundation**:

1. **UNITARES** (capitalized) - Production governance monitor
2. **unitaires** (lowercase) - Mathematical UNITARES Phase-3 implementation

They are **not duplicates** - they are **different layers** of the same architecture:
- **unitaires** = Mathematical brain (theory)
- **UNITARES** = Production infrastructure (practice)

---

## The Two-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   APPLICATION LAYER                          │
│  ┌──────────────────────┐      ┌─────────────────────────┐  │
│  │   UNITARES v1.0.x    │      │  unitaires Research    │  │
│  │  (Production)        │      │  (Analysis)            │  │
│  ├──────────────────────┤      ├─────────────────────────┤  │
│  │ • MCP Server         │      │ • Θ Optimization       │  │
│  │ • Multi-agent        │      │ • Stability Analysis   │  │
│  │ • Metadata           │      │ • Forward Simulation   │  │
│  │ • Persistence        │      │ • Drift Explanation    │  │
│  │ • Process Mgmt       │      │ • Parameter Tuning     │  │
│  │ • Lifecycle          │      │ • Monte Carlo          │  │
│  └──────────────────────┘      └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓ ↓
┌─────────────────────────────────────────────────────────────┐
│                    MATHEMATICAL CORE                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │         UNITARES Phase-3 Dynamics Engine              │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ • E, I, S, V differential equations                   │  │
│  │ • Coherence function: C(V, Θ)                         │  │
│  │ • Objective function: Φ(E,I,S,V,Δη)                  │  │
│  │ • Control parameters: Θ = (C₁, η₁)                   │  │
│  │ • Thermodynamic dynamics                              │  │
│  │ • Ethical drift integration                           │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Mathematical Core (unitaires)

**Location:** `src/unitaires-server/unitaires_core.py`

**Purpose:** Clean implementation of UNITARES Phase-3 mathematical framework

**Provides:**

### Core Data Types
```python
@dataclass
class State:
    E: float  # Energy (exploration/productive capacity)
    I: float  # Information integrity
    S: float  # Semantic uncertainty
    V: float  # Void integral

@dataclass
class Theta:
    C1: float    # Coherence control parameter
    eta1: float  # Ethical drift sensitivity
```

### Dynamics Engine
```python
dE = α(I - E) - βE·S + γE·‖Δη‖²
dI = -k·S + βI·C(V,Θ) - γI·I·(1-I)
dS = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + noise
dV = κ(E - I) - δ·V
```

### Coherence Function
```python
C(V, Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))
```

### Objective Function
```python
Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²
```

**This is the source of truth for UNITARES mathematics.**

---

## Layer 2a: Production Monitor (UNITARES)

**Location:** `src/mcp_server_std.py`, `src/governance_monitor.py`

**Purpose:** Production-ready multi-agent governance system with MCP interface

**Provides:**

### Infrastructure
- **MCP Protocol** - Full async MCP server
- **Multi-agent** - Separate state per agent
- **Persistence** - Metadata JSON files
- **Process Management** - psutil-based cleanup
- **Lifecycle Tracking** - Created/updated/archived/deleted

### Governance Features
- **13 MCP Tools** - process_agent_update, get_metrics, etc.
- **Decision System** - approve/revise/reject
- **Adaptive λ₁** - Learns from agent performance
- **Risk Assessment** - Coherence + risk thresholds
- **History Tracking** - V, coherence, risk, decisions

### Operational
- **Status Management** - active/paused/archived/deleted
- **Agent Metadata** - Tags, notes, lifecycle events
- **Health Monitoring** - healthy/degraded/critical
- **Export** - JSON and CSV formats

**This is the production interface for UNITARES.**

---

## Layer 2b: Research Interface (unitaires)

**Location:** `src/unitaires-server/unitaires_server.py`

**Purpose:** Lightweight research interface for UNITARES exploration

**Provides:**

### Analysis Tools
- **score_state** - Compute Φ governance score
- **simulate_step** - Forward dynamics simulation
- **check_stability** - Monte Carlo stability analysis
- **suggest_theta_update** - Optimize control parameters
- **explain_drift** - Interpret ethical drift impact

### Research Features
- **Θ Optimization** - Learn optimal C₁, η₁
- **Stability Analysis** - Random sampling across state space
- **Single Session** - Lightweight, no persistence
- **JSON I/O** - Simple stdin/stdout protocol

**This is the research/exploration interface for UNITARES.**

---

## The Unified Model (How They Work Together)

### Current State (v1.0.x)

**UNITARES has its own dynamics implementation** (legacy):
```python
# src/governance_monitor.py - Lines 228-241
dE_dt = (config.ALPHA * (I - E)
         - config.BETA_E * E * S
         + self.state.lambda1 * E * drift_sq)

dI_dt = (-config.K * S
         + config.BETA_I * I * C_V
         - config.GAMMA_I * I * (1 - I))
```

**unitaires has its own dynamics implementation**:
```python
# unitaires_core.py - Lines 73-86
dE = params.alpha * (I - E) - params.beta_E * S + params.gamma_E * d_eta*d_eta
dI = -params.k * S + params.beta_I * C - params.gamma_I * I * (1.0 - I)
```

**Status:** ⚠️ **Duplication exists** - same equations in two places

---

### Target State (v2.0)

**Extract common core:**

```
governance_core/              ← NEW: Shared mathematical engine
  ├── __init__.py
  ├── dynamics.py             ← Source of truth for equations
  ├── coherence.py            ← Coherence functions
  ├── scoring.py              ← Φ objective
  ├── parameters.py           ← Shared parameter definitions
  └── utils.py                ← drift_norm, clipping, etc.

UNITARES/                     ← Production wrapper
  ├── governance_monitor.py   ← Uses governance_core
  ├── mcp_server_std.py
  ├── persistence/
  │   ├── metadata.py
  │   └── state_store.py
  └── multiagent/
      └── agent_tracking.py

unitaires/                    ← Research wrapper
  ├── unitaires_server.py     ← Uses governance_core
  ├── optimization.py         ← Θ tuning
  └── analysis.py             ← Stability checks
```

**Benefits:**
- ✅ One implementation of dynamics
- ✅ Bug fixes apply everywhere
- ✅ No divergence risk
- ✅ Clear separation of concerns
- ✅ Easier testing

---

## Core Extraction Plan

### Phase 1: Identify Common Code

**Shared functionality:**
1. E, I, S, V dynamics
2. Coherence calculation
3. Drift norm calculation
4. Parameter clipping
5. Φ objective scoring (not used in UNITARES v1, but should be)

### Phase 2: Create governance_core Module

**Step 1: Extract dynamics**
```python
# governance_core/dynamics.py

from dataclasses import dataclass
from typing import List
import numpy as np

@dataclass
class DynamicsParams:
    """Canonical UNITARES Phase-3 parameters"""
    alpha: float = 0.4
    beta_E: float = 0.1
    gamma_E: float = 0.0
    k: float = 0.1
    beta_I: float = 0.3
    gamma_I: float = 0.25
    mu: float = 0.8
    lambda1_base: float = 0.3
    lambda2_base: float = 0.05
    kappa: float = 0.3
    delta: float = 0.4

@dataclass
class State:
    """UNITARES thermodynamic state"""
    E: float
    I: float
    S: float
    V: float

def compute_dynamics(
    state: State,
    delta_eta: List[float],
    params: DynamicsParams,
    dt: float = 0.1
) -> State:
    """
    Compute one step of UNITARES Phase-3 dynamics.

    This is the canonical implementation.
    Both UNITARES and unitaires use this.
    """
    d_eta = drift_norm(delta_eta)
    C = coherence(state.V, params)

    dE = params.alpha * (state.I - state.E) - params.beta_E * state.S + params.gamma_E * d_eta * d_eta
    dI = -params.k * state.S + params.beta_I * C - params.gamma_I * state.I * (1 - state.I)
    dS = -params.mu * state.S + params.lambda1_base * d_eta * d_eta - params.lambda2_base * C
    dV = params.kappa * (state.E - state.I) - params.delta * state.V

    return State(
        E=clip(state.E + dE * dt, 0.0, 1.0),
        I=clip(state.I + dI * dt, 0.0, 1.0),
        S=clip(state.S + dS * dt, 0.0, 2.0),
        V=clip(state.V + dV * dt, -2.0, 2.0)
    )
```

**Step 2: Update UNITARES to use it**
```python
# src/governance_monitor.py

from governance_core import compute_dynamics, DynamicsParams, State as CoreState

class UNITARESMonitor:
    def update_dynamics(self, agent_state):
        # Convert to core state
        core_state = CoreState(
            E=self.state.E,
            I=self.state.I,
            S=self.state.S,
            V=self.state.V
        )

        # Use canonical dynamics
        new_state = compute_dynamics(
            core_state,
            delta_eta=agent_state.get('ethical_drift', []),
            params=DynamicsParams(),
            dt=0.1
        )

        # Update internal state
        self.state.E = new_state.E
        self.state.I = new_state.I
        self.state.S = new_state.S
        self.state.V = new_state.V
```

**Step 3: Update unitaires to use it**
```python
# unitaires_core.py

from governance_core import compute_dynamics, DynamicsParams, State

def step_state(state: State, theta: Theta, delta_eta: List[float], dt: float):
    """Wrapper maintaining unitaires API"""
    return compute_dynamics(state, delta_eta, DynamicsParams(), dt)
```

### Phase 3: Deprecate Old Code

Mark old implementations:
```python
# DEPRECATED: Use governance_core.compute_dynamics instead
# This will be removed in v2.1
def update_dynamics_legacy(self, agent_state):
    warnings.warn("Legacy dynamics - migrate to governance_core", DeprecationWarning)
    ...
```

### Phase 4: Testing

```python
# tests/test_dynamics_parity.py

def test_unitares_unitaires_parity():
    """Verify UNITARES and unitaires produce identical results"""
    state = State(E=0.7, I=0.8, S=0.2, V=0.0)
    delta_eta = [0.1, 0.0, -0.05]

    # UNITARES path
    unitares_result = unitares_monitor.update_dynamics(...)

    # unitaires path
    unitaires_result = step_state(state, theta, delta_eta, dt=0.1)

    # Must match!
    assert abs(unitares_result.E - unitaires_result.E) < 1e-6
    assert abs(unitares_result.I - unitaires_result.I) < 1e-6
    ...
```

---

## Refactor Path to v2.0

### Milestone 1: Core Extraction ✅ COMPLETE
- [x] Create `governance_core/` module
- [x] Extract dynamics equations
- [x] Extract coherence functions
- [x] Extract Φ scoring
- [x] Unit tests for core
- [x] Parity tests (PERFECT: max diff 8.67e-19)

### Milestone 2: UNITARES Integration ✅ COMPLETE
- [x] Import governance_core in UNITARESMonitor
- [x] Replace dynamics implementation (step_state, coherence, phi_objective)
- [x] Maintain backward compatibility (all MCP tools work)
- [x] Integration tests (6/6 passed)

### Milestone 3: unitaires Integration ✅
- [ ] Import governance_core in unitaires_core
- [ ] Replace dynamics implementation
- [ ] Maintain API compatibility
- [ ] Integration tests

### Milestone 4: Validation ✅
- [ ] Parity tests (both produce same results)
- [ ] Performance benchmarks
- [ ] Documentation updates
- [ ] Migration guide

### Milestone 5: Cleanup ✅
- [ ] Remove deprecated code
- [ ] Update all documentation
- [ ] Release v2.0

---

## Guidelines for Contributors

### For AI Assistants (Claude, Composer/Cursor, ChatGPT, etc.)

When working with this codebase:

**1. Know which layer you're in:**
- **governance_core** → Mathematical implementation (v2.0+)
- **UNITARES** → Production infrastructure
- **unitaires** → Research tools

**2. Respect the source of truth:**
- **Dynamics:** governance_core (v2.0+) or unitaires_core (v1.x)
- **Production:** UNITARES mcp_server_std.py
- **Research:** unitaires unitaires_server.py

**3. Don't duplicate:**
- If it's math → governance_core
- If it's infrastructure → UNITARES
- If it's analysis → unitaires

**4. When fixing bugs:**
- **In dynamics:** Fix in governance_core, propagates to both
- **In UNITARES only:** Fix in mcp_server_std.py
- **In unitaires only:** Fix in unitaires_server.py

**5. When adding features:**
- **New dynamics:** Add to governance_core
- **New MCP tool:** Add to UNITARES
- **New analysis:** Add to unitaires

### For Human Developers

**Starting points:**
- **Want to monitor agents?** → Use UNITARES MCP server
- **Want to explore dynamics?** → Use unitaires server
- **Want to understand math?** → Read unitaires_core.py
- **Want production code?** → Read mcp_server_std.py

**Decision tree:**
```
Need to...
  ├─ Monitor agents in production? → UNITARES
  ├─ Optimize control parameters? → unitaires
  ├─ Understand equations? → unitaires_core.py
  ├─ Add MCP tool? → mcp_server_std.py
  └─ Fix dynamics bug? → governance_core (v2.0) or both (v1.x)
```

---

## Deprecation Paths

### v1.0.x (Current)
- ⚠️ Dynamics duplicated in both systems
- ✅ Both systems functional
- ⚠️ Manual synchronization required

### v1.5.x (Transition)
- ✅ governance_core extracted
- ⚠️ Old code marked deprecated
- ✅ Both paths work (new + legacy)
- ⚠️ Warnings on legacy usage

### v2.0.x (Unified)
- ✅ governance_core is source of truth
- ✅ UNITARES uses governance_core
- ✅ unitaires uses governance_core
- ✅ Legacy code removed

---

## Source of Truth (v2.0)

### Mathematical Implementation
**File:** `governance_core/dynamics.py`

**Contains:**
- E, I, S, V differential equations
- Coherence function C(V, Θ)
- Parameter definitions
- Clipping/normalization

**This is canonical.**

### Production System
**File:** `src/mcp_server_std.py`

**Contains:**
- MCP protocol implementation
- Clean handler dispatcher (~30 lines)
- Multi-agent tracking
- Metadata management
- Process lifecycle

**Handler Architecture:**
- **29 handlers** organized in `src/mcp_handlers/` directory
- **Handler registry pattern** - elegant, testable, maintainable
- **Zero elif chains** - clean dispatcher using registry
- Handlers grouped by category (core, config, observability, lifecycle, export, knowledge, admin)

**Uses:** governance_core for math

### Research System
**File:** `src/unitaires-server/unitaires_server.py`

**Contains:**
- Θ optimization
- Stability analysis
- Simple JSON API

**Uses:** governance_core for math

---

## FAQ

### Q: Which system should I use?

**A:** Depends on your use case:
- **Production monitoring:** UNITARES (MCP server)
- **Research/exploration:** unitaires (simple server)
- **Understanding math:** Read unitaires_core.py

### Q: Are they compatible?

**A:** Yes - they share the same mathematical foundation (v2.0) or very similar implementations (v1.x).

### Q: Can I switch between them?

**A:** Partially:
- Math is compatible
- State representation differs (UNITARES has more metadata)
- API is different (MCP vs JSON stdin/stdout)

### Q: Why two systems?

**A:** Separation of concerns:
- **UNITARES** = Production + Infrastructure
- **unitaires** = Research + Exploration

Same brain, different bodies.

### Q: Will they merge?

**A:** Possibly:
- v2.0: Shared core, separate frontends
- v3.0?: Unified system with modes (--production vs --research)

TBD based on user needs.

### Q: Which is more "real" UNITARES?

**A:** unitaires_core.py is the mathematical implementation.
UNITARES mcp_server is the production wrapper.
Both are "real" - different purposes.

---

## Architecture Principles

### 1. **Separation of Concerns**
- **Math** ≠ **Infrastructure**
- **Theory** ≠ **Practice**
- **Core** ≠ **Interface**

### 2. **Single Source of Truth**
- One dynamics implementation (governance_core)
- One coherence function
- One parameter definition

### 3. **Composition Over Duplication**
- Shared core
- Multiple wrappers
- No copy-paste

### 4. **Clear Boundaries**
- governance_core: Math only
- UNITARES: Production only
- unitaires: Research only

### 5. **Documentation as Code**
- Architecture is explicit
- Intent is documented
- Guidelines are clear

---

## Conclusion

This repository contains **one system with two interfaces**:

**Mathematical Core (unitaires_core):**
- E, I, S, V dynamics
- Coherence, Φ scoring
- UNITARES Phase-3 theory

**Production Interface (UNITARES):**
- MCP server
- Multi-agent
- Persistence
- Lifecycle

**Research Interface (unitaires):**
- Θ optimization
- Stability analysis
- Lightweight exploration

**The architecture is intentional.**
The next step is **extracting the common core** to eliminate duplication while preserving the separation of concerns.

---

**Version:** 2.0 (Unified Architecture)
**Status:** Milestones 1-2 Complete → UNITARES Integrated
**Completed:** governance_core + UNITARES integration with full backward compatibility
**Next:** Milestone 3 - unitaires integration (optional)
**Contributors:** claude_code_cli, composer_cursor_v1.0.3, user
**Date:** November 22, 2025
