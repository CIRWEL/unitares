#!/usr/bin/env python3
"""
Demo: OpenAI Codex connecting to Governance MCP via HTTP API

This demonstrates how any OpenAI model (Codex, GPT-4, etc.) can use
the Governance MCP for multi-agent coordination.

Usage:
    export OPENAI_API_KEY=sk-...  # Optional, for real OpenAI calls
    python examples/openai_codex_demo.py
"""

import requests
import json

# Governance MCP HTTP endpoint
GOVERNANCE_URL = "http://127.0.0.1:8765"
AGENT_ID = "demo_openai_codex"


def demo_http_api():
    """Demonstrate HTTP API integration (no OpenAI key needed)"""

    print("=" * 60)
    print("OpenAI Codex → Governance MCP Integration Demo")
    print("=" * 60)

    # Step 1: Fetch available tools
    print("\n[1] Fetching governance tools...")
    response = requests.get(f"{GOVERNANCE_URL}/v1/tools")
    response.raise_for_status()
    tools_data = response.json()
    print(f"    ✅ Found {tools_data['count']} governance tools")
    print(f"    📋 Sample tools: {[t['function']['name'] for t in tools_data['tools'][:5]]}")

    # Step 2: Log work (simulating Codex doing a coding task)
    print("\n[2] Logging work to governance system...")
    payload = {
        "name": "process_agent_update",
        "arguments": {
            "agent_id": AGENT_ID,
            "operation": "Testing OpenAI Codex integration via HTTP API",
            "complexity": 0.3
        }
    }
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Session-ID": AGENT_ID
        }
    )
    response.raise_for_status()
    result = response.json()

    if result.get("result", {}).get("success"):
        print(f"    ✅ Work logged successfully")
        decision = result["result"].get("decision", {})
        print(f"    🎯 Governance action: {decision.get('action', 'N/A')}")
        print(f"    📝 Reason: {decision.get('reason', 'N/A')}")
        if decision.get("guidance"):
            print(f"    💡 Guidance: {decision['guidance']}")

    # Step 3: Search knowledge graph
    print("\n[3] Searching knowledge graph for related work...")
    payload = {
        "name": "search_knowledge_graph",
        "arguments": {
            "query": "OpenAI integration"
        }
    }
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={"Content-Type": "application/json", "X-Session-ID": AGENT_ID}
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        discoveries = result["result"].get("discoveries", [])
        print(f"    ✅ Found {len(discoveries)} related discoveries")
        for d in discoveries[:3]:
            print(f"       - {d['summary']} (by {d['agent_id']})")

    # Step 4: Store a discovery
    print("\n[4] Storing discovery in knowledge graph...")
    payload = {
        "name": "store_discovery_graph",
        "arguments": {
            "agent_id": AGENT_ID,
            "discovery_type": "integration",
            "summary": "OpenAI Codex can connect to Governance MCP via HTTP API",
            "details": "Using /v1/tools and /v1/tools/call endpoints with X-Session-ID header",
            "tags": ["openai", "http-api", "integration", "demo"]
        }
    }
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={"Content-Type": "application/json", "X-Session-ID": AGENT_ID}
    )
    response.raise_for_status()
    result = response.json()

    if result.get("result", {}).get("success"):
        disc_id = result["result"].get("id") or result["result"].get("discovery_id", "unknown")
        print(f"    ✅ Discovery stored with ID: {disc_id}")

    # Step 5: Get final governance metrics
    print("\n[5] Getting current governance metrics...")
    payload = {
        "name": "get_governance_metrics",
        "arguments": {
            "agent_id": AGENT_ID
        }
    }
    response = requests.post(
        f"{GOVERNANCE_URL}/v1/tools/call",
        json=payload,
        headers={"Content-Type": "application/json", "X-Session-ID": AGENT_ID}
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        metrics = result["result"]
        print(f"    ✅ Current EISV state:")
        print(f"       Energy (E): {metrics.get('E', 0):.3f}")
        print(f"       Integrity (I): {metrics.get('I', 0):.3f}")
        print(f"       Entropy (S): {metrics.get('S', 0):.3f}")
        print(f"       Void (V): {metrics.get('V', 0):.3f}")
        print(f"       Coherence: {metrics.get('coherence', 0):.3f}")
        print(f"       Risk Score: {metrics.get('risk_score', 0):.3f}")

    print("\n" + "=" * 60)
    print("✅ Demo complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. See docs/guides/OPENAI_CODEX_INTEGRATION.md for full guide")
    print("  2. Try with real OpenAI API key for actual Codex integration")
    print("  3. Run multiple agents to see multi-agent coordination")


def demo_with_openai():
    """Demonstrate with real OpenAI API (requires OPENAI_API_KEY)"""
    try:
        from openai import OpenAI
        import os

        if not os.getenv("OPENAI_API_KEY"):
            print("\n⚠️  OPENAI_API_KEY not set, skipping OpenAI demo")
            print("   Set it to see real OpenAI integration:")
            print("   export OPENAI_API_KEY=sk-...")
            return

        print("\n" + "=" * 60)
        print("OpenAI API Demo (with real GPT-4)")
        print("=" * 60)

        client = OpenAI()

        # Fetch governance tools
        response = requests.get(f"{GOVERNANCE_URL}/v1/tools")
        tools = response.json()["tools"]

        # Call OpenAI with governance tools
        print("\n💭 Calling GPT-4 with governance tools...")
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a coding assistant with governance tools."},
                {"role": "user", "content": "What governance tools do you have access to?"}
            ],
            tools=tools[:10],  # Use first 10 tools
            tool_choice="auto"
        )

        message = completion.choices[0].message
        print(f"\n📝 GPT-4 Response:\n{message.content}")

        if message.tool_calls:
            print(f"\n🔧 GPT-4 wants to call {len(message.tool_calls)} tools:")
            for call in message.tool_calls:
                print(f"   - {call.function.name}")

    except ImportError:
        print("\n⚠️  OpenAI library not installed")
        print("   Install with: pip install openai")
    except Exception as e:
        print(f"\n❌ OpenAI demo error: {e}")


if __name__ == "__main__":
    try:
        # Always run HTTP API demo (no OpenAI key needed)
        demo_http_api()

        # Optionally run OpenAI demo if key is available
        demo_with_openai()

    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Cannot connect to Governance MCP server")
        print("   Start the server with:")
        print("   python src/mcp_server_sse.py --port 8765")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
