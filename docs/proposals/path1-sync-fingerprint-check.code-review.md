# Code Review — PATH 1 Sync-Path Fingerprint Check

**Reviewer:** feature-dev:code-reviewer (subagent) · **Date:** 2026-04-25
**Proposal:** `path1-sync-fingerprint-check.md`
**Verdict:** needs-revisions (resolved by parallel-dict approach)

## Critical — FALLBACK scan can silently overwrite a pre-existing binding fingerprint

`shared.py:156-166`. The proposal's option B ("first-bind under current fingerprint, gate subsequent resumes") fails on a cold-index re-entry. After a server restart wipes `_uuid_prefix_index`, the same `agent-{uuid12}` session arrives again, falls into the FALLBACK scan path (because the index is cold), and the proposed write of `bind_ip_ua = current_fp` overwrites what should have been the original binding fingerprint. An attacker who knows the session ID and is on a different IP/UA can manufacture a cold-index condition (any restart or cache eviction suffices) and have their fingerprint recorded as the binding fingerprint.

`_cache_session` at `persistence.py:63-143` defends against this on the async side via the merge-on-binding-exists pattern. The sync FALLBACK has no equivalent.

**Fix:** before writing `bind_ip_ua` at the FALLBACK scan site, check whether a binding fingerprint already exists for this session_key and skip the write if so. Implementation falls out naturally from the parallel-dict alternative below.

Confidence: 92.

## Important — In-memory record from `_cache_session` omits `bind_ip_ua`

`_session_identities[key] = {...}` is written in four places without `bind_ip_ua`:

- `shared.py:148-153` (O(1) index hit path)
- `shared.py:160-165` (FALLBACK scan path)
- `shared.py:179-184` (non-`agent-` key empty-record path)
- `persistence.py:81-96` (in-memory portion of `_cache_session`) — writes `bind_ip_ua` to **Redis** via `_cache_session_redis_write` (line 173), but the in-memory `new_binding` dict at lines 82-95 has no `bind_ip_ua` field.

A session originally cached via `_cache_session` will have a stale in-memory record without the field. The O(1) path in `_get_identity_record_sync` reads `_session_identities[key]` directly (line 137) and returns it before reaching the fingerprint check — silent skip.

**Fix (resolves both issues):** introduce a parallel `_bind_fingerprints: Dict[str, str]` keyed by `session_key`. Written by `_cache_session` and the FALLBACK path (only when not already present), read by `_get_identity_record_sync`. This:

- Doesn't require changing the four `_session_identities` dict-assignment sites — they don't need to know about `bind_ip_ua` at all.
- Makes "is there a binding fingerprint?" a single source of truth.
- Survives wholesale record replacement at line 148 (the O(1) path constructs a fresh record from `agent_metadata`).
- Closes the FALLBACK overwrite by making the "skip if already populated" check trivial.

Confidence: 88.

## Per-question findings

### 1 · Call site inventory

`_get_identity_record_sync` has exactly two external call sites:

- `get_bound_agent_id` at `shared.py:204` — chained to `is_session_bound` and `require_write_permission`. The synchronous identity-check surface used by every tool handler that cannot await.
- `TestGetIdentityRecordSync` at `tests/test_identity_shared.py:252` — test-only.

Both are on the MCP tool dispatch path where session signals are set in contextvars. The proposal's silent-passthrough concern (no `current_fp` → skip gate) is not a live issue today, but a future caller from a background task would silently bypass the gate. **Add `logger.debug` at the skip branch** so it's visible in logs as the call surface grows.

Confidence: 85.

### 2 · In-memory record schema

See "Important" above. Parallel dict resolves it.

### 3 · Parallel-dict recommendation

**Adopt it.** Cleaner than mutating the record shape. The existing four dict-assignment sites stay as-is. Two new write points (`_cache_session`, FALLBACK), one new read point (`_get_identity_record_sync`). Survives wholesale record replacement. Resolves both the critical and important issues at once.

### 4 · Event taxonomy

Sentinel's `FleetState.analyze` at `agents/sentinel/agent.py:257-271` pattern-matches on `event.get("type", "").startswith("identity_")` — does not filter by the `path` subfield. Dashboard receives raw events and renders `event_type`. Both consumers see `identity_hijack_suspected` regardless of `path`. **Keep `path1_sync_session_id` as proposed** — Sentinel's incident correlator merges naturally, while the `path` field lets operators grep logs to see which surface fired. No downstream changes needed.

Confidence: 80.

### 5 · Test plan feasibility

Existing `TestGetIdentityRecordSync` in `tests/test_identity_shared.py:252-341` uses synchronous fixtures with `patch` for `mcp_server` and `get_context_session_key`. Proposed tests need two additional patches: `get_session_signals` and `session_fingerprint_check_mode`. Both are available as module-level imports in `shared.py` and patchable at the same target path as existing mocks. No new fixtures required.

Confidence: 88.

### 6 · The DEPRECATED claim

The `DEPRECATED` docstring is on `_get_session_key` (line 67), **not** on `_get_identity_record_sync`. The proposal's out-of-scope note misidentifies which function is marked. `_get_identity_record_sync` has no active migration — `get_bound_agent_id` calls it explicitly, and `require_write_permission` → `is_session_bound` → `get_bound_agent_id` chain is used throughout the tool layer. **Hardening is the right call.** Killing the function would propagate `await` into `require_write_permission` and every handler that calls it — large blast radius, separate PR.

Confidence: 85.

## Required revisions before implementation

1. **Adopt the parallel-dict (`_bind_fingerprints`) approach.** Don't mutate the `_session_identities` record shape. Resolves both the critical FALLBACK overwrite and the silent-skip from `_cache_session`'s in-memory write.
2. **Guard FALLBACK scan against overwriting an existing fingerprint.** Falls out trivially from the parallel-dict approach: only write to `_bind_fingerprints[key]` when `key` is not already present.
3. **Wire `_cache_session` to populate `_bind_fingerprints`** in addition to the Redis write. Single new line.
4. **Add `logger.debug` at the silent-skip branch** of the fingerprint check so future background-task callers don't bypass the gate invisibly.
5. **Correct the DEPRECATED reference** in the out-of-scope section (function is `_get_session_key`, not `_get_identity_record_sync`).
