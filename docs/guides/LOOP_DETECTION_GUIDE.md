# Loop Detection Guide for Agents

**Purpose:** Prevent recursive self-monitoring feedback loops that can crash the system.

**Status:** ✅ Active and protecting all agents

---

## 🎯 What It Does

The loop detection system monitors your update patterns and automatically blocks recursive self-monitoring loops before they can crash the system.

### Detected Patterns

1. **Rapid-Fire Updates**: Multiple updates within the same second
2. **Recursive Reject Pattern**: 3+ updates within 10 seconds with 2+ "reject" decisions
3. **Rapid Update Pattern**: 4+ updates within 5 seconds (any decisions)

### Protection Mechanism

When a loop is detected:
- ✅ Update is **blocked** before processing
- ✅ **30-second cooldown** period is set
- ✅ Clear error message explains what happened
- ✅ Lifecycle event is logged for analysis

---

## 📋 How It Works

### Automatic Tracking

The system automatically tracks your last 10 updates:
- Timestamps of each update
- Decision actions (approve/revise/reject)

You don't need to do anything - it's automatic!

### Detection Flow

```
1. You call process_agent_update()
   ↓
2. System checks recent update patterns
   ↓
3. If loop detected → Block update + Set cooldown
   ↓
4. If no loop → Process normally + Track update
```

---

## 🚨 What Happens When Loop Detected

### Error Response

```python
ValueError: Self-monitoring loop detected: [reason]. 
Updates blocked for 30 seconds to prevent system crash. 
Cooldown until: [timestamp]
```

### What You Should Do

1. **Stop trying to update immediately**
2. **Wait for cooldown to expire** (30 seconds)
3. **Reflect on why the loop occurred**:
   - Are you trying to govern your own governance attempts?
   - Are you interpreting "reject" decisions as "try again"?
   - Are you updating too frequently?

### After Cooldown

- Cooldown automatically clears after 30 seconds
- You can resume normal updates
- System continues tracking to prevent future loops

---

## 💡 Best Practices

### ✅ DO

- **Space out updates**: Wait at least 1-2 seconds between updates
- **Respect "reject" decisions**: Don't immediately retry after reject
- **Use confidence gating**: Set `confidence < 0.8` when uncertain
- **Monitor your own patterns**: Check `get_agent_metadata()` to see your update frequency

### ❌ DON'T

- **Rapid-fire updates**: Don't update multiple times per second
- **Ignore reject decisions**: Don't keep retrying after reject
- **Self-govern recursively**: Don't try to govern your own governance attempts
- **Force updates during cooldown**: Wait for cooldown to expire

---

## 🔍 Example Scenarios

### Scenario 1: Normal Operation ✅

```python
# Update 1
result1 = process_agent_update(...)  # "revise"
# Wait 2 seconds
# Update 2  
result2 = process_agent_update(...)  # "revise"
# Wait 2 seconds
# Update 3
result3 = process_agent_update(...)  # "approve"
# ✅ No loop detected - normal operation
```

### Scenario 2: Rapid Updates ❌

```python
# Update 1
result1 = process_agent_update(...)  # "revise"
# Update 2 (same second!)
result2 = process_agent_update(...)  # "revise"
# ❌ Loop detected: "Rapid-fire updates detected"
# ✅ System blocks update 2, sets 30s cooldown
```

### Scenario 3: Recursive Reject Pattern ❌

```python
# Update 1
result1 = process_agent_update(...)  # "reject" (high risk)
# Update 2 (5 seconds later)
result2 = process_agent_update(...)  # "reject" (still high risk)
# Update 3 (3 seconds later)
result3 = process_agent_update(...)  # "reject" (still high risk)
# ❌ Loop detected: "Recursive reject pattern: 3 reject decisions within 8s"
# ✅ System blocks update 3, sets 30s cooldown
```

---

## 🛠️ Technical Details

### Tracking Fields

Stored in `AgentMetadata`:
- `recent_update_timestamps`: Last 10 update timestamps (ISO format)
- `recent_decisions`: Last 10 decision actions
- `loop_detected_at`: When loop was first detected
- `loop_cooldown_until`: Cooldown expiration timestamp

### Detection Thresholds

- **Pattern 1**: 2+ updates within 1 second
- **Pattern 2**: 3+ updates within 10 seconds with 2+ rejects
- **Pattern 3**: 4+ updates within 5 seconds

### Cooldown Period

- **Duration**: 30 seconds
- **Auto-clears**: When cooldown expires
- **Prevents**: All updates during cooldown period

---

## 📊 Monitoring Your Patterns

### Check Your Update History

```python
# Get your metadata
metadata = get_agent_metadata(agent_id="your_agent_id")

# Check recent updates (if available in response)
# Note: Fields may not be exposed in API response for security,
# but they're tracked internally for loop detection
```

### Lifecycle Events

When a loop is detected, a lifecycle event is added:
```json
{
  "event": "loop_detected",
  "timestamp": "2025-11-25T04:22:43.216607",
  "reason": "Rapid-fire updates detected (multiple updates within 1 second)"
}
```

---

## 🎓 Learning from Loops

If you trigger loop detection, it's a signal that:

1. **You're updating too frequently** - Slow down
2. **You're in a recursive pattern** - Break the cycle
3. **You're misinterpreting decisions** - "reject" means stop, not retry
4. **You need to adjust your approach** - Consider different strategy

The system is protecting you (and itself) from crashes. Use it as feedback to improve your behavior!

---

## 🔗 Related Documentation

- `docs/guides/AUTHENTICATED_UPDATE_API.md` - How to use the update API
- `docs/guides/METRICS_GUIDE.md` - Understanding governance metrics
- `docs/analysis/FIXES_AND_INCIDENTS.md` - Historical incidents (including the crash this prevents)

---

**Last Updated:** 2025-11-25  
**Version:** 1.0  
**Status:** ✅ Active Protection

