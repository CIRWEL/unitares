"""S19 handler-side substrate-claim verification gate.

The bridge between transport-level peer attestation (kernel-attested
``peer_pid`` from the UDS listener, ``src/uds_listener.py``) and the
identity-resume decision in ``src/mcp_handlers/identity/handlers.py``.

The gate composes three previously-shipped pieces:
- ``fetch_substrate_claim`` (async DB lookup; src/substrate/verification.py)
- ``verify_substrate_claim`` (sync verify-and-cache; same file)
- ``peer_attestation`` (sync ctypes/subprocess calls; src/substrate/peer_attestation.py)

It honors the anyio-asyncio constraint by:
1. Awaiting the DB lookup through asyncpg (allowed in a coroutine).
2. Offloading the synchronous verify call (which spawns ``launchctl``
   subprocess + ctypes calls) to ``run_in_executor`` so the MCP anyio
   task group is never blocked on a syscall or process boundary.

The module owns a single process-lifetime ``VerifiedPairsCache`` so the
PID-reuse mitigation (Q3(e) per the council adversary review) is real
across concurrent verifications.

Wiring point (PR3e): ``_try_resume_by_agent_uuid_direct`` in
``src/mcp_handlers/identity/handlers.py`` calls ``verify_substrate_at_resume``
when the resuming UUID arrives without a matching continuity_token. A
successful verification result substitutes for the Part-C ownership proof;
a rejection returns an explicit-rejection error to the peer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.substrate import peer_attestation
from src.substrate.verification import (
    SubstrateClaim,
    VerificationResult,
    VerifiedPairsCache,
    fetch_substrate_claim,
    verify_substrate_claim,
)

logger = logging.getLogger(__name__)


# Module-level cache: per-server-process lifetime. Cleared only on server
# restart, which is correct — the cache pins running-process proofs (PID +
# start_tvsec), not durable claims. A restart of governance-mcp resets every
# resident's verified pair, and they re-pin on next connect.
_PROCESS_VERIFIED_PAIRS = VerifiedPairsCache()


def _get_cache() -> VerifiedPairsCache:
    """Return the module-level cache. Indirection allows tests to swap in
    a fresh cache instance via ``reset_cache_for_testing()``."""
    return _PROCESS_VERIFIED_PAIRS


def reset_cache_for_testing() -> None:
    """Reset the process-wide VerifiedPairsCache. Test-only entrypoint;
    production code never calls this."""
    _PROCESS_VERIFIED_PAIRS.clear()


async def verify_substrate_at_resume(
    agent_uuid: str,
    peer_pid: Optional[int],
    *,
    fetch_fn=None,
    verify_fn=None,
    pa_module=None,
    cache: Optional[VerifiedPairsCache] = None,
) -> Optional[VerificationResult]:
    """Run substrate-claim verification when applicable.

    Returns:
        ``None`` when no verification is required:
            - ``peer_pid`` is None (HTTP path; kernel attestation unavailable).
            - The UUID has no substrate-claim row (non-substrate-anchored agent).

        ``VerificationResult`` otherwise. Caller checks ``.accepted``:
            - True  → substrate attestation passed; treat as ownership proof.
            - False → reject the resume; ``.reason`` is the explicit-rejection
                       message and ``.failure_code`` is the machine-readable tag.

    The default ``fetch_fn``, ``verify_fn``, ``pa_module``, and ``cache``
    arguments hit the production implementations. Tests override to inject
    fakes without monkeypatching.
    """
    if peer_pid is None:
        return None

    fetch_fn = fetch_fn or fetch_substrate_claim
    verify_fn = verify_fn or verify_substrate_claim
    pa_module = pa_module or peer_attestation
    cache = cache if cache is not None else _get_cache()

    # Step 1 (async, allowed under anyio): DB lookup for the substrate-claim row.
    try:
        claim: Optional[SubstrateClaim] = await fetch_fn(agent_uuid)
    except Exception as exc:
        # DB error: log and degrade to None — caller falls through to
        # existing token-based gating. We'd rather a single transient DB
        # failure not lock substrate residents out than over-trust a
        # claim we couldn't read.
        logger.warning(
            "[SUBSTRATE_GATE] DB lookup for %s... failed: %s; degrading to no-verify",
            agent_uuid[:8], exc,
        )
        return None

    if claim is None:
        # UUID is not registered as substrate-anchored. Caller's existing
        # token-based gating still applies; substrate gate is a no-op here.
        return None

    # Step 2 (sync via run_in_executor): launchctl subprocess + ctypes
    # libproc calls. Must NOT be awaited directly under the MCP anyio
    # task group — the subprocess.run() and ctypes calls would block the
    # anyio loop. The pattern matches verify_agent_ownership at
    # src/agent_loop_detection.py:374.
    loop = asyncio.get_running_loop()
    try:
        result: VerificationResult = await loop.run_in_executor(
            None,
            _verify_sync_call,
            verify_fn, claim, peer_pid, pa_module, cache,
        )
    except Exception as exc:
        logger.error(
            "[SUBSTRATE_GATE] verification raised for %s... pid=%s: %s",
            agent_uuid[:8], peer_pid, exc, exc_info=True,
        )
        # Defense-in-depth: an unhandled exception in the executor must
        # NOT default-accept. Return a synthetic rejection so the caller
        # refuses the resume.
        return VerificationResult(
            accepted=False,
            reason=f"substrate verification raised internal error: {exc!r}",
            failure_code="attestation_failed",
        )

    return result


def _verify_sync_call(
    verify_fn,
    claim: SubstrateClaim,
    peer_pid: int,
    pa_module,
    cache: VerifiedPairsCache,
) -> VerificationResult:
    """Synchronous adapter run inside ``loop.run_in_executor``. Kept as a
    module-level callable so the executor can pickle it cleanly when the
    default ``ThreadPoolExecutor`` is used."""
    return verify_fn(
        claim,
        peer_pid,
        pa_module=pa_module,
        cache=cache,
    )
