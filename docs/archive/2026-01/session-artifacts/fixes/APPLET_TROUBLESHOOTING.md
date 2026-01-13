# RestartGovernanceMCP.app Troubleshooting

**Created:** January 1, 2026  
**Status:** Applet should work with launchd service

---

## Applet Overview

**What it does:**
- Uses `launchctl kickstart` to restart the `com.unitares.governance-mcp` service
- Opens Terminal to show restart progress
- Verifies server is responding

**AppleScript code:**
```applescript
tell application "Terminal"
    do script "launchctl kickstart -k gui/" & (do shell script "id -u") & "/com.unitares.governance-mcp && sleep 2 && curl -s http://127.0.0.1:8765/sse | head -5 && echo '' && echo '✅ Governance MCP restarted successfully' && sleep 3 && exit"
    activate
end tell
```

---

## Requirements

**Launchd service must be:**
1. ✅ Configured: `~/Library/LaunchAgents/com.unitares.governance-mcp.plist`
2. ✅ Loaded: `launchctl list | grep governance`
3. ✅ Running: Service should be active

**Check service status:**
```bash
launchctl list com.unitares.governance-mcp
```

---

## Common Issues

### Issue 1: Service Not Loaded

**Symptoms:** Applet runs but server doesn't restart

**Fix:**
```bash
# Load the service
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# Or reload if already loaded
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### Issue 2: Permission Denied

**Symptoms:** Terminal shows permission errors

**Fix:**
- Check applet has necessary permissions in System Settings
- Grant "Automation" permissions if prompted
- Check `NSAppleEventsUsageDescription` in Info.plist

### Issue 3: Server Running Manually

**Symptoms:** Multiple server processes, applet doesn't affect manual process

**Fix:**
```bash
# Stop manual process first
ps aux | grep mcp_server_sse.py
kill <PID>

# Then use applet to restart via launchd
```

---

## Manual Test

Test the command directly:
```bash
launchctl kickstart -k gui/$(id -u)/com.unitares.governance-mcp
```

Should restart the server and show new PID.

---

## Verification

After restart, verify:
```bash
# Check server is running
curl http://127.0.0.1:8765/health

# Check SEE ALSO sections are loaded
curl -X POST http://127.0.0.1:8765/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"describe_tool","arguments":{"tool_name":"get_governance_metrics","include_full_description":true,"lite":false}}' \
  | jq '.result.tool.description' | grep -c "SEE ALSO"
```

Should return: `1`

---

**Status:** ✅ Applet should work if launchd service is configured  
**Action:** Verify service is loaded and running

