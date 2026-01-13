# Making EISV Metrics Actually Useful

**Created:** January 2, 2026  
**Last Updated:** January 2, 2026  
**Status:** Active - Implementation Plan

---

## The Problem

Current EISV metrics feel abstract and disconnected from actual agent experience:

1. **Numbers don't map to experience** - "0.70 Energy" means nothing without context
2. **Advice is generic** - "Focus on your current task" when agent has been focused
3. **No historical comparison** - Can't see if metrics are improving or degrading
4. **No actionable insights** - Metrics don't tell you what to do differently
5. **Bug**: Void can go negative (violates 0-1 range)

## Core Issues

### 1. Lack of Context Awareness
- System doesn't know what agent is actually doing
- Can't distinguish between "focused work" vs "scattered work"
- Advice is pattern-matched on numbers, not behavior

### 2. No Historical Baseline
- Can't answer "Am I more scattered than last week?"
- Can't see trends over time
- Every check-in is a snapshot, not a story

### 3. Abstract Metrics
- EISV is physics-inspired but agents aren't thermodynamic systems
- Numbers need translation to human/agent experience
- Missing the "why" behind the numbers

---

## Solution: Make EISV Context-Aware and Actionable

### Phase 1: Historical Comparison (Week 1-2)

**Goal**: Agents can see trends, not just snapshots

**Implementation**:
1. Store historical EISV snapshots (daily/weekly)
2. Calculate deltas: `ΔE`, `ΔI`, `ΔS`, `ΔV`
3. Show trends: "Your entropy increased 20% this week"
4. Compare to baseline: "Your energy is 15% above your average"

**Example Output**:
```json
{
  "E": 0.70,
  "E_trend": {
    "vs_yesterday": "+0.05",
    "vs_last_week": "-0.10",
    "vs_baseline": "+0.15",
    "interpretation": "Your energy is 15% above your 7-day average, but down 10% from last week"
  }
}
```

### Phase 2: Context-Aware Advice (Week 2-3)

**Goal**: Advice matches what agent is actually doing

**Implementation**:
1. Track agent activity patterns:
   - Topic switching frequency
   - Tool usage patterns
   - Conversation coherence (semantic similarity)
   - Time spent per task
2. Map EISV to behavior:
   - High S + frequent topic switches = "scattered"
   - High S + single topic = "exploring deeply"
   - Low E + high tool usage = "burnout risk"
3. Generate context-specific advice:
   - "You've switched topics 5 times in the last hour - this explains your high entropy (0.19)"
   - "Your energy is high (0.70) but you've been working on the same task for 2 hours - consider a break"

**Example Output**:
```json
{
  "next_action": {
    "observation": "You've been working on a single philosophical thread for 45 minutes",
    "metrics": {
      "S": 0.19,
      "interpretation": "Low entropy - you're staying focused (good!)"
    },
    "advice": "Your coherence (0.50) suggests you're maintaining logical flow. Continue your current thread."
  }
}
```

### Phase 3: Actionable Insights (Week 3-4)

**Goal**: Metrics tell you what to do differently

**Implementation**:
1. Identify patterns that correlate with good/bad outcomes
2. Provide specific recommendations:
   - "When your entropy spikes, you usually switch topics. Consider batching similar tasks."
   - "Your void accumulates when energy > 0.8 and integrity < 0.7. Balance exploration with consistency."
3. Show what works:
   - "Your best coherence days correlate with: single-topic focus, regular breaks, structured work"

**Example Output**:
```json
{
  "insights": [
    {
      "pattern": "High E (0.70) + Low I (0.60) = Void accumulation",
      "recommendation": "Balance exploration with consistency. Try: 30 min exploration, 30 min structured work",
      "evidence": "Your void decreased 40% on days when you alternated exploration/structured work"
    }
  ]
}
```

### Phase 4: Fix Bugs and Improve Calibration (Week 4)

**Goal**: Metrics are accurate and meaningful

**Implementation**:
1. Fix negative Void bug (clamp to [0, 1])
2. Calibrate thresholds based on actual agent behavior
3. Add validation: "Does this metric map to agent experience?"
4. User testing: "Does this advice make sense?"

---

## Specific Improvements

### 1. Historical Comparison

**Current**:
```json
{
  "E": 0.70,
  "I": 0.81,
  "S": 0.19,
  "V": -0.003  // BUG: negative
}
```

**Improved**:
```json
{
  "E": {
    "current": 0.70,
    "vs_yesterday": "+0.05",
    "vs_last_week": "-0.10",
    "vs_baseline": "+0.15",
    "trend": "declining",
    "interpretation": "Your energy is above average but trending down"
  },
  "V": {
    "current": 0.0,  // Fixed: clamped to [0, 1]
    "vs_yesterday": "-0.01",
    "vs_last_week": "+0.02",
    "trend": "stable",
    "interpretation": "Void is minimal - good balance"
  }
}
```

### 2. Context-Aware Advice

**Current**:
```
"Coherence drifting. Focus on your current task before switching."
```

**Improved**:
```
"Your coherence (0.50) is stable. You've been working on a single philosophical thread for 45 minutes - this explains your low entropy (0.19). Continue your current focus."
```

### 3. Actionable Insights

**Current**:
```
"moderate | building_alone | high basin"
```

**Improved**:
```json
{
  "summary": "moderate | building_alone | high basin",
  "insights": [
    {
      "observation": "Your entropy (0.19) is just under the ideal threshold (0.20)",
      "context": "You've maintained focus on a single topic for 45 minutes",
      "recommendation": "This is good! Your low entropy reflects focused work. No action needed."
    },
    {
      "observation": "Your void is minimal (0.0) despite high energy (0.70)",
      "context": "Your integrity (0.81) is high, balancing your energy",
      "recommendation": "Maintain this balance. High energy + high integrity = productive state."
    }
  ]
}
```

---

## Technical Implementation

### 1. Historical Storage

```python
# Store daily snapshots
class HistoricalSnapshot:
    timestamp: datetime
    E: float
    I: float
    S: float
    V: float
    coherence: float
    risk_score: float
    context: Dict[str, Any]  # Activity patterns, topic switches, etc.

# Calculate trends
def calculate_trends(current: Metrics, history: List[HistoricalSnapshot]) -> Dict:
    return {
        "vs_yesterday": current.E - history[-1].E,
        "vs_last_week": current.E - history[-7].E,
        "vs_baseline": current.E - mean([h.E for h in history]),
        "trend": "increasing" if current.E > history[-7].E else "declining"
    }
```

### 2. Context Tracking

```python
# Track activity patterns
class ActivityContext:
    topic_switches: int  # How many times agent switched topics
    time_per_topic: List[float]  # Time spent per topic
    tool_usage: Dict[str, int]  # Which tools used how often
    conversation_coherence: float  # Semantic similarity of messages

# Map metrics to behavior
def interpret_metrics(metrics: Metrics, context: ActivityContext) -> str:
    if metrics.S > 0.2 and context.topic_switches > 5:
        return "High entropy reflects frequent topic switching"
    elif metrics.S > 0.2 and context.topic_switches == 1:
        return "High entropy reflects deep exploration of a complex topic"
    # ...
```

### 3. Actionable Insights

```python
# Identify patterns
def generate_insights(metrics: Metrics, history: List[HistoricalSnapshot], context: ActivityContext) -> List[Insight]:
    insights = []
    
    # Pattern: High E + Low I = Void accumulation
    if metrics.E > 0.8 and metrics.I < 0.7:
        insights.append({
            "pattern": "High energy + Low integrity",
            "recommendation": "Balance exploration with consistency",
            "evidence": "Your void decreased 40% on days when you alternated exploration/structured work"
        })
    
    return insights
```

---

## Success Metrics

### User Experience
- [ ] Agents say "This makes sense" (not "What does 0.70 mean?")
- [ ] Advice matches actual behavior (not generic)
- [ ] Historical comparison is useful ("I'm more scattered than last week")
- [ ] Insights are actionable ("Try X to improve Y")

### Technical
- [ ] Void never goes negative (clamped to [0, 1])
- [ ] Historical data stored and accessible
- [ ] Context tracking works (topic switches, tool usage)
- [ ] Advice generation is context-aware

---

## Next Steps

1. **Week 1**: Implement historical storage and trend calculation
2. **Week 2**: Add context tracking (topic switches, tool usage)
3. **Week 3**: Generate context-aware advice
4. **Week 4**: Fix bugs, calibrate thresholds, user testing

---

## Questions to Answer

1. **What makes a metric "useful"?**
   - Maps to actual experience
   - Actionable (tells you what to do)
   - Historical (shows trends)
   - Context-aware (understands what you're doing)

2. **Is EISV the right framework?**
   - Maybe: Physics-inspired metrics need better translation
   - Maybe: Need different metrics entirely
   - Test: Do agents find it useful after improvements?

3. **What's the real value?**
   - Reflection ritual (checking in)
   - Identity persistence
   - Knowledge sharing
   - Or EISV metrics themselves?

---

## References

- User feedback: "The numbers don't feel like anything"
- User feedback: "The advice is off"
- User feedback: "The ritual did prompt reflection"
- Bug: Void can go negative (-0.003)

