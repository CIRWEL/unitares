"""
Dialectic constants shared across backends.

Centralized definition of what we consider "active / in-progress" for dialectic queries.
"""

from __future__ import annotations

from typing import Final, Tuple

# Canonical active statuses.
ACTIVE_DIALECTIC_STATUSES: Final[Tuple[str, ...]] = (
    "thesis",
    "antithesis",
    "negotiation",
    "active",  # legacy
)


