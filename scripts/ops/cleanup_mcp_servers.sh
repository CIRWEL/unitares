#!/bin/bash
# Cleanup script for zombie MCP server processes
# Fixes latency and connection issues caused by process proliferation

echo "🔍 Scanning for MCP server processes..."
echo ""

# Count processes
TOTAL=$(ps aux | grep "mcp_server_std.py" | grep -v grep | wc -l | tr -d ' ')
echo "Found: $TOTAL MCP server processes"

if [ "$TOTAL" -le 2 ]; then
    echo "✅ Process count is normal (1-2 expected for Claude Desktop)"
    exit 0
fi

echo ""
echo "⚠️  Too many processes detected!"
echo ""
echo "Processes:"
ps aux | grep "mcp_server_std.py" | grep -v grep | awk '{printf "  PID: %-6s Started: %-8s CPU: %s\n", $2, $9, $10}'

echo ""
echo "Options:"
echo "  1. Kill all and let Claude Desktop restart (recommended)"
echo "  2. Kill old processes only (keep recent 2)"
echo "  3. Cancel"
echo ""
read -p "Select [1-3]: " choice

case $choice in
    1)
        echo ""
        echo "Killing all MCP server processes..."
        pkill -f "mcp_server_std.py"

        # Clean up PID file
        rm -f /Users/cirwel/projects/governance-mcp-v1/data/.mcp_server.pid

        echo "✅ Cleanup complete!"
        echo "   Claude Desktop will auto-restart the MCP server on next use"
        ;;
    2)
        echo ""
        echo "Killing old processes (keeping 2 most recent)..."

        # Get all PIDs, sort by start time, kill all but last 2
        ps aux | grep "mcp_server_std.py" | grep -v grep | \
            sort -k9 | head -n -2 | awk '{print $2}' | \
            xargs -I{} kill {}

        echo "✅ Old processes cleaned up"
        echo "   Kept 2 most recent processes"
        ;;
    3)
        echo "Cancelled"
        exit 0
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Remaining processes:"
ps aux | grep "mcp_server_std.py" | grep -v grep | wc -l | tr -d ' '
