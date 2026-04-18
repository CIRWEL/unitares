#!/usr/bin/env python3
"""
Vigil — The First Resident

A persistent agent that runs every 30 minutes via launchd, checks system health,
and checks in to governance. Builds the longest-running EISV trajectory in the
system. Leaves notes in the knowledge graph when something changes, creating
continuity between ephemeral Claude Code sessions.

Usage:
    python3 agents/vigil/agent.py              # Health checks only (default)
    python3 agents/vigil/agent.py --with-tests  # Also run test suites (~15 min)
    python3 agents/vigil/agent.py --daemon      # Continuous loop

What it does each cycle:
    1. Resumes persistent "Vigil" identity (same UUID across all cycles)
    2. Checks governance health (HTTP /health)
    3. Checks Lumen/anima health (HTTP /health, LAN → Tailscale fallback)
    4. (optional) Runs governance-mcp + anima-mcp pytest suites
    5. Detects changes from previous cycle, leaves notes in knowledge graph
    6. Checks in to governance with findings (process_agent_update)
    7. Self-recovers if paused
    8. Logs one-line summary
"""

import asyncio

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx

from agents.common.config import GOV_MCP_URL
from agents.common.log import trim_log as _trim_log
from unitares_sdk.agent import CycleResult, GovernanceAgent
from unitares_sdk.client import GovernanceClient
from unitares_sdk.errors import GovernanceError, VerdictError
from unitares_sdk.utils import notify
from agents.common.findings import post_finding, compute_fingerprint
from agents.vigil.checks.registry import load_plugins
from agents.vigil.checks.runner import run_health_checks

# Paths
ANIMA_PROJECT = Path(os.getenv("ANIMA_PROJECT", str(project_root.parent / "anima-mcp")))
SESSION_FILE = Path.home() / ".unitares" / "anchors" / "vigil.json"
LEGACY_SESSION_FILE = project_root / ".vigil_session"
STATE_FILE = project_root / ".vigil_state"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-vigil.log"
MAX_LOG_LINES = 500

# Test timeout
TEST_TIMEOUT = 180  # 3 minutes per suite

# Wall-clock cap for a single heartbeat cycle.
CYCLE_TIMEOUT = int(os.getenv("HEARTBEAT_CYCLE_TIMEOUT", "120"))


_interactive = sys.stdout.isatty()


def log(message: str):
    """Append timestamped line to log file. Also prints if running interactively."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    if _interactive:
        print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def detect_changes(prev: Dict[str, Any], current: Dict[str, Any]) -> List[Dict[str, str]]:
    """Compare previous and current cycle state. Returns list of notable changes."""
    notes: List[Dict[str, str]] = []

    # Health status transitions
    for service in ("governance", "lumen"):
        prev_ok = prev.get(f"{service}_healthy")
        curr_ok = current.get(f"{service}_healthy")
        if prev_ok is not None and prev_ok != curr_ok:
            if curr_ok:
                notes.append({
                    "summary": f"{service.title()} recovered (was down)",
                    "tags": ["vigil", "recovery", service],
                })
            else:
                notes.append({
                    "summary": f"{service.title()} is down ({current.get(f'{service}_detail', '?')})",
                    "tags": ["vigil", "outage", service],
                })

    # Consecutive Lumen outage
    prev_streak = prev.get("lumen_down_streak", 0)
    curr_streak = current.get("lumen_down_streak", 0)
    if curr_streak >= 3 and curr_streak > prev_streak and curr_streak % 3 == 0:
        hours = curr_streak * 0.5  # 30-min cycles
        notes.append({
            "summary": f"Lumen unreachable for {curr_streak} consecutive cycles (~{hours:.0f}h)",
            "tags": ["vigil", "outage", "lumen", "sustained"],
        })

    # EISV drift
    prev_coherence = prev.get("coherence")
    curr_coherence = current.get("coherence")
    if prev_coherence is not None and curr_coherence is not None:
        if curr_coherence < 0.40 and prev_coherence >= 0.40:
            notes.append({
                "summary": f"Vigil coherence dropped below 0.40 ({curr_coherence:.3f})",
                "tags": ["vigil", "drift", "coherence"],
            })

    prev_verdict = prev.get("verdict")
    curr_verdict = current.get("verdict")
    if prev_verdict and curr_verdict and prev_verdict != curr_verdict:
        if curr_verdict in ("pause", "reject"):
            notes.append({
                "summary": f"Vigil verdict changed: {prev_verdict} -> {curr_verdict}",
                "tags": ["vigil", "verdict", curr_verdict],
            })

    # Groundskeeper: staleness spike detection
    prev_stale = prev.get("groundskeeper_stale", 0)
    curr_stale = current.get("groundskeeper_stale", 0)
    if curr_stale > prev_stale + 10:
        notes.append({
            "summary": f"KG staleness spike: {prev_stale} -> {curr_stale} stale entries",
            "tags": ["vigil", "groundskeeper", "drift"],
        })

    return notes


def _collect_health_state(
    check_results: List[Tuple[Any, Any]],
    prev_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Turn check results into Vigil's state-dict fragments.

    Preserves the existing state file keys (``governance_healthy``,
    ``lumen_healthy``, ``gov_up_cycles``, ``lumen_up_cycles``,
    ``lumen_down_streak``, ``lumen_last_ok_url``) so the refactor is
    invisible to the persisted .vigil_state format. Plugin-persistent
    fields are pulled from ``result.detail``.
    """
    state: Dict[str, Any] = {}
    by_key = {c.service_key: r for c, r in check_results}

    gov_r = by_key.get("governance")
    gov_healthy = gov_r.ok if gov_r else True
    state["governance_healthy"] = gov_healthy
    state["governance_detail"] = gov_r.summary if gov_r else "no check"
    state["gov_up_cycles"] = prev_state.get("gov_up_cycles", 0) + (1 if gov_healthy else 0)

    lumen_r = by_key.get("lumen")
    anima_healthy = lumen_r.ok if lumen_r else True
    state["lumen_healthy"] = anima_healthy
    state["lumen_detail"] = lumen_r.summary if lumen_r else "not configured"
    state["lumen_up_cycles"] = prev_state.get("lumen_up_cycles", 0) + (1 if anima_healthy else 0)

    lumen_down_streak = 0
    if lumen_r and not anima_healthy:
        lumen_down_streak = prev_state.get("lumen_down_streak", 0) + 1
    state["lumen_down_streak"] = lumen_down_streak

    if lumen_r and lumen_r.detail:
        state.update(lumen_r.detail)

    return state


def run_pytest(project_dir: Path, label: str) -> Tuple[bool, int, int, str]:
    """Run pytest on a project. Returns (passed, n_passed, n_failed, summary)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line", "-x"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
        )
        output = result.stdout + result.stderr
        import re
        n_passed = 0
        n_failed = 0
        for line in output.splitlines():
            line_lower = line.lower()
            if "passed" in line_lower or "failed" in line_lower:
                passed_match = re.search(r"(\d+)\s+passed", line_lower)
                failed_match = re.search(r"(\d+)\s+failed", line_lower)
                if passed_match:
                    n_passed = int(passed_match.group(1))
                if failed_match:
                    n_failed = int(failed_match.group(1))

        passed = result.returncode == 0
        summary = f"{label}: {'PASS' if passed else 'FAIL'} ({n_passed} passed, {n_failed} failed)"
        return passed, n_passed, n_failed, summary
    except subprocess.TimeoutExpired:
        return False, 0, 0, f"{label}: TIMEOUT ({TEST_TIMEOUT}s)"
    except Exception as e:
        return False, 0, 0, f"{label}: ERROR ({e})"


# Sentinel findings that trigger a groundskeeper pass even when --no-audit is set.
# These are fleet-level symptoms that a KG audit can help surface or remediate.
_SENTINEL_AUDIT_TRIGGERS = frozenset({
    "verdict_distribution_shift",
    "correlated_governance_events",
})


def _filter_sentinel_findings(
    results: List[Dict[str, Any]], since_iso: Optional[str]
) -> List[Dict[str, Any]]:
    """Filter raw search_knowledge results down to recent Sentinel high-severity notes.

    Sentinel writes notes tagged ``["sentinel", <finding_type>, "high"]``. We
    want only those, only created after ``since_iso`` (Vigil's last cycle time),
    and annotated with the extracted finding type.
    """
    out: List[Dict[str, Any]] = []
    for d in results:
        if not isinstance(d, dict):
            continue
        tags = d.get("tags") or []
        if "sentinel" not in tags or "high" not in tags:
            continue
        created_at = d.get("created_at")
        if since_iso and created_at and created_at <= since_iso:
            continue
        # Finding type is the tag that isn't "sentinel", "high", or a meta tag.
        finding_type = next(
            (t for t in tags if t not in ("sentinel", "high", "note")),
            "unknown",
        )
        out.append({
            "summary": d.get("summary", ""),
            "type": finding_type,
            "created_at": created_at,
            "id": d.get("id"),
        })
    return out


class VigilAgent(GovernanceAgent):
    def __init__(
        self,
        mcp_url: str = GOV_MCP_URL,
        label: str = "Vigil",
        heartbeat_interval: int = 1800,
        with_tests: bool = False,
        with_audit: bool = True,
        force_new: bool = False,
    ):
        super().__init__(
            name=label,
            mcp_url=mcp_url,
            session_file=SESSION_FILE,
            legacy_session_file=LEGACY_SESSION_FILE,
            state_dir=STATE_FILE.parent,
            timeout=30.0,
        )
        self.heartbeat_interval = heartbeat_interval
        self.with_tests = with_tests
        self.with_audit = with_audit
        self.force_new = force_new
        # Vigil-specific cycle data (populated during run_cycle, used in post-checkin)
        self._cycle_state: Dict[str, Any] = {}
        self._cycle_prev_state: Dict[str, Any] = {}
        # Register built-in checks + any VIGIL_CHECK_PLUGINS externals.
        # Idempotent: safe to call from multiple VigilAgent instances in tests.
        load_plugins()

    async def _read_sentinel_findings(
        self, client: GovernanceClient, since_iso: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Query KG for recent high-severity Sentinel notes newer than ``since_iso``.

        Returns empty list on any failure — coordination is best-effort, a
        broken search must not poison the cycle. Bounded to 15s so a hung MCP
        call can't eat the full cycle timeout.
        """
        try:
            result = await asyncio.wait_for(
                client.search_knowledge(
                    query="sentinel", tags=["sentinel"], limit=10, semantic=False,
                ),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            log("sentinel-read timed out after 15s; continuing cycle")
            return []
        except Exception as e:
            log(f"sentinel-read failed ({e}); continuing cycle")
            return []
        if not getattr(result, "success", False):
            return []
        return _filter_sentinel_findings(result.results or [], since_iso)

    async def _run_groundskeeper(self, client: GovernanceClient) -> Dict[str, Any]:
        """KG audit + lifecycle cleanup + orphan archival."""
        summary: Dict[str, Any] = {
            "audit_run": False,
            "stale_found": 0,
            "archived": 0,
            "orphans_archived": 0,
            "errors": [],
        }

        try:
            audit_result = await client.audit_knowledge(scope="open", top_n=10)
            if audit_result.success:
                summary["audit_run"] = True
                # Server returns audit payload under `audit`, not `results`.
                # Iterating `.results` stays empty and leaves stale_found=0 —
                # the silent failure that hid 127 archive candidates for months.
                audit_data = getattr(audit_result, "audit", None) or {}
                buckets = audit_data.get("buckets", {}) if isinstance(audit_data, dict) else {}
                summary["stale_found"] = (
                    buckets.get("stale", 0) + buckets.get("candidate_for_archive", 0)
                )

                if summary["stale_found"] > 0:
                    cleanup_result = await client.cleanup_knowledge(dry_run=False)
                    if cleanup_result.success:
                        # Use cleaned_total (sums discoveries/ephemeral/deleted
                        # from the server's cleanup_result dict) rather than
                        # the legacy `cleaned` field that the server never
                        # populates.
                        summary["archived"] = cleanup_result.cleaned_total
            else:
                err = getattr(audit_result, "error", None) or "Audit failed"
                summary["errors"].append(str(err))
                log(f"GROUNDSKEEPER: audit_knowledge failed — {err}")

            orphan_result = await client.archive_orphan_agents()
            if orphan_result.success:
                # Server returns `archived_count`; the legacy `archived` field
                # stays 0 in the response. Read whichever is populated.
                summary["orphans_archived"] = (
                    orphan_result.archived_count or orphan_result.archived
                )

        except Exception as e:
            summary["errors"].append(str(e))
            log(f"GROUNDSKEEPER: exception during audit — {type(e).__name__}: {e}")

        if summary["audit_run"]:
            note_text = (
                f"Groundskeeper: {summary['stale_found']} stale, "
                f"{summary['archived']} archived, "
                f"{summary['orphans_archived']} orphans cleaned"
            )
            try:
                await client.leave_note(
                    summary=note_text,
                    tags=["vigil", "groundskeeper", "audit"],
                )
            except Exception:
                pass
            log(f"GROUNDSKEEPER: {note_text}")

        return summary

    async def run_cycle(self, client: GovernanceClient) -> CycleResult | None:
        """Run one heartbeat cycle."""
        findings: List[str] = []
        issues = 0
        prev_state = self.load_state()
        self._cycle_prev_state = prev_state

        # --- 1. Run registered health checks (governance built-in + plugins) ---
        check_results = await run_health_checks(prev_state)
        health_state = _collect_health_state(check_results, prev_state)

        for _check, result in check_results:
            findings.append(result.summary)
            if not result.ok:
                issues += 1

        gov_healthy = health_state["governance_healthy"]
        gov_detail = health_state["governance_detail"]
        anima_healthy = health_state["lumen_healthy"]
        anima_detail = health_state["lumen_detail"]
        anima_ok_url = health_state.get("lumen_last_ok_url")
        lumen_down_streak = health_state["lumen_down_streak"]

        # --- Transition-emit: page once on healthy -> unhealthy per service ---
        for check, result in check_results:
            svc = check.service_key
            was_healthy = prev_state.get(f"{svc}_healthy", True)
            if not result.ok and was_healthy and result.fingerprint_key:
                notify("Vigil", result.summary)
                post_finding(
                    event_type="vigil_finding",
                    severity=result.severity,
                    message=result.summary,
                    agent_id="vigil",
                    agent_name="Vigil",
                    fingerprint=compute_fingerprint(["vigil", result.fingerprint_key]),
                    extra={"finding_type": result.fingerprint_key},
                )

        # --- 2.5. Read Sentinel findings since last cycle, route to action ---
        # First actual coordination arc: Sentinel observes fleet-level anomalies
        # and writes them to the KG as high-severity notes. Vigil reads them and
        # either runs an audit or references them in its check-in so the chain
        # shows up in the governance audit trail.
        sentinel_findings = await self._read_sentinel_findings(
            client, prev_state.get("cycle_time")
        )
        sentinel_force_audit = any(
            f["type"] in _SENTINEL_AUDIT_TRIGGERS for f in sentinel_findings
        )
        for f in sentinel_findings:
            findings.append(f"Sentinel/{f['type']}: {f['summary']}")
            log(f"SENTINEL-COORD: read '{f['type']}' finding")

        # --- 3. Run tests (optional, ~15 min) ---
        total_passed = 0
        total_failed = 0
        if self.with_tests:
            loop = asyncio.get_event_loop()
            gov_future = loop.run_in_executor(None, run_pytest, project_root, "governance")
            # anima-mcp is optional — skip cleanly if the sibling repo isn't present
            anima_future = (
                loop.run_in_executor(None, run_pytest, ANIMA_PROJECT, "anima")
                if ANIMA_PROJECT.exists()
                else None
            )

            gov_passed, gov_n_passed, gov_n_failed, gov_summary = await gov_future
            findings.append(gov_summary)
            total_passed += gov_n_passed
            total_failed += gov_n_failed
            if not gov_passed:
                issues += 1

            if anima_future is not None:
                anima_passed, anima_n_passed, anima_n_failed, anima_summary = await anima_future
                findings.append(anima_summary)
                total_passed += anima_n_passed
                total_failed += anima_n_failed
                if not anima_passed:
                    issues += 1

        # --- 4. Groundskeeper duties (optional) ---
        # Forced on when a Sentinel finding indicates KG-remediable symptoms
        # (verdict churn, correlated governance events). Per-cycle override
        # only — does not mutate self.with_audit.
        effective_audit = self.with_audit or sentinel_force_audit
        groundskeeper_summary: Dict[str, Any] = {}
        if effective_audit:
            groundskeeper_summary = await self._run_groundskeeper(client)
            if groundskeeper_summary.get("stale_found", 0) > 0:
                findings.append(
                    f"KG: {groundskeeper_summary['stale_found']} stale, "
                    f"{groundskeeper_summary['archived']} archived"
                )
            if sentinel_force_audit and not self.with_audit:
                findings.append("Groundskeeper forced by Sentinel coordination")

        # --- 5. Compute complexity/confidence from actual signals ---
        complexity = 0.15
        if self.with_tests:
            complexity += 0.3
        if effective_audit:
            complexity += 0.15
        if sentinel_findings:
            complexity += min(0.15, 0.05 * len(sentinel_findings))
        complexity += min(0.3, issues * 0.1)
        complexity = min(1.0, complexity)

        confidence = 0.90
        confidence -= issues * 0.12
        if lumen_down_streak == 1:
            confidence -= 0.05
        if total_failed > 0:
            confidence -= 0.10
        confidence = max(0.3, min(0.95, confidence))

        summary = " | ".join(findings)
        test_info = f" Tests: {total_passed} passed, {total_failed} failed." if self.with_tests else ""
        gk_info = ""
        if groundskeeper_summary.get("audit_run"):
            gk_info = (
                f" Groundskeeper: {groundskeeper_summary['stale_found']} stale, "
                f"{groundskeeper_summary['archived']} archived."
            )
        checkin_text = f"Heartbeat cycle: {summary}.{test_info}{gk_info} Issues: {issues}"

        # --- 6. Detect changes for notes ---
        # Build cycle state (pre-checkin; coherence/verdict filled in post-checkin)
        total_cycles = prev_state.get("total_cycles", 0) + 1

        self._cycle_state = {
            **health_state,
            "groundskeeper_stale": groundskeeper_summary.get("stale_found", 0),
            "groundskeeper_archived": groundskeeper_summary.get("archived", 0),
            "total_cycles": total_cycles,
            "cycle_time": datetime.now(timezone.utc).isoformat(),
        }

        # Change notes (health transitions, coherence drift, etc.)
        changes = detect_changes(prev_state, self._cycle_state)
        note_tuples = [(c["summary"], c["tags"]) for c in changes]

        return CycleResult(
            summary=checkin_text,
            complexity=complexity,
            confidence=confidence,
            response_mode="compact",
            notes=note_tuples,
        )

    async def _handle_cycle_result(
        self, client: GovernanceClient, result: CycleResult | None
    ) -> None:
        """Override base: add post-checkin EISV tracking and self-recovery."""
        if result is None:
            return

        # Check in
        try:
            checkin_result = await client.checkin(
                response_text=result.summary,
                complexity=result.complexity,
                confidence=result.confidence,
                response_mode=result.response_mode,
            )
            self._last_checkin_time = time.monotonic()
        except VerdictError as e:
            if e.verdict == "pause":
                log("Paused — attempting self-recovery")
                try:
                    await client.self_recovery(action="quick")
                    log("Self-recovery succeeded, retrying check-in")
                    checkin_result = await client.checkin(
                        response_text=result.summary,
                        complexity=result.complexity,
                        confidence=result.confidence,
                        response_mode=result.response_mode,
                    )
                    self._last_checkin_time = time.monotonic()
                except Exception as retry_err:
                    log(f"Self-recovery retry failed: {retry_err}")
                    self.save_state(self._cycle_state)
                    raise
            else:
                self.save_state(self._cycle_state)
                raise

        # Post notes
        if result.notes:
            for summary, tags in result.notes:
                try:
                    await client.leave_note(summary=summary, tags=tags)
                    log(f"NOTE: {summary}")
                except Exception:
                    log(f"NOTE FAILED: {summary}")

        # Extract EISV for state tracking
        coherence = checkin_result.coherence
        verdict = checkin_result.verdict
        metrics = checkin_result.metrics or {}

        self._cycle_state["coherence"] = coherence
        self._cycle_state["verdict"] = verdict

        # Detect coherence/verdict changes that depend on post-checkin data
        late_changes = detect_changes(self._cycle_prev_state, self._cycle_state)
        for change in late_changes:
            # Only post changes not already in notes
            if not any(n[0] == change["summary"] for n in (result.notes or [])):
                try:
                    await client.leave_note(
                        summary=change["summary"], tags=change["tags"]
                    )
                    log(f"NOTE: {change['summary']}")
                except Exception:
                    pass

        # Save state
        self.save_state(self._cycle_state)

        # Log one-line summary
        if checkin_result.success:
            try:
                eisv = (
                    f"E={float(metrics['E']):.3f} "
                    f"I={float(metrics['I']):.3f} "
                    f"S={float(metrics['S']):.3f} "
                    f"V={float(metrics['V']):.3f}"
                )
            except (KeyError, TypeError, ValueError):
                eisv = "EISV=?"
            total_cycles = self._cycle_state.get("total_cycles", 0)
            gov_up = self._cycle_state.get("gov_up_cycles", 0)
            lumen_up = self._cycle_state.get("lumen_up_cycles", 0)
            uptime = f" | uptime: gov={gov_up/total_cycles:.0%} lumen={lumen_up/total_cycles:.0%}" if total_cycles > 0 else ""
            log(f"{verdict or '?'} | {eisv} | {result.summary}{uptime}")

    # --- State persistence (use .vigil_state, not the SDK default) ---

    def load_state(self) -> dict:
        """Load Vigil's cross-cycle state."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def save_state(self, state: dict) -> None:
        """Save Vigil's cross-cycle state."""
        from unitares_sdk.utils import atomic_write
        try:
            atomic_write(STATE_FILE, json.dumps(state, default=str))
        except Exception:
            pass

    # --- Lifecycle overrides ---

    async def run_once(self, timeout: float = CYCLE_TIMEOUT):
        """Run a single heartbeat cycle with a wall-clock timeout.

        Uses asyncio.wait_for — the historical comment here claimed
        anyio.fail_after was required to avoid cancel-scope ownership
        violations, but under Python 3.14 anyio.fail_after itself raises
        RuntimeError on exit ("Attempted to exit a cancel scope that isn't
        the current task's current cancel scope"). wait_for is the
        project-standard pattern (CLAUDE.md "Known Issue" mitigation #3).
        """
        log("--- Heartbeat cycle start ---")
        start = time.time()
        try:
            await asyncio.wait_for(super().run_once(), timeout=timeout)
        except asyncio.TimeoutError:
            elapsed = time.time() - start
            log(f"CYCLE TIMEOUT after {elapsed:.1f}s (limit={timeout}s) — aborting")
            _trim_log(LOG_FILE, MAX_LOG_LINES)
            raise
        elapsed = time.time() - start
        log(f"Cycle complete ({elapsed:.1f}s)")
        _trim_log(LOG_FILE, MAX_LOG_LINES)

    async def run_daemon(self):
        """Run continuously with interval sleeps."""
        log(f"Heartbeat daemon starting (interval={self.heartbeat_interval}s)")
        await self.run_forever(
            interval=self.heartbeat_interval,
            heartbeat_interval=self.heartbeat_interval,
        )
        log("Heartbeat daemon stopped")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vigil — The First Resident")
    parser.add_argument("--once", action="store_true", default=True, help="Run one cycle (default)")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--with-tests", action="store_true", help="Also run pytest suites (~15 min)")
    parser.add_argument("--no-audit", action="store_true", help="Skip KG audit/groundskeeper duties")
    parser.add_argument("--force-new", action="store_true", help="Bootstrap fresh identity (use once, then remove flag)")
    parser.add_argument("--url", default=GOV_MCP_URL, help="MCP URL")
    parser.add_argument("--label", default="Vigil", help="Agent label")
    parser.add_argument("--interval", type=int, default=1800, help="Daemon interval (seconds)")
    args = parser.parse_args()

    agent = VigilAgent(
        mcp_url=args.url,
        label=args.label,
        heartbeat_interval=args.interval,
        with_tests=args.with_tests,
        with_audit=not args.no_audit,
        force_new=args.force_new,
    )

    if args.daemon:
        await agent.run_daemon()
    else:
        try:
            await agent.run_once()
        except asyncio.TimeoutError:
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Interrupted")
        sys.exit(0)
