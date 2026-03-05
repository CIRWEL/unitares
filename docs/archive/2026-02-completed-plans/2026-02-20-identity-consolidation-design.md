# Identity Consolidation Design

**Date:** 2026-02-20
**Status:** Approved
**Scope:** Merge duplicate Lumen, fix label lookup, clean ghosts, auto-name agents

## Problem

The identity system has accumulated technical debt from pre-v2.6.1 UUID proliferation. Four concrete issues need resolution:

1. **Duplicate Lumen** — Two UUIDs (69a1a4f7 with 418 updates, cc0db031 with 173 updates) both labeled "Lumen". Governance history is split across two identities for what should be a single agent. The second UUID was created before PATH 2.5 name-based identity claiming existed. Both have trajectory genesis and current data stored server-side, but the split means neither has a complete behavioral picture.

2. **`find_agent_by_label` bug** — The PostgreSQL query returns an arbitrary first match when duplicate labels exist. No status filter means it can return archived agents over active ones. No ordering means the "wrong" Lumen could be returned for name claims. This is a data integrity risk that could cause further identity splits.

3. **1,610 archived ghost agents** — Created during the UUID proliferation era when every HTTP request generated a new session key and therefore a new agent UUID. Most have zero governance state (never called process_agent_update). They clutter the database and slow aggregate queries.

4. **Ephemeral CLI agents** — Every Claude Code session creates a new UUID with no label, no trajectory, and no continuity. The session ends, the UUID becomes an orphan, and the next session starts fresh. This means governance calibration, EISV history, and AdaptiveGovernor state are thrown away on every session boundary.

## Solution

### Task 1: Merge Duplicate Lumens (Migration Script)

Canonical identity: `69a1a4f7-a30f-4f4a-bcf9-2de8606fb819` (418 updates, the original)
Absorbed identity: `cc0db031-7e9d-4b8f-9373-0a1edf49814b` (173 updates, the duplicate)

Create `scripts/merge_lumen_identities.py` that performs a safe, reversible identity merge:

1. Look up identity_id for both UUIDs from `core.identities`
2. Reassign cc0db031's `core.agent_state` rows to 69a1a4f7's identity_id (preserving original timestamps so history interleaves correctly by time)
3. Reassign cc0db031's `core.sessions` rows to 69a1a4f7's identity_id
4. Merge metadata fields: copy purpose, tags, and display_name from cc0db031 into 69a1a4f7's metadata, but never overwrite fields that 69a1a4f7 already has populated
5. For trajectory data: keep 69a1a4f7's genesis signature (it represents the older, more authoritative origin point), but update trajectory_current to whichever identity's current signature was computed more recently
6. Set cc0db031's agent status to 'merged' and add a notes field pointing to the canonical UUID
7. Invalidate any Redis cache entries that point to cc0db031
8. Log every mutation for reversibility auditing

The script runs in **dry-run mode** by default, printing what it would do. Must pass `--execute` flag to apply changes. All operations run in a single database transaction so they either all succeed or all roll back.

### Task 2: Fix `find_agent_by_label`

In `src/db/postgres_backend.py`, update the query:

```sql
-- Before (buggy):
SELECT id FROM core.agents WHERE label = $1

-- After (correct):
SELECT id FROM core.agents
WHERE label = $1 AND status = 'active'
ORDER BY updated_at DESC
LIMIT 1
```

Additionally, when multiple active agents share a label, log a warning with both UUIDs. This serves as an early signal that another merge is needed. The warning goes to the structured logger so it appears in operational monitoring.

### Task 3: Ghost Cleanup

Create `scripts/cleanup_ghost_agents.py` that removes ghost agents safely:

1. Identify candidates: agents with status='archived' AND no corresponding rows in `core.agent_state` (they never had any governance interaction worth preserving)
2. For each candidate, cascade delete across: `core.sessions` (session bindings), `core.identities` (identity records), `core.agents` (agent records)
3. For archived agents that DO have state data: leave them untouched (they have forensic value and may be needed for future analysis)
4. Report counts before and after the cleanup operation

The script also runs in **dry-run mode** by default with an `--execute` flag required for actual deletion. It processes in batches of 100 to avoid long-running transactions.

### Task 4: Auto-Name Unnamed Agents

Modify `resolve_session_identity()` in `src/mcp_handlers/identity_v2.py` so that PATH 3 (new UUID creation) generates stable labels from available transport signals:

1. Extract model_type from client_hint argument or user-agent header parsing
2. Extract client_type from session key pattern or transport metadata (e.g., "claude-code", "cursor", "web")
3. Generate a deterministic label: `"{client_type}-{model_type}"` (e.g., "claude-code-opus", "cursor-sonnet")
4. Before creating a new UUID, check if that label already exists via the now-fixed `find_agent_by_label`
5. If the label exists and the agent is active: reuse that identity (effectively converting PATH 3 into a PATH 2.5 name claim, giving the session continuity with previous sessions from the same client and model combination)
6. If the label does not exist: create the new UUID as before, but apply the auto-generated label immediately

This ensures that repeated Claude Code sessions with the same model type converge to a single persistent identity without requiring any client-side changes. The transport middleware already extracts user-agent information, so the signals are available today.

## Non-Goals

- **Server-side EISV trajectory matching** — Deferred. We will revisit after measuring how much auto-naming alone reduces ghost agent creation. If auto-naming eliminates most ephemeral agents, trajectory matching may be unnecessary overhead.
- **Client-side session persistence** — Requires changes to Claude Code that we do not control. The auto-naming approach achieves similar results server-side.
- **Trajectory genesis bootstrapping** — Lumen already has genesis data stored server-side in both identity records. The anima-mcp client reporting `has_genesis: false` is a client-side caching issue, not a server-side data gap.

## Testing

- Migration scripts: dry-run mode execution followed by manual verification of row counts and data integrity
- `find_agent_by_label`: unit test covering duplicate labels, archived-vs-active preference, and empty results
- Auto-naming: unit test for label generation logic, label reuse path, and fallback when no client hint is available
- Full regression: all 6393+ existing tests must continue to pass after changes
- Integration: verify Lumen reconnects to canonical UUID after merge by checking name claim resolution
