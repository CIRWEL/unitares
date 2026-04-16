# Lock Contention Fix: Narrow Critical Section in process_agent_update

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate timeout spikes by moving enrichments and post-update DB writes outside the agent lock, reducing lock hold time from seconds to milliseconds.

**Architecture:** The lock in `update_workflow_service.py:45` currently wraps ODE update + post-update DB writes + 28 enrichments (KG queries, Redis I/O, LLM calls). Only the ODE update needs serialization. We restructure the workflow to release the lock immediately after the ODE update completes, then run everything else lock-free. Secondary: bump the lock timeout from 2.0s/1-retry to 5.0s/3-retries as safety margin.

**Tech Stack:** Python 3.12+, asyncio, pytest

---

### Task 1: Write failing test — enrichment runs outside lock

**Files:**
- Modify: `tests/test_update_workflow_service.py`

- [ ] **Step 1: Write the failing test**

This test asserts that `run_enrichment_pipeline` is called AFTER the lock context manager exits. We use a spy on the lock's `__aexit__` to record ordering.

```python
@pytest.mark.asyncio
async def test_enrichment_runs_outside_lock():
    """Enrichment pipeline must execute after the agent lock is released."""
    call_order = []

    class _OrderTrackingLock:
        async def __aenter__(self):
            call_order.append("lock_acquired")
            return self

        async def __aexit__(self, exc_type, exc, tb):
            call_order.append("lock_released")
            return False

    ctx = SimpleNamespace(
        mcp_server=MagicMock(),
        agent_id="agent-123",
        agent_uuid="uuid-123",
        arguments={},
        identity_assurance={"tier": "strong"},
        result={"status": "ok"},
        meta=None,
        is_new_agent=False,
        key_was_generated=False,
        api_key_auto_retrieved=False,
        task_type="mixed",
        loop=AsyncMock(),
    )
    ctx.mcp_server.lock_manager.acquire_agent_lock_async.return_value = _OrderTrackingLock()
    ctx.mcp_server.monitors = {"agent-123": {"dummy": True}}

    async def fake_enrichment(c):
        call_order.append("enrichment_ran")

    with patch("src.mcp_handlers.updates.phases.resolve_identity_and_guards", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.handle_onboarding_and_resume", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.transform_inputs", return_value=None), \
         patch("src.mcp_handlers.updates.phases.execute_locked_update", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.execute_post_update_effects", new=AsyncMock()), \
         patch("src.mcp_handlers.updates.pipeline.run_enrichment_pipeline", new=AsyncMock(side_effect=fake_enrichment)), \
         patch("src.mcp_handlers.response_formatter.format_response", return_value={"status": "formatted"}), \
         patch("src.services.update_workflow_service.serialize_process_update_response", return_value=["done"]):
        result = await run_process_update_workflow(ctx)

    assert result == ["done"]
    # Key assertion: enrichment must come AFTER lock_released
    assert call_order.index("lock_released") < call_order.index("enrichment_ran"), \
        f"Enrichment ran inside the lock! Order: {call_order}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_update_workflow_service.py::test_enrichment_runs_outside_lock -v`
Expected: FAIL with "Enrichment ran inside the lock!"

- [ ] **Step 3: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add tests/test_update_workflow_service.py
git commit -m "test: assert enrichment pipeline runs outside agent lock"
```

---

### Task 2: Write failing test — post-update effects run outside lock

**Files:**
- Modify: `tests/test_update_workflow_service.py`

- [ ] **Step 1: Write the failing test**

Same pattern — verify `execute_post_update_effects` runs after lock release.

```python
@pytest.mark.asyncio
async def test_post_update_effects_run_outside_lock():
    """Post-update DB writes must execute after the agent lock is released."""
    call_order = []

    class _OrderTrackingLock:
        async def __aenter__(self):
            call_order.append("lock_acquired")
            return self

        async def __aexit__(self, exc_type, exc, tb):
            call_order.append("lock_released")
            return False

    ctx = SimpleNamespace(
        mcp_server=MagicMock(),
        agent_id="agent-123",
        agent_uuid="uuid-123",
        arguments={},
        identity_assurance={"tier": "strong"},
        result={"status": "ok"},
        meta=None,
        is_new_agent=False,
        key_was_generated=False,
        api_key_auto_retrieved=False,
        task_type="mixed",
        loop=AsyncMock(),
    )
    ctx.mcp_server.lock_manager.acquire_agent_lock_async.return_value = _OrderTrackingLock()
    ctx.mcp_server.monitors = {"agent-123": {"dummy": True}}

    async def fake_post_effects(c):
        call_order.append("post_effects_ran")

    with patch("src.mcp_handlers.updates.phases.resolve_identity_and_guards", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.handle_onboarding_and_resume", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.transform_inputs", return_value=None), \
         patch("src.mcp_handlers.updates.phases.execute_locked_update", new=AsyncMock(return_value=None)), \
         patch("src.mcp_handlers.updates.phases.execute_post_update_effects", new=AsyncMock(side_effect=fake_post_effects)), \
         patch("src.mcp_handlers.updates.pipeline.run_enrichment_pipeline", new=AsyncMock()), \
         patch("src.mcp_handlers.response_formatter.format_response", return_value={"status": "formatted"}), \
         patch("src.services.update_workflow_service.serialize_process_update_response", return_value=["done"]):
        result = await run_process_update_workflow(ctx)

    assert result == ["done"]
    assert call_order.index("lock_released") < call_order.index("post_effects_ran"), \
        f"Post-update effects ran inside the lock! Order: {call_order}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_update_workflow_service.py::test_post_update_effects_run_outside_lock -v`
Expected: FAIL with "Post-update effects ran inside the lock!"

- [ ] **Step 3: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add tests/test_update_workflow_service.py
git commit -m "test: assert post-update effects run outside agent lock"
```

---

### Task 3: Narrow the critical section — move work outside lock

**Files:**
- Modify: `src/services/update_workflow_service.py:44-82`

- [ ] **Step 1: Restructure the workflow**

Replace the current lock block (lines 44-82) with a narrowed critical section. Only `execute_locked_update` stays inside the lock. Everything else moves after the `async with` block.

The new structure of `run_process_update_workflow` (lines 44 onwards):

```python
    try:
        async with ctx.mcp_server.lock_manager.acquire_agent_lock_async(
            ctx.agent_id, timeout=5.0, max_retries=3
        ):
            early_exit = await execute_locked_update(ctx)
            if early_exit:
                return early_exit

            # Capture monitor ref while lock guarantees consistent state
            ctx.monitor = ctx.mcp_server.monitors.get(ctx.agent_id)
    except TimeoutError:
        try:
            from src.lock_cleanup import cleanup_stale_state_locks
            project_root = Path(__file__).resolve().parent.parent
            cleanup_result = await ctx.loop.run_in_executor(
                None, cleanup_stale_state_locks, project_root, 60.0, False
            )
            if cleanup_result["cleaned"] > 0:
                logger.info(f"Auto-recovery: Cleaned {cleanup_result['cleaned']} stale lock(s) after timeout")
        except Exception as cleanup_error:
            logger.warning(f"Could not perform emergency lock cleanup: {cleanup_error}")

        return [error_response(
            f"Failed to acquire lock for agent '{ctx.agent_id}' after automatic retries and cleanup. "
            f"This usually means another active process is updating this agent. "
            f"The system has automatically cleaned stale locks. If this persists, try: "
            f"1) Wait a few seconds and retry, 2) Check for other Cursor/Claude sessions, "
            f"3) Use cleanup_stale_locks tool, or 4) Restart Cursor if stuck."
            ,
            error_code="LOCK_TIMEOUT",
            error_category="system_error",
            details={
                "lock_error": True,
                "agent_id": ctx.agent_id,
            },
            arguments=ctx.arguments,
        )]

    # --- Everything below runs OUTSIDE the lock ---

    await execute_post_update_effects(ctx)

    ctx.response_data = build_process_update_response_data(
        result=ctx.result,
        agent_id=ctx.agent_id,
        identity_assurance=ctx.identity_assurance,
        monitor=ctx.monitor,
    )

    await run_enrichment_pipeline(ctx)

    try:
        ctx.response_data = format_response(
            ctx.response_data,
            ctx.arguments,
            meta=ctx.meta,
            is_new_agent=ctx.is_new_agent,
            key_was_generated=ctx.key_was_generated,
            api_key_auto_retrieved=ctx.api_key_auto_retrieved,
            task_type=ctx.task_type,
        )
    except Exception as fmt_err:
        logger.error(f"Response formatting failed: {fmt_err}", exc_info=True)

    ctx.arguments["lite_response"] = True
    return serialize_process_update_response(
        response_data=ctx.response_data,
        agent_uuid=ctx.agent_uuid,
        arguments=ctx.arguments,
        fallback_result=ctx.result,
        serializer=serializer,
    )
```

- [ ] **Step 2: Run the new ordering tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_update_workflow_service.py -v`
Expected: All 5 tests PASS (including the 2 new ordering tests)

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
cd /Users/cirwel/projects/governance-mcp-v1
git add src/services/update_workflow_service.py
git commit -m "fix: narrow agent lock to ODE-only, move enrichments and DB writes outside

Reduces lock hold time from seconds (ODE + 28 enrichments + DB writes)
to milliseconds (ODE only). Eliminates timeout spikes caused by lock
contention when enrichments hit slow KG queries or DB pool exhaustion.

Also bumps lock timeout from 2.0s/1-retry to 5.0s/3-retries."
```

---

### Task 4: Verify existing happy-path test still passes with new structure

**Files:**
- Read: `tests/test_update_workflow_service.py`

- [ ] **Step 1: Run all workflow tests**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/test_update_workflow_service.py -v`
Expected: All tests PASS. The existing `test_run_process_update_workflow_happy_path` and `test_run_process_update_workflow_timeout_uses_lock_error_category` should still pass unchanged because they mock `execute_post_update_effects` and `run_enrichment_pipeline` — the mocks don't care whether they're called inside or outside the lock.

- [ ] **Step 2: Run full suite one more time**

Run: `cd /Users/cirwel/projects/governance-mcp-v1 && python3 -m pytest tests/ -q --tb=short -x`
Expected: All pass. No regressions.
