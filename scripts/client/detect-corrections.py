#!/usr/bin/env python3
"""
Detect repeated user corrections across Claude Code sessions.

Parses ~/.claude/history.jsonl for correction signals (e.g. "that's wrong",
"I've told you", "how many times"), extracts topic keywords, groups by topic
across sessions, and reports severity.

Usage:
    python3 detect-corrections.py [--days N] [--min-sessions N] [--verbose]
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Correction signal patterns (regex, case-insensitive)
# ---------------------------------------------------------------------------
CORRECTION_PATTERNS = [
    # Direct corrections
    r"that'?s (?:wrong|incorrect|not (?:right|correct|true|accurate))",
    r"no,?\s+(?:it'?s|that'?s|the)",
    r"(?:actually|wrong)[,.]?\s+(?:it|the|that)",
    r"(?:i(?:'ve| have)) (?:already |just )?(?:told|said|explained|corrected|mentioned)",
    r"how many times",
    r"stop (?:saying|claiming|reporting|telling|repeating)",
    r"(?:i keep|you keep) (?:telling|saying|getting|having to)",
    r"(?:not|never|don'?t)\s+(?:say|claim|report|assume)\s+that",
    r"please (?:stop|don'?t|do not) (?:say|claim|report|assume)",
    # Frustration signals
    r"again\??\s*(?:i|we|this)",
    r"(?:still|again) (?:wrong|incorrect|broken|stale)",
    r"(?:for the \w+ time|once more|yet again)",
    r"did(?:n'?t| not) (?:i|we) (?:just|already)",
    # Explicit correction references
    r"(?:the|that) (?:doc|documentation|skill|file) (?:is|says|claims|states)\s+(?:wrong|stale|outdated|incorrect)",
    r"(?:update|fix|correct)\s+(?:the|that)\s+(?:doc|documentation|skill|claim)",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in CORRECTION_PATTERNS]

# ---------------------------------------------------------------------------
# Topic keyword extraction
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS = {
    "calibration": ["calibration", "calibrate", "ground truth", "ground_truth", "auto_ground_truth"],
    "coherence": ["coherence", "coherence range", "0.45", "0.55", "C(V", "thermodynamic"],
    "identity": ["identity", "uuid", "agent_id", "session binding", "bind_session"],
    "eisv": ["eisv", "energy", "entropy", "void", "information integrity"],
    "thresholds": ["threshold", "critical", "0.40", "risk_threshold"],
    "database": ["database", "postgres", "postgresql", "AGE", "pool", "connection"],
    "knowledge-graph": ["knowledge graph", "discovery", "leave_note", "search_knowledge"],
    "dialectic": ["dialectic", "thesis", "antithesis", "synthesis", "pause verdict"],
    "deployment": ["deploy", "pi", "lumen", "anima", "reflash", "restore"],
    "mcp": ["mcp", "tool call", "mcp_server", "handler"],
    "skill-docs": ["skill", "SKILL.md", "documentation", "stale doc", "outdated"],
}


def extract_topics(text: str) -> list[str]:
    """Extract topic keywords from a correction message."""
    text_lower = text.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                found.append(topic)
                break
    return found if found else ["unknown"]


def is_correction(text: str) -> bool:
    """Check if a message matches correction patterns."""
    return any(p.search(text) for p in COMPILED_PATTERNS)


def load_history(history_path: Path, since: datetime) -> list[dict]:
    """Load and filter history entries."""
    entries = []
    if not history_path.exists():
        return entries
    with open(history_path) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            ts = entry.get("timestamp", 0)
            if ts > 0:
                entry_time = datetime.fromtimestamp(ts / 1000)
                if entry_time >= since:
                    entry["_datetime"] = entry_time
                    entries.append(entry)
    return entries


def analyze_corrections(entries: list[dict], verbose: bool = False) -> dict:
    """Find corrections grouped by topic and session."""
    # topic -> {session_id -> [messages]}
    corrections: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for entry in entries:
        text = entry.get("display", "")
        if not text or len(text) < 10:
            continue
        if not is_correction(text):
            continue

        session_id = entry.get("sessionId", "unknown")
        topics = extract_topics(text)

        for topic in topics:
            corrections[topic][session_id].append({
                "text": text[:200],
                "time": entry["_datetime"].isoformat(),
            })

    # Build summary
    summary = {}
    for topic, sessions in corrections.items():
        session_count = len(sessions)
        total_corrections = sum(len(msgs) for msgs in sessions.values())

        # Calculate date range
        all_times = []
        for msgs in sessions.values():
            all_times.extend(m["time"] for m in msgs)
        all_times.sort()

        if session_count >= 4:
            severity = "HIGH"
        elif session_count >= 2:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        summary[topic] = {
            "severity": severity,
            "sessions": session_count,
            "total_corrections": total_corrections,
            "date_range": f"{all_times[0][:10]} to {all_times[-1][:10]}" if all_times else "unknown",
            "examples": [],
        }

        if verbose:
            for sid, msgs in list(sessions.items())[:3]:
                for m in msgs[:2]:
                    summary[topic]["examples"].append(m["text"])

    return summary


def print_report(summary: dict):
    """Print the correction report."""
    if not summary:
        print("No correction patterns found.")
        return

    # Sort by severity
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_topics = sorted(summary.items(), key=lambda x: (severity_order[x[1]["severity"]], -x[1]["sessions"]))

    RED = "\033[0;31m"
    YELLOW = "\033[0;33m"
    GREEN = "\033[0;32m"
    NC = "\033[0m"

    colors = {"HIGH": RED, "MEDIUM": YELLOW, "LOW": GREEN}

    for severity_label in ["HIGH", "MEDIUM", "LOW"]:
        items = [(t, s) for t, s in sorted_topics if s["severity"] == severity_label]
        if not items:
            continue

        color = colors[severity_label]
        threshold = {"HIGH": "4+", "MEDIUM": "2-3", "LOW": "1"}.get(severity_label, "")
        print(f"\n{color}{severity_label} SEVERITY ({threshold} sessions):{NC}")

        for topic, data in items:
            print(f"  Topic: {topic} — {data['sessions']} sessions over {data['date_range']}")
            print(f"    Total correction signals: {data['total_corrections']}")

            # Suggest action
            if topic != "unknown":
                skill_map = {
                    "calibration": "governance-fundamentals",
                    "coherence": "governance-fundamentals",
                    "eisv": "governance-fundamentals",
                    "thresholds": "governance-fundamentals",
                    "identity": "governance-lifecycle",
                    "dialectic": "dialectic-reasoning",
                    "knowledge-graph": "knowledge-graph",
                    "deployment": "discord-bridge",
                }
                suggested_skill = skill_map.get(topic, "governance-fundamentals")
                print(f"    Suggested: Review {suggested_skill}/SKILL.md {topic} section")

            if data.get("examples"):
                print(f"    Examples:")
                for ex in data["examples"][:3]:
                    print(f"      - \"{ex}\"")


def main():
    parser = argparse.ArgumentParser(description="Detect repeated user corrections in Claude Code history")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--min-sessions", type=int, default=1, help="Minimum sessions to report (default: 1)")
    parser.add_argument("--verbose", action="store_true", help="Show example messages")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--history", type=str, default=None, help="Path to history.jsonl (default: ~/.claude/history.jsonl)")
    args = parser.parse_args()

    history_path = Path(args.history) if args.history else Path.home() / ".claude" / "history.jsonl"
    since = datetime.now() - timedelta(days=args.days)

    entries = load_history(history_path, since)
    if not entries:
        print(f"No history entries found in the last {args.days} days.")
        sys.exit(0)

    print(f"Scanning {len(entries)} messages from the last {args.days} days...")

    summary = analyze_corrections(entries, verbose=args.verbose)

    # Filter by min sessions
    summary = {k: v for k, v in summary.items() if v["sessions"] >= args.min_sessions}

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_report(summary)


if __name__ == "__main__":
    main()
