# Headless Browser Deployment with Screen Sharing

**Configuration:** PI (Raspberry Pi or similar) with browser access through screen sharing (headless) using CLDO as keyring.

---

## Overview

This deployment model enables:
- **Headless operation** - No physical display required
- **Browser access** - Full web interface via screen sharing
- **Secure credential management** - CLDO keyring for authentication
- **Remote monitoring** - Access dashboard and MCP endpoints remotely

---

## Architecture

```
┌─────────────────────────────────────────┐
│         PI (Headless System)            │
│                                         │
│  ┌─────────────────────────────────┐  │
│  │   Governance MCP Server          │  │
│  │   (Port 8765)                    │  │
│  └─────────────────────────────────┘  │
│                                         │
│  ┌─────────────────────────────────┐  │
│  │   Headless Browser               │  │
│  │   (Chrome/Firefox headless)      │  │
│  └─────────────────────────────────┘  │
│                                         │
│  ┌─────────────────────────────────┐  │
│  │   Screen Sharing Service         │  │
│  │   (VNC/X11 forwarding)           │  │
│  └─────────────────────────────────┘  │
│                                         │
│  ┌─────────────────────────────────┐  │
│  │   CLDO Keyring                  │  │
│  │   (Credential Management)       │  │
│  └─────────────────────────────────┘  │
└─────────────────────────────────────────┘
         │
         │ Screen Share / Remote Access
         │
┌─────────────────────────────────────────┐
│      Remote Client (Browser)             │
│      - Dashboard Access                  │
│      - MCP Endpoint Access               │
└─────────────────────────────────────────┘
```

---

## Setup Instructions

### Step 1: Install Dependencies on PI

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install headless browser dependencies
sudo apt install -y chromium-browser chromium-chromedriver

# Install screen sharing (VNC)
sudo apt install -y tigervnc-standalone-server tigervnc-common

# Install CLDO keyring (if not already installed)
# Follow CLDO installation instructions for your system
```

### Step 2: Configure CLDO Keyring

```bash
# Initialize CLDO keyring for governance credentials
cldo keyring init --name governance-mcp

# Store credentials
cldo keyring set governance-mcp POSTGRES_PASSWORD
cldo keyring set governance-mcp HF_TOKEN
cldo keyring set governance-mcp GOOGLE_AI_API_KEY

# Verify
cldo keyring list governance-mcp
```

### Step 3: Configure Environment Variables

Create `.env` file that loads from CLDO keyring:

```bash
#!/bin/bash
# .env loader script (loads from CLDO keyring)

export POSTGRES_PASSWORD=$(cldo keyring get governance-mcp POSTGRES_PASSWORD)
export HF_TOKEN=$(cldo keyring get governance-mcp HF_TOKEN)
export GOOGLE_AI_API_KEY=$(cldo keyring get governance-mcp GOOGLE_AI_API_KEY)

# Standard configuration
export SERVER_PORT=8765
export SERVER_HOST=0.0.0.0
export NODE_ENV=production
```

### Step 4: Setup Screen Sharing (VNC)

```bash
# Create VNC password
vncpasswd

# Start VNC server (display :1)
vncserver :1 -geometry 1920x1080 -depth 24

# Configure VNC to start on boot
sudo systemctl enable vncserver@:1.service
```

### Step 5: Configure Headless Browser

Create browser startup script:

```bash
#!/bin/bash
# scripts/start_headless_browser.sh

# Load environment from CLDO keyring
source .env

# Start headless Chrome with screen sharing support
chromium-browser \
  --headless \
  --disable-gpu \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-dev-shm-usage \
  http://localhost:8765/dashboard &

# Or use Firefox headless
# firefox --headless --remote-debugging-port=9222 http://localhost:8765/dashboard &
```

### Step 6: Start Governance MCP Server

```bash
# Start SSE server
python3 src/mcp_server_sse.py --host 0.0.0.0 --port 8765

# Or use Docker Compose (loads .env automatically)
docker-compose up -d
```

---

## Access Methods

### Method 1: SSH Tunnels (No Router Config Needed) ✅ Recommended

**CLDO keyring was the blocker** - Now that credentials are managed via CLDO, you can use SSH tunnels which **don't require router configuration**.

```bash
# Create SSH tunnel (no router port forwarding needed!)
ssh -L 8765:localhost:8765 -L 5901:localhost:5901 -L 9222:localhost:9222 user@pi-ip-address

# Then access locally:
# - Dashboard: http://localhost:8765/dashboard
# - VNC: vncviewer localhost:5901
# - Browser Debug: http://localhost:9222
```

**Benefits:**
- ✅ No router configuration needed
- ✅ More secure (all traffic encrypted via SSH)
- ✅ Works from anywhere (just need SSH access)
- ✅ No firewall rules needed on router

### Method 2: Direct Access (Requires Router Config)

**Only needed if you want direct HTTP access without SSH:**

```bash
# Requires router port forwarding:
# - External Port 8765 → PI Port 8765
# - External Port 5901 → PI Port 5901
# - External Port 9222 → PI Port 9222

# Then access directly:
http://your-public-ip:8765/dashboard
vncviewer your-public-ip:5901
```

**Router Configuration Needed:**
- Port forwarding rules on your router
- Firewall rules (if router has firewall)
- Dynamic DNS (if IP changes)

### Method 3: VPN (No Router Config Needed)

If PI is on VPN:
```bash
# Connect to VPN first, then access directly
http://pi-vpn-ip:8765/dashboard
```

**No router config needed** - VPN handles routing.

---

## Router Configuration: Do You Need It?

### Short Answer: **No, if using SSH tunnels** ✅

**CLDO keyring was the blocker** - It solved credential management. Router config is **only needed** if you want direct HTTP access without SSH.

### When Router Config is NOT Needed

✅ **SSH Tunnel Method** (Recommended)
- Use `ssh -L` to create tunnels
- All traffic encrypted via SSH
- No router port forwarding needed
- Works from anywhere with SSH access

✅ **VPN Method**
- PI on VPN network
- Access via VPN IP
- No router config needed

✅ **Local Network Only**
- Access from same network
- No external access needed
- No router config needed

### When Router Config IS Needed

❌ **Direct External Access**
- Want to access `http://your-public-ip:8765` directly
- Need router port forwarding
- Need firewall rules
- Less secure (exposes ports publicly)

**Recommendation:** Use SSH tunnels instead - more secure and no router config needed!

---

## Security Considerations

### 1. Firewall Configuration (On PI Only)

**Note:** This is PI firewall, NOT router firewall. Router config only needed for direct external access.

```bash
# Allow only necessary ports (on PI)
sudo ufw allow 8765/tcp    # MCP server
sudo ufw allow 5901/tcp    # VNC (restrict to VPN or SSH only)
sudo ufw allow 9222/tcp    # Browser debugging (restrict to VPN or SSH only)
sudo ufw allow 22/tcp      # SSH (required for tunnels)
sudo ufw enable
```

**If using SSH tunnels only:**
```bash
# Only allow SSH - everything else via tunnel
sudo ufw allow 22/tcp
sudo ufw enable
# Ports 8765, 5901, 9222 only accessible via SSH tunnel
```

### 2. SSH Access

```bash
# Use SSH keys instead of passwords
ssh-copy-id user@pi-ip-address

# Disable password authentication
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
sudo systemctl restart sshd
```

### 3. CLDO Keyring Security

```bash
# Ensure keyring has proper permissions
chmod 600 ~/.cldo/keyring/governance-mcp

# Use strong master password for CLDO keyring
cldo keyring change-password
```

### 4. HTTPS/SSL (Recommended)

```bash
# Use reverse proxy with SSL (nginx)
# See DEPLOYMENT.md for nginx configuration

# Or use Let's Encrypt
sudo certbot --nginx -d your-domain.com
```

---

## Monitoring & Maintenance

### Check Service Status

```bash
# MCP Server
curl http://localhost:8765/health

# VNC Server
vncserver -list

# Browser Process
ps aux | grep chromium
```

### View Logs

```bash
# MCP Server logs
tail -f data/logs/sse_server.log

# System logs
journalctl -u governance-mcp -f
```

### Restart Services

```bash
# Restart MCP server
docker-compose restart server

# Restart VNC
vncserver -kill :1
vncserver :1

# Restart browser
pkill chromium
./scripts/start_headless_browser.sh
```

---

## Troubleshooting

### Issue: Browser Won't Start Headless

**Solution:**
```bash
# Check display
export DISPLAY=:1

# Test headless mode
chromium-browser --headless --dump-dom http://localhost:8765/dashboard
```

### Issue: CLDO Keyring Not Found

**Solution:**
```bash
# Verify CLDO installation
which cldo

# Check keyring exists
cldo keyring list

# Reinitialize if needed
cldo keyring init --name governance-mcp
```

### Issue: VNC Connection Refused

**Solution:**
```bash
# Check VNC is running
vncserver -list

# Check firewall
sudo ufw status

# Test locally first
vncviewer localhost:5901
```

### Issue: Dashboard Not Accessible

**Solution:**
```bash
# Check server is running
curl http://localhost:8765/health

# Check port is open
sudo netstat -tlnp | grep 8765

# Check firewall
sudo ufw status
```

---

## Integration with Existing Setup

### Using with Docker Compose

```yaml
# docker-compose.yml additions
services:
  server:
    environment:
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - HF_TOKEN=${HF_TOKEN}
    # Load from CLDO keyring via .env script
```

### Using with Systemd Service

```ini
# /etc/systemd/system/governance-mcp.service
[Unit]
Description=Governance MCP Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/governance-mcp-v1
EnvironmentFile=/home/pi/governance-mcp-v1/.env
ExecStart=/usr/bin/python3 src/mcp_server_sse.py --host 0.0.0.0 --port 8765
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Benefits of This Setup

1. **No Physical Display Required** - PI can run headless
2. **Secure Credential Management** - CLDO keyring keeps secrets safe
3. **Remote Access** - Monitor and manage from anywhere
4. **Browser Debugging** - Full DevTools access remotely
5. **Screen Sharing** - Visual debugging and monitoring
6. **Production Ready** - Suitable for deployment scenarios

---

## Summary: Router Config vs CLDO Keyring

### What CLDO Keyring Solved (The Blocker)

**Before CLDO:**
- ❌ Credentials hardcoded in `.env` files
- ❌ Manual credential management
- ❌ Security risk (credentials in files)
- ❌ Deployment blocked by credential setup

**After CLDO:**
- ✅ Secure credential storage
- ✅ Automated credential loading
- ✅ No credentials in files
- ✅ Deployment unblocked

### Router Configuration Status

**Router config is OPTIONAL** - Only needed for direct external HTTP access.

**Recommended approach (no router config):**
```bash
# Use SSH tunnels - no router config needed!
ssh -L 8765:localhost:8765 user@pi-ip-address
# Then access: http://localhost:8765/dashboard
```

**Router config only needed if:**
- You want direct `http://public-ip:8765` access
- You don't want to use SSH tunnels
- You're okay with exposing ports publicly

## Next Steps

1. **Test locally** - Verify all components work
2. **Use SSH tunnels** - No router config needed ✅
3. **Configure PI firewall** - Restrict access appropriately
4. **Set up SSL** - Use HTTPS for production (if direct access)
5. **Monitor logs** - Set up log rotation
6. **Backup configuration** - Save CLDO keyring backups securely

---

**Related Documentation:**
- [DEPLOYMENT.md](DEPLOYMENT.md) - General deployment guide
- [NGROK_DEPLOYMENT.md](NGROK_DEPLOYMENT.md) - Remote access via ngrok
- [DASHBOARD_SETUP.md](DASHBOARD_SETUP.md) - Dashboard configuration
