#!/bin/bash
#
# UNITARES Watchdog - Monitors and auto-restarts the governance server
#
# Usage: ./watchdog.sh [--daemon]
#   --daemon: Run in background, logging to /tmp/unitares_watchdog.log
#
# Monitors:
# - Server health endpoint
# - CPU usage (restarts if stuck at 100%)
# - Process existence
#

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/src/mcp_server_sse.py"
PORT=8767
LOG_FILE="/tmp/unitares_watchdog.log"
PID_FILE="/tmp/unitares_server.pid"
CHECK_INTERVAL=30  # seconds
MAX_CPU_THRESHOLD=95  # percent
CPU_HIGH_COUNT=0
CPU_HIGH_LIMIT=3  # restart after 3 consecutive high CPU readings

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

start_server() {
    log "Starting UNITARES server on port $PORT..."
    cd "$SCRIPT_DIR"
    nohup python3 "$SERVER_SCRIPT" --port "$PORT" >> /tmp/unitares.log 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    log "Server started with PID $(cat $PID_FILE)"
}

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log "Stopping server (PID $PID)..."
            kill "$PID" 2>/dev/null
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                log "Force killing server..."
                kill -9 "$PID" 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
    # Also kill any orphan processes
    pkill -f "mcp_server_sse.py.*$PORT" 2>/dev/null
}

check_health() {
    HEALTH=$(curl -s --max-time 5 "http://localhost:$PORT/health" 2>/dev/null)
    if echo "$HEALTH" | grep -q '"status":"ok"'; then
        return 0
    fi
    return 1
}

get_cpu_usage() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            ps -p "$PID" -o %cpu= 2>/dev/null | tr -d ' ' | cut -d. -f1
            return
        fi
    fi
    echo "0"
}

daemon_mode() {
    log "=== UNITARES Watchdog Starting (daemon mode) ==="

    # Initial start
    if ! check_health; then
        stop_server
        start_server
    else
        log "Server already running and healthy"
    fi

    while true; do
        sleep $CHECK_INTERVAL

        # Check health
        if ! check_health; then
            log "ALERT: Health check failed!"
            stop_server
            start_server
            CPU_HIGH_COUNT=0
            continue
        fi

        # Check CPU
        CPU=$(get_cpu_usage)
        if [ "$CPU" -gt "$MAX_CPU_THRESHOLD" ]; then
            CPU_HIGH_COUNT=$((CPU_HIGH_COUNT + 1))
            log "WARNING: CPU at ${CPU}% (count: $CPU_HIGH_COUNT/$CPU_HIGH_LIMIT)"

            if [ "$CPU_HIGH_COUNT" -ge "$CPU_HIGH_LIMIT" ]; then
                log "ALERT: CPU stuck high - restarting server"
                stop_server
                start_server
                CPU_HIGH_COUNT=0
            fi
        else
            CPU_HIGH_COUNT=0
        fi
    done
}

case "$1" in
    --daemon)
        daemon_mode
        ;;
    --start)
        stop_server
        start_server
        ;;
    --stop)
        stop_server
        log "Server stopped"
        ;;
    --status)
        if check_health; then
            echo "UNITARES server is healthy"
            CPU=$(get_cpu_usage)
            echo "CPU: ${CPU}%"
            if [ -f "$PID_FILE" ]; then
                echo "PID: $(cat $PID_FILE)"
            fi
        else
            echo "UNITARES server is NOT responding"
        fi
        ;;
    *)
        echo "UNITARES Watchdog"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  --daemon    Run watchdog in background (monitors and auto-restarts)"
        echo "  --start     Start the server"
        echo "  --stop      Stop the server"
        echo "  --status    Check server status"
        ;;
esac
