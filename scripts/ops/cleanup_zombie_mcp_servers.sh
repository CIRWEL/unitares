#!/bin/bash
# Cleanup script for zombie MCP server processes
# Kills stale governance-mcp-v1 server instances
# Enhanced with version checking and better process detection

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/data/.mcp_server.pid"

echo "🔍 Finding governance MCP server processes..."

# Find all mcp_server_std.py processes with detailed info
PROCESSES=$(ps aux | grep "mcp_server_std.py" | grep -v grep | awk '{print $2}')

if [ -z "$PROCESSES" ]; then
    echo "✅ No governance MCP server processes found"
    exit 0
fi

echo ""
echo "📋 Found processes:"
ps aux | grep "mcp_server_std.py" | grep -v grep | while read line; do
    PID=$(echo "$line" | awk '{print $2}')
    ETIME=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ')
    echo "  PID $PID (runtime: ${ETIME:-unknown})"
done

# Check for PID file and version info
if [ -f "$PID_FILE" ]; then
    echo ""
    echo "📄 PID file found:"
    PID_FILE_PID=$(head -n 1 "$PID_FILE" 2>/dev/null)
    PID_FILE_VERSION=$(sed -n '2p' "$PID_FILE" 2>/dev/null)
    echo "  PID: $PID_FILE_PID"
    echo "  Version: ${PID_FILE_VERSION:-unknown}"
fi

# Get the most recent PIDs (keep the 9 newest)
# Sort by start time (column 9) and keep last 9
KEEP_COUNT=9
RECENT_PIDS=$(ps aux | grep "mcp_server_std.py" | grep -v grep | sort -k9 | tail -$KEEP_COUNT | awk '{print $2}')

echo ""
echo "📋 Keeping most recent processes (max $KEEP_COUNT):"
for pid in $RECENT_PIDS; do
    ETIME=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
    echo "  ✓ PID $pid (runtime: ${ETIME:-unknown})"
done

echo ""
echo "💀 Killing stale processes..."

KILLED=0
STALE_COUNT=0
for pid in $PROCESSES; do
    # Check if this PID is in the recent list
    if echo "$RECENT_PIDS" | grep -q "^$pid$"; then
        echo "  ✓ Keeping PID $pid (recent)"
    else
        STALE_COUNT=$((STALE_COUNT + 1))
        ETIME=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        echo "  🗑️  Killing PID $pid (stale, runtime: ${ETIME:-unknown})"
        kill "$pid" 2>/dev/null && KILLED=$((KILLED + 1)) || echo "    (already dead)"
    fi
done

echo ""
if [ $KILLED -gt 0 ]; then
    echo "✅ Cleanup complete: Killed $KILLED stale process(es)"
else
    if [ $STALE_COUNT -eq 0 ]; then
        echo "✅ No stale processes found - all processes are recent"
    else
        echo "⚠️  Found $STALE_COUNT stale process(es) but could not kill them"
    fi
fi

echo ""
echo "📊 Remaining processes:"
REMAINING=$(ps aux | grep "mcp_server_std.py" | grep -v grep)
if [ -z "$REMAINING" ]; then
    echo "  (none)"
else
    echo "$REMAINING"
fi

echo ""
echo "💡 Tip: The server now automatically cleans up stale processes on startup."
echo "💡 Use the 'get_server_info' MCP tool to check server health and version."

