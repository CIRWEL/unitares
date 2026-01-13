# SEE ALSO Sections Investigation

**Created:** January 1, 2026  
**Status:** Investigating why SEE ALSO sections aren't appearing in responses

---

## Findings

**Code verification:**
- ✅ SEE ALSO sections ARE in `tool_schemas.py` (21 tools)
- ✅ ALTERNATIVES sections ARE in `tool_schemas.py` (21 tools)
- ✅ Full descriptions include SEE ALSO when `verbosity="full"`

**Response verification:**
- ❌ SEE ALSO sections NOT appearing in `describe_tool()` responses
- ❌ Response descriptions are shorter (2706 vs 3275 chars)
- ❌ Missing ~569 characters (roughly SEE ALSO + ALTERNATIVES length)

---

## Analysis

**Description lengths:**
- Code: 3275 characters (includes SEE ALSO/ALTERNATIVES)
- Response: 2706 characters (missing SEE ALSO/ALTERNATIVES)

**Section positions in code:**
- SEE ALSO: index 736
- ALTERNATIVES: index 1010
- USE CASES: index 1305

**Section positions in response:**
- USE CASES: index 736 (shifted forward by ~569 chars)
- This suggests SEE ALSO/ALTERNATIVES are being stripped

---

## Possible Causes

1. **Server cache** - Server may be using cached/old code
2. **Description processing** - Something filtering SEE ALSO sections
3. **Code path** - Different code path being used
4. **Restart needed** - Changes not loaded yet

---

## Next Steps

1. Verify server restart loaded latest code
2. Check if there's any description filtering
3. Test with fresh server restart
4. Verify tool_schemas.py changes are active

---

**Status:** Investigating  
**Action:** Verify server is using latest code

