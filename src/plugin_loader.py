"""Entry-point-based plugin discovery for governance-mcp.

Discovers packages that advertise the ``governance_mcp.plugins`` entry
point group (``[project.entry-points."governance_mcp.plugins"]`` in
their ``pyproject.toml``) and calls each plugin's ``register()``
function at governance startup.

A plugin's ``register()`` may:
  - import its handler modules so ``@mcp_tool`` decorators fire and
    populate governance's tool registry,
  - call ``action_router(...)`` to wire a consolidated action-dispatch
    tool,
  - merge extra tool descriptions, aliases, and Pydantic schemas via
    the ``register_extra_*`` hook functions in governance.

Set ``UNITARES_DISABLE_PLUGINS=1`` to skip plugin loading entirely
(useful for test isolation and stripped OSS builds).
"""

from __future__ import annotations

import os
from importlib.metadata import entry_points
from typing import List

from src.logging_utils import get_logger

logger = get_logger(__name__)

_ENTRY_POINT_GROUP = "governance_mcp.plugins"


def load_plugins() -> List[str]:
    """Load every registered ``governance_mcp.plugins`` entry point.

    Returns the list of plugin names that registered successfully. A
    failed plugin logs a warning and is skipped so one broken plugin
    can't take governance down.
    """
    if os.environ.get("UNITARES_DISABLE_PLUGINS"):
        logger.info("plugin loading skipped (UNITARES_DISABLE_PLUGINS set)")
        return []

    loaded: List[str] = []
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        try:
            register_fn = ep.load()
            register_fn()
            loaded.append(ep.name)
            logger.info("plugin loaded: %s (from %s)", ep.name, ep.value)
        except Exception as e:  # noqa: BLE001 — intentional broad catch
            logger.warning("plugin failed: %s (%s): %s", ep.name, ep.value, e)
    return loaded
