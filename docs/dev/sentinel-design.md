Status: Phase 2 MVP shipped
Date: 2026-04-07
Shipped: 2026-04-07

# Sentinel Design — Code Hardening + Independent Observer

## The Honest Split

Not everything needs a sentinel agent. Some gaps are missing features in governance-mcp
itself — just code. The sentinel's job is the irreducible part: independent observation,
cross-agent correlation, and judgment that can't live inside the system it's watching.

---

## Part 1: Code Hardening (no sentinel needed)

These are governance-mcp improvements. Ship them first — they reduce the sentinel's
scope to what actually requires an independent observer.

### 1.1 Persist Behavioral Baselines

**Problem:** `AgentBehavioralBaseline` stores Welford stats in `_baselines` (in-memory dict).
Server restart wipes every agent's baseline. Post-restart, anomalous behavior looks normal
because there's no history to compare against.

**Fix:** Write baselines to PostgreSQL on each update. Load on agent resume. Table:
```sql
CREATE TABLE IF NOT EXISTS agent_baselines (
    agent_id UUID PRIMARY KEY,
    baselines JSONB NOT NULL,  -- {signal_name: {mean, variance, count}}
    updated_at TIMESTAMPTZ DEFAULT now()
);
```
**Files:** `src/agent_behavioral_baseline.py` (add persistence), `src/db/` (add table).

**Complexity:** Low. Welford state is just `{mean, variance, count}` per signal — small JSONB.

### 1.2 Lifecycle Event Hooks

**Problem:** Lifecycle transitions (pause, resume, archive, onboard) are written to
`meta.lifecycle_events[]` in memory. No callback, no event bus, no way for external
code to react. A sentinel would have to poll.

**Fix:** Add a lightweight event emitter. On each lifecycle transition, broadcast via the
existing `broadcaster.py` WebSocket *and* write to `audit.events`:
```python
# In agent_lifecycle.py, after meta.add_lifecycle_event():
await audit_db.append_audit_event_async(
    event_type=f"lifecycle_{event_name}",
    agent_id=agent_id,
    payload={"reason": reason, "previous_status": prev_status}
)
await broadcaster.broadcast({"type": "lifecycle", "agent_id": agent_id, "event": event_name})
```
**Files:** `src/agent_lifecycle.py`, `src/mcp_handlers/updates/phases.py` (pause path),
`src/audit_db.py` (ensure `lifecycle_*` types indexed).

**Complexity:** Low. The broadcast infra exists — just need to call it.

### 1.3 Trajectory Drift Alert

**Problem:** `update_current_signature()` computes `lineage_similarity` and logs a warning
when it drops below 0.6. Nothing else happens. No audit event, no lifecycle transition,
no notification.

**Fix:** Emit an audit event and optionally trigger a macOS notification:
```python
if lineage_similarity < LINEAGE_ALERT_THRESHOLD:
    await audit_db.append_audit_event_async(
        event_type="trajectory_drift",
        agent_id=agent_id,
        payload={"lineage_similarity": lineage_similarity, "threshold": 0.6}
    )
```
Also add `trajectory_drift` as a CIRS event type so the adaptive governor can factor it in.

**Files:** `src/trajectory_identity.py`, `src/audit_db.py`.

**Complexity:** Low.

### 1.4 KG Write Confidence Cross-Check

**Problem:** An agent can write a discovery with `confidence: 0.95` while its EISV shows
`coherence: 0.2`. The KG trusts the caller's stated confidence.

**Fix:** In the knowledge write path, look up the author's current EISV. If
`discovery.confidence` exceeds `agent.coherence + 0.3`, flag it:
- Clamp stored confidence to `min(stated, coherence + 0.3)`
- Add `confidence_adjusted: true` to provenance
- Emit audit event `kg_confidence_mismatch`

**Files:** `src/storage/knowledge_graph_age.py` (`_persist_discovery_row`),
`src/mcp_handlers/knowledge/handlers.py`.

**Complexity:** Medium. Need to resolve agent EISV at write time — may need to pass
current metrics through the handler chain.

### 1.5 Silence Detection

**Problem:** If an agent stops checking in, nothing notices. Vigil checks every 30 min
but only checks *system* health, not individual agent liveness.

**Fix:** Add a background task (like the existing auto-archiver) that runs every 10 min:
- For each agent with `status=active` and `last_update > expected_interval * 2`:
  - Emit `agent_silent` audit event
  - If `last_update > expected_interval * 5`: auto-archive with reason `silence`
- Skip agents without a defined heartbeat interval (ephemeral sessions).
- Only meaningful for persistent agents (Vigil, Lumen, future Sentinel).

**Files:** `src/agent_lifecycle.py` (new background task), `src/background_tasks.py`.

**Complexity:** Medium. Need to define expected intervals per agent type.

### 1.6 Circuit Breaker Telemetry

**Problem:** Circuit breakers trip, but nobody tracks frequency. A breaker tripping
5 times in an hour is a very different signal than tripping once in a month.

**Fix:** Add counter + timestamp ring buffer to both circuit breakers. Expose via
`get_governance_metrics()`:
```json
{
    "circuit_breakers": {
        "governance": {"trips_1h": 3, "trips_24h": 7, "last_trip": "..."},
        "redis": {"state": "closed", "trips_1h": 0, "failure_count": 2}
    }
}
```
**Files:** `src/agent_loop_detection.py`, `src/cache/redis_client.py`,
`src/mcp_handlers/observability/handlers.py`.

**Complexity:** Low.

---

## Part 2: Sentinel Agent (the irreducible observer)

After the code hardening above, what's left is the stuff that *can't* live inside
governance-mcp — because it needs independence, cross-agent reasoning, and the ability
to question whether governance itself is behaving correctly.

### 2.1 What Sentinel Is

A persistent Python agent (like Vigil) that:
- Connects to governance via WebSocket broadcaster (real-time event stream)
- Queries PostgreSQL directly for historical analysis
- Maintains its own state file (like Vigil's `.vigil_state`)
- Checks in to governance (has its own EISV trajectory)
- Can call governance MCP tools (pause an agent, leave notes, flag discoveries)

### 2.2 What Sentinel Is NOT

- Not a replacement for governance — it's a consumer, not the engine
- Not a firewall or network security tool — that's a different layer
- Not Vigil — Vigil is janitorial (sweep, tidy, report). Sentinel is analytical
  (observe, correlate, intervene)

### 2.3 Core Capabilities

#### A. Fleet-Level Anomaly Detection

**Why code can't do this:** Each agent's behavioral baseline is self-relative. The
governance monitor processes one agent at a time. Nobody asks "are 3 agents all
degrading simultaneously?" — which would indicate a systemic issue (network outage,
governance bug, environmental problem).

**How:**
- Subscribe to broadcaster WebSocket
- Maintain a rolling window of EISV snapshots per agent (last 1h)
- Compute fleet statistics: mean coherence, mean entropy, verdict distribution
- Alert conditions:
  - `>= 3 agents` with coherence drop `> 0.15` in same 10-min window → systemic event
  - Fleet mean entropy rising `> 2σ` from 24h baseline → environmental degradation
  - Verdict distribution shift: `pause` rate `> 20%` of updates → governance may be
    miscalibrated

#### B. Situation Reports

**Why code can't do this:** Requires temporal reasoning and narrative synthesis. "While
you were away: Lumen dropped at 2:14 AM, Vigil detected it at 2:30 AM, 3 agents
got guide verdicts between 2:30-4:00 AM, Lumen recovered at 5:47 AM, all agents
stabilized by 6:00 AM."

**How:**
- On startup (or on-demand via MCP tool), query:
  - `audit.events` for lifecycle transitions in last N hours
  - `outcomes` table for test pass/fail
  - Vigil's state file for health timeline
  - KG for notes tagged `vigil` or `sentinel`
- Synthesize a timeline with causal connections
- Store as a KG discovery tagged `sentinel/sitrep`

#### C. Governance Self-Verification

**Why code can't do this:** Governance can't objectively evaluate itself. If the ODE
parameters drift or a code change breaks coherence calculation, the system would
produce confident but wrong verdicts — and the agents receiving those verdicts
can't tell.

**How:**
- Maintain a set of "canary" expectations:
  - An agent with `E=0.9, I=0.9, S=0.1, V=0.0` should always get `proceed`
  - An agent with `E=0.1, I=0.1, S=0.9, V=0.8` should always get `pause`
  - Sentinel submits synthetic check-ins with known-good inputs periodically
  - If verdict doesn't match expectation → governance is broken
- Compare ODE outputs against analytical bounds (E should never exceed 1.0, S should
  never go negative, coherence should be monotonically related to |V|)
- Track phi distribution over time — sudden mean shift suggests parameter change

#### D. Cross-Agent Identity Correlation

**Why code can't do this:** Identity resolution happens per-request. Nobody asks
"is this agent's trajectory signature suspiciously similar to another agent's?" or
"did two agents share a continuity token?"

**How:**
- Periodically pull all active trajectory signatures from PostgreSQL
- Compute pairwise similarity matrix
- Flag: two agents with `similarity > 0.9` but different UUIDs (possible clone/spoof)
- Flag: same `session_key` appearing for different agent UUIDs (token sharing)
- Track identity assurance tier changes over time per agent

#### E. Incident Correlation

**Why code can't do this:** Individual signals are handled in isolation. Circuit
breaker trip + Lumen health down + KG write spike + 2 agents paused = connected
event. But governance processes each signal in its own handler.

**How:**
- Maintain an event timeline (ring buffer, last 6h)
- Pattern matching rules:
  - Health endpoint down within 5 min of circuit breaker trip → infrastructure event
  - Multiple agents paused within 10 min → systemic, not individual
  - KG write velocity spike from single agent + low coherence → possible poisoning
  - Agent silence + last known healthy → compute accurate downtime window
- Tag correlated events with a shared `incident_id`
- Write incident summary to KG

### 2.4 Intervention Capabilities

Sentinel can act, not just observe. Graduated response:

| Level | Action | Trigger |
|-------|--------|---------|
| 0 — Log | Write KG note, audit event | Any anomaly detected |
| 1 — Alert | macOS notification, Discord webhook | Sustained anomaly (> 2 cycles) |
| 2 — Guide | Inject guidance into agent's next verdict | Identity drift, confidence mismatch |
| 3 — Pause | Call `process_agent_update` to force pause | Active threat (token sharing, KG flood) |
| 4 — Escalate | Notify human (push notification, Discord DM) | Governance self-verification failure |

Level 3+ requires confirmation unless running in autonomous mode.

### 2.5 Architecture

```
                    ┌──────────────────────────┐
                    │    governance-mcp (8767)  │
                    │                          │
                    │  broadcaster ──ws──┐     │
                    │  audit.events      │     │
                    │  outcomes           │     │
                    │  agent_metadata     │     │
                    └─────────┬──────────┘     │
                              │                │
               ┌──────────────┼────────────────┘
               │ MCP tools    │ WebSocket stream
               │              │
        ┌──────▼──────────────▼──────┐
        │        Sentinel            │
        │                            │
        │  ┌─ Fleet Monitor          │
        │  ├─ Identity Correlator    │
        │  ├─ Incident Engine        │
        │  ├─ Governance Verifier    │
        │  └─ Sitrep Generator       │
        │                            │
        │  State: .sentinel_state    │
        │  Log: sentinel.log         │
        │  Cadence: continuous       │
        └────────────────────────────┘
```

### 2.6 How It's Governed

Sentinel checks in to governance like any other agent. It has EISV, gets verdicts,
builds a trajectory. But with a key difference:

- If governance tells Sentinel to pause → Sentinel logs the verdict but does NOT
  stop. Instead it switches to a minimal "heartbeat-only" mode (health checks,
  no interventions) and escalates to human.
- This is the "who watches the watcher" answer: Sentinel trusts governance for
  self-calibration but retains a survival instinct. A governance system that
  incorrectly pauses its own monitor has a bigger problem.
- Sentinel's own behavioral baseline is tracked separately and compared against
  its genesis signature. If *Sentinel* drifts, that's a critical alert.

### 2.7 Operational Details

- **Runtime:** Python script, launchd-managed (like Vigil)
- **Cadence:** WebSocket-driven (continuous), with periodic batch analysis (every 5 min)
- **State:** `.sentinel_state` JSON file (atomic writes, like Vigil)
- **Dependencies:** httpx, websockets, psycopg (direct DB reads — not via MCP for speed)
- **Resource footprint:** Minimal — event processing, no ML inference, no heavy compute
- **Deployment:** Same machine as governance-mcp (localhost access to WebSocket + DB)

---

## Part 3: Implementation Sequence

### Phase 1 — Code Hardening [SHIPPED 2026-04-07]
1. ~~Persist behavioral baselines (1.1)~~
2. ~~Lifecycle event hooks via broadcaster (1.2)~~
3. ~~Circuit breaker telemetry (1.6)~~
4. ~~Trajectory drift alerts (1.3)~~
5. ~~Silence detection (1.5)~~
6. ~~KG confidence cross-check (1.4)~~

### Phase 2 — Sentinel MVP [SHIPPED 2026-04-07]
1. ~~Scaffold: persistent identity, launchd, state file, WebSocket connection~~
2. ~~Fleet monitor: rolling EISV window, coordinated anomaly detection~~
3. ~~Situation reports: query audit trail, synthesize timeline~~
4. ~~Basic intervention: KG notes + macOS notifications~~

### Phase 3 — Advanced Sentinel (ongoing)
1. Governance self-verification (canary check-ins)
2. Cross-agent identity correlation
3. Incident correlation engine
4. Discord webhook integration
5. Intervention levels 2-4

### Phase 4 — Research
1. Formalize the watcher-watches-the-watcher protocol
2. Evaluate: does Sentinel actually catch things? Backtest against incident log
3. Write up for grant/paper: "Self-Monitoring Governance for Autonomous AI Agents"
