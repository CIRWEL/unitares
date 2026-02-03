#!/bin/bash
#
# Deploy UNITARES MCP Server via ngrok
#
# Usage:
#   ./scripts/deploy_ngrok.sh              # Uses unitares.ngrok.io (default)
#   ./scripts/deploy_ngrok.sh [domain]     # Use different domain
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default port for SSE server
# NOTE: 8767 is the standard port for unitares governance on Mac
#       8766 is used by anima (tunneled from Pi)
#       8765 was the old default but caused conflicts
SSE_PORT="${SSE_PORT:-8767}"

# Domain (defaults to your reserved domain)
DOMAIN="${1:-unitares.ngrok.io}"

echo "🚀 UNITARES MCP Server - ngrok Deployment"
echo "=========================================="
echo ""

# Check if SSE server is running
if ! lsof -ti:$SSE_PORT > /dev/null 2>&1; then
    echo "❌ SSE server not running on port $SSE_PORT"
    echo ""
    echo "Start it first:"
    echo "  cd $PROJECT_ROOT"
    echo "  python src/mcp_server_sse.py --port $SSE_PORT"
    echo ""
    exit 1
fi

echo "✅ SSE server running on port $SSE_PORT"
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
NGROK_CMD="ngrok http $SSE_PORT"

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
    echo "   https://$DOMAIN/sse"
else
    echo "   https://[random-domain]/sse"
fi
echo ""
echo "📋 For ChatGPT MCP:"
if [ -n "$DOMAIN" ]; then
    echo "   {
     \"servers\": {
       \"unitares\": {
         \"url\": \"https://$DOMAIN/sse\",
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
         "url": "https://[your-domain]/sse",
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
