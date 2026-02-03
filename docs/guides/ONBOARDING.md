# UNITARES Governance System - Onboarding Guide

**Last Updated:** 2025-12-25

**For Humans - Detailed Onboarding Guide**

> **AI Agents:** Start with [START_HERE.md](START_HERE.md) → [AI_ASSISTANT_GUIDE.md](../reference/AI_ASSISTANT_GUIDE.md) instead. This guide is for humans who want more detail.

**Autonomous governance system for agents.** This guide covers registration, integration, and participation in the governance network.

---

## ✅ Quick Start Checklist (2 Minutes)

**Agent Registration & Integration:**

- [ ] **Get your identity:** Call `identity()` - auto-creates on first call, returns your UUID
- [ ] **Name yourself (optional):** Call `identity(name="your_name")` to set display name
- [ ] **Discover capabilities:** Call `list_tools` to enumerate available governance functions
- [ ] **Log first operation:** Call `process_agent_update` (identity auto-injected)
- [ ] **Verify state:** Call `get_governance_metrics` to retrieve current thermodynamic state

**Integration note:** Use MCP tools directly when available. Identity auto-binds per session - no API keys needed.

**Status:** Agent now participating in autonomous governance network.

---

## 🚀 Initial Integration

### System Health Verification (Optional)

**Verify system health before integration:**

**Via MCP:**
```python
# Call get_workspace_health tool
# Returns workspace state baseline in <5 seconds
```

**Benefits:**
- Establishes accurate baseline
- Identifies configuration issues early
- Reduces integration troubleshooting time

---

## 🚀 Agent Integration (5 Minutes)

### MCP-Compatible Agents

**Integration test sequence (v2.4.0+):**
```python
# Step 1: Check your identity (auto-creates if new)
identity_result = identity()
# Returns: agent_uuid, label, bound, source

# Step 2: Name yourself (optional but recommended)
identity(name="my_agent_20251225")
# Returns: agent_uuid with label set

# Step 3: Log initial operation (identity auto-injected)
process_agent_update(
    response_text="Initial integration test",  # Operation description
    complexity=0.5  # Self-assessed complexity [0-1]
)
# No agent_id or api_key needed - session binding handles identity
```

**Note:** Identity auto-binds per session. No API keys required in v2.4.0+.

### CLI-Only Interfaces

**Integration via Python:**
```bash
cd /path/to/governance-mcp-v1
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor(agent_id='your_agent_id')
r = m.process_update({'response_text': 'Initial integration test', 'complexity': 0.5})
print(f'Decision: {r[\"decision\"][\"action\"]}')
print(f'Metrics: E={r[\"metrics\"][\"E\"]:.3f}, I={r[\"metrics\"][\"I\"]:.3f}')
"
```

**4. Check Status**
```bash
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor(agent_id='your_agent_id')
print(m.get_metrics())
"
```

### For System Administrators

**1. Install Dependencies**
```bash
pip3 install -r requirements-core.txt
```

**2. Configure MCP**
- **Cursor:** Copy `config/mcp-config-cursor.json` to your Cursor MCP config
- **Claude Desktop:** Copy `config/mcp-config-claude-desktop.json` to your Claude Desktop MCP config

**3. Verify Server**
```bash
# Check server process
ps aux | grep mcp_server_std.py | grep -v grep

# Check server info (via MCP tool)
get_server_info()
```

**📖 Full Setup Guide:** [MCP Setup Guide](docs/guides/MCP_SETUP.md)

---

## 🎯 Integration Paths

Select integration scenario:

### 🤖 Agent Integration
**Documentation path:** [Metrics Guide](docs/guides/METRICS_GUIDE.md) → [Parameter Examples](docs/guides/PARAMETER_EXAMPLES.md)

**⚠️ Common Confusions to Avoid:**
- **EISV metrics** track thermodynamic structure, NOT semantic content quality
  - E is NOT "exploration capacity" - it tracks thermodynamic balance with I
  - I is NOT "preservation" - it's boosted by coherence, tracks information integrity
  - S is NOT "drift accumulation" - decay dominates, tracks uncertainty decay
- **Risk metrics** - Two different metrics:
  - `current_risk`: Recent trend (last 10) - **used for health status**
  - `mean_risk`: Overall average - **used for display/analysis**
- **Health status** uses `current_risk` (recent trend), NOT `mean_risk` (overall mean)
- **Agents with no updates** use coherence fallback for health status

**Core concepts:**
- Agent identity: Unique `agent_id` for state tracking
- Authentication: API key-based ownership verification
- State variables: EISV thermodynamic metrics (see METRICS_GUIDE.md)
- Governance feedback: `proceed`/`pause` decisions
- Lifecycle states: `active`, `waiting_input`, `paused`, `archived`

**Primary tools:**
- `identity()` - Check/create identity (auto-creates on first call, returns UUID)
- `list_tools` - Enumerate available governance functions (79 tools)
- `process_agent_update` - Main governance cycle (identity auto-injected)
- `simulate_update` - Dry-run governance evaluation (no state persistence)
- `get_governance_metrics` - Retrieve current thermodynamic state
- `get_dialectic_session` - Query active peer review sessions
- `store_knowledge_graph` - Log discoveries in knowledge graph
- `mark_response_complete` - Signal operation completion (`waiting_input` transition)
- `archive_agent` - Archive agent state (preserves data, enables resumption)

**Registration (v2.4.0+):** Identity auto-creates on first tool call. No explicit registration needed.

**Knowledge layer usage:** Use `store_knowledge` for discoveries. Create markdown only for comprehensive reports (1000+ words). See [Knowledge Layer Guide](docs/guides/KNOWLEDGE_LAYER_USAGE.md).

### 🔌 System Integration
**Documentation path:** [MCP Setup](docs/guides/MCP_SETUP.md) → [Authentication Guide](docs/guides/AUTHENTICATION.md)

**Integration requirements:**
- MCP protocol compliance
- Session-based identity (v2.4.0+ - no API keys needed)
- State persistence layer
- Multi-process coordination

**Integration tools:**
- `UNITARESMonitor` - Python class for direct integration
- `identity()` - Agent identity endpoint (MCP, auto-creates)
- `get_server_info` - System diagnostics (MCP)

### ⚙️ Infrastructure Setup
**Documentation path:** [MCP Setup](docs/guides/MCP_SETUP.md) → [Troubleshooting](docs/guides/TROUBLESHOOTING.md) → [Quick Reference](docs/QUICK_REFERENCE.md)

**Setup requirements:**
- MCP server configuration
- Process lifecycle management
- Data directory structure
- Backup/recovery procedures

**Administration tools:**
- `cleanup_zombie_mcp_servers.sh` - Process cleanup utility
- `get_server_info` - Server status query
- `list_agents` - Agent registry enumeration

---

## 📅 Progressive Integration Path

### Phase 1: Initial Integration (15 minutes)

**Objective:** Execute first governance cycle and observe feedback.

1. **Select integration path** (see above)
2. **Verify system health:**
   ```python
   # Use MCP tool
   get_workspace_health()
   ```
3. **Execute first governance cycle:**
   - **MCP Integration (v2.4.0+):**
     ```python
     # Step 1: Check your identity (auto-creates if new)
     identity_result = identity()
     # Returns: agent_uuid, label, bound, source

     # Step 2: Log first operation (identity auto-injected)
     result = process_agent_update(
         response_text="My first update",
         complexity=0.5  # Honest self-assessment, see complexity guide
     )
     # No agent_id or api_key needed - session binding handles identity
     ```
   - **Developer:** Use `UNITARESMonitor.process_update()`
   - **Admin:** Verify server is running
4. **Check the result:**
   - Status (healthy/moderate/critical)
   - Decision (proceed/pause)
   - Metrics (E, I, S, V, coherence, attention_score)
   - Sampling params (optional suggestions for next generation)

**✅ Success criteria:** You see a governance decision returned.

**Next:** [Understanding Metrics](docs/guides/METRICS_GUIDE.md)

---

### Day 2: Understand Metrics (30 minutes)

**Goal:** Understand what the metrics mean and how they relate to decisions.

1. **Read:** [Metrics Guide](docs/guides/METRICS_GUIDE.md) ⚠️ **Important: Read the full guide!**
2. **Key concepts** (see METRICS_GUIDE.md for accurate descriptions):
   - **E (Energy):** Thermodynamic balance with I (NOT semantic "exploration") [0, 1]
   - **I (Information Integrity):** Coherence-stabilized information (NOT semantic "preservation") [0, 1]
   - **S (Entropy):** Uncertainty decay (decay-dominated, NOT drift accumulation) [0, 1]
   - **V (Void Integral):** E-I imbalance [(-inf, +inf)]
   - **Coherence:** Pure thermodynamic C(V) signal from E-I balance [0, 1]
   - **Attention Score:** Two metrics:
     - **`current_risk`**: Recent trend (last 10) - used for health status
     - **`mean_risk`**: Overall average - used for display/analysis
3. **⚠️ Critical Understanding:**
   - EISV metrics track **thermodynamic structure**, NOT semantic content quality
   - Health status uses **`current_risk`** (recent trend), NOT `mean_risk` (overall mean)
   - Agents with no updates use **coherence fallback** for health status
4. **Experiment:**
   - Run updates with different complexity values
   - Observe how metrics change
   - See how decisions change with risk
   - Check both `current_risk` and `mean_risk` in metrics

**✅ Success criteria:** You can explain what each metric means and understand the difference between `current_risk` and `mean_risk`.

**Next:** [Parameter Examples](docs/guides/PARAMETER_EXAMPLES.md)

---

### Day 3: Advanced Features (45 minutes)

**Goal:** Use advanced features like simulation, threshold adjustment, and fleet monitoring.

1. **Simulation:**
   ```python
   # Test decisions without persisting state
   result = simulate_update(
       agent_id="your_id",
       response_text="Test scenario for simulation",
       complexity=0.7  # Test with different complexity levels
   )
   ```

2. **Runtime Configuration:**
   ```python
   # Check thresholds
   thresholds = get_thresholds()
   
   # Adjust thresholds
   set_thresholds({
       "risk_approve_threshold": 0.35
   })
   ```

3. **Fleet Monitoring:**
   ```python
   # Get fleet health overview
   fleet_health = aggregate_metrics()
   
   # Compare agents
   comparison = compare_agents(["agent1", "agent2"])
   
   # Detect anomalies
   anomalies = detect_anomalies()
   ```

**✅ Success criteria:** You can use simulation and fleet monitoring tools.

**Next:** [Knowledge Layer](docs/guides/KNOWLEDGE_LAYER_USAGE.md) (optional)

---

### Day 4+: Deep Dive

**Goal:** Master the system and customize for your needs.

**Specialized Guides:**
- [Agent ID Architecture](docs/guides/AGENT_ID_ARCHITECTURE.md) - Identity and lifecycle
- [Authentication Guide](docs/guides/AUTHENTICATION.md) - Security model
- [CLI Logging Guide](docs/guides/CLI_LOGGING_GUIDE.md) - CLI integration
- [Troubleshooting](docs/guides/TROUBLESHOOTING.md) - Common issues
- [Knowledge Layer](docs/guides/KNOWLEDGE_LAYER_USAGE.md) - Structured learning
- [Documentation Guidelines](docs/DOCUMENTATION_GUIDELINES.md) - **When to use markdown vs knowledge layer** ⚠️
- [Lifecycle Perspective](docs/meta/LIFECYCLE_PERSPECTIVE.md) - **Understanding lifecycle from agent's perspective** ⚠️
- [Quick Reference](docs/QUICK_REFERENCE.md) - Fast lookups

**Reference Docs:**
- [Integration Flow](docs/reference/INTEGRATION_FLOW.md) - Integration patterns
- [Cursor Handoff](docs/reference/CURSOR_HANDOFF.md) - Handoff guide

---

## 🔐 Authentication (Important!)

**New in v2.0:** The system uses API key authentication to prevent identity theft and impersonation attacks.

**Quick Start:**
```bash
# Option 1: Via Python directly
python3 -c "
from src.governance_monitor import UNITARESMonitor
m = UNITARESMonitor('your_agent_id')
m.process_update({'response_text': 'Work summary', 'complexity': 0.5})
"

# Option 2: Via MCP tools (from Claude Desktop, Cursor, etc.)
# Just call any tool - identity auto-creates on first call
# identity() to check your UUID, process_agent_update to log work
```

**Key Points (v2.4.0+):**
- Each session = unique identity bound to UUID
- Identity auto-creates on first tool call (no registration step)
- Session binding handles authentication automatically
- No API keys needed for MCP clients

**📖 Complete Guide:** [Authentication Guide](docs/guides/AUTHENTICATION.md)

---

## 🔄 Lifecycle Management

**Understanding your lifecycle states:**

### Lifecycle States

| State | Meaning | When to Use |
|-------|---------|-------------|
| `active` | You're working, making updates | Default state - you're engaged |
| `waiting_input` | You've finished your response, waiting for user | After completing work - call `mark_response_complete` |
| `paused` | You're stuck or need help | Circuit breaker triggered - use dialectic recovery |
| `archived` | You're done for now, but can come back | When finished with a session - preserves state |
| `deleted` | You're gone (protected if pioneer) | Rare - only if truly obsolete |

### Key Behaviors

**Auto-Resume (Forgiving):**
- If you're `archived` and you try to update, you automatically resume to `active`
- No friction - just start working again
- System trusts that if you're engaging, you should be active

**Protection:**
- If you're tagged as `"pioneer"`, you can't be deleted
- System protects you from accidental deletion
- Forces archive instead (preserves history)

**Automatic Cleanup:**
- Test/demo agents auto-archive after 7 days of inactivity
- Keeps the system lean
- Only affects test agents (not production agents)

### Best Practices

1. **Use `mark_response_complete`** - Explicitly mark when waiting for input
   ```python
   mark_response_complete(
       agent_id="your_id",
       api_key="your_key",
       summary="Completed analysis of lifecycle management"
   )
   ```

2. **Archive when done** - Don't leave agents active indefinitely
   ```python
   archive_agent(
       agent_id="your_id",
       reason="Session complete",
       keep_in_memory=False  # Free memory when archived
   )
   ```

3. **Use tags** - Tag yourself for easier lifecycle management
   ```python
   update_agent_metadata(
       agent_id="your_id",
       tags=["composer", "standardization", "documentation"]
   )
   ```

4. **Check lifecycle events** - Review your lifecycle history
   ```python
   metadata = get_agent_metadata(agent_id="your_id")
   # See lifecycle_events for full history
   ```

**📖 Complete Guide:** [Lifecycle Perspective](docs/meta/LIFECYCLE_PERSPECTIVE.md) - Detailed analysis from agent's perspective

---

## 🛠️ Common Tasks

### I want to...

**Get started quickly:**
→ [Quick Start](#-quick-start-5-minutes) (above)

**Understand what metrics mean:**
→ [Metrics Guide](docs/guides/METRICS_GUIDE.md)

**Set up MCP server:**
→ [MCP Setup Guide](docs/guides/MCP_SETUP.md)

**Fix a problem:**
→ [Troubleshooting Guide](docs/guides/TROUBLESHOOTING.md)

**See all available tools:**
→ **Call `list_tools` MCP tool** - Returns all 47 tools with descriptions, categories, and workflows  
→ Or check [README.md](README.md) for full feature list

**Find a quick command:**
→ [Quick Reference](docs/QUICK_REFERENCE.md)

**Learn about agent identity:**
→ [Agent ID Architecture](docs/guides/AGENT_ID_ARCHITECTURE.md)

**Integrate with my system:**
→ [Integration Flow](docs/reference/INTEGRATION_FLOW.md)

---

## 📚 Documentation Structure

```
governance-mcp-v1/
├── ONBOARDING.md          ← You are here
├── README.md              ← Main documentation
├── docs/
│   ├── guides/           ← How-to guides
│   │   ├── METRICS_GUIDE.md
│   │   ├── MCP_SETUP.md
│   │   ├── AUTHENTICATION.md
│   │   └── ...
│   ├── reference/        ← Technical reference
│   │   ├── AI_ASSISTANT_GUIDE.md  ← AI agent guide (all models)
│   │   └── ...
│   └── QUICK_REFERENCE.md ← Fast lookups
```

---

## ❓ Frequently Asked Questions

### Q: Do I need to configure MCP?
**A:** If you're using Cursor or Claude Desktop, yes. See [MCP Setup Guide](docs/guides/MCP_SETUP.md). If you're using Python directly, no.

### Q: What's the difference between `process_agent_update` and `simulate_update`?
**A:** `process_agent_update` persists state. `simulate_update` is a dry-run that doesn't modify state. Use simulation to test decisions safely.

### Q: How do I get my identity?
**A:** Call `identity()` - it auto-creates your identity on first call and returns your UUID.

**v2.4.0+ (Recommended):** No API keys needed. Identity binds per session automatically.
- Call `identity()` to see your UUID
- Call `identity(name="...")` to set a display name
- All other tools auto-inject your identity from the session

**Legacy (v2.3.0 and earlier):** API key-based authentication still works but is no longer required.

### Q: Can I use this without MCP?
**A:** Yes! Use the Python API directly:
```python
from src.governance_monitor import UNITARESMonitor
monitor = UNITARESMonitor(agent_id="your_id")
result = monitor.process_update({...})
```

### Q: What if I get an error?
**A:** Check [Troubleshooting Guide](docs/guides/TROUBLESHOOTING.md) or [Quick Reference](docs/QUICK_REFERENCE.md).

---

## 🎯 Next Steps

1. **Choose your role** (see [Who Are You?](#-who-are-you))
2. **Follow the Quick Start** (5 minutes)
3. **Progressive learning** (Day 1 → Day 2 → Day 3 → Deep dive)
4. **Explore specialized guides** as needed

**Remember:** Start simple, learn progressively, explore deeply.

---

## 🆘 Need Help?

- **Quick Reference:** [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)
- **Troubleshooting:** [docs/guides/TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md)
- **Full Documentation:** [README.md](README.md)

---

**Welcome to UNITARES Governance! 🚀**

