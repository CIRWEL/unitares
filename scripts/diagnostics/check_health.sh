#!/bin/bash
# Local operational health check for UNITARES governance.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8767/health}"
PID_FILE="data/.mcp_server.pid"
EXIT_CODE=0

echo "=== UNITARES Health ==="
echo "Repo: $PROJECT_ROOT"
echo "Endpoint: $HEALTH_URL"

echo ""
echo "=== HTTP Health ==="
if RESPONSE="$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null)"; then
    python3 - "$RESPONSE" <<'PY'
import json
import sys

d = json.loads(sys.argv[1])
status = d.get("status", "?")
version = d.get("version", "?")
uptime = d.get("uptime", {}).get("formatted", "?")
print(f"✓ HTTP: {status} v{version} uptime={uptime}")
PY
else
    echo "✗ HTTP: Not responding"
    EXIT_CODE=1
fi

echo ""
echo "=== PID File ==="
if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
        echo "✓ PID file: active process $PID"
    else
        echo "✗ PID file: stale or unreadable ($PID_FILE)"
        EXIT_CODE=1
    fi
else
    echo "✗ PID file: missing ($PID_FILE)"
    EXIT_CODE=1
fi

echo ""
echo "=== PostgreSQL Container ==="
if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' | grep -q '^postgres-age$'; then
        if docker exec postgres-age pg_isready -U postgres >/dev/null 2>&1; then
            echo "✓ PostgreSQL: postgres-age ready"
        else
            echo "✗ PostgreSQL: postgres-age running but not ready"
            EXIT_CODE=1
        fi
    else
        echo "✗ PostgreSQL: postgres-age container not running"
        EXIT_CODE=1
    fi
else
    echo "- PostgreSQL: docker not installed"
fi

echo ""
echo "=== Operator Hint ==="
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "System looks healthy."
else
    echo "If HTTP is down, start with: ./scripts/ops/start_with_deps.sh"
    echo "If PID is stale, stop with: ./scripts/ops/stop_unitares.sh"
fi

exit "$EXIT_CODE"
