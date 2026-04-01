# UNITARES Operator Runbook

This is the simplest local operator path for running UNITARES governance on the Mac host.

## Start

From the repo root:

```bash
./scripts/ops/start_with_deps.sh
```

This waits for Docker, starts `postgres-age` if needed, then launches the governance server on port `8767`.

If you already know dependencies are ready and only want the server:

```bash
./scripts/ops/start_server.sh
```

## Stop

```bash
./scripts/ops/stop_unitares.sh
```

This attempts a graceful stop first, then force-kills only if needed, and cleans up the real `data/.mcp_server.*` files in the repo root.

## Health Check

```bash
./scripts/diagnostics/check_health.sh
```

This verifies:

- local HTTP health on `http://127.0.0.1:8767/health`
- whether `data/.mcp_server.pid` maps to a live process
- whether the `postgres-age` container is running and ready

The `health_check()` tool now also returns `operator_summary`:

- `overall_status`
- `failing_checks`
- `degraded_checks`
- `first_action`

Use `first_action` as the initial remediation hint instead of reading every component block first.

For a deeper live read from the running server, call `health_check()` through MCP or the REST tool API. The shell script is meant to answer "is the local instance up at all?" while `health_check()` is the better source for component-level diagnosis such as Redis, calibration DB, knowledge graph, and Pi connectivity.

## Identity Continuity

The default `onboard()` and `identity()` responses now expose two small continuity fields even when `verbose=false`:

- `session_resolution_source`
- `continuity_token_supported`

The default `identity()` response also includes:

- `identity_status` (`created` or `resumed`)
- `bound_identity` (`uuid`, `agent_id`, `display_name`)

Interpretation:

- `session_resolution_source="continuity_token"` means the agent resumed via a signed continuity token
- `session_resolution_source="explicit_client_session_id"` means the caller passed a stable session ID directly
- `session_resolution_source="mcp_session_id"` or `x_session_id` means the transport provided a stable session key
- `session_resolution_source="pinned_onboard_session"` means the system recovered continuity from the onboard pin
- `session_resolution_source="ip_ua_fingerprint"` means continuity is weaker and the caller should prefer `client_session_id` or `continuity_token`

Operator rule:

- If an agent seems to fork identity unexpectedly, inspect `session_resolution_source` first.
- Prefer `continuity_token` when supported.
- Otherwise pass `client_session_id` explicitly on every call for the most reliable attribution.

The intended minimal agent workflow is:

1. `onboard()`
2. Keep the returned `client_session_id` and any `continuity_token`
3. Use `process_agent_update()` for actual work logging
4. Use `get_governance_metrics()` when you want state without mutating anything
5. Use `identity()` when you need to confirm who the system currently thinks you are

`bind_session()` is not the normal first step. It is mainly for explicit transport bridging or intentional reattachment across MCP and non-MCP paths.

## Expected Endpoints

- MCP: `http://127.0.0.1:8767/mcp/`
- Health: `http://127.0.0.1:8767/health`
- Dashboard: `http://127.0.0.1:8767/dashboard`

## Common Failure Modes

### Stale PID file

Symptom:

- `check_health.sh` reports `PID file: stale or unreadable`

Fix:

```bash
./scripts/ops/stop_unitares.sh
./scripts/ops/start_with_deps.sh
```

### PostgreSQL container not running

Symptom:

- `check_health.sh` reports `postgres-age container not running`

Fix:

```bash
docker start postgres-age
./scripts/ops/start_with_deps.sh
```

### HTTP health down

Symptom:

- `check_health.sh` reports `HTTP: Not responding`

Fix:

```bash
./scripts/ops/start_with_deps.sh
```

If that still fails, inspect:

```bash
tail -f /tmp/unitares.log
```

### Knowledge graph degraded

Symptom:

- `health_check()` reports `knowledge_graph` as degraded or warning
- `operator_summary.degraded_checks` includes `knowledge_graph`

Interpretation:

- If `knowledge_graph.info.error` mentions `graph with oid ... does not exist`, the AGE catalog and schema drifted out of sync.
- Current runtime logic will attempt to repair the AGE graph and rehydrate it from durable PostgreSQL tables.
- If recovery succeeds, `knowledge_graph.status` should return to `healthy` and the discovery counts should be nonzero again.

What to check:

- `health_check().checks.knowledge_graph.lifecycle`
- `health_check().checks.knowledge_graph.info`
- server logs during startup or first KG access

### Weak continuity

Symptom:

- `identity()` shows `session_resolution_source="ip_ua_fingerprint"`
- agents appear to "resume" into unexpected identities

Fix:

- rerun `onboard()`
- keep the returned `client_session_id`
- if `continuity_token_supported=true`, prefer the continuity token on future calls

### Start script exits unexpectedly

Symptom:

- the wrapper script starts the server and then the process exits during shutdown/cleanup

Interpretation:

- This points to process-management or event-loop cleanup behavior, not necessarily a core governance failure
- confirm with `health_check()` whether a live server is still reachable before assuming the whole stack is down

## Practical Triage Order

When something feels wrong, do the checks in this order:

1. Run `./scripts/diagnostics/check_health.sh`
2. If HTTP is up, call `health_check()`
3. If an agent identity looks wrong, call `identity()`
4. If the issue is governance-state related, call `get_governance_metrics()`
5. Only after that inspect logs or restart services

This order matters because many apparent "agent bugs" are actually continuity or process issues, and many apparent "graph bugs" are now observable directly through `health_check()` without guessing from symptoms.
