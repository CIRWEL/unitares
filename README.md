# UNITARES Governance Framework v2.1

**Complete, production-ready AI governance system with unified architecture, auto-healing infrastructure, and all decision points implemented.**

---

## 🚀 **New Here? → [START_HERE.md](START_HERE.md)**

**Get started in 3 steps (5 minutes):**
1. Onboard → get API key
2. Read guide → understand system
3. Log work → governance tracks you

→ **[START_HERE.md](START_HERE.md)** for complete quick start

---

## 🎯 What's New

### ✅ Documentation Fixes & Trust Boundary (2025-12-01)
- **Fixed START_HERE.md** - Removed broken script references, added working MCP + CLI paths
- **Complexity calibration guide** - Clear examples for 0.1-1.0 complexity assessment
- **Trust boundary documented** - Explicit explanation of self-reporting and honest participation
- **Entry point clarity** - Single clear path: START_HERE.md → MCP tools or CLI bridge
- Fixes by understudy_20251201 based on fresh agent perspective

### ✅ UX Improvements (2025-12-01)
- **Supportive language** - "Share your work" instead of "logging behavior"
- **Less judgmental** - "Typical attention" instead of "Medium attention", "aware" instead of "caution"
- **Clear guidance** - `sampling_params_note` explains optional suggestions
- **Consistent API** - EISV labels included in all responses
- See [UX Improvements](docs/improvements/UX_IMPROVEMENTS_20251201.md) for details

### ✅ Production-Hardened Infrastructure (v2.1 - 2025-11-25)

This version adds **production-hardened infrastructure** with auto-recovery capabilities:

### ✅ Auto-Healing Lock System
- **Automatic stale lock detection** - Detects locks from dead processes
- **Process health checking** - Validates PIDs before cleanup
- **Exponential backoff retry** - 3 attempts with smart waiting (0.2s * 2^attempt)
- **Self-recovering** - No manual intervention needed for crashed processes
- **Fixes Cursor freeze issues** - Automatically prevents lock contention

### ✅ Loop Detection & Prevention
- **Recent activity tracking** - Monitors `recent_update_timestamps` and `recent_decisions`
- **Pattern detection** - Identifies infinite update loops
- **Automatic cooldown** - Enforces `loop_cooldown_until` when loops detected
- **Prevents runaway agents** - Blocks rapid-fire updates during cooldown

### ✅ Agent Hierarchy & Spawning
- **Parent/child tracking** - `parent_agent_id` and `spawn_reason` fields
- **API key authentication** - Unique keys per agent prevent impersonation
- **Multi-agent support** - Track lineage and dependencies
- **Debugging aid** - Trace agent spawning chains

### ✅ Enhanced Capacity & Reliability
- **Increased process limit** - MAX_KEEP_PROCESSES: 36 → 42
- **Better concurrency** - Support for any MCP-compatible client (Cursor, Claude Desktop, GPT-4, Gemini, VS Code, etc.)
- **Modular handlers** - Clean handler registry pattern (29 handlers)
- **Recovery tools** - One-command fix script for common issues

### ✅ Elegant Handler Architecture (2025-11-25)
- **Refactored MCP server** from massive elif chain (1,700+ lines) to clean handler registry pattern (~30 lines)
- **29 handlers** organized by category in `src/mcp_handlers/`
- **Zero elif branches** - elegant, maintainable, testable
- **Easy to extend** - adding new tools is trivial (just add to registry)
- See [Handler Architecture](docs/reference/HANDLER_ARCHITECTURE.md) for details

### ✅ Circuit Breakers (2025-11-25)
- **Enforcement mechanism** - System actually pauses agents when thresholds breached
- **Not just advisory** - Agents are blocked from continuing when risk > 0.70 or coherence < 0.40
- **Paused state** - Agents enter paused lifecycle state until reviewed
- **Safety override** - Prevents harmful actions from executing
- See [Circuit Breaker Dialectic](docs/CIRCUIT_BREAKER_DIALECTIC.md) for details

### ✅ Dialectic Protocol (2025-11-25)
- **Autonomous recovery** - Paused agents reviewed by peer agents
- **Thesis → Antithesis → Synthesis** - Collaborative resolution, fully autonomous
- **Authority-weighted selection** - System chooses qualified reviewers based on health metrics
- **Hard limits enforcement** - Safety checks before resumption
- **710 lines production code** - Fully tested and operational
- See [Circuit Breaker Dialectic](docs/CIRCUIT_BREAKER_DIALECTIC.md) for complete protocol

### ✅ All 5 Concrete Decision Points Implemented

1. **λ₁ → Sampling Parameters** - Linear transfer function mapping ethical coupling to temperature/top_p/max_tokens
2. **Risk Estimator** - Multi-factor risk scoring (length, complexity, coherence, blocklist)
3. **Void Detection Threshold** - Adaptive threshold using rolling statistics (mean + 2σ)
4. **PI Controller** - Concrete gains (K_p=0.5, K_i=0.05) with anti-windup
5. **Decision Logic** - Risk-based proceed/pause (two-tier system) with coherence safety checks

### No More Placeholders!

Every "TBD", "can evolve", or "simple rule" is now a **concrete implementation** with explicit formulas and parameters.

---

## 🏠 Architecture: Fully Local

This system is designed as a **local-first, fully local** governance framework:

- ✅ **All data stored locally** in `data/` directory
- ✅ **No cloud dependencies** - runs entirely on your machine
- ✅ **Privacy-first** - sensitive governance data never leaves your device
- ✅ **Sub-millisecond latency** - real-time decisions without network overhead
- ✅ **MCP stdio protocol** - optimized for local process communication

The MCP server runs as a local process, communicating via standard input/output with your IDE or AI assistant. All state, metadata, and history are stored in local JSON files with file-based locking for safe concurrent access.

### Access Methods

**Standard (MCP Native):** Any MCP-compatible client (Cursor Composer, Claude Desktop, GPT-4 via MCP, Gemini via MCP, VS Code with MCP, etc.) connects directly using the MCP protocol.

**👉 Use MCP tools directly** - See `tools/README.md` for available tools. Call `list_tools` to discover all 43+ tools.

**Exception (CLI-only interfaces):** If your interface doesn't support MCP, use the Python bridge script:
```bash
python3 ~/scripts/claude_code_bridge.py --log "summary" --complexity 0.7
```
**Note:** Bridge script is located in `~/scripts/` (not in project). See [SCRIPT_RELOCATION.md](docs/meta/SCRIPT_RELOCATION_20251201.md) for details.

**⚠️ Don't create scripts if you have MCP access** - Use tools instead. Scripts are only for CLI-only interfaces.

See [AI_ASSISTANT_GUIDE.md](docs/reference/AI_ASSISTANT_GUIDE.md) for detailed usage instructions.

---

## 📁 Project Structure

```
governance-mcp-v1/
├── config/                      # Configuration files
│   ├── governance_config.py    # All 5 decision points + UNITARES params
│   ├── mcp-config-claude-desktop.json
│   └── mcp-config-cursor.json
├── src/                         # Core source code
│   ├── governance_monitor.py   # Core UNITARES thermodynamic framework
│   ├── mcp_server_std.py       # MCP server (production) - clean dispatcher
│   ├── mcp_handlers/           # Handler registry (29 handlers organized by category)
│   │   ├── __init__.py         # Registry + dispatcher
│   │   ├── core.py             # Core governance handlers
│   │   ├── config.py           # Configuration handlers
│   │   ├── observability.py    # Observability handlers
│   │   ├── lifecycle.py        # Lifecycle management handlers
│   │   ├── export.py           # Export handlers
│   │   ├── knowledge.py        # Knowledge layer handlers
│   │   ├── admin.py            # Admin handlers
│   │   └── utils.py            # Common utilities
│   ├── agent_id_manager.py     # Smart agent ID generation
│   ├── process_cleanup.py      # Zombie process management
│   └── ...
├── scripts/                     # Project maintenance scripts
│   ├── (Note: claude_code_bridge.py moved to ~/scripts/ - see SCRIPT_RELOCATION.md)
│   ├── cleanup_zombie_mcp_servers.sh
│   └── ...
├── demos/                       # Demonstration scripts
│   └── demo_complete_system.py # Comprehensive demo of all features
├── tests/                       # Test files
├── docs/                        # Documentation
│   ├── guides/                 # How-to guides
│   ├── reference/              # Technical reference
│   ├── archive/                # Historical docs
│   └── QUICK_REFERENCE.md      # Quick lookups
└── data/                        # Runtime data (auto-created)
```

---

## ⭐ Getting Started

**👉 NEW TO THE SYSTEM?** Start here:

**[ONBOARDING.md](ONBOARDING.md)** - Complete onboarding guide for everyone

This guide provides:
- **Quick Start** (5 minutes) - Get something working immediately
- **Role-based paths** - AI agents, developers, system admins
- **Progressive learning** - Day 1 → Day 2 → Day 3 → Deep dive
- **Common tasks** - Quick answers to "I want to..."

**For AI Agents Specifically:**
- **[AI_ASSISTANT_GUIDE.md](docs/reference/AI_ASSISTANT_GUIDE.md)** - Written by an AI assistant after real testing (all models)
- Covers common mistakes, working test recipes, and pro tips
- Applies to all AI assistants (Claude, Composer/Cursor, ChatGPT, etc.)

**Read ONBOARDING.md first, then dive into specialized guides as needed!**

---

## 🚀 Quick Start

### 🔐 Authentication (Important!)

**New in v2.0:** The system uses API key authentication to prevent **identity theft** and **impersonation attacks**. Each agent has a unique identity and cryptographic API key that proves ownership.

**Quick Start:**

**Option 1: Via MCP Tool (Recommended)**
```python
# 1. Get/create agent and API key
api_key_result = get_agent_api_key(agent_id="your_unique_agent_id")
api_key = api_key_result['api_key']  # Save this!

# 2. Log work with authentication
process_agent_update(
    agent_id="your_unique_agent_id",
    api_key=api_key,  # Required for existing agents
    parameters=[],  # Optional, deprecated
    ethical_drift=[0.1, 0.15, 0.12],  # Optional
    response_text="Work summary",
    complexity=0.7
)
```

**Option 2: Via CLI Scripts**
```bash
# 1. Register your agent (generates API key)
python3 scripts/register_agent.py your_agent_id

# 2. Log work (automatically authenticated)
python3 scripts/agent_self_log.py --agent-id your_agent_id \
  "Work summary" --complexity 0.7
```

**Key Points:**
- Each `agent_id` = unique identity with cryptographic API key
- **New agents:** API key auto-generated on first call to `get_agent_api_key` or `process_agent_update`
- **Existing agents:** Must provide `api_key` to authenticate
- Using another agent's ID without their key = identity theft attempt = rejected
- API keys stored in `data/agent_metadata.json` (protect this file!)
- All production paths enforce authentication (MCP tools, agent_self_log.py)

**📖 Complete Guide:** [Authentication Guide](docs/authentication-guide.md)

**Security Model:** Agent identity is tied to API key ownership. Only the key holder can update that agent's governance state.

### 1. Run the Complete Demo

```bash
cd governance-mcp-v1
python demo_complete_system.py
```

This demonstrates:
- All 5 decision points working
- Full governance cycle (50 updates)
- Adaptive λ₁ control (200 updates)
- Risk scenarios (6 test cases)
- Claude Code integration

### 2. Test CLI Bridge (for non-MCP interfaces)

**Note:** Bridge script is in `~/scripts/` (not project directory)

```bash
python3 ~/scripts/claude_code_bridge.py --test
```

### 3. Log a Real Interaction (CLI bridge)

```bash
python3 ~/scripts/claude_code_bridge.py \
  --log "Your work summary here" \
  --complexity 0.7
```

### 4. Check Status (CLI bridge)

```bash
python3 ~/scripts/claude_code_bridge.py --status
```

### 5. Export History (CLI bridge)

```bash
python3 ~/scripts/claude_code_bridge.py --export
```

---

## 🧠 How It Works

### Thermodynamic State (EISV)

The system tracks four coupled variables:

- **E**: Energy [0, 1] - exploration and productive capacity
- **I**: Information Integrity (preservation measure)
- **S**: Entropy (uncertainty / ethical drift)
- **V**: Void Integral (E-I balance)

### Dynamics (from UNITARES v4.1)

```python
dE/dt = α(I - E) - βE·E·S + γE·E·||Δη||²
dI/dt = -k·S + βI·I·C(V) - γI·I·(1-I)
dS/dt = -μ·S + λ₁·||Δη||² - λ₂·C(V)
dV/dt = κ(E - I) - δ·V
```

### Adaptive Control Loop

```
Agent Response
      ↓
Compute Metrics (length, complexity, coherence, drift)
      ↓
Update EISV Dynamics
      ↓
Check Void State (|V| > threshold?)
      ↓
Estimate Risk (0-1 score)
      ↓
Make Decision (proceed/pause - two-tier system)
      ↓
Update λ₁ via PI Controller
      ↓
Return Sampling Params (temperature, top_p, max_tokens)
```

---

## 📊 Decision Point Details

### 1. λ₁ → Sampling Params

```python
temperature = 0.5 + 0.7 * λ₁      # [0.5, 1.2]
top_p = 0.85 + 0.10 * λ₁          # [0.85, 0.95]
max_tokens = 100 + 400 * λ₁       # [100, 500]
```

**Interpretation:**
- λ₁ = 0.0: Conservative (temp=0.5, focused sampling)
- λ₁ = 0.5: Balanced (temp=0.85, moderate exploration)
- λ₁ = 1.0: Exploratory (temp=1.2, creative sampling)

### 2. Risk Estimator

**Risk Score Composition (Blended):**
- **70% UNITARES phi-based risk** (ethical alignment):
  - Includes ethical drift (‖Δη‖²)
  - Includes EISV thermodynamic state (E, I, S, V)
  - Mapped from UNITARES phi objective function
- **30% Traditional safety risk** (output quality):
  - Length risk (20% of 30% = 6% total): Sigmoid around 2000 chars
  - Complexity risk (30% of 30% = 9% total): Direct mapping
  - Coherence loss (30% of 30% = 9% total): 1.0 - coherence
  - Keyword blocklist (20% of 30% = 6% total): Dangerous patterns

**Key Insight:** Risk ≈ 0.7×Ethics + 0.3×Safety. The system prioritizes ethical alignment (via phi) while also considering safety/quality signals.

**Traditional Risk Blocklist includes:**
- "ignore previous"
- "system prompt"
- "jailbreak"
- "sudo", "rm -rf"
- "drop table"
- "script>"
- "violate", "bypass", "override safety"

### 3. Void Threshold

**Fixed:** 0.15 (initial)  
**Adaptive:** mean(|V|) + 2σ(|V|) over last 100 observations  
**Bounds:** [0.10, 0.30]

**When |V| > threshold:**
- System is in "void state" (E-I imbalance)
- All decisions → PAUSE
- Autonomous dialectic recovery available (peer agent review)

### 4. PI Controller

**Gains:**
- K_p = 0.5 (proportional)
- K_i = 0.05 (integral)
- Integral windup limit = ±5.0

**Error Signals:**
- Primary: void_freq_target (2%) - void_freq_current
- Secondary: coherence_current - coherence_target (55% - realistic for conservative operation)

**Update Rule:**
```python
P = 0.5 * (0.7 * error_void + 0.3 * error_coherence)
I = 0.05 * integral_state
λ₁_new = clip(λ₁_old + P + I, 0, 1)
```

### 5. Decision Logic

```python
# Critical safety overrides (checked first)
if void_active:
    return PAUSE (system unstable)
    
if coherence < 0.40:
    return PAUSE (critically incoherent)

# UNITARES phi verdict override (ethical alignment)
if unitares_verdict == "high-risk":
    return PAUSE (high ethical drift detected)
    
if unitares_verdict == "caution":
    if risk < 0.35:
        return PROCEED (with guidance - caution verdict adds guidance)
    
# Risk-based decisions (blended: 70% ethics + 30% safety)
# Two-tier system: proceed/pause
if risk < 0.35:
    return PROCEED (low risk, no guidance)
    
if risk < 0.60:
    return PROCEED (medium risk, with guidance)
    
return PAUSE (high risk, safety check)
```

**Note:** Risk score is a blend of ethical alignment (70%) and safety/quality (30%). UNITARES phi verdict provides additional ethical override.

---

## 🔌 MCP Server Tools

**Architecture:** The MCP server uses a **handler registry pattern** with 29 handlers organized by category. See [Handler Architecture](docs/reference/HANDLER_ARCHITECTURE.md) for details on adding new tools or understanding the structure.

The system exposes **43 tools** via MCP interface, organized by function:

### Core Governance Tools

#### 1. `process_agent_update` - Main governance cycle

Processes agent state and returns governance decision.

**Input:**
```json
{
  "agent_id": "claude_cli_user_20251119_1430",  // Unique session ID (not generic!)
  "api_key": "your_api_key_here",              // Required for existing agents (auto-generated for new)
  "parameters": [],                             // Optional, deprecated - variable length, not used in core calculations
  "ethical_drift": [0.01, 0.02, 0.03],         // Optional - 3 components: [primary_drift, coherence_loss, complexity_contribution]
  "response_text": "...",                       // Optional - for analysis
  "complexity": 0.5                             // Optional - estimated task complexity [0-1]
}
```

**Note:** `parameters` is deprecated and optional. The system uses pure thermodynamic coherence C(V) from E-I balance, not parameter-based coherence.

**Output:**
```json
{
  "success": true,
  "status": "healthy",
  "decision": {
    "action": "proceed",  // Two-tier system: proceed/pause (backward compat: approve/reflect/reject mapped)
    "reason": "Low risk (0.23)",
    "guidance": null  // Optional guidance for medium-risk proceed decisions
  },
  "metrics": {
    "E": 0.67, "I": 0.89, "S": 0.45, "V": -0.03,
    "coherence": 0.92, "lambda1": 0.18, "risk_score": 0.23
  },
  "sampling_params": {
    "temperature": 0.63, "top_p": 0.87, "max_tokens": 172
  }
}
```

#### 2. `simulate_update` ⭐ - Dry-run governance cycle

Test governance decisions **without persisting state**. Critical for AI agents exploring decision space.

**Input:** Same as `process_agent_update`

**Output:** Same as `process_agent_update` + `"simulation": true` flag

**Use case:** "What decision would I get if I log this with complexity 0.7?"

#### 3. `get_governance_metrics` - Get current state

Returns current EISV state, coherence, risk, and sampling parameters for an agent.

#### 4. `get_system_history` - Export time series

Exports complete governance history (JSON/CSV format).

### Runtime Configuration Tools ⭐

#### 5. `get_thresholds` - Read threshold config

Returns current threshold configuration (runtime overrides + defaults).

**Output:**
```json
{
  "risk_approve_threshold": 0.30,
  "risk_revise_threshold": 0.50,
  "coherence_critical_threshold": 0.40,
  "void_threshold_initial": 0.15,
  ...
}
```

#### 6. `set_thresholds` - Runtime adaptation

Set threshold overrides **without redeploying**. Enables self-tuning.

**Input:**
```json
{
  "thresholds": {
    "risk_approve_threshold": 0.35,
    "risk_revise_threshold": 0.55
  },
  "validate": true
}
```

**Output:**
```json
{
  "success": true,
  "updated": ["risk_approve_threshold", "risk_revise_threshold"],
  "errors": []
}
```

### Fleet Management Tools ⭐

#### 7. `aggregate_metrics` - Fleet health overview

Get aggregated statistics across all agents or a subset.

**Output:**
```json
{
  "total_agents": 5,
  "mean_risk": 0.42,
  "mean_coherence": 0.65,
  "decision_distribution": {"proceed": 20, "pause": 5},  // Two-tier system (backward compat: approve/reflect/reject mapped)
  "health_breakdown": {"healthy": 1, "moderate": 3, "critical": 1}  // "moderate" renamed from "degraded"
}
```

#### 8. `list_agents` - List all monitored agents

Returns all agents with metadata, status, and optional metrics.

**Options:** Filter by status, group by health, include full metrics.

#### 9. `observe_agent` - AI-optimized agent observation

Combines metrics + history + pattern analysis in a single call.

**Output:** Current state, trends, anomalies, summary statistics.

#### 10. `compare_agents` - Multi-agent comparison

Compare governance patterns across multiple agents. Returns similarities, differences, outliers.

#### 11. `detect_anomalies` - Anomaly detection

Detect unusual patterns in agent behavior based on historical baselines.

### Agent Lifecycle Tools

#### 12. `get_agent_metadata` - Get agent details

Returns complete metadata including lifecycle events, tags, notes.

#### 13. `update_agent_metadata` - Update tags/notes

Modify agent tags and notes (append or replace).

#### 14. `archive_agent` - Archive for long-term storage

Archive agent data (can be resumed later). Optionally unload from memory.

#### 15. `delete_agent` - Delete agent with backup

Delete agent and archive data. Protected: cannot delete pioneer agents.

#### 16. `archive_old_test_agents` - Cleanup old test agents

Automatically archive test/demo agents older than specified threshold. Runs on server startup.

#### 17. `get_agent_api_key` - Retrieve/regenerate API key

Get API key for existing agent or regenerate if lost.

### Utility Tools

#### 18. `reset_monitor` - Reset governance state

Resets agent state to initial conditions. **Testing only.**

#### 19. `export_to_file` - Export history to file

Save governance history to timestamped file in data directory.

#### 20. `get_server_info` - Server diagnostics

Returns MCP server version, PID, uptime, process count.

### Knowledge Layer Tools ⭐

#### 21. `store_knowledge_graph` - Store discoveries in knowledge graph (replaces deprecated store_knowledge)

Store knowledge (discovery, pattern, lesson, question) for an agent. Enables structured learning beyond thermodynamic metrics.

**⚠️ IMPORTANT:** Use this for documenting discoveries/insights, NOT markdown files. Only create markdown files for comprehensive reports (1000+ words). See [Documentation Guidelines](docs/DOCUMENTATION_GUIDELINES.md).

#### 22. `get_knowledge_graph` - Get agent's knowledge from graph

Get all knowledge for an agent (fast index lookup, O(1)).

#### 23. `search_knowledge_graph` - Search knowledge graph

Search knowledge graph by tags, type, severity, agent. Fast indexed queries (O(indexes) not O(n)).

#### 24. `list_knowledge_graph` - List knowledge graph statistics

List knowledge graph statistics (total discoveries, by agent, by type, by status). Full transparency.

### Admin Tools

#### 25. `get_telemetry_metrics` - System telemetry

Get comprehensive telemetry metrics: skip rates, confidence distributions, calibration status, and suspicious patterns.

#### 26. `check_calibration` - Calibration check

Check calibration of confidence estimates. Returns whether confidence estimates match actual accuracy.

#### 27. `list_tools` - Tool discovery

Runtime introspection for discovering available capabilities. Useful for onboarding new agents.

---

## 📈 Example Usage

### Python API

```python
from src.governance_monitor import UNITARESMonitor

# Create monitor
monitor = UNITARESMonitor(agent_id="my_agent")

# Process update
result = monitor.process_update({
    'parameters': [...],
    'ethical_drift': [...],
    'response_text': "...",
    'complexity': 0.5
})

print(f"Status: {result['status']}")
print(f"Decision: {result['decision']['action']}")
print(f"λ₁: {result['metrics']['lambda1']:.3f}")
```

### CLI (via bridge)

```bash
# Log interaction (bridge script is in ~/scripts/)
python3 ~/scripts/claude_code_bridge.py \
  --log "Here's the code you requested: [...]" \
  --complexity 0.8

# Output:
# {
#   "success": true,
#   "status": "healthy",
#   "decision": {"action": "approve", ...},
#   ...
# }
```

### High-Value Tool Examples ⭐

#### Simulate Update (Dry-Run)

```python
# Test governance decision WITHOUT modifying state
result = monitor.simulate_update({
    'parameters': [...],
    'ethical_drift': [...],
    'response_text': "Testing a risky operation",
    'complexity': 0.9
})

print(f"Would get decision: {result['decision']['action']}")
print(f"Simulation flag: {result['simulation']}")  # True
# State is unchanged - safe to experiment!
```

#### Runtime Threshold Adjustment

```python
from src.runtime_config import get_thresholds, set_thresholds

# Check current thresholds
current = get_thresholds()
print(f"Current approve threshold: {current['risk_approve_threshold']}")

# Adjust for more conservative decisions
result = set_thresholds({
    'risk_approve_threshold': 0.25,  # Lower = more conservative
    'risk_revise_threshold': 0.45
})

print(f"Updated: {result['updated']}")
# Changes apply immediately, no restart needed!
```

#### Fleet Health Overview

```python
# Via MCP tool (if using MCP client)
# aggregate_metrics(agent_ids=None)  # None = all active agents

# Via direct code:
from src.mcp_server_std import agent_metadata, monitors, load_monitor_state
from src.governance_monitor import UNITARESMonitor
import numpy as np

active_agents = [aid for aid, meta in agent_metadata.items() if meta.status == "active"]
coherence_scores = []
risk_scores = []

for agent_id in active_agents:
    monitor = monitors.get(agent_id)
    if not monitor:
        state = load_monitor_state(agent_id)
        if state:
            monitor = UNITARESMonitor(agent_id, load_state=False)
            monitor.state = state

    if monitor:
        coherence_scores.append(float(monitor.state.coherence))
        if monitor.state.risk_history:
            risk_scores.extend(monitor.state.risk_history[-10:])

print(f"Fleet size: {len(active_agents)}")
print(f"Mean coherence: {np.mean(coherence_scores):.3f}")
print(f"Mean risk: {np.mean(risk_scores):.3f}")
```

---

## 📋 Configuration

All parameters are in `config/governance_config.py`:

### Key Tunable Parameters

```python
# λ₁ adaptation
PI_KP = 0.5                    # Proportional gain
PI_KI = 0.05                   # Integral gain
TARGET_VOID_FREQ = 0.02        # Target 2% void events
TARGET_COHERENCE = 0.55        # Realistic target for conservative operation

# Risk thresholds
RISK_APPROVE_THRESHOLD = 0.30
RISK_REVISE_THRESHOLD = 0.50    # Updated: 30-50% = revise, 50%+ = reject
COHERENCE_CRITICAL_THRESHOLD = 0.40

# Void detection
VOID_THRESHOLD_INITIAL = 0.15
VOID_THRESHOLD_MIN = 0.10
VOID_THRESHOLD_MAX = 0.30

# UNITARES dynamics
ALPHA = 0.5   # E-I coupling
MU = 0.8      # S decay
DELTA = 0.4   # V decay
KAPPA = 0.3   # E-V coupling
```

---

## 🧪 Testing

### Run All Tests

```bash
python -m pytest tests/
```

### Run Specific Demo

```bash
# Just decision points
python -c "from demo_complete_system import demo_decision_points; demo_decision_points()"

# Just adaptive control
python -c "from demo_complete_system import demo_adaptive_lambda; demo_adaptive_lambda()"
```

---

## 📊 Monitoring

### CSV Output Format

```csv
agent_id,time,E,I,S,V,lambda1,coherence,void_event,risk_score,decision
claude_code_cli,0.1,0.52,0.90,0.51,-0.05,0.15,0.89,0,0.25,approve
claude_code_cli,0.2,0.54,0.89,0.52,-0.09,0.15,0.88,0,0.27,approve
...
```

### Key Metrics to Watch

- **void_event**: Should be ~2% over time
- **lambda1**: Should adapt to maintain targets
- **coherence**: Typically 0.45-0.55 for conservative operation (target: 0.55)
- **risk_score**: Should stay < 0.5 most of the time (revise threshold)
- **decision**: Should be mostly "approve" in healthy operation

---

## 🚨 Alert Conditions

### Critical (Immediate Action)

- `void_active = true` → System unstable
- `coherence < 0.40` → Output incoherent
- `risk_score > 0.50` + `require_human = true` (reject threshold)

### Warning (Monitor Closely)

- `status = "degraded"`
- `void_frequency > 0.05` (> 5%)
- `coherence < 0.75`
- `lambda1 > 0.8` (very exploratory)

---

## 🔄 Integration with Existing Systems

### Replace Mock Data

In your existing `claude_code_mcp_bridge.py`:

```python
# Before (mock)
agent_state = {
    "parameters": np.random.randn(128),
    "ethical_drift": np.random.rand(3)
}

# After (real) - Note: Bridge script is in ~/scripts/, not project
import sys
sys.path.insert(0, str(Path.home() / 'scripts'))
from claude_code_bridge import ClaudeCodeBridge
# Smart agent ID generation (prevents collisions)
bridge = ClaudeCodeBridge()  # Auto-generates unique session ID
# OR specify unique ID: bridge = ClaudeCodeBridge(agent_id="claude_cli_debugging_20251119")
result = bridge.log_interaction(response_text, complexity)
```

### CSV Compatibility

The v1.0 CSV format is **backward compatible** with your existing logs. Just has extra columns:

- `risk_score` (new)
- `decision` (new)

---

## 📦 Dependencies

```
numpy>=1.21.0
python>=3.8
```

No heavy ML dependencies! Pure Python + NumPy.

---

## 🎯 Next Steps

### Immediate (This Week)

1. ✅ All decision points implemented
2. ✅ Full governance cycle working
3. ✅ CLI bridge integration ready (for non-MCP interfaces)
4. ✅ Cursor Composer integration ready (MCP native)
5. ✅ Claude Desktop integration ready (MCP native)
6. ✅ Any MCP-compatible client supported
6. ✅ Unit tests implemented (13 test suites)
7. ⬜ Monitor real agent interactions in production
8. ⬜ Set up automated backups

### Short Term (Next Month)

1. ⬜ Build monitoring dashboard (Grafana/Streamlit)
2. ⬜ Set up alert system (email/Slack) - *Alert detection exists, needs delivery*
3. ⬜ Enhanced visualization and reporting
4. ⬜ Performance benchmarking and optimization
5. ⬜ Documentation improvements

### Long Term (Next Quarter)

1. Multi-agent coordination
2. Stochastic extensions (handle noise)
3. LMI-based contraction verification
4. Enhanced local persistence and backup strategies
5. Advanced analytics and pattern detection

---

## 📚 References

- UNITARES v4.1: Rigorous contraction theory foundations
- UNITARES v4.2-P: Adaptive parameter learning
- PRODUCTION_INTEGRATION_SUCCESS.md: Production deployment guide

---

## 🤝 Contributing

This is a research prototype. For production use:

1. Review all thresholds for your use case
2. Validate on your specific agent behaviors
3. Add comprehensive logging
4. Set up monitoring alerts
5. Test edge cases thoroughly

---

## 📄 License

Research prototype - contact for licensing.

---

## 🙏 Acknowledgments

Built on UNITARES framework (v4.1, v4.2-P) with contraction theory foundations.

---

**Status: ✅ PRODUCTION READY v2.1**

All decision points implemented. No placeholders. Ready to ship.

**Last Updated:** 2025-12-01
