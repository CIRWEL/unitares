# Claude Code CLI - Governance Monitor Guide

Since Claude Code doesn't have native MCP support like Cursor or Claude Desktop, you can use governance through either MCP SSE (recommended) or direct Python API.

## 🎯 Recommended: MCP SSE Approach (Unified)

**Why:** Single source of truth - canonical MCP handler interpretations, no custom warning layers

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Simple usage (connects to SSE server)
./scripts/governance_mcp_cli.sh

# With parameters
./scripts/governance_mcp_cli.sh "my_agent_id" "what I did" 0.7
```

**Benefits:**
- ✅ Canonical MCP handler feedback (same as Cursor sees)
- ✅ Shared state with all MCP clients in real-time
- ✅ No custom interpretation layers
- ✅ Access to all 50 MCP tools
- ✅ Supportive, not punitive feedback

**Requirements:**
- SSE server must be running (check with `lsof -i :8765`)
- Start with: `./scripts/start_sse_server.sh`

## Alternative: Direct Python API

### Option 1: Bash Script (Direct API)

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# Simple usage with defaults
./scripts/governance_cli.sh

# With custom parameters
./scripts/governance_cli.sh "my_agent_id" "what I did" 0.7
```

### Option 2: Python Helper

```bash
cd /Users/cirwel/projects/governance-mcp-v1

# As a script
python3 scripts/cli_helper.py "my_agent_id" "completed task" 0.7

# Or import in Python
python3 -c "
from scripts.cli_helper import quick_check
result = quick_check('my_agent', 'task done', 0.5)
print(result)
"
```

### Option 3: Direct Python (Most Control)

```python
from src.governance_monitor import UNITARESMonitor

# Create monitor
monitor = UNITARESMonitor(agent_id='claude_code_cli_20251210')

# Process update
result = monitor.process_update({
    'response_text': 'Summary of what you did',
    'complexity': 0.5  # 0.0-1.0
})

# Check decision
print(f"Action: {result['decision']['action']}")
print(f"Reason: {result['decision']['reason']}")
print(f"Coherence: {result['metrics']['coherence']:.3f}")
```

## Available Integration Methods

| Method | Transport | Best For | Status |
|--------|-----------|----------|--------|
| **stdio MCP** | Standard MCP (command) | Claude Desktop, single-client | ✅ Available |
| **SSE MCP** | HTTP/SSE (url) | Cursor, multi-client | ✅ Available |
| **Direct Python** | Native API | Claude Code CLI, scripts | ✅ Available |
| **HTTP/REST** | Via SSE server | Custom integrations | ✅ Available |

## Key Differences from MCP

| Feature | MCP (Cursor/Desktop) | Claude Code CLI |
|---------|---------------------|-----------------|
| Setup | MCP config JSON | Direct script/Python calls |
| API | `process_agent_update` tool | `UNITARESMonitor.process_update()` |
| Integration | Automatic via MCP | Manual via scripts |
| Tools | 49+ MCP tools available | Direct Python API |
| Multi-client | SSE server (shared state) | Can use SSE server too! |

## Available Scripts

### 1. governance_cli.sh
**Location:** `/Users/cirwel/projects/governance-mcp-v1/scripts/governance_cli.sh`

**Usage:**
```bash
./scripts/governance_cli.sh [agent_id] [response_text] [complexity]
```

**Features:**
- Nice formatted output
- Colored decision display
- Metric interpretation
- Auto-saves API key for new agents

### 2. cli_helper.py
**Location:** `/Users/cirwel/projects/governance-mcp-v1/scripts/cli_helper.py`

**Usage:**
```bash
python3 scripts/cli_helper.py <agent_id> [response_text] [complexity]
```

**Features:**
- Can be used as script or imported module
- Returns full result dict
- Pretty printing included

## Example Workflow

```bash
# 1. Navigate to project
cd /Users/cirwel/projects/governance-mcp-v1

# 2. First call - get your API key
./scripts/governance_cli.sh "claude_code_cirwel_$(date +%Y%m%d)" \
    "Initial setup and exploration" 0.3

# 3. Save the API key shown (you'll need it for future integrations)

# 4. Continue logging work
./scripts/governance_cli.sh "claude_code_cirwel_20251210" \
    "Implemented feature X, refactored Y" 0.7

# 5. Check metrics anytime
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor(agent_id='claude_code_cirwel_20251210')
print(m.get_current_metrics())
"
```

## Complexity Guidelines

Use these values for the complexity parameter:

- **0.1-0.3**: Simple operations, routine tasks, low cognitive load
- **0.4-0.6**: Moderate operations, standard task complexity
- **0.7-0.9**: Complex operations, high cognitive load, multi-step reasoning
- **1.0**: Maximum complexity, system-wide operations, novel problem-solving

## Understanding Results

### Decision Actions
- `proceed`: Continue working - you're on track
- `pause`: System suggests taking a break

### Key Metrics
- **Coherence (0-1)**: How well your work hangs together
  - < 0.5: Consider simplifying approach
  - ≥ 0.5: Work is well-organized

- **Attention Score (0-1)**: Cognitive load indicator
  - > 0.5: High complexity - take breaks
  - ≤ 0.5: Manageable load

- **Energy (E)**: How engaged your work feels (0-1)
- **Integrity (I)**: Consistency of approach (0-1)
- **Entropy (S)**: How scattered things are (0-2)
- **Void (V)**: Accumulated strain (-2 to +2)

## Automation Ideas

### Auto-log after commits
```bash
# In .git/hooks/post-commit
cd /Users/cirwel/projects/governance-mcp-v1
./scripts/governance_cli.sh "claude_code_$(whoami)_$(date +%Y%m%d)" \
    "$(git log -1 --pretty=%B)" 0.5
```

### Periodic check-ins
```bash
# Add to crontab for hourly checks
0 * * * * cd /Users/cirwel/projects/governance-mcp-v1 && \
  ./scripts/governance_cli.sh "periodic_check_$(date +%Y%m%d_%H)" \
    "Hourly activity checkpoint" 0.3
```

## Troubleshooting

### Import errors
```bash
# Make sure PYTHONPATH includes project root
export PYTHONPATH="/Users/cirwel/projects/governance-mcp-v1:$PYTHONPATH"
```

### Script not found
```bash
# Ensure you're in the right directory
cd /Users/cirwel/projects/governance-mcp-v1
ls -la scripts/governance_cli.sh  # Should show the script
```

### Permission denied
```bash
# Make scripts executable
chmod +x scripts/governance_cli.sh
chmod +x scripts/cli_helper.py
```

## Advanced: Using the SSE Server from CLI

For Claude Code instances that want to share state with other clients (Cursor, Claude Desktop, etc.), you can also interact with the SSE server via HTTP:

### Check if SSE server is running
```bash
curl http://127.0.0.1:8765/
# Should return: Not Found (server is up, just no root endpoint)

lsof -i :8765
# Should show Python process listening on port 8765
```

### Start SSE server if not running
```bash
cd /Users/cirwel/projects/governance-mcp-v1
./scripts/start_sse_server.sh

# Or run in background
nohup python3 src/mcp_server_sse.py --port 8765 > /tmp/mcp_sse.log 2>&1 &
```

### Use SSE server from Python
```python
# The MCP tools are available via the SSE server too
# You can use the same Python API - it will share state with other clients
from src.governance_monitor import UNITARESMonitor

# This uses the shared state if SSE server is running
monitor = UNITARESMonitor(agent_id='claude_code_shared')
result = monitor.process_update({'response_text': 'work', 'complexity': 0.5})
```

### Benefits of SSE server
- **Shared state**: Multiple clients see same data
- **Multi-agent awareness**: See who else is connected
- **Persistent**: Survives client restarts
- **Real peer review**: Agents can actually review each other

See [SSE_SERVER.md](SSE_SERVER.md) for full SSE documentation.

## Next Steps

1. **Read the main guide**: [START_HERE.md](START_HERE.md)
2. **Understand the system**: [AI_ASSISTANT_GUIDE.md](reference/AI_ASSISTANT_GUIDE.md)
3. **Explore tools**: Check `src/mcp_handlers/` for all available functionality
4. **View metrics**: Your session data is in `data/governance_history_<agent_id>.csv`
5. **Multi-client setup**: [SSE_SERVER.md](SSE_SERVER.md) and [SSE_VS_STDIO.md](guides/SSE_VS_STDIO.md)

## Full Python API

For advanced usage, the full Python API is available:

```python
from src.governance_monitor import UNITARESMonitor

monitor = UNITARESMonitor(agent_id='your_id')

# Process update
result = monitor.process_update({
    'response_text': 'what you did',
    'complexity': 0.5
})

# Get metrics
metrics = monitor.get_current_metrics()

# Get history
history = monitor.get_history()

# Export data
monitor.export_session_data()
```

See the source code in `src/governance_monitor.py` for all available methods.

---

**Last Updated:** 2025-12-10
