#!/usr/bin/env bash
# Enforce that the SHARED CONTRACT block is byte-identical in AGENTS.md and CLAUDE.md.
#
# The two root bootstrap files are adapter-specific preambles over a common
# contract. The contract section is delimited by HTML comment markers:
#
#   <!-- BEGIN SHARED CONTRACT ... -->
#   ...
#   <!-- END SHARED CONTRACT -->
#
# This script extracts that block from each file and fails if they differ
# or if either file is missing the markers. Wire it into CI or run it
# manually before committing any edit to AGENTS.md or CLAUDE.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENTS="$REPO_ROOT/AGENTS.md"
CLAUDE="$REPO_ROOT/CLAUDE.md"

for f in "$AGENTS" "$CLAUDE"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: missing required file: $f" >&2
        exit 1
    fi
done

extract() {
    # Print inclusive range between BEGIN and END markers.
    awk '/<!-- BEGIN SHARED CONTRACT/{flag=1} flag; /<!-- END SHARED CONTRACT/{flag=0}' "$1"
}

agents_block="$(extract "$AGENTS")"
claude_block="$(extract "$CLAUDE")"

if [[ -z "$agents_block" ]]; then
    echo "ERROR: SHARED CONTRACT markers missing in AGENTS.md" >&2
    exit 1
fi
if [[ -z "$claude_block" ]]; then
    echo "ERROR: SHARED CONTRACT markers missing in CLAUDE.md" >&2
    exit 1
fi

if [[ "$agents_block" != "$claude_block" ]]; then
    echo "ERROR: SHARED CONTRACT block has drifted between AGENTS.md and CLAUDE.md" >&2
    echo "       Edit shared rules in both files or revert one." >&2
    echo >&2
    diff -u <(printf '%s\n' "$claude_block") <(printf '%s\n' "$agents_block") >&2 || true
    exit 1
fi

echo "SHARED CONTRACT: in sync ($(printf '%s\n' "$agents_block" | wc -l | tr -d ' ') lines)"
