"""Base types for Vigil's check registry.

A Check is a small async unit that Vigil runs each cycle. Built-in checks live
in this package; external checks are registered via VIGIL_CHECK_PLUGINS (see
registry.load_plugins). Plugins depend on this module — this module never
imports from plugins. That keeps the dependency direction one-way: unitares
knows nothing about Lumen/anima.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol, runtime_checkable

Severity = Literal["info", "warning", "critical"]


@dataclass
class CheckResult:
    ok: bool
    summary: str
    detail: Optional[dict[str, Any]] = None
    severity: Severity = "warning"
    fingerprint_key: str = ""


@runtime_checkable
class Check(Protocol):
    name: str
    service_key: str

    async def run(self) -> CheckResult: ...
