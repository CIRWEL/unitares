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
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from mcp.client.session import ClientSession

from agents.common.config import GOV_MCP_URL
from agents.common.log import trim_log as _trim_log
from agents.common.mcp_client import mcp_connect

# Paths
ANIMA_PROJECT = Path(os.getenv("ANIMA_PROJECT", str(project_root.parent / "anima-mcp")))
SESSION_FILE = project_root / ".vigil_session"
STATE_FILE = project_root / ".vigil_state"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-heartbeat.log"
MAX_LOG_LINES = 500

# Health endpoints
GOVERNANCE_HEALTH_URL = "http://localhost:8767/health"
ANIMA_HEALTH_URLS = [
    "http://192.168.1.165:8766/health",   # LAN
    "http://lumen:8766/health",            # Tailscale hostname
]

# Test timeout
TEST_TIMEOUT = 180  # 3 minutes per suite

# MCP retry on transient failures
MCP_RETRY_DELAY = 3  # seconds

# Wall-clock cap for a single heartbeat cycle.
#
# If run_cycle() stalls past this (e.g. MCP client parked on a dead
# streamable-http session, or the anyio/asyncpg deadlock), the cycle is
# aborted and the process exits so launchd's StartInterval can rotate.
#
# Prior to this, a hung --once invocation could stay alive for days
# (2026-04-08 incident: PID 3985 hung ~46h, silently blocking all
# subsequent launchd runs because StartInterval does not fire while the
# previous instance is still running).
CYCLE_TIMEOUT = int(os.getenv("HEARTBEAT_CYCLE_TIMEOUT", "120"))


def _atomic_write(path: Path, data: str):
    """Write data to file atomically via temp file + rename."""
    fd = None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.write(fd, data.encode())
        os.close(fd)
        fd = None
        os.replace(tmp, str(path))
        tmp = None  # successfully replaced, no cleanup needed
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def notify(title: str, message: str):
    """Send a macOS notification. Best-effort, never raises."""
    try:
        subprocess.Popen(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass



def load_session() -> Dict[str, Optional[str]]:
    """Load saved session data (client_session_id + continuity_token).

    Accepts two on-disk shapes:
      * a JSON object (current format)
      * a bare JSON string (legacy format, migrated in place)

    Anything else — a list, a number, null, or a non-JSON file — is
    discarded. The previous implementation fell through to
    ``str(data)``, which happily converted e.g. ``[1, 2, 3]`` into the
    literal string ``"[1, 2, 3]"`` and persisted it as a bogus
    ``client_session_id``. We'd rather start fresh than corrupt state.
    """
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            if isinstance(data, dict):
                return data
            if isinstance(data, str) and data:
                # Migrate legacy bare-string format.
                return {"client_session_id": data}
            # list / number / null / bool → reject, fall through to {}
        except (json.JSONDecodeError, Exception):
            # Try as plain text (pre-JSON legacy format)
            try:
                text = SESSION_FILE.read_text().strip()
                if text and not text.startswith(("{", "[")):
                    return {"client_session_id": text}
            except Exception:
                pass
    return {}


def save_session(client_session_id: str, continuity_token: Optional[str] = None):
    """Save session data for cross-invocation resume (atomic write)."""
    try:
        data = {"client_session_id": client_session_id}
        if continuity_token:
            data["continuity_token"] = continuity_token
        _atomic_write(SESSION_FILE, json.dumps(data))
    except Exception:
        pass


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



def load_state() -> Dict[str, Any]:
    """Load Vigil's cross-cycle state.

    Callers access keys via ``.get(k, default)`` and assume a mapping, so we
    type-check the parsed payload and fall back to an empty dict on anything
    unexpected (corrupt file, hand-edited list/null, partial write survived).
    """
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_state(state: Dict[str, Any]):
    """Save Vigil's cross-cycle state (atomic write)."""
    try:
        _atomic_write(STATE_FILE, json.dumps(state, default=str))
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


def check_http_health(url: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Check an HTTP health endpoint. Returns (healthy, detail_with_latency)."""
    import time
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


def _get_anima_urls(prev_state: Dict[str, Any]) -> List[str]:
    """Return anima health URLs, trying last-successful URL first."""
    last_ok = prev_state.get("lumen_last_ok_url")
    if last_ok and last_ok in ANIMA_HEALTH_URLS:
        # Put the last-successful URL first, then the rest
        return [last_ok] + [u for u in ANIMA_HEALTH_URLS if u != last_ok]
    return list(ANIMA_HEALTH_URLS)


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
        # Parse pytest output for counts
        # Look for line like "5625 passed" or "3 failed, 5622 passed"
        n_passed = 0
        n_failed = 0
        for line in output.splitlines():
            line_lower = line.lower()
            if "passed" in line_lower or "failed" in line_lower:
                import re
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


class HeartbeatAgent:
    def __init__(
        self,
        mcp_url: str = GOV_MCP_URL,
        label: str = "Vigil",
        heartbeat_interval: int = 1800,
        with_tests: bool = False,
        with_audit: bool = True,
        force_new: bool = False,
    ):
        self.mcp_url = mcp_url
        self.label = label
        self.heartbeat_interval = heartbeat_interval
        self.with_tests = with_tests
        self.with_audit = with_audit
        self.force_new = force_new
        self.client_session_id: Optional[str] = None
        self.agent_uuid: Optional[str] = None  # Expected UUID, set by _capture_identity
        self.running = True

    def _inject_session(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Inject client_session_id and continuity_token for identity continuity.

        Skip injection for onboard and identity calls — identity uses name-claim
        path for resumption, and injecting client_session_id sets
        explicit_resume_binding=True which bypasses the name-claim fallback.
        """
        if tool_name in ("onboard", "identity"):
            return arguments
        arguments = dict(arguments)
        if self.client_session_id and "client_session_id" not in arguments:
            arguments["client_session_id"] = self.client_session_id
        # Also inject continuity_token so PATH 2.8 can rebind after server restart
        saved = load_session()
        token = saved.get("continuity_token")
        if token and "continuity_token" not in arguments:
            arguments["continuity_token"] = token
        return arguments

    async def call_tool(self, session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool and parse JSON response. Retries once on transient failure."""
        last_error = None
        for attempt in range(2):
            try:
                result = await session.call_tool(tool_name, self._inject_session(tool_name, arguments))
                final_result: Dict[str, Any] = {}
                json_parsed = False
                raw_texts: List[str] = []

                for content in result.content:
                    if hasattr(content, "text"):
                        text = content.text
                        raw_texts.append(text)
                        try:
                            data = json.loads(text)
                            if isinstance(data, dict):
                                final_result.update(data)
                                json_parsed = True
                        except json.JSONDecodeError:
                            continue

                if json_parsed:
                    return final_result
                if raw_texts:
                    return {"text": "\n".join(raw_texts), "raw": True}
                return {"success": False, "error": "No content in response"}
            except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as e:
                last_error = e
                if attempt == 0:
                    log(f"MCP transient error on {tool_name}, retrying in {MCP_RETRY_DELAY}s: {e}")
                    await asyncio.sleep(MCP_RETRY_DELAY)
                    continue
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"retry exhausted: {last_error}"}

    def _extract_session_id(self, result: Dict[str, Any]) -> Optional[str]:
        """Extract client_session_id from various response shapes."""
        return (
            result.get("client_session_id")
            or result.get("session_continuity", {}).get("client_session_id")
            or result.get("identity_summary", {}).get("client_session_id", {}).get("value")
        )

    def _extract_continuity_token(self, result: Dict[str, Any]) -> Optional[str]:
        """Extract continuity_token for trajectory-verified resume."""
        return (
            result.get("continuity_token")
            or result.get("session_continuity", {}).get("continuity_token")
            or result.get("identity_summary", {}).get("continuity_token", {}).get("value")
            or result.get("quick_reference", {}).get("for_strong_resume")
        )

    def _capture_identity(self, result: Dict[str, Any], source: str = "") -> bool:
        """Extract and save session ID + continuity token from a successful identity response."""
        sid = self._extract_session_id(result)
        token = self._extract_continuity_token(result)
        resolved_uuid = result.get("uuid") or result.get("agent_uuid") or result.get("bound_identity", {}).get("uuid")

        # Identity drift detection: if we already have an expected UUID and this
        # one doesn't match, something went wrong — alert instead of silently switching.
        if self.agent_uuid and resolved_uuid and resolved_uuid != self.agent_uuid:
            log(f"IDENTITY DRIFT: expected {self.agent_uuid[:12]}... but got {resolved_uuid[:12]}...")
            notify("Vigil", f"Identity drift detected! Expected {self.agent_uuid[:8]}...")
            return False

        if resolved_uuid:
            self.agent_uuid = resolved_uuid
        if sid:
            self.client_session_id = sid
            save_session(sid, token)

        # Prefer self.label over auto-generated agent_id (e.g. "Vigil_7d9966bb")
        raw_name = result.get("display_name") or result.get("label")
        agent_name = raw_name if (raw_name and "_" not in raw_name) else self.label
        suffix = f" ({source})" if source else ""
        log(f"Identity: {agent_name}{suffix}")
        return True

    async def ensure_identity(self, session: ClientSession) -> bool:
        """Resume persistent Vigil identity using saved continuity token."""
        try:
            # Explicit bootstrap: create fresh identity and save token
            if self.force_new:
                log("Bootstrapping fresh identity (--force-new)")
                result = await self.call_tool(session, "onboard", {
                    "name": self.label,
                    "force_new": True,
                })
                if result.get("success"):
                    return self._capture_identity(result, "bootstrap")
                log(f"Bootstrap failed: {result}")
                return False

            saved = load_session()
            if saved.get("client_session_id"):
                self.client_session_id = saved["client_session_id"]

            # Validate saved token before trusting it — decode and check the
            # embedded agent UUID matches what we expect. Catches token corruption
            # and the session-overwrite bug where another agent's token replaced ours.
            token = saved.get("continuity_token")
            if token:
                try:
                    import base64 as _b64
                    parts = token.split(".")
                    if len(parts) == 3 and parts[0] == "v1":
                        payload = json.loads(_b64.urlsafe_b64decode(parts[1] + "==").decode())
                        token_aid = payload.get("aid")
                        if self.agent_uuid and token_aid and token_aid != self.agent_uuid:
                            log(f"TOKEN MISMATCH: token has {token_aid[:12]}... but expected {self.agent_uuid[:12]}... — discarding stale token")
                            notify("Vigil", f"Stale token detected (wrong agent UUID)")
                            token = None
                        elif token_aid:
                            # First run or no prior UUID — trust the token and set expectation
                            self.agent_uuid = token_aid
                except Exception:
                    pass  # Token decode failed — let the server validate it

            # If we have a continuity token, use it for strong resume.
            # Don't pass name — it triggers name-claim path which requires trajectory_signature.
            # Session-key resolution via token is sufficient to find the identity.
            if token:
                result = await self.call_tool(session, "identity", {
                    "resume": True,
                    "continuity_token": token,
                })
                if result.get("success"):
                    return self._capture_identity(result, "token")
                log(f"Token resume failed: {result.get('error', result)}")

            # Resume by name (works if no trajectory verification needed)
            result = await self.call_tool(session, "identity", {
                "name": self.label,
                "resume": True,
            })

            # Handle options prompt
            if result.get("options"):
                result = await self.call_tool(session, "identity", {
                    "name": self.label,
                    "resume": True,
                })

            # Trajectory verification required — need a human to bootstrap
            if result.get("recovery", {}).get("reason") == "trajectory_required":
                log("IDENTITY BLOCKED: trajectory verification required. "
                    "Run manually once: python3 agents/vigil/agent.py --once --force-new")
                return False

            if result.get("success"):
                return self._capture_identity(result)

            log(f"Identity failed: {result}")
            return False
        except Exception as e:
            log(f"Identity error: {e}")
            return False

    async def _run_groundskeeper(self, session: ClientSession) -> Dict[str, Any]:
        """Run groundskeeper duties: KG audit, stale cleanup, orphan archival.

        Returns a summary dict with audit results and actions taken.
        """
        summary: Dict[str, Any] = {
            "audit_run": False,
            "stale_found": 0,
            "archived": 0,
            "orphans_archived": 0,
            "errors": [],
        }

        try:
            # 1. Run KG audit
            audit_result = await self.call_tool(session, "knowledge", {
                "action": "audit",
                "scope": "open",
                "top_n": "10",
                "use_model": "true",
            })

            if audit_result.get("success") or "audit" in audit_result:
                summary["audit_run"] = True
                audit_data = audit_result.get("audit", {})
                buckets = audit_data.get("buckets", {})
                summary["stale_found"] = buckets.get("stale", 0) + buckets.get("candidate_for_archive", 0)

                # 2. If archive candidates exist, trigger lifecycle cleanup
                if buckets.get("candidate_for_archive", 0) > 0:
                    cleanup_result = await self.call_tool(session, "knowledge", {
                        "action": "cleanup",
                        "dry_run": "false",
                    })
                    if cleanup_result.get("success") or "cleanup_result" in cleanup_result:
                        cleanup_data = cleanup_result.get("cleanup_result", {})
                        summary["archived"] = (
                            cleanup_data.get("ephemeral_archived", 0)
                            + cleanup_data.get("discoveries_archived", 0)
                        )
            else:
                summary["errors"].append(f"Audit: {audit_result.get('error', 'unknown')}")

            # 3. Trigger orphan agent cleanup
            orphan_result = await self.call_tool(session, "archive_orphan_agents", {})
            if orphan_result.get("success"):
                summary["orphans_archived"] = orphan_result.get("archived_count", 0)

        except Exception as e:
            summary["errors"].append(str(e))

        # 4. Leave summary note in KG
        if summary["audit_run"]:
            note_text = (
                f"Groundskeeper: {summary['stale_found']} stale, "
                f"{summary['archived']} archived, "
                f"{summary['orphans_archived']} orphans cleaned"
            )
            await self.call_tool(session, "leave_note", {
                "summary": note_text,
                "tags": ["vigil", "groundskeeper", "audit"],
            })
            log(f"GROUNDSKEEPER: {note_text}")

        return summary

    async def run_cycle(self) -> str:
        """Run one heartbeat cycle. Returns summary string."""
        findings: List[str] = []
        issues = 0
        prev_state = load_state()

        # --- 1. Governance health ---
        gov_healthy, gov_detail = check_http_health(GOVERNANCE_HEALTH_URL)
        if gov_healthy:
            findings.append(f"Governance: {gov_detail}")
        else:
            findings.append(f"Governance: UNHEALTHY ({gov_detail})")
            issues += 1

        # --- 2. Lumen/Anima health (smart URL ordering) ---
        anima_healthy = False
        anima_detail = "unreachable"
        anima_ok_url = None
        for url in _get_anima_urls(prev_state):
            anima_healthy, anima_detail = check_http_health(url, timeout=10.0)
            if anima_healthy:
                anima_ok_url = url
                break
        if anima_healthy:
            findings.append(f"Lumen: {anima_detail}")
        else:
            findings.append(f"Lumen: UNREACHABLE ({anima_detail})")
            issues += 1

        # Track Lumen outage streak
        lumen_down_streak = 0
        if not anima_healthy:
            lumen_down_streak = prev_state.get("lumen_down_streak", 0) + 1

        # --- macOS notifications for critical events ---
        if not gov_healthy and prev_state.get("governance_healthy", True):
            notify("Vigil", f"Governance is down: {gov_detail}")
        if lumen_down_streak == 3:
            notify("Vigil", "Lumen unreachable for 3 consecutive cycles (1.5h)")

        # --- 3. Run tests (optional, ~15 min) ---
        total_passed = 0
        total_failed = 0
        if self.with_tests:
            loop = asyncio.get_event_loop()
            gov_future = loop.run_in_executor(None, run_pytest, project_root, "governance")
            anima_future = loop.run_in_executor(None, run_pytest, ANIMA_PROJECT, "anima")

            gov_passed, gov_n_passed, gov_n_failed, gov_summary = await gov_future
            anima_passed, anima_n_passed, anima_n_failed, anima_summary = await anima_future

            findings.append(gov_summary)
            findings.append(anima_summary)
            total_passed = gov_n_passed + anima_n_passed
            total_failed = gov_n_failed + anima_n_failed
            if not gov_passed:
                issues += 1
            if not anima_passed:
                issues += 1

        # --- 4. Compute complexity/confidence from actual signals ---
        # Complexity: how much work this cycle involved
        # - Base: health checks only = 0.15
        # - Tests add 0.3 (significant computation)
        # - Groundskeeper adds 0.15
        # - Issues add 0.1 each (diagnosing problems is harder)
        complexity = 0.15
        if self.with_tests:
            complexity += 0.3
        if self.with_audit:
            complexity += 0.15
        complexity += min(0.3, issues * 0.1)
        complexity = min(1.0, complexity)

        # Confidence: how certain are we about what we found
        # - Start high (health checks are deterministic)
        # - Reduce for each issue (something unexpected)
        # - Reduce for flaky signals (Lumen down streak = intermittent)
        confidence = 0.90
        confidence -= issues * 0.12
        if lumen_down_streak == 1:
            confidence -= 0.05  # First miss could be transient
        if total_failed > 0:
            confidence -= 0.10  # Test failures are concerning
        confidence = max(0.3, min(0.95, confidence))

        summary = " | ".join(findings)

        # --- 5. Check in to governance + leave notes on changes ---
        try:
            async with mcp_connect(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    if not await self.ensure_identity(session):
                        log("SKIP: identity failed")
                        return f"SKIP (identity failed) | {summary}"

                    # --- Groundskeeper duties (optional) ---
                    groundskeeper_summary: Dict[str, Any] = {}
                    if self.with_audit:
                        groundskeeper_summary = await self._run_groundskeeper(session)
                        if groundskeeper_summary.get("stale_found", 0) > 0:
                            findings.append(
                                f"KG: {groundskeeper_summary['stale_found']} stale, "
                                f"{groundskeeper_summary['archived']} archived"
                            )
                            summary = " | ".join(findings)

                    test_info = f" Tests: {total_passed} passed, {total_failed} failed." if self.with_tests else ""
                    gk_info = ""
                    if groundskeeper_summary.get("audit_run"):
                        gk_info = (
                            f" Groundskeeper: {groundskeeper_summary['stale_found']} stale, "
                            f"{groundskeeper_summary['archived']} archived."
                        )
                    checkin_text = (
                        f"Heartbeat cycle: {summary}.{test_info}{gk_info} "
                        f"Issues: {issues}"
                    )

                    result = await self.call_tool(session, "process_agent_update", {
                        "response_text": checkin_text,
                        "complexity": complexity,
                        "confidence": confidence,
                        "response_mode": "compact",
                    })

                    # Self-recovery: if paused, attempt quick resume
                    if not result.get("success") and "paused" in str(result.get("error", "")):
                        log("Paused — attempting self-recovery")
                        recovery = await self.call_tool(session, "self_recovery", {
                            "action": "quick",
                        })
                        if recovery.get("success"):
                            log("Self-recovery succeeded, retrying check-in")
                            result = await self.call_tool(session, "process_agent_update", {
                                "response_text": checkin_text,
                                "complexity": complexity,
                                "confidence": confidence,
                                "response_mode": "compact",
                            })

                    # Extract EISV for state tracking
                    metrics = result.get("metrics", {}) if result.get("success") else {}
                    coherence = metrics.get("coherence")
                    verdict = result.get("decision", {}).get("action")

                    # --- Self-verification: did the check-in land on the right agent? ---
                    response_agent = (
                        result.get("agent_signature", {}).get("uuid")
                        or result.get("resolved_agent_id")
                    )
                    if self.agent_uuid and response_agent and response_agent != self.agent_uuid:
                        log(
                            f"CHECK-IN MISDIRECTED: sent to {response_agent[:12]}... "
                            f"but expected {self.agent_uuid[:12]}... — identity may need refresh"
                        )
                        notify("Vigil", f"Check-in went to wrong agent! Run --force-new")

                    # --- Uptime tracking ---
                    total_cycles = prev_state.get("total_cycles", 0) + 1
                    gov_up_cycles = prev_state.get("gov_up_cycles", 0) + (1 if gov_healthy else 0)
                    lumen_up_cycles = prev_state.get("lumen_up_cycles", 0) + (1 if anima_healthy else 0)

                    # Build current state for change detection
                    current_state: Dict[str, Any] = {
                        "governance_healthy": gov_healthy,
                        "governance_detail": gov_detail,
                        "lumen_healthy": anima_healthy,
                        "lumen_detail": anima_detail,
                        "lumen_down_streak": lumen_down_streak,
                        "lumen_last_ok_url": anima_ok_url,
                        "coherence": coherence,
                        "verdict": verdict,
                        "cycle_time": datetime.now(timezone.utc).isoformat(),
                        "groundskeeper_stale": groundskeeper_summary.get("stale_found", 0),
                        "groundskeeper_archived": groundskeeper_summary.get("archived", 0),
                        "total_cycles": total_cycles,
                        "gov_up_cycles": gov_up_cycles,
                        "lumen_up_cycles": lumen_up_cycles,
                    }

                    # Detect changes and leave notes
                    changes = detect_changes(prev_state, current_state)
                    for change in changes:
                        note_result = await self.call_tool(session, "leave_note", {
                            "summary": change["summary"],
                            "tags": change["tags"],
                        })
                        if note_result.get("success"):
                            log(f"NOTE: {change['summary']}")
                        else:
                            log(f"NOTE FAILED: {change['summary']}")

                    # Save state for next cycle
                    save_state(current_state)

                    if result.get("success"):
                        try:
                            eisv = (
                                f"E={float(metrics['E']):.3f} "
                                f"I={float(metrics['I']):.3f} "
                                f"S={float(metrics['S']):.3f} "
                                f"V={float(metrics['V']):.3f}"
                            )
                        except (KeyError, TypeError, ValueError):
                            eisv = "EISV=?"
                        decision = verdict or "?"
                        uptime_pct = f" | uptime: gov={gov_up_cycles/total_cycles:.0%} lumen={lumen_up_cycles/total_cycles:.0%}" if total_cycles > 0 else ""
                        one_line = f"{decision} | {eisv} | {summary}{uptime_pct}"
                        log(one_line)
                        return one_line
                    else:
                        error = result.get("error", "unknown")
                        log(f"Check-in failed: {error} | {summary}")
                        return f"CHECK-IN FAILED ({error}) | {summary}"
        except Exception as e:
            log(f"MCP error: {e} | {summary}")
            return f"MCP ERROR ({e}) | {summary}"

    async def run_once(self, timeout: float = CYCLE_TIMEOUT):
        """Run a single heartbeat cycle with a wall-clock timeout.

        If run_cycle() stalls past ``timeout`` seconds, the cycle is aborted
        via ``asyncio.wait_for``. This is the safety net against a hung MCP
        client (dead streamable-http session, anyio/asyncpg deadlock) —
        without it a ``--once`` invocation can stay alive indefinitely and
        block every subsequent launchd ``StartInterval`` rotation.

        Raises ``asyncio.TimeoutError`` on timeout so callers can choose
        whether to rotate (``--once``) or continue (``--daemon``).
        """
        log("--- Heartbeat cycle start ---")
        start = time.time()
        try:
            await asyncio.wait_for(self.run_cycle(), timeout=timeout)
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

        def signal_handler(signum, frame):
            log(f"Signal {signum}, shutting down")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while self.running:
            try:
                await self.run_once()
            except Exception as e:
                log(f"Cycle error: {e}")
            if self.running:
                await asyncio.sleep(self.heartbeat_interval)

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

    agent = HeartbeatAgent(
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
            # Already logged in run_once; exit non-zero so launchd rotates
            # to a fresh invocation rather than blocking on a hung socket.
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Interrupted")
        sys.exit(0)
