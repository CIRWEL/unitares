#!/bin/bash
# Stop UNITARES MCP Server + ngrok tunnel
# Clean shutdown script

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

# Stop MCP server
if pgrep -f "mcp_server.py" > /dev/null; then
    echo "📡 Stopping MCP server..."
    pkill -f "mcp_server.py" || true
    sleep 2

    # Force kill if still running
    if pgrep -f "mcp_server.py" > /dev/null; then
        echo -e "${YELLOW}⚠️  Force killing server...${NC}"
        pkill -9 -f "mcp_server.py" || true
    fi
    echo -e "${GREEN}✅ MCP server stopped${NC}"
else
    echo "ℹ️  MCP server not running"
fi

# Stop ngrok (check both old port 8765 and current 8767)
if pgrep -f "ngrok http" > /dev/null; then
    echo "🌐 Stopping ngrok tunnel..."
    pkill -f "ngrok http" || true
    sleep 1

    # Force kill if still running
    if pgrep -f "ngrok http" > /dev/null; then
        echo -e "${YELLOW}⚠️  Force killing ngrok...${NC}"
        pkill -9 -f "ngrok http" || true
    fi
    echo -e "${GREEN}✅ Ngrok tunnel stopped${NC}"
else
    echo "ℹ️  Ngrok not running"
fi

# Clean up lock and PID files in the real project data directory
echo "🧹 Cleaning up lock files..."
rm -f data/.mcp_server.* 2>/dev/null || true

echo ""
echo -e "${GREEN}✅ UNITARES stopped successfully${NC}"
