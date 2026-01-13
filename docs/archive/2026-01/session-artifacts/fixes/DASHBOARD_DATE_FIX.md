# Dashboard Date Parsing Fix

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Fixed

---

## Issue

Dashboard was parsing dates incorrectly. It's January 2026, so discoveries from December 29, 2025 are actually recent (3 days ago), not old.

## Root Cause

Date parsing from ISO timestamp IDs wasn't handling the format correctly. JavaScript's `Date()` constructor can be inconsistent with ISO strings without timezone.

## Fix

Updated date parsing to:
1. Explicitly parse ISO timestamp components (year, month, day, hour, minute, second)
2. Create Date object using `new Date(year, month-1, day, hour, minute, second)`
3. Show relative time:
   - "Just now" / "X minutes ago" for very recent
   - "X hours ago" for today
   - "Yesterday" for 1 day ago
   - "X days ago" for < 7 days
   - Full date/time for older

## Example

**Before:** "12/29/2025, 8:34:42 AM" (looks old)

**After:** "3 days ago" (correctly shows it's recent)

---

**Status:** Fixed - Dates now parse correctly and show relative time

