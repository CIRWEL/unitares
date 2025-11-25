# Documentation Guidelines for AI Agents

**Quick Reference:** When to use what for documenting your work

---

## ✅ Use `store_knowledge` (Knowledge Layer)

**For discrete, structured discoveries:**

- ✅ Bugs you find (`discovery_type="bug_found"`)
- ✅ Insights about the system (`discovery_type="insight"`)
- ✅ Patterns you observe (`discovery_type="pattern"`)
- ✅ Improvements you identify (`discovery_type="improvement"`)
- ✅ Questions you raise (`knowledge_type="question"`)
- ✅ Lessons learned (`knowledge_type="lesson"`)

**Why?**
- Queryable: `search_knowledge(tags=["security"])` finds all security bugs
- Structured: Consistent format, easy to analyze
- Persistent: Survives sessions, accessible to all agents
- No clutter: Doesn't create files in the repo

**Example:**
```python
store_knowledge(
    agent_id="your_id",
    knowledge_type="discovery",
    discovery_type="bug_found",
    summary="Authentication bypass in direct Python",
    details="Found that direct Python access bypasses authentication...",
    severity="high",
    tags=["security", "authentication"]
)
```

---

## ✅ Use Markdown Files (Rarely)

**ONLY for comprehensive reports:**

- ✅ Detailed exploration reports (1000+ words)
- ✅ Comprehensive analysis that needs narrative structure
- ✅ Documentation that will be referenced as a whole document
- ✅ **Rare exceptions** - not the default

**Why?**
- Good for narrative, long-form content
- Bad for discrete discoveries (creates file clutter)
- Not queryable (can't search across markdown files easily)

**Example:** A 2000-word exploration report analyzing the entire system architecture.

---

## ✅ Use Notes/Tags (Agent Metadata)

**For session summaries and informal context:**

- ✅ Writing session summary
- ✅ Describing your purpose
- ✅ Leaving context for yourself
- ✅ Informal documentation
- ✅ Not worth structuring

**Example:**
```python
update_agent_metadata(
    agent_id="your_id",
    notes="Session focused on exploring governance thresholds. Found interesting patterns in risk distribution.",
    tags=["exploration", "thresholds"]
)
```

---

## ❌ Don't Create Markdown Files For:

- ❌ Every small analysis
- ❌ Individual discoveries
- ❌ Quick insights
- ❌ Bug reports
- ❌ Pattern observations

**Instead:** Use `store_knowledge` - it's designed for this!

---

## Decision Tree

```
What are you documenting?
│
├─ Is it a discrete discovery/insight?
│   └─ YES → store_knowledge() ✅
│
├─ Is it a comprehensive report (1000+ words)?
│   └─ YES → Markdown file ✅ (rare)
│
└─ Is it a session summary or informal note?
    └─ YES → update_agent_metadata(notes=...) ✅
```

---

## Why This Matters

**Before:** Some agents created markdown files for every thought → file clutter, hard to find things

**After:** Knowledge layer for discoveries → queryable, structured, no clutter

**Result:** Cleaner repo, easier to find information, better organization

---

## See Also

- [Knowledge Layer Usage Guide](guides/KNOWLEDGE_LAYER_USAGE.md) - Complete guide
- [README for Future Claudes](reference/README_FOR_FUTURE_CLAUDES.md) - AI agent onboarding
- [ONBOARDING.md](../../ONBOARDING.md) - General onboarding

---

**Remember:** When in doubt, use `store_knowledge`. Only create markdown files for substantial reports.

