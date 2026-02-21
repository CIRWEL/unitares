# Troubleshooting Guide

**Last Updated:** February 7, 2026

---

## Quick Diagnostics

### Check Server Status
```bash
# Health check
curl http://localhost:8767/health | python3 -m json.tool

# Check processes
ps aux | grep -E "(mcp_server|ngrok)"

# Check logs
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```

---

## Common Issues

### Issue 1: Server Won't Start

**Symptoms:**
- Error: "Port 8767 already in use"
- Server process not responding

**Solutions:**

1. **Check what's using the port:**
   ```bash
   lsof -i :8767
   ```

2. **Kill existing processes:**
   ```bash
   pkill -f "mcp_server"
   pkill -f "ngrok.*8767"
   ```

3. **Restart via launchd (macOS production):**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   ```

4. **Force start:**
   ```bash
   python3 src/mcp_server.py --port 8767 --host 0.0.0.0 --force
   ```

---

### Issue 2: Ngrok Not Connecting

**Symptoms:**
- `https://your-domain.ngrok.io/mcp` returns 404
- Ngrok log shows "connection refused"

**Solutions:**

1. **Check server is running:**
   ```bash
   curl http://localhost:8767/health
   ```

2. **Verify ngrok tunnel:**
   ```bash
   curl http://localhost:4040/api/tunnels | python3 -m json.tool | grep -A 5 "8767"
   ```

3. **Restart ngrok:**
   ```bash
   pkill -f "ngrok.*8767"
   ngrok http 8767 --url=your-domain.ngrok.io
   ```

4. **Check ngrok authentication:**
   ```bash
   ngrok config check
   ```

---

### Issue 3: MCP Tools Not Loading in Client

**Symptoms:**
- Client shows "MCP server not connected"
- Tools don't appear

**Solutions:**

1. **Verify MCP config:**
   ```bash
   # Claude Code
   cat ~/.claude.json | python3 -m json.tool

   # Cursor
   cat ~/.cursor/mcp.json | python3 -m json.tool
   ```

2. **Check server is accessible:**
   ```bash
   curl http://localhost:8767/health
   ```

3. **Restart your client** (Cursor: Cmd+Q then reopen, Claude Desktop: quit and reopen)

4. **Check client logs** for connection errors

---

### Issue 4: Database Connection Errors

**Symptoms:**
- PostgreSQL connection errors
- Error: "Failed to initialize database"

**Solutions:**

1. **Check PostgreSQL container:**
   ```bash
   docker ps | grep postgres-age
   docker exec postgres-age pg_isready -U postgres
   ```

2. **Start if not running:**
   ```bash
   docker start postgres-age
   ```

3. **Check environment variables:**
   ```bash
   echo $DB_POSTGRES_URL  # Should be set
   ```

4. **Check container logs:**
   ```bash
   docker logs postgres-age --tail 50
   ```

---

### Issue 5: Redis Connection Errors

**Symptoms:**
- Warning: "Redis unavailable"
- Session binding not persisting across restarts

**Solutions:**

1. **Check Redis:**
   ```bash
   redis-cli ping  # Should return PONG
   ```

2. **Restart Redis:**
   ```bash
   brew services restart redis
   ```

3. **Note:** Redis is optional. If unavailable, the server falls back to in-memory session cache (sessions won't persist across restarts).

---

### Issue 6: High Memory Usage

**Symptoms:**
- Server becomes slow
- High memory consumption

**Solutions:**

1. **Check memory usage:**
   ```bash
   ps aux | grep mcp_server | awk '{print $4, $11}'
   ```

2. **Restart server:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   ```

---

## Debugging Steps

### Step 1: Check Basic Connectivity

```bash
# Server health
curl http://localhost:8767/health

# Dashboard
curl http://localhost:8767/dashboard | head -20
```

### Step 2: Check Processes

```bash
# List all related processes
ps aux | grep -E "(mcp_server|ngrok|python.*governance)"

# Check port usage
lsof -i :8767
```

### Step 3: Check Logs

```bash
# Server logs
tail -50 data/logs/mcp_server.log

# Error logs
tail -50 data/logs/mcp_server_error.log

# Look for errors
grep -i error data/logs/mcp_server.log | tail -20
```

### Step 4: Verify Configuration

```bash
# MCP config
cat ~/.claude.json | python3 -m json.tool

# Environment variables
env | grep -E "(DB_|UNITARES_|NGROK_)"

# Python path
which python3
python3 --version
```

---

## Recovery Procedures

### Service Restart

```bash
# macOS launchd (production)
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Verify
curl http://localhost:8767/health
```

### Database Reset (DANGEROUS)

**WARNING: This will delete all agent data!**

```bash
# Backup first!
docker exec postgres-age pg_dump -U postgres governance > backup_$(date +%Y%m%d).sql

# Reset PostgreSQL
docker exec postgres-age psql -U postgres -c "DROP DATABASE IF EXISTS governance;"
docker exec postgres-age psql -U postgres -c "CREATE DATABASE governance;"

# Restart server (schema auto-creates)
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

---

## Getting Help

### Documentation

1. [START_HERE.md](START_HERE.md) — Agent onboarding
2. [MCP_SETUP.md](MCP_SETUP.md) — Client configuration
3. [DEPLOYMENT.md](DEPLOYMENT.md) — Deployment guide
4. [database_architecture.md](../database_architecture.md) — Database details

### Health Monitoring

```bash
# MCP health check tool
curl http://localhost:8767/health | python3 -m json.tool
```

---

*Last updated: February 7, 2026*
