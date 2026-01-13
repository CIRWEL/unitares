# Metrics Display Fix

**Created:** January 2, 2026  
**Last Updated:** January 2, 2026  
**Status:** Fixed

---

## Issue

Dashboard showed "No metrics yet" for agents that should have metrics.

## Root Cause

In `list_agents`, when `include_metrics=true`:
- **If monitor in memory:** Metrics were populated ✅
- **If monitor NOT in memory:** Metrics were set to `None` ❌

The code loaded the monitor to calculate health status, but didn't populate metrics from it.

## Fix

Updated `src/mcp_handlers/lifecycle.py` (line 249-276):
- Now loads monitor even if not in memory
- Populates metrics from monitor state
- Falls back gracefully if monitor can't be loaded

## Result

**Before:**
- Only agents with monitors in memory showed metrics
- Other agents showed "No metrics yet"

**After:**
- All agents with at least one `process_agent_update()` call show metrics
- Agents with 0 updates still show "No metrics yet" (expected - they haven't generated metrics yet)

## Dashboard Display

Dashboard now shows all 5 metrics:
- **E** - Energy
- **I** - Information Integrity  
- **S** - Entropy
- **V** - Void Integral
- **C** - Coherence

---

**Status:** ✅ Fixed - Metrics now load for all agents with monitor state

