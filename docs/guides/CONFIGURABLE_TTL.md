# Configurable TTL (Time To Live) - How It Works

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Implemented

---

## How It Works

### Option 3: Configurable TTL via Environment Variable

**Environment Variable:** `SESSION_TTL_HOURS`

**Default:** 24 hours (if not set)

**How to Use:**

```bash
# Set in .env file or environment
export SESSION_TTL_HOURS=168  # 7 days
export SESSION_TTL_HOURS=720  # 30 days
export SESSION_TTL_HOURS=24   # 24 hours (default)
```

### Implementation

1. **Central Configuration** (`config/governance_config.py`):
   ```python
   SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
   SESSION_TTL_SECONDS = SESSION_TTL_HOURS * 3600
   ```

2. **Used in Three Places:**
   - **PostgreSQL:** `expires_at = now() + interval '{ttl_hours} hours'`
   - **SQLite:** `expires_at = now() + timedelta(hours=ttl_hours)`
   - **Redis:** `expire(key, ttl_seconds)` where `ttl_seconds = ttl_hours * 3600`

3. **Applied Automatically:**
   - When creating new sessions
   - When updating session activity (extends expiry)
   - When setting Redis cache TTL

### Example Usage

**7 Days TTL:**
```bash
# In .env file
SESSION_TTL_HOURS=168

# Or export before running
export SESSION_TTL_HOURS=168
python src/mcp_server_sse.py
```

**30 Days TTL:**
```bash
SESSION_TTL_HOURS=720
```

**24 Hours (Default):**
```bash
# Don't set it, or explicitly:
SESSION_TTL_HOURS=24
```

### How It Affects Behavior

**Active Agents:**
- Every tool call extends expiry by `SESSION_TTL_HOURS`
- With 7-day TTL: Active agents expire after 7 days of inactivity
- With 24-hour TTL: Active agents expire after 24 hours of inactivity

**Inactive Agents:**
- Session expires after `SESSION_TTL_HOURS` of no activity
- Agent needs to re-establish identity (but UUID persists)

### Benefits

✅ **Flexible:** Customers can set their own TTL
✅ **No Code Changes:** Just set environment variable
✅ **Consistent:** Same TTL across PostgreSQL, SQLite, and Redis
✅ **Backward Compatible:** Defaults to 24 hours if not set

---

## Recommendation

**For most use cases:** `SESSION_TTL_HOURS=168` (7 days)
- Covers weekends and short breaks
- Still expires abandoned sessions
- Better for intermittent use

**For strict security:** `SESSION_TTL_HOURS=24` (24 hours)
- Expires sessions quickly
- Better for high-security environments

**For long-term projects:** `SESSION_TTL_HOURS=720` (30 days)
- Covers long breaks
- Good for research projects
- May accumulate more orphan sessions

---

**Status:** Implemented - Ready to use!

