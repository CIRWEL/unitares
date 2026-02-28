#!/usr/bin/env python3
"""
Validate that all tools are registered in all four required places:

1. TOOL_CATEGORIES in tool_modes.py (filtering)
2. TOOL_HANDLERS in mcp_handlers/__init__.py (dispatch)
3. @server.list_tools() in mcp_server_std.py (MCP protocol definition)
4. Handler function decorated with @mcp_tool (implementation)

Missing any of these causes "Tool not found" even if the tool appears in list_tools output.
"""

import sys
from pathlib import Path
import ast
import re

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def extract_tools_from_tool_modes():
    """Extract tools from TOOL_CATEGORIES in tool_modes.py"""
    tool_modes_file = project_root / "src" / "tool_modes.py"
    
    # Parse the Python file to extract TOOL_CATEGORIES
    with open(tool_modes_file, 'r') as f:
        tree = ast.parse(f.read())
    
    tools = set()
    
    # Find TOOL_CATEGORIES assignment
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'TOOL_CATEGORIES':
                    if isinstance(node.value, ast.Dict):
                        # Extract all string values from nested sets
                        for key, value in zip(node.value.keys, node.value.values):
                            if isinstance(value, ast.Set):
                                for elt in value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        tools.add(elt.value)
    
    return tools

def extract_tools_from_handlers_init():
    """Extract tools from TOOL_HANDLERS in mcp_handlers/__init__.py"""
    handlers_file = project_root / "src" / "mcp_handlers" / "__init__.py"
    
    # Use regex as fallback - TOOL_HANDLERS is a dictionary literal
    with open(handlers_file, 'r') as f:
        content = f.read()
    
    tools = set()
    
    # Find TOOL_HANDLERS = { ... } section
    # Pattern: "tool_name": handle_function,
    pattern = r'["\']([a-z_][a-z0-9_]*)["\']\s*:\s*handle_'
    matches = re.findall(pattern, content)
    tools.update(matches)
    
    return tools

def extract_tools_from_mcp_server():
    """Extract tools from Tool(name=...) in mcp_server_std.py list_tools()"""
    server_file = project_root / "src" / "mcp_server_std.py"
    
    # Parse the Python file to extract Tool(name=...) calls
    with open(server_file, 'r') as f:
        tree = ast.parse(f.read())
    
    tools = set()
    
    # Find Tool(name="tool_name") calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == 'Tool':
                # Look for name= keyword argument
                for keyword in node.keywords:
                    if keyword.arg == 'name':
                        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                            tools.add(keyword.value.value)
    
    return tools

def extract_tools_from_decorators():
    """Extract tools from @mcp_tool("tool_name") decorators"""
    handlers_dir = project_root / "src" / "mcp_handlers"
    tools = set()
    
    # Pattern to match @mcp_tool("tool_name")
    pattern = r'@mcp_tool\s*\(\s*["\']([a-z_][a-z0-9_]*)["\']'
    
    # Search all Python files in handlers directory
    for py_file in handlers_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        
        with open(py_file, 'r') as f:
            content = f.read()
            matches = re.findall(pattern, content)
            tools.update(matches)
    
    return tools

def main():
    """Validate all tools are registered in all four places"""
    print("🔍 Validating tool registration across all four points...\n")
    
    # Extract tools from each registration point
    tool_modes_tools = extract_tools_from_tool_modes()
    handlers_tools = extract_tools_from_handlers_init()
    mcp_server_tools = extract_tools_from_mcp_server()
    decorator_tools = extract_tools_from_decorators()
    
    print(f"📊 Registration Point Coverage:")
    print(f"  1. TOOL_CATEGORIES (tool_modes.py): {len(tool_modes_tools)} tools")
    print(f"  2. TOOL_HANDLERS (mcp_handlers/__init__.py): {len(handlers_tools)} tools")
    print(f"  3. MCP list_tools() (mcp_server_std.py): {len(mcp_server_tools)} tools")
    print(f"  4. @mcp_tool decorators: {len(decorator_tools)} tools\n")
    
    # Find missing tools
    all_tools = tool_modes_tools | handlers_tools | mcp_server_tools | decorator_tools
    
    # Filter out false positives (parameter names, etc.)
    false_positives = {"name", "type", "value", "key", "id"}
    all_tools = {t for t in all_tools if t not in false_positives}
    
    issues = []
    
    for tool in sorted(all_tools):
        missing = []
        if tool not in tool_modes_tools:
            missing.append("TOOL_CATEGORIES")
        # Note: Decorator-registered tools don't need manual TOOL_HANDLERS entry
        # They're auto-registered via decorators, so only check if not decorator-registered
        if tool not in handlers_tools and tool not in decorator_tools:
            missing.append("TOOL_HANDLERS (and not decorator-registered)")
        elif tool not in handlers_tools and tool in decorator_tools:
            # Decorator-registered - this is OK, skip TOOL_HANDLERS check
            pass
        if tool not in mcp_server_tools:
            missing.append("MCP list_tools()")
        if tool not in decorator_tools:
            missing.append("@mcp_tool decorator")
        
        if missing:
            issues.append((tool, missing))
    
    if issues:
        print("❌ Missing Registrations Found:\n")
        for tool, missing in issues:
            print(f"  {tool}:")
            for point in missing:
                print(f"    - Missing in {point}")
            print()
        
        print(f"\n⚠️  Found {len(issues)} tool(s) with missing registrations")
        return 1
    else:
        print("✅ All tools are registered in all four places!")
        return 0

if __name__ == "__main__":
    sys.exit(main())

