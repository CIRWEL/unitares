#!/usr/bin/env python3
"""
Sentinel — The Independent Observer

A continuous agent that monitors UNITARES governance in real-time via WebSocket,
detects fleet-wide anomalies, correlates incidents, and generates situation reports.

Unlike Vigil (cron, every 30 min, janitorial), Sentinel is:
- Continuous (WebSocket-connected, event-driven)
- Analytical (cross-agent correlation, fleet statistics)
- Interventional (can pause agents, escalate to human)

Usage:
    python3 scripts/ops/sentinel_agent.py                # Run continuously
    python3 scripts/ops/sentinel_agent.py --sitrep       # Generate situation report and exit
    python3 scripts/ops/sentinel_agent.py --once         # Run one analysis cycle and exit

Architecture:
    1. Resumes persistent "Sentinel" identity via MCP
    2. Connects to /ws/eisv WebSocket for real-time event stream
    3. Maintains rolling EISV windows per agent (fleet state)
    4. Every 5 minutes: analyzes fleet, detects anomalies, checks in to governance
    5. On anomaly: leaves KG notes, sends macOS notifications
    6. On --sitrep: queries audit trail, generates timeline report
"""

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import httpx
from contextlib import asynccontextmanager
from mcp.client.session import ClientSession

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------

GOVERNANCE_PROJECT = Path("/Users/cirwel/projects/governance-mcp-v1")
SESSION_FILE = GOVERNANCE_PROJECT / ".sentinel_session"
STATE_FILE = GOVERNANCE_PROJECT / ".sentinel_state"
LOG_FILE = Path("/Users/cirwel/Library/Logs/unitares-sentinel.log")
MAX_LOG_LINES = 1000

GOVERNANCE_HEALTH_URL = "http://localhost:8767/health"
WEBSOCKET_URL = "ws://localhost:8767/ws/eisv"
MCP_URL = "http://127.0.0.1:8767/mcp/"

# Analysis cycle interval
ANALYSIS_INTERVAL = 300  # 5 minutes

# Hard upper bound on a single analysis cycle. Normal process_agent_update
# completes in <10s; 45s leaves comfortable slack while preventing a hung
# MCP call from blocking the main loop indefinitely (the anyio/asyncpg
# deadlock documented in governance-mcp-v1 CLAUDE.md can hang call_tool
# without raising, which previously wedged Sentinel for ~30h until
# manual restart).
CYCLE_TIMEOUT = 45  # seconds

# Fleet anomaly thresholds
FLEET_COHERENCE_DROP_THRESHOLD = 0.15   # single-agent coherence drop to flag
FLEET_COORDINATED_WINDOW = 600          # 10 min window for coordinated detection
FLEET_COORDINATED_MIN_AGENTS = 2        # min agents degrading simultaneously
FLEET_ENTROPY_SIGMA = 2.0               # z-score for fleet entropy anomaly

# Rolling window sizes
EISV_WINDOW_SIZE = 72     # ~6h at 5-min intervals
EVENT_WINDOW_SIZE = 500   # recent events for correlation


# ---------------------------------------------------------------------------
# Utilities (shared patterns with Vigil)
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: str):
    fd = None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.write(fd, data.encode())
        os.close(fd)
        fd = None
        os.replace(tmp, str(path))
        tmp = None
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
    import subprocess
    try:
        subprocess.Popen(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


_interactive = sys.stdout.isatty()


def log(message: str):
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


def trim_log():
    try:
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text().splitlines()
            if len(lines) > MAX_LOG_LINES:
                LOG_FILE.write_text("\n".join(lines[-MAX_LOG_LINES:]) + "\n")
    except Exception:
        pass


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: Dict[str, Any]):
    try:
        _atomic_write(STATE_FILE, json.dumps(state, default=str))
    except Exception:
        pass


def load_session() -> Dict[str, Optional[str]]:
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_session(client_session_id: str, continuity_token: Optional[str] = None):
    try:
        data = {"client_session_id": client_session_id}
        if continuity_token:
            data["continuity_token"] = continuity_token
        _atomic_write(SESSION_FILE, json.dumps(data))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MCP Connection (shared with Vigil)
# ---------------------------------------------------------------------------

def _mcp_connect(url: str):
    if "/mcp" in url:
        from mcp.client.streamable_http import streamable_http_client

        @asynccontextmanager
        async def _connect():
            async with httpx.AsyncClient(http2=False, timeout=30) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                    yield read, write
        return _connect()
    else:
        from mcp.client.sse import sse_client
        return sse_client(url)


# ---------------------------------------------------------------------------
# Fleet State — rolling EISV windows per agent
# ---------------------------------------------------------------------------

class AgentSnapshot:
    """Rolling window of EISV observations for one agent."""
    __slots__ = ("agent_id", "name", "eisv_history", "last_seen", "last_verdict",
                 "last_coherence", "coherence_history")

    def __init__(self, agent_id: str, name: str = ""):
        self.agent_id = agent_id
        self.name = name
        self.eisv_history: deque[Dict[str, Any]] = deque(maxlen=EISV_WINDOW_SIZE)
        self.coherence_history: deque[float] = deque(maxlen=EISV_WINDOW_SIZE)
        self.last_seen: float = 0.0
        self.last_verdict: str = ""
        self.last_coherence: float = 1.0

    def record(self, event: Dict[str, Any]):
        self.last_seen = time.time()
        self.name = event.get("agent_name", self.name)

        eisv = event.get("eisv", {})
        coherence = event.get("coherence", 0)
        decision = event.get("decision", {})
        verdict = decision.get("action", "") if isinstance(decision, dict) else ""

        self.eisv_history.append({
            "ts": self.last_seen,
            "E": eisv.get("E", 0),
            "I": eisv.get("I", 0),
            "S": eisv.get("S", 0),
            "V": eisv.get("V", 0),
            "coherence": coherence,
            "verdict": verdict,
        })
        self.coherence_history.append(coherence)
        self.last_verdict = verdict
        self.last_coherence = coherence

    def coherence_drop(self, window_seconds: float = 600) -> float:
        """Return coherence drop in the last window. Positive = degradation."""
        if len(self.coherence_history) < 2:
            return 0.0
        cutoff = time.time() - window_seconds
        recent = [h for h in self.eisv_history if h["ts"] >= cutoff]
        if len(recent) < 2:
            return 0.0
        return recent[0]["coherence"] - recent[-1]["coherence"]

    def mean_entropy(self, window_seconds: float = 3600) -> float:
        cutoff = time.time() - window_seconds
        recent = [h["S"] for h in self.eisv_history if h["ts"] >= cutoff]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)


class FleetState:
    """Tracks all agents' EISV state for cross-agent analysis."""

    def __init__(self):
        self.agents: Dict[str, AgentSnapshot] = {}
        self.events: deque[Dict[str, Any]] = deque(maxlen=EVENT_WINDOW_SIZE)
        self.incidents: List[Dict[str, Any]] = []

    def ingest(self, event: Dict[str, Any]):
        """Process a WebSocket event."""
        self.events.append(event)

        event_type = event.get("type", "")
        agent_id = event.get("agent_id", "")

        if event_type == "eisv_update" and agent_id:
            if agent_id not in self.agents:
                self.agents[agent_id] = AgentSnapshot(agent_id, event.get("agent_name", ""))
            self.agents[agent_id].record(event)

    def analyze(self) -> List[Dict[str, Any]]:
        """Run fleet-wide anomaly detection. Returns list of findings."""
        findings: List[Dict[str, Any]] = []
        now = time.time()

        # --- 1. Coordinated coherence drop ---
        degraded = []
        for aid, snap in self.agents.items():
            if now - snap.last_seen > FLEET_COORDINATED_WINDOW * 2:
                continue  # stale agent, skip
            drop = snap.coherence_drop(FLEET_COORDINATED_WINDOW)
            if drop >= FLEET_COHERENCE_DROP_THRESHOLD:
                degraded.append((aid, snap.name, drop))

        if len(degraded) >= FLEET_COORDINATED_MIN_AGENTS:
            agents_str = ", ".join(f"{name or aid[:8]}(-{drop:.2f})" for aid, name, drop in degraded)
            findings.append({
                "type": "coordinated_degradation",
                "severity": "high",
                "summary": f"Coordinated coherence drop: {agents_str}",
                "agents": [aid for aid, _, _ in degraded],
                "details": {aid: round(drop, 3) for aid, _, drop in degraded},
            })

        # --- 2. Fleet entropy anomaly ---
        entropies = []
        for aid, snap in self.agents.items():
            if now - snap.last_seen > 3600:
                continue
            s = snap.mean_entropy(3600)
            if s > 0:
                entropies.append((aid, snap.name, s))

        if len(entropies) >= 3:
            values = [s for _, _, s in entropies]
            mean_s = sum(values) / len(values)
            if len(values) > 1:
                var = sum((x - mean_s) ** 2 for x in values) / (len(values) - 1)
                std_s = var ** 0.5
                if std_s > 0:
                    for aid, name, s in entropies:
                        z = (s - mean_s) / std_s
                        if z >= FLEET_ENTROPY_SIGMA:
                            findings.append({
                                "type": "entropy_outlier",
                                "severity": "medium",
                                "summary": f"{name or aid[:8]} entropy outlier (z={z:.1f}, S={s:.3f})",
                                "agents": [aid],
                            })

        # --- 3. Verdict distribution shift ---
        recent_verdicts = []
        for aid, snap in self.agents.items():
            if now - snap.last_seen > FLEET_COORDINATED_WINDOW:
                continue
            for h in snap.eisv_history:
                if h["ts"] >= now - FLEET_COORDINATED_WINDOW:
                    recent_verdicts.append(h["verdict"])

        if len(recent_verdicts) >= 5:
            pause_count = sum(1 for v in recent_verdicts if v in ("pause", "reject"))
            pause_rate = pause_count / len(recent_verdicts)
            if pause_rate >= 0.20:
                findings.append({
                    "type": "verdict_shift",
                    "severity": "high",
                    "summary": f"Pause rate {pause_rate:.0%} in last {FLEET_COORDINATED_WINDOW // 60}min ({pause_count}/{len(recent_verdicts)})",
                    "details": {"pause_rate": round(pause_rate, 3), "pause_count": pause_count},
                })

        # --- 4. Incident correlation from typed events ---
        typed_events = [e for e in self.events
                        if e.get("type", "").startswith(("lifecycle_", "circuit_breaker_", "identity_", "knowledge_"))]
        recent_typed = [e for e in typed_events if self._event_age(e) < FLEET_COORDINATED_WINDOW]

        if len(recent_typed) >= 3:
            # Multiple event types in short window = potential incident
            event_types = set(e.get("type") for e in recent_typed)
            if len(event_types) >= 2:
                findings.append({
                    "type": "correlated_events",
                    "severity": "medium",
                    "summary": f"{len(recent_typed)} governance events in {FLEET_COORDINATED_WINDOW // 60}min: {', '.join(sorted(event_types))}",
                    "details": {"event_types": sorted(event_types), "count": len(recent_typed)},
                })

        return findings

    def _event_age(self, event: Dict[str, Any]) -> float:
        ts = event.get("timestamp", "")
        if ts:
            try:
                return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
            except (ValueError, TypeError):
                pass
        return float("inf")

    def fleet_summary(self) -> Dict[str, Any]:
        """Compact fleet state for check-in text."""
        now = time.time()
        active = [(aid, s) for aid, s in self.agents.items() if now - s.last_seen < 3600]
        return {
            "active_agents": len(active),
            "agents": {
                s.name or aid[:8]: {
                    "coherence": round(s.last_coherence, 3),
                    "verdict": s.last_verdict,
                    "age_min": round((now - s.last_seen) / 60, 1),
                }
                for aid, s in active
            },
        }


# ---------------------------------------------------------------------------
# Situation Report Generator
# ---------------------------------------------------------------------------

class SitrepGenerator:
    """Template-based situation report from audit trail and fleet state."""

    def __init__(self, fleet: FleetState):
        self.fleet = fleet

    async def generate(self, hours: float = 6.0) -> str:
        """Generate a situation report covering the last N hours."""
        lines: List[str] = []
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        lines.append(f"# Sentinel Situation Report")
        lines.append(f"Period: {since.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%H:%M')} UTC ({hours:.0f}h)")
        lines.append("")

        # Fleet status
        summary = self.fleet.fleet_summary()
        lines.append(f"## Fleet Status ({summary['active_agents']} active agents)")
        for name, info in summary.get("agents", {}).items():
            verdict_icon = {"proceed": "+", "guide": "~", "pause": "!", "reject": "X"}.get(info["verdict"], "?")
            lines.append(f"  [{verdict_icon}] {name}: coherence={info['coherence']}, last seen {info['age_min']}min ago")
        lines.append("")

        # Recent events from ring buffer
        typed_events = [e for e in self.fleet.events
                        if e.get("type", "").startswith(("lifecycle_", "circuit_breaker_", "identity_", "knowledge_"))]
        if typed_events:
            lines.append(f"## Events ({len(typed_events)} total)")
            # Group by type
            by_type: Dict[str, int] = {}
            for e in typed_events:
                t = e.get("type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1
            for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"  {t}: {count}")
            lines.append("")

            # Timeline of notable events
            notable = [e for e in typed_events if any(k in e.get("type", "")
                       for k in ("paused", "silent", "drift", "trip", "clamped"))]
            if notable:
                lines.append("## Timeline")
                for e in notable[-20:]:  # last 20
                    ts = e.get("timestamp", "?")
                    if isinstance(ts, str) and len(ts) > 16:
                        ts = ts[11:16]  # HH:MM
                    agent = e.get("agent_id", "?")[:8]
                    etype = e.get("type", "?")
                    reason = e.get("reason", e.get("payload", {}).get("reason", ""))
                    line = f"  {ts} [{agent}] {etype}"
                    if reason:
                        line += f" — {reason}"
                    lines.append(line)
                lines.append("")

        # Query audit DB for deeper history
        try:
            from src.audit_db import query_audit_events_async
            audit_events = await query_audit_events_async(
                start_time=since.isoformat(),
                limit=50,
                order="desc",
            )
            if audit_events:
                lifecycle_events = [e for e in audit_events if "lifecycle" in e.get("event_type", "")]
                if lifecycle_events:
                    lines.append(f"## Audit Trail ({len(lifecycle_events)} lifecycle events)")
                    for e in lifecycle_events[:15]:
                        ts = e.get("timestamp", "?")
                        if isinstance(ts, str) and len(ts) > 16:
                            ts = ts[11:16]
                        agent = (e.get("agent_id") or "?")[:8]
                        etype = e.get("event_type", "?")
                        details = e.get("details", {})
                        reason = details.get("reason", "")
                        line = f"  {ts} [{agent}] {etype}"
                        if reason:
                            line += f" — {reason}"
                        lines.append(line)
                    lines.append("")
        except Exception as e:
            lines.append(f"## Audit Trail (unavailable: {e})")
            lines.append("")

        # Findings
        findings = self.fleet.analyze()
        if findings:
            lines.append(f"## Findings ({len(findings)})")
            for f in findings:
                sev = f.get("severity", "?").upper()
                lines.append(f"  [{sev}] {f['summary']}")
            lines.append("")
        else:
            lines.append("## Findings: None")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sentinel Agent
# ---------------------------------------------------------------------------

class SentinelAgent:
    def __init__(
        self,
        mcp_url: str = MCP_URL,
        ws_url: str = WEBSOCKET_URL,
        label: str = "Sentinel",
        analysis_interval: int = ANALYSIS_INTERVAL,
    ):
        self.mcp_url = mcp_url
        self.ws_url = ws_url
        self.label = label
        self.analysis_interval = analysis_interval
        self.client_session_id: Optional[str] = None
        self.agent_uuid: Optional[str] = None
        self.fleet = FleetState()
        self.sitrep = SitrepGenerator(self.fleet)
        self.running = True
        self._ws_connected = False
        self._cycle_count = 0
        self._findings_total = 0

    # --- MCP helpers (same pattern as Vigil) ---

    def _inject_session(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in ("onboard", "identity"):
            return arguments
        arguments = dict(arguments)
        if self.client_session_id and "client_session_id" not in arguments:
            arguments["client_session_id"] = self.client_session_id
        saved = load_session()
        token = saved.get("continuity_token")
        if token and "continuity_token" not in arguments:
            arguments["continuity_token"] = token
        return arguments

    async def call_tool(self, session: ClientSession, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        last_error = None
        for attempt in range(2):
            try:
                result = await session.call_tool(tool_name, self._inject_session(tool_name, arguments))
                final_result: Dict[str, Any] = {}
                raw_texts: List[str] = []
                json_parsed = False

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
                    log(f"MCP transient error on {tool_name}, retrying: {e}")
                    await asyncio.sleep(3)
                    continue
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"retry exhausted: {last_error}"}

    def _extract_session_id(self, result: Dict[str, Any]) -> Optional[str]:
        return (
            result.get("client_session_id")
            or result.get("session_continuity", {}).get("client_session_id")
            or result.get("identity_summary", {}).get("client_session_id", {}).get("value")
        )

    def _extract_continuity_token(self, result: Dict[str, Any]) -> Optional[str]:
        return (
            result.get("continuity_token")
            or result.get("session_continuity", {}).get("continuity_token")
            or result.get("identity_summary", {}).get("continuity_token", {}).get("value")
            or result.get("quick_reference", {}).get("for_strong_resume")
        )

    def _capture_identity(self, result: Dict[str, Any], source: str = "") -> bool:
        sid = self._extract_session_id(result)
        token = self._extract_continuity_token(result)
        resolved_uuid = result.get("uuid") or result.get("agent_uuid") or result.get("bound_identity", {}).get("uuid")

        if self.agent_uuid and resolved_uuid and resolved_uuid != self.agent_uuid:
            log(f"IDENTITY DRIFT: expected {self.agent_uuid[:12]}... got {resolved_uuid[:12]}...")
            notify("Sentinel", f"Identity drift detected!")
            return False

        if resolved_uuid:
            self.agent_uuid = resolved_uuid
        if sid:
            self.client_session_id = sid
            save_session(sid, token)

        suffix = f" ({source})" if source else ""
        log(f"Identity: {self.label}{suffix}")
        return True

    async def ensure_identity(self, session: ClientSession) -> bool:
        try:
            saved = load_session()
            if saved.get("client_session_id"):
                self.client_session_id = saved["client_session_id"]

            token = saved.get("continuity_token")
            if token:
                result = await self.call_tool(session, "identity", {
                    "resume": True,
                    "continuity_token": token,
                })
                if result.get("success"):
                    return self._capture_identity(result, "token")
                log(f"Token resume failed: {result.get('error', result)}")

            result = await self.call_tool(session, "identity", {
                "name": self.label,
                "resume": True,
            })
            if result.get("success"):
                return self._capture_identity(result, "name")

            # Fresh onboard
            result = await self.call_tool(session, "onboard", {
                "name": self.label,
            })
            if result.get("success"):
                return self._capture_identity(result, "onboard")

            log(f"Identity failed: {result}")
            return False
        except Exception as e:
            log(f"Identity error: {e}")
            return False

    # --- WebSocket consumer ---

    async def ws_consumer(self):
        """Connect to WebSocket and feed events into fleet state."""
        import websockets

        while self.running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self._ws_connected = True
                    log(f"WebSocket connected to {self.ws_url}")
                    async for message in ws:
                        if not self.running:
                            break
                        try:
                            event = json.loads(message)
                            self.fleet.ingest(event)
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                self._ws_connected = False
                if self.running:
                    log(f"WebSocket disconnected: {e}")
                    await asyncio.sleep(10)  # reconnect delay

    # --- Analysis cycle ---

    async def run_analysis_cycle(self) -> str:
        """Run one analysis cycle: detect anomalies, check in to governance."""
        self._cycle_count += 1
        findings = self.fleet.analyze()
        fleet = self.fleet.fleet_summary()

        # Build check-in text
        parts = [f"Cycle {self._cycle_count}"]
        parts.append(f"Fleet: {fleet['active_agents']} agents")
        parts.append(f"WS: {'connected' if self._ws_connected else 'DISCONNECTED'}")

        if findings:
            self._findings_total += len(findings)
            for f in findings:
                parts.append(f"[{f['severity'].upper()}] {f['summary']}")
                log(f"FINDING: [{f['severity']}] {f['summary']}")
                # macOS notification for high severity
                if f["severity"] == "high":
                    notify("Sentinel", f["summary"])

        issues = len([f for f in findings if f["severity"] == "high"])
        complexity = min(1.0, 0.2 + len(findings) * 0.15 + (0.1 if not self._ws_connected else 0))
        confidence = max(0.4, 0.85 - issues * 0.1 - (0.15 if not self._ws_connected else 0))

        summary = " | ".join(parts)

        # Check in to governance
        try:
            async with _mcp_connect(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    if not await self.ensure_identity(session):
                        log("SKIP: identity failed")
                        return f"SKIP (identity) | {summary}"

                    result = await self.call_tool(session, "process_agent_update", {
                        "response_text": f"Sentinel analysis: {summary}",
                        "complexity": complexity,
                        "confidence": confidence,
                        "response_mode": "compact",
                    })

                    # Leave KG notes for significant findings
                    for f in findings:
                        if f["severity"] == "high":
                            await self.call_tool(session, "leave_note", {
                                "summary": f"[Sentinel] {f['summary']}",
                                "tags": ["sentinel", f["type"], f["severity"]],
                            })

                    if result.get("success"):
                        metrics = result.get("metrics", {})
                        try:
                            eisv = (
                                f"E={float(metrics['E']):.3f} "
                                f"I={float(metrics['I']):.3f} "
                                f"S={float(metrics['S']):.3f} "
                                f"V={float(metrics['V']):.3f}"
                            )
                        except (KeyError, TypeError, ValueError):
                            eisv = "EISV=?"
                        verdict = result.get("decision", {}).get("action", "?")
                        one_line = f"{verdict} | {eisv} | {summary}"
                        log(one_line)
                        return one_line
                    else:
                        error = result.get("error", "unknown")
                        log(f"Check-in failed: {error}")
                        return f"CHECK-IN FAILED | {summary}"
        except Exception as e:
            log(f"MCP error: {e}")
            return f"MCP ERROR | {summary}"

    # --- Main loops ---

    async def _bounded_analysis_cycle(self) -> str:
        """Run one analysis cycle with a hard timeout.

        Wraps ``run_analysis_cycle`` in ``asyncio.wait_for`` so a hung
        MCP call (e.g. from the governance-side anyio/asyncpg deadlock)
        can never block the main loop forever. A timeout is logged and
        the next cycle will run at its normal cadence.
        """
        try:
            return await asyncio.wait_for(
                self.run_analysis_cycle(), timeout=CYCLE_TIMEOUT
            )
        except asyncio.TimeoutError:
            log(f"Analysis cycle exceeded {CYCLE_TIMEOUT}s — skipping")
            return f"TIMEOUT after {CYCLE_TIMEOUT}s"

    async def run_continuous(self):
        """Run Sentinel continuously: WebSocket consumer + periodic analysis."""
        log("=== Sentinel starting ===")

        def signal_handler(signum, frame):
            log(f"Signal {signum}, shutting down")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start WebSocket consumer in background
        ws_task = asyncio.create_task(self.ws_consumer())

        # Initial check-in
        await asyncio.sleep(5)  # let WS connect
        await self._bounded_analysis_cycle()

        # Periodic analysis
        while self.running:
            await asyncio.sleep(self.analysis_interval)
            if self.running:
                try:
                    await self._bounded_analysis_cycle()
                except Exception as e:
                    log(f"Analysis cycle error: {e}")
                trim_log()

        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

        log("=== Sentinel stopped ===")

    async def run_once(self):
        """Run one analysis cycle and exit."""
        log("--- Sentinel single cycle ---")
        # Brief WS connection to gather some state
        ws_task = asyncio.create_task(self.ws_consumer())
        await asyncio.sleep(10)  # collect events for 10s
        result = await self.run_analysis_cycle()
        self.running = False
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        log(f"Result: {result}")

    async def run_sitrep(self, hours: float = 6.0):
        """Generate and print a situation report."""
        # Brief WS connection
        ws_task = asyncio.create_task(self.ws_consumer())
        await asyncio.sleep(5)
        report = await self.sitrep.generate(hours)
        self.running = False
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        print(report)
        log(f"Sitrep generated ({hours}h window)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sentinel — The Independent Observer")
    parser.add_argument("--once", action="store_true", help="Run one analysis cycle and exit")
    parser.add_argument("--sitrep", action="store_true", help="Generate situation report and exit")
    parser.add_argument("--hours", type=float, default=6.0, help="Sitrep window (hours)")
    parser.add_argument("--url", default=os.getenv("MCP_SERVER_URL", MCP_URL), help="MCP URL")
    parser.add_argument("--ws-url", default=os.getenv("SENTINEL_WS_URL", WEBSOCKET_URL), help="WebSocket URL")
    parser.add_argument("--interval", type=int, default=ANALYSIS_INTERVAL, help="Analysis interval (seconds)")
    args = parser.parse_args()

    agent = SentinelAgent(
        mcp_url=args.url,
        ws_url=args.ws_url,
        analysis_interval=args.interval,
    )

    if args.sitrep:
        await agent.run_sitrep(args.hours)
    elif args.once:
        await agent.run_once()
    else:
        await agent.run_continuous()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Interrupted")
        sys.exit(0)
