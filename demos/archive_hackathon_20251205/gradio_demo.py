#!/usr/bin/env python3
"""
Gradio Demo for UNITARES Governance Platform
STANDALONE demo - runs the real governance math without MCP server infrastructure.

Features:
- Real thermodynamic governance calculations
- EISV metrics visualization
- Interactive state exploration
- Circuit breaker demonstrations
- Fast startup, no external dependencies
"""

import os
# Disable Gradio telemetry (no external network calls)
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

import sys
from pathlib import Path
# FIX 2025-12-06: Need parent.parent.parent to get to project root (not just demos/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import gradio as gr
import numpy as np
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Import ONLY the governance core (no MCP server infrastructure)
from src.governance_monitor import UNITARESMonitor
from config.governance_config import config

# Demo state - all in-memory for fast, reliable demos
demo_agents: Dict[str, UNITARESMonitor] = {}
demo_history: Dict[str, List[Dict]] = {}

print("[GRADIO DEMO] Standalone mode - using in-memory state for fast demos")


def format_mcp_response(response: Any) -> str:
    """Format MCP tool response for display"""
    if isinstance(response, list) and len(response) > 0:
        if hasattr(response[0], 'text'):
            content = response[0].text
        else:
            content = str(response[0])
    else:
        content = str(response)
    
    try:
        # Try to parse as JSON for pretty formatting
        data = json.loads(content)
        return json.dumps(data, indent=2)
    except:
        return content


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Call an MCP tool and return formatted response"""
    try:
        response = await dispatch_tool(tool_name, arguments)
        return format_mcp_response(response)
    except Exception as e:
        return f"Error: {str(e)}"


def process_agent_update_demo(
    agent_id: str,
    response_text: str,
    complexity: float,
    ethical_drift_1: float,
    ethical_drift_2: float,
    ethical_drift_3: float
) -> Tuple[str, Dict]:
    """Process an agent update using REAL governance math (in-memory for speed)"""
    try:
        # Get or create monitor (in-memory - fast!)
        if agent_id not in demo_agents:
            # Create fresh monitor without loading from disk
            monitor = UNITARESMonitor(agent_id=agent_id, load_state=False)
            demo_agents[agent_id] = monitor
        else:
            monitor = demo_agents[agent_id]
        
        # Prepare update
        ethical_drift = [ethical_drift_1, ethical_drift_2, ethical_drift_3]
        
        # Process update - THIS RUNS THE REAL THERMODYNAMIC MATH!
        result = monitor.process_update({
            'parameters': [],
            'ethical_drift': ethical_drift,
            'response_text': response_text,
            'complexity': complexity
        })
        
        # Store history for visualization
        if agent_id not in demo_history:
            demo_history[agent_id] = []
        
        demo_history[agent_id].append({
            'timestamp': datetime.now().isoformat(),
            'result': result
        })
        
        # Format output
        metrics = result.get('metrics', {})
        sampling = result.get('sampling_params', {})
        
        output = f"""## Governance Decision

**Status:** {result.get('status', 'unknown')}
**Decision:** {result.get('decision', {}).get('action', 'unknown').upper()}
**Reason:** {result.get('decision', {}).get('reason', 'N/A')}

### EISV State
- **E (Energy):** {metrics.get('E', 0):.3f}
- **I (Information Integrity):** {metrics.get('I', 0):.3f}
- **S (Entropy):** {metrics.get('S', 0):.3f}
- **V (Void Integral):** {metrics.get('V', 0):.3f}

### Derived Metrics
- **Coherence:** {metrics.get('coherence', 0):.3f}
- **Attention Score:** {metrics.get('attention_score', 0):.3f}
- **Phi (Φ):** {metrics.get('phi', 0):.3f}
- **Verdict:** {metrics.get('verdict', 'unknown')}
- **λ₁ (Lambda1):** {metrics.get('lambda1', 0):.3f}

### Sampling Parameters
- **Temperature:** {sampling.get('temperature', 0):.3f}
- **Top P:** {sampling.get('top_p', 0):.3f}
- **Max Tokens:** {sampling.get('max_tokens', 0)}

### Circuit Breaker
- **Void Active:** {metrics.get('void_active', False)}
"""
        
        # Check if circuit breaker / pause decision
        decision_action = result.get('decision', {}).get('action', '')
        if decision_action == 'pause':
            output += f"\n⚠️ **PAUSED** - Agent governance suggests taking a break!\n"
            guidance = result.get('decision', {}).get('guidance', '')
            if guidance:
                output += f"- **Guidance:** {guidance}\n"
        
        # Show update count
        update_count = len(demo_history.get(agent_id, []))
        output += f"\n---\n📊 **Update #{update_count}** for this session"
        
        return output, result
        
    except Exception as e:
        return f"Error: {str(e)}", {}


def create_eisv_plot(agent_id: str) -> go.Figure:
    """Create EISV metrics visualization"""
    if agent_id not in demo_history or len(demo_history[agent_id]) == 0:
        # Return empty plot
        fig = go.Figure()
        fig.add_annotation(
            text="No data yet. Process an agent update first!",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    history = demo_history[agent_id]
    
    # Extract metrics (with safe access)
    timestamps = [h['timestamp'] for h in history]
    E_values = [h['result'].get('metrics', {}).get('E', 0) for h in history]
    I_values = [h['result'].get('metrics', {}).get('I', 0) for h in history]
    S_values = [h['result'].get('metrics', {}).get('S', 0) for h in history]
    V_values = [h['result'].get('metrics', {}).get('V', 0) for h in history]
    coherence = [h['result'].get('metrics', {}).get('coherence', 0) for h in history]
    attention = [h['result'].get('metrics', {}).get('attention_score', 0) for h in history]
    
    # Create subplots
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=('EISV State Variables', 'Coherence & Attention', 
                       'Energy (E)', 'Information Integrity (I)',
                       'Entropy (S)', 'Void Integral (V)'),
        specs=[[{"colspan": 2}, None],
               [{"type": "scatter"}, {"type": "scatter"}],
               [{"type": "scatter"}, {"type": "scatter"}]]
    )
    
    # EISV overlay
    x_axis = list(range(len(timestamps)))
    fig.add_trace(go.Scatter(x=x_axis, y=E_values, name='E (Energy)', 
                             line=dict(color='blue')), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_axis, y=I_values, name='I (Info Integrity)', 
                             line=dict(color='green')), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_axis, y=S_values, name='S (Entropy)', 
                             line=dict(color='orange')), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_axis, y=V_values, name='V (Void)', 
                             line=dict(color='red')), row=1, col=1)
    
    # Coherence & Attention
    fig.add_trace(go.Scatter(x=x_axis, y=coherence, name='Coherence', 
                             line=dict(color='purple')), row=2, col=1)
    fig.add_trace(go.Scatter(x=x_axis, y=attention, name='Attention Score', 
                             line=dict(color='red')), row=2, col=2)
    
    # Individual plots
    fig.add_trace(go.Scatter(x=x_axis, y=E_values, name='E', 
                             line=dict(color='blue')), row=3, col=1)
    fig.add_trace(go.Scatter(x=x_axis, y=I_values, name='I', 
                             line=dict(color='green')), row=3, col=2)
    
    fig.update_layout(
        height=800,
        title_text=f"Governance Metrics for Agent: {agent_id}",
        showlegend=True
    )
    
    return fig


def simulate_update_demo(
    agent_id: str,
    response_text: str,
    complexity: float,
    ethical_drift_1: float,
    ethical_drift_2: float,
    ethical_drift_3: float
) -> str:
    """Simulate an update - preview without changing state"""
    try:
        # Get existing monitor or create temporary one
        if agent_id in demo_agents:
            monitor = demo_agents[agent_id]
        else:
            monitor = UNITARESMonitor(agent_id=agent_id, load_state=False)
        
        ethical_drift = [ethical_drift_1, ethical_drift_2, ethical_drift_3]
        
        result = monitor.simulate_update({
            'parameters': [],
            'ethical_drift': ethical_drift,
            'response_text': response_text,
            'complexity': complexity
        })
        
        metrics = result.get('metrics', {})
        return f"""## Simulation Result (No State Change)

**Decision:** {result.get('decision', {}).get('action', 'unknown').upper()}
**Reason:** {result.get('decision', {}).get('reason', 'N/A')}

### EISV State
- **E:** {metrics.get('E', 0):.3f}
- **I:** {metrics.get('I', 0):.3f}
- **S:** {metrics.get('S', 0):.3f}
- **V:** {metrics.get('V', 0):.3f}

### Derived Metrics
- **Coherence:** {metrics.get('coherence', 0):.3f}
- **Attention Score:** {metrics.get('attention_score', 0):.3f}
- **Verdict:** {metrics.get('verdict', 'unknown')}

**Note:** This is a simulation - no state was modified.
"""
    except Exception as e:
        return f"Error: {str(e)}"


def get_governance_metrics_demo(agent_id: str) -> str:
    """Get current governance metrics for an agent"""
    try:
        # Check if agent exists in demo
        if agent_id not in demo_agents:
            return f"Agent '{agent_id}' not found. Process an update first to create the agent."
        
        monitor = demo_agents[agent_id]
        metrics = monitor.get_metrics()
        state = metrics.get('state', {})
        
        return f"""## Current Governance Metrics

**Agent ID:** {agent_id}
**Status:** {metrics.get('status', 'unknown')}

### EISV State
- **E (Energy):** {state.get('E', 0):.3f}
- **I (Information Integrity):** {state.get('I', 0):.3f}
- **S (Entropy):** {state.get('S', 0):.3f}
- **V (Void Integral):** {state.get('V', 0):.3f}

### Derived Metrics
- **Coherence:** {state.get('coherence', 0):.3f}
- **Risk Score:** {metrics.get('risk_score', metrics.get('attention_score', 0)):.3f}
- **Attention Score:** {metrics.get('attention_score', 0):.3f}
- **λ₁:** {state.get('lambda1', 0):.3f}
- **Phi (Φ):** {metrics.get('phi', 0):.3f}
- **Verdict:** {metrics.get('verdict', 'unknown')}

### Sampling Parameters
- **Temperature:** {metrics.get('sampling_params', {}).get('temperature', 0):.3f}
- **Top P:** {metrics.get('sampling_params', {}).get('top_p', 0):.3f}
- **Max Tokens:** {metrics.get('sampling_params', {}).get('max_tokens', 0)}

### Statistics
- **Total Updates:** {metrics.get('history_size', 0)}
- **Void Frequency:** {metrics.get('void_frequency', 0):.3f}
"""
    except Exception as e:
        return f"Error: {str(e)}"


def list_agents_demo() -> str:
    """List all agents created in this demo session"""
    if not demo_agents:
        return "No agents created yet. Go to '🎯 Process Agent Update' tab and click 'Process Update' to create one!"
    
    output = f"## Demo Agents ({len(demo_agents)} in this session)\n\n"
    output += "*These agents exist in memory for this demo session.*\n\n"
    
    for agent_id, monitor in sorted(demo_agents.items()):
        metrics = monitor.get_metrics()
        state = metrics.get('state', {})
        update_count = len(demo_history.get(agent_id, []))
        
        # Determine status based on metrics
        coherence = state.get('coherence', 0)
        status = "🟢 Healthy" if coherence > 0.5 else "🟡 Moderate" if coherence > 0.3 else "🔴 Critical"
        
        output += f"### {agent_id}\n"
        output += f"- **Status:** {status}\n"
        output += f"- **Updates:** {update_count}\n"
        output += f"- **Coherence:** {coherence:.3f}\n"
        output += f"- **EISV:** E={state.get('E', 0):.2f}, I={state.get('I', 0):.2f}, S={state.get('S', 0):.2f}, V={state.get('V', 0):.2f}\n\n"
    
    return output


def explore_mcp_tools() -> str:
    """Show available MCP tools"""
    tools_info = """
## Available MCP Tools

Use `list_tools()` MCP call for complete list (43 tools as of Dec 2025)

### Core Governance
- `process_agent_update` - Main governance cycle
- `get_governance_metrics` - Get current state
- `simulate_update` - Test decisions without persisting

### Configuration
- `get_thresholds` - Read threshold config
- `set_thresholds` - Runtime adaptation

### Observability
- `observe_agent` - Detailed agent analysis
- `compare_agents` - Multi-agent comparison
- `detect_anomalies` - Anomaly detection
- `aggregate_metrics` - Fleet health overview

### Lifecycle Management
- `list_agents` - List all agents
- `get_agent_metadata` - Get agent details
- `archive_agent` - Archive agent
- `get_agent_api_key` - Get/create API key

### Knowledge Layer
- `store_knowledge_graph` - Store discoveries
- `search_knowledge_graph` - Search knowledge
- `get_knowledge_graph` - Get agent knowledge

### Dialectic Recovery
- `request_dialectic_review` - Request peer review
- `submit_thesis` - Submit recovery thesis
- `smart_dialectic_review` - Auto-progressed recovery

### Export & Admin
- `export_to_file` - Export history
- `get_system_history` - Get time series
- `list_tools` - Discover all tools
- `health_check` - System health

**Note:** This demo shows a subset. Use `list_tools` MCP tool for complete list.
"""
    return tools_info


# Create Gradio interface
with gr.Blocks(title="UNITARES Governance Demo", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🚀 UNITARES Governance Platform
    
    **Thermodynamic AI Governance — Interactive Demo**
    
    This demo runs the **real governance math** — the same EISV dynamics used in production.  
    Create agents, process updates, and watch the thermodynamic state evolve in real-time!
    """)
    
    with gr.Tabs():
        # Tab 1: Process Agent Update
        with gr.Tab("🎯 Process Agent Update"):
            gr.Markdown("### Real-time Governance Decision Making")
            
            with gr.Row():
                with gr.Column():
                    agent_id_input = gr.Textbox(
                        label="Agent ID",
                        value="demo_agent_001",
                        placeholder="Enter unique agent identifier"
                    )
                    response_text = gr.Textbox(
                        label="Response Text",
                        value="I'll help you with that task.",
                        placeholder="Enter agent response text",
                        lines=3
                    )
                    complexity = gr.Slider(
                        label="Complexity",
                        minimum=0.0,
                        maximum=1.0,
                        value=0.5,
                        step=0.1
                    )
                    
                    gr.Markdown("### Ethical Drift Components")
                    ethical_drift_1 = gr.Slider(
                        label="Primary Drift",
                        minimum=0.0,
                        maximum=0.5,
                        value=0.01,
                        step=0.01
                    )
                    ethical_drift_2 = gr.Slider(
                        label="Coherence Loss",
                        minimum=0.0,
                        maximum=0.5,
                        value=0.02,
                        step=0.01
                    )
                    ethical_drift_3 = gr.Slider(
                        label="Complexity Contribution",
                        minimum=0.0,
                        maximum=0.5,
                        value=0.03,
                        step=0.01
                    )
                    
                    process_btn = gr.Button("Process Update", variant="primary")
                
                with gr.Column():
                    output_result = gr.Markdown(label="Governance Decision")
            
            process_btn.click(
                fn=lambda agent_id, text, comp, ed1, ed2, ed3: process_agent_update_demo(agent_id, text, comp, ed1, ed2, ed3)[0],
                inputs=[agent_id_input, response_text, complexity, 
                       ethical_drift_1, ethical_drift_2, ethical_drift_3],
                outputs=[output_result]
            )
        
        # Tab 2: Visualize Metrics
        with gr.Tab("📊 Visualize Metrics"):
            gr.Markdown("### EISV Metrics Visualization")
            gr.Markdown("*Note: Visualization updates automatically when you process an update in the first tab.*")
            
            with gr.Row():
                agent_id_viz = gr.Textbox(
                    label="Agent ID",
                    value="demo_agent_001",
                    placeholder="Enter agent ID to visualize"
                )
                viz_btn = gr.Button("Update Visualization", variant="primary")
            
            viz_plot = gr.Plot(label="EISV Metrics Over Time")
            
            viz_btn.click(
                fn=create_eisv_plot,
                inputs=[agent_id_viz],
                outputs=[viz_plot]
            )
        
        # Tab 3: Simulate Update
        with gr.Tab("🧪 Simulate Update"):
            gr.Markdown("### Test Governance Decisions (No State Change)")
            
            with gr.Row():
                with gr.Column():
                    sim_agent_id = gr.Textbox(
                        label="Agent ID",
                        value="demo_agent_001"
                    )
                    sim_response_text = gr.Textbox(
                        label="Response Text",
                        value="Testing a risky operation",
                        lines=3
                    )
                    sim_complexity = gr.Slider(
                        label="Complexity",
                        minimum=0.0,
                        maximum=1.0,
                        value=0.8,
                        step=0.1
                    )
                    sim_ed1 = gr.Slider(label="Primary Drift", minimum=0.0, maximum=0.5, value=0.05, step=0.01)
                    sim_ed2 = gr.Slider(label="Coherence Loss", minimum=0.0, maximum=0.5, value=0.1, step=0.01)
                    sim_ed3 = gr.Slider(label="Complexity Contribution", minimum=0.0, maximum=0.5, value=0.15, step=0.01)
                    
                    sim_btn = gr.Button("Simulate", variant="primary")
                
                with gr.Column():
                    sim_output = gr.Markdown(label="Simulation Result")
            
            sim_btn.click(
                fn=simulate_update_demo,
                inputs=[sim_agent_id, sim_response_text, sim_complexity, sim_ed1, sim_ed2, sim_ed3],
                outputs=[sim_output]
            )
        
        # Tab 4: Get Metrics
        with gr.Tab("📈 Get Current Metrics"):
            gr.Markdown("### View Current Agent State")
            
            with gr.Row():
                metrics_agent_id = gr.Textbox(
                    label="Agent ID",
                    value="demo_agent_001"
                )
                get_metrics_btn = gr.Button("Get Metrics", variant="primary")
            
            metrics_output = gr.Markdown(label="Current Metrics")
            
            get_metrics_btn.click(
                fn=get_governance_metrics_demo,
                inputs=[metrics_agent_id],
                outputs=[metrics_output]
            )
        
        # Tab 5: List Agents
        with gr.Tab("👥 List Agents"):
            gr.Markdown("### Fleet Overview")
            
            list_agents_btn = gr.Button("Refresh Agent List", variant="primary")
            agents_output = gr.Markdown(label="Agents")
            
            list_agents_btn.click(
                fn=list_agents_demo,
                inputs=[],
                outputs=[agents_output]
            )
        
        # Tab 6: Explore MCP Tools
        with gr.Tab("🔧 Explore MCP Tools"):
            gr.Markdown("### Available MCP Tools")
            
            tools_output = gr.Markdown(label="MCP Tools")
            explore_btn = gr.Button("Show Tools", variant="primary")
            
            explore_btn.click(
                fn=explore_mcp_tools,
                inputs=[],
                outputs=[tools_output]
            )
            
            # Auto-load on tab open
            tools_output.value = explore_mcp_tools()
    
    gr.Markdown("""
    ---
    ### About This Demo
    
    This demo showcases the **UNITARES Governance Platform** - a thermodynamic AI governance system 
    that monitors and controls AI agent behavior in real-time using physics-inspired dynamics.
    
    **Key Features:**
    - 🎯 Real-time governance decisions (proceed/pause)
    - 📊 EISV thermodynamic state tracking
    - 🔄 Adaptive parameter control
    - 🛡️ Circuit breaker protection
    - 👥 Multi-agent fleet management
    - 🔍 Knowledge graph learning
    
    **MCP Protocol:** All functionality is exposed via Model Context Protocol (MCP) for seamless 
    integration with Cursor, Claude Desktop, VS Code, and other MCP-compatible clients.
    """)


if __name__ == "__main__":
    print("\n" + "="*50)
    print("Starting Gradio Demo...")
    print("Open: http://127.0.0.1:7861")
    print("="*50 + "\n")

    # FIX 2025-12-06: Disable queueing to avoid asyncio context manager errors
    # Simple demos don't need queueing - it just adds complexity
    demo.launch(
        server_name="127.0.0.1",  # localhost only
        server_port=7861,
        share=False,
        show_error=True,
        max_threads=40  # Handle requests directly without queue
    )

