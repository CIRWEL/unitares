# Progressive Disclosure Implementation Plan

**Created:** December 29, 2025  
**Status:** Implementation Proposal

## Strategy: Additive, Not Replacement

Progressive disclosure works **WITH** existing modes, not instead of them:

```
Existing: Filter → Sort → Return
New:      Filter → Sort (by usage) → Group → Return
```

## Implementation Steps

### Step 1: Add `progressive` Parameter (Non-Breaking)

Add to `handle_list_tools`:

```python
progressive = parse_bool(arguments.get("progressive"), False)
```

### Step 2: Usage-Based Ordering Function

```python
def order_tools_by_usage(tools_list: List[Dict], window_hours: int = 168) -> List[Dict]:
    """Order tools by usage frequency, fallback to tier-based ordering."""
    try:
        from src.tool_usage_tracker import get_tool_usage_tracker
        tracker = get_tool_usage_tracker()
        stats = tracker.get_usage_stats(window_hours=window_hours)
        usage_data = stats.get("tools", {})
    except Exception:
        usage_data = {}
    
    # Tier priority for fallback (essential > common > advanced)
    tier_priority = {"essential": 3, "common": 2, "advanced": 1}
    
    def sort_key(tool):
        tool_name = tool["name"]
        call_count = usage_data.get(tool_name, {}).get("call_count", 0)
        tier_prio = tier_priority.get(tool.get("tier", "common"), 0)
        # Primary: usage count (descending), Secondary: tier priority (descending)
        return (-call_count, -tier_prio)
    
    return sorted(tools_list, key=sort_key)
```

### Step 3: Progressive Grouping (Optional)

Only when `progressive=true`:

```python
def group_tools_progressively(tools_list: List[Dict], usage_data: Dict) -> Dict:
    """Group tools into Most Used / Commonly Used / Available."""
    most_used = []
    commonly_used = []
    available = []
    
    for tool in tools_list:
        tool_name = tool["name"]
        call_count = usage_data.get(tool_name, {}).get("call_count", 0)
        
        if call_count > 10:
            most_used.append(tool)
        elif call_count > 0:
            commonly_used.append(tool)
        else:
            available.append(tool)
    
    return {
        "most_used": {
            "tools": most_used,
            "count": len(most_used),
            "threshold": ">10 calls/week"
        },
        "commonly_used": {
            "tools": commonly_used,
            "count": len(commonly_used),
            "threshold": "1-10 calls/week"
        },
        "available": {
            "tools": available,
            "count": len(available),
            "threshold": "0 calls or new"
        }
    }
```

### Step 4: Integration Point

Insert after filtering, before lite mode check:

```python
# After all filters applied (line ~1321)
tools_list = [...]  # Filtered tools

# NEW: Progressive ordering (if enabled)
if progressive:
    tools_list = order_tools_by_usage(tools_list)
    # Optional: Add grouping metadata
    if not lite_mode:  # Only in full mode to avoid complexity
        usage_data = get_usage_data()  # Helper function
        sections = group_tools_progressively(tools_list, usage_data)
        # Add sections to response
else:
    # Existing behavior: tier-based ordering (or alphabetical)
    pass

# Continue with lite_mode check...
```

## Compatibility Matrix

| Mode | Progressive | Behavior |
|------|-------------|----------|
| `lite=true` | `false` | Current: Workflow-ordered lite tools |
| `lite=true` | `true` | New: Usage-ordered lite tools |
| `essential_only=true` | `false` | Current: Essential tools (tier order) |
| `essential_only=true` | `true` | New: Essential tools (usage order) |
| `tier=common` | `false` | Current: Common tools (alphabetical) |
| `tier=common` | `true` | New: Common tools (usage order) |
| Default | `false` | Current: All tools (alphabetical) |
| Default | `true` | New: All tools (usage order) |

## Response Format (Backward Compatible)

**Without progressive:**
```json
{
  "tools": [...],  // Alphabetical or tier-ordered
  "total_available": 50
}
```

**With progressive:**
```json
{
  "tools": [...],  // Usage-ordered
  "total_available": 50,
  "progressive": {
    "enabled": true,
    "ordered_by": "usage_frequency",
    "window": "7 days"
  },
  "sections": {  // Only if progressive=true AND not lite
    "most_used": {...},
    "commonly_used": {...},
    "available": {...}
  }
}
```

## Benefits

1. **Non-breaking**: Default behavior unchanged
2. **Opt-in**: Agents choose when to use progressive disclosure
3. **Composable**: Works with any filter mode
4. **Data-driven**: Uses actual usage patterns
5. **Graceful degradation**: Falls back to tier ordering if no stats

## Migration Path

1. **Phase 1**: Add ordering only (no grouping)
2. **Phase 2**: Add grouping in full mode
3. **Phase 3**: Make progressive default for new agents

## Example Usage

```python
# Current: Alphabetical order
list_tools()

# New: Usage-based order (respects filters)
list_tools(progressive=true)

# Combined with filters
list_tools(
    essential_only=true,  # Filter to tier 1
    progressive=true       # Order by usage within tier 1
)

# Lite mode with progressive
list_tools(
    lite=true,
    progressive=true  # Order lite tools by usage
)
```

