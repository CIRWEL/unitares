"""
Shared helpers for lifecycle handler modules.

Private utilities used across query, mutation, and operations modules.
"""

from src.logging_utils import get_logger
from src.cache import get_metadata_cache

logger = get_logger(__name__)


async def _invalidate_agent_cache(agent_id: str) -> None:
    """Invalidate Redis metadata cache for an agent. Best-effort, never raises."""
    try:
        await get_metadata_cache().invalidate(agent_id)
    except Exception as e:
        logger.debug(f"Cache invalidation failed: {e}")

def _is_test_agent(agent_id: str) -> bool:
    """Identify test/demo agents by naming patterns.

    Used consistently across list_agents handlers to filter test agents.
    """
    agent_id_lower = agent_id.lower()
    return (
        agent_id.startswith("test_") or
        agent_id.startswith("demo_") or
        agent_id.startswith("test") or
        "test" in agent_id_lower or
        "demo" in agent_id_lower
    )
