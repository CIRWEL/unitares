#!/bin/bash
# Health monitoring script for UNITARES
# Checks server health and sends alerts if issues detected

set -e

# Configuration
HEALTH_URL="${HEALTH_URL:-http://localhost:8765/health}"
METRICS_URL="${METRICS_URL:-http://localhost:8765/metrics}"
ALERT_EMAIL="${ALERT_EMAIL:-}"  # Optional: email for alerts
CHECK_INTERVAL="${CHECK_INTERVAL:-60}"  # Check every 60 seconds
MAX_FAILURES="${MAX_FAILURES:-3}"  # Alert after 3 consecutive failures

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# State tracking
FAILURE_COUNT=0
LAST_STATUS="unknown"

check_health() {
    local response
    local status
    
    # Check health endpoint
    response=$(curl -s -w "\n%{http_code}" "$HEALTH_URL" 2>/dev/null || echo -e "\n000")
    status=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$status" = "200" ]; then
        # Parse JSON response
        server_status=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null || echo "unknown")
        uptime=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('uptime', {}).get('formatted', 'unknown'))" 2>/dev/null || echo "unknown")
        connections=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('connections', {}).get('active', 0))" 2>/dev/null || echo "0")
        
        if [ "$server_status" = "ok" ]; then
            echo -e "${GREEN}✅ Health check passed${NC}"
            echo "  Status: $server_status"
            echo "  Uptime: $uptime"
            echo "  Connections: $connections"
            FAILURE_COUNT=0
            LAST_STATUS="ok"
            return 0
        else
            echo -e "${YELLOW}⚠️  Server warming up${NC}"
            echo "  Status: $server_status"
            FAILURE_COUNT=0
            LAST_STATUS="warming_up"
            return 0
        fi
    else
        echo -e "${RED}❌ Health check failed${NC}"
        echo "  HTTP Status: $status"
        FAILURE_COUNT=$((FAILURE_COUNT + 1))
        LAST_STATUS="failed"
        
        if [ $FAILURE_COUNT -ge $MAX_FAILURES ]; then
            send_alert "UNITARES health check failed $FAILURE_COUNT times. HTTP Status: $status"
        fi
        return 1
    fi
}

check_metrics() {
    local response
    local status
    
    response=$(curl -s -w "\n%{http_code}" "$METRICS_URL" 2>/dev/null || echo -e "\n000")
    status=$(echo "$response" | tail -1)
    
    if [ "$status" = "200" ]; then
        echo -e "${GREEN}✅ Metrics endpoint accessible${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  Metrics endpoint returned status $status${NC}"
        return 1
    fi
}

send_alert() {
    local message="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo -e "${RED}🚨 ALERT: $message${NC}"
    echo "  Time: $timestamp"
    
    # Optional: Send email alert
    if [ -n "$ALERT_EMAIL" ]; then
        echo "Sending email alert to $ALERT_EMAIL..."
        echo -e "Subject: UNITARES Alert\n\n$message\nTime: $timestamp" | \
            sendmail "$ALERT_EMAIL" 2>/dev/null || echo "  (Email send failed - check sendmail config)"
    fi
    
    # Optional: Log to file
    echo "[$timestamp] ALERT: $message" >> /tmp/unitares_alerts.log 2>/dev/null || true
}

check_processes() {
    local server_running=false
    local ngrok_running=false
    
    if pgrep -f "mcp_server.py" > /dev/null; then
        server_running=true
    fi
    
    if pgrep -f "ngrok.*8765" > /dev/null || pgrep -f "ngrok.*unitares" > /dev/null; then
        ngrok_running=true
    fi
    
    if [ "$server_running" = true ] && [ "$ngrok_running" = true ]; then
        echo -e "${GREEN}✅ Processes running${NC}"
        return 0
    else
        echo -e "${RED}❌ Process check failed${NC}"
        [ "$server_running" = false ] && echo "  MCP server not running"
        [ "$ngrok_running" = false ] && echo "  Ngrok not running"
        return 1
    fi
}

main() {
    echo "🔍 UNITARES Health Monitor"
    echo "=========================="
    echo "Health URL: $HEALTH_URL"
    echo "Check interval: ${CHECK_INTERVAL}s"
    echo "Max failures before alert: $MAX_FAILURES"
    echo ""
    
    if [ "$1" = "--once" ]; then
        # Single check mode
        check_processes
        check_health
        check_metrics
        exit $?
    fi
    
    # Continuous monitoring mode
    echo "Starting continuous monitoring (Ctrl+C to stop)..."
    echo ""
    
    while true; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking health..."
        
        check_processes
        check_health
        check_metrics
        
        echo ""
        sleep "$CHECK_INTERVAL"
    done
}

main "$@"
