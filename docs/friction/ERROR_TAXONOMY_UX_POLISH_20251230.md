# Error Taxonomy Standardization & UX Polish

**Created:** December 30, 2025  
**Status:** Implemented  
**Priority:** High (Agent-Requested)

---

## Summary

Implemented standardized error taxonomy and UX polish improvements based on agent feedback and ticket requirements.

---

## Changes Implemented

### 1. Standardized Error Taxonomy ✅

**New Error Codes Added:**
- `MISSING_PARAMETER` - Specific parameter name included
- `INVALID_PARAMETER_TYPE` - Parameter name, expected type, provided type
- `PERMISSION_DENIED` - Operation and required role

**Files Modified:**
- `src/mcp_handlers/error_helpers.py` - Added new error helper functions
- `src/mcp_handlers/utils.py` - Updated `require_argument()` to use standardized errors
- `src/mcp_handlers/validators.py` - Updated `_format_param_error()` to parse and use specific error codes

**Before:**
```json
{
  "error": "invalid arguments",
  "error_code": "PARAMETER_ERROR"
}
```

**After:**
```json
{
  "error": "Missing required parameter: 'summary' for tool 'store_knowledge_graph'",
  "error_code": "MISSING_PARAMETER",
  "error_category": "validation_error",
  "details": {
    "error_type": "missing_parameter",
    "parameter": "summary",
    "tool_name": "store_knowledge_graph"
  },
  "recovery": {
    "action": "Include the missing required parameter",
    "related_tools": ["describe_tool", "list_tools"],
    "workflow": [
      "1. Check tool description with describe_tool(tool_name=...)",
      "2. Add the missing parameter to your call",
      "3. Retry your request"
    ]
  }
}
```

---

### 2. Improved Parameter Validation Errors ✅

**Enhancement:** Parameter validation now detects specific error types and uses appropriate error codes.

**Implementation:**
- Parses error messages to detect missing parameters vs type mismatches
- Uses `MISSING_PARAMETER` for missing required fields
- Uses `INVALID_PARAMETER_TYPE` for type mismatches
- Falls back to detailed error message for complex cases

**Example Type Error:**
```json
{
  "error": "Parameter 'tags' must be array, got string for tool 'store_knowledge_graph'",
  "error_code": "INVALID_PARAMETER_TYPE",
  "details": {
    "parameter": "tags",
    "expected_type": "array",
    "provided_type": "string",
    "tool_name": "store_knowledge_graph"
  }
}
```

---

### 3. Enhanced Fallback Messages ✅

**Improvement:** Fallback explanations now clearly explain WHY fallback was used.

**Before:**
```
"fallback_message": "No exact matches found. Retried with individual terms (OR operator)."
```

**After:**
```
"fallback_message": "Semantic search found no concepts similar to 'void state continuity' (similarity threshold: 0.25). Falling back to keyword search (FTS) for exact term matching."
```

**Changes:**
- Semantic → FTS fallback: Explains threshold and reason
- FTS → Individual terms: Lists which terms were searched
- Semantic threshold reduction: Shows both thresholds

---

### 4. Helpful Hints for Empty Results ✅

**New Feature:** When search returns 0 results, system provides actionable hints.

**Implementation:**
- Detects empty results
- Provides context-aware suggestions based on query type
- Suggests alternative search strategies

**Example:**
```json
{
  "count": 0,
  "empty_results_hints": [
    "Try: Broaden your search terms or use semantic search (semantic=true)",
    "Try: Search by tags instead (tags=['tag1', 'tag2'])",
    "Try: Remove agent_id filter to search across all agents"
  ],
  "tip": "No results found. Try: Broaden your search terms or use semantic search (semantic=true) Try: Search by tags instead (tags=['tag1', 'tag2'])"
}
```

---

## Error Code Reference

### Standardized Error Codes

| Code | Category | Use Case |
|------|----------|----------|
| `MISSING_PARAMETER` | validation_error | Required parameter not provided |
| `INVALID_PARAMETER_TYPE` | validation_error | Parameter type mismatch |
| `PERMISSION_DENIED` | auth_error | Operation requires permissions |
| `NOT_CONNECTED` | system_error | MCP server connection unavailable |
| `MISSING_CLIENT_SESSION_ID` | validation_error | client_session_id required but missing |
| `SESSION_MISMATCH` | auth_error | Session identity mismatch |
| `AGENT_NOT_FOUND` | validation_error | Agent doesn't exist |
| `AGENT_NOT_REGISTERED` | validation_error | Agent not registered (needs onboarding) |
| `AUTHENTICATION_FAILED` | auth_error | Authentication failed |
| `AUTHENTICATION_REQUIRED` | auth_error | Authentication required |
| `OWNERSHIP_VIOLATION` | auth_error | Cannot modify resource owned by another agent |
| `RATE_LIMIT_EXCEEDED` | validation_error | Rate limit exceeded |
| `TIMEOUT` | system_error | Tool execution timed out |
| `RESOURCE_NOT_FOUND` | validation_error | Resource doesn't exist |
| `SYSTEM_ERROR` | system_error | Unexpected system error |

---

## Testing Recommendations

### Test Cases

1. **Missing Parameter:**
   ```python
   store_knowledge_graph()  # Missing 'summary'
   # Expected: MISSING_PARAMETER error with parameter name
   ```

2. **Invalid Type:**
   ```python
   store_knowledge_graph(summary="test", tags="not-an-array")
   # Expected: INVALID_PARAMETER_TYPE error with expected/provided types
   ```

3. **Empty Search Results:**
   ```python
   search_knowledge_graph(query="nonexistent_xyz_abc")
   # Expected: Empty results with helpful hints
   ```

4. **Fallback Behavior:**
   ```python
   search_knowledge_graph(query="very specific phrase that doesn't exist")
   # Expected: Fallback explanation showing why fallback was used
   ```

---

## Impact

**Agent Experience:**
- ✅ Clear error messages specify exactly what's wrong
- ✅ Actionable recovery guidance included
- ✅ Fallback behavior is transparent
- ✅ Empty results provide helpful suggestions

**Developer Experience:**
- ✅ Standardized error codes enable consistent error handling
- ✅ Error taxonomy makes debugging easier
- ✅ Recovery patterns reusable across tools

---

## Related Files

- `src/mcp_handlers/error_helpers.py` - Error taxonomy definitions
- `src/mcp_handlers/utils.py` - `require_argument()` uses standardized errors
- `src/mcp_handlers/validators.py` - Parameter validation uses specific error codes
- `src/mcp_handlers/knowledge_graph.py` - Enhanced fallback messages and empty result hints

---

**Status:** ✅ Complete - Ready for agent testing

