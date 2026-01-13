# Progressive Disclosure Design for Tool Discovery

**Created:** December 29, 2025  
**Status:** Design Proposal

## Problem

We have multiple tool filtering modes (`lite`, `essential_only`, `tier`, etc.) but no way to progressively reveal tools based on actual usage patterns. Agents see either:
- All tools (overwhelming)
- Filtered subset (may miss useful tools)

## Key Insight

**Progressive disclosure is about ORDERING and GROUPING, not filtering.**

Existing modes handle filtering. Progressive disclosure should:
1. Order tools by usage frequency (most used first)
2. Group into "core" vs "extended" sections
3. Show counts ("5 more tools available")
4. Work WITH existing modes, not replace them

## Design

### New Parameter: `progressive` (bool, default: false)

When `progressive=true`:
- Orders tools by usage frequency (most used first)
- Groups into sections: "Most Used" → "Commonly Used" → "Available"
- Shows counts: "Showing top 10 of 50 tools. Use `expand=true` to see all."
- Respects existing filters (`tier`, `essential_only`, etc.)

### Usage Stats Integration

```python
# Get usage stats (7-day window)
usage_stats = get_tool_usage_stats(window_hours=168)

# Order tools by call_count (descending)
# Fallback to tier-based ordering if no stats
tool_order = sorted(
    tools,
    key=lambda t: (
        usage_stats.get(t.name, {}).get("call_count", 0),
        tier_priority[t.tier]  # Fallback ordering
    ),
    reverse=True
)
```

### Progressive Grouping

1. **Most Used** (top 10-15): Tools with >10 calls in last 7 days
2. **Commonly Used** (next 10-15): Tools with 1-10 calls
3. **Available** (rest): Tools with 0 calls or no stats

### Response Structure

```json
{
  "tools": [...],  // Ordered by usage
  "sections": {
    "most_used": {
      "tools": [...],
      "count": 12,
      "threshold": ">10 calls/week"
    },
    "commonly_used": {
      "tools": [...],
      "count": 15,
      "threshold": "1-10 calls/week"
    },
    "available": {
      "tools": [...],
      "count": 23,
      "threshold": "0 calls or new"
    }
  },
  "progressive": {
    "enabled": true,
    "showing": "top_20",  // or "all"
    "total": 50,
    "expand": "Use expand=true to see all tools"
  }
}
```

## Implementation Strategy

### Phase 1: Ordering Only (No Breaking Changes)

Add `progressive=true` parameter that:
- Orders tools by usage stats (when available)
- Falls back to tier-based ordering
- No grouping yet (backward compatible)

### Phase 2: Grouping

Add sections when `progressive=true`:
- Most Used / Commonly Used / Available
- Show counts per section

### Phase 3: Expansion Control

Add `expand` parameter:
- `expand=false` (default): Show top N tools
- `expand=true`: Show all tools (still ordered by usage)

## Compatibility with Existing Modes

Progressive disclosure works WITH existing modes:

| Mode | Progressive Behavior |
|------|---------------------|
| `lite=true` | Order lite tools by usage |
| `essential_only=true` | Order essential tools by usage |
| `tier=common` | Order common tools by usage |
| `progressive=true` | Order ALL filtered tools by usage |

**Example:**
```python
list_tools(
    essential_only=true,  # Filter to tier 1
    progressive=true     # Order by usage within tier 1
)
# Result: Essential tools ordered by most-used first
```

## Benefits

1. **Reduces cognitive load**: Most useful tools appear first
2. **Data-driven**: Uses actual usage patterns, not assumptions
3. **Backward compatible**: Existing modes still work
4. **Flexible**: Can combine with any filter mode
5. **Discoverable**: Shows "more tools available" hints

## Edge Cases

1. **No usage stats**: Fallback to tier-based ordering
2. **New tools**: Appear in "Available" section
3. **Tie scores**: Use tier priority as tiebreaker
4. **Empty filters**: Progressive still orders all tools

## Future Enhancements

1. **Personalized ordering**: Order by agent's own usage
2. **Context-aware**: Show relevant tools based on current task
3. **Learning**: Adapt ordering based on agent patterns
4. **Categories**: Progressive disclosure within categories

