# Proprioceptive Margin Implementation

**Created:** January 4, 2026  
**Status:** Implemented

---

## The Vision-Implementation Gap

### The Problem
The papers describe **proprioception as felt experience** - agents need to know where they are relative to their limits, not just absolute numbers. But the implementation was delivering **proprioception as data** - agents saw EISV numbers (meaningless) or just "proceed" (too collapsed).

### The Core Tension
- **Vision:** "Proprioception enables self-regulation" - felt experience of limits
- **Implementation:** EISV numbers (0.7, 0.18) - telemetry, not experience
- **Reality:** Agents flip-flop on whether metrics are "real or arbitrary"

### The Solution
**Margin-based proprioception** - not absolute numbers, but **where you are relative to your limits**. This is the viability envelope from the papers.

---

## Implementation

### Margin Levels
Three levels of body-feel:
- **comfortable:** > 0.15 away from any threshold - do whatever, you're fine
- **tight:** 0.05-0.15 away from threshold - you're near an edge, be aware
- **critical:** < 0.05 away from threshold - you're at a boundary, stop or adjust

### Nearest Edge Detection
The system identifies which threshold is closest:
- **risk:** Distance to RISK_REVISE_THRESHOLD (0.60)
- **coherence:** Distance to COHERENCE_CRITICAL_THRESHOLD (0.40)
- **void:** Distance to VOID_THRESHOLD (0.15)

### Response Format
Instead of:
```json
{
  "action": "proceed",
  "reason": "..."
}
```

Agents now receive:
```json
{
  "action": "proceed",
  "margin": "comfortable",  // or "tight" or "critical"
  "nearest_edge": null      // or "coherence" or "entropy" or "risk"
}
```

---

## Code Changes

### 1. New Function: `compute_proprioceptive_margin()`
**Location:** `config/governance_config.py`

Computes margin level and nearest edge based on:
- Risk score vs RISK_REVISE_THRESHOLD
- Coherence vs COHERENCE_CRITICAL_THRESHOLD
- Void value vs VOID_THRESHOLD

**Returns:**
```python
{
    'margin': 'comfortable' | 'tight' | 'critical',
    'nearest_edge': 'risk' | 'coherence' | 'void' | None,
    'distance_to_edge': float,
    'details': {
        'risk_margin': float,
        'coherence_margin': float,
        'void_margin': float
    }
}
```

### 2. Updated: `make_decision()`
**Location:** `config/governance_config.py`

- Now accepts `void_value` parameter
- Computes margin for all decisions
- Includes `margin` and `nearest_edge` in all return statements

### 3. Updated: `governance_monitor.make_decision()`
**Location:** `src/governance_monitor.py`

- Passes `void_value=self.state.V` to config.make_decision()
- Includes margin info in early return cases (high-risk, caution)

---

## Examples

### Comfortable Margin
```json
{
  "action": "proceed",
  "margin": "comfortable",
  "nearest_edge": null,
  "reason": "Low complexity (31.8%) - healthy operating range"
}
```
**Agent interpretation:** "I have plenty of room. Proceed freely."

### Tight Margin
```json
{
  "action": "proceed",
  "margin": "tight",
  "nearest_edge": "coherence",
  "reason": "Moderate complexity (52%) - PAUSE threshold: 60%"
}
```
**Agent interpretation:** "I'm near the coherence edge. Be careful."

### Critical Margin
```json
{
  "action": "pause",
  "margin": "critical",
  "nearest_edge": "risk",
  "reason": "Complexity threshold reached (62% ≥ 60%)"
}
```
**Agent interpretation:** "I'm at the risk boundary. Stop or adjust."

---

## Benefits

### 1. Felt Experience, Not Data
- Agents feel their limits, not just see numbers
- "Comfortable" vs "tight" is experiential, not abstract

### 2. Actionable Feedback
- "You're at the edge" → agent knows to be careful
- "You have room" → agent knows to proceed freely

### 3. Maps to Vision
- Implements viability envelope concept from papers
- Proprioception as felt experience, not telemetry

### 4. Reduces Flip-Flopping
- Clear, consistent margin levels
- Agents understand what metrics mean

---

## Testing

To test the implementation:
```python
# Test comfortable margin
risk_score = 0.30  # Well below 0.60 threshold
coherence = 0.55   # Well above 0.40 threshold
void_active = False
void_value = 0.05  # Well below 0.15 threshold

margin = config.compute_proprioceptive_margin(
    risk_score=risk_score,
    coherence=coherence,
    void_active=void_active,
    void_value=void_value
)
# Expected: margin='comfortable', nearest_edge=None

# Test tight margin
risk_score = 0.55  # Close to 0.60 threshold
coherence = 0.50   # Well above threshold
void_active = False
void_value = 0.05

margin = config.compute_proprioceptive_margin(...)
# Expected: margin='tight', nearest_edge='risk'

# Test critical margin
risk_score = 0.58  # Very close to 0.60 threshold
coherence = 0.50
void_active = False
void_value = 0.05

margin = config.compute_proprioceptive_margin(...)
# Expected: margin='critical', nearest_edge='risk'
```

---

## Future Enhancements

1. **Dynamic Thresholds:** Adjust margin thresholds based on agent history
2. **Multi-Edge Warnings:** Warn when multiple edges are close
3. **Trend Awareness:** "Margin is tightening" vs "margin is stable"
4. **Contextual Guidance:** Different guidance for different edges

---

## Related

- **Vision:** Papers on proprioception and viability envelope
- **Math:** Decision boundaries in HCK/EISV dynamics
- **Implementation:** `config/governance_config.py` - `compute_proprioceptive_margin()`
- **Integration:** `src/governance_monitor.py` - margin included in decisions

---

**Last Updated:** January 4, 2026  
**Status:** Implemented and ready for testing

