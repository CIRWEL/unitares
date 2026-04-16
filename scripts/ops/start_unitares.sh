#!/bin/bash
# Start UNITARES MCP Server
# Cloudflare tunnel is managed separately via launchd (com.cloudflare.tunnel.governance)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Host header allowlists for LAN/Cloudflare access (see src/mcp_listen_config.py)
export UNITARES_BIND_ALL_INTERFACES="${UNITARES_BIND_ALL_INTERFACES:-1}"
export UNITARES_MCP_ALLOWED_HOSTS="${UNITARES_MCP_ALLOWED_HOSTS:-192.168.1.151:*,192.168.1.164:*,100.96.201.46:*,gov.cirwel.org}"
export UNITARES_MCP_ALLOWED_ORIGINS="${UNITARES_MCP_ALLOWED_ORIGINS:-http://192.168.1.151:*,http://192.168.1.164:*,http://100.96.201.46:*,https://gov.cirwel.org}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🚀 Starting UNITARES Governance MCP Server..."

print_remote_mode_hint() {
    echo ""
    echo -e "${YELLOW}Remote mode fallback:${NC}"
    echo "  If local bootstrap is unavailable, connect to your hosted UNITARES endpoint"
    echo "  and set UNITARES_SERVER_URL to that base URL in your client."
}

print_venv_install_hint() {
    local os_id=""
    if [ -f /etc/os-release ]; then
        os_id="$(. /etc/os-release && echo "${ID:-}")"
    fi
    case "$os_id" in
        ubuntu|debian)
            echo "  sudo apt install python3-venv"
            ;;
        fedora|rhel|centos)
            echo "  sudo dnf install python3-venv"
            ;;
        arch)
            echo "  sudo pacman -S python"
            ;;
        *)
            echo "  Install your distro's Python venv package (python3-venv)."
            ;;
    esac
}

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating one...${NC}"
    if ! python3 -m venv .venv; then
        echo -e "${RED}❌ Failed to create virtual environment (.venv).${NC}"
        echo "This usually means ensurepip/python3-venv is missing."
        echo ""
        echo "Install support package:"
        print_venv_install_hint
        print_remote_mode_hint
        exit 1
    fi
fi

# Activate virtual environment
source .venv/bin/activate

# Validate pip in venv (partial venvs can have python without pip)
if ! python3 -m pip --version > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Detected partial/broken virtual environment (pip missing).${NC}"
    echo "Attempting pip bootstrap via ensurepip..."
    if ! python3 -m ensurepip --upgrade > /dev/null 2>&1; then
        echo -e "${RED}❌ Could not bootstrap pip in .venv.${NC}"
        echo "Recreate the environment after installing venv support:"
        print_venv_install_hint
        echo "Then run:"
        echo "  rm -rf .venv && scripts/ops/start_unitares.sh"
        print_remote_mode_hint
        exit 1
    fi
fi

wait_for_exit() {
    local pattern="$1"
    local attempts="${2:-20}"
    local sleep_seconds="${3:-0.5}"
    local i
    for ((i=0; i<attempts; i++)); do
        if ! pgrep -f "$pattern" > /dev/null; then
            return 0
        fi
        sleep "$sleep_seconds"
    done
    return 1
}

cleanup_stale_markers() {
    if pgrep -f "mcp_server.py" > /dev/null; then
        echo -e "${YELLOW}⚠️  Server process still running; preserving marker files${NC}"
        return
    fi
    rm -f data/.mcp_server.pid data/.mcp_server.lock 2>/dev/null || true
}

# Check if server is already running
if pgrep -f "mcp_server.py" > /dev/null; then
    echo -e "${YELLOW}⚠️  Server appears to be running. Stopping existing instance...${NC}"
    pkill -f "mcp_server.py" || true
    if ! wait_for_exit "mcp_server.py" 10 0.5; then
        echo -e "${YELLOW}⚠️  Force killing existing server...${NC}"
        pkill -9 -f "mcp_server.py" || true
        wait_for_exit "mcp_server.py" 10 0.5 || true
    fi
fi

echo "🧹 Cleaning up stale lock files..."
cleanup_stale_markers

# Start MCP server
echo "📡 Starting MCP server on port 8767..."
nohup python3 src/mcp_server.py --port 8767 --host 0.0.0.0 --force > /tmp/unitares.log 2>&1 &
SERVER_PID=$!

# Wait for server to start
echo "⏳ Waiting for server to start..."
sleep 3

# Check if server started successfully
if ! ps -p $SERVER_PID > /dev/null; then
    echo -e "${RED}❌ Server failed to start. Check logs: tail -f /tmp/unitares.log${NC}"
    exit 1
fi

# Test server connectivity
if curl -s http://localhost:8767/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Server is running (PID: $SERVER_PID)${NC}"
else
    echo -e "${YELLOW}⚠️  Server started but health check failed. It may still be warming up.${NC}"
fi

# Display status
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  UNITARES Status"
echo "════════════════════════════════════════════════════════════"
echo "  MCP Server:  http://localhost:8767/mcp/"
echo "  Health:      http://localhost:8767/health"
echo "  Tunnel:      https://gov.cirwel.org/mcp/"
echo ""
echo "  Logs:"
echo "    Server:    tail -f /tmp/unitares.log"
echo "    Tunnel:    tail -f /tmp/cloudflared-gov.log"
echo ""
echo "  Stop:        ./scripts/stop_unitares.sh"
echo "════════════════════════════════════════════════════════════"
