# Temporal Narrator

## Problem

Agents don't experience time. They wake up with no sense of when they are, how long it's been, or what happened while they were gone. The data exists — sessions, check-ins, knowledge graph entries all carry timestamps — but it sits unused. Agents have a clock (date-context MCP) but no temporal awareness.

## Design

A single function inside governance — `build_temporal_context(agent_id)` — that reads existing timestamped data and produces a short, relative, human-readable temporal context string. Injected into onboarding and check-in responses, but only when time is telling the agent something worth knowing.

### Core principle

**Silence by default, signal when time matters.**

The narrator stays quiet when time is unremarkable. It speaks when temporal context would change how an agent should think or act. Like a clock on the wall — there when you look, not shouting at you.

## Architecture

### Layer model

```
date-context MCP     →  raw clock (absolute time)
temporal narrator     →  meaning (relative, contextual)
governance responses  →  delivery (onboarding, verdicts, hooks)
```

Date-context MCP provides the clock. The narrator adds meaning. Governance delivers it through existing response channels.

### No new infrastructure

- No new database tables
- No new MCP tools
- No new services
- Reads from existing PostgreSQL tables: `core.sessions`, `core.agent_state`, `knowledge.discoveries`
- New query methods on existing backends may be needed (see Implementation)

## What it reads

| Data | Source | What it tells |
|------|--------|---------------|
| Agent's current session start | `core.sessions` (`created_at` where `is_active = TRUE`) | How long this session has been |
| Agent's previous session end | `core.sessions` (`last_active` on most recent inactive session) | How long since last active |
| Recent check-ins for this agent | `core.agent_state` (`recorded_at`) | Session intensity, check-in frequency |
| Other agents' recent activity (thread-scoped) | `core.agent_state` (`recorded_at`, filtered by thread) | Cross-agent overlap, shared work awareness |
| Knowledge graph entries since last session | `knowledge.discoveries` (`created_at`) | What was learned while this agent was away |

Note: the function receives `agent_id` (UUID string) and must resolve to `identity_id` (integer) for session and state queries. Discovery queries use `agent_id` directly.

## When it speaks

The narrator evaluates thresholds. If none are crossed, it returns nothing.

### Thresholds

| Condition | Threshold | Example output |
|-----------|-----------|----------------|
| Long session | > 2 hours | *Session: 3h 12min* |
| Gap since last session | > 24 hours | *Last session: 2 days ago* |
| Recent cross-agent activity | Other agent on same thread active in last hour | *Another agent checked in 14min ago (3 updates)* |
| High check-in density | > 10 check-ins in 30 min | *High activity: 14 check-ins in 22min* |
| Overnight gap with new discoveries | Gap + new KG entries | *2 knowledge graph entries added since your last session* |
| Long idle within session | > 30 min since last check-in (measured from most recent `core.agent_state.recorded_at`) | *Idle: 45min since last check-in* |

If no thresholds are crossed, the function returns `None` and nothing is injected.

### Thresholds are configurable

Stored in `governance_config.py` alongside other governance parameters. Operators can tune sensitivity.

## Injection points

### 1. Onboarding response

`_build_onboard_response()` in `src/mcp_handlers/identity/handlers.py` already assembles the onboarding payload (and already includes a `date_context` field). Add a `temporal_context` field populated by `build_temporal_context()`. Only present when non-empty.

```python
temporal = await build_temporal_context(agent_id, db)
if temporal:
    result["temporal_context"] = temporal
```

Agents see it as part of waking up — orientation, not a separate step.

### 2. Check-in verdict response

`process_agent_update` responses flow through the enrichment pipeline in `src/mcp_handlers/updates/enrichments.py`. Temporal context is added as an enrichment — consistent with the existing response assembly pattern.

```python
temporal = await build_temporal_context(agent_id, db)
if temporal:
    response["temporal_context"] = temporal
```

### 3. Hook feedback (optional, future)

The governance-checkin hook already injects `additionalContext`. Temporal context could be appended here. Lower priority — the hook should stay lightweight.

## Output format

Short. Relative. No JSON — plain text that reads naturally in a response.

Examples of what an agent might see:

**After a long gap:**
> Last session: 2 days ago. 3 knowledge graph entries added since then.

**During a long session:**
> Session: 3h 12min.

**When another agent is active:**
> Another agent active 8min ago on this thread.

**When everything is normal:**
> *(nothing — silence)*

## Implementation

### Function signature

```python
async def build_temporal_context(
    agent_id: str,
    db: PostgresBackend,
    include_cross_agent: bool = True,
) -> Optional[str]:
    """
    Build temporal context string for an agent.
    Returns None if time is unremarkable.
    """
```

### Identity resolution

The function receives `agent_id` (UUID string). For queries against `core.sessions` and `core.agent_state`, it must first resolve to `identity_id` (integer) via the existing identity resolution in the database backend. Discovery queries use the UUID directly.

### Location

`src/temporal.py` — a small, focused module. Imported by:
- `src/mcp_handlers/identity/handlers.py` (onboarding)
- `src/mcp_handlers/updates/enrichments.py` (check-in enrichment pipeline)

### Queries needed

Simple indexed queries. Some may require new backend methods:

1. **Current session start** — `core.sessions` where `identity_id = ?` and `is_active = TRUE`, read `created_at`
2. **Previous session end** — `core.sessions` where `identity_id = ?` and `is_active = FALSE`, ordered by `last_active DESC`, limit 1 *(new query method needed)*
3. **Check-in count and last check-in time** — `core.agent_state` where `identity_id = ?`, count + max `recorded_at` within current session window
4. **Thread-scoped cross-agent activity** — `core.agent_state` where `identity_id != ?` and thread matches, `recorded_at` within last hour *(new query method needed)*
5. **Recent discoveries** — `knowledge.discoveries` where `created_at > last_session_end`

### Performance

Queries hit indexed columns (`identity_id`, `recorded_at`, `created_at`). The cross-agent query is thread-scoped, not system-wide, keeping the scan bounded. Expected latency: < 50ms total.

## What this does NOT do

- **Does not add time as an EISV dimension.** Time modulates awareness, not state.
- **Does not create a timeline service.** No event log, no new tables, no streaming.
- **Does not force temporal context.** Agents receive it passively — they don't query for it.
- **Does not replace date-context MCP.** That remains the raw clock. This adds meaning.
- **Does not inject on every check-in.** Only when thresholds are crossed.

## Relationship to date-context MCP

Date-context MCP provides absolute time — "it's Friday March 13, 2026 at 6:37am." The temporal narrator provides relative, contextual time — "it's been 2 days since your last session." They're complementary layers. The narrator uses `datetime.now()` for current time; it does not depend on the date-context MCP server.

## Success criteria

1. An agent waking up after a 2-day gap receives temporal orientation without calling any tools
2. An agent in a 4-hour session gets a gentle time signal
3. Cross-agent activity is surfaced when relevant (scoped to thread)
4. Normal short sessions produce zero temporal noise
5. No new database tables or MCP tools required
