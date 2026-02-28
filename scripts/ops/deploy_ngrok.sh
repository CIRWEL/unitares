#!/bin/bash
#
# Deploy UNITARES MCP Server via ngrok
#
# Usage:
#   ./scripts/deploy_ngrok.sh your-domain.ngrok.io   # Use your reserved domain
#   ./scripts/deploy_ngrok.sh                        # Uses random ngrok URL (no domain)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default port for MCP server (Streamable HTTP)
# 8767 = governance (Mac), 8766 = anima (Pi)
MCP_PORT="${MCP_PORT:-8767}"

# Domain (optional - pass your reserved ngrok domain as first argument)
# Get your own domain at: https://dashboard.ngrok.com/domains
DOMAIN="${1:-}"

echo "🚀 UNITARES MCP Server - ngrok Deployment"
echo "=========================================="
echo ""

# Check if MCP server is running
if ! lsof -ti:$MCP_PORT > /dev/null 2>&1; then
    echo "❌ MCP server not running on port $MCP_PORT"
    echo ""
    echo "Start it first:"
    echo "  cd $PROJECT_ROOT"
    echo "  python src/mcp_server.py --port $MCP_PORT"
    echo ""
    exit 1
fi

echo "✅ MCP server running on port $MCP_PORT"
echo ""

# Check ngrok installation
if ! command -v ngrok &> /dev/null; then
    echo "❌ ngrok not installed"
    echo ""
    echo "Install with:"
    echo "  brew install ngrok"
    echo ""
    exit 1
fi

echo "✅ ngrok installed: $(ngrok --version)"
echo ""

# Check ngrok auth
if ! ngrok config check > /dev/null 2>&1; then
    echo "❌ ngrok not configured"
    echo ""
    echo "Add your authtoken:"
    echo "  ngrok config add-authtoken YOUR_TOKEN"
    echo ""
    exit 1
fi

echo "✅ ngrok configured"
echo ""

# Build ngrok command
NGROK_CMD="ngrok http $MCP_PORT"

# Add domain if provided
if [ -n "$DOMAIN" ]; then
    NGROK_CMD="$NGROK_CMD --domain=$DOMAIN"
    echo "📍 Using reserved domain: $DOMAIN"
else
    echo "📍 Using random domain (provide reserved domain as argument for stable URL)"
fi

echo ""
echo "🌐 Starting ngrok tunnel..."
echo ""
echo "Command: $NGROK_CMD"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔗 Your UNITARES MCP Server is available at:"
if [ -n "$DOMAIN" ]; then
    echo "   https://$DOMAIN/mcp/"
else
    echo "   https://[random-domain]/mcp/"
fi
echo ""
echo "📋 For ChatGPT MCP:"
if [ -n "$DOMAIN" ]; then
    echo "   {
     \"servers\": {
       \"unitares\": {
         \"url\": \"https://$DOMAIN/mcp/\",
         \"description\": \"UNITARES AI Governance Framework\",
         \"auth\": {
           \"type\": \"oauth\",
           \"provider\": \"google\"
         }
       }
     }
   }"
else
    echo '   {
     "servers": {
       "unitares": {
         "url": "https://[your-domain]/mcp/",
         "description": "UNITARES AI Governance Framework",
         "auth": {
           "type": "oauth",
           "provider": "google"
         }
       }
     }
   }'
fi
echo ""
echo "🛑 Press Ctrl+C to stop"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Run ngrok
$NGROK_CMD
