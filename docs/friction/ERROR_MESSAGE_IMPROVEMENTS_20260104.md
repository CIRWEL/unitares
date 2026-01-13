# Error Message Improvements - January 4, 2026

**Created:** January 4, 2026  
**Status:** Complete

## Problem

Agents were getting unclear error messages when missing required parameters, especially for `leave_note` and `store_knowledge_graph`. The errors didn't provide examples or guidance on how to fix the issue.

## Solution

Enhanced error messages to include:
1. **Custom guidance messages** - When handlers provide custom error messages, they're now included
2. **Examples** - Common tools like `leave_note` and `store_knowledge_graph` now show example usage
3. **Parameter aliases** - For `leave_note`, shows alternative parameter names (note, text, content, etc.)
4. **Quick fixes** - Provides copy-paste ready examples

## Changes Made

### 1. Enhanced `require_argument()` (`src/mcp_handlers/utils.py`)
- Now passes custom error messages to `missing_parameter_error()`
- Preserves handler-specific guidance

### 2. Enhanced `missing_parameter_error()` (`src/mcp_handlers/error_helpers.py`)
- Includes custom messages from handlers
- Adds tool-specific examples for common tools:
  - `leave_note`: Shows example usage and parameter aliases
  - `store_knowledge_graph`: Shows example usage
- Provides quick-fix examples in error details

### 3. Updated Handlers
- `leave_note`: Sets `_tool_name` in context for better error messages
- `store_knowledge_graph`: Sets `_tool_name` in context for better error messages

## Example Error Messages

### Before:
```json
{
  "error": "Missing required parameter: 'summary'",
  "error_code": "MISSING_PARAMETER"
}
```

### After:
```json
{
  "error": "Missing required parameter: 'summary' for tool 'leave_note'. Note content required. Use 'summary', 'note', 'text', or 'content' parameter.",
  "error_code": "MISSING_PARAMETER",
  "details": {
    "error_type": "missing_parameter",
    "parameter": "summary",
    "tool_name": "leave_note",
    "examples": {
      "example": "leave_note(summary=\"Your note here\")",
      "aliases": "You can also use: 'note', 'text', 'content', 'message', 'insight', 'finding', 'learning'",
      "quick_fix": "Add summary parameter: leave_note(summary='Your note text')"
    }
  }
}
```

## Benefits

1. **Self-service debugging** - Agents can fix errors without human intervention
2. **Faster resolution** - Examples show exactly what to do
3. **Parameter discovery** - Aliases help agents find the right parameter name
4. **Consistent experience** - All tools benefit from enhanced error messages

## Testing

To test the improvements:
```python
# This should now show helpful error with examples
leave_note()  # Missing summary

# This should show helpful error with examples  
store_knowledge_graph()  # Missing summary
```

## Related

- Minimal mode default: Agents complained about verbose full mode, so minimal is now default
- Error taxonomy: Standardized error codes and recovery patterns
- Parameter aliases: Handlers accept multiple parameter names (e.g., "text" → "summary")

