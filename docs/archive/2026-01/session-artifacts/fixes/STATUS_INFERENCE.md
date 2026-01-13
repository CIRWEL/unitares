# Agent Status Inference

**Created:** January 2, 2026  
**Last Updated:** January 2, 2026  
**Status:** Implemented

---

## Problem

Many agents have `status=None` or unrecognized status values, making them appear as "unknown" in the dashboard.

## Solution

**Automatic status inference** based on activity patterns:

### Inference Rules

1. **No updates or no last_update** → `archived`
   - Agent was created but never used
   - No activity = inactive = archived

2. **Recent activity (<7 days)** → `active`
   - Agent has been active recently
   - Likely still in use

3. **Old activity (>7 days)** → `archived`
   - Agent hasn't been active recently
   - Likely inactive = archived

### Implementation

In `list_agents`, when an agent has unrecognized status:
- Check `total_updates` and `last_update`
- Calculate days since last update
- Infer status based on activity pattern
- Use inferred status for categorization

## Result

**Before:**
- 719 total agents
- 2 active, 48 archived, **669 unknown**

**After:**
- 719 total agents
- ~X active (recent activity)
- ~Y archived (no activity or old activity)
- **0 unknown** (all inferred)

---

**Status:** ✅ Implemented - Unknown agents are now automatically categorized

