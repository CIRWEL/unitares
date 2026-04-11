# Governance — Reusable SQL Queries

*Reference SQL for the production governance database. All queries are SELECT only; none modify data.*

**Connect:** `psql postgresql://postgres:postgres@localhost:5432/governance`

---

## Full pause population by agent and verdict

Reproduces the pause breakdown used in `DEPLOYMENT_DATA_CAVEAT.md`.

```sql
SELECT
    payload->>'agent_id' AS agent_id_payload,
    agent_id,
    payload->>'unitares_verdict' AS verdict,
    COUNT(*) AS pause_count
FROM audit.events
WHERE event_type = 'auto_attest'
  AND payload->>'decision' = 'pause'
GROUP BY agent_id, payload->>'unitares_verdict'
ORDER BY pause_count DESC;
```

Alternatively, using the top-level `agent_id` column directly:

```sql
SELECT
    agent_id,
    payload->>'unitares_verdict' AS verdict,
    COUNT(*) AS pause_count
FROM audit.events
WHERE event_type = 'auto_attest'
  AND payload->>'decision' = 'pause'
GROUP BY agent_id, payload->>'unitares_verdict'
ORDER BY pause_count DESC;
```

Expected shape: ~7 rows. `test_stress` dominates with ~1,400 high-risk pauses (93% of total). See `DEPLOYMENT_DATA_CAVEAT.md` for interpretation.

---

## Reproduce paper Table 3 (verdict x decision crosstab)

Reconstructs the verdict x decision breakdown from `audit.events` payload JSON.

```sql
SELECT
    payload->>'unitares_verdict' AS verdict,
    payload->>'decision'         AS decision,
    COUNT(*)                     AS count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM audit.events
WHERE event_type = 'auto_attest'
  AND payload->>'unitares_verdict' IS NOT NULL
GROUP BY 1, 2
ORDER BY count DESC;
```

**Note:** Values as of 2026-04-10 differ slightly from the paper's Table 3 (which reflects a Mar 30 snapshot): current figures are approximately 10,142 caution/proceed, 9,787 safe/proceed, 1,407 high-risk/pause. Drift may reflect verdict reclassification after a schema migration or continued check-in volume. See `DEPLOYMENT_DATA_CAVEAT.md` for the seesaw caveat before citing these numbers.

---

## Event type distribution in audit.events

```sql
SELECT
    event_type,
    COUNT(*) AS count
FROM audit.events
GROUP BY event_type
ORDER BY count DESC;
```

Expected: `auto_attest` ~21,535, `cross_device_call` ~8,476, `complexity_derivation` ~6,273, `eisv_sync` ~3,661, then smaller categories.

---

## Payload key frequency for auto_attest events

Useful for discovering the schema of the `payload` JSONB column.

```sql
SELECT
    jsonb_object_keys(payload) AS key,
    COUNT(*) AS count
FROM audit.events
WHERE event_type = 'auto_attest'
GROUP BY 1
ORDER BY count DESC;
```

Expected top keys: `risk_score`, `ci_passed`, `decision` (~21,552 each), then `reason`, `unitares_verdict`, `coherence`, `void_active` (~21,435), then `continuity` and `beh_obs` (~6,719), then `k` (1). See `DATA_NOTES.md` for field-level documentation.

---

## Lumen-specific queries

**Count Lumen state records in core.agent_state:**

```sql
SELECT COUNT(*) AS lumen_state_rows
FROM core.agent_state
WHERE agent_id = 'eisv-sync-task';
```

Expected: ~96,000 rows (sensor polling updates).

**eisv_sync events date range and count:**

```sql
SELECT
    COUNT(*) AS total_events,
    MIN(ts)  AS first_event,
    MAX(ts)  AS last_event
FROM audit.events
WHERE event_type = 'eisv_sync';
```

**Lumen pause events (the governance-stability tension signal):**

```sql
SELECT
    ts,
    payload->>'unitares_verdict' AS verdict,
    payload->>'decision'         AS decision,
    payload->>'reason'           AS reason,
    (payload->>'risk_score')::float AS risk_score,
    (payload->>'coherence')::float  AS coherence
FROM audit.events
WHERE event_type = 'auto_attest'
  AND agent_id = 'eisv-sync-task'
  AND payload->>'decision' = 'pause'
ORDER BY ts DESC
LIMIT 20;
```

These 95 pause rows are the primary empirical signal for the thermostat pathology discussed in the paper. Lumen's physical low-E / high-I sensor state is stable, but the contracting ODE interprets the E-I gap as drift.

---

## Outcome events schema probe

```sql
SELECT
    outcome_type,
    COUNT(*) AS count,
    ROUND(AVG(outcome_score)::numeric, 3) AS avg_score,
    SUM(CASE WHEN is_bad THEN 1 ELSE 0 END) AS bad_count
FROM audit.outcome_events
GROUP BY outcome_type
ORDER BY count DESC;
```

---

## Pause audit sample

The pause audit sampler is at `papers/scripts/pause_audit_sampler.py`. It has two modes:

- **Random sample** (`--mode random --n 50`): draws 50 uniformly random pause events from `audit.events` where `decision='pause'`, writes to `papers/data/pause_audit_50.csv`.
- **Stratified sample** (`--mode stratified`): samples proportionally across agent categories and verdict classes, writes to `papers/data/pause_audit_43.csv`.

Output files already exist at:
- `papers/data/pause_audit_43.csv`
- `papers/data/pause_audit_50.csv`

A companion classifier is at `papers/scripts/pause_audit_classify.py` for labeling sampled rows.
