"""Stub `governance_core.utils`."""

from __future__ import annotations

from typing import Sequence


def drift_norm(delta_eta: Sequence[float]) -> float:
    if not delta_eta:
        return 0.0
    s = 0.0
    for x in delta_eta:
        s += float(x) * float(x)
    return float(s ** 0.5)
