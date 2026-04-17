"""Built-in governance health check.

Probes the governance MCP's /health endpoint once per cycle. This check is
always present — unlike Lumen health, governance is the thing Vigil needs in
order to check in at all, so there's no point making it optional.
"""

from __future__ import annotations

import os
import time
from typing import Tuple

import httpx

from .base import CheckResult

GOVERNANCE_HEALTH_URL = os.environ.get(
    "GOVERNANCE_HEALTH_URL", "http://localhost:8767/health"
)


def check_http_health(url: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Sync HTTP health probe — mirrors the helper in agent.py intentionally.

    Duplicated rather than imported so `agent.py` can be refactored independently
    and so tests can monkeypatch this symbol in isolation.
    """
    start = time.monotonic()
    try:
        resp = httpx.get(url, timeout=timeout)
        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            try:
                data = resp.json()
                status = data.get("status", "ok")
                return True, f"{status} ({latency_ms}ms)"
            except Exception:
                return True, f"ok ({latency_ms}ms)"
        return False, f"HTTP {resp.status_code} ({latency_ms}ms)"
    except httpx.ConnectError:
        return False, "unreachable"
    except httpx.TimeoutException:
        return False, f"timeout (>{int(timeout*1000)}ms)"
    except Exception as e:
        return False, str(e)


class GovernanceHealth:
    name = "governance_health"
    service_key = "governance"

    async def run(self) -> CheckResult:
        # Reach through the module to pick up monkeypatches in tests.
        from . import governance_health as _this
        ok, detail = _this.check_http_health(_this.GOVERNANCE_HEALTH_URL)
        if ok:
            return CheckResult(ok=True, summary=f"Governance: {detail}")
        return CheckResult(
            ok=False,
            summary=f"Governance: UNHEALTHY ({detail})",
            severity="critical",
            fingerprint_key="governance_down",
        )
