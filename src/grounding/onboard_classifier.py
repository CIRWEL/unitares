"""S8a Phase-1 default-stamp: classify fresh identities at onboard.

Rule (2-branch, per docs/ontology/s8a-tag-discipline-audit.md):
  - ``name`` matches ``KNOWN_RESIDENT_LABELS`` → resident default tags.
  - otherwise → ``["ephemeral"]``.

If the caller already supplied tags, return ``None`` to signal "don't
override." This preserves backward compatibility with callers that stamp
their own class tag at onboard time (SDK residents, custom harnesses).

The rule deliberately does NOT introduce new classes (``resident_lineage``,
``session_like``). Phase 1 populates the existing ``ephemeral`` bucket;
Phase 2 decides what promotes out of it based on observed behavior.
"""
from __future__ import annotations

from typing import Iterable, Optional

from src.grounding.class_indicator import KNOWN_RESIDENT_LABELS

# Mirror of agents/sdk/src/unitares_sdk/agent.py:RESIDENT_TAGS. Residents
# need BOTH tags: 'persistent' protects from auto_archive_orphan_agents,
# 'autonomous' exempts from loop-detection pattern 4. Keeping the list in
# sync across SDK and server is a known Phase-1 cost.
RESIDENT_DEFAULT_TAGS = ["persistent", "autonomous"]
EPHEMERAL_DEFAULT_TAGS = ["ephemeral"]


def default_tags_for_onboard(
    name: Optional[str],
    existing_tags: Optional[Iterable[str]] = None,
) -> Optional[list[str]]:
    """Return the default tag list to stamp at onboard, or ``None``.

    Args:
      name: Display name supplied at onboard (e.g. "Lumen"). Matched
        exactly against ``KNOWN_RESIDENT_LABELS``; structured labels like
        "Lumen_abc123" do not match.
      existing_tags: Tags already on the identity metadata. If truthy,
        the caller has asserted class and the default must not override.

    Returns:
      ``None`` when ``existing_tags`` is non-empty (skip stamping).
      ``RESIDENT_DEFAULT_TAGS`` when ``name`` is a known resident.
      ``EPHEMERAL_DEFAULT_TAGS`` otherwise.
    """
    if existing_tags:
        return None

    if name and name in KNOWN_RESIDENT_LABELS:
        return list(RESIDENT_DEFAULT_TAGS)

    return list(EPHEMERAL_DEFAULT_TAGS)
