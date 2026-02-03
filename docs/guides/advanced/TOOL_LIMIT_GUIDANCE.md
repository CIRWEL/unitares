# MCP Tool Limit Guidance

**Created:** December 30, 2025  
**Last Updated:** December 30, 2025  
**Status:** Active

---

## Current Status

**Total Tools:** 51

**Alert:** "Exceeding total tools limit on MCP servers"

## Research Findings

### Tool Limit Recommendations

- **General threshold:** ~40 tools (some models struggle beyond this)
- **Smaller models:** 12-16 tools
- **Issue:** Not just context window size, but LLMs getting confused with:
  - Too many tool names to remember
  - Tool definitions mixing up
  - Hallucinating non-existent tools
  - Failing to follow instructions correctly

### Impact

- **Performance:** Degraded performance and increased latency
- **Accuracy:** Models may hallucinate tools or mix up names
- **Cost:** Larger context usage = higher costs

## Our Situation

**51 tools** - Above recommended threshold but:
- ✅ **Server is working** - No immediate issues reported
- ✅ **Well-organized** - Tools are logically grouped (governance, knowledge graph, lifecycle, etc.)
- ✅ **Good descriptions** - Tools have clear "SEE ALSO" and "ALTERNATIVES" sections
- ✅ **Specialized domain** - Governance/coordination server naturally needs many tools

## Recommendation

### Option 1: Monitor and Ignore (Recommended for Now)

**If it's working, ignore the alert** but monitor for:
- Agents hallucinating tools
- Agents mixing up tool names
- Performance degradation
- Increased errors

**Rationale:** 
- The server is functioning correctly
- 51 tools is manageable for modern LLMs (GPT-4, Claude 3.5)
- The alert may be conservative
- Breaking changes aren't worth it if there are no issues

### Option 2: Tool Grouping/Namespacing (If Issues Arise)

If problems occur, consider:
- **Tool aliases** - Group related tools (already implemented)
- **Tool categories** - Add category metadata
- **Conditional exposure** - Only expose relevant tools per agent type
- **Tool consolidation** - Merge similar tools (risky, may break existing workflows)

### Option 3: Split into Multiple Servers (Future)

If we grow significantly:
- **Core governance server** - Essential tools (~20-30)
- **Extended features server** - Advanced tools (~20-30)
- Agents connect to both as needed

## Monitoring Checklist

Watch for these signs of tool overload:
- [ ] Agents calling non-existent tools
- [ ] Agents mixing up tool names (e.g., `get_governance_metrics` vs `get_telemetry_metrics`)
- [ ] Increased "tool not found" errors
- [ ] Agents asking for tool lists repeatedly
- [ ] Slower tool selection/decision making
- [ ] Higher token usage (from tool descriptions)

## Action Items

**Current:** ✅ **Ignore the alert** - Monitor for issues

**If issues arise:**
1. Document specific problems
2. Identify which tools are being confused
3. Consider tool grouping/consolidation
4. Evaluate splitting into multiple servers

---

**Status:** Alert acknowledged, monitoring recommended, no action needed if working correctly.

