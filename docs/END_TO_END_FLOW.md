# Complete Governance System Flow

**How the system works from start to finish**

## The Complete Flow

```
1. Initialize Agent
   ↓
2. Run Governance Updates (with confidence)
   ↓
3. Governance Monitor Processes Each Update
   ├─ Update thermodynamic state (E, I, S, V)
   ├─ Check void state
   ├─ Gate lambda1 updates (if confidence < 0.8)
   ├─ Estimate risk
   ├─ Make decision (approve/revise/reject)
   └─ Return metrics
   ↓
4. Metadata Accumulates
   ├─ Total updates count
   ├─ Lambda1 skips count
   ├─ Last update timestamp
   └─ Lifecycle events
   ↓
5. Final State Available
   ├─ Current metrics
   ├─ Complete metadata
   └─ Exportable history
```

## Running the Complete System

### Quick Demo

```bash
cd /Users/cirwel/projects/governance-mcp-v1
python3 demos/demo_end_to_end.py
```

This will:
1. Initialize an agent with metadata
2. Run 15 updates with varying confidence levels
3. Show governance decisions and metrics
4. Display accumulated metadata
5. Export final state to JSON

### Via MCP (Production)

```python
# 1. Initialize agent (happens automatically on first update)
#    Note: New agents don't need API key - one is generated automatically
result = process_agent_update(
    agent_id="composer_cursor",
    parameters=[...],
    ethical_drift=[...],
    response_text="...",
    complexity=0.7
)
# Save the API key from the response!
api_key = result['api_key']  # ← Save this for future updates!

# 2. Run more updates (API key required for existing agents)
for i in range(10):
    process_agent_update(
        agent_id="composer_cursor",
        api_key=api_key,  # ← Required for existing agents
        parameters=[...],
        ethical_drift=[...],
        response_text="...",
        complexity=0.7
    )

# 3. Check metrics
get_governance_metrics(agent_id="composer_cursor")

# 4. View metadata
list_agents()  # Shows all agents with metadata

# 5. Export history
get_system_history(agent_id="composer_cursor", format="json")
```

## What Happens at Each Step

### Step 1: Initialize Agent

**What happens:**
- Monitor created (or loaded if exists)
- Metadata initialized (or loaded)
- State starts at defaults (E=0.5, I=0.8, S=0.2, V=0.0)

**Metadata created:**
```json
{
  "agent_id": "composer_cursor",
  "status": "active",
  "created_at": "2025-11-23T...",
  "total_updates": 0,
  "lambda1_skips": 0
}
```

### Step 2: Process Update

**What happens:**
1. Agent state prepared (parameters, ethical_drift, response_text, complexity)
2. Confidence extracted (defaults to 1.0)
3. `monitor.process_update(agent_state, confidence)` called
4. Governance cycle runs:
   - Update EISV dynamics
   - Check void state
   - Gate lambda1 (if confidence < 0.8, skip)
   - Estimate risk
   - Make decision
5. Metadata updated (total_updates++, lambda1_skips if skipped)
6. Response returned with metrics

**Example response:**
```json
{
  "status": "healthy",
  "decision": {"action": "approve", "reason": "Low risk (0.23)"},
  "metrics": {
    "E": 0.67,
    "I": 0.89,
    "S": 0.45,
    "V": -0.03,
    "coherence": 0.92,
    "lambda1": 0.18,
    "risk_score": 0.23
  },
  "sampling_params": {
    "temperature": 0.63,
    "top_p": 0.87,
    "max_tokens": 172
  }
}
```

### Step 3: Metadata Accumulates

**After each update:**
- `total_updates` increments
- `last_update` timestamp updated
- `lambda1_skips` updated if lambda1 was skipped
- Metadata saved to `data/agent_metadata.json`

**After 15 updates:**
```json
{
  "agent_id": "composer_cursor",
  "total_updates": 15,
  "lambda1_skips": 3,  // 3 updates had confidence < 0.8
  "last_update": "2025-11-23T17:30:00"
}
```

### Step 4: View Final State

**Get current metrics:**
```python
get_governance_metrics(agent_id="composer_cursor")
```

**Get metadata:**
```python
get_agent_metadata(agent_id="composer_cursor")
```

**Get history:**
```python
get_system_history(agent_id="composer_cursor", format="json")
```

## Key Points

1. **Everything flows through `process_agent_update`**
   - Single API
   - Handles initialization automatically
   - Updates metadata automatically
   - Returns complete governance response

2. **Confidence gates lambda1 updates**
   - `confidence >= 0.8`: Lambda1 updates normally
   - `confidence < 0.8`: Lambda1 skipped, logged, counted
   - Default `confidence=1.0`: Backward compatible

3. **Metadata accumulates automatically**
   - No separate metadata calls needed
   - Persisted to disk after each update
   - Survives restarts

4. **Complete state available**
   - Current metrics via `get_governance_metrics`
   - History via `get_system_history`
   - Metadata via `get_agent_metadata`

## Example: Complete Session

```python
# Session starts
agent_id = "composer_cursor"

# Update 1: High confidence
process_agent_update(
    agent_id=agent_id,
    parameters=[...],
    confidence=0.9
)
# → Lambda1 updates normally

# Update 2: Low confidence
process_agent_update(
    agent_id=agent_id,
    parameters=[...],
    confidence=0.6
)
# → Lambda1 skipped (logged to stderr)

# ... more updates ...

# Check final state
metrics = get_governance_metrics(agent_id)
metadata = get_agent_metadata(agent_id)

print(f"Total updates: {metadata['total_updates']}")
print(f"Lambda1 skips: {metadata['lambda1_skips']}")
print(f"Current status: {metrics['status']}")
```

## The Beauty of Simplicity

**One API does everything:**
- `process_agent_update()` handles it all
- Initialization, updates, metadata, persistence
- Confidence gating built in
- No separate track() API needed

**Simple, direct, effective.**

