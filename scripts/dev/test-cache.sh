#!/usr/bin/env bash
# test-cache.sh — tree-hash pytest cache
#
# Hashes all tracked Python files in src/, tests/, agents/.
# If tests already passed against this exact tree state, prints
# the cached summary and exits 0 without re-running pytest.
#
# Usage:
#   ./scripts/dev/test-cache.sh              # default: pytest tests/ agents/ -q --tb=short -x
#   ./scripts/dev/test-cache.sh --fresh      # ignore cache, force run
#   ./scripts/dev/test-cache.sh -- -k "test_foo"  # extra pytest args after --

set -euo pipefail

CACHE_DIR=".test-cache"
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

# --- parse args ---
FRESH=false
PYTEST_EXTRA=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh) FRESH=true; shift ;;
        --)      shift; PYTEST_EXTRA=("$@"); break ;;
        *)       PYTEST_EXTRA+=("$1"); shift ;;
    esac
done

# --- compute tree hash ---
TREE_HASH=$(git ls-files -- 'src/*.py' 'tests/*.py' 'agents/*.py' | sort | xargs cat | shasum -a 256 | cut -d' ' -f1)
CACHE_FILE="$CACHE_DIR/$TREE_HASH"

# --- cache hit ---
if [[ "$FRESH" == false && -f "$CACHE_FILE" ]]; then
    AGE_SECS=$(( $(date +%s) - $(stat -f %m "$CACHE_FILE") ))
    AGE_MIN=$(( AGE_SECS / 60 ))
    echo "[test-cache] HIT — tree $TREE_HASH (cached ${AGE_MIN}m ago)"
    cat "$CACHE_FILE"
    exit 0
fi

# --- cache miss: run pytest ---
mkdir -p "$CACHE_DIR"
echo "[test-cache] MISS — tree $TREE_HASH, running pytest..."

# Use framework Python (has pytest + project deps installed)
PYTHON="${UNITARES_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3}"
PYTEST_CMD=("$PYTHON" -m pytest tests/ agents/ -q --tb=short -x ${PYTEST_EXTRA[@]+"${PYTEST_EXTRA[@]}"})
TMPOUT=$(mktemp)
set +e
"${PYTEST_CMD[@]}" 2>&1 | tee "$TMPOUT"
EXIT_CODE=${PIPESTATUS[0]}
set -e

if [[ $EXIT_CODE -eq 0 ]]; then
    # cache only passing results — tail gives the summary line
    tail -5 "$TMPOUT" > "$CACHE_FILE"
    echo "[test-cache] CACHED — tree $TREE_HASH"
else
    echo "[test-cache] FAILED (exit $EXIT_CODE) — not cached"
fi

rm -f "$TMPOUT"

# prune old entries (keep last 20)
ENTRIES=$(ls -t "$CACHE_DIR"/ 2>/dev/null | tail -n +21)
if [[ -n "$ENTRIES" ]]; then
    echo "$ENTRIES" | while read -r f; do rm -f "$CACHE_DIR/$f"; done
fi

exit "$EXIT_CODE"
