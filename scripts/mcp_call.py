#!/usr/bin/env python3
"""
MCP Tool Caller - Clean CLI for calling MCP tools without shell quoting issues.

Usage:
    # List all tools
    python scripts/mcp_call.py --list

    # Call a tool
    python scripts/mcp_call.py process_agent_update agent_id=my_agent update_type=reflection content="Hello world"

    # With session binding
    python scripts/mcp_call.py --session my_session bind_identity agent_id=my_agent

    # Show tool schema
    python scripts/mcp_call.py --describe update_agent_metadata
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

DEFAULT_URL = "http://127.0.0.1:8765"


def call_tool(
    base_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Call an MCP tool via HTTP."""
    url = f"{base_url}/v1/tools/call"
    data = json.dumps({"name": tool_name, "arguments": arguments}).encode()

    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["X-Session-ID"] = session_id

    req = urllib.request.Request(url, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "body": e.read().decode()}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def list_tools(base_url: str) -> None:
    """List all available tools."""
    url = f"{base_url}/v1/tools"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            tools = data.get("tools", [])
            print(f"Available tools ({len(tools)}):\n")
            for tool in sorted(tools, key=lambda t: t.get("function", {}).get("name", "")):
                func = tool.get("function", {})
                name = func.get("name", "?")
                desc = func.get("description", "")[:60]
                print(f"  {name}")
                if desc:
                    print(f"    {desc}...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def describe_tool(base_url: str, tool_name: str, session_id: Optional[str] = None) -> None:
    """Show tool schema."""
    result = call_tool(base_url, "describe_tool", {"tool_name": tool_name}, session_id)
    print(json.dumps(result, indent=2))


def parse_value(value: str) -> Any:
    """Parse a string value to appropriate type."""
    # Try JSON first (handles arrays, objects, booleans, numbers)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass

    # Try numeric
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        pass

    # Boolean strings
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False

    # Keep as string
    return value


def parse_arguments(args: list) -> Dict[str, Any]:
    """Parse key=value arguments."""
    result = {}
    for arg in args:
        if "=" not in arg:
            print(f"Warning: Ignoring argument without '=': {arg}", file=sys.stderr)
            continue
        key, value = arg.split("=", 1)
        result[key] = parse_value(value)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Call MCP tools without shell quoting issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list
  %(prog)s --describe process_agent_update
  %(prog)s --session my_session bind_identity agent_id=my_agent
  %(prog)s process_agent_update agent_id=test update_type=reflection content="test"
  %(prog)s search_knowledge_graph query=migration limit=5
  %(prog)s update_agent_metadata agent_id=test tags='["tag1","tag2"]'
        """,
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP server URL")
    parser.add_argument("--session", "-s", help="Session ID for X-Session-ID header")
    parser.add_argument("--list", "-l", action="store_true", help="List available tools")
    parser.add_argument("--describe", "-d", metavar="TOOL", help="Describe a tool")
    parser.add_argument("--raw", "-r", action="store_true", help="Output raw JSON")
    parser.add_argument("tool", nargs="?", help="Tool name to call")
    parser.add_argument("args", nargs="*", help="Tool arguments as key=value pairs")

    args = parser.parse_args()

    if args.list:
        list_tools(args.url)
        return

    if args.describe:
        describe_tool(args.url, args.describe, args.session)
        return

    if not args.tool:
        parser.print_help()
        sys.exit(1)

    arguments = parse_arguments(args.args)
    result = call_tool(args.url, args.tool, arguments, args.session)

    if args.raw:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
