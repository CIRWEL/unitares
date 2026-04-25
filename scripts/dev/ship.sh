#!/usr/bin/env bash
# ship.sh — agent-friendly commit-and-deliver
#
# Routes changes to the right delivery path based on what they touch:
#   - Runtime code (agents/, src/mcp_handlers/, src/mcp_server*, src/core.py,
#     src/background_tasks.py) → feature branch + PR + auto-merge-on-green.
#   - Everything else → direct commit + push on the current branch.
#
# The split exists because multiple agents push to this repo concurrently.
# Runtime changes need a rollback artifact (the PR) and cross-agent
# visibility; docs/tests/helpers don't, and PR friction for every tiny
# edit would slow the fleet down.
#
# Usage:
#   ./scripts/dev/ship.sh "commit message"
#   ./scripts/dev/ship.sh --classify          # just print "runtime" or "other"
#
# Requirements: staged changes (git add already done), gh CLI authed.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

RUNTIME_PATTERNS=(
    '^agents/'
    '^src/mcp_handlers/'
    '^src/mcp_server'
    '^src/core\.py$'
    '^src/background_tasks\.py$'
)

classify() {
    local files; files=$(git diff --cached --name-only)
    if [[ -z "$files" ]]; then
        echo "empty"; return
    fi
    while IFS= read -r f; do
        for pat in "${RUNTIME_PATTERNS[@]}"; do
            if [[ "$f" =~ $pat ]]; then
                echo "runtime"; return
            fi
        done
    done <<< "$files"
    echo "other"
}

if [[ "${1:-}" == "--classify" ]]; then
    classify
    exit 0
fi

MESSAGE="${1:-}"
if [[ -z "$MESSAGE" ]]; then
    echo "usage: ship.sh \"commit message\"" >&2
    exit 2
fi

KIND=$(classify)
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# S15-d gate: if this commit touches skills/, the plugin's mirror must be
# in sync with unitares canonical. Fires only when skills/ is staged AND the
# plugin checkout is reachable (script no-ops on operators without it).
if git diff --cached --name-only | grep -q '^skills/'; then
    if ! "$PROJECT_ROOT/scripts/dev/sync-plugin-skills.sh" --check; then
        echo
        echo "[ship] skills/ staged but plugin bundle is out of sync." >&2
        echo "[ship] run: ./scripts/dev/sync-plugin-skills.sh" >&2
        echo "[ship] then commit the plugin-side mirror update before shipping the unitares-side change." >&2
        exit 1
    fi
fi

case "$KIND" in
    empty)
        echo "nothing staged — stage files with 'git add' first" >&2
        exit 2 ;;
    runtime)
        SLUG=$(printf '%s' "$MESSAGE" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)
        # Agent-scoped prefix so concurrent agents' auto-branches are self-identifying.
        # Override with UNITARES_SHIP_AGENT=<name>; otherwise detect from env.
        AGENT_PREFIX="${UNITARES_SHIP_AGENT:-}"
        if [[ -z "$AGENT_PREFIX" ]]; then
            if [[ -n "${CLAUDECODE:-}" ]]; then
                AGENT_PREFIX="claude"
            else
                AGENT_PREFIX="codex"
            fi
        fi
        NEW_BRANCH="${AGENT_PREFIX}/auto/$(date +%Y%m%d-%H%M%S)-${SLUG}"
        echo "[ship] runtime path → $NEW_BRANCH (PR + auto-merge)"
        git checkout -b "$NEW_BRANCH"
        git commit -m "$MESSAGE"
        git push -u origin "$NEW_BRANCH"
        PR_URL=$(gh pr create --title "$MESSAGE" --body "Auto-shipped by ship.sh — runtime path. Auto-merge is enabled; CI gate applies.")
        echo "$PR_URL"
        gh pr merge --auto --squash "$PR_URL" || \
            echo "[ship] auto-merge not enabled (branch protection may require manual setup); PR is open"
        ;;
    other)
        echo "[ship] non-runtime → direct commit + push on $BRANCH"
        git commit -m "$MESSAGE"
        # Push to the same-name branch on origin, not whatever upstream tracks
        # (a feature branch may track master and would otherwise push ambiguously).
        git push origin "HEAD:$BRANCH"
        ;;
esac
