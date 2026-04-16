#!/bin/bash
# Start the Governance MCP Server (multi-client support)
#
# Usage:
#   ./scripts/start_server.sh [--port PORT] [--host HOST]
#
# Default: http://127.0.0.1:8767/mcp
#
# Key Environment Variables (set in .env):
#   DB_BACKEND=postgres           - Database backend
#   UNITARES_I_DYNAMICS=linear    - v4.2-P: Prevents I-channel boundary saturation
#   UNITARES_KNOWLEDGE_BACKEND=age - Apache AGE graph backend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Load environment from .env if it exists
# Uses set -a to auto-export and handles comments safely
if [ -f ".env" ]; then
    set -a
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        # Remove leading/trailing whitespace from key
        key=$(echo "$key" | xargs)
        [[ -z "$key" ]] && continue
        # Export the variable
        export "$key=$value"
    done < .env
    set +a
fi

# Check for Python
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &> /dev/null; then
    echo "Error: Python not found. Set PYTHON env var or install Python 3."
    exit 1
fi

_check_import_error=$("$PYTHON" - <<'PY'
import importlib
missing = []
for mod in ("mcp", "uvicorn", "starlette"):
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(mod)
if missing:
    print("missing:" + ",".join(missing))
else:
    print("ok")
PY
)

# Dependencies: do NOT auto-install at runtime (avoids surprise failures / permission issues)
if [[ "$_check_import_error" != "ok" ]]; then
    echo "Error: missing dependencies for HTTP server."
    echo "Details: ${_check_import_error}"
    echo ""
    echo "Install minimal (stdio only):"
    echo "  pip install -r requirements-core.txt"
    echo ""
    echo "Install full (HTTP):"
    echo "  pip install -r requirements-full.txt"
    echo ""
    if [[ "$_check_import_error" == *"missing:mcp"* ]]; then
        echo "If install fails on the private core dependency:"
        echo "  Missing import is governance_core (from unitares-core, private package)."
        echo "  Install your unitares-core wheel/source first, then reinstall requirements."
        echo "  Fallback: use a hosted UNITARES endpoint (remote mode) instead of local server startup."
        echo ""
    fi
    exit 1
fi

echo "Starting Governance MCP Server from $PROJECT_ROOT..."
exec "$PYTHON" src/mcp_server.py "$@"
