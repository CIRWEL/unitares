#!/usr/bin/env bash
# backup_governance.sh — Daily PostgreSQL backup for UNITARES governance DB
# Scheduled via ~/Library/LaunchAgents/com.unitares.governance-backup.plist
# (template: scripts/ops/com.unitares.governance-backup.plist)
#
# Dumps the governance database from the postgres-age Docker container,
# compresses with gzip, and retains the last N backup files.
#
# Hardening: start stopped container, optional docker compose up, wait for
# pg_isready, pg_dump retries, last_backup_status.json, optional macOS alert.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_DEFAULT_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# Auto-detect repo root when script lives in scripts/ (for docker compose recovery).
if [ -z "${GOVERNANCE_REPO:-}" ] && [ -f "$_DEFAULT_REPO/docker-compose.yml" ]; then
    GOVERNANCE_REPO="$_DEFAULT_REPO"
fi

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/governance}"
CONTAINER="${CONTAINER:-postgres-age}"
DATABASE="${DATABASE:-governance}"
# Keep the last N backup files (not calendar days; filename list order).
KEEP_DAYS="${KEEP_DAYS:-14}"
LOG="${LOG:-$BACKUP_DIR/backup.log}"

# Wait for Postgres inside the container (handles slow restarts).
PG_READY_ATTEMPTS="${PG_READY_ATTEMPTS:-30}"
PG_READY_SLEEP_SEC="${PG_READY_SLEEP_SEC:-2}"

# pg_dump transient failure retries.
DUMP_RETRIES="${DUMP_RETRIES:-3}"
DUMP_RETRY_SLEEP_SEC="${DUMP_RETRY_SLEEP_SEC:-5}"

STATUS_JSON="$BACKUP_DIR/last_backup_status.json"
LAST_SUCCESS_FILE="$BACKUP_DIR/last_backup_success.txt"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M)
BACKUP_FILE="$BACKUP_DIR/governance_${TIMESTAMP}.sql.gz"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

write_status_error() {
    local detail="${1:-}"
    DETAIL="$detail" TS=$(date -u +%Y-%m-%dT%H:%M:%SZ) python3 -c '
import json, os
print(json.dumps({"status": "error", "timestamp": os.environ["TS"], "detail": os.environ.get("DETAIL", "")}))
' >"$STATUS_JSON"
}

write_status_ok() {
    local backup_path="$1"
    FILE="$backup_path" TS=$(date -u +%Y-%m-%dT%H:%M:%SZ) python3 -c '
import json, os
print(json.dumps({"status": "ok", "timestamp": os.environ["TS"], "file": os.environ["FILE"]}))
' >"$STATUS_JSON"
}

alert_failure() {
    local msg="$1"
    if [ "${UNITARES_BACKUP_NO_ALERT:-0}" = "1" ]; then
        return 0
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
        osascript -e "display notification \"${msg//\"/\\\"}\" with title \"Governance backup failed\"" 2>/dev/null || true
    fi
}

docker_daemon_ok() {
    docker info >/dev/null 2>&1
}

container_running() {
    docker inspect "$CONTAINER" --format='{{.State.Running}}' 2>/dev/null | grep -q true
}

container_exists() {
    docker inspect "$CONTAINER" --format='{{.Name}}' >/dev/null 2>&1
}

ensure_container_running() {
    if container_running; then
        return 0
    fi

    log "WARN: Container '$CONTAINER' is not running; attempting recovery"

    if ! docker_daemon_ok; then
        log "ERROR: Docker daemon not reachable (is Docker Desktop running?)"
        write_status_error "Docker daemon not reachable"
        alert_failure "Governance backup: Docker not running"
        return 1
    fi

    if container_exists; then
        log "Starting existing container $CONTAINER"
        docker start "$CONTAINER" >/dev/null || true
    fi

    if ! container_running && [ -n "${GOVERNANCE_REPO:-}" ] && [ -f "$GOVERNANCE_REPO/docker-compose.yml" ]; then
        log "Running: docker compose up -d (from GOVERNANCE_REPO=$GOVERNANCE_REPO)"
        (cd "$GOVERNANCE_REPO" && docker compose up -d postgres-age) || true
    fi

    if ! container_running; then
        log "ERROR: Could not start '$CONTAINER' (set GOVERNANCE_REPO to repo with docker-compose.yml for compose recovery)"
        write_status_error "Container not running after recovery attempts"
        alert_failure "Governance backup: postgres-age not running"
        return 1
    fi

    log "Container '$CONTAINER' is running"
    return 0
}

wait_for_postgres() {
    local i=0
    while [ "$i" -lt "$PG_READY_ATTEMPTS" ]; do
        if docker exec "$CONTAINER" pg_isready -U postgres -d "$DATABASE" >/dev/null 2>&1; then
            return 0
        fi
        i=$((i + 1))
        sleep "$PG_READY_SLEEP_SEC"
    done
    log "ERROR: Postgres not ready after ${PG_READY_ATTEMPTS} attempts (${PG_READY_SLEEP_SEC}s)"
    write_status_error "Postgres not ready (pg_isready timeout)"
    alert_failure "Governance backup: database not ready"
    return 1
}

run_pg_dump() {
    docker exec "$CONTAINER" pg_dump -U postgres "$DATABASE" | gzip >"$BACKUP_FILE"
}

# --- main ---

if ! ensure_container_running; then
    exit 1
fi

if ! wait_for_postgres; then
    exit 1
fi

log "Starting backup to $BACKUP_FILE"

attempt=1
while [ "$attempt" -le "$DUMP_RETRIES" ]; do
    if run_pg_dump; then
        SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        log "Backup complete: $BACKUP_FILE ($SIZE)"
        ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        echo "$ts" >"$LAST_SUCCESS_FILE"
        write_status_ok "$BACKUP_FILE"
        break
    fi
    rm -f "$BACKUP_FILE"
    if [ "$attempt" -lt "$DUMP_RETRIES" ]; then
        log "WARN: pg_dump failed (attempt $attempt/$DUMP_RETRIES), retrying in ${DUMP_RETRY_SLEEP_SEC}s"
        sleep "$DUMP_RETRY_SLEEP_SEC"
    fi
    attempt=$((attempt + 1))
done

if [ ! -f "$BACKUP_FILE" ]; then
    log "ERROR: pg_dump failed after $DUMP_RETRIES attempts"
    write_status_error "pg_dump failed"
    alert_failure "Governance backup: pg_dump failed"
    exit 1
fi

# Prune old backups (keep last N files)
PRUNED=$(ls -1t "$BACKUP_DIR"/governance_*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAYS + 1)) | wc -l | tr -d ' ')
ls -1t "$BACKUP_DIR"/governance_*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAYS + 1)) | xargs rm -f 2>/dev/null || true
if [ "$PRUNED" -gt 0 ]; then
    log "Pruned $PRUNED old backup(s)"
fi

# Trim log (keep last 200 lines)
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 200 ]; then
    tail -200 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0
