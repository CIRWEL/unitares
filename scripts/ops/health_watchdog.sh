#!/bin/bash
# UNITARES + Anima health watchdog
# Runs every 5 minutes via launchd. Logs failures to /tmp/unitares_health.log.
# Exits silently on success — only writes when something is wrong.

LOG="/tmp/unitares_health.log"
MAX_LOG_LINES=500

ts() { date '+%Y-%m-%d %H:%M:%S'; }

check() {
    local name="$1" url="$2" timeout="${3:-5}"
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$timeout" "$url" 2>/dev/null)
    if [ "$code" != "200" ]; then
        echo "[$(ts)] FAIL $name — HTTP $code ($url)" >> "$LOG"
        return 1
    fi
    return 0
}

failures=0

# Governance (Mac local)
check "governance" "http://localhost:8767/health" || failures=$((failures + 1))

# Anima (Pi via Tailscale)
check "anima" "http://100.79.215.83:8766/health" 10 || failures=$((failures + 1))

# PostgreSQL (via governance health detail)
if [ $failures -eq 0 ]; then
    db_status=$(curl -s --max-time 5 http://localhost:8767/health 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('database', {}).get('status', 'unknown'))
except: print('unknown')
" 2>/dev/null)
    if [ "$db_status" != "connected" ]; then
        echo "[$(ts)] WARN governance db pool: $db_status" >> "$LOG"
        failures=$((failures + 1))
    fi
fi

# Trim log if it gets too long
if [ -f "$LOG" ]; then
    lines=$(wc -l < "$LOG")
    if [ "$lines" -gt "$MAX_LOG_LINES" ]; then
        tail -n "$MAX_LOG_LINES" "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
fi

exit 0
