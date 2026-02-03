#!/bin/bash
# Kill idle PostgreSQL connections that are older than 5 minutes

CONTAINER="postgres-age"

echo "🧹 Killing idle connections older than 5 minutes..."
echo ""

docker exec $CONTAINER psql -U postgres -d postgres <<EOF
-- Kill idle connections (not idle in transaction) older than 5 minutes
SELECT 
    count(*) as killed,
    pg_terminate_backend(pid) as terminated
FROM pg_stat_activity
WHERE datname = 'governance'
  AND pid != pg_backend_pid()
  AND state = 'idle'
  AND state_change < now() - interval '5 minutes';
EOF

echo ""
echo "📊 Remaining connections:"
docker exec $CONTAINER psql -U postgres -d governance -c "
    SELECT 
        count(*) as total,
        count(*) FILTER (WHERE state = 'active') as active,
        count(*) FILTER (WHERE state = 'idle') as idle
    FROM pg_stat_activity
    WHERE datname = 'governance';
"

echo ""
echo "✅ Done"
