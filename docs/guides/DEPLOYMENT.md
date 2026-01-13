# Self-Hosted Deployment Guide

**Created:** December 30, 2025  
**Last Updated:** December 30, 2025  
**Status:** Active

---

## Quick Start

**One-command installation:**
```bash
./install.sh
```

That's it! The script will:
1. Check Docker installation
2. Create `.env` file with secure password
3. Build Docker images
4. Start all services
5. Verify health

**Access:**
- Dashboard: http://localhost:8765/dashboard
- MCP Endpoint: http://localhost:8765/sse
- Health Check: http://localhost:8765/health

---

## System Requirements

- **Docker** 20.10+ and **Docker Compose** 2.0+
- **4GB RAM** minimum (8GB recommended)
- **10GB disk space** for data
- **Port 8765** available (configurable)

---

## Manual Installation

### Step 1: Clone Repository
```bash
git clone <repository-url>
cd governance-mcp-v1
```

### Step 2: Configure Environment
```bash
# Copy example .env (if exists) or create new
cat > .env << EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
HF_TOKEN=your_token_here  # Optional
GOOGLE_AI_API_KEY=your_key_here  # Optional
EOF
```

### Step 3: Start Services
```bash
docker-compose up -d
```

### Step 4: Verify Installation
```bash
curl http://localhost:8765/health
# Should return: {"status": "ok", ...}
```

---

## Configuration

### Environment Variables

**Required:**
- `POSTGRES_PASSWORD` - Database password (auto-generated if not set)

**Optional:**
- `HF_TOKEN` - Hugging Face token for model inference
- `GOOGLE_AI_API_KEY` - Google AI key for Gemini
- `NGROK_API_KEY` - ngrok key for gateway
- `SERVER_PORT` - Server port (default: 8765)
- `SERVER_HOST` - Server host (default: 0.0.0.0)

### Port Configuration

To change the port, edit `docker-compose.yml`:
```yaml
ports:
  - "YOUR_PORT:8765"  # Change YOUR_PORT
```

---

## Data Persistence

**Data is stored in Docker volumes:**
- `postgres_data` - PostgreSQL database
- `redis_data` - Redis cache
- `./data` - Application data (mounted from host)
- `./logs` - Application logs (mounted from host)

**Backup:**
```bash
# Backup PostgreSQL
docker-compose exec postgres pg_dump -U governance governance > backup.sql

# Backup data directory
tar -czf data-backup.tar.gz data/
```

**Restore:**
```bash
# Restore PostgreSQL
docker-compose exec -T postgres psql -U governance governance < backup.sql

# Restore data directory
tar -xzf data-backup.tar.gz
```

---

## Updates

### Update to Latest Version
```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose build
docker-compose up -d
```

### Update Docker Images Only
```bash
docker-compose pull
docker-compose up -d
```

---

## Troubleshooting

### Server Won't Start

**Check logs:**
```bash
docker-compose logs server
```

**Common issues:**
- Port 8765 already in use → Change port in `docker-compose.yml`
- PostgreSQL not ready → Wait 30 seconds, check `docker-compose logs postgres`
- Missing .env → Run `./install.sh` again

### Database Connection Errors

**Check PostgreSQL:**
```bash
docker-compose exec postgres psql -U governance -d governance -c "SELECT 1;"
```

**Reset database (⚠️ deletes all data):**
```bash
docker-compose down -v
docker-compose up -d
```

### Health Check Fails

**Check server status:**
```bash
curl http://localhost:8765/health
docker-compose logs server | tail -50
```

---

## Production Deployment

### Security Checklist

- [ ] Change `POSTGRES_PASSWORD` in `.env`
- [ ] Use reverse proxy (nginx/traefik) with SSL
- [ ] Restrict port 8765 to internal network
- [ ] Set up firewall rules
- [ ] Enable log rotation
- [ ] Set up backups
- [ ] Monitor disk space

### Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Monitoring

**Health check endpoint:**
```bash
curl http://localhost:8765/health
```

**Metrics endpoint:**
```bash
curl http://localhost:8765/metrics
```

---

## Deployment Variants

### Headless Browser with Screen Sharing
For PI (Raspberry Pi) or headless systems with browser access via screen sharing and CLDO keyring:
- **[HEADLESS_BROWSER_DEPLOYMENT.md](HEADLESS_BROWSER_DEPLOYMENT.md)** - Complete setup guide

### Remote Access via ngrok
For public deployment and ChatGPT OAuth integration:
- **[NGROK_DEPLOYMENT.md](NGROK_DEPLOYMENT.md)** - ngrok tunnel setup

## Support

**Documentation:**
- [README.md](../../README.md) - Full documentation
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [MULTI_AGENT_TUTORIAL.md](MULTI_AGENT_TUTORIAL.md) - Usage guide

**Logs:**
```bash
docker-compose logs -f server  # Follow server logs
docker-compose logs postgres   # Database logs
docker-compose logs redis      # Redis logs
```

---

**Status:** Ready for Production Deployment

