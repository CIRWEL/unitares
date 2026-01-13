# UNITARES Governance MCP Server - Docker Image
# Multi-agent coordination and governance system

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better caching)
COPY requirements-full.txt requirements-core.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-full.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DATA_DIR=/app/data
ENV LOG_DIR=/app/logs

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

# Run the SSE server
CMD ["python", "src/mcp_server_sse.py", "--host", "0.0.0.0", "--port", "8765"]

