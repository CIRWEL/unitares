# Ticket: Reduce MCP friction (Agent UX)

**Created:** December 28, 2025  
**Severity:** High  
**Tags:** ticket, ux, mcp, friction, session-binding, errors, kg-search, chatgpt-mac, unitares  
**Status:** Open

---

## Problem (observed in real use):

1. **Identity/session binding mismatch:** some tools accept agent_id and/or client_session_id inconsistently; passing agent_id can cause silent failures that feel like "no access."

2. **Errors are not self-healing:** mismatch errors don't always tell the agent how to fix it.

3. **KG search feels broken:** multi-term queries can return 0 due to AND-heavy FTS / field scope / tokenization.

4. **Mac ChatGPT UI forks composers:** users think tools are connected but are typing in a non-tool chatbox.

5. **Permissions feel inconsistent:** e.g., can write KG but can't rename identity → unclear boundaries.

---

## Proposed fixes:

### Identity/Session Binding
- **Make client_session_id the primary identity for writes;** treat agent_id as read-only metadata.

### Error Taxonomy + Remediation Hints
Standardize error taxonomy with remediation hints:
- `NOT_CONNECTED`
- `MISSING_CLIENT_SESSION_ID`
- `SESSION_MISMATCH` (include expected resolved IDs)
- `PERMISSION_DENIED` (include required role)

### Write Response Echo
Every write response should echo:
- `resolved_agent_id`
- `resolved_uuid`
- `resolved_client_session_id`

### KG Search Defaults
- default operator=OR (or mode=hybrid)
- if 0 results, auto-retry with fallback and say so
- return: `search_mode_used`, `fields_searched`, `operator_used`

### Connection Status
- Add `get_connection_status` tool
- Surface "Tools Connected ✅" clearly (esp. in Mac app composer split)

### Documentation
- Update `describe_tool` docs for each tool: which identity fields are accepted/required

---

## Acceptance criteria:

- ✅ A naive agent can onboard + write a note first try (no trial-and-error)
- ✅ If a mismatch happens, the next retry succeeds using the hint from the error
- ✅ Query: "EISV basin phi risk" returns results or explains fallback behavior
- ✅ User can tell which chatbox is tool-enabled in <3 seconds

---

## Agent UX "lab" scenarios (fast + revealing):

### 1. First contact
**Scenario:** agent discovers tools → onboards → writes one KG note  
**Measure:** time-to-first-success, number of failed calls

### 2. Resume vs fork
**Scenario:** open 2 tabs / sessions, see if identity collides  
**Measure:** collisions, confusion text ("who am I?"), mismatch errors

### 3. KG retrieval
**Scenario:** ask for something you know exists using vague phrasing  
**Measure:** 0-result rate, retries, whether it asks better queries

### 4. Approaching basin boundary
**Scenario:** simulate warning/critical → see if agent self-regulates  
**Measure:** behavior change, whether it uses "pause/resume" properly

### 5. Explainability
**Scenario:** agent must answer "why did I get blocked / warned?"  
**Measure:** does tool return enough info to explain action

---

## Metrics to log automatically:

- call success rate
- error type counts
- retries per task
- time-to-first-meaningful-result
- "confusion markers" (agent says "I can't access MCP" when it actually can)

---

## Notes:

- MCP connection dropped during initial filing attempt (store_knowledge_graph returned "Resource not found")
- Ticket formatted for direct implementation by coding agent
- UX scenarios designed to surface real pain points quickly

