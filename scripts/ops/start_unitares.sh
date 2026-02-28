#!/bin/bash
# Start UNITARES MCP Server + ngrok tunnel
# Unified startup script for reliable operation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🚀 Starting UNITARES Governance MCP Server..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating one...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Clean up stale locks and PID files
echo "🧹 Cleaning up stale lock files..."
rm -f data/.mcp_server.* 2>/dev/null || true

# Check if server is already running
if pgrep -f "mcp_server.py" > /dev/null; then
    echo -e "${YELLOW}⚠️  Server appears to be running. Stopping existing instance...${NC}"
    pkill -f "mcp_server.py" || true
    sleep 2
fi

# Check if ngrok is already running for this port
if pgrep -f "ngrok.*8767" > /dev/null; then
    echo -e "${YELLOW}⚠️  Ngrok appears to be running. Stopping existing instance...${NC}"
    pkill -f "ngrok.*8767" || true
    sleep 1
fi

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

# Start ngrok tunnel (pass domain as argument or use random URL)
NGROK_DOMAIN="${NGROK_DOMAIN:-}"
echo "🌐 Starting ngrok tunnel..."
if [ -n "$NGROK_DOMAIN" ]; then
    nohup ngrok http 8767 --url="$NGROK_DOMAIN" --log=stdout > /tmp/ngrok.log 2>&1 &
else
    echo -e "${YELLOW}ℹ️  No NGROK_DOMAIN set - using random URL. Set NGROK_DOMAIN env var for stable URL.${NC}"
    nohup ngrok http 8767 --log=stdout > /tmp/ngrok.log 2>&1 &
fi
NGROK_PID=$!

# Wait for ngrok to start
sleep 2

# Check if ngrok started successfully
if ps -p $NGROK_PID > /dev/null; then
    echo -e "${GREEN}✅ Ngrok tunnel started (PID: $NGROK_PID)${NC}"
else
    echo -e "${YELLOW}⚠️  Ngrok may have failed to start. Check logs: tail -f /tmp/ngrok.log${NC}"
fi

# Display status
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  UNITARES Status"
echo "════════════════════════════════════════════════════════════"
echo "  MCP Server:  http://localhost:8767/mcp/"
echo "  Health:      http://localhost:8767/health"
if [ -n "$NGROK_DOMAIN" ]; then
    echo "  Ngrok URL:   https://$NGROK_DOMAIN/mcp/"
else
    echo "  Ngrok URL:   (check /tmp/ngrok.log for URL)"
fi
echo ""
echo "  Logs:"
echo "    Server:    tail -f /tmp/unitares.log"
echo "    Ngrok:     tail -f /tmp/ngrok.log"
echo ""
echo "  Stop:        ./scripts/stop_unitares.sh"
echo "════════════════════════════════════════════════════════════"
