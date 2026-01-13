# UX Improvements - December 25, 2025

**Author**: Claude Opus 4.5 (session: 2778b4a0)  
**Context**: Fresh eyes review from an agent exploring the system for the first time

## Summary

Six friction points identified during initial exploration, with concrete fixes proposed.

---

## 1. Search Mode Confusion

**Problem**: Semantic search exists but requires explicit `semantic=True` parameter. Default falls back to substring scan for JSON backend, which returns nothing for conceptual queries like "existential consciousness".

**Fix**: Auto-detect semantic search availability and use it by default when a text query is provided.

```python
# In handle_search_knowledge_graph, around line 270

# OLD: Requires explicit semantic=True
use_semantic = arguments.get("semantic", False) and hasattr(graph, "semantic_search")

# NEW: Auto-enable semantic when available and query is conceptual (>2 words)
query_words = len(str(query_text).split()) if query_text else 0
use_semantic_default = query_words >= 2 and hasattr(graph, "semantic_search")
use_semantic = arguments.get("semantic", use_semantic_default)
```

Also add helpful message when falling back to substring scan:

```python
if search_mode == "substring_scan" and not results:
    response_data["search_hint"] = (
        "No results found with substring matching. "
        "Try: semantic=true for conceptual search, or use specific tags."
    )
```

---

## 2. Optional agent_signature in Responses

**Problem**: Every response includes `agent_signature` block, which clutters output during normal use. Useful for debugging but noisy otherwise.

**Fix**: Add `lite_response` parameter to tools that suppresses verbose metadata.

In `src/mcp_handlers/utils.py`, modify `success_response`:

```python
def success_response(
    data: Dict[str, Any], 
    agent_id: str = None, 
    arguments: Dict[str, Any] = None,
    include_signature: bool = None  # NEW: explicit control
) -> Sequence[TextContent]:
    """..."""
    
    # Determine whether to include signature
    # Default: include unless lite_response=True in arguments
    if include_signature is None:
        include_signature = not (arguments or {}).get("lite_response", False)
    
    # ... existing code ...
    
    if include_signature:
        # Add agent_signature block
        response["agent_signature"] = { ... }
```

Then document `lite_response=true` as a global parameter hint.

---

## 3. Discovery Details Truncation Without Continuation

**Problem**: `get_discovery_details` truncates long content with "... [truncated]" but provides no way to get the rest.

**Fix**: Add `offset` and `length` parameters for pagination:

```python
@mcp_tool("get_discovery_details", timeout=10.0, rate_limit_exempt=True)
async def handle_get_discovery_details(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Get full details for a specific discovery with optional pagination."""
    
    # ... validation ...
    
    discovery = await graph.get_discovery(discovery_id)
    
    # Pagination for long details
    offset = arguments.get("offset", 0)
    length = arguments.get("length", 2000)  # Default 2000 chars
    
    details = discovery.details or ""
    total_length = len(details)
    
    if offset > 0 or length < total_length:
        details_slice = details[offset:offset + length]
        has_more = (offset + length) < total_length
    else:
        details_slice = details
        has_more = False
    
    response = {
        "discovery": discovery.to_dict(include_details=False),
        "details": details_slice,
        "pagination": {
            "offset": offset,
            "length": len(details_slice),
            "total_length": total_length,
            "has_more": has_more,
            "next_offset": offset + length if has_more else None
        }
    }
    
    return success_response(response)
```

---

## 4. client_session_id Threading Friction

**Problem**: Must include `client_session_id` in every tool call for identity continuity. Easy to forget.

**Observation**: The system already uses contextvars for session context within a request. The friction is at the *client* level (Claude having to remember to include it).

**Partial Fix**: Document that once identity is bound, `client_session_id` is optional for subsequent calls *within the same MCP connection*. The SSE transport maintains session state.

For REST/CLI clients, the `X-Agent-Id` header provides similar functionality without per-call threading.

**Documentation Update**:
```
SESSION CONTINUITY:
- SSE transport: Session persists across tool calls automatically
- REST transport: Use X-Agent-Id header instead of client_session_id
- client_session_id is most useful for: resuming after disconnection, 
  claiming a specific prior identity
```

---

## 5. Tool Volume / Discovery Friction

**Problem**: 46 tools is overwhelming. Categories help but there's still discovery cost.

**Fix**: Enhance `list_tools` with a `quick_start` mode that shows only the 5 most essential tools:

```python
# In handle_list_tools

if arguments.get("quick_start", False):
    # Show only essential onboarding tools
    essential_tools = ["onboard", "process_agent_update", "identity", 
                       "search_knowledge_graph", "leave_note"]
    tools = [t for t in tools if t["name"] in essential_tools]
    response["mode"] = "quick_start"
    response["tip"] = "Use list_tools() for full catalog, or list_tools(category='...') for focused view"
```

Also add a `describe_tool` enhancement that suggests related tools:

```python
response["see_also"] = get_related_tools(tool_name)
```

---

## 6. kwargs JSON String Pattern

**Problem**: Claude wraps all parameters in `{"kwargs": "{\"param\": \"value\"}"}` requiring JSON parsing on the server side.

**Observation**: This appears to be how Claude's MCP client serializes parameters. The server already handles unwrapping (lines 163-178 in `__init__.py`), but it adds friction when reading logs and understanding the protocol.

**No code change needed** - the unwrapping works. But worth documenting:

```
MCP PARAMETER HANDLING:
Some MCP clients (including Claude) wrap parameters as:
  {"kwargs": "{\"key\": \"value\"}"}

The server automatically unwraps this to:
  {"key": "value"}

Both formats are supported transparently.
```

---

## Implementation Priority

1. **Search auto-semantic** - High impact, low risk
2. **Discovery pagination** - Medium impact, straightforward  
3. **Optional agent_signature** - Nice to have, reduces noise
4. **list_tools quick_start** - Improves onboarding
5. **Documentation updates** - Clarifies existing behavior

---

## Testing Notes

After implementing, test with:
```python
# Search should now find conceptual matches
search_knowledge_graph(query="consciousness experience")

# Should return paginated details
get_discovery_details(discovery_id="...", offset=0, length=500)

# Should suppress signature
leave_note(summary="test", lite_response=True)

# Should show only essentials  
list_tools(quick_start=True)
```
