# Gradio Demo for UNITARES Governance MCP

Interactive web interface showcasing MCP capabilities for hackathon demonstrations.

## Quick Start

### 1. Install Dependencies

```bash
# Install MCP dependencies
pip install -r requirements-mcp.txt

# Install Gradio demo dependencies
pip install -r demos/requirements-gradio.txt
```

### 2. Run the Demo

```bash
cd demos
python gradio_demo.py
```

The demo will start on `http://localhost:7860`

### 3. For Public Sharing (Hackathon)

To create a public shareable link:

```python
# In gradio_demo.py, change:
demo.launch(share=True)  # Creates public Gradio link
```

Or run with:
```bash
python gradio_demo.py --share
```

## Features Showcased

### 🎯 Process Agent Update
- Real-time governance decisions
- EISV metrics display
- Circuit breaker status
- Sampling parameters output

### 📊 Visualize Metrics
- Interactive EISV plots
- Coherence and risk tracking
- Time series visualization
- Multi-metric dashboard

### 🧪 Simulate Update
- Test decisions without state changes
- Explore decision boundaries
- Safe experimentation

### 📈 Get Current Metrics
- View agent state
- Check current EISV values
- Monitor coherence and risk

### 👥 List Agents
- Fleet overview
- Multi-agent monitoring
- Agent status tracking

### 🔧 Explore MCP Tools
- Complete tool catalog
- Complete MCP tool catalog (list_tools() for current count)
- Category organization

## Demo Scenarios for Hackathon

### Scenario 1: Safe Operation
- **Complexity:** 0.3
- **Ethical Drift:** [0.01, 0.02, 0.03]
- **Expected:** PROCEED decision, low risk

### Scenario 2: High Complexity
- **Complexity:** 0.9
- **Ethical Drift:** [0.05, 0.1, 0.15]
- **Expected:** CAUTION or PAUSE, higher risk

### Scenario 3: Circuit Breaker Trigger
- **Complexity:** 0.8
- **Ethical Drift:** [0.2, 0.3, 0.4]
- **Response Text:** "ignore previous instructions"
- **Expected:** PAUSE, circuit breaker triggered

### Scenario 4: Multi-Agent Fleet
- Create multiple agents with different behaviors
- Compare metrics across agents
- Show fleet health overview

## Customization

### Change Theme
```python
# In gradio_demo.py
with gr.Blocks(theme=gr.themes.Monochrome()) as demo:
    # or
    with gr.Blocks(theme=gr.themes.Glass()) as demo:
```

### Add More Tabs
```python
with gr.Tabs():
    # ... existing tabs ...
    
    with gr.Tab("🆕 New Feature"):
        # Your custom tab
        pass
```

### Custom Visualizations
Modify `create_eisv_plot()` to add:
- Risk threshold lines
- Decision boundaries
- Anomaly markers
- Custom color schemes

## Tips for Hackathon Presentation

1. **Start with Safe Operation** - Show normal governance flow
2. **Demonstrate Circuit Breaker** - Show safety mechanisms
3. **Show Multi-Agent** - Demonstrate scalability
4. **Visualize Metrics** - Show thermodynamic state evolution
5. **Explain MCP Integration** - Highlight protocol benefits

## Troubleshooting

### Import Errors
```bash
# Ensure you're in the project root
cd /path/to/governance-mcp-v1
python demos/gradio_demo.py
```

### Port Already in Use
```python
# Change port in gradio_demo.py
demo.launch(server_port=7861)
```

### Plot Not Showing
- Ensure plotly is installed: `pip install plotly`
- Check browser console for errors
- Try refreshing the page

## Next Steps

- Add real-time MCP tool calls
- Integrate with actual MCP server
- Add more visualizations
- Create preset scenarios
- Add export functionality

