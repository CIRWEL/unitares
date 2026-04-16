"""
Count registered MCP tools for CI reporting.

Usage:
    python scripts/analysis/count_tools.py              # Print total count
    python scripts/analysis/count_tools.py --json       # Print as JSON
    python scripts/analysis/count_tools.py --by-module  # Breakdown by module
"""
import sys
import os
import json
import re
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

def count_tools():
    """Count @mcp_tool decorated functions across handler modules."""
    handlers_dir = os.path.join(PROJECT_ROOT, "src", "mcp_handlers")
    if not os.path.isdir(handlers_dir):
        return {}, 0

    by_module = defaultdict(list)
    total = 0

    for fname in sorted(os.listdir(handlers_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        filepath = os.path.join(handlers_dir, fname)
        with open(filepath) as f:
            content = f.read()

        # Find @mcp_tool("tool_name") decorators
        for match in re.finditer(r'@mcp_tool\(\s*["\'](\w+)["\']', content):
            tool_name = match.group(1)
            by_module[fname].append(tool_name)
            total += 1

    return dict(by_module), total

def main():
    by_module, total = count_tools()

    if "--json" in sys.argv:
        print(json.dumps({"total": total, "by_module": by_module}, indent=2))
    elif "--by-module" in sys.argv:
        for module, tools in sorted(by_module.items()):
            print(f"\n{module} ({len(tools)} tools):")
            for t in tools:
                print(f"  - {t}")
        print(f"\nTotal: {total} tools")
    else:
        print(f"{total} tools")

if __name__ == "__main__":
    main()
