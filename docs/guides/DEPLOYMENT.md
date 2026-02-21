# Self-Hosted Deployment Guide

**Last Updated:** February 2026
**Transport:** Streamable HTTP (`/mcp/` endpoint)
**Port:** 8767 (default)

---

## Prerequisites

- **Python 3.11+**
- **PostgreSQL 16** with [Apache AGE](https://age.apache.org/) extension
- **macOS** (launchd) or **Linux** (systemd)

---

## Quick Start (macOS)

### 1. Install Dependencies

```bash
brew install postgresql@16
pip install -r requirements-full.txt
```

### 2. Set Up PostgreSQL + AGE

Use the AGE Docker image for the database:

```bash
docker compose -f scripts/age/docker-compose.age.yml up -d
```

Or install AGE natively — see `db/postgres/README.md`.

Then apply the schema:

```bash
psql postgresql://postgres:postgres@localhost:5432/governance -f db/postgres/schema.sql
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 4. Run the Server

```bash
# Foreground (for testing)
python src/mcp_server.py --port 8767

# Or install as launchd service (persistent)
cp config/com.unitares.governance-mcp.plist.example ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
# Edit the plist to match your paths and credentials
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### 5. Verify

```bash
curl -s http://localhost:8767/mcp/ -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"health_check","arguments":{}},"id":1}'
```

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POSTGRES_URL` | — | PostgreSQL connection URL (required) |
| `DB_POSTGRES_MIN_CONN` | `2` | Min pool connections |
| `DB_POSTGRES_MAX_CONN` | `10` | Max pool connections |
| `UNITARES_KNOWLEDGE_BACKEND` | `auto` | Knowledge graph backend (`age`, `postgres`, `auto`) |
| `UNITARES_DIALECTIC_BACKEND` | `postgres` | Dialectic session backend |

---

## Service Management (macOS)

```bash
# Start/restart
make restart

# View logs
make logs       # stdout
make logs-err   # stderr

# Or manually:
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

---

## Public Access via ngrok

For remote access, set up an ngrok tunnel:

```bash
ngrok http --url=your-domain.ngrok.io --basic-auth=user:pass 8767
```

Or install as a launchd service — see the ngrok plist example in `config/`.

See also: [NGROK_DEPLOYMENT.md](NGROK_DEPLOYMENT.md)

---

## Production Checklist

- [ ] Use a strong `POSTGRES_PASSWORD`
- [ ] Use reverse proxy (nginx/traefik) with SSL for public access
- [ ] Restrict port 8767 to internal network or use ngrok
- [ ] Enable log rotation
- [ ] Set up PostgreSQL backups
- [ ] Monitor disk space

---

## Backup & Restore

```bash
# Backup PostgreSQL
pg_dump -U postgres governance > backup.sql

# Restore
psql -U postgres governance < backup.sql
```

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues.

```bash
# Check server is running
launchctl list | grep unitares

# Check logs
tail -f data/logs/mcp_server.log
tail -f data/logs/mcp_server_error.log
```
