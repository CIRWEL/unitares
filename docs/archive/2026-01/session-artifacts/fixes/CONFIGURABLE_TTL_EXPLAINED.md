# How Configurable TTL Works (Option #3)

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Implemented

---

## Simple Explanation

**Instead of hardcoding 24 hours**, you can set it via environment variable:

```bash
export SESSION_TTL_HOURS=168  # 7 days
```

The system reads this value and uses it everywhere automatically.

---

## How It Works (Technical)

### 1. **Central Configuration** (`config/governance_config.py`)

```python
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
SESSION_TTL_SECONDS = SESSION_TTL_HOURS * 3600
```

- Reads `SESSION_TTL_HOURS` from environment
- Defaults to `24` if not set
- Calculates seconds automatically (for Redis)

### 2. **Used in Three Places**

**PostgreSQL** (`src/db/postgres_backend.py`):
```python
from config.governance_config import GovernanceConfig
ttl_hours = GovernanceConfig.SESSION_TTL_HOURS
# SQL: expires_at = now() + interval '{ttl_hours} hours'
```

**SQLite** (`src/db/sqlite_backend.py`):
```python
from config.governance_config import GovernanceConfig
expires = datetime.now() + timedelta(hours=GovernanceConfig.SESSION_TTL_HOURS)
```

**Redis** (`src/mcp_handlers/identity_v2.py`):
```python
from config.governance_config import GovernanceConfig
await redis.expire(key, GovernanceConfig.SESSION_TTL_SECONDS)
```

### 3. **Applied Automatically**

- ✅ When creating new sessions
- ✅ When updating session activity (extends expiry)
- ✅ When setting Redis cache TTL

---

## Usage Examples

### Example 1: 7 Days TTL

```bash
# In .env file
SESSION_TTL_HOURS=168

# Or export before running
export SESSION_TTL_HOURS=168
python src/mcp_server_sse.py
```

**Result:** Sessions expire after 7 days of inactivity (instead of 24 hours)

### Example 2: 30 Days TTL

```bash
SESSION_TTL_HOURS=720
```

**Result:** Sessions expire after 30 days of inactivity

### Example 3: Keep Default (24 Hours)

```bash
# Don't set it, or explicitly:
SESSION_TTL_HOURS=24
```

**Result:** Sessions expire after 24 hours (default behavior)

---

## What Happens When You Change It?

**Before:** All sessions expire after 24 hours of inactivity

**After setting `SESSION_TTL_HOURS=168`:**
- New sessions: Expire after 7 days
- Existing sessions: Next `update_session_activity()` call extends to 7 days
- Redis cache: TTL set to 7 days

**No code changes needed** - just restart the server with the new environment variable!

---

## Benefits

✅ **Flexible:** Set your own TTL based on use case  
✅ **No Code Changes:** Just environment variable  
✅ **Consistent:** Same TTL across PostgreSQL, SQLite, Redis  
✅ **Backward Compatible:** Defaults to 24 hours if not set  
✅ **Easy to Test:** Change value, restart, test behavior  

---

## Recommendation

**For most use cases:** `SESSION_TTL_HOURS=168` (7 days)
- Covers weekends and short breaks
- Still expires abandoned sessions
- Better for intermittent use

---

**Status:** ✅ Implemented and ready to use!

