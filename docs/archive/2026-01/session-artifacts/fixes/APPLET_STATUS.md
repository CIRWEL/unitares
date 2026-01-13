# RestartGovernanceMCP.app Status

**Created:** January 1, 2026  
**Status:** ✅ Applet works correctly

---

## Applet Functionality

**What it does:**
1. Executes `launchctl kickstart` to restart the launchd service
2. Opens Terminal window to show progress
3. Verifies server restart with curl test
4. Shows success message

**AppleScript:**
```applescript
tell application "Terminal"
    do script "launchctl kickstart -k gui/" & (do shell script "id -u") & "/com.unitares.governance-mcp && sleep 2 && curl -s http://127.0.0.1:8765/sse | head -5 && echo '' && echo '✅ Governance MCP restarted successfully' && sleep 3 && exit"
    activate
end tell
```

---

## How It Works

1. **Kills old process:** `launchctl kickstart -k` stops the current service
2. **Restarts service:** Launchd automatically restarts it (KeepAlive=true)
3. **Shows progress:** Terminal window displays restart status
4. **Verifies:** Curl test confirms server is responding

---

## Requirements

✅ **Launchd service configured:**
- `~/Library/LaunchAgents/com.unitares.governance-mcp.plist`
- Symlinked to project: `scripts/com.unitares.governance-mcp.plist`

✅ **Service loaded:**
```bash
launchctl list | grep governance
```

✅ **Service running:**
- Managed by launchd with KeepAlive=true
- Auto-restarts if it crashes

---

## Usage

**Double-click the app:**
- `/Users/cirwel/Desktop/RestartGovernanceMCP.app`

**What happens:**
1. Terminal window opens
2. Shows restart command executing
3. Displays server response test
4. Shows success message
5. Terminal closes after 3 seconds

---

## Troubleshooting

**If applet doesn't work:**

1. **Check service is loaded:**
   ```bash
   launchctl list com.unitares.governance-mcp
   ```

2. **Reload service if needed:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
   ```

3. **Check permissions:**
   - System Settings → Privacy & Security → Automation
   - Grant Terminal.app permission if prompted

4. **Manual restart test:**
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.unitares.governance-mcp
   ```

---

## Verification

After using applet, verify:
```bash
# Check server is running
curl http://127.0.0.1:8765/health

# Check SEE ALSO sections loaded
curl -X POST http://127.0.0.1:8765/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"describe_tool","arguments":{"tool_name":"get_governance_metrics","include_full_description":true,"lite":false}}' \
  | jq '.result.tool.description' | grep -c "SEE ALSO"
```

Should return: `1`

---

**Status:** ✅ Applet works correctly  
**Action:** Double-click to restart server anytime

