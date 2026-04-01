#!/usr/bin/env bash
# check_governance_backup_health.sh — Exit non-zero if governance backups look stale.
#
# Use in cron/LaunchAgent, monitoring, or pre-deploy checks.
# Reads last_backup_success.txt (written by backup_governance.sh) or last_backup_status.json.
#
# Environment:
#   BACKUP_DIR   — default ~/backups/governance
#   MAX_AGE_SEC  — default 93600 (26 hours; allows daily job + slack)

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/governance}"
MAX_AGE_SEC="${MAX_AGE_SEC:-93600}"
LAST_SUCCESS="$BACKUP_DIR/last_backup_success.txt"
STATUS_JSON="$BACKUP_DIR/last_backup_status.json"

die() {
    echo "check_governance_backup_health: $*" >&2
    exit 1
}

if [ ! -d "$BACKUP_DIR" ]; then
    die "BACKUP_DIR does not exist: $BACKUP_DIR"
fi

now=$(date +%s)

if [ -f "$LAST_SUCCESS" ]; then
    ts=$(tr -d ' \t\r\n' <"$LAST_SUCCESS")
    # Expect ISO8601 UTC from backup script
    # macOS: -u parses input as UTC; Linux: GNU date -d handles Zulu
    if ts_sec=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null) || \
       ts_sec=$(date -u -d "$ts" +%s 2>/dev/null); then
        age=$((now - ts_sec))
        if [ "$age" -gt "$MAX_AGE_SEC" ]; then
            die "last success was ${age}s ago (limit ${MAX_AGE_SEC}s): $ts"
        fi
        echo "OK: last backup success $ts (age ${age}s)"
        exit 0
    fi
fi

# Fallback: newest governance_*.sql.gz mtime
latest=$(ls -1t "$BACKUP_DIR"/governance_*.sql.gz 2>/dev/null | head -1 || true)
if [ -n "$latest" ]; then
    mtime=$(stat -f %m "$latest" 2>/dev/null || stat -c %Y "$latest" 2>/dev/null || echo 0)
    age=$((now - mtime))
    if [ "$age" -gt "$MAX_AGE_SEC" ]; then
        die "newest dump is stale (${age}s): $latest"
    fi
    echo "OK: newest dump $latest (age ${age}s, no last_backup_success.txt yet)"
    exit 0
fi

if [ -f "$STATUS_JSON" ]; then
    die "no backups found; see $STATUS_JSON"
fi

die "no governance_*.sql.gz in $BACKUP_DIR"
