# Gradio Demo Summary

## What Was Created

A comprehensive Gradio web interface to showcase your UNITARES Governance MCP platform for hackathon demonstrations.

## Files Created

1. **`gradio_demo.py`** - Main Gradio application
   - Interactive web interface with 6 tabs
   - Real-time governance decision making
   - EISV metrics visualization
   - Multi-agent fleet monitoring

2. **`requirements-gradio.txt`** - Dependencies for Gradio demo
   - gradio>=4.0.0
   - plotly>=5.0.0

3. **`launch_gradio.sh`** - Launch script
   - Checks dependencies
   - Auto-installs missing packages
   - Launches demo

4. **`README_GRADIO.md`** - Technical documentation
   - Setup instructions
   - Feature descriptions
   - Customization guide

5. **`HACKATHON_GUIDE.md`** - Presentation guide
   - Step-by-step presentation flow
   - Demo scenarios
   - Talking points
   - Troubleshooting

## Features Showcased

### 🎯 Process Agent Update
- Real-time governance decisions
- EISV metrics display
- Circuit breaker status
- Sampling parameters

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
- Complete MCP tool catalog (list_tools() for details)
- Category organization

## Quick Start

```bash
cd demos
./launch_gradio.sh
```

Or:

```bash
cd demos
pip install -r requirements-gradio.txt
python gradio_demo.py
```

## For Hackathon

### Public Sharing
```python
# In gradio_demo.py, change:
demo.launch(share=True)  # Creates public Gradio link
```

### Demo Scenarios
1. **Safe Operation** - Show normal governance flow
2. **High Complexity** - Demonstrate risk assessment
3. **Circuit Breaker** - Show safety mechanisms
4. **Multi-Agent** - Demonstrate scalability

## Architecture

The demo uses:
- **Gradio** for web interface
- **Plotly** for interactive visualizations
- **UNITARESMonitor** for governance logic
- **Direct Python calls** (not MCP protocol) for simplicity

Note: This is a demonstration interface. The actual MCP server runs separately and can be integrated with Cursor, Claude Desktop, etc.

## Customization

### Change Theme
```python
with gr.Blocks(theme=gr.themes.Monochrome()) as demo:
```

### Add More Tabs
```python
with gr.Tabs():
    with gr.Tab("🆕 New Feature"):
        # Your custom tab
        pass
```

### Custom Visualizations
Modify `create_eisv_plot()` to add:
- Risk threshold lines
- Decision boundaries
- Anomaly markers

## Next Steps

1. Test the demo locally
2. Practice presentation flow
3. Prepare backup screenshots/videos
4. Customize for your specific hackathon needs
5. Consider adding more visualizations or features

## Support

- See `HACKATHON_GUIDE.md` for presentation tips
- See `README_GRADIO.md` for technical details
- Check main `README.md` for project overview

Good luck with your hackathon! 🚀

