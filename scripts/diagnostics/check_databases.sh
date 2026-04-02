#!/bin/bash
# Quick database status check

set -euo pipefail

DB_POSTGRES_URL="${DB_POSTGRES_URL:-postgresql://postgres:postgres@localhost:5432/governance}"

echo "📊 Database Status Check"
echo "======================="
echo ""

# PostgreSQL
echo "🐘 PostgreSQL:"
if command -v psql >/dev/null 2>&1 && psql "$DB_POSTGRES_URL" -Atqc "SELECT 1" >/dev/null 2>&1; then
    echo "  ✅ Reachable via DB_POSTGRES_URL"
    echo "  URL: $DB_POSTGRES_URL"
    psql "$DB_POSTGRES_URL" -c "
        SELECT 
            count(*) as connections,
            count(*) FILTER (WHERE state = 'active') as active,
            count(*) FILTER (WHERE state = 'idle') as idle
        FROM pg_stat_activity
        WHERE datname = 'governance';
    " 2>/dev/null || echo "  ⚠️  Connection issue"
    
    echo ""
    echo "  Extensions:"
    psql "$DB_POSTGRES_URL" -c "
        SELECT extname, extversion 
        FROM pg_extension 
        WHERE extname IN ('age', 'vector');
    " 2>/dev/null | grep -E "(age|vector)" || echo "  ⚠️  AGE/vector not found"

    echo ""
    echo "  Knowledge Graph Consistency:"
    KG_COUNTS="$(
        psql "$DB_POSTGRES_URL" -Atq <<'SQL' 2>/dev/null
LOAD 'age';
SET search_path = ag_catalog, core, audit, public;
WITH durable AS (
    SELECT count(*)::bigint AS durable_count, max(created_at)::text AS durable_max
    FROM knowledge.discoveries
),
graph AS (
    SELECT count(*)::bigint AS graph_count
    FROM cypher('governance_graph', $$ MATCH (d:Discovery) RETURN d $$) AS (d agtype)
)
SELECT durable_count || '|' || graph_count || '|' || COALESCE(durable_max, '')
FROM durable, graph;
SQL
    )"
    if [ -n "$KG_COUNTS" ]; then
        IFS='|' read -r DURABLE_COUNT GRAPH_COUNT DURABLE_MAX <<<"$KG_COUNTS"
        echo "  Durable discoveries: $DURABLE_COUNT"
        echo "  AGE discoveries: $GRAPH_COUNT"
        echo "  Durable max created_at: ${DURABLE_MAX:-unknown}"
        if [ "$DURABLE_COUNT" != "$GRAPH_COUNT" ]; then
            echo "  ❌ Drift detected between knowledge.discoveries and AGE graph"
        else
            echo "  ✅ Durable rows and AGE graph are in sync"
        fi
    else
        echo "  ⚠️  Could not query AGE discovery counts"
    fi
else
    echo "  ❌ PostgreSQL not reachable at $DB_POSTGRES_URL"
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
