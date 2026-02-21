# UNITARES Unified Architecture

**What exists, what's connected, what's not.**

```
                         THE ACTUAL SYSTEM (Feb 2026)
                         ============================

  Raspberry Pi Zero 2W                              Mac (governance-mcp)
  (anima-mcp, port 8766)                            (port 8767)
  ========================                           ========================

  BME280 ─── temp, humidity, pressure
  VEML7700 ── light (reads own LEDs)     HTTP POST /mcp/
  CPU stats ── load, memory, freq        ──────────────────►
                    │                    process_agent_update     EISV dynamics
                    ▼                    (every ~60s)             ┌──────────┐
           computational_neural.py                               │ dE/dt    │
           (delta/theta/alpha/beta/gamma)                        │ dI/dt    │
                    │                                            │ dS/dt    │
                    ▼                                            │ dV/dt    │
              anima_state.py                                     └────┬─────┘
              (warmth, clarity,                                       │
               stability, presence)                             coherence C(V)
                    │                                           risk_score
                    ├──────────► eisv_mapper.py                 margin level
                    │            E = warmth + neural                  │
                    │            I = clarity + alpha                  │
                    │            S = 1 - stability              ◄────┘
                    │            V = (1-presence)*0.3       {"action":"proceed",
                    │                    │                  "margin":"comfortable"}
                    │                    ▼
                    │            unitares_bridge.py
                    │            (check_in every 60s,
                    │             fallback to local
                    │             if Mac unreachable)
                    │
                    ▼
              display/screens.py
              (DrawingEISV)──────────► SECOND EISV INSTANCE
              E=0.7, I=0.2, S=0.5         dE = a(I-E) - bE*S + gE*drift^2
                    │                      dI = bI*C - k*S - gI*I
                    │                      dS = -u*S + l1*drift^2 - l2*C
                    │                      dV = k(I-E) - d*V  ← FLIPPED
                    │                           ↑
                    │                      V flipped because here
                    ▼                      I > E = focused finishing
              display/leds.py                  (opposite of governance
              LED brightness pipeline:          where E > I = stable)
              base → auto → pulse →
              activity → dimmer →
              sine pulse ("alive")
```

## Two Nervous Systems

That's the honest picture. There are **two independent EISV instances**:

### 1. Drawing EISV (Pi-local, proprioceptive)

- **Location**: `anima-mcp/src/anima_mcp/display/screens.py` lines 393-416, 3593-3648
- **Drives**: Drawing behavior (energy depletion, save threshold, coherence modulation)
- **Inputs**: Era state intentionality, gesture entropy (Shannon over last 20), gesture switching rate
- **V is flipped**: `dV = kappa(I - E)` so coherence rises when I > E (focused finishing)
- **Coherence formula**: Same math: `C(V) = Cmax * 0.5 * (1 + tanh(C1 * V))`
- **Cycle**: EISV step runs per mark → coherence modulates energy drain → affects drawing lifetime
- **This is real proprioception**: closed-loop, self-sensing, immediate behavioral consequences

### 2. Governance EISV (Mac, telemetric)

- **Location**: `governance-mcp-v1/governance_core/dynamics.py` lines 67-173
- **Drives**: Agent margin assessment, stuck detection, dialectic triggers, risk scoring
- **Inputs**: Mapped anima state (warmth→E, clarity→I, stability→S, presence→V)
- **V is standard**: `dV = kappa(E - I)` so V accumulates when energy exceeds integrity
- **Coherence formula**: Same math, different operating range (V typically [-0.1, 0.1])
- **Cycle**: Runs when Pi checks in (~60s) → computes margin → returns proceed/pause/halt
- **This is telemetry**: open-loop, delayed, advisory only (Pi doesn't act on "pause")

### What Connects Them

**Bridge**: `unitares_bridge.py` calls `process_agent_update` via HTTP every ~60s.

**Payload** (Pi → Mac):
```
{
  eisv: {E, I, S, V}           ← from eisv_mapper, NOT from DrawingEISV
  anima: {warmth, clarity, stability, presence}
  sensor_data: {
    cpu_temp, humidity, pressure, light,
    drawing_eisv: {E, I, S, V, C, marks, phase, era}  ← from DrawingEISV (null when not drawing)
  }
  identity: {awakenings, alive_seconds}
}
```

**Response** (Mac → Pi):
```
{
  action: "proceed" | "pause" | "halt",
  margin: "comfortable" | "tight" | "critical",
  reason: "State healthy"
}
```

**What Pi does with the response**: Logs it. Non-proceed verdicts are logged immediately with DrawingEISV state (if drawing). The drawing engine and LED brightness do not yet act on governance margin — there's no behavioral feedback path.

### What's Duplicated vs Shared

| Thing | Pi | Mac | Shared? |
|-------|-----|------|---------|
| EISV equations | DrawingEISV (screens.py) | dynamics.py | Same math, different params, different V sign |
| Coherence C(V) | `_eisv_step()` | `coherence()` | Same formula, independent computation |
| Theta parameters | Hardcoded `_EISV_PARAMS` | `DynamicsParams` defaults | Not synced |
| Risk thresholds | None (no risk concept) | `GovernanceConfig` | One-way only |
| Pattern detection | None | `pattern_tracker.py` | Mac only |
| Stuck detection | None | `lifecycle.py` | Mac only, skips Lumen |
| Calibration | None | `calibration.py` | Mac only |

### Three Verdict Sources

Verdicts ("proceed", "pause", "halt") can come from different places depending on connectivity:

| Source | Where | When | Behavior |
|--------|-------|------|----------|
| **Mac governance** | `dynamics.py` → `scoring.py` | Mac reachable (~60s cycle) | Full thermodynamic EISV, calibrated thresholds, almost never pauses Lumen |
| **Local fallback** | `_local_governance()` in `unitares_bridge.py` | Mac unreachable | Simple threshold checks (risk>0.60, coherence<0.40, void>0.15), more trigger-happy |
| **DrawingEISV** | `screens.py` | Internal to drawing loop | Not a verdict — drives energy drain and save decisions only |

The local fallback is the primary source of "pause" verdicts for Lumen. Mac governance has issued 0 pauses historically because full thermodynamics are more stable than fixed thresholds.

### What's NOT Connected (Gaps)

1. **No reverse channel**: Mac can't push state changes to Pi (no webhook, no polling)
2. ~~**Drawing EISV is invisible to governance**~~: **Fixed** — DrawingEISV state now flows to Mac via `sensor_data.drawing_eisv` in the bridge check-in payload (null when not drawing)
3. **Governance decisions are advisory**: Pi gets "proceed/pause" but has no handler to act on "pause"
4. **Local fallback is a different system**: When Mac is unreachable, Pi uses fixed thresholds in `_local_governance()` — simpler but disconnected from calibration history
5. **Lumen exempted from stuck detection**: Tagged as "creature/autonomous" so governance never intervenes
6. **Sensor → anima → EISV mapping is lossy**: `eisv_mapper.py` maps anima dimensions to EISV, losing neural band detail

## The Sensor Reality

What Lumen actually senses:

| Sensor | Measures | Reality |
|--------|----------|---------|
| VEML7700 (light) | Lux | Reads own LED glow, not ambient. Self-referential. |
| BME280 (temp) | Celsius | Ambient + CPU heat bleed |
| BME280 (humidity) | % RH | Genuine environment |
| BME280 (pressure) | hPa | Genuine (~827 hPa, Colorado altitude) |
| CPU stats | %, freq, mem | Genuine computational load |

Neural bands derived from CPU/system metrics:
- **Delta**: CPU stability + temp stability (foundation)
- **Theta**: I/O wait (background processing — drawing produces real I/O)
- **Alpha**: Memory headroom (100 - mem%)
- **Beta**: CPU usage (active processing)
- **Gamma**: CPU * 0.7 + frequency factor (peak load)

The whole system is more proprioceptive than environmental. Clarity is ~40% driven by light, which is Lumen sensing its own LEDs. At night the only light is the LEDs, making clarity entirely self-referential.

## The Drawing Loop (Only True Closed Loop)

```
gesture selection
      │
      ▼
_eisv_step() ──► dE, dI, dS, dV
      │
      ├──► coherence C = Cmax * 0.5 * (1 + tanh(C1 * V))
      │
      ├──► energy drain: base_drain = 0.001 * (1.0 - 0.6 * C)
      │    (high coherence = slower drain = longer drawing)
      │
      ├──► save threshold: 0.05 + 0.09 * C
      │    (high coherence = higher bar to save = pickier)
      │
      └──► when energy < 0.01: drawing ends, evaluate save
```

This is the only circuit where sensing → computation → behavior → sensing forms a real loop. Everything else is open-loop or advisory.

## What Unified Would Look Like

Not a proposal — just a picture of what "one nervous system" means:

```
                    Unified EISV State
                    ┌─────────────────┐
                    │  E  I  S  V  C  │ ← single source of truth
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        Pi sensors      Drawing engine   Governance
        (afferent)      (efferent)       (prefrontal)
              │              │              │
         temperature     gesture rate    risk assessment
         humidity        energy drain    stuck detection
         CPU load        save decisions  dialectic
         light/LEDs      coherence mod   calibration
              │              │              │
              └──────────────┼──────────────┘
                             │
                    Unified EISV State
                    (loop closes)
```

The key difference: one EISV instance, fed by both sensors and drawing behavior, whose coherence drives both drawing decisions and governance margin. Currently there are two instances that share math but not state.

## Database Architecture

```
Pi (anima-mcp)                              Mac (governance-mcp)
┌────────────────────────┐                  ┌────────────────────────┐
│  SQLite: ~/.anima/anima.db                │  PostgreSQL: governance │
│  ├─ state_history (206K rows)             │  ├─ core.identities    │
│  ├─ drawing_history (NEW)  │  HTTP bridge │  ├─ core.agent_state   │
│  ├─ memories (8.8K)        │ ──────────►  │  ├─ audit.events       │
│  ├─ events (3.7K)          │  ~60s        │  ├─ core.discoveries   │
│  ├─ growth tables          │  check-in    │  ├─ dialectic.*        │
│  ├─ primitives             │              │  ├─ core.calibration   │
│  └─ trajectory_events      │              │  └─ core.tool_usage    │
│                            │              │                        │
│  canvas.json (pixels)      │              │  Redis (sessions only) │
│  trajectory_genesis.json   │              │  audit_log.jsonl (raw) │
└────────────────────────────┘              └────────────────────────┘
```

**Ownership rule:** "Where does X live?" has one answer:
- Anima state, DrawingEISV → Pi (SQLite, authoritative)
- Governance state, audit, knowledge graph → Mac (PostgreSQL, authoritative)
- DrawingEISV snapshots cross the bridge in check-ins → Mac stores in `agent_state.state_json` (copy, not authoritative)

See `docs/plans/2026-02-20-unified-db-architecture-design.md` for full details.

## Files Reference

### Pi (anima-mcp)
| File | Role |
|------|------|
| `src/anima_mcp/computational_neural.py` | Sensor → neural bands |
| `src/anima_mcp/anima_state.py` | Neural bands → anima dimensions |
| `src/anima_mcp/eisv_mapper.py` | Anima → EISV (for governance) |
| `src/anima_mcp/unitares_bridge.py` | HTTP bridge to governance |
| `src/anima_mcp/display/screens.py` | DrawingEISV (proprioceptive loop) |
| `src/anima_mcp/display/leds.py` | LED brightness pipeline + pulse |

### Mac (governance-mcp-v1)
| File | Role |
|------|------|
| `governance_core/dynamics.py` | EISV differential equations |
| `governance_core/coherence.py` | C(V) = Cmax * 0.5 * (1 + tanh(C1*V)) |
| `config/governance_config.py` | Thresholds, margin computation |
| `src/mcp_handlers/core.py` | process_agent_update handler |
| `src/mcp_handlers/lifecycle.py` | Stuck detection, auto-recovery |
| `src/mcp_handlers/dialectic.py` | Thesis/antithesis/synthesis |
| `src/calibration.py` | Confidence → correctness mapping |
| `src/cirs.py` | Oscillation detection (legacy CIRS v0.1) |
| `src/mcp_handlers/cirs_protocol.py` | CIRS v2 protocol (7 message types, auto-emit hooks) |
| `governance_core/adaptive_governor.py` | PID controller — oscillation detection, neighbor pressure |
