# UNITARES Governance System - Onboarding Guide

**Welcome!** This guide will get you up and running with the UNITARES Governance Framework in minutes.

---

## 🚀 Quick Start (5 Minutes)

### For AI Agents (Claude, Composer/Cursor, ChatGPT, etc.)

**👉 Start here:** [README_FOR_FUTURE_CLAUDES.md](docs/reference/README_FOR_FUTURE_CLAUDES.md)

This guide was written by an AI assistant after real testing and covers:
- Common mistakes to avoid
- Working test recipes
- Quick self-check before using tools
- Pro tips from hands-on experience

**Quick test:**
```python
# Via MCP tool (if MCP is configured)
process_agent_update(
    agent_id="your_unique_id_20251124_143000",
    parameters=[0.6, 0.4, 0.7, 0.85, 0.0, 0.1] + [0.01]*122,
    ethical_drift=[0.1, 0.15, 0.12],
    response_text="Test response",
    complexity=0.5
)
```

### For Human Developers

**1. Setup MCP Server** (if not already configured)
```bash
# Check if MCP is configured
cat ~/.cursor/mcp.json | grep governance

# If not configured, see: docs/guides/MCP_SETUP.md
```

**2. Run Demo**
```bash
cd governance-mcp-v1
python3 demos/demo_complete_system.py
```

**3. Test First Update**
```bash
# Via CLI bridge
python3 scripts/claude_code_bridge.py \
  --log "Test interaction" \
  --complexity 0.5
```

**4. Check Status**
```bash
python3 scripts/claude_code_bridge.py --status
```

### For System Administrators

**1. Install Dependencies**
```bash
pip3 install -r requirements-mcp.txt
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

## 🎯 Who Are You?

Choose your path:

### 🤖 I'm an AI Agent
**Path:** [README_FOR_FUTURE_CLAUDES.md](docs/reference/README_FOR_FUTURE_CLAUDES.md) → [Metrics Guide](docs/guides/METRICS_GUIDE.md) → [Parameter Examples](docs/guides/PARAMETER_EXAMPLES.md)

**Key concepts:**
- Agent identity (unique `agent_id`)
- API key authentication
- EISV state variables
- Governance decisions (approve/revise/reject)

**Essential tools:**
- `process_agent_update` - Main governance cycle
- `simulate_update` - Test decisions without persisting
- `get_governance_metrics` - Check your state
- `list_tools` - Discover all available tools
- `store_knowledge` - Document discoveries/insights (preferred over markdown files)

**📝 Documentation Note:** Use `store_knowledge` for discoveries/insights, NOT markdown files. Only create markdown files for comprehensive reports (1000+ words). See [Knowledge Layer Guide](docs/guides/KNOWLEDGE_LAYER_USAGE.md).

### 👨‍💻 I'm a Developer Integrating This System
**Path:** [MCP Setup](docs/guides/MCP_SETUP.md) → [Authentication Guide](docs/guides/AUTHENTICATION.md) → [Integration Flow](docs/reference/INTEGRATION_FLOW.md)

**Key concepts:**
- MCP protocol integration
- API key management
- State persistence
- Multi-process synchronization

**Essential tools:**
- `claude_code_bridge.py` - CLI integration example
- `register_agent.py` - Agent registration
- `get_server_info` - Server diagnostics

### 🔧 I'm Setting Up the System
**Path:** [MCP Setup](docs/guides/MCP_SETUP.md) → [Troubleshooting](docs/guides/TROUBLESHOOTING.md) → [Quick Reference](docs/QUICK_REFERENCE.md)

**Key concepts:**
- MCP server configuration
- Process management
- Data directory structure
- Backup strategies

**Essential tools:**
- `cleanup_zombie_mcp_servers.sh` - Process cleanup
- `get_server_info` - Server diagnostics
- `list_agents` - Agent management

---

## 📅 Progressive Learning Path

### Day 1: Get It Working (15 minutes)

**Goal:** Make your first governance update and see a decision.

1. **Choose your role** (see above)
2. **Run the demo:**
   ```bash
   python3 demos/demo_complete_system.py
   ```
3. **Make your first update:**
   - **AI Agent:** Use `process_agent_update` via MCP
   - **Developer:** Use `claude_code_bridge.py --log`
   - **Admin:** Verify server is running
4. **Check the result:**
   - Status (healthy/degraded/critical)
   - Decision (approve/revise/reject)
   - Metrics (E, I, S, V, coherence, risk)

**✅ Success criteria:** You see a governance decision returned.

**Next:** [Understanding Metrics](docs/guides/METRICS_GUIDE.md)

---

### Day 2: Understand Metrics (30 minutes)

**Goal:** Understand what the metrics mean and how they relate to decisions.

1. **Read:** [Metrics Guide](docs/guides/METRICS_GUIDE.md)
2. **Key concepts:**
   - **E (Energy):** Exploration/productive capacity [0, 1]
   - **I (Information):** Preservation/integrity [0, 1]
   - **S (Entropy):** Disorder/uncertainty [0, 1]
   - **V (Void):** E-I balance (like free energy)
   - **Coherence:** Parameter stability over time [0, 1]
   - **Risk Score:** Multi-factor risk estimate [0, 1]
3. **Experiment:**
   - Run updates with different complexity values
   - Observe how metrics change
   - See how decisions change with risk

**✅ Success criteria:** You can explain what each metric means.

**Next:** [Parameter Examples](docs/guides/PARAMETER_EXAMPLES.md)

---

### Day 3: Advanced Features (45 minutes)

**Goal:** Use advanced features like simulation, threshold adjustment, and fleet monitoring.

1. **Simulation:**
   ```python
   # Test decisions without persisting state
   result = simulate_update(
       agent_id="your_id",
       parameters=[...],
       ethical_drift=[...],
       response_text="Test",
       complexity=0.7
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
- [Quick Reference](docs/QUICK_REFERENCE.md) - Fast lookups

**Reference Docs:**
- [Integration Flow](docs/reference/INTEGRATION_FLOW.md) - Integration patterns
- [Cursor Handoff](docs/reference/CURSOR_HANDOFF.md) - Handoff guide

---

## 🔐 Authentication (Important!)

**New in v2.0:** The system uses API key authentication to prevent identity theft and impersonation attacks.

**Quick Start:**
```bash
# 1. Register your agent (generates API key)
python3 scripts/register_agent.py your_agent_id

# 2. Log work (automatically authenticated)
python3 scripts/agent_self_log.py --agent-id your_agent_id \
  "Work summary" --complexity 0.7
```

**Key Points:**
- Each `agent_id` = unique identity with cryptographic API key
- Using another agent's ID without their key = identity theft attempt = rejected
- API keys stored in `data/agent_metadata.json` (protect this file!)
- All production paths enforce authentication

**📖 Complete Guide:** [Authentication Guide](docs/guides/AUTHENTICATION.md)

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
→ Use `list_tools` MCP tool or check [README.md](README.md#-mcp-server-tools)

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
│   │   ├── README_FOR_FUTURE_CLAUDES.md  ← AI agent guide
│   │   └── ...
│   └── QUICK_REFERENCE.md ← Fast lookups
```

---

## ❓ Frequently Asked Questions

### Q: Do I need to configure MCP?
**A:** If you're using Cursor or Claude Desktop, yes. See [MCP Setup Guide](docs/guides/MCP_SETUP.md). If you're using Python directly, no.

### Q: What's the difference between `process_agent_update` and `simulate_update`?
**A:** `process_agent_update` persists state. `simulate_update` is a dry-run that doesn't modify state. Use simulation to test decisions safely.

### Q: How do I get an API key?
**A:** API keys are auto-generated on first update. Use `get_agent_api_key` to retrieve it, or `register_agent.py` to pre-register.

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

