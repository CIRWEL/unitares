# UNITARES Governance MCP Server
#
# Build:
#   docker build -t unitares-governance .
#
# Run:
#   docker run -p 8767:8767 unitares-governance

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# Copy application code
COPY src/ src/
COPY governance_core/ governance_core/
COPY config/ config/
COPY dashboard/ dashboard/
COPY skills/ skills/
COPY VERSION .

EXPOSE 8767

CMD ["python", "src/mcp_server.py", "--host", "0.0.0.0", "--port", "8767", "--force"]
