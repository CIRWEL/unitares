# TTL (Time To Live) Analysis - 24 Hours

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Analysis

---

## Current TTL Settings

**24 hours** (86400 seconds) for:
- Redis session cache
- PostgreSQL session expiry
- SQLite session expiry

## How It Works

### Active Agents (NOT Expired)
- **Every tool call** → `update_session_activity()` extends expiry by 24 hours
- **Result:** Active agents never expire (as long as they're being used)
- **Code:** `expires_at = now() + interval '24 hours'` on every call

### Inactive Agents (Expired)
- **After 24 hours** of no activity → Session expires
- **Cleanup:** Expired sessions are cleaned up automatically
- **Impact:** Agent needs to re-establish identity (but UUID persists)

## Is 24 Hours Too Strict?

### Arguments FOR 24 Hours (Current)
- ✅ **Active agents never expire** (activity extends TTL)
- ✅ **Prevents orphan sessions** from accumulating
- ✅ **Reasonable for daily use** (if you use it daily, it never expires)
- ✅ **Security:** Expires abandoned sessions quickly

### Arguments AGAINST 24 Hours (Too Strict)
- ❌ **Weekend breaks** → Agent expires if not used Saturday/Sunday
- ❌ **Holiday breaks** → Agent expires during vacations
- ❌ **Intermittent use** → Agent expires between sessions
- ❌ **Multi-day projects** → Agent might expire mid-project

## Recommendations

### Option 1: Extend to 7 Days (Recommended)
**Pros:**
- Covers weekends and short breaks
- Still expires abandoned sessions
- Better for intermittent use

**Cons:**
- Longer cleanup time for orphans

### Option 2: Activity-Based Extension
**Current:** 24h from last activity
**Proposed:** 7 days from last activity, but extend to 30 days if agent has recent `process_agent_update` calls

### Option 3: Configurable TTL
**Allow customers to set:** `SESSION_TTL_HOURS` environment variable
- Default: 24 hours
- Can set to 168 (7 days) or 720 (30 days)

## Current Behavior Summary

**Active agents:** Never expire (activity extends TTL)
**Inactive agents:** Expire after 24 hours of no activity

**Question:** Is 24 hours too strict for inactive agents?

---

**Status:** Analysis complete - Recommend extending to 7 days for better UX

