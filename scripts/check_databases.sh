#!/bin/bash
# Quick database status check

echo "📊 Database Status Check"
echo "======================="
echo ""

# PostgreSQL
echo "🐘 PostgreSQL:"
if docker ps | grep -q postgres-age; then
    echo "  ✅ Container running"
    docker exec postgres-age psql -U postgres -d governance -c "
        SELECT 
            count(*) as connections,
            count(*) FILTER (WHERE state = 'active') as active,
            count(*) FILTER (WHERE state = 'idle') as idle
        FROM pg_stat_activity
        WHERE datname = 'governance';
    " 2>/dev/null || echo "  ⚠️  Connection issue"
    
    echo ""
    echo "  Extensions:"
    docker exec postgres-age psql -U postgres -d governance -c "
        SELECT extname, extversion 
        FROM pg_extension 
        WHERE extname IN ('age', 'vector');
    " 2>/dev/null | grep -E "(age|vector)" || echo "  ⚠️  AGE/vector not found"
else
    echo "  ❌ Container not running"
fi

echo ""
echo "🔴 Redis:"
if redis-cli ping > /dev/null 2>&1; then
    echo "  ✅ Running"
    echo "  Keys: $(redis-cli --scan --pattern 'session:*' 2>/dev/null | wc -l | tr -d ' ') session keys"
else
    echo "  ⚠️  Not running (using in-memory fallback)"
fi

echo ""
echo "✅ Check complete"
