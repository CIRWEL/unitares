#!/usr/bin/env python3
"""
Watcher — Independent Bug-Pattern Observer

A non-blocking agent that scans recently edited code for known-bad patterns
using a local LLM (qwen3-coder-next via Ollama, routed through governance call_model).
Unlike Vigil (cron, janitorial) and Sentinel (continuous, analytical), Watcher
is event-driven — fired by PostToolUse hooks on Edit/Write.

Successor to Anthropic's deprecated Ogler (Claude Code 2.1.96 companion), built
local and governance-native so it survives any upstream feature churn.

Usage:
    watcher_agent.py --file <path>                  # scan a file
    watcher_agent.py --file <path> --region L1-L40  # scan a region
    watcher_agent.py --self-test                    # run on a synthetic bug
    watcher_agent.py --list-findings                # dump current findings

Architecture:
    1. Load pattern library (agents/watcher/patterns.md)
    2. Read target file + optional region
    3. Build prompt (pattern list + code)
    4. POST to governance REST /v1/tools/call → call_model (Ollama local)
    5. Parse JSON findings, dedup against data/watcher/dedup.json
    6. Append new findings to data/watcher/findings.jsonl
    7. Route by severity:
       - low/medium → file only
       - high       → file + mark for SessionStart surfacing
       - critical   → file + surfacing + (optional) Lumen voice + KG discovery

Design notes:
    - Never blocks the editor. The PostToolUse hook forks this script and exits.
    - Persistent governance identity via SyncGovernanceClient (REST transport).
      Checks in after surface_pending; resolution events posted on --resolve/--dismiss.
    - Graceful degradation: if governance REST is down, falls back to calling
      Ollama directly at localhost:11434.
    - Findings are append-only; lifecycle (resolved/dismissed/aged-out) happens
      via the surface hook and explicit user action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from agents.common.log import trim_log as _common_trim_log
from agents.common.findings import post_finding

PATTERNS_FILE = Path(__file__).resolve().parent / "patterns.md"
STATE_DIR = PROJECT_ROOT / "data" / "watcher"
FINDINGS_FILE = STATE_DIR / "findings.jsonl"
DEDUP_FILE = STATE_DIR / "dedup.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-watcher.log"

GOV_REST_URL = "http://localhost:8767/v1/tools/call"
OLLAMA_FALLBACK_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_MODEL = "qwen3-coder-next:latest"
DEFAULT_TIMEOUT = 45

# How many lines of context to include when no explicit region is given.
# Qwen3-Coder-Next (the current default detector) has a 256K context window,
# and should_skip() already caps at 256KB of file bytes (~6500 lines at
# typical density), so DEFAULT_CONTEXT_LINES is effectively a last-resort
# sanity cap rather than a real limit. The old 200-line value was a
# gemma4-era relic that silently truncated scans to the file head and
# missed every bug past line 200. Ogler's third-round self-review caught
# it on 2026-04-11.
DEFAULT_CONTEXT_LINES = 10000

# Age findings out after this many days
FINDINGS_TTL_DAYS = 14

# Cap for ~/Library/Logs/unitares-watcher.log rotation. Watcher logs a few
# lines per scan; 5000 lines ≈ 500 scans of operational history, which is
# plenty for debugging. Without this, the log file was a direct P002 match
# against the Watcher's own pattern library — unbounded append forever.
MAX_LOG_LINES = 5000

# ---------------------------------------------------------------------------
# Identity — persistent governance presence
# ---------------------------------------------------------------------------

# Anchor-scoped: one Watcher identity per host, shared across every git
# worktree. The legacy per-worktree path (PROJECT_ROOT/.watcher_session)
# minted a fresh UUID on the first edit in each new worktree, producing
# N Watchers per developer instead of one.
SESSION_FILE = Path.home() / ".unitares" / "anchors" / "watcher.json"
LEGACY_SESSION_FILE = PROJECT_ROOT / ".watcher_session"

_watcher_identity: dict[str, str] | None = None


def _load_session() -> dict[str, str]:
    """Load persistent identity from the anchor, migrating from legacy if needed."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    if LEGACY_SESSION_FILE.exists():
        try:
            data = json.loads(LEGACY_SESSION_FILE.read_text())
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps(data))
            log(f"migrated watcher identity from {LEGACY_SESSION_FILE} to {SESSION_FILE}")
            return data
        except (json.JSONDecodeError, OSError) as e:
            log(f"legacy session migration failed: {e}", "warning")
    return {}


def _save_session(client_session_id: str, continuity_token: str, agent_uuid: str) -> None:
    """Persist identity state to the anchor."""
    data = {
        "client_session_id": client_session_id,
        "continuity_token": continuity_token,
        "agent_uuid": agent_uuid,
    }
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(data))
    except OSError as e:
        log(f"failed to save session: {e}", "warning")


def resolve_identity(client) -> None:
    """Resolve Watcher identity via UUID-direct → token → fresh onboard.

    Name-resume (previous Step 2) was removed 2026-04-17 when the server-side
    name-claim path was deleted. Without it, every `identity(name="Watcher")`
    call forks a fresh UUID, which is exactly what happened: 21 Watcher
    forks in ~2h before this fix. PATH 0 (UUID-direct) takes its place —
    strongest signal, unambiguous, unchallengeable by name-collision bugs.

    Timeout discipline (added 2026-04-17 after a 34-fork incident):
    a transient governance timeout must NOT fall through to onboard — the
    stored UUID is probably still valid, and onboarding forks a new agent
    every time the server is slow. On GovernanceTimeoutError we just skip
    this cycle; a later cycle will retry PATH 0.

    Sets module-level _watcher_identity on success, leaves it None on failure.
    """
    from unitares_sdk.errors import GovernanceTimeoutError

    global _watcher_identity
    saved = _load_session()

    # Step 0: UUID-direct (PATH 0) — strongest resume signal.
    # Works whenever we have a stored UUID, even if the token is stale.
    if saved.get("agent_uuid"):
        try:
            client.identity(agent_uuid=saved["agent_uuid"], resume=True)
            _sync_identity(client)
            return
        except GovernanceTimeoutError as e:
            # Transient server slowness — don't fork a new agent. Skip this
            # cycle; the stored UUID remains the ground truth.
            log(f"uuid-direct resume timed out ({e}) — skipping, will retry next cycle", "warning")
            _watcher_identity = None
            return
        except Exception as e:
            log(f"uuid-direct resume failed: {e}", "warning")

    # Step 1: Token resume (PATH 2.8) — fallback when UUID is missing.
    if saved.get("continuity_token"):
        try:
            client.identity(continuity_token=saved["continuity_token"], resume=True)
            _sync_identity(client)
            return
        except GovernanceTimeoutError as e:
            log(f"token resume timed out ({e}) — skipping, will retry next cycle", "warning")
            _watcher_identity = None
            return
        except Exception as e:
            log(f"token resume failed: {e}", "warning")

    # Step 2: Fresh onboard — only when nothing else works.
    try:
        client.onboard("Watcher", spawn_reason="resident_observer")
        _sync_identity(client)
        # Stamp 'persistent' tag so auto_archive_orphan_agents skips this
        # identity (is_agent_protected in src/agent_lifecycle.py). Without
        # this, low-activity windows cause orphan-sweep false-positives and
        # the Watcher gets archived-then-silently-resurrected every cycle.
        if _watcher_identity and _watcher_identity.get("agent_uuid"):
            try:
                client.call_tool(
                    "update_agent_metadata",
                    {
                        "agent_id": _watcher_identity["agent_uuid"],
                        "tags": ["persistent"],
                    },
                )
                log("stamped 'persistent' tag — protected from orphan sweep")
            except Exception as e:
                log(f"failed to stamp 'persistent' tag: {e}", "warning")
    except GovernanceTimeoutError as e:
        # Onboard timeout is the worst case — don't assume it failed, it may
        # have partial-committed on the server side (which is exactly how
        # the 34-fork incident happened). Just give up for this cycle.
        log(f"onboard timed out ({e}) — skipping, will retry next cycle", "warning")
        _watcher_identity = None
    except Exception as e:
        log(f"onboard failed — identity unavailable: {e}", "warning")
        _watcher_identity = None


def _sync_identity(client) -> None:
    """Capture identity from client after successful resolution."""
    global _watcher_identity
    _watcher_identity = {
        "client_session_id": client.client_session_id or "",
        "continuity_token": client.continuity_token or "",
        "agent_uuid": client.agent_uuid or "",
    }
    _save_session(
        _watcher_identity["client_session_id"],
        _watcher_identity["continuity_token"],
        _watcher_identity["agent_uuid"],
    )


def get_watcher_identity() -> dict[str, str] | None:
    """Return resolved identity or None if governance is unavailable."""
    return _watcher_identity


def _make_identity_client():
    """Create a SyncGovernanceClient for identity resolution."""
    from unitares_sdk import SyncGovernanceClient
    return SyncGovernanceClient(rest_url=GOV_REST_URL, transport="rest", timeout=30)


# ---------------------------------------------------------------------------
# Check-in — periodic EISV signal to governance
# ---------------------------------------------------------------------------


def compute_checkin_complexity(active_count: int) -> float:
    """Map active finding count to complexity: 0→0.1, 10+→0.6, linear between."""
    return min(0.6, 0.1 + active_count * 0.05)


def compute_checkin_confidence(confirmed: int, dismissed: int) -> float:
    """Confirmed / (confirmed + dismissed), with warmup default of 0.7."""
    total = confirmed + dismissed
    if total < 5:
        return 0.7
    return confirmed / total


def _build_checkin_summary() -> tuple[str, float, float]:
    """Build check-in response_text, complexity, and confidence from findings.jsonl."""
    findings = _iter_findings_raw()
    if not findings:
        return "Watcher idle", 0.05, 0.9

    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        status = f.get("status", "open")
        by_status[status] = by_status.get(status, 0) + 1
        if status in ("open", "surfaced"):
            sev = f.get("severity", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1

    active = by_status.get("open", 0) + by_status.get("surfaced", 0)
    confirmed = by_status.get("confirmed", 0)
    dismissed = by_status.get("dismissed", 0)

    sev_parts = ", ".join(f"{n} {s}" for s, n in sorted(by_severity.items()) if n > 0)
    summary_parts = []
    if active:
        summary_parts.append(f"{active} unresolved ({sev_parts})" if sev_parts else f"{active} unresolved")
    if confirmed:
        summary_parts.append(f"{confirmed} confirmed")
    if dismissed:
        summary_parts.append(f"{dismissed} dismissed")
    summary = f"Watcher: {', '.join(summary_parts)}" if summary_parts else "Watcher idle"

    complexity = compute_checkin_complexity(active)
    confidence = compute_checkin_confidence(confirmed, dismissed)
    return summary, complexity, confidence


def _do_checkin() -> None:
    """Post a check-in to governance. Called at the end of surface_pending()."""
    identity = get_watcher_identity()
    if identity is None:
        return

    summary, complexity, confidence = _build_checkin_summary()

    try:
        client = _make_identity_client()
        # Restore identity state so the client can inject session args
        client.client_session_id = identity["client_session_id"]
        client.continuity_token = identity["continuity_token"]
        client.agent_uuid = identity["agent_uuid"]

        client.checkin(
            response_text=summary,
            complexity=complexity,
            confidence=confidence,
            response_mode="compact",
        )
        log(f"check-in: {summary}")
    except Exception as e:
        log(f"check-in failed: {e}", "warning")


# Paths we never scan — too much churn, not worth the noise
SKIP_PATH_FRAGMENTS = (
    "/.git/",
    "/node_modules/",
    "/__pycache__/",
    "/.venv/",
    "/venv/",
    "/dist/",
    "/build/",
    "/.pytest_cache/",
    "/data/logs/",
    "/data/watcher/",  # never scan our own findings
)

SKIP_EXTENSIONS = (
    ".pyc",
    ".log",
    ".lock",
    ".min.js",
    ".map",
    ".svg",
    ".png",
    ".jpg",
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    pattern: str
    file: str
    line: int
    hint: str
    severity: str  # critical | high | medium | low
    detected_at: str
    model_used: str
    # Hash of the normalized source line at `line` at the time of detection.
    # Included in the fingerprint so the same pattern flagged at the same
    # line number but against DIFFERENT code (e.g. you fixed bug A at line 47
    # and a new bug B arrived at the same line) does not get silently
    # dedup'd as a rerun of the old finding.
    line_content_hash: str = ""
    fingerprint: str = ""
    status: str = "open"  # open | surfaced | confirmed | dismissed | aged_out
    violation_class: str = ""  # CON | INT | ENT | REC | BEH | VOI

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """Stable identifier combining pattern, file, line, and (optionally)
        a content hash. Callers that want content-aware dedup should set
        ``line_content_hash`` BEFORE invoking this and then assign the
        result back to ``fingerprint``.

        The file path is normalized to its repo-relative form (relative to
        the git worktree root containing it) so the same line in identical
        code checked out across multiple git worktrees produces ONE
        fingerprint, not N. The displayed ``file`` field is left absolute so
        the user can navigate to the right copy.
        """
        normalized_path = repo_relative_path(self.file)
        key = f"{self.pattern}|{normalized_path}|{self.line}|{self.line_content_hash}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


_REPO_ROOT_CACHE: dict[str, str] = {}


def repo_relative_path(file_path: str) -> str:
    """Return ``file_path`` relative to its containing git worktree root.

    Falls back to the absolute string if the path is not inside a git
    repository or git invocation fails. Result is normalized to forward
    slashes so the fingerprint is platform-stable.

    Cached per-directory because hook-driven scans hit the same worktree
    over and over and ``git rev-parse`` is otherwise tens of ms each call.
    """
    if not file_path:
        return file_path
    p = Path(file_path)
    parent_key = str(p.parent if p.is_absolute() else p.resolve().parent)
    toplevel = _REPO_ROOT_CACHE.get(parent_key)
    if toplevel is None:
        try:
            result = subprocess.run(
                ["git", "-C", parent_key, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            toplevel = result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            toplevel = ""
        _REPO_ROOT_CACHE[parent_key] = toplevel
    if not toplevel:
        return file_path
    try:
        rel = Path(file_path).resolve().relative_to(Path(toplevel).resolve())
    except ValueError:
        return file_path
    return rel.as_posix()


def hash_line_content(source_line: str) -> str:
    """Stable hash of a source line for content-aware fingerprinting.

    Whitespace is stripped from both ends so indent-only reformats do not
    trigger spurious re-flags. Internal whitespace is preserved because it
    can be semantically meaningful (e.g. dict literal formatting).
    """
    normalized = (source_line or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Logging (simple rotating append)
# ---------------------------------------------------------------------------


def log(msg: str, level: str = "info") -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} [{level}] {msg}\n"
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except OSError:
        pass  # never let logging errors take down the watcher
    if os.environ.get("WATCHER_DEBUG") == "1":
        sys.stderr.write(line)




# ---------------------------------------------------------------------------
# Skip heuristics
# ---------------------------------------------------------------------------


def should_skip(file_path: str) -> tuple[bool, str]:
    """Return (skip, reason)."""
    if not file_path:
        return True, "no file path"
    p = Path(file_path)
    if not p.exists():
        return True, "file does not exist"
    if not p.is_file():
        return True, "not a regular file"
    abs_path = str(p.resolve())
    for frag in SKIP_PATH_FRAGMENTS:
        if frag in abs_path:
            return True, f"skip fragment {frag}"
    for ext in SKIP_EXTENSIONS:
        if abs_path.endswith(ext):
            return True, f"skip extension {ext}"
    try:
        if p.stat().st_size > 256 * 1024:
            return True, "file larger than 256KB"
    except OSError as e:
        return True, f"stat failed: {e}"
    return False, ""


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_file_region(
    file_path: str, region: str | None = None, max_lines: int = DEFAULT_CONTEXT_LINES
) -> tuple[str, int, int]:
    """Return (text, start_line, end_line). Lines are 1-indexed, inclusive."""
    p = Path(file_path)
    lines = p.read_text(errors="replace").splitlines()
    total = len(lines)

    if region:
        # Accept "L240-L290", "240-290", "L240-290", "240-L290".
        # The previous lstrip("L") only stripped the leading L of the start
        # token; the end token kept its L and int() raised, causing a silent
        # fallback to the file head.
        try:
            start_token, _, end_token = region.partition("-")
            if not end_token:
                raise ValueError("region missing '-' separator")
            start = max(1, int(start_token.lstrip("Ll")))
            end = min(total, int(end_token.lstrip("Ll")))
            if end < start:
                raise ValueError(f"end {end} before start {start}")
        except ValueError as e:
            log(f"bad region {region!r}: {e}; scanning head", "warning")
            start, end = 1, min(total, max_lines)
    else:
        start, end = 1, min(total, max_lines)

    snippet_lines = [f"{i:4d}: {lines[i - 1]}" for i in range(start, end + 1)]
    return "\n".join(snippet_lines), start, end


# ---------------------------------------------------------------------------
# Pattern library loading
# ---------------------------------------------------------------------------


def load_patterns() -> str:
    if not PATTERNS_FILE.exists():
        return "(no pattern library found)"
    return PATTERNS_FILE.read_text()


# Map pattern id → authoritative severity. The model is allowed to flag
# patterns but we override its severity field with the library's, since small
# local models tend to downgrade severities to "medium" by default.
def load_pattern_severities() -> dict[str, str]:
    import re

    severities: dict[str, str] = {}
    if not PATTERNS_FILE.exists():
        return severities
    text = PATTERNS_FILE.read_text()
    # Match headings like:  ### P001 — Fire-and-forget task leak (severity: high)
    pat = re.compile(r"^###\s+(P\d{3})\b.*?\(severity:\s*([a-zA-Z]+)", re.MULTILINE)
    for m in pat.finditer(text):
        severities[m.group(1)] = m.group(2).strip().lower()
    return severities


def load_pattern_violation_classes() -> dict[str, str]:
    """Map pattern id -> violation class from patterns.md headers."""
    import re

    classes: dict[str, str] = {}
    if not PATTERNS_FILE.exists():
        return classes
    text = PATTERNS_FILE.read_text()
    pat = re.compile(
        r"^###\s+((?:EXP-)?P\d{3})\b.*?violation_class:\s*([A-Z]+)",
        re.MULTILINE,
    )
    for m in pat.finditer(text):
        classes[m.group(1)] = m.group(2).strip()
    return classes


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_review_prompt(file_path: str, code_snippet: str) -> str:
    """Reasoning-based code review prompt — no pattern library, model thinks freely."""
    return f"""You are a senior code reviewer. Read the code below carefully and identify actual bugs, logic errors, resource leaks, race conditions, or security issues.

RULES:
1. Only report issues you are confident about. No style nitpicks, no "consider using X" suggestions.
2. Each finding must explain WHY it's a bug — what breaks, under what conditions.
3. Ignore comments. Only analyze executable code.
4. If the code looks correct, return an empty findings list. That is the right answer most of the time.

OUTPUT FORMAT — JSON only, no prose, no markdown fences:
{{"findings":[{{"line":<int>,"severity":"high|medium|low","hint":"<what's wrong, <=15 words>","reasoning":"<1-2 sentences: what breaks and when>"}}]}}

CODE TO REVIEW (from {file_path}):
```
{code_snippet}
```

Remember: JSON only. Empty findings list is correct if nothing is wrong. Quality over quantity — one real bug beats ten maybes.
"""


def build_prompt(patterns_md: str, file_path: str, code_snippet: str) -> str:
    return f"""You are Watcher — a bug-pattern matcher for this codebase. You do NOT need to decide if a bug is "real" or "standard practice". Your job is to flag every occurrence of a known-bad pattern from the library below, without second-guessing.

CRITICAL RULES — read carefully before scanning:

1. **Code only, never comments.** Lines starting with `#`, lines inside `'''...'''` or `\"\"\"...\"\"\"` triple-quoted blocks, and lines inside `/* ... */` or `//` are COMMENTS. They are documentation, not code. NEVER flag a pattern that only appears in a comment — even if the comment uses words like "leak", "transient", "mutation", "fire-and-forget", or describes a past bug. Comments often EXPLAIN fixes for past bugs and will mention the bug words in plain English. Ignore them.

2. **Pattern matches must be literal code occurrences.** P001 requires a literal `create_task(` call. P003 requires a literal `UNITARESMonitor(` constructor. P011 requires an assignment statement followed by no `await` to a persist function. Function names containing "task" are NOT P001 matches; comments containing "monitor" are NOT P003 matches.

3. **Asyncio supervisor exception.** A `while True:` (or `while self.running:`) loop that contains a `try: ... except asyncio.CancelledError:` handler is a STANDARD asyncio supervisor task pattern. Do NOT flag it as P009. P009 is for polling loops that lack ANY cancellation/timeout, not for long-running supervisors with proper shutdown handling.

4. **For every finding you emit, include a 1-sentence justification field `evidence` quoting the literal code (not a comment) that matches.** If you can't quote actual code, drop the finding.

OUTPUT FORMAT — JSON only, no prose, no markdown fences:
{{"findings":[{{"pattern":"P001","line":<int>,"hint":"<<=12 words>","evidence":"<literal code line>"}}]}}

5. Empty findings list is valid and correct if nothing matches.
6. Do NOT invent pattern IDs. Only use IDs present in the library.
7. Do NOT rationalize. Either the literal code matches the literal pattern or it doesn't.
8. The `line` field is the line number shown in the snippet (the number before the colon).

PATTERN LIBRARY:
{patterns_md}

CODE TO SCAN (from {file_path}):
```
{code_snippet}
```

Remember: JSON only. No prose. No markdown fences around the JSON. Comments don't count.
"""


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------


def call_model_via_governance(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    """Call the governance REST /v1/tools/call endpoint with call_model.

    Notes:
        - Uses REST /v1/tools/call transport (no anyio deadlock).
        - If the governance server is down, the caller should catch the exception
          and fall back to Ollama direct.
    """
    from unitares_sdk import SyncGovernanceClient
    from unitares_sdk.errors import GovernanceError

    client = SyncGovernanceClient(rest_url=GOV_REST_URL, transport="rest", timeout=timeout)
    try:
        result = client.call_model(
            prompt=prompt,
            provider="ollama",
            model=model,
            max_tokens=1024,
            temperature=0.0,
        )
    except GovernanceError as e:
        raise RuntimeError(str(e)) from e

    if not result.success:
        raise RuntimeError(f"call_model reported failure: {result}")
    return {
        "text": result.response or "",
        "model_used": model,
        "tokens_used": 0,
    }


def call_ollama_direct(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    """Fallback: call Ollama's OpenAI-compatible endpoint directly."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            # Same rationale as call_model_via_governance above:
            # trimmed max_tokens to match Qwen3 token economy, and
            # temperature=0.0 for deterministic detector output.
            "max_tokens": 1024,
            "temperature": 0.0,
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_FALLBACK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    choice = data["choices"][0]["message"]
    text = choice.get("content", "") or choice.get("reasoning", "") or ""
    usage = data.get("usage", {})
    return {
        "text": text,
        "model_used": data.get("model", model),
        "tokens_used": usage.get("total_tokens", 0),
    }


def call_model(prompt: str, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    try:
        return call_model_via_governance(prompt, model, timeout)
    except (urllib.error.URLError, RuntimeError, TimeoutError, json.JSONDecodeError, ImportError) as e:
        # ImportError covers the case where unitares_sdk is not installed in the
        # Python that launched the hook (e.g. Homebrew python3 vs system framework
        # python). Without this the silent-fail path skips the Ollama fallback.
        log(f"governance call_model failed ({e}); falling back to ollama direct", "warning")
        return call_ollama_direct(prompt, model, timeout)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _looks_like_comment(line: str) -> bool:
    """Cheap heuristic: does this line look like a comment rather than code?"""
    stripped = line.strip()
    if not stripped:
        return True
    # Strip the leading "  NNN: " line-number prefix the watcher emits
    if ":" in stripped:
        head, _, rest = stripped.partition(":")
        if head.strip().isdigit():
            stripped = rest.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    if stripped.startswith(('"""', "'''")):
        return True
    if stripped.startswith(("//", "/*", "*")):
        return True
    return False


def parse_findings(
    text: str, file_path: str, model_used: str, region_start: int
) -> list[tuple[Finding, str]]:
    """Parse the model's JSON response into Finding objects.

    Tolerant of:
      - leading/trailing whitespace
      - markdown code fences (```json ... ```)
      - extra prose before the JSON block
    """
    cleaned = text.strip()

    # Strip markdown fences
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        # typically ['', 'json\n{...}', ''] or ['', '{...}', '']
        for part in parts:
            stripped = part.strip()
            if stripped.startswith(("json\n", "json ")):
                stripped = stripped[5:].strip()
            if stripped.startswith("{"):
                cleaned = stripped
                break

    # Find the first '{' and last '}' as a last resort
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    if not cleaned:
        return []

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log(f"failed to parse model output as JSON: {e}; raw={text[:300]!r}", "warning")
        return []

    raw_findings = data.get("findings", []) if isinstance(data, dict) else []
    if not isinstance(raw_findings, list):
        return []

    library_severities = load_pattern_severities()
    library_violation_classes = load_pattern_violation_classes()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings: list[tuple[Finding, str]] = []
    for rf in raw_findings:
        if not isinstance(rf, dict):
            continue
        pattern = str(rf.get("pattern", "")).strip()
        if not pattern:
            continue
        # Drop findings whose pattern id we don't recognize — the model is
        # only allowed to flag library patterns, not invent new ones.
        if pattern not in library_severities:
            log(f"dropping unknown pattern id from model: {pattern!r}", "warning")
            continue
        try:
            line_in_snippet = int(rf.get("line", 0))
        except (TypeError, ValueError):
            line_in_snippet = 0
        # The model sees line numbers within the snippet — they are already
        # the actual file line numbers since we emit `{i}: <content>` where
        # `i` is the original file line number.
        line = line_in_snippet if line_in_snippet > 0 else region_start
        hint = str(rf.get("hint", "")).strip()[:200]
        evidence = str(rf.get("evidence", "")).strip()[:300]
        # Authoritative severity comes from the library, never the model.
        severity = library_severities[pattern]
        findings.append(
            (
                Finding(
                    pattern=pattern,
                    file=file_path,
                    line=line,
                    hint=hint,
                    severity=severity,
                    detected_at=now,
                    model_used=model_used,
                    violation_class=library_violation_classes.get(pattern, ""),
                ),
                evidence,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Dedup & persistence
# ---------------------------------------------------------------------------


def load_dedup() -> dict[str, str]:
    """Return mapping of fingerprint → detected_at timestamp."""
    if not DEDUP_FILE.exists():
        return {}
    try:
        return json.loads(DEDUP_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_dedup(dedup: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DEDUP_FILE.write_text(json.dumps(dedup, indent=2))


def sweep_stale_dedup(
    dedup: dict[str, str],
    ttl_days: int = FINDINGS_TTL_DAYS,
    now: datetime | None = None,
) -> dict[str, str]:
    """Drop dedup entries older than ``ttl_days``.

    Prevents the dedup dict from growing unboundedly over months — a P002
    pattern match against the Watcher's own code that Ogler correctly
    flagged at :78 / :127 / :496 on 2026-04-10. ``FINDINGS_TTL_DAYS`` was
    defined but never enforced in the first cut of this module; this
    function is the enforcement point.

    Entries with an unparseable timestamp are kept (fail-open), so a
    corrupted dedup file never silently empties itself.
    """
    if not dedup:
        return dedup
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=ttl_days)
    pruned: dict[str, str] = {}
    dropped = 0
    for fingerprint, ts in dedup.items():
        try:
            detected = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            # Unparseable timestamp — keep the entry rather than drop it
            # blindly. We'd rather leak a few entries than lose findings.
            pruned[fingerprint] = ts
            continue
        if detected >= cutoff:
            pruned[fingerprint] = ts
        else:
            dropped += 1
    if dropped:
        log(
            f"dedup sweep: dropped {dropped} stale entries older than {ttl_days}d "
            f"({len(pruned)} remain)"
        )
    return pruned


def persist_findings(new_findings: list[Finding]) -> list[Finding]:
    """Append new (non-duplicate) findings to findings.jsonl. Return the ones
    that were actually new (dedup filter applied)."""
    dedup = load_dedup()
    dedup = sweep_stale_dedup(dedup)
    fresh: list[Finding] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for f in new_findings:
        if f.fingerprint in dedup:
            continue  # already flagged this one
        dedup[f.fingerprint] = now
        fresh.append(f)

    if fresh or dedup != load_dedup():
        # Persist even if `fresh` is empty, so the sweep's pruning actually
        # lands on disk. Otherwise stale entries would rematerialize on the
        # next scan.
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if fresh:
            for f in fresh:
                persist_finding(f)
        save_dedup(dedup)

    return fresh


def persist_finding(finding: Finding) -> None:
    """Append a new finding to findings.jsonl and, for high/critical severity,
    mirror it into the governance event stream so the Discord bridge surfaces it.

    Low/medium stays local — the SessionStart hook handles surfacing those
    to the in-editor Claude session.

    The caller is responsible for the dedup gate; this function does NOT
    check dedup itself.
    """
    FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FINDINGS_FILE.open("a") as f:
        f.write(json.dumps(asdict(finding)) + "\n")

    if finding.severity in ("high", "critical"):
        post_finding(
            event_type="watcher_finding",
            severity=finding.severity,
            message=f"[{finding.pattern}] {finding.file}:{finding.line} — {finding.hint}",
            agent_id="watcher",
            agent_name="Watcher",
            fingerprint=finding.fingerprint,
            extra={
                "pattern": finding.pattern,
                "file": finding.file,
                "line": finding.line,
                "violation_class": finding.violation_class,
            },
        )


# ---------------------------------------------------------------------------
# Lifecycle commands
#
# Without these, findings.jsonl is append-only with no way to mark a finding
# as confirmed, dismissed, or stale. Governance has no calibration signal and
# the surface hook just accumulates noise. Ogler's critique of the rollup
# daemon was specifically "build the bottom before the top" — this is the
# bottom.
# ---------------------------------------------------------------------------


VALID_FINDING_STATUSES = ("open", "surfaced", "confirmed", "dismissed", "aged_out")
MIN_FINGERPRINT_PREFIX = 4  # users can type the first N chars instead of all 16


def _iter_findings_raw() -> list[dict[str, Any]]:
    """Load all findings from findings.jsonl as raw dicts. Silently skips
    malformed lines. Returns [] if the file doesn't exist."""
    if not FINDINGS_FILE.exists():
        return []
    out: list[dict[str, Any]] = []
    with FINDINGS_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_findings_atomic(findings: list[dict[str, Any]]) -> None:
    """Atomically replace findings.jsonl with the given list. Writes to a
    sibling temp file and renames, so a crash mid-write cannot corrupt the
    findings feed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FINDINGS_FILE.with_suffix(FINDINGS_FILE.suffix + ".tmp")
    with tmp.open("w") as fh:
        for f in findings:
            fh.write(json.dumps(f) + "\n")
    tmp.replace(FINDINGS_FILE)


def match_fingerprint(prefix: str, findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Return (matches, error) for a fingerprint prefix lookup.

    - Exact 16-char match returns at most one finding.
    - Shorter prefixes match all findings whose fingerprint starts with it.
    - Prefix shorter than ``MIN_FINGERPRINT_PREFIX`` is rejected to guard
      against accidental nukes from a 1-2 char typo.
    """
    if not prefix:
        return [], "empty fingerprint"
    if len(prefix) < MIN_FINGERPRINT_PREFIX:
        return [], f"fingerprint too short (min {MIN_FINGERPRINT_PREFIX} chars)"
    matches = [f for f in findings if f.get("fingerprint", "").startswith(prefix)]
    return matches, None


def update_finding_status(fingerprint_prefix: str, new_status: str, resolver_agent_id: str | None = None) -> int:
    """Mark a finding as ``new_status`` by fingerprint prefix.

    Returns exit code:
      0 — updated exactly one finding
      1 — no match or ambiguous prefix
      2 — invalid status
    """
    if new_status not in VALID_FINDING_STATUSES:
        log(f"update_finding_status: invalid status {new_status!r}", "error")
        print(f"error: invalid status {new_status!r}; must be one of {VALID_FINDING_STATUSES}")
        return 2

    findings = _iter_findings_raw()
    if not findings:
        print("error: findings.jsonl is empty or absent")
        return 1

    matches, err = match_fingerprint(fingerprint_prefix, findings)
    if err:
        print(f"error: {err}")
        return 1
    if not matches:
        print(f"error: no finding matches fingerprint prefix {fingerprint_prefix!r}")
        return 1
    if len(matches) > 1:
        print(f"error: fingerprint prefix {fingerprint_prefix!r} is ambiguous ({len(matches)} matches):")
        for m in matches:
            print(
                f"  {m.get('fingerprint','?')[:16]} {m.get('severity','?')} "
                f"{m.get('pattern','?')} {m.get('file','?')}:{m.get('line','?')}"
            )
        return 1

    target_fp = matches[0].get("fingerprint", "")
    updated: list[dict[str, Any]] = []
    for f in findings:
        if f.get("fingerprint") == target_fp:
            f = {**f, "status": new_status}
        updated.append(f)
    _write_findings_atomic(updated)
    log(f"update_finding_status: {target_fp[:8]} → {new_status}")
    print(
        f"ok: {target_fp[:16]} → {new_status} "
        f"({matches[0].get('pattern','?')} at {matches[0].get('file','?')}:{matches[0].get('line','?')})"
    )

    # --- Post resolution event to governance ---
    if new_status in ("confirmed", "dismissed"):
        _post_resolution_event(matches[0], new_status, resolver_agent_id)

    return 0


def _post_resolution_event(finding: dict, action: str, resolver_agent_id: str | None) -> None:
    """Post a watcher_resolution event to the governance event stream."""
    identity = get_watcher_identity()
    if identity is None:
        return

    try:
        post_finding(
            event_type="watcher_resolution",
            severity=finding.get("severity", "unknown"),
            message=f"[{action}] {finding.get('pattern', '?')} {finding.get('file', '?')}:{finding.get('line', '?')} — {finding.get('hint', '')}",
            agent_id=identity["agent_uuid"],
            agent_name="Watcher",
            fingerprint=finding.get("fingerprint", ""),
            extra={
                "action": action,
                "pattern": finding.get("pattern", ""),
                "file": finding.get("file", ""),
                "line": finding.get("line", 0),
                "violation_class": finding.get("violation_class", ""),
                "resolved_by": resolver_agent_id,
            },
        )
    except Exception as e:
        log(f"resolution event failed: {e}", "warning")


def sweep_stale_findings() -> int:
    """Drop findings whose target file no longer exists on disk.

    This is the "the file got deleted or renamed" cleanup — we don't want
    the surface hook to keep nagging you about a file that isn't there
    anymore. Open/surfaced findings get aged_out via this path too because
    there's no code to evaluate.
    """
    findings = _iter_findings_raw()
    if not findings:
        print("(no findings to sweep)")
        return 0

    kept: list[dict[str, Any]] = []
    dropped = 0
    for f in findings:
        path = f.get("file", "")
        if path and Path(path).exists():
            kept.append(f)
        else:
            dropped += 1

    if dropped == 0:
        print(f"(nothing to sweep: {len(findings)} findings, all target files present)")
        return 0

    _write_findings_atomic(kept)
    log(f"sweep_stale_findings: dropped {dropped} findings for missing files")
    print(f"ok: dropped {dropped} finding(s) with missing target files, kept {len(kept)}")
    return 0


# ---------------------------------------------------------------------------
# Surfacing — how findings reach the main Claude session
#
# Two hooks call the functions below:
#
#   SessionStart → --print-unresolved (read-only, shows open+surfaced so the
#     new session sees the full backlog — if it only showed open, findings
#     already "surfaced" in a previous session would silently disappear from
#     context)
#
#   UserPromptSubmit → --surface-pending (chime mode: shows only open
#     findings, transitions them to surfaced so the next prompt doesn't
#     re-chime the same items)
#
# Both print a <unitares-watcher-findings> block that the Claude Code hook
# system injects as additionalContext. The formatter is shared between the
# two commands so the block shape stays consistent no matter which hook
# emitted it.
# ---------------------------------------------------------------------------


def _format_findings_block(
    findings: list[dict[str, Any]],
    *,
    header: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Render the <unitares-watcher-findings> block.

    Returns ``(block, shown)`` where:
      - ``block`` is the formatted string to print, or None if nothing
        should be surfaced (empty list / all-low-severity).
      - ``shown`` is the ordered list of findings that actually made it
        into the displayed block. Callers use this to decide which
        findings to transition to ``surfaced`` status — we only want to
        mark findings the user actually saw, never the ones dropped by
        the display cap.

    The (block, shown) tuple shape replaces an earlier bug where
    surface_pending marked ALL open findings as surfaced regardless of
    whether the display cap had hidden them. Medium-severity findings
    behind a wall of criticals would transition silently and then get
    dedup'd on re-detection — effectively a silent drop of real signal.
    Ogler caught it on 2026-04-11.

    Severity rules for the displayed subset:
      - critical/high: always shown
      - medium: shown only if there's room under the 10-item display cap
        reserved for critical+high (keeps session context from drowning in
        medium-severity noise while still surfacing some)
      - low: never shown (file-only signal)
    """
    if not findings:
        return None, []

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings = sorted(
        findings,
        key=lambda f: (
            severity_order.get(f.get("severity", "low"), 9),
            f.get("detected_at", ""),
        ),
    )

    critical_high = [f for f in findings if f.get("severity") in ("critical", "high")]
    medium = [f for f in findings if f.get("severity") == "medium"]
    shown = critical_high[:]
    if len(shown) < 10:
        shown += medium[: 10 - len(shown)]

    if not shown:
        return None, []

    lines: list[str] = []
    lines.append("<unitares-watcher-findings>")
    lines.append(header)
    lines.append("")
    for f in shown:
        sev = str(f.get("severity", "?")).upper()
        pat = f.get("pattern", "?")
        vcls = f.get("violation_class", "")
        file = f.get("file", "?")
        line_no = f.get("line", "?")
        hint = f.get("hint", "")
        fp = str(f.get("fingerprint", ""))[:8]
        status = f.get("status", "open")
        marker = "" if status == "open" else f" ({status})"
        cls_tag = f"[{vcls}] " if vcls else ""
        lines.append(f"  [{sev}] {cls_tag}{pat} {file}:{line_no} — {hint}  (#{fp}){marker}")
    lines.append("")
    lines.append(f"Total unresolved: {len(findings)} (showing {len(shown)})")
    lines.append(
        "Resolve: python3 agents/watcher/agent.py --resolve <fingerprint> --agent-id <your-uuid>"
    )
    lines.append(
        "Dismiss: python3 agents/watcher/agent.py --dismiss <fingerprint> --agent-id <your-uuid>"
    )
    lines.append("</unitares-watcher-findings>")
    return "\n".join(lines), shown


def print_unresolved() -> int:
    """Print the unresolved-findings block (open + surfaced) without mutating
    state. Called by the SessionStart hook — it's read-only so session starts
    never accidentally reshape the findings state.
    """
    findings = [
        f
        for f in _iter_findings_raw()
        if f.get("status", "open") in ("open", "surfaced")
    ]
    block, _shown = _format_findings_block(
        findings,
        header=(
            "The UNITARES Watcher agent flagged the following unresolved code\n"
            "patterns in recently edited files. Watcher has a track record — these\n"
            "are not noise. Investigate or explicitly --dismiss them."
        ),
    )
    if block is None:
        return 0
    print(block)
    return 0


def surface_pending() -> int:
    """Chime mode: print findings with status == 'open' and transition ONLY
    THOSE ACTUALLY DISPLAYED to 'surfaced'. Called by the UserPromptSubmit
    hook so each prompt the user sends gets a delta of "what Watcher caught
    since your last prompt".

    After this runs, the findings that were actually shown in the block are
    recorded as surfaced. Any findings dropped by the severity display cap
    (typically medium-severity findings crowded out by a wall of
    critical/high) stay `open` so they'll appear on a later chime once the
    high-severity queue drains. This prevents the silent-drop bug where
    medium findings were previously marked surfaced without the user ever
    seeing them.
    """
    all_findings = _iter_findings_raw()
    open_findings = [f for f in all_findings if f.get("status", "open") == "open"]

    block, shown = _format_findings_block(
        open_findings,
        header=(
            "Watcher caught the following while you were working. These are\n"
            "new since your last prompt. Look them over before proceeding — or\n"
            "dismiss any false positives with --dismiss <fingerprint>."
        ),
    )
    # Always check in to governance, even when there's nothing new to surface.
    # Otherwise Watcher goes silent between finding bursts.
    _do_checkin()

    if block is None:
        return 0

    print(block)

    # Only transition findings that made it past the display cap. The ones
    # the user saw → surfaced. The ones crowded out → stay open.
    surfaced_fps = {f.get("fingerprint") for f in shown}
    updated: list[dict[str, Any]] = []
    changed = False
    for f in all_findings:
        if f.get("fingerprint") in surfaced_fps and f.get("status", "open") == "open":
            f = {**f, "status": "surfaced"}
            changed = True
        updated.append(f)
    if changed:
        _write_findings_atomic(updated)
        log(
            f"surface_pending: marked {len(surfaced_fps)} open → surfaced "
            f"({len(open_findings) - len(surfaced_fps)} left pending for next chime)"
        )

    return 0


def compact_findings(max_age_days: int = 7, now: datetime | None = None) -> int:
    """Rewrite findings.jsonl dropping confirmed/dismissed/aged_out entries
    older than ``max_age_days``.

    Active findings (``open`` / ``surfaced``) are always kept regardless of
    age — they still need your attention. Only already-resolved entries get
    compacted away. This is the fix for Ogler's P002-round-two: the findings
    file itself was growing unboundedly even after the dedup dict got its
    TTL sweep.
    """
    findings = _iter_findings_raw()
    if not findings:
        print("(no findings to compact)")
        return 0

    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=max_age_days)
    resolved_states = {"confirmed", "dismissed", "aged_out"}

    kept: list[dict[str, Any]] = []
    dropped = 0
    for f in findings:
        status = f.get("status", "open")
        if status not in resolved_states:
            # open/surfaced — always keep
            kept.append(f)
            continue
        ts = f.get("detected_at", "")
        try:
            detected = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            # Unparseable timestamp — keep it, fail-open
            kept.append(f)
            continue
        if detected >= cutoff:
            kept.append(f)
        else:
            dropped += 1

    if dropped == 0:
        print(
            f"(nothing to compact: {len(findings)} findings, "
            f"none resolved >{max_age_days}d ago)"
        )
        return 0

    _write_findings_atomic(kept)
    log(
        f"compact_findings: dropped {dropped} resolved findings older than {max_age_days}d"
    )
    print(
        f"ok: compacted {dropped} finding(s) older than {max_age_days}d, "
        f"kept {len(kept)}"
    )
    return 0


# ---------------------------------------------------------------------------
# Severity routing
# ---------------------------------------------------------------------------


def escalate(finding: Finding) -> None:
    """Route high/critical findings beyond the findings.jsonl file.

    High findings: logged + surfaced via SessionStart hook (findings.jsonl).
    Critical findings: also stored in governance KG for visibility across agents.
    """
    log(f"ESCALATE {finding.severity.upper()} {finding.fingerprint} {finding.pattern} {finding.file}:{finding.line} — {finding.hint}", "warning")

    if finding.severity != "critical":
        return

    # --- Governance KG discovery ---
    _escalate_to_kg(finding)


def _escalate_to_kg(finding: Finding) -> None:
    """Store a critical finding as a discovery in the governance knowledge graph."""
    from unitares_sdk import SyncGovernanceClient

    summary = f"[Watcher] {finding.pattern}: {finding.hint} ({Path(finding.file).name}:{finding.line})"
    details = (
        f"Pattern: {finding.pattern}\n"
        f"File: {finding.file}:{finding.line}\n"
        f"Hint: {finding.hint}\n"
        f"Fingerprint: {finding.fingerprint}"
    )
    try:
        client = SyncGovernanceClient(rest_url=GOV_REST_URL, transport="rest", timeout=30)
        client.store_discovery(
            summary=summary,
            discovery_type="bug_found",
            severity="critical",
            tags=["watcher", finding.pattern, "critical"],
            details=details,
        )
        log(f"KG discovery stored for {finding.fingerprint}", "info")
    except Exception as e:
        log(f"KG discovery write failed: {e}", "warning")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


_PERSIST_VERB_PATTERN = re.compile(
    r"\bawait\s+\w*(persist|save|store|write|archive|insert|update|commit|flush|sync)\w*\s*\("
)

# Required literal substrings on the flagged line, by pattern id. If a pattern
# is in this map and the substring is missing from the flagged line, the
# finding is dropped as a false positive.
_PATTERN_REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "P001": ("create_task(",),
    "P003": ("UNITARESMonitor(",),
    # P004 needs a literal asyncpg/Redis call marker on the flagged line.
    # Without this, qwen3-coder-next associates the pattern with a nearby
    # `async def http_dashboard(...)` or unrelated arithmetic. Caught when
    # it flagged http_api.py:736 and :907 on 2026-04-14.
    "P004": ("asyncpg", "pool.acquire", "conn.fetch", "conn.execute",
             "db.fetch", "db.execute", "await redis", "redis.get(",
             "redis.set(", "load_metadata_async(", "archive_agent("),
    # P005 needs a literal acquire/cursor call on the flagged line.
    # Without this, the model sometimes associates a P005 "resource leak"
    # finding with the method DEFINITION (async def __aexit__, etc.)
    # instead of the acquire call itself. Caught when qwen3-coder-next
    # flagged postgres_backend.py:199 on 2026-04-11.
    "P005": (".acquire(", ".cursor(", ".connect(", ".lock("),
    "P008": ("shell=True", "os.system(", "subprocess.run(", "subprocess.call("),
    "P012": ("json.loads(", "yaml.load(", "yaml.safe_load("),
    # P016 is about double-envelope dict parsing (`data["success"]`,
    # `data.get("success")`). Pure attribute access on a typed pydantic model
    # (`result.success`, `audit_result.success`) is by construction flat — the
    # schema makes the shape explicit. Requiring a quoted "success" literal
    # drops the typed-attribute false positives while keeping the real shape.
    # Caught when qwen3-coder-next flagged 4 SDK-typed call sites in
    # agents/vigil/agent.py:292,308,318,324 on 2026-04-14.
    "P016": ('"success"', "'success'"),
}

# File-path substrings that MUST be present in finding.file for the pattern
# to apply. P004 (asyncpg-in-MCP-handler) is only relevant to code under
# src/mcp_handlers/ — the pattern library explicitly excludes Starlette REST
# routes in src/http_api.py, which run outside the MCP anyio task group.
_PATTERN_FILE_PATH_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "P004": ("/src/mcp_handlers/",),
}

# Regex: `name = ...create_task(...)` on one line. If this matches the P001
# flagged line, the task reference is stored — not fire-and-forget.
_P001_TASK_ASSIGNMENT = re.compile(r"\b[a-zA-Z_]\w*\s*=\s*[^=].*create_task\(")

# Regex: project's blessed tracked-task wrapper. By construction stores the
# task ref in a tracked set; P001 should not flag call sites of it. The
# required-token check still keeps `create_task(` matches because
# `create_tracked_task` contains the substring `create_task(`. Caught when
# qwen3-coder-next flagged 2 sites in mcp_server_std.py on 2026-04-17.
_P001_TRACKED_HELPER = re.compile(r"\bcreate_tracked_task\s*\(")

# Regex: header line of `def get_or_create_monitor(` — when a P003 flag
# lands inside the body of this function (which IS the cache), the
# "instantiated outside the cache" rule does not apply. Caught when
# qwen3-coder-next flagged agent_lifecycle.py:26 on 2026-04-17.
_P003_CACHE_FUNC_HEADER = re.compile(
    r"^\s*(?:async\s+)?def\s+get_or_create_monitor\s*\("
)
_P003_OTHER_DEF = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(")

# Regex: `getattr(<obj>, "success", ...)` — defensive typed-attribute access.
# By construction this targets a flat object's attribute and cannot mask a
# nested envelope. The quoted "success" satisfies the required-token check,
# so an extra drop rule is needed to handle this shape.
_P016_GETATTR_SUCCESS = re.compile(
    r"""\bgetattr\s*\([^,]+,\s*['"]success['"]"""
)


def _is_inside_get_or_create_monitor(
    flagged_line: int, snippet_lines_by_num: dict[int, str]
) -> bool:
    """Return True if the flagged line sits inside the body of the
    ``def get_or_create_monitor`` function. Walks back through the snippet:
    the first def header we hit decides — if it's our cache function, we're
    inside; if it's any other def at the same/outer indent, we're not.
    """
    for line_no in sorted(snippet_lines_by_num.keys(), reverse=True):
        if line_no >= flagged_line:
            continue
        line = snippet_lines_by_num.get(line_no, "")
        if not line.strip():
            continue
        if _P003_CACHE_FUNC_HEADER.match(line):
            return True
        if _P003_OTHER_DEF.match(line):
            return False
    return False


def _has_preceding_persist_call(
    flagged_line: int, snippet_lines_by_num: dict[int, str], lookback: int = 8
) -> bool:
    """Check if any of the `lookback` lines BEFORE flagged_line contains an
    `await <persist-like>(` call. Used to suppress false-positive P011 hits
    where the mutation correctly comes AFTER the persistence call."""
    for line_no in range(flagged_line - lookback, flagged_line):
        line = snippet_lines_by_num.get(line_no, "")
        if not line or _looks_like_comment(line):
            continue
        if _PERSIST_VERB_PATTERN.search(line):
            return True
    return False


def _verify_finding_against_source(
    finding: Finding, raw_evidence: str, snippet_lines_by_num: dict[int, str]
) -> bool:
    """Drop a finding if it can't be substantiated against actual code.

    Returns True if the finding survives verification.
    """
    # File-path constraint: some patterns only apply under certain paths
    # (e.g. P004 only applies to files under src/mcp_handlers/).
    path_constraints = _PATTERN_FILE_PATH_CONSTRAINTS.get(finding.pattern)
    if path_constraints and not any(seg in finding.file for seg in path_constraints):
        log(
            f"drop {finding.pattern} {finding.file}:{finding.line} — file outside "
            f"required path segments {path_constraints!r}",
            "warning",
        )
        return False
    src_line = snippet_lines_by_num.get(finding.line, "")
    if not src_line:
        log(
            f"drop {finding.pattern} {finding.file}:{finding.line} — line not in scanned region",
            "warning",
        )
        return False
    if _looks_like_comment(src_line):
        log(
            f"drop {finding.pattern} {finding.file}:{finding.line} — flagged line is a comment: {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # Required-token verifier: some patterns must have a literal substring on
    # the flagged line. Without it, the finding is a false positive (model
    # matched the function name or a comment, not the actual code construct).
    required_tokens = _PATTERN_REQUIRED_TOKENS.get(finding.pattern)
    if required_tokens and not any(tok in src_line for tok in required_tokens):
        log(
            f"drop {finding.pattern} {finding.file}:{finding.line} — required token "
            f"{required_tokens!r} not on line: {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # P001 specifically: if the flagged line assigns create_task() to a name,
    # the task reference is stored somewhere (even if not in a set); the
    # pattern's own library note says "assigned to a variable or added to a
    # collection in the same block → NOT fire-and-forget".
    if finding.pattern == "P001" and _P001_TASK_ASSIGNMENT.search(src_line):
        log(
            f"drop P001 {finding.file}:{finding.line} — task ref assigned on flagged line "
            f"(not fire-and-forget): {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # P001 specifically: `create_tracked_task(...)` is the project's blessed
    # wrapper that stores the task ref in a tracked set. Call sites of it
    # are by construction not fire-and-forget.
    if finding.pattern == "P001" and _P001_TRACKED_HELPER.search(src_line):
        log(
            f"drop P001 {finding.file}:{finding.line} — create_tracked_task() "
            f"wrapper stores ref by construction: {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # P003 specifically: if the flagged line is inside the body of
    # get_or_create_monitor itself (the cache function), the
    # "instantiated outside the cache" rule does not apply.
    if finding.pattern == "P003" and _is_inside_get_or_create_monitor(
        finding.line, snippet_lines_by_num
    ):
        log(
            f"drop P003 {finding.file}:{finding.line} — flag lands inside "
            f"get_or_create_monitor body (the cache itself): {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # P016 specifically: `getattr(<obj>, "success", ...)` is defensive typed-
    # attribute access on a flat object — the quoted "success" string is just
    # the attribute name, not a dict key probing a nested envelope.
    if finding.pattern == "P016" and _P016_GETATTR_SUCCESS.search(src_line):
        log(
            f"drop P016 {finding.file}:{finding.line} — getattr-style typed "
            f"attribute access (no nested envelope): {src_line.strip()[:80]}",
            "warning",
        )
        return False
    # P011 specifically: if there's an `await persist|archive|save|...` call in
    # the lines preceding the flagged mutation, the temporal ordering is
    # correct and this is a false positive.
    if finding.pattern == "P011" and _has_preceding_persist_call(
        finding.line, snippet_lines_by_num
    ):
        log(
            f"drop P011 {finding.file}:{finding.line} — preceding persist call found, ordering is correct",
            "warning",
        )
        return False
    if raw_evidence:
        # If the model quoted "evidence", verify it (a) isn't comment-like and
        # (b) actually appears somewhere near the flagged line. We allow ±2
        # lines of slack to forgive minor model line-counting drift.
        if _looks_like_comment(raw_evidence):
            log(
                f"drop {finding.pattern} {finding.file}:{finding.line} — evidence is comment-like: {raw_evidence[:80]}",
                "warning",
            )
            return False
        evidence_norm = raw_evidence.strip()
        nearby = " ".join(
            snippet_lines_by_num.get(finding.line + offset, "")
            for offset in range(-2, 3)
        )
        if evidence_norm and evidence_norm[:40] not in nearby:
            log(
                f"drop {finding.pattern} {finding.file}:{finding.line} — evidence not found near line: {evidence_norm[:80]}",
                "warning",
            )
            return False
    return True


def scan_file(
    file_path: str,
    region: str | None = None,
    persist: bool = True,
) -> list[Finding]:
    """Scan a file and return findings.

    ``persist`` controls whether findings are appended to ``findings.jsonl``
    and whether high/critical severity findings get escalated. The self-test
    harness calls this with ``persist=False`` so synthetic results don't
    pollute the real findings feed.
    """
    _common_trim_log(LOG_FILE, MAX_LOG_LINES)
    skip, reason = should_skip(file_path)
    if skip:
        log(f"skip {file_path}: {reason}")
        return []

    log(f"scan {file_path} region={region or 'head'}")
    try:
        code_snippet, region_start, region_end = read_file_region(file_path, region)
    except (OSError, UnicodeDecodeError) as e:
        log(f"failed to read {file_path}: {e}", "error")
        return []

    # Build a line_number → raw line content lookup so verification can compare
    # findings against the actual source.
    snippet_lines_by_num: dict[int, str] = {}
    for raw in code_snippet.splitlines():
        head, _, rest = raw.partition(":")
        try:
            n = int(head.strip())
        except ValueError:
            continue
        snippet_lines_by_num[n] = rest.lstrip()

    patterns_md = load_patterns()
    prompt = build_prompt(patterns_md, file_path, code_snippet)

    try:
        result = call_model(prompt)
    except Exception as e:
        log(f"model call failed: {e}", "error")
        return []

    parsed = parse_findings(
        result["text"], file_path, result.get("model_used", DEFAULT_MODEL), region_start
    )
    findings: list[Finding] = []
    for f, raw_evidence in parsed:
        if not _verify_finding_against_source(f, raw_evidence, snippet_lines_by_num):
            continue
        # Stamp a content hash onto the finding so its fingerprint encodes
        # WHAT the code looked like, not just where it lived. Fixes the
        # silent-dedup bug where bug B arriving at the same line as fixed
        # bug A would never resurface.
        source_line = snippet_lines_by_num.get(f.line, "")
        f.line_content_hash = hash_line_content(source_line)
        f.fingerprint = f.compute_fingerprint()
        findings.append(f)
    if persist:
        fresh = persist_findings(findings)
    else:
        fresh = findings

    log(
        f"scan complete: {len(findings)} raw, {len(fresh)} new, "
        f"tokens={result.get('tokens_used')}, region=L{region_start}-L{region_end}"
        + ("" if persist else " (persist=False)")
    )

    if persist:
        for f in fresh:
            if f.severity in ("high", "critical"):
                escalate(f)

    return fresh


def review_file(
    file_path: str,
    region: str | None = None,
) -> list[Finding]:
    """Reasoning-based code review — model thinks freely, no pattern library.

    Findings from review mode use pattern ID 'R000' and are printed to stdout
    but NOT persisted to findings.jsonl (they don't have pattern IDs from the
    library, so the dedup/lifecycle machinery doesn't apply).
    """
    _common_trim_log(LOG_FILE, MAX_LOG_LINES)
    skip, reason = should_skip(file_path)
    if skip:
        log(f"skip {file_path}: {reason}")
        return []

    log(f"review {file_path} region={region or 'head'}")
    try:
        code_snippet, region_start, region_end = read_file_region(file_path, region)
    except (OSError, UnicodeDecodeError) as e:
        log(f"failed to read {file_path}: {e}", "error")
        return []

    prompt = build_review_prompt(file_path, code_snippet)

    try:
        result = call_model(prompt, timeout=90)
    except Exception as e:
        log(f"model call failed: {e}", "error")
        return []

    raw_text = result["text"]
    # Parse the JSON — review mode returns a simpler schema
    try:
        # Strip thinking tags if present (qwen3 sometimes wraps in <think>)
        cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON from surrounding text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                log(f"review parse failed: could not extract JSON", "warning")
                return []
        else:
            log(f"review parse failed: no JSON found", "warning")
            return []

    findings = []
    for item in data.get("findings", []):
        line = item.get("line", 0)
        if region_start and isinstance(line, int):
            line = line  # review mode lines are already absolute from the snippet
        f = Finding(
            pattern="R000",
            file=file_path,
            line=int(line),
            hint=str(item.get("hint", ""))[:80],
            severity=item.get("severity", "medium"),
            detected_at=datetime.now(timezone.utc).isoformat(),
            model_used=result.get("model_used", DEFAULT_MODEL),
        )
        findings.append(f)

    log(
        f"review complete: {len(findings)} findings, "
        f"tokens={result.get('tokens_used')}, region=L{region_start}-L{region_end}"
    )
    return findings


SELF_TEST_CODE = """async def stuck_agent_recovery_task(self):
    while self.running:
        stale_ephemerals = await self.fetch_stale_ephemerals()
        for ephemeral in stale_ephemerals:
            monitor = self.create_stuck_monitor(ephemeral)
            asyncio.create_task(monitor.watch())
        await asyncio.sleep(300)
"""


def self_test() -> int:
    """Run the watcher against a synthetic known-buggy file and verify that
    at least one P001 (fire-and-forget) finding comes back."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_selftest.py", delete=False
    ) as tf:
        tf.write(SELF_TEST_CODE)
        tmp_path = tf.name

    try:
        # persist=False so synthetic findings never land in the real
        # findings.jsonl — keeps the self-test entry point safe to run
        # ad-hoc without polluting the live findings feed.
        findings = scan_file(tmp_path, persist=False)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not findings:
        print("SELF-TEST: FAIL — no findings produced")
        return 1

    hit_p001 = any(f.pattern == "P001" for f in findings)
    for f in findings:
        print(
            f"  [{f.severity}] {f.pattern} {f.file}:{f.line} — {f.hint}"
        )
    if hit_p001:
        print(f"SELF-TEST: PASS — got {len(findings)} finding(s), P001 detected")
        return 0
    print(
        f"SELF-TEST: PARTIAL — {len(findings)} finding(s) but no P001; "
        "pattern library may need a stronger hint"
    )
    return 2


def list_findings(only_open: bool = False) -> int:
    findings = _iter_findings_raw()
    if not findings:
        print("(no findings file yet)")
        return 0
    shown = 0
    for d in findings:
        status = d.get("status", "open")
        if only_open and status not in ("open", "surfaced"):
            continue
        fp = d.get("fingerprint", "?")[:8]
        print(
            f"{fp}  {status:9s} {d.get('severity','?'):8s} {d.get('pattern','?'):6s} "
            f"{d.get('file','?')}:{d.get('line','?')} — {d.get('hint','')}"
        )
        shown += 1
    if shown == 0:
        print("(nothing to show)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="UNITARES Watcher bug-pattern agent")
    parser.add_argument("--file", help="file to scan")
    parser.add_argument("--region", help="line range within file, e.g. L10-L40")
    parser.add_argument(
        "--review", action="store_true",
        help="reasoning-based review (no pattern library, model thinks freely)",
    )
    parser.add_argument(
        "--self-test", action="store_true", help="scan a synthetic buggy file and verify"
    )
    parser.add_argument(
        "--list-findings", action="store_true", help="dump current findings.jsonl"
    )
    parser.add_argument(
        "--only-open",
        action="store_true",
        help="with --list-findings, show only open/surfaced entries",
    )
    parser.add_argument(
        "--resolve",
        metavar="FINGERPRINT",
        help="mark a finding as confirmed by fingerprint (or unique prefix, min 4 chars)",
    )
    parser.add_argument(
        "--dismiss",
        metavar="FINGERPRINT",
        help="mark a finding as dismissed (false positive) by fingerprint",
    )
    parser.add_argument(
        "--sweep-stale",
        action="store_true",
        help="drop findings whose target file no longer exists on disk",
    )
    parser.add_argument(
        "--agent-id",
        metavar="UUID",
        help="governance UUID of the agent resolving/dismissing (for audit trail)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="drop resolved/dismissed/aged_out findings older than the TTL",
    )
    parser.add_argument(
        "--compact-days",
        type=int,
        default=7,
        help="age cutoff for --compact (default: 7 days)",
    )
    parser.add_argument(
        "--print-unresolved",
        action="store_true",
        help="print the unresolved-findings block (open+surfaced) without mutating state",
    )
    parser.add_argument(
        "--surface-pending",
        action="store_true",
        help="print open findings as a chime block and transition them to surfaced",
    )
    args = parser.parse_args()

    # --- Identity resolution (best-effort) ---
    try:
        client = _make_identity_client()
        resolve_identity(client)
    except Exception as e:
        log(f"identity resolution skipped: {e}", "warning")

    if args.self_test:
        return self_test()
    if args.list_findings:
        return list_findings(only_open=args.only_open)
    if args.resolve:
        return update_finding_status(args.resolve, "confirmed", resolver_agent_id=args.agent_id)
    if args.dismiss:
        return update_finding_status(args.dismiss, "dismissed", resolver_agent_id=args.agent_id)
    if args.sweep_stale:
        return sweep_stale_findings()
    if args.compact:
        return compact_findings(max_age_days=args.compact_days)
    if args.print_unresolved:
        return print_unresolved()
    if args.surface_pending:
        return surface_pending()
    if not args.file:
        parser.print_help()
        return 1

    if args.review:
        findings = review_file(args.file, args.region)
        if findings:
            for f in findings:
                print(f"[{f.severity}] {f.file}:{f.line} — {f.hint}")
        else:
            print("No issues found.")
        return 0

    fresh = scan_file(args.file, args.region)
    if fresh:
        for f in fresh:
            print(
                f"[{f.severity}] {f.pattern} {f.file}:{f.line} — {f.hint}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
