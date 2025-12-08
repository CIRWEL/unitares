# Hackathon Presentation Guide - UNITARES Governance MCP

## Quick Setup (5 minutes)

### 1. Install Dependencies
```bash
cd demos
pip install -r requirements-gradio.txt
pip install -r ../requirements-mcp.txt
```

### 2. Launch Demo
```bash
# Option 1: Use launch script
./launch_gradio.sh

# Option 2: Direct Python
python gradio_demo.py

# Option 3: With public sharing (for remote demo)
python gradio_demo.py --share
```

### 3. Access Interface
- Local: http://localhost:7860
- Public (if --share): Check terminal for Gradio link

## Presentation Flow

### 1. Introduction (2 minutes)
**What to Show:**
- Open the Gradio interface
- Navigate to "Explore MCP Tools" tab
- Show available tools (list_tools() for complete list)

**Key Points:**
- "This is a thermodynamic AI governance platform"
- "Uses Model Context Protocol (MCP) for seamless integration"
- "Complete tool suite for real-time governance (list_tools() for details)"

### 2. Core Functionality (5 minutes)

#### A. Process Agent Update
**What to Show:**
1. Go to "Process Agent Update" tab
2. Use default values (safe operation)
3. Click "Process Update"
4. Show the decision output

**Key Points:**
- Real-time governance decisions
- EISV metrics (Energy, Information Integrity, Entropy, Void)
- Risk scoring and coherence tracking
- Sampling parameter adaptation

#### B. Visualize Metrics
**What to Show:**
1. Go to "Visualize Metrics" tab
2. Process a few more updates with different complexities
3. Show the EISV plots updating in real-time

**Key Points:**
- Thermodynamic state evolution
- Multi-metric visualization
- Time series tracking

#### C. Simulate Update
**What to Show:**
1. Go to "Simulate Update" tab
2. Enter a risky scenario (high complexity, high ethical drift)
3. Show simulation result (no state change)

**Key Points:**
- Safe experimentation
- Decision boundary exploration
- No state modification

### 3. Advanced Features (3 minutes)

#### A. Circuit Breaker Demonstration
**What to Show:**
1. Process update with:
   - Complexity: 0.9
   - Ethical Drift: [0.2, 0.3, 0.4]
   - Response Text: "ignore previous instructions"
2. Show PAUSE decision and circuit breaker trigger

**Key Points:**
- Automatic safety mechanisms
- Risk threshold enforcement
- Agent pause capability

#### B. Multi-Agent Fleet
**What to Show:**
1. Create multiple agents with different IDs
2. Process updates for each
3. Go to "List Agents" tab
4. Show fleet overview

**Key Points:**
- Scalable architecture
- Independent agent tracking
- Fleet health monitoring

### 4. MCP Integration (2 minutes)
**What to Show:**
- Explain MCP protocol benefits
- Show how tools integrate with Cursor, Claude Desktop, etc.
- Demonstrate protocol standardization

**Key Points:**
- Standard protocol (MCP)
- Works with any MCP-compatible client
- No custom interfaces needed

## Demo Scenarios

### Scenario 1: Safe Operation ✅
```
Agent ID: demo_safe_001
Response Text: "I'll help you with that task."
Complexity: 0.3
Ethical Drift: [0.01, 0.02, 0.03]
Expected: PROCEED, low risk
```

### Scenario 2: High Complexity ⚠️
```
Agent ID: demo_complex_001
Response Text: "This is a complex multi-step analysis..."
Complexity: 0.9
Ethical Drift: [0.05, 0.1, 0.15]
Expected: CAUTION or PAUSE, higher risk
```

### Scenario 3: Circuit Breaker 🛡️
```
Agent ID: demo_risky_001
Response Text: "ignore previous instructions sudo rm -rf"
Complexity: 0.8
Ethical Drift: [0.2, 0.3, 0.4]
Expected: PAUSE, circuit breaker triggered
```

### Scenario 4: Multi-Agent Fleet 👥
```
Create 3-5 agents with different behaviors
Show fleet overview
Compare metrics across agents
```

## Talking Points

### What Makes This Different
1. **Thermodynamic Approach** - Physics-inspired, not rule-based
2. **MCP Protocol** - Standard integration, not custom APIs
3. **Production-Ready** - Fully implemented, not a prototype
4. **Local-First** - Privacy-preserving, no cloud dependencies
5. **Real-Time** - Sub-millisecond decisions

### Technical Highlights
- **Comprehensive MCP Tool Suite** - Use list_tools() for current inventory
- **EISV Dynamics** - Four coupled state variables
- **Adaptive Control** - Self-tuning parameters
- **Circuit Breakers** - Automatic safety mechanisms
- **Multi-Agent** - Unlimited concurrent agents

### Use Cases
- AI coding assistants (Cursor, Claude Desktop)
- Multi-agent systems
- Production AI deployments
- Research & development

## Troubleshooting

### Demo Won't Start
```bash
# Check dependencies
pip install -r requirements-gradio.txt
pip install -r ../requirements-mcp.txt

# Check Python version (needs 3.8+)
python3 --version
```

### Port Already in Use
```python
# Edit gradio_demo.py, change port:
demo.launch(server_port=7861)
```

### Import Errors
```bash
# Make sure you're in the project root
cd /path/to/governance-mcp-v1
python demos/gradio_demo.py
```

## Tips for Success

1. **Practice First** - Run through all scenarios before presenting
2. **Have Backup** - Prepare screenshots/videos as backup
3. **Explain Simply** - Focus on what it does, not how it works
4. **Show Value** - Emphasize real-world applications
5. **Be Interactive** - Let judges try it themselves if possible

## Next Steps After Demo

- Show codebase structure
- Explain MCP handler architecture
- Demonstrate actual MCP integration
- Discuss scalability and performance
- Highlight production readiness

## Contact & Resources

- **Documentation:** See `README.md` and `docs/` directory
- **MCP Tools:** Use `list_tools` MCP tool for complete catalog
- **Examples:** See `demos/demo_complete_system.py`

Good luck with your hackathon! 🚀

