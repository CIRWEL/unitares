"""Tool descriptions for MCP tool definitions. Loaded from JSON."""
import json
from pathlib import Path

_DESCRIPTIONS_FILE = Path(__file__).parent / "tool_descriptions.json"

_IDENTITY_DESCRIPTION_OVERRIDES = {
    "onboard": (
        "Start or create a UNITARES identity binding.\n\n"
        "Current identity posture (S1-a, 2026-04-24): use "
        "onboard(force_new=true) for a fresh process. If this process is "
        "continuing prior work, include parent_agent_id=<prior uuid> and "
        "spawn_reason='new_session'. Do not rely on bare onboard() because "
        "legacy weak session evidence can pin-resume an unrelated UUID.\n\n"
        "continuity_token is short-lived ownership proof for same-owner "
        "rebinding and PATH 0 anti-hijack; it is not indefinite "
        "cross-process continuity. Cross-process onboard(continuity_token=...) "
        "is accepted only during the S1-a deprecation window and should be "
        "migrated to force_new=true plus parent_agent_id lineage declaration.\n\n"
        "Name/model fields are cosmetic/contextual. The returned uuid is an "
        "identity anchor, not proof that future processes own it."
    ),
    "identity": (
        "Inspect the current identity binding or perform a proof-owned rebind.\n\n"
        "Use identity() with no arguments to see the current bound identity. "
        "Use identity(name='...') to set a cosmetic display label.\n\n"
        "For an explicit UUID rebind, pass both agent_uuid and a matching "
        "continuity_token: identity(agent_uuid='...', continuity_token='...', "
        "resume=true). Bare identity(agent_uuid='...', resume=true) is an "
        "unsigned UUID claim and is hijack-shaped under strict identity mode.\n\n"
        "For a fresh process continuing prior work, do not use identity() to "
        "silently resume. Call onboard(force_new=true, parent_agent_id=<prior "
        "uuid>, spawn_reason='new_session') so lineage is explicit."
    ),
}


def _load_descriptions() -> dict:
    with open(_DESCRIPTIONS_FILE, encoding="utf-8") as f:
        descriptions = json.load(f)
    # Keep the large legacy JSON stable while overriding fast-moving identity
    # teaching text close to the S1-a implementation.
    descriptions.update(_IDENTITY_DESCRIPTION_OVERRIDES)
    return descriptions


TOOL_DESCRIPTIONS = _load_descriptions()


def register_extra_descriptions(descriptions: dict) -> None:
    """Merge plugin-supplied tool descriptions into ``TOOL_DESCRIPTIONS``.

    Called by ``governance_mcp.plugins`` entry-point plugins during
    ``plugin_loader.load_plugins()``. Existing keys are overwritten
    silently — the last loader wins, same precedence as the JSON file.
    """
    TOOL_DESCRIPTIONS.update(descriptions)
