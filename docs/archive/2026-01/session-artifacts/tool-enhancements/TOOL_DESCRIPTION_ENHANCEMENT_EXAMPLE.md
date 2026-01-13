# Tool Description Enhancement Example

**Created:** January 1, 2026  
**Status:** Example enhancement for get_governance_metrics

---

## Before vs After

### Before (Original)

```
Get current governance state and metrics for an agent without updating state.

✨ WHAT IT DOES:
- Shows your current "health" metrics (Energy, Integrity, Entropy, Void)
- Displays your risk score and coherence
...
```

**Problem:** Agent might think "I need to create a status tool" when `status()` already exists as an alias.

---

### After (Enhanced)

```
Get current governance state and metrics for an agent without updating state.

✨ WHAT IT DOES:
- Shows your current "health" metrics (Energy, Integrity, Entropy, Void)
- Displays your risk score and coherence
...

SEE ALSO:
- status() - Alias for this tool (intuitive name, same functionality)
- health_check() - System health (not agent-specific, server-level)
- get_connection_status() - MCP connection status (transport-level)
- identity() - Agent identity (who you are, not metrics)

ALTERNATIVES:
- Want intuitive name? → Use status() instead (same tool)
- Want system health? → Use health_check() (server-level, not agent metrics)
- Want connection status? → Use get_connection_status() (MCP transport)
- Want identity info? → Use identity() (who you are, display name, UUID)
```

**Benefit:** Agent immediately sees:
1. ✅ `status()` exists (alias)
2. ✅ Related tools for different use cases
3. ✅ Clear boundaries (what this tool does vs alternatives)

---

## Pattern for All Tools

**Template:**

```
TOOL DESCRIPTION

SEE ALSO:
- tool_name() - Brief description (relationship)
- tool_name() - Brief description (relationship)

ALTERNATIVES:
- Use case → tool_name() (why different)
- Use case → tool_name() (why different)
```

---

## Implementation Strategy

**Phase 1: High-traffic tools**
1. ✅ get_governance_metrics (done)
2. ⏳ identity
3. ⏳ process_agent_update
4. ⏳ search_knowledge_graph
5. ⏳ list_agents

**Phase 2: All tools**
- Add SEE ALSO / ALTERNATIVES to all tool descriptions
- Use consistent format
- Cross-reference related tools

---

**Status:** Example implemented  
**Action:** Apply pattern to all tools

