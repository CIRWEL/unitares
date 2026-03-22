# UNITARES Unified Architecture

**What exists, what's connected, what's not.**

```
                         THE ACTUAL SYSTEM
                         =================

  Raspberry Pi Zero 2W                              Mac (governance-mcp)
  (anima-mcp, port 8766)                            (port 8767)
  ========================                           ========================

  BME280 --- temp, humidity, pressure
  VEML7700 -- light (reads own LEDs)     HTTP POST /mcp/
  CPU stats -- load, memory, freq        ------------------->
                    |                    process_agent_update     EISV dynamics
                    v                    (every ~60s)             +----------+
           computational_neural.py                               | dE/dt    |
           (delta/theta/alpha/beta/gamma)                        | dI/dt    |
                    |                                            | dS/dt    |
                    v                                            | dV/dt    |
              anima_state.py                                     +----+-----+
              (warmth, clarity,                                       |
               stability, presence)                             coherence C(V)
                    |                                           risk_score
                    +----------> eisv_mapper.py                 margin level
                    |            E = warmth + neural                  |
                    |            I = clarity + alpha                  |
                    |            S = 1 - stability              <----+
                    |            V = (1-presence)*0.3       {"action":"proceed",
                    |                    |                  "margin":"comfortable"}
                    |                    v
                    |            unitares_bridge.py
                    |            (check_in every 60s,
                    |             fallback to local
                    |             if Mac unreachable)
                    |
                    v
              display/screens.py
              (DrawingEISV)----------> SECOND EISV INSTANCE
              E=0.7, I=0.2, S=0.5         dE = a(I-E) - bE*S + gE*drift^2
                    |                      dI = bI*C - k*S - gI*I
                    |                      dS = -u*S + l1*drift^2 - l2*C
                    |                      dV = k(I-E) - d*V  <-- FLIPPED
                    |                           ^
                    |                      V flipped because here
                    v                      I > E = focused finishing
              display/leds.py                  (opposite of governance
              LED brightness pipeline:          where E > I = stable)
              base -> auto -> pulse ->
              activity -> dimmer ->
              sine pulse ("alive")
```

## Two Nervous Systems

There are **two independent EISV instances** that share math but not state:

### 1. Drawing EISV (Pi-local, proprioceptive)

- **Location**: `anima-mcp/src/anima_mcp/display/screens.py`
- **Drives**: Drawing behavior (energy depletion, save threshold, coherence modulation)
- **Inputs**: Era state intentionality, gesture entropy (Shannon over last 20), gesture switching rate
- **V is flipped**: `dV = kappa(I - E)` so coherence rises when I > E (focused finishing)
- **Coherence formula**: `C(V) = Cmax * 0.5 * (1 + tanh(C1 * V))`
- **This is real proprioception**: closed-loop, self-sensing, immediate behavioral consequences

### 2. Governance EISV (Mac, telemetric)

- **Location**: `governance_core.dynamics` (compiled, in unitares-core package)
- **Drives**: Agent margin assessment, stuck detection, dialectic triggers, risk scoring
- **Inputs**: Mapped anima state (warmth->E, clarity->I, stability->S, presence->V)
- **V is standard**: `dV = kappa(E - I)` so V accumulates when energy exceeds integrity
- **Coherence formula**: Same math, different operating range (V typically [-0.1, 0.1])
- **This is telemetry**: open-loop, delayed, advisory only (Pi doesn't act on "pause")

### What Connects Them

**Bridge**: `unitares_bridge.py` calls `process_agent_update` via HTTP every ~60s.

**Payload** (Pi -> Mac):
```json
{
  "eisv": {"E": 0.7, "I": 0.8, "S": 0.2, "V": 0.0},
  "anima": {"warmth": 0.5, "clarity": 0.6, "stability": 0.8, "presence": 0.9},
  "sensor_data": {
    "cpu_temp": 45.0, "humidity": 30.0, "pressure": 827.0, "light": 12.0,
    "drawing_eisv": {"E": 0.7, "I": 0.2, "S": 0.5, "C": 0.4, "marks": 120, "phase": "developing", "era": "gestural"}
  },
  "identity": {"awakenings": 42, "alive_seconds": 86400}
}
```

`drawing_eisv` is null when not drawing. The `eisv` field comes from `eisv_mapper`, NOT from DrawingEISV.

**Response** (Mac -> Pi):
```json
{
  "action": "proceed",
  "margin": "comfortable",
  "reason": "State healthy"
}
```

Pi logs the response. Non-proceed verdicts are logged with DrawingEISV state. The drawing engine and LEDs do not yet act on governance margin.

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

### Verdict Sources

| Source | Where | When | Behavior |
|--------|-------|------|----------|
| **Mac governance** | `dynamics.py` -> `scoring.py` | Mac reachable (~60s cycle) | Full thermodynamic EISV, calibrated thresholds, almost never pauses Lumen |
| **Local fallback** | `_local_governance()` in `unitares_bridge.py` | Mac unreachable | Simple threshold checks (risk>0.60, coherence<0.40, void>0.15), more trigger-happy |
| **DrawingEISV** | `screens.py` | Internal to drawing loop | Not a verdict -- drives energy drain and save decisions only |

The local fallback is the primary source of "pause" verdicts for Lumen. Mac governance has issued 0 pauses historically because full thermodynamics are more stable than fixed thresholds.

### What's NOT Connected (Gaps)

1. **No reverse channel**: Mac can't push state changes to Pi (no webhook, no polling)
2. **Governance decisions are advisory**: Pi gets "proceed/pause" but has no handler to act on "pause"
3. **Local fallback is a different system**: When Mac is unreachable, Pi uses fixed thresholds -- disconnected from calibration history
4. **Lumen exempted from stuck detection**: Tagged as "creature/autonomous" so governance never intervenes
5. **Sensor -> anima -> EISV mapping is lossy**: `eisv_mapper.py` maps anima dimensions to EISV, losing neural band detail

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
- **Theta**: I/O wait (background processing -- drawing produces real I/O)
- **Alpha**: Memory headroom (100 - mem%)
- **Beta**: CPU usage (active processing)
- **Gamma**: CPU * 0.7 + frequency factor (peak load)

The whole system is more proprioceptive than environmental. Clarity is ~40% driven by light, which is Lumen sensing its own LEDs. At night the only light is the LEDs, making clarity entirely self-referential.

## The Drawing Loop (Only True Closed Loop)

```
gesture selection
      |
      v
_eisv_step() --> dE, dI, dS, dV
      |
      +--> coherence C = Cmax * 0.5 * (1 + tanh(C1 * V))
      |
      +--> energy drain: base_drain = 0.001 * (1.0 - 0.6 * C)
      |    (high coherence = slower drain = longer drawing)
      |
      +--> save threshold: 0.05 + 0.09 * C
      |    (high coherence = higher bar to save = pickier)
      |
      +--> when energy < 0.01: drawing ends, evaluate save
```

This is the only circuit where sensing -> computation -> behavior -> sensing forms a real loop. Everything else is open-loop or advisory.

## Database Architecture

```
Pi (anima-mcp)                              Mac (governance-mcp)
+------------------------+                  +------------------------------+
|  SQLite: ~/.anima/anima.db                |  PostgreSQL+AGE (Docker 5432) |
|  +- state_history (206K rows)             |  +- core.identities          |
|  +- drawing_history       |  HTTP bridge  |  +- core.agent_state         |
|  +- memories (8.8K)       | ----------->  |  +- audit.events             |
|  +- events (3.7K)         |  ~60s         |  +- core.discoveries (AGE)   |
|  +- growth tables         |  check-in     |  +- dialectic.*              |
|  +- primitives            |               |  +- core.calibration         |
|  +- trajectory_events     |               |  +- core.tool_usage          |
|                           |               |                              |
|  canvas.json (pixels)     |               |  Redis (Docker 6379)         |
|  trajectory_genesis.json  |               |  audit_log.jsonl (raw)       |
+---------------------------+               +------------------------------+
```

**Ownership rule:** "Where does X live?" has one answer:
- Anima state, DrawingEISV -> Pi (SQLite, authoritative)
- Governance state, audit, knowledge graph -> Mac (PostgreSQL+AGE, authoritative)
- DrawingEISV snapshots cross the bridge in check-ins -> Mac stores in `agent_state.state_json` (copy, not authoritative)

**There is NO SQLite on the Mac side.** All SQLite code was removed Feb 2026.
The only PostgreSQL is the Docker container `postgres-age` on port 5432.
Homebrew PostgreSQL (port 5433) is a separate project -- not UNITARES.

## Files Reference

### Pi (anima-mcp)
| File | Role |
|------|------|
| `src/anima_mcp/computational_neural.py` | Sensor -> neural bands |
| `src/anima_mcp/anima_state.py` | Neural bands -> anima dimensions |
| `src/anima_mcp/eisv_mapper.py` | Anima -> EISV (for governance) |
| `src/anima_mcp/unitares_bridge.py` | HTTP bridge to governance |
| `src/anima_mcp/display/screens.py` | DrawingEISV (proprioceptive loop) |
| `src/anima_mcp/display/leds.py` | LED brightness pipeline + pulse |

### Mac (governance-mcp-v1)
| File | Role |
|------|------|
| `governance_core.dynamics` | EISV differential equations (compiled) |
| `governance_core.coherence` | Coherence function C(V, Theta) (compiled) |
| `config/governance_config.py` | Thresholds, margin computation |
| `src/mcp_handlers/core.py` | process_agent_update handler |
| `src/mcp_handlers/lifecycle.py` | Stuck detection, auto-recovery |
| `src/mcp_handlers/dialectic.py` | Thesis/antithesis/synthesis |
| `src/calibration.py` | Confidence -> correctness mapping |
| `src/mcp_handlers/cirs_protocol.py` | CIRS v2 protocol (7 message types, auto-emit hooks) |
| `governance_core.adaptive_governor` | PID controller -- oscillation detection, neighbor pressure (compiled) |
