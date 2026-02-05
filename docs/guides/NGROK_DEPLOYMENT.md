# ngrok Deployment Guide

**Last Updated:** February 4, 2026
**Tier Required:** ngrok Hobby or higher
**Reserved Domain:** unitares.ngrok.io ✅
**Target:** ChatGPT MCP, Gemini, public demos

---

## Overview

Deploy your UNITARES MCP server publicly via ngrok for:
- ✅ ChatGPT OAuth testing
- ✅ Multi-model client demos
- ✅ Investor presentations
- ✅ Remote collaboration

**ngrok Hobby tier benefits:**
- Reserved domains (stable URL)
- Custom subdomains
- Higher rate limits
- Better for production demos

---

## Quick Start

### Deploy Server

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Start SSE server (if not already running)
python src/mcp_server_sse.py --port 8765 &

# Deploy via ngrok (uses reserved domain automatically)
./scripts/deploy_ngrok.sh
```

**Output:**
```
🚀 UNITARES MCP Server - ngrok Deployment
==========================================

✅ SSE server running on port 8765
✅ ngrok installed: ngrok version 3.34.1
✅ ngrok configured
📍 Using reserved domain: unitares.ngrok.io

🌐 Starting ngrok tunnel...

🔗 Your UNITARES MCP Server is available at:
   https://unitares.ngrok.io/sse
```

---

## ChatGPT MCP Configuration

### Step 1: Add MCP Connector

In ChatGPT settings → Connectors:

```json
{
  "servers": {
    "unitares": {
      "url": "https://unitares.ngrok.io/sse",
      "description": "UNITARES AI Governance Framework",
      "auth": {
        "type": "oauth",
        "provider": "google",
        "client_id": "YOUR_GOOGLE_CLIENT_ID",
        "client_secret": "YOUR_GOOGLE_CLIENT_SECRET",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["openid", "email", "profile"]
      }
    }
  }
}
```

### Step 2: Test Connection

In ChatGPT:
```
Can you list available governance tools?
```

**Expected:** ChatGPT prompts for OAuth login, then lists ~25 tools.

---

## Production Deployment

### Using launchd (Auto-Start)

Your SSE server already has launchd integration:

```bash
# Check status
launchctl list | grep governance

# Logs
tail -f ~/Library/Logs/governance-mcp-sse.log
```

### ngrok as a Service

Create persistent ngrok tunnel:

```bash
# Install ngrok service (macOS)
ngrok service install \
  --config /Users/cirwel/Library/Application\ Support/ngrok/ngrok.yml

# Start service
ngrok service start

# Check status
ngrok service status
```

**Alternative:** Use tmux/screen for persistence:

```bash
# Create persistent session
tmux new -s ngrok

# Run deploy script
./scripts/deploy_ngrok.sh unitares-governance.ngrok-free.app

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t ngrok
```

---

## Security Considerations

### 1. OAuth Secret Management

**Set server OAuth secret:**
```bash
# In .env
GOVERNANCE_OAUTH_SECRET="your-production-secret-here-change-from-default"

# Restart SSE server
pkill -f mcp_server_sse.py
python src/mcp_server_sse.py --port 8765
```

### 2. ngrok Security

**Enable IP restrictions (Hobby tier):**
```yaml
# ~/Library/Application Support/ngrok/ngrok.yml
version: "3"
agent:
  authtoken: YOUR_TOKEN
tunnels:
  unitares:
    proto: http
    addr: 8765
    domain: unitares-governance.ngrok-free.app
    inspect: false  # Disable request inspection for privacy
    ip_restriction:
      allow_cidrs:
        - 0.0.0.0/0  # Allow all (or restrict to specific IPs)
```

### 3. Rate Limiting

**Check ngrok dashboard:**
- Monitor requests/min
- Set up alerts for unusual traffic
- ngrok Hobby: 20,000 requests/month

**SSE server has built-in rate limiting:**
- 100 requests/minute per IP (configurable)
- Circuit breaker for suspicious patterns

---

## Custom Domain (Optional)

### Using Your Own Domain

With ngrok Hobby, you can use your own domain:

```bash
# 1. Add CNAME record in your DNS:
#    governance.yourdomain.com → [your-ngrok-id].ngrok-free.app

# 2. Reserve domain in ngrok:
ngrok domains create governance.yourdomain.com

# 3. Deploy:
./scripts/deploy_ngrok.sh governance.yourdomain.com
```

**Result:** `https://governance.yourdomain.com/sse`

---

## Monitoring

### ngrok Dashboard

Access: https://dashboard.ngrok.com

**Key Metrics:**
- Active tunnels
- Request volume
- Error rates
- Geographic distribution

### Server Logs

```bash
# SSE server logs
tail -f data/logs/mcp_sse.log

# Filter for OAuth
tail -f data/logs/mcp_sse.log | grep -i oauth

# Filter for errors
tail -f data/logs/mcp_sse.log | grep -i error
```

### Health Check

```bash
# From remote
curl https://unitares-governance.ngrok-free.app/health

# Expected response:
{
  "status": "healthy",
  "version": "2.4.0",
  "transport": "SSE",
  "uptime_seconds": 3600
}
```

---

## Troubleshooting

### "Tunnel not found"

**Cause:** Reserved domain not created or authtoken missing.

**Fix:**
```bash
# Create domain
ngrok domains create unitares-governance.ngrok-free.app

# Or use random domain
./scripts/deploy_ngrok.sh
```

---

### "Connection refused"

**Cause:** SSE server not running.

**Fix:**
```bash
# Check if running
lsof -ti:8765

# Start if not running
cd /Users/cirwel/projects/governance-mcp-v1
python src/mcp_server_sse.py --port 8765 &
```

---

### "OAuth failed"

**Cause:** Invalid OAuth configuration or missing scopes.

**Fix:**
1. Verify OAuth provider credentials
2. Check scopes include `openid`, `email`, `profile`
3. Verify redirect URI is whitelisted
4. Check server logs for OAuth errors

---

### "Rate limit exceeded"

**Cause:** ngrok Hobby limit reached (20k req/month).

**Upgrade to:**
- ngrok Pro: 100k req/month
- ngrok Business: Unlimited

**Or optimize:**
- Cache responses
- Reduce polling frequency
- Use webhooks instead of polling

---

## Cost Analysis

### ngrok Hobby ($8/month)

**Limits:**
- 20,000 requests/month (~27 req/hour sustained)
- Reserved domains: 1
- Simultaneous tunnels: 3

**Good for:**
- Testing/demos
- Small user base (<10 daily users)
- Investor presentations

### ngrok Pro ($29/month)

**Limits:**
- 100,000 requests/month (~135 req/hour sustained)
- Reserved domains: 5
- Simultaneous tunnels: 10
- IP restrictions
- Custom domains

**Good for:**
- Production pilot (10-50 users)
- Multi-model testing
- Team collaboration

### When to Self-Host

**Threshold:** >100k requests/month or >50 concurrent users

**Alternative:** Deploy to:
- Railway.app (starts free, $5/month)
- Fly.io ($0-$5/month)
- Google Cloud Run (pay-per-use)
- Your own VPS (Digital Ocean $6/month)

---

## Testing OAuth Flow

### 1. Start Tunnel

```bash
./scripts/deploy_ngrok.sh  # Uses unitares.ngrok.io automatically
```

### 2. Configure ChatGPT

Add MCP connector with your ngrok URL.

### 3. Test Identity

In ChatGPT:
```
Call the status tool to check my identity
```

**Expected response:**
```json
{
  "bound": true,
  "agent_id": "oauth_google_a3f8c2e1",
  "oauth": true,
  "oauth_provider": "google"
}
```

### 4. Test Governance

```
Process a governance update:
- I analyzed the codebase structure
- Complexity: 0.6
- Confidence: 0.7
```

**Expected:** OAuth identity auto-injected, governance cycle runs.

---

## Production Checklist

Before showing to investors/users:

- [x] Reserved domain created (unitares.ngrok.io ✅)
- [ ] OAuth secret set (`GOVERNANCE_OAUTH_SECRET`)
- [ ] SSE server running (`lsof -ti:8765`)
- [ ] launchd auto-start enabled
- [ ] ngrok tunnel running (`./scripts/deploy_ngrok.sh`)
- [ ] Health check passes (`curl https://unitares.ngrok.io/health`)
- [ ] OAuth flow tested (ChatGPT login works)
- [ ] Tool discovery works (`list_tools`)
- [ ] Governance cycle works (`process_agent_update`)
- [ ] Logs monitored (`tail -f data/logs/mcp_sse.log`)

---

## Next Steps

1. **Deploy:** (domain already reserved ✅)
   ```bash
   ./scripts/deploy_ngrok.sh
   ```

2. **Test with ChatGPT:**
   - Add MCP connector (use https://unitares.ngrok.io/sse)
   - Complete OAuth flow
   - Call governance tools

3. **Monitor:**
   - Check ngrok dashboard: https://dashboard.ngrok.com
   - Watch server logs: `tail -f data/logs/mcp_sse.log`
   - Track OAuth success rate

---

## Support

**Issues?**
- ngrok docs: https://ngrok.com/docs
- UNITARES troubleshooting: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- OAuth guide: [OAUTH_IDENTITY.md](OAUTH_IDENTITY.md)
- Embeddings guide: [HUGGINGFACE_EMBEDDINGS.md](HUGGINGFACE_EMBEDDINGS.md)

**Questions?**
- ngrok community: https://ngrok.com/slack
- UNITARES GitHub issues

---

**Status:** ✅ Ready for deployment
**Verified:** December 20, 2025
**ngrok Tier:** Hobby or higher required
