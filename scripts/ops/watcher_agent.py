#!/usr/bin/env python3
"""
Watcher — Independent Bug-Pattern Observer

A non-blocking agent that scans recently edited code for known-bad patterns
using a local LLM (gemma4 via Ollama, routed through governance call_model).
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
    1. Load pattern library (scripts/ops/watcher_patterns.md)
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
    - No agent_id passed to call_model → skips the governance DB path → no
      anyio deadlock (see anyio-deadlock.md).
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
PATTERNS_FILE = PROJECT_ROOT / "scripts" / "ops" / "watcher_patterns.md"
STATE_DIR = PROJECT_ROOT / "data" / "watcher"
FINDINGS_FILE = STATE_DIR / "findings.jsonl"
DEDUP_FILE = STATE_DIR / "dedup.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "unitares-watcher.log"

GOV_REST_URL = "http://localhost:8767/v1/tools/call"
OLLAMA_FALLBACK_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_MODEL = "gemma4:latest"
DEFAULT_TIMEOUT = 45

# How many lines of context to include around an edit when no explicit region
# is given
DEFAULT_CONTEXT_LINES = 200

# Age findings out after this many days
FINDINGS_TTL_DAYS = 14

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

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """Stable identifier combining pattern, file, line, and (optionally)
        a content hash. Callers that want content-aware dedup should set
        ``line_content_hash`` BEFORE invoking this and then assign the
        result back to ``fingerprint``.
        """
        key = f"{self.pattern}|{self.file}|{self.line}|{self.line_content_hash}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


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


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


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
        - No `agent_id` passed → skips the governance DB path → no anyio deadlock.
        - If the governance server is down, the caller should catch the exception
          and fall back to Ollama direct.
    """
    body = json.dumps(
        {
            "name": "call_model",
            "arguments": {
                "prompt": prompt,
                "provider": "ollama",
                "model": model,
                "max_tokens": 2048,
                "temperature": 0.1,
            },
        }
    ).encode()

    req = urllib.request.Request(
        GOV_REST_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    if not data.get("success"):
        raise RuntimeError(f"call_model reported failure: {data}")
    result = data.get("result", {})
    return {
        "text": result.get("response", "") or "",
        "model_used": result.get("model_used", model),
        "tokens_used": result.get("tokens_used", 0),
    }


def call_ollama_direct(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    """Fallback: call Ollama's OpenAI-compatible endpoint directly."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.1,
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
    except (urllib.error.URLError, RuntimeError, TimeoutError, json.JSONDecodeError) as e:
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
            with FINDINGS_FILE.open("a") as fh:
                for f in fresh:
                    fh.write(json.dumps(asdict(f)) + "\n")
        save_dedup(dedup)

    return fresh


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


def update_finding_status(fingerprint_prefix: str, new_status: str) -> int:
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
    return 0


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

    For now this only logs; Lumen voice / KG discovery wiring is a follow-up.
    The file-based surfacing happens automatically via the SessionStart hook
    reading findings.jsonl.
    """
    log(f"ESCALATE {finding.severity.upper()} {finding.fingerprint} {finding.pattern} {finding.file}:{finding.line} — {finding.hint}", "warning")
    # TODO: for severity=="critical", call anima MCP say() and gov KG discovery write
    # Left as a follow-up so the first deploy stays minimal and testable.


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
    "P008": ("shell=True", "os.system(", "subprocess.run(", "subprocess.call("),
    "P012": ("json.loads(", "yaml.load(", "yaml.safe_load("),
}


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
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.list_findings:
        return list_findings(only_open=args.only_open)
    if args.resolve:
        return update_finding_status(args.resolve, "confirmed")
    if args.dismiss:
        return update_finding_status(args.dismiss, "dismissed")
    if args.sweep_stale:
        return sweep_stale_findings()
    if args.compact:
        return compact_findings(max_age_days=args.compact_days)
    if not args.file:
        parser.print_help()
        return 1

    fresh = scan_file(args.file, args.region)
    if fresh:
        for f in fresh:
            print(
                f"[{f.severity}] {f.pattern} {f.file}:{f.line} — {f.hint}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
