#!/bin/bash
# Quick setup script for MCP server

set -e

echo "🚀 Setting up UNITARES Governance MCP Server v1.0"
echo ""

# Get project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 not found"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
if [ -f "requirements-mcp.txt" ]; then
    pip3 install -q -r requirements-mcp.txt
    echo "✅ Dependencies installed"
else
    echo "⚠️  requirements-mcp.txt not found, installing manually..."
    pip3 install -q mcp numpy
    echo "✅ Dependencies installed"
fi

# Make server executable
chmod +x src/mcp_server_std.py
echo "✅ Server script is executable"

# Test import
echo ""
echo "🧪 Testing imports..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
try:
    from src.governance_monitor import UNITARESMonitor
    print('✅ Governance monitor imported')
except ImportError as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
"

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Darwin*)
        CURSOR_CONFIG="$HOME/Library/Application Support/Cursor/User/globalStorage/mcp.json"
        CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
        ;;
    Linux*)
        CURSOR_CONFIG="$HOME/.config/Cursor/User/globalStorage/mcp.json"
        CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        CURSOR_CONFIG="$APPDATA/Cursor/User/globalStorage/mcp.json"
        CLAUDE_CONFIG="$APPDATA/Claude/claude_desktop_config.json"
        ;;
    *)
        echo "⚠️  Unknown OS: $OS"
        echo "   Please configure manually (see MCP_SETUP.md)"
        exit 0
        ;;
esac

echo ""
echo "📝 Configuration files:"
echo "   Cursor: $CURSOR_CONFIG"
echo "   Claude Desktop: $CLAUDE_CONFIG"
echo ""

# Create config snippet
CONFIG_SNIPPET=$(cat <<EOF
{
  "mcpServers": {
    "governance-monitor": {
      "command": "python3",
      "args": [
        "$PROJECT_DIR/src/mcp_server_std.py"
      ],
      "env": {
        "PYTHONPATH": "$PROJECT_DIR"
      }
    }
  }
}
EOF
)

echo "📋 Configuration snippet (save to your MCP config file):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$CONFIG_SNIPPET"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if config files exist
if [ -f "$CURSOR_CONFIG" ]; then
    echo "✅ Cursor config exists: $CURSOR_CONFIG"
    echo "   Add the snippet above to your existing config"
else
    echo "⚠️  Cursor config not found: $CURSOR_CONFIG"
    echo "   Create it and add the snippet above"
fi

if [ -f "$CLAUDE_CONFIG" ]; then
    echo "✅ Claude Desktop config exists: $CLAUDE_CONFIG"
    echo "   Add the snippet above to your existing config"
else
    echo "⚠️  Claude Desktop config not found: $CLAUDE_CONFIG"
    echo "   Create it and add the snippet above"
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add the configuration snippet to your MCP config file"
echo "2. Restart Cursor/Claude Desktop"
echo "3. Test with: python3 src/mcp_server_std.py"
echo ""
echo "For more details, see: MCP_SETUP.md"

