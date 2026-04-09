"""Workflow orchestration for process_agent_update."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from mcp.types import TextContent

from src.logging_utils import get_logger
from src.services.update_response_service import (
    build_process_update_response_data,
    serialize_process_update_response,
)

logger = get_logger(__name__)


async def run_process_update_workflow(ctx, *, serializer=None) -> Sequence[TextContent]:
    """Execute the extracted process_agent_update workflow for a prepared UpdateContext."""
    from src.mcp_handlers.updates.phases import (
        execute_locked_update,
        execute_post_update_effects,
        handle_onboarding_and_resume,
        resolve_identity_and_guards,
        transform_inputs,
    )
    from src.mcp_handlers.updates.pipeline import run_enrichment_pipeline
    from src.mcp_handlers.response_formatter import format_response
    from src.mcp_handlers.utils import error_response

    early_exit = await resolve_identity_and_guards(ctx)
    if early_exit:
        return early_exit

    early_exit = await handle_onboarding_and_resume(ctx)
    if early_exit:
        return early_exit

    early_exit = transform_inputs(ctx)
    if early_exit:
        return early_exit

    try:
        async with ctx.mcp_server.lock_manager.acquire_agent_lock_async(ctx.agent_id, timeout=5.0, max_retries=3):
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
