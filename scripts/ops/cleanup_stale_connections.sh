#!/bin/bash
# Clean up stale PostgreSQL connections

CONTAINER="postgres-age"

echo "🧹 Cleaning up stale PostgreSQL connections..."
echo ""

# Kill idle in transaction connections older than 1 minute
docker exec $CONTAINER psql -U postgres -d postgres <<EOF
SELECT 
    count(*) as killed,
    pg_terminate_backend(pid) as terminated
FROM pg_stat_activity
WHERE datname = 'governance'
  AND pid != pg_backend_pid()
  AND state = 'idle in transaction'
  AND state_change < now() - interval '1 minute';
EOF

# Show current connection status
echo ""
echo "📊 Current connection status:"
docker exec $CONTAINER psql -U postgres -d governance -c "
    SELECT 
        count(*) as total,
        count(*) FILTER (WHERE state = 'active') as active,
        count(*) FILTER (WHERE state = 'idle') as idle,
        count(*) FILTER (WHERE state = 'idle in transaction') as stale
    FROM pg_stat_activity
    WHERE datname = 'governance';
"

echo ""
echo "✅ Cleanup complete"
