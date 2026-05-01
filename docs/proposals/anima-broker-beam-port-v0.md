---
status: DRAFT-v0.1 (council pass 1 complete; ack-pass pending)
authored: 2026-04-30
amended: 2026-04-30 (v0, v0.1 same session)
council_pass_1: 2026-04-30
author_session: agent-c9e03e26-33c (claude_code-claude_c9e03e26)
review_target: |
  Council pass 1 complete (parallel agents, 2026-04-30; same precedent as
  surface-lease-plane-v0.md):
    - dialectic-knowledge-architect: 3 BLOCKs, 7 CONCERNs, 4 NITs — addressed in v0.1
    - feature-dev:code-reviewer: 4 BLOCKs, 7 CONCERNs, 3 NITs — addressed in v0.1
    - live-verifier: 1 BLOCK, 2 DRIFTs, 5 CONCERNs, 15 VERIFIED — addressed in v0.1

  All three council agents returned NO-SHIP for v0. Eight distinct BLOCKs across
  the panel (with one cross-pollinated — dialectic §2 corollary breakage and
  code-reviewer §4.2/§3.3 SHM `governance` key fallback name the same wedge from
  opposite angles). v0.1 addresses all eight; ack-pass on v0.1 amendments is
  the next gate before promotion past draft.
provenance: |
  Same-session synthesis. v0 was a single-author sketch (claude_code-claude_c9e03e26,
  2026-04-30) written after operator-decision archaeology (KG
  `2026-04-30T19:30:54.644112+00:00`). v0.1 amendments fold in council pass 1
  findings from three parallel agents in the same session; the council's
  contribution is visible inline (cited section numbers + BLOCK/CONCERN tags).
  This RFC is downstream of the same operator decision that authorized
  surface-lease-plane-v0.md (the Mac-side substrate); both are wedges of the
  same "full BEAM nervous system" destination.
related:
  - docs/proposals/surface-lease-plane-v0.md (Mac-side first wedge; council-clean v0.4; this RFC inherits invariant text but re-states the Pi corollary in §2 to survive Pi-specific contact with broker code)
  - docs/ontology/beam-coordination-kernel.md (parallel ontology-track framing — UNITARES R7 row in `docs/ontology/plan.md`)
  - PR #45 anima-mcp `fix(sensors): server reads SHM, never opens /dev/i2c-1` (the BMP280 wedge — single-writer-to-hardware violation; live-verified)
  - PR #14 anima-mcp `Periodically refresh D22/D24 to prevent TFT blackout` (D22 = TFT backlight + joystick LEFT; D24 = TFT reset + joystick RIGHT; live-verified at `src/anima_mcp/input/brainhat_input.py:65-83` and `display/renderer.py:219-242,327`)
  - PR #11 anima-mcp `fix(sensors): recreate I2C bus handle when multiple sensors fail` (bus-wedge recovery; live-verified)
  - PR #8 anima-mcp `fix(server): swallow MCP SDK ClosedResourceError on client disconnect` (anyio cousin; live-verified)
  - commit `c83748c test: add regression coverage for shutdown ownership + warmup race` (live-verified in git log)
  - `~/.claude/projects/-Users-cirwel/memory/feedback_trust-operator-pattern-over-data-anchor.md` + `anima-mcp/systemd/anima.service:26-31` (BMP280 wedge incident anchor — replaces the earlier wildcard `KG 2026-04-28T*` citation that did not surface in KG search)
  - KG `2026-04-30T19:30:54.644112+00:00` (operator decision: BEAM spike greenlit, full BEAM nervous system as destination — live-verified, exact text match)
out_of_scope_explicit: |
  Hard line — load-bearing substrate boundaries (inherited from `surface-lease-plane-v0.md`):
  - Distributed Erlang clustering between Pi BEAM node and Mac BEAM node (each node single-node; cross-host coordination uses HTTP and Postgres heartbeat-TTL, never Erlang clustering)
  - Identity issuance, EISV math, KG writes, calibration — these stay in Python on the Mac
  - **EISV mapping on the Pi** — see §2 corollary clarification; `anima_to_eisv` and `UnitaresBridge.check_in()` stay in Python as a Pi-resident `unitares-bridge` sidecar process

  Deferred to subsequent RFCs (each merits its own scope):
  - LED hardware ownership cleanup — see §3.4 explicit honesty section; trigger named for v0.5 fold-in
  - Voice/TTS write-path deduplication — server today independently runs `AutonomousVoice` (live-verified at `accessors.py:376-397`); this dual-ownership predates the BEAM port and is out of scope
  - Mic/speaker hardware surface ownership cleanup — same dual-ownership story
  - Phoenix LiveView replacement of TFT display rendering pipeline (Pillow-based today)
  - Cross-language type generation (Pydantic↔Ecto schemas) — v0 ships JSON Schema as the contract floor (§7.6); generated bindings deferred
unblocks: |
  - Single-writer-to-hardware enforcement structurally (today it's convention, repeatedly violated)
  - Shared-pin GPIO races (D22/D24 today coordinated by periodic-refresh hack)
  - Bus-wedge recovery (today: recreate-handle-on-failure heuristic; with OTP: supervisor restarts the GenServer that owns the bus, lease released on death)
  - Distribution: Lumen as appliance ships a single Elixir release tarball, not Python+venv+system-deps+service-files
---

# Proposal: Anima Broker BEAM Port v0 (Pi-side coordination kernel)

> **Status: DRAFT-v0.1, ack-pass pending.** Follow-on to `surface-lease-plane-v0.md`. The lease plane is the **Mac-side** first wedge for BEAM/OTP. This RFC is the **Pi-side** second wedge: porting the `anima-creature` broker to a single-node Elixir application that owns Lumen's hardware lifecycle. Both nodes are single-node by design (no Distributed Erlang between them); they coordinate via HTTP and Postgres heartbeat-TTL, the same patterns the Python fleet uses today.

## 1. Problem

The Pi-side broker (`anima-creature`, `src/anima_mcp/stable_creature.py`, 1299 LOC Python — live-verified) sits in a class of bugs that OTP was built to make boring. The git trail shows a steady diet:

1. **Single-writer-to-hardware violations.** PR #45 (`fix(sensors): server reads SHM, never opens /dev/i2c-1`) closed the BMP280 wedge: the Python anima-mcp server had been opening I2C directly while the broker also held it. Detection took days because nothing structurally prevented it; lsof eventually showed the violation. Anchor: `feedback_trust-operator-pattern-over-data-anchor.md` (memory) + `systemd/anima.service:26-31` (incident note inline in service file). Replaces the wildcard `KG 2026-04-28T*` citation in v0 that did not surface in KG search.

2. **Bus-wedge recovery as application logic.** PR #11 (`fix(sensors): recreate I2C bus handle when multiple sensors fail`) hand-rolled a recovery routine. This is a manual reinvention of `Supervisor.restart_strategy: :rest_for_one`. **(Genuine OTP-shaped win — see §1.1 bucketing.)**

3. **Shared-pin GPIO races.** PR #14 (`Periodically refresh D22/D24 to prevent TFT blackout`) — TFT backlight (D22) is shared with joystick LEFT; TFT reset (D24) is shared with joystick RIGHT. Periodic 30-second OUTPUT-HIGH re-assertion counters pull-up droop in the absence of a single owner. **(Genuine OTP-shaped win — single GPIO owner via GenServer.)**

4. **Shutdown / warmup ordering races.** Regression test in `c83748c` exists because shutdown ownership and warmup race against each other; tested but not structurally prevented.

5. **anyio-asyncio cousin bugs.** PR #8 (`swallow MCP SDK ClosedResourceError on client disconnect`) is a smaller version of the deadlock class that motivated `surface-lease-plane-v0.md`.

6. **Distribution friction.** Lumen-as-appliance is in the operator goal set. Today's deploy is "Pi reflash → restore_lumen.sh → venv + system deps + service files." This is shippable to operators (Kenny), not to non-developer end-users.

### 1.1 Honest bucketing (revised v0.1)

v0 framed the bucketing as "~5 of 6 in OTP-shaped buckets." Council pass 1 (dialectic) flagged this as over-attribution: any single-writer-discipline fix delivers items 1, 4, 5, 6 — only items 2 (bus recreate via supervisor) and 3 (single GPIO owner) are uniquely OTP-shaped wins. Re-stated:

- **Items 2, 3** — uniquely OTP-shaped (rest_for_one cascade, GenServer-owned pin claim).
- **Items 1, 4, 5, 6** — addressed by *any* substrate change with single-writer-to-hardware discipline; OTP is one solution but not the only one.

The genuine OTP-specific win is **supervision-tree-as-recovery-story** (a structured upgrade and crash-recovery model), not raw fault-class coverage. The §8.1 / §8.5 steelmans below address this directly.

## 2. Decision

Port `anima-creature` to a **single-node Elixir/OTP application** running on the Pi. Hardware ownership lives in OTP processes under a supervision tree; the supervisor IS the recovery story; lease release on death is automatic.

Inherit the lease-plane RFC's invariant verbatim:

> BEAM owns live coordination.
> Python owns governance truth.
> Postgres owns durable truth.
> No BEAM component may silently become source of truth for identity, EISV, KG, or calibration.

### 2.1 Pi corollary (revised v0.1 — addresses dialectic BLOCK §2)

The v0 corollary "BEAM owns hardware lifecycle, Python anima-mcp server stays in Python" was incorrect about current state. **Today the broker calls `UnitaresBridge.check_in()` (`stable_creature.py:925-998` — live-verified) and computes EISV via `anima_to_eisv()` (`:567`).** The broker is the primary UNITARES caller from the Pi.

The corrected corollary, with explicit process placement:

> **BEAM owns hardware lifecycle.**
> **Python owns governance + EISV mapping**, on the Pi via a Pi-resident `unitares-bridge` sidecar process; on the Mac via the governance MCP server. Neither is moved into BEAM.
> **Postgres owns durable truth** on the Mac. **SQLite owns durable truth on the Pi** (`~/.anima/anima.db`); the BEAM broker does NOT hold the SQLite handle — the Python `unitares-bridge` and `anima` server retain it, same as today.

The Pi-side process layout after v0:

```
  ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
  │ anima-broker (BEAM)  │    │ unitares-bridge (py) │    │ anima (py, MCP/HTTP) │
  │  hardware lifecycle  │───▶│  sensor→EISV→bridge  │    │  MCP API + LEDs      │
  │  sensors, GPIO, TFT  │SHM │  to UNITARES         │HTTP│                      │
  │  face, telemetry     │    │  reads SHM, posts    │    │  reads SHM           │
  └──────────────────────┘    └──────────────────────┘    └──────────────────────┘
            │                            │                           │
            ▼                            ▼                           ▼
       /dev/i2c-1               UNITARES (Mac:8767)            /dev/spidev0.0
       /dev/spidev0.0                                          (LED display)
       GPIO claims                                             AutonomousVoice
                                                               (broker also)
```

The `unitares-bridge` Python sidecar is a new service in v0; its responsibility is `anima_to_eisv` mapping + governance check-in. Code is lifted from `stable_creature.py:567,925-998` essentially unchanged. This avoids the three failure modes the v0 corollary was silent about (porting EISV math into BEAM, growing an undocumented Pi process, or moving per-tick computation across Tailscale).

This invariant is non-negotiable. Any future RFC that proposes moving identity issuance, EISV math, KG writes, or calibration into the BEAM node must reopen the threat model and re-justify the polyglot tax.

## 3. Scope (in / out)

### 3.1 In scope (v0)

- A new Elixir application running on the Pi, separate process from the Python anima-mcp server.
- A new Python `unitares-bridge` sidecar process on the Pi (lifts EISV-mapping + UNITARES check-in code from current broker; not part of v0 Elixir port but is part of v0 deployment).
- OTP supervision tree owning: I2C bus, BMP280 sensor, accelerometer/gyro sensor, TFT display + reset/backlight pins, joystick GPIO, face-state derivation, metacognitive reflection serialization. **Reflection serialization is under top-level supervisor, not HardwareSupervisor** (council nit — it's not hardware).
- SHM-compatible JSON write to `/dev/shm/anima_state.json` matching the current envelope shape, with the lock-parity contract spelled out in §4.2.
- Health endpoint over HTTP, bound to `127.0.0.1` (council nit — explicit local-only).
- OTP application-controlled clean shutdown ordering. The `os._exit` workaround cited in v0 was already removed in `ed1b2f6` (live-verified) — re-framing: BEAM upgrade story is supervisor restart, replacing Python's PartOf= + explicit-systemctl dance.
- Telemetry emission to UNITARES `audit.tool_usage` via HTTP, same channel the lease plane uses.
- Vanilla Elixir on Raspbian (council closed §7.1).

### 3.2 Out of scope (v0)

Listed in the frontmatter `out_of_scope_explicit` field. Two items deserve in-body explanation because the v0 wording was misleading:

- **LED hardware ownership** — stays where it is today (server owns LEDs, broker does not import `LEDDisplay` per `stable_creature.py:60`, live-verified). v0 carve-out documented honestly in §3.4.
- **Voice/TTS write-path** — current state is **dual-ownership**, not single-broker-ownership: both broker and server independently instantiate `AutonomousVoice` (live-verified at `accessors.py:376-397`). v0 keeps the broker's voice subsystem in Python (does not port to BEAM, does not change ownership). The dual-ownership cleanup is its own RFC.
- **Mic/speaker hardware surfaces** — `audio/mic.py`, `audio/speaker.py` are real hardware surfaces with the same dual-ownership story. Out of v0 scope.

### 3.3 Promotion bundles (revised v0.1 — addresses code-reviewer BLOCK §6.2)

The v0 8-row surface table assumed surfaces could be promoted independently. Council pass 1 (code-reviewer) flagged this as architecturally incoherent: the broker is a **single synchronous loop** where every surface is computed sequentially from shared sensor input. Reflection cannot be Python-owned while sensors are Elixir-owned — Python broker would have to read-from-SHM-to-write-back, introducing a new race.

Replacing per-row promotion with three **atomic bundles** that mirror the actual loop dependencies:

| Bundle | Surfaces | Phase B promotion order | Notes |
|---|---|---|---|
| **A. Sensors+Anima** | `/dev/i2c-1` bus, BMP280, IMU, GPIO bus, joystick GPIO, raw sensor readings, anima derivation | First | Lowest blast radius; Elixir-owned sensors mean any Python derived state must read from SHM. Once promoted, Python broker may continue to run in shadow but its sensor-reading code path is dead. |
| **B. Display+Face** | TFT display (SPI), face-state derivation, D22/D24 single-owner | Second | Visible regression if wrong. Phase B-display is gated on Phase B-sensors completing. |
| **C. Reflection+Telemetry** | Metacognitive reflection serialization, UNITARES telemetry forwarder | Third | Pure compute downstream of A+B. No hardware. Could go simultaneously with B. |

**Reserved hardware surface IDs (lease-plane interaction — addresses dialectic CONCERN):**

The lease-plane RFC §3.3 reserves a `td:/op_path` row "for design fit" without registering. This RFC reserves analogous hardware IDs in the surface-ID schema, NOT registered with the Mac-side lease plane in v0:

| Reserved ID | Purpose | Notes |
|---|---|---|
| `hw:/i2c-1` | Reservation for I2C bus ownership | If we ever register, the BMP280 wedge becomes a `held_by_other` event the moment any second process opens the bus — the days-to-detect failure becomes seconds. |
| `hw:/gpio/D22`, `hw:/gpio/D24` | Reservation for shared-pin claims | TFT/joystick |
| `hw:/spi/tft` | Reservation for SPI display | |

Wiring (round-tripping every hardware lease through the Mac across Tailscale) is correctly out of v0. **Schema reservation only**, so a v0.1+ advisory registration is a wiring change, not a re-design.

### 3.4 LED honesty (new in v0.1 — addresses dialectic BLOCK §3.2/§7.3)

v0 deferred LED ownership cleanup with the framing "stay split, it's its own RFC." Council pass 1 (dialectic) flagged this as cementing an unacknowledged invariant violation. The §2 corollary says "every hardware resource is owned by exactly one OTP process." LEDs are a hardware resource. The Python anima server holds the LED FD outside the BEAM supervision tree.

Stated honestly: **nothing structurally prevents an LED-class wedge during v0**. The single-writer-to-hardware discipline is convention, not enforcement, for LEDs specifically. It is the same shape as the BMP280 wedge before PR #45.

The v0.5 fold-in trigger: **any I2C-conflict-class symptom involving LEDs (LED FD held by two processes, or any duplicate-claim incident on the LED bus) between Phase A and Phase C forces LED ownership into v0.5 before cutover**. Operator may also fold LED in voluntarily; this is not a delay until "after cutover."

This is not refusing scope creep — it is naming the deferred wedge so the v0 promise is honest about what it does and does not structurally fix.

## 4. Architecture

### 4.1 Supervision tree (revised v0.1 — split I2C from SPI per code-reviewer CONCERN)

```
AnimaBroker.Application
└── AnimaBroker.Supervisor (one_for_one)
    ├── AnimaBroker.I2CHardwareSupervisor (rest_for_one)
    │   ├── AnimaBroker.I2CBus           (owns /dev/i2c-1; killing this kills sensor children)
    │   ├── AnimaBroker.BMP280
    │   └── AnimaBroker.IMU
    ├── AnimaBroker.SPIHardwareSupervisor (one_for_one)
    │   ├── AnimaBroker.SPIBus           (owns /dev/spidev0.0)
    │   └── AnimaBroker.TFTDisplay       (uses GPIOBus for D22/D24 + SPIBus)
    ├── AnimaBroker.GPIOSupervisor (one_for_one)
    │   ├── AnimaBroker.GPIOBus          (owns BCM pin claims)
    │   └── AnimaBroker.Joystick         (uses GPIOBus for D22/D23/D24/D27)
    ├── AnimaBroker.Reflection           (top-level: not hardware; per dialectic NIT)
    ├── AnimaBroker.SHMWriter            (writes /dev/shm/anima_state.json envelope)
    ├── AnimaBroker.HealthEndpoint       (Bandit/Plug HTTP, bound 127.0.0.1)
    └── AnimaBroker.Telemetry            (HTTP forwarder to UNITARES audit channel)
```

`rest_for_one` only on the I2C tree (where sensor children genuinely depend on a healthy bus). SPI hardware uses `one_for_one` so a TFT crash doesn't restart the entire display tree, and an I2C bus wedge does not force a TFT restart (council CONCERN — different bus, no shared dependency).

### 4.2 Wire to Python anima-mcp server (revised v0.1 — addresses code-reviewer BLOCK §4.2 + live-verifier CONCERN)

v0 keeps the **same SHM wire** (`/dev/shm/anima_state.json` JSON envelope). Below is the explicit lock-parity contract:

- **Final file path**: `/dev/shm/anima_state.json` (Phase B/C) or `/dev/shm/anima_state_elixir.json` (Phase A shadow).
- **Lock file**: `/dev/shm/anima_state.lock` companion file. The Elixir writer MUST acquire fcntl LOCK_EX on this lock file (NOT on the data file, NOT via Erlang `:file.lock` — those don't interop). Reference: `shared_memory.py:_write_file` line 70 uses `filepath.with_suffix(".lock")` and `fcntl.flock(lock_fd, fcntl.LOCK_EX)`.
- **Temp file path**: `<final>.tmp` (matches Python's `filepath.with_suffix(".tmp")`).
- **Write sequence**: open lock file in `"a"` mode, fcntl LOCK_EX, write to temp file, `flush()` + `fsync()`, atomic `os.replace(temp, final)` (or NIF equivalent providing `rename(2)` semantics on the same filesystem), fcntl LOCK_UN, close.
- **Phase B "gating Python's writes"**: when a bundle is promoted, the Python broker's `SharedMemoryClient` instance is replaced with a no-op writer (does not touch lock file, does not write temp file, does not write final). Not a flag check inside `write()` — full replacement to eliminate any race between Python's lock-acquire and Elixir's. Backup channel `/dev/shm/anima_state_python_backup.json` is OUT — Phase B is decisively single-writer.

#### 4.2.1 SHM envelope: fields Elixir broker WILL populate in v0

Live-verified envelope at `stable_creature.py:1002-1088` has 15+ top-level keys. Elixir broker in v0 populates ONLY the subset directly derivable from hardware + face/reflection:

| Key | v0 Elixir? | Source |
|---|---|---|
| `timestamp` | YES | BEAM clock |
| `readings` | YES | sensor GenServers |
| `anima` | YES | derived from readings |
| `inner_life` (basic dimensions) | YES | derived from anima |
| `drive_events` | NO | Python `agency` module — out of scope |
| `eisv` | NO | Python `unitares-bridge` writes this via separate SHM key (see §4.2.2) |
| `governance` | NO | Python `unitares-bridge` writes this |
| `identity` | YES (passthrough) | Read from disk — bridge process owns the source of truth, broker reads as snapshot |
| `metacognition` | YES | reflection module |
| `learning`, `experiential` | NO | Python modules — out of scope |
| `agency_led_brightness` | NO | Python `agency` — out of scope |

#### 4.2.2 Server fallback when Elixir-not-populated keys are missing (revised v0.1 — addresses code-reviewer BLOCK §4.2/§3.3)

Critical: if Elixir broker writes SHM without a `governance` key, the server's `SERVER_GOVERNANCE_FALLBACK_SECONDS=240s` timer triggers and the server begins calling UNITARES directly — re-introducing the pre-PR-#45 architecture violation.

Resolution: **the `unitares-bridge` Python sidecar (§2.1) writes a parallel SHM file `/dev/shm/anima_state_governance.json`** with `{governance, eisv, drive_events, learning, experiential, agency_led_brightness, last_decision}`. Server's read path is updated (one-line server change) to merge this side-channel into the data dict before the staleness check. Both files are written through their own lock files; both must be fresh for the server to operate normally.

This makes the server's fallback path explicitly: typed-absence (per lease-plane RFC §4.5 pattern) — when either SHM file is stale/missing, server reports `governance: degraded` to its own callers, NOT direct UNITARES call. The v0.1 decision FORECLOSES the v0 §7.4 option (c) — see §7.4 below.

#### 4.2.3 Other SHM channels (live-verifier CONCERN)

- `/dev/shm/anima_social_boost` — server writes it on user interaction; broker reads. Elixir broker MUST also read this flag (no lock; tiny advisory file). Phase A divergence comparator must factor social-boost-applied state to avoid phantom diffs.
- `~/.anima/display_brightness.json` — renderer writes brightness preset; broker reads each tick. Same passthrough behavior.

### 4.3 Hardware ownership lines

Every hardware resource is owned by exactly one OTP process (subject to the §3.4 LED honesty caveat). FD lives in BEAM VM; direct hardware access from outside the supervision tree is OS-level prevented while BEAM is alive.

**Phase A two-reader caveat (code-reviewer CONCERN):** Phase A intentionally re-introduces a two-reader-on-I2C situation (Python broker for canonical reads, Elixir broker for shadow reads). Both processes use **read-only** semantics during Phase A — no concurrent writes to I2C, no bus resets from Elixir, no GPIO claim contention (Elixir reads sensor pins only, does not touch shared-pin pull-ups). This is the BMP280 wedge shape *deliberately* re-introduced for shadow comparison; it is bounded in scope (read-only) and time (1-2 weeks of Phase A).

**BEAM-down failure mode (foreclosed in §7.4):** when BEAM is down, the FDs are released. The Python server and `unitares-bridge` MUST NOT re-acquire them. Server-side discipline: stale-SHM beyond threshold → typed-absence to callers, NOT direct hardware read. This is a v0.1 server-side commitment, NOT a hope.

## 5. API surface (v0)

The broker exposes:

- HTTP `/health` on `127.0.0.1:<port>` — same shape as today.
- HTTP `/sensors` on `127.0.0.1:<port>` — diagnostic curl only; bound local.
- SHM write to `/dev/shm/anima_state.json` (or `_elixir.json` in Phase A).
- Telemetry POSTs to UNITARES audit channel.

The `unitares-bridge` Python sidecar exposes:
- HTTP `/health` on `127.0.0.1:<bridge-port>`.
- SHM write to `/dev/shm/anima_state_governance.json`.

No new public API in v0. The point of v0 is to swap the runtime, not the contract.

## 6. Rollout (shadow → swap → cutover)

### 6.1 Phase A — Shadow (week 1-2; revised v0.1 — addresses code-reviewer BLOCK §6.1)

- Elixir app runs alongside Python broker on the Pi.
- Reads sensors at the same cadence; writes shadow SHM `/dev/shm/anima_state_elixir.json`.
- Telemetry emits diff between Python and Elixir envelopes; UNITARES audit ingests.

**Concrete promotion gate (per surface_kind):**

| Field class | Diff metric | Threshold for promotion to Phase B |
|---|---|---|
| Sensor floats (temperature, pressure, accel) | `abs(python - elixir)` per field | ≤ 1% relative for ≥ 99% of samples over rolling 7-day window |
| Sensor ints (counters, raw GPIO) | byte-equal | exact, ≥ 99.9% of samples |
| Anima/derived (computed from sensors) | symmetric structural diff | ≤ 0.5% per-key disagreement after sensor-tolerance pass |
| Structural keys (presence) | exact set | exact match (no missing or extra keys) |
| Timestamps (`timestamp`, `updated_at`) | EXCLUDED | not compared |
| Reflection text | EXCLUDED | not compared (subjective; out-of-band review) |

**ASR baseline:** 7-day rolling pre-shadow measurement of the dashboard's `meta_existence_ratio` (alive_ratio) panel. Phase B promotion requires NO statistical drop (Welch's t-test p > 0.05) over 7-day shadow window vs. 7-day pre-shadow baseline.

**Regression triggers** (any one halts Phase A → B promotion):
- KG `audit.tool_usage` row with structured `error: shm_parse` from anima server.
- `meta_existence_ratio` drop > 1 standard deviation from pre-shadow baseline for > 12h.
- Any operator-flagged hardware-anomaly KG entry tagged `lumen` during the 7-day window.

### 6.2 Phase B — Swap (week 3-5; revised v0.1)

- Per **bundle** (not per surface), Elixir writes the canonical SHM file. Python broker's `SharedMemoryClient` is replaced with a no-op writer for that bundle's fields; Elixir is sole writer for that bundle going forward.
- Bundle order: A (Sensors+Anima) → B (Display+Face) → C (Reflection+Telemetry).
- Bundle B and C may proceed in parallel after A is stable.

**Promotion gate per bundle:**
- ≥ 3 days post-swap with NO regression triggers from §6.1.
- ≥ 3 days with no operator KG entry tagged `lumen-broker-port` AND severity ≥ medium.
- Server error log (from anima.service journalctl) shows zero entries containing `shm_parse` or `governance: degraded` over the window.

**Rollback (per bundle):** Python broker's SharedMemoryClient is restored. Elixir broker is reverted to shadow mode for that bundle. Rollback is per-bundle, not all-or-nothing. **Bundle B/C cannot start until Bundle A is stable** because Display+Face depends on Sensors+Anima as input.

### 6.3 Phase C — Cutover (week 6; revised v0.1 — live-verifier CONCERN)

- Python broker removed from systemd. The current service file is `anima-broker.service`; the dependent service is `anima.service` (NOT `anima-mcp.service`).
- Critical step: `anima.service` line 9 has `PartOf=anima-broker.service` (live-verified). Phase C must REPLACE this with `PartOf=anima-broker-elixir.service` (or whatever the Elixir unit name is); not just remove the old line.
- `stable_creature.py` archived to `_archive/` (per repo convention) for one release cycle.
- The Python `unitares-bridge` sidecar STAYS (it carries the EISV/governance code).

## 7. Open RFC questions

### 7.1 Nerves vs. vanilla Elixir on Raspbian — CLOSED in v0.1 (per code-reviewer)

**v0 was indeterminate. v0.1 closes:** vanilla Elixir on Raspbian for v0. Trigger to re-open as a separate Nerves-migration RFC: **second Pi added to the fleet** (where A/B firmware update + cluster management compounds). For one Pi with existing Tailscale + systemd + backup-script management, vanilla Elixir is the right v0 substrate; `circuits_i2c` / `circuits_gpio` / `circuits_spi` are NOT Nerves-exclusive.

### 7.2 SHM JSON envelope: keep, or migrate to typed format

**v0.1 stance:** keep JSON envelope for v0. v0 ships a JSON Schema file (§7.6) as the contract floor. Strict typing migration (Pydantic↔Ecto) is its own RFC.

### 7.3 LED hardware: stay split, or fold into v0

**v0.1 closes:** stay split, see §3.4 honesty section. Fold-in trigger named.

### 7.4 What if the Elixir broker is down? — CLOSED in v0.1

v0 listed three options with no recommendation. v0.1 chooses:

- **(a) Server serves stale SHM with typed-absence flag** — chosen.
- (b) Fail health check to UNITARES — server already does this via separate `governance: degraded` reporting on stale SHM; not the runtime fallback.
- (c) Fall back to direct hardware reads — **explicitly foreclosed**. This is the BMP280 wedge by another name.

Server-side change required for v0: the existing `SERVER_GOVERNANCE_FALLBACK_SECONDS=240s` timer that triggers direct UNITARES call must be REPLACED with a typed-absence path (return `governance: degraded` to MCP callers, never direct call). This is part of the v0 deliverable, not deferred. **Without this, the §4.3 "structurally prevented" claim is false; with it, Elixir-down is bounded in failure mode.**

### 7.5 Hot-reload — out of scope for v0; restart cost named (revised v0.1 — addresses dialectic CONCERN)

Hardware-owning GenServers are deeply stateful (FD, calibration, peripheral handshake). Hot-reload is NOT a v0 promise. Supervisor restart IS the upgrade story. **Realistic restart cost:** I2C bus + sensors restart takes ~100ms-300ms (handshake + first-read settle); TFT restart takes ~500ms-1s (display init + first frame). During a deploy mid-tick, expect:
- 1-2 telemetry tick gaps (broker writes paused for restart window).
- Possible 1-tick mood-momentum dip in face state.
- A deploy during a governance-critical window (Mac side observing tight-margin verdicts) can produce a `stuck/critical_margin_timeout` event on the Mac.

**Deploy procedure** must therefore wait for Mac-side governance idle before broker restart, OR be coordinated through the lease plane (Mac-side broker holds a `surface:/lumen-deploy-window` lease that other agents observe). The lease-plane integration is OUT of v0; v0's deploy procedure is "manual coordination — operator chooses deploy window."

### 7.6 Cross-language schema source-of-truth — closed in v0.1 (per code-reviewer)

**v0 floor:** ship a JSON Schema file (`docs/schemas/anima_state_envelope.v0.json`) that BOTH sides validate against. Python uses `jsonschema`; Elixir uses `ex_json_schema`. Single shared file in the repo. Generated bindings (Pydantic↔Ecto) deferred. Validation is a contract test, not a runtime gate.

### 7.7 D22/D24 refresh removability

**v0.1 stance:** removable in Phase B-display, after Elixir's `GPIOBus` becomes single owner. Verify in shadow phase that Elixir reads of D22/D24 don't observe pull-up droop without the periodic refresh hack. Currently a §9 checklist item.

## 8. Concerns / counter-arguments / minority views (revised v0.1 — addresses dialectic CONCERN)

### 8.1 "Python's been working. Why migrate?" (steelmanned in v0.1)

Stronger version: *"Five of six PRs landed in <30 days of operator-developer time. The empirical bug-arrival rate is decreasing — PR #45 was the architecture-class fix; the architecture is now consistent. You're proposing a 4-8 week port to prevent N future bugs of the same class, when the past N≤6 cost less than the port will."*

**Honest answer:** for the *backward-looking* fault count, this is correct. The argument relies on **forward-looking surface count**:
- Voice ownership cleanup is in the queue (dual-ownership today, live-verified).
- LED ownership cleanup is in the queue (§3.4 trigger).
- Mic/speaker hardware deduplication is in the queue.
- Lumen-as-appliance distribution (single Elixir release vs. Python+venv) is the load-bearing distribution argument; it does not depend on fault count.

Concession: the Pi-side architectural argument is **weaker than the Mac-side argument** (where 17+13 concurrency commits over 4+ months is harder to dismiss). The Pi-side case stands on (a) supervision-tree-as-recovery-story for items 2,3 of §1.1, plus (b) appliance-shaped distribution. Each alone is insufficient; the conjunction is.

### 8.2 "BEAM is heavy on a Pi 4."

Live-verified: broker today RSS = 76 MB Python (`/proc/<pid>/status`, 2-day uptime). Server RSS = 158 MB. Vanilla Elixir resident memory ~25-40 MB (NOT live-verified — no Elixir process running on Pi yet). v0 spike must measure Elixir broker's actual RSS as a §9 checklist item.

### 8.3 "You'd be debugging hardware drivers in BEAM."

True, and not nothing. `circuits_i2c` / `circuits_gpio` / `circuits_spi` wrap the same Linux kernel devices Python uses. Driver semantics same; runtime around them changes. Real cost — flagged, not minimized.

### 8.4 "Why not Go?"

Same answer as lease-plane RFC §8.3: Go gives cheap concurrency but no supervision primitive. Mac+Pi BEAM unifies the substrate. KG `2026-04-30T19:30:54.644112+00:00` operator decision settles this.

### 8.5 "This is just substrate migration tax dressed as architecture." (steelmanned in v0.1)

Stronger version: *"The Pi-side incident class is single-host single-Pi single-process-pair. OTP's load-bearing wins are supervision-on-multi-process and cross-process coordination via mailboxes. Single-host single-Pi has neither — broker + server, two processes, coordinating via a 1KB JSON file. You don't need OTP to fix two processes coordinating via a JSON file; you need a contract test, an `lsof` check in CI, and a single-writer linter rule."*

**Honest answer:** the genuine OTP-shaped wins are items 2 (rest_for_one cascade for bus recovery) and 3 (single GenServer-owned GPIO). The other items in §1 are addressed by *any* substrate change with discipline. The OTP-specific value is **supervision-tree-as-recovery-story** as an ergonomic frame: explicit restart strategies, observable child trees, structured upgrade story. That is *one* well-formed argument, not five.

The architectural argument is therefore a *style* argument, not a fault-count argument. The distribution argument (appliance-shaped Elixir release) is the stronger leg. The conjunction is what justifies v0; either alone does not.

## 9. Pre-implementation checklist (revised v0.1 — addresses §9 BLOCKs from dialectic and live-verifier)

### 9.1 Lease-plane substrate status (live-verifier BLOCK)

- **Lease plane schema:** DEPLOYED (migration `024_lease_plane.sql` applied; `lease_plane.surface_leases` and `lease_plane.lease_plane_events` exist in governance DB; live-verified).
- **Lease plane Elixir process:** NOT RUNNING (port 8788 connection refused; 0 rows in both lease tables; live-verified).
- **This RFC's Phase A is NOT gated on lease plane runtime health.** Lease plane is the operator-decision-and-substrate-test for "BEAM on the fleet"; it is NOT a runtime dependency for the Pi broker port. Anima broker BEAM port can begin Phase A independently of lease plane reaching Phase B.
- A future v1 RFC can integrate the broker with lease plane for `hw:/` advisory leases (§3.3 reservation); v0 does not.

### 9.2 Council pass items

- [ ] §7.1 Nerves vs. vanilla — CLOSED in v0.1 (vanilla Elixir on Raspbian; trigger named for Nerves)
- [ ] §7.2 SHM envelope schema — JSON Schema in v0 (§7.6); typed migration deferred
- [ ] §7.3 LED scope — CLOSED in v0.1 (§3.4 honesty + trigger)
- [ ] §7.4 down-mode behavior — CLOSED in v0.1 (option a; option c foreclosed)
- [ ] §7.5 hot-reload — CLOSED out of v0; restart cost named
- [ ] §7.6 cross-language contract — JSON Schema floor

### 9.3 Spike requirements (must produce evidence before v0.2 implementation gate)

- [ ] **Elixir on Pi — single sensor (BMP280) GenServer reading and emitting telemetry.** ~3 days. Promotes RFC to v0.2 if spike surfaces gaps.
- [ ] **SHM lock parity verified.** Elixir writer acquires `/dev/shm/anima_state.lock` via `:os.cmd("flock ...")` or NIF; round-trip with Python writer over 1000 concurrent acquisitions shows no torn writes.
- [ ] **Elixir RSS measurement.** Confirm vanilla Elixir resident size on Pi 4 (claim 25-40 MB unverified).
- [ ] **JSON Schema validation round-trip.** Python writer envelope validates against schema; Elixir writer envelope validates against schema; shared file checked in.
- [ ] **Server fallback path verified.** anima.service writes typed-absence on stale SHM; SERVER_GOVERNANCE_FALLBACK_SECONDS code path NOT triggered by missing `governance` key (server change deployed and tested before Phase A).
- [ ] **Phase A divergence comparator.** Code that emits diffs to telemetry, with the §6.1 thresholds as gate logic.

### 9.4 Crash-recovery and edge cases (code-reviewer CONCERN)

- [ ] **Elixir startup behavior** — chosen: clear SHM on startup (matches Python broker's `shm_client.clear()` at `stable_creature.py:325`). Stale-from-pre-crash data is NEVER served as live state.
- [ ] **Python broker crash during shadow** — Phase A divergence comparator must tolerate Python broker dying (continue with Elixir-only data; flag as `python_unavailable`).
- [ ] **Hardware unavailable** — sensor disconnect handler returns `:error` from GenServer.call; SHM envelope shows `readings: {error: "unavailable"}`; server tolerates via `.get()` pattern.
- [ ] **Malformed SHM** — JSON parse fail in server log; v0 server change adds explicit `shm_parse` error logging for the §6.1 regression trigger.
- [ ] **Rollback from partially promoted bundle** — v0 deploy procedure requires explicit per-bundle rollback test before promotion.

### 9.5 Cross-link

- [ ] Cross-link with `surface-lease-plane-v0.md` Phase A status. **Concrete dependency direction:** Pi RFC Phase A may proceed independently of lease plane Phase A; Pi RFC Phase B (swap) does not require lease plane in any specific phase. The broker's `hw:/` advisory leases are reserved (§3.3) but not registered in v0.

## 10. Versions / changelog

- **v0** (2026-04-30) — initial draft. Pre-council. Authored after archaeology session.
- **v0.1** (2026-04-30, same session) — council pass 1 amendments. Three NO-SHIPs returned. Eight BLOCKs addressed:
  1. §2 corollary corrected — broker calls UNITARES today; Pi corollary now places `unitares-bridge` Python sidecar explicitly (dialectic BLOCK).
  2. §3.4 LED honesty section added with v0.5 fold-in trigger (dialectic BLOCK).
  3. §6.1/§6.2 promotion gates rewritten with concrete diff thresholds, ASR baseline, regression triggers (dialectic + code-reviewer BLOCKs).
  4. §4.2 SHM lock parity contract spelled out; Elixir writer must use companion `.lock` file with fcntl LOCK_EX (code-reviewer BLOCK).
  5. §6.1 "zero-divergence" replaced with per-field-class diff thresholds (code-reviewer BLOCK).
  6. §4.2.1/§4.2.2 SHM envelope field enumeration; `governance` key gap closed via `unitares-bridge` parallel SHM channel; server fallback foreclosed from option (c) (code-reviewer BLOCK).
  7. §3.3 promotion bundles replace per-surface promotion (code-reviewer BLOCK).
  8. §9.1 lease plane runtime status stated explicitly; Phase A NOT gated on lease plane runtime (live-verifier BLOCK).

  Plus DRIFT corrections (voice dual-ownership, broker memory ~75-80 MB, `os._exit` already removed in `ed1b2f6`, BMP280 KG citation replaced with concrete anchors), §8.1/§8.5 steelmans, §7.4/§7.1/§7.6 council questions closed, §4.1 supervision tree split (I2C vs SPI vs GPIO), §3.3 hardware surface IDs reserved, provenance block added.
