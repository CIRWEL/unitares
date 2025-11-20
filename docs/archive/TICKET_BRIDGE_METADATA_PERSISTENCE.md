# 🐛 TICKET: Bridge Doesn't Persist Agent Metadata

**Priority:** Medium
**Type:** Bug / Enhancement
**Component:** `scripts/claude_code_bridge.py`
**Discovered:** 2025-11-20 by claude_code_cli_discovery
**Affects:** Agent registration and metadata tracking

---

## Problem

The `claude_code_bridge.py` logs governance updates to CSV but **does NOT persist agent metadata** to `data/agent_metadata.json`.

### Current Behavior
```python
# Bridge uses old MCP server class
from src.mcp_server import GovernanceMCPServer  # ❌ No metadata persistence

bridge = ClaudeCodeBridge(agent_id="claude_cli_user_123")
bridge.log_interaction("response text")
# ✅ Logs to CSV: governance_history_claude_cli_user_123.csv
# ❌ Does NOT create entry in agent_metadata.json
```

### Expected Behavior
```python
# Bridge should register agent in metadata system
bridge = ClaudeCodeBridge(agent_id="claude_cli_user_123")
bridge.log_interaction("response text")
# ✅ Logs to CSV
# ✅ Creates/updates agent_metadata.json
# ✅ Records lifecycle events
# ✅ Tracks total_updates, status, etc.
```

---

## Impact

**What Works:**
- ✅ Governance decisions logged
- ✅ Metrics tracked in CSV
- ✅ Risk scores calculated

**What's Missing:**
- ❌ Agent not visible in `list_agents`
- ❌ No lifecycle tracking (created, paused, resumed)
- ❌ No status management (active, archived, deleted)
- ❌ Can't use metadata-based tools (`get_agent_metadata`, etc.)

---

## Reproduction

```bash
# 1. Run bridge with unique agent ID
python3 scripts/claude_code_bridge.py --log "test" --agent-id test_ticket_123

# 2. Check CSV (works)
ls ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents/governance-monitor-mcp/data/ | grep test_ticket_123
# Result: governance_history_test_ticket_123.csv ✅

# 3. Check metadata (broken)
cat data/agent_metadata.json | grep test_ticket_123
# Result: (empty) ❌

# 4. List agents
cat data/agent_metadata.json | python3 -c "import json, sys; print(list(json.load(sys.stdin).keys()))"
# Result: test_ticket_123 NOT in list ❌
```

---

## Root Cause

### Architecture Split

**Old Server (`src/mcp_server.py`):**
- Used by bridge
- NO agent metadata persistence
- NO lifecycle tracking
- Simple GovernanceMCPServer class

**New Server (`src/mcp_server_std.py`):**
- Used by MCP clients (Cursor, Claude Desktop)
- HAS agent metadata persistence
- HAS lifecycle tracking (created, paused, archived, etc.)
- Full AgentMetadata dataclass
- Saves to `data/agent_metadata.json`

### Code Location

```python
# scripts/claude_code_bridge.py:19
from src.mcp_server import GovernanceMCPServer  # ⚠️ Old version

# Should use functionality from:
# src/mcp_server_std.py (has metadata persistence)
```

---

## Proposed Solutions

### Option 1: Update Bridge to Use New Server (Recommended)

**Pros:**
- Reuses existing metadata infrastructure
- Consistent behavior across all interfaces
- No code duplication

**Cons:**
- Bridge might need refactoring
- New server is async (bridge is sync)

**Implementation:**
```python
# In claude_code_bridge.py
from src.mcp_server_std import (
    get_or_create_metadata,
    save_metadata,
    agent_metadata,
    AgentMetadata
)

class ClaudeCodeBridge:
    def __init__(self, agent_id, ...):
        self.agent_id = agent_id

        # Register in metadata system
        self.metadata = get_or_create_metadata(agent_id)
        save_metadata()

        # ... rest of init

    def log_interaction(self, ...):
        result = self.server.handle_request(...)

        # Update metadata
        self.metadata.total_updates += 1
        self.metadata.last_update = datetime.now().isoformat()
        save_metadata()

        return result
```

### Option 2: Add Metadata Persistence to Old Server

**Pros:**
- Minimal changes to bridge
- Self-contained solution

**Cons:**
- Code duplication
- Two separate metadata implementations to maintain

**Implementation:**
```python
# In src/mcp_server.py
class GovernanceMCPServer:
    def __init__(self):
        self.monitors = {}
        self.metadata = {}  # Add metadata tracking
        self.metadata_file = Path("data/agent_metadata.json")
        self._load_metadata()

    def _load_metadata(self):
        # Load from agent_metadata.json
        pass

    def _save_metadata(self):
        # Save to agent_metadata.json
        pass
```

### Option 3: Create Metadata Utility Module (Best Long-term)

**Pros:**
- Single source of truth
- Reusable across both servers
- Clean separation of concerns

**Cons:**
- More refactoring required
- Need to update both servers

**Implementation:**
```python
# New file: src/agent_metadata_manager.py
class AgentMetadataManager:
    """Shared metadata persistence for all governance interfaces"""

    def __init__(self, metadata_file="data/agent_metadata.json"):
        self.metadata_file = Path(metadata_file)
        self.metadata = {}
        self.load()

    def get_or_create(self, agent_id: str) -> AgentMetadata:
        """Get or create agent metadata"""
        pass

    def update(self, agent_id: str, **kwargs):
        """Update agent metadata fields"""
        pass

    def save(self):
        """Persist to disk"""
        pass

# Use in both servers:
from src.agent_metadata_manager import AgentMetadataManager
```

---

## Testing Checklist

After implementing fix:

```bash
# 1. Create test agent via bridge
python3 scripts/claude_code_bridge.py --log "test" --agent-id test_fix_verify

# 2. Verify CSV created
ls ~/Library/.../data/ | grep test_fix_verify
# Expected: governance_history_test_fix_verify.csv ✅

# 3. Verify metadata created
cat data/agent_metadata.json | grep test_fix_verify
# Expected: Entry exists ✅

# 4. Verify metadata fields
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
agent = data.get('test_fix_verify', {})
print(f'Status: {agent.get(\"status\")}')  # Should be 'active'
print(f'Updates: {agent.get(\"total_updates\")}')  # Should be 1
print(f'Created: {agent.get(\"created_at\")}')  # Should exist
print(f'Lifecycle: {agent.get(\"lifecycle_events\")}')  # Should have 'created' event
"

# 5. Verify subsequent updates increment
python3 scripts/claude_code_bridge.py --log "test2" --agent-id test_fix_verify
cat data/agent_metadata.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Updates: {data[\"test_fix_verify\"][\"total_updates\"]}')  # Should be 2
"

# 6. Cleanup
rm data/agent_metadata.json.backup 2>/dev/null
```

---

## Files to Modify

**Primary:**
- `scripts/claude_code_bridge.py` - Add metadata persistence

**Dependencies:**
- `src/mcp_server.py` - May need updates (Option 2)
- OR `src/mcp_server_std.py` - Extract shared code (Option 3)

**New Files (Option 3):**
- `src/agent_metadata_manager.py` - Shared metadata utilities

**Tests:**
- `tests/test_bridge_metadata.py` - New test file

---

## Related Issues/Docs

- **Agent ID Architecture:** `docs/guides/AGENT_ID_ARCHITECTURE.md`
- **MCP Server Standard:** `src/mcp_server_std.py` (has working implementation)
- **Session Notes:** `docs/archive/SESSION_2025_11_20_IMPROVEMENTS.md`

---

## Acceptance Criteria

- [ ] Bridge creates entry in `agent_metadata.json` on first use
- [ ] Entry includes: `agent_id`, `status`, `created_at`, `last_update`, `total_updates`
- [ ] Lifecycle events recorded: `created` event on first use
- [ ] `total_updates` increments with each `log_interaction()`
- [ ] `last_update` timestamp updates with each interaction
- [ ] Agent appears in `list_agents` queries
- [ ] Existing CSV logging still works
- [ ] No breaking changes to bridge API
- [ ] Unit tests pass
- [ ] Integration test added

---

## Notes

**Discovered during:** Session improvements where I logged 3 governance updates via bridge but agent didn't appear in metadata.

**Current Workaround:** Use MCP tools directly (via Cursor/Claude Desktop) instead of bridge for agents that need metadata tracking.

**Future Enhancement:** Consider unifying `mcp_server.py` and `mcp_server_std.py` into single implementation with shared metadata layer.

---

**Ticket Created:** 2025-11-20
**Assigned To:** Cursor IDE session
**Estimated Effort:** 2-4 hours (Option 1), 4-6 hours (Option 3)
**Priority:** Medium (system works, but tracking incomplete)

---

## Quick Start (For Cursor)

```bash
# 1. Checkout branch
git checkout -b fix/bridge-metadata-persistence

# 2. Start with Option 1 (simplest)
# Edit: scripts/claude_code_bridge.py
# Add: metadata persistence calls

# 3. Test
python3 scripts/claude_code_bridge.py --test
cat data/agent_metadata.json | python3 -m json.tool

# 4. Verify agent appears
# Should see agent in metadata with lifecycle events

# 5. Commit
git add scripts/claude_code_bridge.py
git commit -m "fix: Add agent metadata persistence to bridge"
```

Good luck! 🚀
