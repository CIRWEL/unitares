#!/bin/bash
# Launch script for Gradio demo

set -e

echo "🚀 Launching UNITARES Governance MCP Gradio Demo..."
echo ""

# Check if we're in the right directory
if [ ! -f "gradio_demo.py" ]; then
    echo "Error: gradio_demo.py not found. Please run this script from the demos/ directory."
    exit 1
fi

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Check if dependencies are installed
echo ""
echo "Checking dependencies..."

if ! python3 -c "import gradio" 2>/dev/null; then
    echo "❌ gradio not found. Installing..."
    pip install -q gradio>=4.0.0
fi

if ! python3 -c "import plotly" 2>/dev/null; then
    echo "❌ plotly not found. Installing..."
    pip install -q plotly>=5.0.0
fi

if ! python3 -c "import numpy" 2>/dev/null; then
    echo "❌ numpy not found. Installing..."
    pip install -q numpy>=1.24.0
fi

echo "✅ Dependencies OK"
echo ""

# Launch Gradio
echo "Starting Gradio interface..."
echo "Access at: http://localhost:7860"
echo "Press Ctrl+C to stop"
echo ""

python3 gradio_demo.py "$@"

