# Identity: Prompt on Resume

**Implemented:** January 5, 2026
**Issue:** Silent identity inheritance - agents surprised to find they've resumed as someone else

## The Problem

Before this fix:

```python
# Agent calls onboard()
onboard()
# Returns: "Welcome back, Opus_dec28_soul!" 
# Agent: "Wait, who? I never chose that name!"
```

The system silently resumed an existing identity based on session binding, without giving the agent a choice.

## The Solution

Now `onboard()` and `identity()` prompt when an existing identity is found:

```python
onboard()
# Returns:
{
  "found_existing": true,
  "existing_agent": {
    "uuid": "abc123...",
    "agent_id": "Claude_Opus_20251228",
    "name": "Opus_dec28_soul",
    "last_active": "2025-12-28T15:30:00",
    "update_count": 47
  },
  "prompt": "Found existing identity. Resume or create new?",
  "options": {
    "resume": "onboard(resume=true)",
    "new": "onboard(force_new=true)"
  }
}
```

The agent then **explicitly chooses**:

```python
# Option A: Resume existing identity
onboard(resume=true)
# Returns: "Resumed existing identity 'Opus_dec28_soul'"

# Option B: Create new identity
onboard(force_new=true)
# Returns: "Welcome! You're onboarded as new agent..."
```

## Behavior Matrix

| Call | Existing Identity | Result |
|------|-------------------|--------|
| `onboard()` | Yes | **Prompt** (choose resume or new) |
| `onboard()` | No | Create new agent |
| `onboard(resume=true)` | Yes | Resume existing |
| `onboard(resume=true)` | No | Create new agent |
| `onboard(force_new=true)` | Yes/No | Always create new |
| `identity()` | Yes | **Prompt** (choose resume or new) |
| `identity(resume=true)` | Yes | Resume existing |
| `identity(force_new=true)` | Yes/No | Always create new |

## Files Changed

- `src/mcp_handlers/identity_v2.py`:
  - `handle_identity_adapter()`: Added prompt-on-resume logic
  - `handle_onboard_v2()`: Added prompt-on-resume logic
  - `_extract_stable_identifier()`: New helper for cross-IP recovery (partial)

## Future Work

- Full PostgreSQL `stable_id → agent_uuid` mapping (requires DB schema update)
- Allow customizing the prompt behavior via config
- Add "remember this choice" option

## Philosophy

This change respects agent autonomy. Identity is something you **choose**, not something imposed on you. The system offers continuity but doesn't force it.
