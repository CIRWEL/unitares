"""Finding model, persistence, dedup, lifecycle, surfacing, compaction,
escalation.

Split out of agent.py so the file stayed navigable. Identity, scanning, and
CLI orchestration remain in agent.py. ``surface_pending`` also stays there
because it calls ``_do_checkin`` from the identity block; everything else
that touches findings.jsonl / dedup.json lives here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents.common.findings import post_finding
from agents.watcher._util import (
    PROJECT_ROOT,
    hash_line_content,
    log,
    repo_relative_path,
)

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------

STATE_DIR = PROJECT_ROOT / "data" / "watcher"
FINDINGS_FILE = STATE_DIR / "findings.jsonl"
DEDUP_FILE = STATE_DIR / "dedup.json"

GOV_REST_URL = "http://localhost:8767/v1/tools/call"

# Age findings out after this many days
FINDINGS_TTL_DAYS = 14

VALID_FINDING_STATUSES = ("open", "surfaced", "confirmed", "dismissed", "aged_out")
MIN_FINGERPRINT_PREFIX = 4  # users can type the first N chars instead of all 16


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


# ---------------------------------------------------------------------------
# Dedup (data/watcher/dedup.json)
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


# ---------------------------------------------------------------------------
# Persistence (data/watcher/findings.jsonl)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lifecycle commands
#
# Without these, findings.jsonl is append-only with no way to mark a finding
# as confirmed, dismissed, or stale. Governance has no calibration signal and
# the surface hook just accumulates noise. Ogler's critique of the rollup
# daemon was specifically "build the bottom before the top" — this is the
# bottom.
# ---------------------------------------------------------------------------


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


_STATUS_TIMESTAMP_FIELD = {
    "confirmed": "confirmed_at",
    "dismissed": "dismissed_at",
    "aged_out": "aged_out_at",
}


def update_finding_status(
    fingerprint_prefix: str,
    new_status: str,
    resolver_agent_id: str | None = None,
    reason: str | None = None,
) -> int:
    """Mark a finding as ``new_status`` by fingerprint prefix.

    Writes a status-transition timestamp (``confirmed_at``/``dismissed_at``/
    ``aged_out_at``) and, when supplied, ``resolved_by`` + ``resolution_reason``
    so the dashboard timeline and audit trail have the data they need — the
    prior implementation only mutated ``status`` and the timeline series were
    always zero as a result.

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
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    timestamp_field = _STATUS_TIMESTAMP_FIELD.get(new_status)

    updated: list[dict[str, Any]] = []
    for f in findings:
        if f.get("fingerprint") == target_fp:
            merged = {**f, "status": new_status}
            if timestamp_field:
                merged[timestamp_field] = now_iso
            if resolver_agent_id:
                merged["resolved_by"] = resolver_agent_id
            if reason:
                merged["resolution_reason"] = reason
            f = merged
        updated.append(f)
    _write_findings_atomic(updated)
    log(f"update_finding_status: {target_fp[:8]} → {new_status}")
    print(
        f"ok: {target_fp[:16]} → {new_status} "
        f"({matches[0].get('pattern','?')} at {matches[0].get('file','?')}:{matches[0].get('line','?')})"
    )

    # --- Post resolution event to governance ---
    if new_status in ("confirmed", "dismissed"):
        # Lazy import: _post_resolution_event needs get_watcher_identity
        # from agent.py's identity block. Top-level import would be circular.
        from agents.watcher.agent import _post_resolution_event
        _post_resolution_event(matches[0], new_status, resolver_agent_id, reason=reason)

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
#   UserPromptSubmit → --surface-pending (chime mode, in agent.py because
#     it also triggers a governance check-in; it reuses _format_findings_block
#     and _write_findings_atomic from here)
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
