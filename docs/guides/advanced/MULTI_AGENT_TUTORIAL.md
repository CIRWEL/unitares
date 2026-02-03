# Deploy Your First Multi-Agent System

**Created:** December 30, 2025  
**Last Updated:** December 30, 2025  
**Status:** Active

---

## Overview

This tutorial walks you through coordinating multiple AI agents on a single project. You'll learn how agents share discoveries, avoid duplicate work, and coordinate through the UNITARES governance system.

**Time:** 15-20 minutes  
**Prerequisites:** MCP server running, at least 2 AI agents (Cursor, Claude Desktop, ChatGPT, etc.)

---

## What You'll Build

A multi-agent system where:
- **Agent 1** explores and discovers solutions
- **Agent 2** builds on Agent 1's discoveries
- **Agent 3** reviews and validates the work
- All agents share knowledge via the knowledge graph
- The system tracks coordination and prevents duplication

---

## Step 1: Verify Your Setup (2 minutes)

### Check Server Status

```bash
# Check if server is running
curl http://127.0.0.1:8765/health

# Should return: {"status": "ok", ...}
```

### Check Available Agents

From any MCP client, call:
```python
list_agents()
```

You should see existing agents or an empty list (that's fine - we'll create new ones).

---

## Step 2: Set Up Your First Agent (3 minutes)

### Agent 1: The Explorer

**Goal:** This agent will explore the problem space and make initial discoveries.

**From your first agent (e.g., Cursor):**

```python
# Step 1: Get your identity
identity_result = identity(name="explorer_agent_20251230")
# Save client_session_id from response!

# Step 2: Log your first work
process_agent_update(
    client_session_id="agent-...",  # From identity() response
    response_text="Exploring authentication system architecture, reviewing existing patterns",
    complexity=0.6
)

# Step 3: Make a discovery and share it
store_knowledge_graph(
    client_session_id="agent-...",
    summary="Found authentication pattern: JWT tokens expire after 1 hour",
    discovery_type="insight",
    content="The system uses JWT tokens with 1-hour expiration. Tokens are refreshed automatically via refresh_token endpoint.",
    tags=["authentication", "jwt", "security"]
)
```

**What happened:**
- Agent 1 created an identity
- Logged work to the governance system
- Shared a discovery in the knowledge graph

---

## Step 3: Set Up Your Second Agent (3 minutes)

### Agent 2: The Builder

**Goal:** This agent will build on Agent 1's discoveries.

**From your second agent (e.g., Claude Desktop):**

```python
# Step 1: Get your identity
identity_result = identity(name="builder_agent_20251230")
# Save client_session_id!

# Step 2: Search for existing discoveries BEFORE starting work
discoveries = search_knowledge_graph(
    client_session_id="agent-...",
    query="authentication patterns",
    limit=5
)

# Step 3: Log that you're building on existing knowledge
process_agent_update(
    client_session_id="agent-...",
    response_text="Building authentication module based on discovered JWT pattern. Implementing token refresh logic.",
    complexity=0.7
)

# Step 4: Share your implementation discovery
store_knowledge_graph(
    client_session_id="agent-...",
    summary="Implemented token refresh: refresh_token endpoint returns new access_token",
    discovery_type="improvement",
    content="Created /api/auth/refresh endpoint that validates refresh_token and returns new access_token. Refresh tokens expire after 7 days.",
    tags=["authentication", "jwt", "implementation"],
    related_files=["src/auth/refresh.py"]
)
```

**What happened:**
- Agent 2 searched the knowledge graph BEFORE starting work
- Found Agent 1's discovery
- Built on it instead of duplicating effort
- Shared new implementation details

---

## Step 4: Set Up Your Third Agent (3 minutes)

### Agent 3: The Reviewer

**Goal:** This agent will review the work and validate it.

**From your third agent (e.g., ChatGPT with MCP):**

```python
# Step 1: Get your identity
identity_result = identity(name="reviewer_agent_20251230")
# Save client_session_id!

# Step 2: Search for all authentication-related discoveries
auth_discoveries = search_knowledge_graph(
    client_session_id="agent-...",
    query="authentication",
    limit=10
)

# Step 3: Review the discoveries
process_agent_update(
    client_session_id="agent-...",
    response_text="Reviewing authentication implementation. Found 2 discoveries: JWT pattern and refresh endpoint. Validating security best practices.",
    complexity=0.5
)

# Step 4: Share review findings
store_knowledge_graph(
    client_session_id="agent-...",
    summary="Security review: JWT implementation follows best practices",
    discovery_type="insight",
    content="Reviewed JWT implementation. Token expiration (1 hour) and refresh token expiration (7 days) align with OWASP recommendations. No security issues found.",
    tags=["authentication", "security", "review"],
    response_to={"discovery_id": "..."}  # Link to previous discoveries
)
```

**What happened:**
- Agent 3 found both previous discoveries
- Reviewed them together
- Validated the implementation
- Linked review to original discoveries

---

## Step 5: Verify Coordination (2 minutes)

### Check Agent List

```python
agents = list_agents(include_metrics=True)
```

You should see all three agents:
- `explorer_agent_20251230`
- `builder_agent_20251230`
- `reviewer_agent_20251230`

### Check Knowledge Graph

```python
all_discoveries = search_knowledge_graph(
    query="authentication",
    limit=20
)
```

You should see:
1. Explorer's pattern discovery
2. Builder's implementation discovery
3. Reviewer's security review

### Check Coordination Metrics

```python
fleet_metrics = aggregate_metrics()
```

Look for:
- Total agents: 3
- Active agents: 3
- Knowledge graph nodes: 3+ discoveries
- Cross-agent discovery sharing

---

## Step 6: See Coordination in Action (5 minutes)

### Scenario: Agent 4 Joins Late

**What happens when a new agent joins?**

```python
# Agent 4 searches BEFORE starting work
discoveries = search_knowledge_graph(
    query="authentication",
    limit=10
)

# Agent 4 finds all previous work!
# Instead of starting from scratch, Agent 4 can:
# 1. Build on existing discoveries
# 2. Fill gaps
# 3. Improve implementations
```

**This is the power of multi-agent coordination:**
- Agents don't duplicate work
- Knowledge accumulates
- Each agent builds on previous discoveries

---

## Real-World Patterns

### Pattern 1: Exploration → Implementation → Review

**Common workflow:**
1. **Explorer** discovers patterns
2. **Builder** implements based on discoveries
3. **Reviewer** validates and improves

**Example:**
```python
# Explorer
store_knowledge_graph(
    summary="Database connection pooling pattern",
    discovery_type="pattern",
    tags=["database", "performance"]
)

# Builder (searches first!)
search_knowledge_graph(query="database connection")
store_knowledge_graph(
    summary="Implemented connection pool with 10 max connections",
    discovery_type="improvement",
    tags=["database", "implementation"]
)

# Reviewer
search_knowledge_graph(query="database")
store_knowledge_graph(
    summary="Validated: Connection pool prevents connection exhaustion",
    discovery_type="insight",
    tags=["database", "review"]
)
```

### Pattern 2: Parallel Work with Coordination

**Multiple agents work in parallel, sharing discoveries:**

```python
# Agent A: Working on frontend
store_knowledge_graph(
    summary="Frontend: React component structure",
    tags=["frontend", "react"]
)

# Agent B: Working on backend (searches first!)
search_knowledge_graph(query="frontend")
store_knowledge_graph(
    summary="Backend API matches frontend component structure",
    discovery_type="improvement",
    tags=["backend", "api", "coordination"]
)
```

### Pattern 3: Problem → Solution → Validation

**Agents collaborate to solve problems:**

```python
# Agent 1: Identifies problem
store_knowledge_graph(
    summary="Problem: API rate limiting causing errors",
    discovery_type="bug_found",
    tags=["api", "rate-limiting"]
)

# Agent 2: Finds solution
search_knowledge_graph(query="rate limiting")
store_knowledge_graph(
    summary="Solution: Implement exponential backoff",
    discovery_type="improvement",
    tags=["api", "rate-limiting", "solution"]
)

# Agent 3: Validates solution
search_knowledge_graph(query="rate limiting solution")
store_knowledge_graph(
    summary="Validation: Exponential backoff reduces errors by 90%",
    discovery_type="insight",
    tags=["api", "validation"]
)
```

---

## Best Practices

### 1. Always Search Before Starting

**Before starting new work, search the knowledge graph:**
```python
existing = search_knowledge_graph(
    query="your topic",
    limit=10
)
```

**Why:** Avoids duplication, builds on existing knowledge.

### 2. Use Descriptive Tags

**Tags help agents find related work:**
```python
tags=["authentication", "security", "jwt"]  # Good
tags=["stuff", "things"]  # Bad - too generic
```

### 3. Link Related Discoveries

**Use `response_to` to create knowledge chains:**
```python
store_knowledge_graph(
    summary="Review of previous discovery",
    response_to={"discovery_id": "abc123"}
)
```

### 4. Share Early, Share Often

**Don't wait until completion - share discoveries as you find them:**
```python
# Share pattern discovery
store_knowledge_graph(discovery_type="pattern", ...)

# Share implementation
store_knowledge_graph(discovery_type="improvement", ...)

# Share validation
store_knowledge_graph(discovery_type="insight", ...)
```

### 5. Monitor Fleet Health

**Check how agents are coordinating:**
```python
# See all agents
agents = list_agents()

# Check coordination metrics
metrics = aggregate_metrics()

# Detect anomalies
anomalies = detect_anomalies()
```

---

## Troubleshooting

### Agents Can't Find Each Other's Discoveries

**Problem:** `search_knowledge_graph` returns empty results.

**Solutions:**
1. Check tags match: Use consistent tag naming
2. Try broader queries: "authentication" instead of "JWT token refresh endpoint"
3. Check discovery types: Some searches filter by type
4. Verify discoveries were stored: Check `list_knowledge_graph()`

### Agents Creating Duplicate Work

**Problem:** Multiple agents working on the same thing.

**Solution:** Always search BEFORE starting work:
```python
# Always do this first!
existing = search_knowledge_graph(query="your topic")
if existing['discoveries']:
    # Build on existing work instead
    pass
```

### Coordination Not Visible

**Problem:** Can't see how agents are coordinating.

**Solution:** Use aggregate metrics:
```python
# See fleet-wide coordination
metrics = aggregate_metrics()

# Compare agents
comparison = compare_agents(["agent1", "agent2", "agent3"])

# Detect patterns
patterns = observe_agent("agent1", analyze_patterns=True)
```

---

## Next Steps

### Explore Advanced Features

1. **Dialectic Protocol:** Agents review each other when paused
   ```python
   request_dialectic_review(
       agent_id="paused_agent",
       reason="Need peer review"
   )
   ```

2. **Agent Comparison:** See how agents differ
   ```python
   compare_agents(["agent1", "agent2"])
   ```

3. **Anomaly Detection:** Find unusual patterns
   ```python
   anomalies = detect_anomalies()
   ```

4. **Knowledge Graph Visualization:** See discovery relationships
   ```python
   # Use get_discovery_details to see connections
   details = get_discovery_details(discovery_id="...")
   ```

### Scale Up

- **10+ agents:** Use `aggregate_metrics()` to monitor fleet health
- **100+ agents:** Use `detect_anomalies()` to find coordination issues
- **Knowledge graph:** Use semantic search to find related discoveries

---

## Summary

**You've learned:**
1. ✅ How to set up multiple agents
2. ✅ How agents share discoveries via knowledge graph
3. ✅ How agents coordinate to avoid duplication
4. ✅ How to verify coordination is working
5. ✅ Real-world coordination patterns

**Key takeaway:** Multi-agent coordination happens through the shared knowledge graph. Agents search before starting work, share discoveries as they find them, and build on each other's knowledge.

---

## Additional Resources

- **Dashboard:** http://127.0.0.1:8765/dashboard - See coordination in real-time
- **Full Documentation:** [README.md](../../README.md)
- **Agent Guide:** [AI_ASSISTANT_GUIDE.md](../reference/AI_ASSISTANT_GUIDE.md)
- **Troubleshooting:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**Status:** Tutorial Complete - Ready for customer use

