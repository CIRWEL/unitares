# Quick Reference Card

**Fast lookups for common governance operations**

---

## 🎯 Common Tasks

### I want to...

#### Get Server Info
```bash
# Check MCP server processes
ps aux | grep mcp_server_std.py | grep -v grep

# Check PID file
cat data/.mcp_server.pid

# Clean up zombies
./scripts/cleanup_zombie_mcp_servers.sh
```

#### List All Agents
```bash
# Via data file (fastest)
cat data/agent_metadata.json | python3 -m json.tool

# Quick summary
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total: {len(data)}')
for aid, meta in data.items():
    print(f'  {meta[\"status\"]:10} {aid} ({meta[\"total_updates\"]} updates)')
"
```

#### Register New Agent
```bash
# Interactive (recommended)
python3 scripts/claude_code_bridge.py --status

# You'll be prompted for agent ID selection

# Non-interactive (auto-generate)
python3 scripts/claude_code_bridge.py --non-interactive --status
```

#### Check Agent Status
```bash
# Via bridge (if agent was created via bridge)
python3 scripts/claude_code_bridge.py --status --agent-id <your_agent_id>

# Via data file (works for all agents)
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
agent = data.get('your_agent_id', {})
print(json.dumps(agent, indent=2))
"
```

#### Resume Previous Session
```bash
# Check cached session
cat .governance_session

# Resume (just run bridge - it auto-detects session)
python3 scripts/claude_code_bridge.py --status

# Clear session and start fresh
rm .governance_session
python3 scripts/claude_code_bridge.py --status
```

#### Log an Interaction
```bash
# Simple
python3 scripts/claude_code_bridge.py --log "response text here"

# With complexity override
python3 scripts/claude_code_bridge.py --log "response text" --complexity 0.7

# Specify agent ID
python3 scripts/claude_code_bridge.py --log "response text" --agent-id my_agent
```

#### Export History
```bash
# Export via bridge
python3 scripts/claude_code_bridge.py --export --agent-id <your_agent_id>

# View CSV (if exists)
cat ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data/governance_history_<agent_id>.csv
```

#### Run Tests
```bash
# Full system demo
python3 demo_complete_system.py

# Bridge test sequence
python3 scripts/claude_code_bridge.py --test
```

---

## 🔧 Troubleshooting

### "No monitor found for agent"
**Cause:** Agent exists in metadata but not loaded in current process.

**Solution:** Process an update first:
```bash
python3 scripts/claude_code_bridge.py --log "test" --agent-id <agent_id>
```

### "Agent ID collision detected"
**Cause:** Agent ID is already active.

**Solution:** Either:
1. Resume existing session (recommended)
2. Use different agent ID
3. Archive old agent first

### Too Many Zombie Processes
**Cause:** Multiple script executions spawning servers.

**Solution:**
```bash
# Clean up zombies
./scripts/cleanup_zombie_mcp_servers.sh

# Check remaining
ps aux | grep mcp_server | grep -v grep
```

### Generic Agent ID Warning
**Cause:** Using `claude_code_cli`, `test`, `demo`, etc.

**Solution:** Let agent ID manager generate unique ID or use:
```bash
python3 scripts/claude_code_bridge.py --non-interactive
```

---

## 📊 Quick Data Lookups

### Active Agents
```bash
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
active = [aid for aid, meta in data.items() if meta['status'] == 'active']
print(f'Active agents ({len(active)}):')
for aid in active:
    print(f'  - {aid}')
"
```

### Agent Update Counts
```bash
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
sorted_agents = sorted(data.items(), key=lambda x: x[1]['total_updates'], reverse=True)
for aid, meta in sorted_agents[:10]:
    print(f'{meta[\"total_updates\"]:4d} updates: {aid}')
"
```

### Recent Activity
```bash
cat data/agent_metadata.json | python3 -c "
import json, sys
from datetime import datetime
data = json.load(sys.stdin)
sorted_agents = sorted(data.items(), key=lambda x: x[1]['last_update'], reverse=True)
for aid, meta in sorted_agents[:10]:
    print(f'{meta[\"last_update\"]}: {aid}')
"
```

---

## 🚀 Workflow Examples

### Starting a New Session
```bash
# 1. Check if previous session exists
cat .governance_session

# 2. Start bridge (auto-resumes or prompts for new ID)
python3 scripts/claude_code_bridge.py --status

# 3. Verify agent ID
# (Printed in bridge output)
```

### Monitoring a Conversation
```bash
# Log each response as you go
python3 scripts/claude_code_bridge.py --log "response 1"
python3 scripts/claude_code_bridge.py --log "response 2"

# Check status
python3 scripts/claude_code_bridge.py --status

# Export at end
python3 scripts/claude_code_bridge.py --export > session_history.json
```

### Automation Script
```python
#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from scripts.claude_code_bridge import ClaudeCodeBridge

# Non-interactive bridge
bridge = ClaudeCodeBridge(interactive=False)

# Log interactions
for response in my_responses:
    result = bridge.log_interaction(response)
    if not result['success']:
        print(f"Error: {result.get('error')}")

# Export
history = bridge.export_history()
```

---

## 📚 Related Documentation

- **Architecture**: `docs/guides/AGENT_ID_ARCHITECTURE.md`
- **Troubleshooting**: `docs/guides/TROUBLESHOOTING.md`
- **MCP Setup**: `MCP_SETUP.md`
- **Full Guide**: `README.md`

---

**Last Updated:** November 20, 2025
**Quick Tip:** Bookmark this file for fast lookups!
