# Agent/User Probing Session

**Date:** December 29, 2025  
**Agent:** Composer (testing as user)  
**Purpose:** Probe system for friction points, edge cases, and UX issues

---

## Workflow Testing

### 1. ✅ Onboarding Flow
**Test:** Called `onboard()`

**Result:**
- Found existing identity (good continuity)
- Provided helpful `next_calls` guidance
- Clear session continuity instructions
- Suggests naming yourself

**UX:** ⭐⭐⭐⭐⭐ Excellent - very helpful for new agents

**Finding:** `client_session_id` is provided but agents need to remember to include it in future calls. Could be auto-injected?

---

### 2. ✅ Tool Discovery
**Test:** `list_tools(essential_only=true, lite=true)`

**Result:**
- Clean, organized categories
- Helpful workflows section
- Good signatures showing parameter patterns
- Emojis make scanning easier

**UX:** ⭐⭐⭐⭐⭐ Excellent organization

**Finding:** `lite` parameter accepts string `"true"` but should be boolean. Got error: "Parameter 'lite' must be one of types [boolean, null], got string"

---

### 3. ✅ Tool Documentation
**Test:** `describe_tool("store_knowledge_graph", lite=false)`

**Result:**
- Comprehensive documentation
- Clear examples
- Enum values listed
- Aliases documented

**UX:** ⭐⭐⭐⭐⭐ Very helpful

**Finding:** Description mentions aliases (bug→bug_found, ux_feedback→improvement) but doesn't list ALL aliases. Could be more explicit.

---

### 4. ✅ Governance Metrics
**Test:** `get_governance_metrics(include_state=false)`

**Result:**
- Clear status indicators (🟡 moderate)
- Helpful metrics (E, I, S, V)
- Actionable guidance ("Coherence drifting. Focus on your current task")
- Lite mode reduces verbosity

**UX:** ⭐⭐⭐⭐ Very good

**Finding:** Auto-registration working perfectly - no friction!

---

### 5. ✅ Simulate Update
**Test:** `simulate_update(complexity=0.7, confidence=0.85, response_text="...")`

**Result:**
- Very comprehensive output
- Decision tree, metrics, guidance, restorative info
- Helpful but verbose

**UX:** ⭐⭐⭐⭐ Good, but could use `lite` mode

**Finding:** Returns a LOT of data. Could benefit from `lite=true` option like other tools.

---

### 6. ✅ List Agents
**Test:** `list_agents(limit=5, include_metrics=false)`

**Result:**
- Clean list
- Good filtering
- Summary stats helpful

**UX:** ⭐⭐⭐⭐ Good

**Finding:** When `lite` provided as string `"true"`, got type error. Should coerce strings to booleans.

---

### 7. ⚠️ Knowledge Graph Operations
**Test:** `store_knowledge_graph()` and `leave_note()`

**Issues Found:**
- Parameter validation errors unclear
- Need to provide `summary` but error messages could be clearer
- Testing `ux_feedback` alias...

**Status:** Testing in progress

---

## Edge Cases & Friction Points Found

### 1. 🔴 Boolean Parameter Coercion
**Issue:** `lite="true"` (string) fails, expects boolean

**Impact:** Agents using string booleans get errors

**Recommendation:** Coerce string booleans ("true"/"false") → boolean

**Priority:** Medium

---

### 2. 🟡 Parameter Error Messages
**Issue:** `store_knowledge_graph()` and `leave_note()` errors still not super clear

**Status:** We fixed `leave_note` schema, but testing shows errors could be clearer

**Priority:** Low (already improved)

---

### 3. 🟢 Search Fallback Explanation
**Issue:** Fallback used but doesn't explain WHY original query failed

**Example:**
```
"fallback_message": "Original query 'ux_feedback alias' returned 0 results. Retried with individual terms..."
```

**Better:** "No exact phrase matches found. Searching individual terms: ux_feedback, alias"

**Priority:** Low

---

### 4. 🟡 Simulate Update Verbosity
**Issue:** Returns very comprehensive data (good!) but might be overwhelming

**Recommendation:** Add `lite=true` option

**Priority:** Low

---

### 5. 🟢 Client Session ID Memory
**Issue:** `onboard()` provides `client_session_id` but agents need to remember to include it

**Recommendation:** Auto-inject if available in context

**Priority:** Low (minor convenience)

---

## Positive Observations ✅

1. **Onboarding flow** - Excellent guidance and next steps
2. **Tool discovery** - Well organized, helpful workflows
3. **Auto-registration** - Works seamlessly, no friction
4. **Error recovery** - Helpful workflows and guidance
5. **Documentation** - Comprehensive tool descriptions

---

## Testing Checklist

- [x] Onboarding flow
- [x] Tool discovery
- [x] Tool documentation
- [x] Governance metrics
- [x] Simulate update
- [x] List agents
- [x] Health check
- [x] System history
- [x] Knowledge graph search
- [ ] Knowledge graph write operations (parameter issues)
- [ ] Error handling edge cases
- [ ] Parameter validation edge cases

## Summary of Findings

### Critical Issues Found
1. **Boolean Parameter Coercion** - String booleans fail validation

### Minor Friction Points
1. Parameter error messages could be clearer (partially fixed)
2. Search fallback explanation could be better
3. Simulate update very verbose (could use lite mode)
4. Client session ID needs manual inclusion

### Excellent UX
1. Onboarding flow - very helpful
2. Tool discovery - well organized
3. Auto-registration - seamless
4. Documentation - comprehensive

---

## Recommendations

### High Priority
1. **Boolean coercion** - Coerce string booleans ("true"/"false") → boolean

### Medium Priority
2. **Simulate update lite mode** - Add `lite=true` option for less verbose output

### Low Priority
3. **Search fallback explanation** - Clarify why fallback was needed
4. **Client session ID** - Auto-inject if available

---

**Status:** Probing in progress. Found several minor friction points, overall UX is excellent!

