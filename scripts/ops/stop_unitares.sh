#!/bin/bash
# Stop UNITARES MCP Server
# Clean shutdown script (tunnel managed by launchd separately)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🛑 Stopping UNITARES Governance MCP Server..."

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

# Stop MCP server
if pgrep -f "mcp_server.py" > /dev/null; then
    echo "📡 Stopping MCP server..."
    pkill -f "mcp_server.py" || true
    wait_for_exit "mcp_server.py" 10 0.5 || true

    # Force kill if still running
    if pgrep -f "mcp_server.py" > /dev/null; then
        echo -e "${YELLOW}⚠️  Force killing server...${NC}"
        pkill -9 -f "mcp_server.py" || true
        wait_for_exit "mcp_server.py" 10 0.5 || true
    fi
    if pgrep -f "mcp_server.py" > /dev/null; then
        echo -e "${RED}❌ MCP server still appears to be running${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ MCP server stopped${NC}"
else
    echo "ℹ️  MCP server not running"
fi

# Clean up only when the server is actually gone; avoids racing a fresh restart.
echo "🧹 Cleaning up lock files..."
if pgrep -f "mcp_server.py" > /dev/null; then
    echo -e "${YELLOW}⚠️  Skipping marker cleanup because a server process is still running${NC}"
else
    rm -f data/.mcp_server.pid data/.mcp_server.lock 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}✅ UNITARES stopped successfully${NC}"
