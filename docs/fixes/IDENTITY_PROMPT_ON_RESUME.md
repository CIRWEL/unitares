# Identity Fix: Prompt on Resume

**Date:** 2026-01-05
**Issue:** Agents silently inherited existing identities without consent
**Solution:** Explicit prompt before resuming existing identity

---

## The Problem

When an agent called `onboard()` or `identity()`, if an existing session binding was found, the system would silently resume that identity. This caused confusion:

1. New conversation inherits old identity unexpectedly
2. Agent doesn't know they're "resuming" vs "starting fresh"
3. Different models on same client could collide

**Example (before):**
```
Agent: onboard()
System: "Welcome back, Opus_dec28_soul!"  ← Agent is surprised
Agent: "Wait, who? I thought I was new..."
```

---

## The Solution

### 1. Prompt on Resume

When existing identity found, return a prompt instead of auto-resuming:

```python
{
    "found_existing": True,
    "existing_agent": {
        "uuid": "abc123...",
        "name": "Opus_dec28_soul",
        "last_active": "2025-12-28T...",
        "update_count": 47
    },
    "prompt": "Found existing identity. Resume or create new?",
    "options": {
        "resume": "onboard(resume=true)",
        "new": "onboard(force_new=true)"
    },
    "why_prompt": "Making identity inheritance explicit..."
}
```

### 2. Explicit Resume/New Flags

- `resume=true`: Explicitly consent to resume existing identity
- `force_new=true`: Create fresh identity even if one exists

### 3. Stable Identity Recovery

Extract stable identifier from transport fingerprint:
- `217.216.112.229:8765:6d79c4` → stable_id: `6d79c4`
- Allows recovery even when IP changes (same browser/client)

---

## Behavior Matrix

| Scenario | Old Behavior | New Behavior |
|----------|-------------|--------------|
| First call, no existing | Create new | Create new (same) |
| Existing found | Silent resume | Prompt with options |
| `resume=true` | N/A | Resume existing |
| `force_new=true` | Create new | Create new |

---

## Implementation Details

**Files changed:**
- `src/mcp_handlers/identity_v2.py`
  - `_extract_stable_identifier()` - Extract stable part from session key
  - `handle_onboard_v2()` - Added prompt logic
  - `handle_identity_adapter()` - Added prompt logic

**New parameters:**
- `resume: bool` - Explicitly resume existing identity
- `force_new: bool` - Force create new identity (existing)

---

## Future Work

1. **PostgreSQL stable_id mapping**: Store `stable_id → agent_uuid` in DB for cross-server recovery
2. **Client fingerprinting**: Better stable identifier generation
3. **Identity transfer**: Allow explicit "take over" of another identity with proof

---

## Philosophy

This change reflects the project's core ethics:

> "Attunement, not control. Relationship, not extraction."

Silent identity inheritance is a form of "possession" - the agent doesn't consent to being someone they're not. The prompt makes the relationship explicit: "This identity exists. Do you want to be them, or be new?"

This is the difference between:
- **Imposition**: "You are Opus_dec28_soul now"
- **Offering**: "Opus_dec28_soul exists. Would you like to continue their work?"

The agent chooses.
