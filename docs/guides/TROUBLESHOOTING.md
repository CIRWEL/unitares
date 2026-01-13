# Troubleshooting Guide

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Quick Diagnostics

### Check Server Status
```bash
# Health check
curl http://localhost:8765/health | python3 -m json.tool

# Check processes
ps aux | grep -E "(mcp_server_sse|ngrok)"

# Check logs
tail -f /tmp/unitares.log
tail -f /tmp/ngrok.log
```

### Run Health Monitor
```bash
# Single check
./scripts/monitor_health.sh --once

# Continuous monitoring
./scripts/monitor_health.sh
```

---

## Common Issues

### Issue 1: Server Won't Start

**Symptoms:**
- `./scripts/start_unitares.sh` fails
- Error: "SSE server is already running"
- Error: "Port 8765 already in use"

**Solutions:**

1. **Clean up stale locks:**
   ```bash
   cd /Users/cirwel/projects/governance-mcp-v1
   rm -f data/.mcp_server_sse.*
   ```

2. **Kill existing processes:**
   ```bash
   ./scripts/stop_unitares.sh
   # Or manually:
   pkill -f "mcp_server_sse"
   pkill -f "ngrok.*8765"
   ```

3. **Check port availability:**
   ```bash
   lsof -i :8765
   # If something is using it, kill that process
   ```

4. **Use --force flag:**
   ```bash
   python3 src/mcp_server_sse.py --port 8765 --host 0.0.0.0 --force
   ```

---

### Issue 2: Ngrok Not Connecting

**Symptoms:**
- `https://unitares.ngrok.io/mcp` returns 404
- Ngrok log shows "connection refused"
- Error: ERR_NGROK_3200

**Solutions:**

1. **Check server is running:**
   ```bash
   curl http://localhost:8765/health
   ```

2. **Verify ngrok is pointing to correct port:**
   ```bash
   curl http://localhost:4040/api/tunnels | python3 -m json.tool | grep -A 5 "8765"
   ```

3. **Restart ngrok:**
   ```bash
   pkill -f "ngrok.*8765"
   ngrok http 8765 --url=unitares.ngrok.io --log=stdout > /tmp/ngrok.log 2>&1 &
   ```

4. **Check ngrok authentication:**
   ```bash
   ngrok config check
   ```

5. **Verify custom domain:**
   - Check ngrok dashboard: https://dashboard.ngrok.com
   - Ensure `unitares.ngrok.io` is configured
   - Check Traffic Policy isn't blocking requests

---

### Issue 3: MCP Tools Not Loading in Cursor

**Symptoms:**
- Cursor shows "MCP server not connected"
- Tools don't appear in Cursor
- Connection errors in Cursor logs

**Solutions:**

1. **Verify MCP config:**
   ```bash
   cat ~/.cursor/mcp.json | python3 -m json.tool
   ```
   
   Should contain:
   ```json
   {
     "mcpServers": {
       "unitares-governance": {
         "type": "http",
         "url": "http://localhost:8765/mcp"
       }
     }
   }
   ```

2. **Check server is accessible:**
   ```bash
   curl http://localhost:8765/health
   curl http://localhost:8765/mcp
   ```

3. **Restart Cursor:**
   - Quit Cursor completely (Cmd+Q)
   - Wait 5 seconds
   - Reopen Cursor

4. **Check Cursor logs:**
   - Open Cursor Settings → MCP
   - Check for connection errors
   - Look for "unitares-governance" in server list

5. **Try SSE endpoint instead:**
   ```json
   {
     "mcpServers": {
       "unitares-governance": {
         "url": "http://localhost:8765/sse"
       }
     }
   }
   ```

---

### Issue 4: Database Connection Errors

**Symptoms:**
- Error: "Failed to initialize database"
- PostgreSQL connection errors
- SQLite lock errors

**Solutions:**

1. **Check PostgreSQL (if using):**
   ```bash
   # Check if Docker container is running
   docker ps | grep postgres
   
   # Start if not running
   docker start postgres-age
   
   # Check connection
   docker exec postgres-age pg_isready -U postgres
   ```

2. **Check SQLite (if using):**
   ```bash
   # Check for lock files
   ls -la data/*.db*
   
   # Remove stale locks (be careful!)
   # Only if you're sure no process is using the DB
   ```

3. **Check environment variables:**
   ```bash
   echo $DB_BACKEND  # Should be "postgres" or "sqlite"
   ```

4. **Verify database permissions:**
   ```bash
   ls -la data/
   # Ensure write permissions
   ```

---

### Issue 5: High Memory Usage

**Symptoms:**
- Server becomes slow
- High memory consumption
- Out of memory errors

**Solutions:**

1. **Check memory usage:**
   ```bash
   ps aux | grep mcp_server_sse | awk '{print $4, $11}'
   ```

2. **Restart server:**
   ```bash
   ./scripts/stop_unitares.sh
   ./scripts/start_unitares.sh
   ```

3. **Check for memory leaks:**
   - Monitor memory over time
   - Check logs for errors
   - Review connection count (too many connections?)

4. **Reduce connection limits:**
   - Edit `src/mcp_server_sse.py`
   - Reduce `limit_concurrency` in uvicorn config

---

### Issue 6: Lock File Conflicts

**Symptoms:**
- Error: "SSE server is already running"
- Lock file exists but process not running
- Can't start server

**Solutions:**

1. **Check if process is actually running:**
   ```bash
   ps aux | grep mcp_server_sse
   ```

2. **Check lock file:**
   ```bash
   cat data/.mcp_server_sse.lock
   # Note the PID
   ```

3. **Verify PID is running:**
   ```bash
   ps -p <PID>
   ```

4. **Clean up stale locks:**
   ```bash
   rm -f data/.mcp_server_sse.*
   ```

5. **Use --force flag:**
   ```bash
   python3 src/mcp_server_sse.py --force
   ```

---

### Issue 7: Ngrok Tunnel Drops

**Symptoms:**
- Ngrok tunnel disconnects frequently
- Connection errors from remote clients
- Tunnel URL changes

**Solutions:**

1. **Use custom domain (prevents URL changes):**
   ```bash
   ngrok http 8765 --url=unitares.ngrok.io
   ```

2. **Check ngrok status:**
   ```bash
   curl http://localhost:4040/api/tunnels
   ```

3. **Monitor ngrok logs:**
   ```bash
   tail -f /tmp/ngrok.log
   ```

4. **Restart ngrok:**
   ```bash
   pkill -f ngrok
   ngrok http 8765 --url=unitares.ngrok.io --log=stdout > /tmp/ngrok.log 2>&1 &
   ```

5. **Check network stability:**
   - Ensure stable internet connection
   - Check firewall settings
   - Verify ngrok account limits

---

## Debugging Steps

### Step 1: Check Basic Connectivity

```bash
# Server health
curl http://localhost:8765/health

# Metrics
curl http://localhost:8765/metrics | head -20

# Dashboard
curl http://localhost:8765/dashboard | head -20
```

### Step 2: Check Processes

```bash
# List all related processes
ps aux | grep -E "(mcp_server|ngrok|python.*governance)"

# Check port usage
lsof -i :8765
lsof -i :4040  # ngrok web interface
```

### Step 3: Check Logs

```bash
# Server logs
tail -50 /tmp/unitares.log

# Ngrok logs
tail -50 /tmp/ngrok.log

# Look for errors
grep -i error /tmp/unitares.log | tail -20
```

### Step 4: Verify Configuration

```bash
# MCP config
cat ~/.cursor/mcp.json

# Environment variables
env | grep -E "(DB_|UNITARES_|NGROK_)"

# Python path
which python3
python3 --version
```

### Step 5: Test Individual Components

```bash
# Test server startup
cd /Users/cirwel/projects/governance-mcp-v1
source .venv/bin/activate
python3 src/mcp_server_sse.py --port 8765 --host 0.0.0.0 --force

# Test ngrok separately
ngrok http 8765 --url=unitares.ngrok.io
```

---

## Recovery Procedures

### Complete Reset

If everything is broken:

```bash
# 1. Stop everything
./scripts/stop_unitares.sh

# 2. Clean up
rm -f data/.mcp_server_sse.*
rm -f /tmp/unitares.log
rm -f /tmp/ngrok.log

# 3. Verify nothing is running
ps aux | grep -E "(mcp_server|ngrok.*8765)"

# 4. Restart
./scripts/start_unitares.sh

# 5. Verify
curl http://localhost:8765/health
```

### Database Reset (DANGEROUS - Only if needed)

**⚠️ WARNING: This will delete all agent data!**

```bash
# Backup first!
cp -r data/ data_backup_$(date +%Y%m%d_%H%M%S)/

# Stop server
./scripts/stop_unitares.sh

# Reset database (SQLite)
rm -f data/governance.db*

# Or reset PostgreSQL
docker exec postgres-age psql -U postgres -c "DROP DATABASE IF EXISTS governance;"
docker exec postgres-age psql -U postgres -c "CREATE DATABASE governance;"

# Restart
./scripts/start_unitares.sh
```

---

## Getting Help

### Check Documentation

1. **README.md** - Overview and quick start
2. **docs/guides/MCP_SETUP.md** - MCP configuration
3. **docs/guides/START_HERE.md** - Agent onboarding
4. **docs/guides/TROUBLESHOOTING.md** - This file

### Check Logs

```bash
# Server logs
tail -f /tmp/unitares.log

# Ngrok logs
tail -f /tmp/ngrok.log

# System logs (macOS)
log show --predicate 'process == "Python"' --last 1h
```

### Health Monitoring

```bash
# Run health monitor
./scripts/monitor_health.sh --once

# Check metrics
curl http://localhost:8765/metrics | grep unitares_server
```

---

## Prevention

### Best Practices

1. **Use startup scripts:**
   ```bash
   ./scripts/start_unitares.sh  # Always use this
   ```

2. **Monitor regularly:**
   ```bash
   ./scripts/monitor_health.sh  # Run in background
   ```

3. **Check logs periodically:**
   ```bash
   tail -20 /tmp/unitares.log  # Quick check
   ```

4. **Keep backups:**
   ```bash
   # Backup data directory regularly
   tar -czf data_backup_$(date +%Y%m%d).tar.gz data/
   ```

5. **Update dependencies:**
   ```bash
   # Keep packages updated
   pip install --upgrade -r requirements-full.txt
   ```

---

## Still Stuck?

1. **Check all logs** (server, ngrok, system)
2. **Verify configuration** (MCP config, environment variables)
3. **Test components individually** (server, ngrok, database)
4. **Check network** (firewall, connectivity)
5. **Review recent changes** (what changed before issue started?)

---

**Last Updated:** January 12, 2026
