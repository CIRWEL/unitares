# Deployment Checklist

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active

---

## Pre-Deployment

### Environment Setup

- [ ] **Python 3.9+ installed**
  ```bash
  python3 --version
  ```

- [ ] **Virtual environment created**
  ```bash
  cd /path/to/governance-mcp-v1
  python3 -m venv .venv
  source .venv/bin/activate
  ```

- [ ] **Dependencies installed**
  ```bash
  pip install -r requirements-full.txt
  ```

- [ ] **Database backend configured**
  - [ ] PostgreSQL (Docker) OR
  - [ ] SQLite (default)
  
  ```bash
  # PostgreSQL
  docker ps | grep postgres
  
  # SQLite (no setup needed)
  ```

- [ ] **Environment variables set** (optional)
  ```bash
  # Create .env file if needed
  cat > .env << EOF
  DB_BACKEND=postgres  # or sqlite
  UNITARES_HTTP_API_TOKEN=your_token_here  # optional
  EOF
  ```

---

## Deployment Steps

### Step 1: Stop Existing Services

- [ ] **Stop any running instances**
  ```bash
  ./scripts/stop_unitares.sh
  ```

- [ ] **Verify nothing is running**
  ```bash
  ps aux | grep -E "(mcp_server|ngrok.*8765)"
  ```

- [ ] **Clean up stale locks**
  ```bash
  rm -f data/.mcp_server_sse.*
  ```

### Step 2: Start Services

- [ ] **Start UNITARES server**
  ```bash
  ./scripts/start_unitares.sh
  ```

- [ ] **Verify server started**
  ```bash
  curl http://localhost:8765/health
  ```

- [ ] **Check server logs**
  ```bash
  tail -20 /tmp/unitares.log
  ```

### Step 3: Configure Ngrok (if using)

- [ ] **Ngrok installed**
  ```bash
  ngrok version
  ```

- [ ] **Ngrok authenticated**
  ```bash
  ngrok config check
  ```

- [ ] **Custom domain configured** (if using)
  - [ ] Domain added in ngrok dashboard
  - [ ] Domain verified

- [ ] **Ngrok tunnel started** (handled by startup script)
  ```bash
  # Verify tunnel is active
  curl http://localhost:4040/api/tunnels | python3 -m json.tool
  ```

### Step 4: Configure MCP Clients

- [ ] **Cursor MCP config updated**
  ```bash
  # Check config
  cat ~/.cursor/mcp.json | python3 -m json.tool
  
  # Should contain:
  # {
  #   "mcpServers": {
  #     "unitares-governance": {
  #       "type": "http",
  #       "url": "http://localhost:8765/mcp"
  #     }
  #   }
  # }
  ```

- [ ] **Claude Desktop config updated** (if using)
  ```bash
  # Location: ~/Library/Application Support/Claude/claude_desktop_config.json
  ```

- [ ] **Clients restarted**
  - [ ] Cursor restarted
  - [ ] Claude Desktop restarted (if using)

### Step 5: Verify Deployment

- [ ] **Health check passes**
  ```bash
  curl http://localhost:8765/health | python3 -m json.tool
  ```

- [ ] **Metrics endpoint accessible**
  ```bash
  curl http://localhost:8765/metrics | head -20
  ```

- [ ] **Dashboard accessible**
  ```bash
  curl http://localhost:8765/dashboard | head -20
  ```

- [ ] **Ngrok tunnel working** (if using)
  ```bash
  curl https://unitares.ngrok.io/health
  ```

- [ ] **MCP tools load in Cursor**
  - [ ] Open Cursor
  - [ ] Check MCP status (Settings → MCP)
  - [ ] Verify "unitares-governance" appears
  - [ ] Test a tool call

---

## Post-Deployment

### Monitoring Setup

- [ ] **Health monitoring configured**
  ```bash
  # Test health monitor
  ./scripts/monitor_health.sh --once
  ```

- [ ] **Log rotation configured** (optional)
  ```bash
  # Set up logrotate or similar
  ```

- [ ] **Backup strategy** (optional)
  ```bash
  # Backup data directory
  tar -czf data_backup_$(date +%Y%m%d).tar.gz data/
  ```

### Documentation

- [ ] **Deployment documented**
  - [ ] Deployment date recorded
  - [ ] Configuration changes noted
  - [ ] Issues encountered documented

- [ ] **Team notified** (if applicable)
  - [ ] Deployment announcement
  - [ ] Configuration changes shared
  - [ ] Access instructions provided

---

## Production Checklist

### Security

- [ ] **API token configured** (if exposing publicly)
  ```bash
  export UNITARES_HTTP_API_TOKEN="your_secure_token"
  ```

- [ ] **Firewall configured**
  - [ ] Only necessary ports open
  - [ ] Access restricted appropriately

- [ ] **HTTPS configured** (if using ngrok)
  - [ ] Ngrok tunnel uses HTTPS
  - [ ] Custom domain has SSL

### Performance

- [ ] **Resource limits set**
  - [ ] Memory limits configured
  - [ ] CPU limits configured (if using containers)

- [ ] **Connection limits configured**
  - [ ] Max concurrent connections set
  - [ ] Timeout values configured

### Reliability

- [ ] **Auto-restart configured**
  - [ ] Launchd service (macOS)
  - [ ] systemd service (Linux)
  - [ ] Docker restart policy

- [ ] **Monitoring alerts configured**
  - [ ] Health check monitoring
  - [ ] Error rate alerts
  - [ ] Uptime monitoring

---

## Rollback Procedure

If deployment fails:

1. **Stop new deployment**
   ```bash
   ./scripts/stop_unitares.sh
   ```

2. **Restore previous version** (if using version control)
   ```bash
   git checkout <previous-commit>
   ```

3. **Restore data** (if needed)
   ```bash
   # Restore from backup
   tar -xzf data_backup_YYYYMMDD.tar.gz
   ```

4. **Restart previous version**
   ```bash
   ./scripts/start_unitares.sh
   ```

5. **Verify rollback**
   ```bash
   curl http://localhost:8765/health
   ```

---

## Quick Reference

### Start Services
```bash
./scripts/start_unitares.sh
```

### Stop Services
```bash
./scripts/stop_unitares.sh
```

### Check Status
```bash
curl http://localhost:8765/health | python3 -m json.tool
```

### View Logs
```bash
tail -f /tmp/unitares.log    # Server
tail -f /tmp/ngrok.log       # Ngrok
```

### Health Monitor
```bash
./scripts/monitor_health.sh --once      # Single check
./scripts/monitor_health.sh            # Continuous
```

### Common Issues
- See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**Last Updated:** January 12, 2026
