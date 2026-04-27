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

# Portable mtime in epoch seconds (macOS `stat -f` is not GNU `stat -c`)
_cache_mtime() {
  python3 -c 'import os, sys; print(int(os.path.getmtime(sys.argv[1])))' "$1"
}

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

# --- cache hit (fast path, no lock) ---
if [[ "$FRESH" == false && -f "$CACHE_FILE" ]]; then
    AGE_SECS=$(( $(date +%s) - $(_cache_mtime "$CACHE_FILE") ))
    AGE_MIN=$(( AGE_SECS / 60 ))
    echo "[test-cache] HIT — tree $TREE_HASH (cached ${AGE_MIN}m ago)"
    cat "$CACHE_FILE"
    exit 0
fi

# --- acquire cross-invocation lock before running pytest ---
#
# Without this, two concurrent test-cache.sh callers (pre-commit hook
# firing while an agent's auto-test hook has already started a run, or
# two agents hitting the script from different sessions) both enter the
# miss path and spawn parallel pytests that hammer Postgres/Redis and
# leave ghost/zombie children. macOS has no native flock(1); use atomic
# mkdir as the lock primitive and record the holder PID so stale locks
# from killed holders can be reclaimed.
LOCK_DIR="/tmp/unitares-test-cache.lock"
LOCK_HOLDER="$LOCK_DIR/holder.pid"
LOCK_WAIT_MAX=600   # seconds
LOCK_WAITED=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    HOLDER_PID="$(cat "$LOCK_HOLDER" 2>/dev/null || echo "")"
    if [[ -n "$HOLDER_PID" ]] && ! kill -0 "$HOLDER_PID" 2>/dev/null; then
        echo "[test-cache] reclaiming stale lock from dead pid $HOLDER_PID"
        rm -rf "$LOCK_DIR"
        continue
    fi
    if [[ "$LOCK_WAITED" -eq 0 ]]; then
        echo "[test-cache] waiting for pytest lock (held by pid ${HOLDER_PID:-?})..."
    fi
    sleep 2
    LOCK_WAITED=$(( LOCK_WAITED + 2 ))
    if [[ "$LOCK_WAITED" -ge "$LOCK_WAIT_MAX" ]]; then
        echo "[test-cache] gave up waiting for lock after ${LOCK_WAIT_MAX}s — exiting 3" >&2
        exit 3
    fi
done
echo "$$" > "$LOCK_HOLDER"
trap 'rm -rf "$LOCK_DIR"' EXIT INT TERM

# --- double-check cache now that we hold the lock ---
# The holder ahead of us may have just populated the cache for this
# tree hash; skip pytest if so.
if [[ "$FRESH" == false && -f "$CACHE_FILE" ]]; then
    AGE_SECS=$(( $(date +%s) - $(_cache_mtime "$CACHE_FILE") ))
    AGE_MIN=$(( AGE_SECS / 60 ))
    echo "[test-cache] HIT (post-lock) — tree $TREE_HASH (cached ${AGE_MIN}m ago)"
    cat "$CACHE_FILE"
    exit 0
fi

# --- cache miss: run pytest ---
mkdir -p "$CACHE_DIR"
echo "[test-cache] MISS — tree $TREE_HASH, running pytest..."

# Prefer env override; otherwise `python3` on PATH (Linux CI + typical macOS).
PYTHON="${UNITARES_PYTHON:-python3}"
PYTEST_CMD=("$PYTHON" -m pytest tests/ agents/ -q --tb=short -x \
	--cov=src --cov=agents/sdk/src/unitares_sdk --cov=agents \
	--cov-report=term-missing --cov-fail-under=25 \
	${PYTEST_EXTRA[@]+"${PYTEST_EXTRA[@]}"})
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
