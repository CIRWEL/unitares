#!/bin/bash
# Emergency fix for PostgreSQL "too many clients" error

set -e

echo "🚨 Emergency PostgreSQL Connection Fix"
echo "======================================"
echo ""

CONTAINER="postgres-age"

# Method 1: Try to connect via docker exec with superuser
echo "📊 Attempting to connect..."
docker exec $CONTAINER psql -U postgres -d postgres -c "
    -- Kill idle connections older than 1 minute
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = 'governance'
      AND pid != pg_backend_pid()
      AND state = 'idle in transaction'
      AND state_change < now() - interval '1 minute';
" || echo "Could not kill stale connections"

# Check current max_connections
echo ""
echo "Current max_connections setting:"
docker exec $CONTAINER psql -U postgres -d postgres -c "SHOW max_connections;" || echo "Could not check max_connections"

# Increase max_connections
echo ""
echo "🔧 Increasing max_connections to 200..."
docker exec $CONTAINER psql -U postgres -d postgres -c "
    ALTER SYSTEM SET max_connections = 200;
    SELECT pg_reload_conf();
" || echo "Could not increase max_connections (may need container restart)"

echo ""
echo "✅ Fix applied. You may need to restart the container:"
echo "   docker restart $CONTAINER"
