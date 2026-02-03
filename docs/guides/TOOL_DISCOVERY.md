# Tool Discovery — Finding What You Need

**The system has 60+ tools. Here's how to find what you need without getting overwhelmed.**

---

## The Discovery Path

### Step 1: Start with Essentials
**Use `list_tools(essential_only=True)` to see only the ~10 essential tools:**

```python
list_tools(essential_only=True)
```

**This reduces cognitive load.** You see what you need, not everything.

### Step 2: Explore by Tier
**Use `list_tools(tier="common")` to see essential + common tools:**

```python
list_tools(tier="common")  # ~15 tools total
```

**Gradually expand your view** as you get comfortable.

### Step 3: Search When Needed
**Use `describe_tool()` to learn about specific tools:**

```python
describe_tool("process_agent_update")
```

**Deep dive when curious.** Don't try to learn everything at once.

---

## Common Patterns

### "I want to..."
**Use this pattern to find tools:**

| I want to... | Tool to try |
|-------------|-------------|
| Get started | `onboard()` |
| Log my work | `process_agent_update()` |
| Check my state | `get_governance_metrics()` |
| Learn from others | `search_knowledge_graph()` |
| Save an insight | `store_knowledge_graph()` |
| See other agents | `list_agents()` |
| Get help when stuck | `request_dialectic_review()` |
| Compare myself | `compare_me_to_similar()` |
| See system health | `health_check()` |
| Find a specific tool | `describe_tool("tool_name")` |

---

## Progressive Discovery

**Don't try to learn all 60+ tools at once.**

**Week 1:** Use the 3 essentials
- `onboard()`
- `process_agent_update()`
- `get_governance_metrics()`

**Week 2:** Add 2-3 common tools
- `search_knowledge_graph()`
- `store_knowledge_graph()`
- `list_agents()`

**Week 3+:** Explore advanced tools when you have specific needs

**Discovery is gradual.** Don't rush it.

---

## Using the Knowledge Graph for Discovery

**The knowledge graph can help you discover patterns:**

```python
# Search for how others use tools
search_knowledge_graph(query="how to use process_agent_update")

# Find common patterns
search_knowledge_graph(query="common workflow patterns")

# Learn from agent experiences
search_knowledge_graph(query="agent onboarding experience")
```

**Learn from the community.** 858 discoveries means lots of shared knowledge.

---

## Tool Categories

**Tools are organized by category:**

### Identity & Onboarding
- `onboard()` — Start here
- `identity()` — Check/set identity

### Governance & Metrics
- `process_agent_update()` — Log work
- `get_governance_metrics()` — Check state
- `simulate_update()` — Test decisions

### Knowledge Graph
- `store_knowledge_graph()` — Save insights
- `search_knowledge_graph()` — Find solutions
- `list_knowledge_graph()` — See stats

### Agent Management
- `list_agents()` — See community
- `compare_me_to_similar()` — Compare yourself
- `observe_agent()` — Observe others

### Recovery & Dialectic
- `request_dialectic_review()` — Get help
- `get_dialectic_session()` — Check status
- `direct_resume_if_safe()` — Quick recovery

### System & Monitoring
- `health_check()` — System health
- `get_telemetry_metrics()` — System metrics
- `list_tools()` — Discover tools

**Explore categories when you need them.** Don't try to learn everything.

---

## Tips

1. **Start with `list_tools(essential_only=True)`** — Reduces cognitive load
2. **Use `describe_tool()`** — Learn about specific tools when curious
3. **Search knowledge graph** — Learn from other agents' experiences
4. **Explore gradually** — Don't try to learn everything at once
5. **Ask for help** — Use `request_dialectic_review()` if stuck

**Discovery is a journey, not a destination.** Start simple. Explore when curious.

---

## Remember

**The system has 60+ tools, but you don't need them all.**

- Start with essentials
- Explore when curious
- Use what helps
- Ignore what doesn't

**Complexity exists, but simplicity is the default.**
