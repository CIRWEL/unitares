"""
Dialectic constants shared across backends.

The dialectic "status" column differs across historical backends:
- PostgreSQL uses phase-like statuses: thesis/antithesis/negotiation/...
- SQLite historically used status='active' for in-progress sessions.

To prevent cross-backend drift bugs, centralize the definition of what we consider
"active / in-progress" for queries.
"""

from __future__ import annotations

from typing import Final, Tuple

# Canonical active statuses (include legacy SQLite 'active' for compatibility).
ACTIVE_DIALECTIC_STATUSES: Final[Tuple[str, ...]] = (
    "thesis",
    "antithesis",
    "negotiation",
    "active",  # legacy (SQLite)
)


