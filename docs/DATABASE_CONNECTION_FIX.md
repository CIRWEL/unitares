# Database Connection Pool Fix

**Issue:** PostgreSQL "too many clients already" error  
**Root Cause:** Connection pool exhausted (default max_size=10 too small)  
**Status:** Fixed

---

## What Was Fixed

### 1. Increased Default Connection Pool Size

**Before:**
- `min_size=2`, `max_size=10` (too small for concurrent requests)

**After:**
- `min_size=5`, `max_size=25` (better for concurrent dashboard/API requests)

**File:** `src/db/postgres_backend.py`

### 2. Connection Pool Health Checks

- Periodic health checks every 60 seconds
- Automatic pool recreation on connection failures
- Better error messages

### 3. Diagnostic Script

Created `scripts/fix_database_connections.sh` to:
- Check current PostgreSQL connections
- Show connection states (active/idle/idle in transaction)
- Clean up stale connections
- Verify AGE extension
- Check Redis status

---

## Quick Fix

### Option 1: Increase Pool Size (Recommended)

Set environment variables before starting server:

```bash
export DB_POSTGRES_MAX_CONN=25
export DB_POSTGRES_MIN_CONN=5

# Then restart your MCP server
```

### Option 2: Increase PostgreSQL max_connections

If you need more than 25 connections:

```bash
# Check current setting
docker exec postgres-age psql -U postgres -c "SHOW max_connections;"

# Increase to 200 (adjust as needed)
docker exec postgres-age psql -U postgres -c "ALTER SYSTEM SET max_connections = 200;"
docker restart postgres-age
```

### Option 3: Run Diagnostic Script

```bash
cd /Users/cirwel/projects/governance-mcp-v1
bash scripts/fix_database_connections.sh
```

This will:
- Show current connection usage
- Clean up stale connections
- Check AGE and Redis status
- Provide recommendations

---

## Architecture

### PostgreSQL + AGE

- **PostgreSQL**: Primary database for persistent data
- **AGE (Apache AGE)**: Graph database extension for knowledge graph
- **Connection Pool**: asyncpg pool (now 5-25 connections by default)

### Redis

- **Purpose**: Session cache, rate limiting, distributed locks
- **Fallback**: In-memory cache if Redis unavailable
- **Status**: Optional but recommended

---

## Monitoring

### Check Connection Usage

```bash
# Current connections
docker exec postgres-age psql -U postgres -d governance -c "
    SELECT 
        count(*) as total,
        count(*) FILTER (WHERE state = 'active') as active,
        count(*) FILTER (WHERE state = 'idle') as idle,
        count(*) FILTER (WHERE state = 'idle in transaction') as stale
    FROM pg_stat_activity
    WHERE datname = 'governance';
"

# Check pool size from application
# (Shown in health_check tool response)
```

### Check Redis

```bash
redis-cli ping
redis-cli info stats
redis-cli --scan --pattern "session:*" | wc -l
```

---

## Troubleshooting

### "Too many clients already"

1. **Run diagnostic script:**
   ```bash
   bash scripts/fix_database_connections.sh
   ```

2. **Clean up stale connections:**
   ```bash
   docker exec postgres-age psql -U postgres -d governance -c "
       SELECT pg_terminate_backend(pid)
       FROM pg_stat_activity
       WHERE datname = 'governance'
         AND state = 'idle in transaction'
         AND state_change < now() - interval '5 minutes';
   "
   ```

3. **Increase pool size:**
   ```bash
   export DB_POSTGRES_MAX_CONN=50
   # Restart server
   ```

4. **Increase PostgreSQL max_connections:**
   ```bash
   docker exec postgres-age psql -U postgres -c "ALTER SYSTEM SET max_connections = 200;"
   docker restart postgres-age
   ```

### Redis Not Available

- **Impact**: Session persistence lost across restarts (minor)
- **Fallback**: Automatic in-memory cache
- **Fix**: `brew services start redis`

### AGE Extension Missing

- **Impact**: Knowledge graph queries fail
- **Check**: `docker exec postgres-age psql -U postgres -d governance -c "SELECT * FROM pg_extension WHERE extname = 'age';"`
- **Fix**: Install AGE extension (see database setup docs)

---

## Best Practices

1. **Use connection context managers:**
   ```python
   async with db.acquire() as conn:
       await conn.fetchval("SELECT 1")
   # Connection automatically released
   ```

2. **Set appropriate pool size:**
   - Small deployments: `max_size=10-20`
   - Medium deployments: `max_size=25-50`
   - Large deployments: `max_size=50-100` + increase PostgreSQL `max_connections`

3. **Monitor connection usage:**
   - Run diagnostic script regularly
   - Check for "idle in transaction" connections (leaks)
   - Monitor pool size vs. PostgreSQL max_connections

4. **Restart server after pool size changes:**
   - Pool size is set at initialization
   - Must restart to apply new `DB_POSTGRES_MAX_CONN` value

---

## Files Changed

- `src/db/postgres_backend.py` - Increased default pool size (5-25)
- `scripts/fix_database_connections.sh` - New diagnostic script
- `docs/DATABASE_CONNECTION_FIX.md` - This document

---

**The connection pool issue should now be resolved. Restart your MCP server to apply the new defaults.**
