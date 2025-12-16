#!/bin/bash
# Quick health check: MCP vs Anthropic

echo "=== MCP Server ==="
curl -s --max-time 2 http://127.0.0.1:8765/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✓ MCP: {d.get(\"status\",\"?\")} v{d.get(\"version\",\"?\")}')" 2>/dev/null || echo "✗ MCP: Not responding"

echo ""
echo "=== PostgreSQL ==="
docker exec postgres-age psql -U postgres -d governance -c "SELECT 1" >/dev/null 2>&1 && echo "✓ PostgreSQL: Connected" || echo "✗ PostgreSQL: Not responding"

echo ""
echo "=== Anthropic API ==="
curl -s --max-time 5 https://status.claude.com/ >/dev/null 2>&1 && echo "✓ status.claude.com: Reachable" || echo "✗ status.claude.com: Unreachable"

echo ""
echo "If MCP ✓ but Cursor Claude fails → Anthropic API issue"
echo "If MCP ✗ → Run: launchctl kickstart -k gui/$(id -u)/com.unitares.mcp"
