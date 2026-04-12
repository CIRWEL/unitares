"""Shared configuration for UNITARES resident agents."""

from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Governance endpoints — override via env vars if needed
GOV_MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8767/mcp/")
GOV_REST_URL = os.getenv("GOV_REST_URL", "http://localhost:8767/v1/tools/call")
GOV_HEALTH_URL = os.getenv("GOV_HEALTH_URL", "http://localhost:8767/health")
GOV_WS_URL = os.getenv("GOV_WS_URL", "ws://localhost:8767/ws/eisv")
