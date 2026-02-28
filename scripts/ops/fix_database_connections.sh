#!/bin/bash
# Fix PostgreSQL connection pool issues and check Redis/AGE

set -e

echo "🔧 Fixing Database Connection Issues"
echo "===================================="
echo ""

# Check PostgreSQL
echo "📊 Checking PostgreSQL..."
if docker ps | grep -q postgres-age; then
    echo "✅ PostgreSQL container is running"
    
    # Check current connections
    echo ""
    echo "Current PostgreSQL connections:"
    docker exec postgres-age psql -U postgres -d governance -c "
        SELECT 
            count(*) as total_connections,
            count(*) FILTER (WHERE state = 'active') as active,
            count(*) FILTER (WHERE state = 'idle') as idle,
            count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
        FROM pg_stat_activity
        WHERE datname = 'governance';
    "
    
    # Check max_connections setting
    echo ""
    echo "PostgreSQL max_connections setting:"
    docker exec postgres-age psql -U postgres -d governance -c "SHOW max_connections;"
    
    # Kill idle connections older than 5 minutes
    echo ""
    echo "🧹 Cleaning up stale connections..."
    docker exec postgres-age psql -U postgres -d governance -c "
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = 'governance'
          AND state = 'idle in transaction'
          AND state_change < now() - interval '5 minutes';
    " || echo "No stale connections to clean"
    
    # Check AGE extension
    echo ""
    echo "🔍 Checking Apache AGE extension..."
    docker exec postgres-age psql -U postgres -d governance -c "
        SELECT extname, extversion 
        FROM pg_extension 
        WHERE extname = 'age';
    " || echo "⚠️  AGE extension not found"
    
else
    echo "❌ PostgreSQL container not running"
    echo "   Start with: docker start postgres-age"
fi

echo ""
echo "📊 Checking Redis..."
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis is running"
    echo ""
    echo "Redis info:"
    redis-cli info stats | grep -E "(total_connections|rejected_connections)" || true
    echo ""
    echo "Redis keys (sample):"
    redis-cli --scan --pattern "session:*" | head -5 || echo "No session keys found"
else
    echo "⚠️  Redis not running (will use in-memory fallback)"
    echo "   Start with: brew services start redis"
fi

echo ""
echo "✅ Database check complete"
echo ""
echo "💡 Recommendations:"
echo "   1. Increase PostgreSQL max_connections if needed:"
echo "      docker exec postgres-age psql -U postgres -c \"ALTER SYSTEM SET max_connections = 200;\""
echo "      docker restart postgres-age"
echo ""
echo "   2. Increase connection pool size (set in environment):"
echo "      export DB_POSTGRES_MAX_CONN=20"
echo ""
echo "   3. Restart MCP server to apply new pool settings"
