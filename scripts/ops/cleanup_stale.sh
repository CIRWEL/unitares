#!/bin/bash
# Cleanup stale processes and resources from governance-mcp
# Run: ./scripts/cleanup_stale.sh [--dry-run]

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN - no processes will be killed ==="
fi

echo "=== Governance MCP Cleanup ==="
echo ""

# 1. Find stale MCP server processes
echo "Checking for stale MCP server processes..."
STALE_PIDS=$(pgrep -f "mcp_server" 2>/dev/null)
if [[ -n "$STALE_PIDS" ]]; then
    echo "Found MCP server processes:"
    ps -p $(echo $STALE_PIDS | tr '\n' ',') -o pid,etime,command 2>/dev/null | head -10
    if [[ "$DRY_RUN" == false ]]; then
        echo "Killing..."
        echo $STALE_PIDS | xargs kill 2>/dev/null
        echo "Done."
    fi
else
    echo "No stale MCP server processes found."
fi
echo ""

# 2. Check for stale lock files
echo "Checking for stale lock files..."
LOCK_DIR="/Users/cirwel/projects/governance-mcp-v1/data/locks"
if [[ -d "$LOCK_DIR" ]]; then
    LOCK_COUNT=$(find "$LOCK_DIR" -name "*.lock" -mmin +30 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$LOCK_COUNT" -gt 0 ]]; then
        echo "Found $LOCK_COUNT stale lock files (>30 min old):"
        find "$LOCK_DIR" -name "*.lock" -mmin +30 -ls 2>/dev/null | head -5
        if [[ "$DRY_RUN" == false ]]; then
            echo "Removing..."
            find "$LOCK_DIR" -name "*.lock" -mmin +30 -delete 2>/dev/null
            echo "Done."
        fi
    else
        echo "No stale lock files found."
    fi
else
    echo "Lock directory not found (OK if not using file locks)."
fi
echo ""

# 3. Check for orphaned heartbeat files
echo "Checking heartbeat freshness..."
HEARTBEAT_FILE="/Users/cirwel/projects/governance-mcp-v1/data/mcp_heartbeat.json"
if [[ -f "$HEARTBEAT_FILE" ]]; then
    AGE_MINUTES=$(( ($(date +%s) - $(stat -f %m "$HEARTBEAT_FILE")) / 60 ))
    if [[ $AGE_MINUTES -gt 10 ]]; then
        echo "Heartbeat is stale ($AGE_MINUTES min old)"
        if [[ "$DRY_RUN" == false ]]; then
            rm -f "$HEARTBEAT_FILE"
            echo "Removed stale heartbeat file."
        fi
    else
        echo "Heartbeat is fresh ($AGE_MINUTES min old)."
    fi
else
    echo "No heartbeat file (server not running)."
fi
echo ""

# 4. Summary
echo "=== Cleanup complete ==="
if [[ "$DRY_RUN" == true ]]; then
    echo "This was a dry run. Run without --dry-run to actually clean up."
fi
