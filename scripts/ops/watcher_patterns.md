# Watcher Pattern Library

Curated bug patterns for the Watcher agent. Seeded from real incidents in the
UNITARES project. The Watcher feeds this file to a local LLM (gemma4 via Ollama)
and asks for pattern-matches against recently edited code.

**Edit freely.** Add patterns you've been bitten by. Remove patterns that produce
too many false positives. The Watcher reloads this file on every run.

## Severity levels

- **critical** — data loss, security, irrecoverable state
- **high** — runtime failure, resource exhaustion, deadlock
- **medium** — degradation, leaks, unbounded growth
- **low** — smell, style, best-practice

## Patterns

### P001 — Fire-and-forget task leak (severity: high)

Creating `asyncio.create_task(...)` inside a loop or per-event handler without
storing the task reference for later cancellation or cleanup.

**Seen in:** `background_tasks.py` stuck_agent_recovery_task (2026-04-10 incident,
1.1GB RSS runaway)

**Hint template:** `fire-and-forget task — store ref or use TaskGroup`

### P002 — Unbounded dict/list growth (severity: medium)

`dict[key] = value` or `list.append(x)` inside a loop or per-event handler
without a cap, LRU eviction, or periodic sweep.

**Seen in:** `adaptive_prediction.py`, `serialization.py` (Ogler finds, 2026-04),
`lifecycle_events` cap fix (2026-04-07)

**Hint template:** `unbounded growth — needs cap or eviction`

### P003 — Transient monitor pattern (severity: high, project-specific)

Creating a `UNITARESMonitor(agent_id)` instance outside of
`mcp_server.get_or_create_monitor()`. The cached factory inserts into
`mcp_server.monitors`; bypassing it creates throwaway instances that never enter
the cache and cause init storms over time.

**Seen in:** `stuck.py:175-186` (2026-04-10 incident)

**Hint template:** `transient monitor — use get_or_create_monitor`

### P004 — DB-touching code inside MCP tool handler (severity: high, project-specific)

Any `await` on asyncpg or Redis inside an `@mcp_tool`-decorated handler. The
anyio task group in the MCP SDK's StreamableHTTP transport deadlocks with
asyncpg/Redis async calls. Symptom: `/v1/tools/call` hangs indefinitely for that
tool.

**Seen in:** `health_check` (still deadlocks), KG lifecycle, eisv_sync

**Hint template:** `asyncpg inside MCP handler — will deadlock, wrap in executor`

### P005 — Acquire without paired release (severity: high)

`pool.acquire()`, `lock.acquire()`, `connection.cursor()`, or similar resource
acquisitions without a paired release in a `finally:` or `async with` context.

**Hint template:** `acquired resource not released on all paths`

### P006 — Silent exception swallow (severity: medium)

`except Exception: pass` or `except Exception: logger.warning(...)` without
re-raising. Hides real bugs and makes debugging impossible.

**Hint template:** `silent swallow — log and re-raise or narrow the except`

<!-- P007 has been demoted to the EXPERIMENTAL section below.
     Detecting it requires reasoning about temporal flow (which pool was
     acquired vs. which is being released to), which the local 8B model
     can't do reliably without flagging the FIX as a bug. See the
     experimental section for the original definition. -->


### P008 — Unchecked shell input (severity: critical)

`subprocess.run(..., shell=True)` or `os.system(...)` with any string that
includes user/external input without `shlex.quote` or a list-form invocation.

**Hint template:** `shell injection — use shlex.quote or list-form subprocess`

### P009 — Runaway polling without iteration cap (severity: medium)

`while True:` or `while condition:` loops that poll for state with `sleep`
without a max-iteration guard or timeout. Can hang agents indefinitely if the
expected state change never arrives.

**Hint template:** `unbounded poll — needs max-iteration or timeout`

### P010 — Missing test coverage on behavior change (severity: low)

New behavior (a bound, cap, eviction, cleanup branch) added without a matching
test. This is a standing rule for this project — see
`feedback_tests-with-fixes.md`.

**Hint template:** `behavior change needs test in same commit`

### P011 — mutate-then-persist in memory (severity: high, project-specific)

Mutating in-memory state BEFORE (or WITHOUT) the corresponding DB persistence
call. The temporal ordering matters: **persist must come first**, then mutate.

**BAD (flag this):**
```python
meta.status = "archived"           # in-memory mutation
await archive_agent(agent_id)      # persist comes after — race & clobber risk
```

**ALSO BAD (flag this):**
```python
meta.status = "archived"           # mutation with no persist call anywhere
# (nothing else)
```

**GOOD — DO NOT FLAG:**
```python
await archive_agent(agent_id)      # persist first
meta.status = "archived"           # mutation comes after — correct ordering
```

If you see `await <something_persist_like>(...)` BEFORE the mutation in the
same function/block, the code is correctly ordered. Do not flag it.

**Seen in:** `auto_archive_orphan_agents` in `agent_lifecycle.py:134-148` (the
pre-fix version was archiving 73 agents on every cron cycle with no persistence
at all). The fix added `await archive_agent()` before the in-memory mutation —
the post-fix code is the GOOD example above.

**Hint template:** `mutation before persistence — will be clobbered on next load`

### P012 — json.loads / yaml.load on untrusted input (severity: medium)

Parsing JSON or YAML from external sources (HTTP bodies, files, MCP tool args)
without schema validation. Pydantic v2 schemas in `src/mcp_handlers/schemas/`
are the project-standard way.

**Hint template:** `unvalidated parse — add pydantic schema`

### P013 — --no-verify / --amend after hook failure (severity: critical, process)

Not a code pattern but a process one. Never bypass pre-commit hooks with
`--no-verify`, and never `git commit --amend` after a pre-commit hook failure
(the failure means the commit did NOT happen; amend would modify the PREVIOUS
commit and risk losing work). Fix the underlying issue and create a NEW commit.

**Hint template:** `bypass/amend after hook fail — fix root cause, new commit`

### P014 — Force push / reset --hard on shared branches (severity: critical, process)

`git push --force`, `git reset --hard origin/X`, `git branch -D` without
explicit user approval. See the 2026-02-25 incident: another Claude session
force-pushed master and lost ~80 commits on the remote.

**Hint template:** `destructive git op — requires explicit user approval`

### P015 — Docker commands against retired containers (severity: medium, project-specific)

Any `docker exec postgres-age` or `docker-compose` command targeting the retired
`postgres-age` container. The canonical database is Homebrew PostgreSQL@17 on
port 5432. Docker postgres-age is retired; commands targeting it will either
fail or hit stale data.

**Hint template:** `docker postgres-age retired — use homebrew psql on 5432`

## Experimental patterns

These are real bug shapes that the 8B local model cannot reliably detect
without false-positiving on the FIX for the bug. They're documented here so
the knowledge isn't lost. Re-promote them once we have either (a) a structural
verifier in `watcher_agent.py` or (b) a larger model with stronger temporal
reasoning.

### EXP-P007 — Path acquired from one pool, released to another (high)

Using `postgres_backend.py` pool helpers where `acquired_pool` is not tracked
and the connection gets released to a different pool than it was acquired from.

**Why disabled:** Detecting this requires distinguishing the bad shape (no
`acquired_pool` field) from the fix shape (`acquired_pool` is tracked and
release is gated on `current_pool is acquired_pool`). The local model flags
both as P007. Needs an AST-based verifier that walks the class and confirms
no per-pool tracking exists. See `src/db/postgres_backend.py:170-205` for the
post-fix reference shape.

**Seen in:** `src/db/postgres_backend.py` pool mismatch bug

## Adding new patterns

When Watcher flags a real bug you would have missed, add a new pattern here
with:
1. A unique `Pxxx` id
2. A severity
3. A "Seen in:" reference with the commit or incident date
4. A hint template Watcher should use when surfacing the pattern

The Watcher rewards you for curation: confirmed finds on a pattern raise its
priority; dismissed finds lower it. Over time the library becomes a bespoke
bug-hunter tuned to your codebase.
