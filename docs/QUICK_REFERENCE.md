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

### Cursor/IDE Freezing (NEW! v2.1)
**Cause:** Duplicate MCP servers or stale lock files causing contention.

**Solution - One Command Fix:**
```bash
/Users/cirwel/scripts/fix_cursor_freeze.sh
```

**Or Manual:**
```bash
# Kill all MCP servers
pkill -9 -f mcp_server

# Clean stale locks
python3 ~/projects/governance-mcp-v1/src/lock_cleanup.py

# Restart your IDE
```

**Prevention:** v2.1 includes auto-healing locks that self-recover from stale locks. This should prevent future freezes automatically.

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

## ⭐ High-Value Tools (New!)

### Test Decisions Without Persisting (simulate_update)

```python
# Python API
result = monitor.simulate_update({
    'parameters': [...],
    'response_text': "Risky operation test",
    'complexity': 0.9
})
print(f"Would get: {result['decision']['action']}")  # State unchanged!
```

### Runtime Threshold Adjustment

```python
# Get current thresholds
from src.runtime_config import get_thresholds, set_thresholds
current = get_thresholds()
print(current['risk_approve_threshold'])  # 0.30

# Make system more conservative
set_thresholds({'risk_approve_threshold': 0.25})
# No restart needed!
```

### Fleet Health Overview

```bash
# Via Python
python3 -c "
import sys
sys.path.insert(0, '/Users/cirwel/projects/governance-mcp-v1')
from src.mcp_server_std import agent_metadata
active = [a for a, m in agent_metadata.items() if m.status == 'active']
print(f'Active agents: {len(active)}')
"

# Or use aggregate_metrics MCP tool (via client)
# Returns: mean_risk, mean_coherence, health_breakdown, decision_distribution
```

### Register New Agent (CLI)

```bash
# New simplified registration
python3 scripts/register_agent.py my_agent_id

# Then log work
python3 scripts/agent_self_log.py --agent-id my_agent_id \
  "Initial session" --complexity 0.3
```

**CLI Logging Now Fully Functional!** ✅ (Fixed 2025-11-24)
- ✅ Governance history maintained across calls
- ✅ Coherence evolves properly
- ✅ Update counter increments
- ✅ State persists to disk
- ✅ Export works
- Each call loads existing state, processes update, saves state

---

## 📚 Related Documentation

- **Architecture**: `docs/guides/AGENT_ID_ARCHITECTURE.md`
- **CLI Logging Guide**: `docs/guides/CLI_LOGGING_GUIDE.md` ⭐
- **CLI Architecture Analysis**: `docs/analysis/CLI_LOGGING_ARCHITECTURE.md`
- **Troubleshooting**: `docs/guides/TROUBLESHOOTING.md`
- **MCP Setup**: `MCP_SETUP.md`
- **Full Guide**: `README.md`

---

## 🆕 New in v2.1 (November 25, 2025)

### Auto-Healing Infrastructure
- **Stale lock cleanup** - Automatic recovery from crashed processes
- **Loop detection** - Prevents infinite agent update loops
- **Agent spawning** - Track parent/child relationships with API keys
- **72 process capacity** - Doubled from 36 for better concurrency
- **One-command recovery** - `/Users/cirwel/scripts/fix_cursor_freeze.sh`

### New Tools & Scripts
```bash
# Cursor freeze recovery
/Users/cirwel/scripts/fix_cursor_freeze.sh

# Enhanced locking tests
python3 /Users/cirwel/scripts/test_enhanced_locking.py

# MCP protocol verification
python3 /Users/cirwel/scripts/test_mcp_json_rpc.py

# System diagnostics
/Users/cirwel/scripts/diagnose_cursor_mcp.sh
```

See `/Users/cirwel/scripts/cursor_implementations_summary.md` for complete feature details.

---

**Last Updated:** November 25, 2025
**Quick Tip:** Bookmark this file for fast lookups!
