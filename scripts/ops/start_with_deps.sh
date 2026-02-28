#!/bin/bash
# Start Governance MCP Server with dependencies (Docker + PostgreSQL)
# Used by LaunchAgent for auto-start at login

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Wait for Docker daemon (may take a moment after login)
echo "Waiting for Docker..."
for i in {1..30}; do
    if docker info &>/dev/null; then
        echo "Docker is ready"
        break
    fi
    sleep 2
done

# Start PostgreSQL container if not running
if ! docker ps --format '{{.Names}}' | grep -q '^postgres-age$'; then
    echo "Starting PostgreSQL container..."
    docker start postgres-age || {
        echo "Failed to start postgres-age container"
        exit 1
    }
    # Wait for postgres to be ready
    echo "Waiting for PostgreSQL..."
    for i in {1..15}; do
        if docker exec postgres-age pg_isready -U postgres &>/dev/null; then
            echo "PostgreSQL is ready"
            break
        fi
        sleep 1
    done
fi

# Start the MCP server
exec "$SCRIPT_DIR/start_server.sh" "$@"
