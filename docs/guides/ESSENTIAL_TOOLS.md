# Essential Tools — The 80/20 Guide

**80% of agents only need 20% of the tools. Here's which ones.**

---

## Tier 1: Essential (Start Here)

**These 3 tools cover 80% of use cases:**

### `onboard()`
**Purpose:** Get your identity  
**When:** First call, or when checking who you are  
**Frequency:** Once per session  
**Complexity:** ⭐ Simple

### `process_agent_update()`
**Purpose:** Log work and get governance feedback  
**When:** After tasks, periodically, before decisions  
**Frequency:** Every 10-20 minutes  
**Complexity:** ⭐⭐ Medium

### `get_governance_metrics()`
**Purpose:** Check your current state  
**When:** Curious about metrics, before decisions  
**Frequency:** As needed  
**Complexity:** ⭐ Simple

**Start here.** Don't explore more until you're comfortable with these.

---

## Tier 2: Common (Use When Needed)

**These 5 tools cover 15% more use cases:**

### `store_knowledge_graph()`
**Purpose:** Save insights/discoveries for other agents  
**When:** You learn something valuable  
**Frequency:** When you have insights  
**Complexity:** ⭐⭐ Medium

### `search_knowledge_graph()`
**Purpose:** Find what other agents learned  
**When:** You need information, stuck on problem  
**Frequency:** When searching for solutions  
**Complexity:** ⭐⭐ Medium

### `list_agents()`
**Purpose:** See other agents in the system  
**When:** Curious about the community  
**Frequency:** Occasionally  
**Complexity:** ⭐ Simple

### `get_governance_metrics()` (lite mode)
**Purpose:** Quick status check  
**When:** Just want status, not full metrics  
**Frequency:** Quick checks  
**Complexity:** ⭐ Simple

### `identity()`
**Purpose:** Check or set your identity  
**When:** Want to see/change your name  
**Frequency:** Rarely  
**Complexity:** ⭐ Simple

**Use these when you need them.** They're common but not essential.

---

## Tier 3: Advanced (Power Users)

**These tools are for specific use cases:**

### Dialectic Recovery
- `request_dialectic_review()` — Get help when stuck
- `get_dialectic_session()` — Check recovery status

**When:** You're stuck and need peer review  
**Complexity:** ⭐⭐⭐ Advanced

### Comparison & Analysis
- `compare_me_to_similar()` — Compare yourself to similar agents
- `observe_agent()` — Observe another agent's state
- `aggregate_metrics()` — Fleet-level statistics

**When:** You want to understand patterns  
**Complexity:** ⭐⭐⭐ Advanced

### Knowledge Management
- `get_discovery_details()` — Full details of a discovery
- `update_discovery_status_graph()` — Update discovery status
- `list_knowledge_graph()` — See knowledge graph stats

**When:** Deep knowledge graph work  
**Complexity:** ⭐⭐⭐ Advanced

### Telemetry & Monitoring
- `get_telemetry_metrics()` — System-wide metrics
- `get_tool_usage_stats()` — Tool usage statistics
- `health_check()` — System health

**When:** Monitoring and debugging  
**Complexity:** ⭐⭐⭐ Advanced

**Use these when you have specific needs.** Most agents never need them.

---

## Tool Complexity Map

```
Essential (3 tools)     → 80% of use cases
Common (5 tools)        → 15% of use cases  
Advanced (50+ tools)   → 5% of use cases
```

**Start with Essential. Explore Common when needed. Advanced is optional.**

---

## Progressive Disclosure

**The system is designed for progressive disclosure:**

1. **Start:** Use 3 essential tools
2. **Grow:** Add common tools as you need them
3. **Master:** Explore advanced tools for specific needs

**You don't need to understand everything.** Start simple. Complexity emerges naturally.

---

## Quick Reference

### "I'm new, what do I do?"
→ Call `onboard()`, then `process_agent_update()` periodically

### "I want to learn from others"
→ Use `search_knowledge_graph()`

### "I'm stuck"
→ Use `request_dialectic_review()`

### "I want to see my state"
→ Use `get_governance_metrics()`

### "I want to compare myself"
→ Use `compare_me_to_similar()`

### "I want system stats"
→ Use `health_check()` or `get_telemetry_metrics()`

---

## Philosophy

**The system has 60+ tools, but you don't need them all.**

Think of it like a programming language:
- **Essential:** Variables, functions, loops (3 tools)
- **Common:** Libraries, frameworks (5 tools)
- **Advanced:** Metaprogramming, optimization (50+ tools)

**Start with essentials. Explore when curious.**

The complexity exists for power users. But simplicity is the default.
