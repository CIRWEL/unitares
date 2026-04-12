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

def _is_test_agent(agent_id: str, label: str | None = None) -> bool:
    """Identify test/demo agents by naming patterns.

    Checks both agent_id and label. CLI-spawned pytest agents use UUIDs
    as agent_id but contain 'cli-pytest' in the label.

    Used consistently across list_agents handlers to filter test agents.
    """
    agent_id_lower = agent_id.lower()
    if (
        agent_id.startswith("test_") or
        agent_id.startswith("demo_") or
        agent_id.startswith("test") or
        "test" in agent_id_lower or
        "demo" in agent_id_lower
    ):
        return True
    if label:
        label_lower = label.lower()
        if (
            label_lower.startswith("cli-pytest") or
            label_lower.startswith("test_") or
            label_lower.startswith("test-") or
            "pytest" in label_lower or
            "test" in label_lower.split("-") or
            "test" in label_lower.split("_")
        ):
            return True
    return False
