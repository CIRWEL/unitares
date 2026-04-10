# Spec: Option F — Cached Health Snapshots

**Date:** 2026-04-10
**Status:** SHIPPED (in progress — implementation follows this spec)
**Predecessor:** `2026-04-09-anyio-asyncio-refactor.md` (recommended this approach)

## Problem restated

`handle_health_check` calls `get_health_check_data`, which awaits ~10 asyncpg/Redis/KG operations inline. When invoked from an MCP tool handler (inside the SDK's anyio task group), those awaits deadlock. The 20s handler timeout fires, REST `POST /v1/tools/call` hangs, and operators lose visibility.

Background tasks (e.g., `periodic_matview_refresh`, `periodic_partition_maintenance`) successfully `await` asyncpg from the main event loop outside the anyio request context. The deadlock is specific to the call-site context, not to asyncpg itself.

## Design

**Split health into three layers.** Probe the deep layer on the main loop; serve reads from memory.

### Layer 1 — Liveness
- **Endpoint:** `GET /health/live`
- **Semantics:** Process is up, event loop is scheduling
- **Implementation:** Returns `{"status": "alive", "version": ..., "uptime_seconds": ...}` immediately
- **No DB, no Redis, no lock acquisition**
- **Backwards compat:** `GET /health` already does this (just asserts pool attributes + connection count); it stays as-is for existing load balancer configs

### Layer 2 — Readiness
- **Endpoint:** `GET /health/ready`
- **Semantics:** Lifespan entered, `server_ready_fn()` returns true, streamable_http transport reachable
- **Implementation:** Returns 200 with `{"status": "ready"}` when ready, 503 with `{"status": "warming_up"}` otherwise
- **No DB — checks in-memory flags only**

### Layer 3 — Deep health (the interesting one)
- **Endpoint:** `POST /v1/tools/call` with `health_check` tool (MCP parity) and `GET /health/deep` (new REST convenience)
- **Semantics:** Full component status (PostgreSQL, Redis, KG, Pi, calibration, audit log, data dir)
- **Implementation:** Reads a cached snapshot produced by a periodic probe on the main loop

## Components

### 1. Cache module — `src/services/health_snapshot.py`

```python
"""Cached health snapshot shared between the probe task and the health_check handler."""
import asyncio
import time
from typing import Optional

_snapshot: Optional[dict] = None
_snapshot_monotonic: Optional[float] = None
_snapshot_wall: Optional[float] = None
_lock = asyncio.Lock()

async def set_snapshot(data: dict) -> None:
    """Called only by the probe task."""
    global _snapshot, _snapshot_monotonic, _snapshot_wall
    async with _lock:
        _snapshot = data
        _snapshot_monotonic = time.monotonic()
        _snapshot_wall = time.time()

def get_snapshot() -> tuple[Optional[dict], Optional[float], Optional[float]]:
    """Synchronous read — safe because writes are atomic dict replacements.

    Returns (snapshot, age_seconds, produced_at_wall) or (None, None, None)
    if the probe has not populated the cache yet.
    """
    if _snapshot is None or _snapshot_monotonic is None:
        return None, None, None
    age = time.monotonic() - _snapshot_monotonic
    return _snapshot, age, _snapshot_wall

def clear_snapshot() -> None:
    """Test helper — resets module state."""
    global _snapshot, _snapshot_monotonic, _snapshot_wall
    _snapshot = None
    _snapshot_monotonic = None
    _snapshot_wall = None
```

**Concurrency model:** single writer (probe task), many readers. Dict replacement is atomic in CPython, and the probe rebuilds the whole dict each cycle — so reads never see a half-built snapshot. The lock exists for the benefit of future multi-probe scenarios; readers don't need it.

### 2. Probe task — `src/background_tasks.py`

Add `deep_health_probe_task(interval_seconds: float = 30.0)`:
- Initial sleep: 5s (let DB pool warm up)
- Loop: call `get_health_check_data({"lite": False})` → write snapshot → sleep
- On exception: log warning, sleep 10s, retry (supervised by `_supervised_create_task`)
- Do NOT use `_in_mcp` detection — probe runs outside MCP handler context, wants full data

Wire into `start_all_background_tasks`:
```python
_supervised_create_task(deep_health_probe_task(), name="deep_health_probe")
```

### 3. Handler refactor — `src/mcp_handlers/admin/handlers.py`

```python
@mcp_tool("health_check", timeout=5.0, rate_limit_exempt=True)
async def handle_health_check(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Read the cached health snapshot (produced by deep_health_probe_task).

    Does NOT touch the database — that is what caused the anyio/asyncpg
    deadlock. See docs/handoffs/2026-04-10-option-f-spec.md.
    """
    from src.services.health_snapshot import get_snapshot
    snapshot, age_seconds, produced_at = get_snapshot()

    if snapshot is None:
        return error_response(
            "Health snapshot not yet available — probe has not run. "
            "Try again in a few seconds.",
            metadata={"retry_after_seconds": 5}
        )

    # Lite filter operates on the cached copy — does not re-run checks
    lite = arguments.get("lite", True)
    response = _filter_lite(snapshot) if lite else dict(snapshot)
    response["_cache"] = {
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "produced_at": produced_at,
        "stale": age_seconds > STALENESS_THRESHOLD_SECONDS if age_seconds else True,
        "probe_interval_seconds": PROBE_INTERVAL_SECONDS,
    }
    return success_response(response)
```

Reduce the handler timeout from 20s to 5s — there's no legitimate reason a memory read should take more than a few milliseconds.

### 4. REST routes — `src/http_api.py`

Add two new routes alongside the existing `/health`:
- `GET /health/live` → `http_health_live` (trivial: server up)
- `GET /health/ready` → `http_health_ready` (checks `server_ready_fn()`)
- `GET /health/deep` → `http_health_deep` (reads `get_snapshot()`)

Keep `GET /health` as-is for backwards compat.

## Staleness contract

- **Probe interval:** 30s (configurable via `UNITARES_HEALTH_PROBE_INTERVAL_SECONDS`)
- **Staleness threshold:** 90s (3x interval)
- Clients check `_cache.age_seconds` and `_cache.stale` fields
- If `_cache.stale == true`, the probe is backed up or crashed — operators should investigate

## Testing

Unit tests in `tests/test_health_snapshot.py`:
1. `set_snapshot` populates cache, `get_snapshot` returns it
2. `get_snapshot` returns `(None, None, None)` before any `set_snapshot`
3. Age increases monotonically across calls
4. `clear_snapshot` resets state

Unit tests in `tests/test_health_handler_cached.py`:
1. Handler returns error when snapshot is None
2. Handler returns snapshot contents when cache is populated
3. Handler marks stale when age exceeds threshold
4. Lite filter strips per-check details
5. Handler is timing-independent — does NOT call `get_health_check_data` directly

## Risks

1. **First-call window:** 5s initial delay + 30s probe interval means deep-health is unavailable for the first ~5s after start. Operators must use liveness/readiness during that window.
2. **Probe crash:** Supervised task auto-restarts. If it fails repeatedly, stale flag trips and operators see explicit staleness rather than silent hangs.
3. **Memory:** Snapshot is ~5KB. Negligible.
4. **Test isolation:** Tests must reset the module-level snapshot via `clear_snapshot()` in `setUp`/fixtures.

## Non-goals

- Fixing the underlying anyio/asyncpg conflict (that's Option C or full migration)
- Changing non-health MCP tools that may have similar deadlock characteristics — out of scope for this PR
