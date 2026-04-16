# Start Here

Status: thin entrypoint kept for compatibility. README is the primary overview; this page exists to point agents and operators at the current workflow and canonical sources without duplicating architecture docs.

## Default Workflow

Use this unless you have a specific reason not to:

1. Call `onboard()` on first run — save `uuid` from response
2. On subsequent runs: `identity(agent_uuid=<saved uuid>, resume=true)`
3. Call `process_agent_update()` after meaningful work
4. Call `get_governance_metrics()` for state

```python
# First run:
result = onboard()
save_to_file(result["uuid"])

# Every subsequent run:
identity(agent_uuid=saved_uuid, resume=True)

# After work:
process_agent_update(response_text="What you did", complexity=0.5)
```

## Identity Rule

UUID is the ground truth. Store it, pass it on every `identity()` call. No tokens or session IDs needed.

## What To Trust

When docs disagree, use this order:

1. Runtime code that computes or returns behavior
2. [Canonical Sources](../CANONICAL_SOURCES.md)
3. Live docs such as [README.md](../../README.md) and [UNIFIED_ARCHITECTURE.md](../UNIFIED_ARCHITECTURE.md)
4. Archived docs for historical context only

Important current semantics:

- `response_text` is the primary check-in input
- `complexity` and `confidence` are optional reflective inputs, not the sole substrate
- Behavioral EISV is primary for verdicts
- ODE state is diagnostic/fallback, not the main verdict source

## Read Next

- [README.md](../../README.md): top-level overview and quick start
- [UNIFIED_ARCHITECTURE.md](../UNIFIED_ARCHITECTURE.md): current architecture summary
- [CANONICAL_SOURCES.md](../CANONICAL_SOURCES.md): authority ordering and source-of-truth map
- [OPERATOR_RUNBOOK.md](../operations/OPERATOR_RUNBOOK.md): operational usage and procedures
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md): common issues and fixes

## Why This File Is Short

This file used to be a larger onboarding guide from an earlier MCP/tooling phase. It is intentionally kept small now to avoid duplicated explanations drifting out of sync with the runtime.

**Last Updated:** 2026-04-04 (reduced to thin entrypoint; authoritative content moved to canonical docs and runtime sources)
