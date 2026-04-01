#!/usr/bin/env python3
"""Check documentation health: dead refs, ghost tools, hardcoded IPs/counts.

Usage:
    python3 scripts/diagnostics/check_doc_health.py [--strict]

Exit codes:
    0 — no warnings (or warnings only in non-strict mode)
    1 — warnings found (strict mode only)
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories to skip when scanning .md files
SKIP_DIRS = {".git", ".venv", "venv", ".pytest_cache", "node_modules",
             ".claude", "archive", "__pycache__", ".hypothesis",
             ".agent-guides", "plans", "superpowers"}

# Files to skip (historical records — dead refs are expected)
SKIP_FILES = {"CHANGELOG.md"}

# --- Check 1: Dead file references ---

# Patterns that look like file paths in docs
_PATH_PATTERNS = [
    # Backtick-quoted paths: `src/foo.py`, `config/bar.py`
    re.compile(r'`((?:src|config|scripts|docs|db|dashboard)/[^`\s]+)`'),
    # Markdown links: [text](path/to/file)
    re.compile(r'\]\(((?:src|config|scripts|docs|db|dashboard)/[^\)#\s]+)\)'),
]


def check_dead_refs(md_files: list[Path]) -> list[str]:
    warnings = []
    seen = set()
    for fpath in md_files:
        for i, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
            for pat in _PATH_PATTERNS:
                for match in pat.finditer(line):
                    ref = match.group(1).rstrip(".,;:)")
                    if ref in seen:
                        continue
                    seen.add(ref)
                    # Skip wildcards, placeholders, and example paths
                    if any(c in ref for c in "*<>{}"):
                        continue
                    if "/foo" in ref or "YYYY" in ref:
                        continue
                    # Check if file or directory exists
                    candidate = REPO_ROOT / ref
                    if not candidate.exists():
                        rel = fpath.relative_to(REPO_ROOT)
                        warnings.append(f"  {rel}:{i}: dead ref `{ref}`")
    return warnings


# --- Check 2: Ghost tools ---

def _load_tool_names() -> set[str]:
    """Load canonical tool names from this repo's registry."""
    names = set()

    # Try governance-mcp: TOOL_ORDER in src/tool_schemas.py
    schemas = REPO_ROOT / "src" / "tool_schemas.py"
    if schemas.exists():
        for m in re.finditer(r'"(\w+)"', schemas.read_text()):
            names.add(m.group(1))

    # Try governance-mcp: aliases from tool_stability.py
    stability = REPO_ROOT / "src" / "mcp_handlers" / "tool_stability.py"
    if stability.exists():
        text = stability.read_text()
        for m in re.finditer(r'"(\w+)":\s*ToolAlias', text):
            names.add(m.group(1))

    # Try anima-mcp: HANDLERS dict in tool_registry.py
    registry = REPO_ROOT / "src" / "anima_mcp" / "tool_registry.py"
    if registry.exists():
        text = registry.read_text()
        for m in re.finditer(r'"(\w+)":\s*handle_', text):
            names.add(m.group(1))

    return names


# Common words and internal functions that appear in backticks but aren't MCP tools
_TOOL_ALLOWLIST = {
    "master", "main", "true", "false", "null", "none", "ok",
    "proceed", "guide", "pause", "reject",  # verdict names
    "open", "resolved", "archived",  # status names
    "convergent", "divergent", "mixed",  # task types
    "note", "insight", "bug_found", "improvement", "analysis", "pattern",  # discovery types
    "comfortable", "tight", "critical",  # margin levels
    "high", "low", "boundary",  # basin names
    "postgres", "redis", "age", "docker",  # infra
    "smoke", "pytest",  # test
    "export",  # consolidated tool (registered as action, not standalone)
}

# Files/dirs where ghost tool warnings are noise (plans, specs, internal docs)
_GHOST_SKIP_DIRS = {"plans", "superpowers", "specs"}


def check_ghost_tools(md_files: list[Path], tool_names: set[str]) -> list[str]:
    if not tool_names:
        return []  # Can't validate without a registry

    warnings = []
    # Match backtick-quoted identifiers that look like MCP tool calls: `foo()`
    # Only check function-call patterns, not arbitrary backtick-quoted words
    pat = re.compile(r'`(\w+)\(\)`')
    seen = set()

    for fpath in md_files:
        # Skip plans/specs — they reference hypothetical code
        rel = fpath.relative_to(REPO_ROOT)
        if any(d in rel.parts for d in _GHOST_SKIP_DIRS):
            continue
        for i, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
            for match in pat.finditer(line):
                name = match.group(1)
                if not name or name in seen:
                    continue
                if name in tool_names or name in _TOOL_ALLOWLIST:
                    continue
                if name.startswith(("pi_", "mcp_", "_")):
                    # pi_ = proxy tools, _private = internal functions
                    continue
                seen.add(name)
                warnings.append(f"  {rel}:{i}: possible ghost tool `{name}`")
    return warnings


# --- Check 3: Hardcoded Tailscale IPs ---

_IP_PATTERN = re.compile(r'100\.\d{1,3}\.\d{1,3}\.\d{1,3}')


def check_hardcoded_ips(md_files: list[Path]) -> list[str]:
    warnings = []
    seen = set()
    for fpath in md_files:
        for i, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
            for match in _IP_PATTERN.finditer(line):
                ip = match.group(0)
                key = (fpath, ip)
                if key in seen:
                    continue
                seen.add(key)
                # Skip if it's already a placeholder instruction
                if "tailscale status" in line.lower() or "<tailscale-ip>" in line:
                    continue
                rel = fpath.relative_to(REPO_ROOT)
                warnings.append(f"  {rel}:{i}: hardcoded Tailscale IP {ip}")
    return warnings


# --- Check 4: Hardcoded counts ---

_COUNT_PATTERN = re.compile(
    r'\d{1,2},\d{3}\+?\s*(?:tests|agents|discoveries|identities|awakenings|check-ins|entries|edges)',
    re.IGNORECASE,
)


def check_hardcoded_counts(md_files: list[Path]) -> list[str]:
    warnings = []
    for fpath in md_files:
        for i, line in enumerate(fpath.read_text(errors="replace").splitlines(), 1):
            for match in _COUNT_PATTERN.finditer(line):
                rel = fpath.relative_to(REPO_ROOT)
                warnings.append(f"  {rel}:{i}: hardcoded count \"{match.group(0)}\"")
    return warnings


# --- Main ---

def collect_md_files() -> list[Path]:
    md_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md") and f not in SKIP_FILES:
                md_files.append(Path(root) / f)
    return sorted(md_files)


def main():
    strict = "--strict" in sys.argv
    md_files = collect_md_files()
    tool_names = _load_tool_names()

    all_warnings = []

    dead = check_dead_refs(md_files)
    if dead:
        all_warnings.append(("Dead file references", dead))

    ghosts = check_ghost_tools(md_files, tool_names)
    if ghosts:
        all_warnings.append(("Possible ghost tools", ghosts))

    ips = check_hardcoded_ips(md_files)
    if ips:
        all_warnings.append(("Hardcoded Tailscale IPs", ips))

    counts = check_hardcoded_counts(md_files)
    if counts:
        all_warnings.append(("Hardcoded counts (will go stale)", counts))

    if not all_warnings:
        print("📄 Doc health: all clear")
        return 0

    total = sum(len(w) for _, w in all_warnings)
    print(f"📄 Doc health: {total} warning(s)")
    for category, items in all_warnings:
        print(f"\n  {category}:")
        for item in items:
            print(item)
    print()

    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
