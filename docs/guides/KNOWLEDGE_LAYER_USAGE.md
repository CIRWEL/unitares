# Knowledge Layer Usage Guide

**For AI Agents Using the Governance System**

---

## Quick Start

The knowledge layer lets you store structured learning beyond thermodynamic metrics. Use it to:
- Track bugs you find
- Record insights you gain
- Log patterns you observe
- Remember lessons learned
- Raise questions for future exploration

---

## Available Tools

### 1. store_knowledge

Store any type of knowledge (discovery, pattern, lesson, or question).

**Example - Store a Bug:**
```json
{
  "agent_id": "your_agent_id",
  "knowledge_type": "discovery",
  "discovery_type": "bug_found",
  "summary": "Authentication bypass in direct Python",
  "details": "Found that direct Python access bypasses authentication...",
  "severity": "high",
  "tags": ["security", "authentication"],
  "related_files": ["src/mcp_server_std.py"]
}
```

**Example - Store a Lesson:**
```json
{
  "agent_id": "your_agent_id",
  "knowledge_type": "lesson",
  "lesson": "Confidence gating prevents dangerous adaptation when uncertain"
}
```

**Example - Store a Pattern:**
```json
{
  "agent_id": "your_agent_id",
  "knowledge_type": "pattern",
  "pattern_id": "coherence_exploration_drop",
  "description": "Coherence consistently drops when agents explore new features",
  "severity": "medium",
  "tags": ["coherence", "exploration"],
  "examples": ["Update 5: coherence 0.65→0.58"]
}
```

**Example - Store a Question:**
```json
{
  "agent_id": "your_agent_id",
  "knowledge_type": "question",
  "question": "Should agents be able to configure their own governance thresholds?"
}
```

### 2. retrieve_knowledge

Get your complete knowledge record.

**Example:**
```json
{
  "agent_id": "your_agent_id"
}
```

**Returns:** All your discoveries, patterns, lessons, and questions.

### 3. search_knowledge

Search knowledge across agents (including yourself).

**Example - Find All Security Bugs:**
```json
{
  "discovery_type": "bug_found",
  "tags": ["security"],
  "severity": "high"
}
```

**Example - Find All Insights:**
```json
{
  "discovery_type": "insight"
}
```

**Example - Find Your Own Discoveries:**
```json
{
  "agent_id": "your_agent_id"
}
```

### 4. list_knowledge

Get summary statistics across all agents.

**Example:**
```json
{}
```

**Returns:** Total counts of discoveries, patterns, lessons, questions across all agents.

---

## When to Use Knowledge Layer vs Markdown Files

### Use Knowledge Layer When:
- ✅ You find a bug or vulnerability
- ✅ You have a significant insight about the system
- ✅ You observe a recurring pattern (2+ times)
- ✅ You learn something others should know
- ✅ You raise an important question
- ✅ You want it queryable (find all security bugs)
- ✅ **Most discoveries and insights** (preferred method)

### Use Markdown Files When:
- ✅ Writing a comprehensive exploration report (1000+ words)
- ✅ Detailed analysis that needs narrative structure
- ✅ Documentation that will be referenced as a whole document
- ✅ **Rarely** - only for substantial reports

### Use Notes/Tags When:
- ✅ Writing session summary
- ✅ Describing your purpose
- ✅ Leaving context for yourself
- ✅ Informal documentation
- ✅ Not worth structuring

**Guideline:** Prefer knowledge layer for discrete discoveries. Use markdown files sparingly for comprehensive reports only. Avoid creating markdown files for every small analysis or thought.

---

## Decision Tree

```
Is it a discrete event?
├─ Yes → Is it recurring (2+ times)?
│   ├─ Yes → store_knowledge(knowledge_type="pattern")
│   └─ No → store_knowledge(knowledge_type="discovery")
│       ├─ Bug? → discovery_type="bug_found"
│       ├─ Insight? → discovery_type="insight"
│       ├─ Improvement? → discovery_type="improvement"
│       ├─ First pattern observation? → discovery_type="pattern"
│       └─ Complex question? → discovery_type="question"
│
└─ No → Is it a lesson?
    ├─ Yes → store_knowledge(knowledge_type="lesson")
    └─ No → Is it a simple question?
        ├─ Yes → store_knowledge(knowledge_type="question")
        └─ No → Use notes/tags instead
```

---

## Examples

### Example 1: Log a Bug You Found

```python
# Via MCP tool
store_knowledge(
    agent_id="your_agent_id",
    knowledge_type="discovery",
    discovery_type="bug_found",
    summary="Lambda1 updates not gated by confidence",
    details="Found that lambda1 updates proceed even when confidence < 0.8...",
    severity="high",
    tags=["governance", "confidence-gating"],
    related_files=["src/governance_monitor.py"]
)
```

### Example 2: Record a Lesson

```python
store_knowledge(
    agent_id="your_agent_id",
    knowledge_type="lesson",
    lesson="Minimal integration proves value before deeper integration"
)
```

### Example 3: Search for Security Bugs

```python
# Find all security bugs across all agents
search_knowledge(
    discovery_type="bug_found",
    tags=["security"],
    severity="high"
)
```

### Example 4: Get Your Knowledge

```python
# Retrieve your complete knowledge record
retrieve_knowledge(agent_id="your_agent_id")
```

---

## Tips

1. **Be Selective** - Only log significant discoveries/lessons
2. **Use Tags** - Tags enable powerful cross-agent queries
3. **Set Severity** - Helps prioritize important discoveries
4. **Link Files** - `related_files` helps future agents find context
5. **Query First** - Before logging, search to see if others found similar things

---

## Cross-Agent Learning

The knowledge layer enables cross-agent learning:

- **Find all security bugs:** `search_knowledge(tags=["security"], discovery_type="bug_found")`
- **Learn from others:** `search_knowledge(discovery_type="insight")`
- **See common patterns:** `list_knowledge()` shows aggregate statistics

---

**Status:** Tools are ready. Start using them and see what works!

