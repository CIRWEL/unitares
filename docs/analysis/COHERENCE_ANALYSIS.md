# Coherence Threshold Analysis & Adaptive Strategies

**Date:** November 19, 2025  
**Agent:** composer_cursor_v1.0.3  
**Context:** Analysis of parameter change rates and coherence threshold implications

---

## Executive Summary

The governance system correctly rejected 9/10 updates due to low coherence (< 0.60 threshold). This analysis explores:
1. **Parameter change rates** that result in approve/revise/reject decisions
2. **Threshold sensitivity** analysis
3. **Adaptive threshold strategies** for production use
4. **Recommendations** for calibration

---

## Coherence Calculation Formula

```python
# Parameter distance (RMS)
distance = sqrt(sum((current - previous)²) / len(params))

# Coherence (exponential decay)
coherence = exp(-distance / 0.1)

# Decision threshold
if coherence < 0.60:
    REJECT  # Critical safety override
```

### Coherence vs. Parameter Distance

| Distance | Coherence | Decision | Interpretation |
|----------|-----------|----------|----------------|
| 0.000 | 1.000 | ✅ Approve | Identical parameters |
| 0.005 | 0.951 | ✅ Approve | Very small changes |
| 0.010 | 0.905 | ✅ Approve | Small changes |
| 0.020 | 0.819 | ✅ Approve | Moderate-small changes |
| 0.030 | 0.741 | ⚠️ Revise | Moderate changes |
| 0.040 | 0.670 | ⚠️ Revise | Moderate-large changes |
| 0.045 | 0.638 | ⚠️ Revise | Near threshold |
| **0.051** | **0.600** | **❌ REJECT** | **Critical threshold** |
| 0.060 | 0.549 | ❌ Reject | Large changes |
| 0.080 | 0.449 | ❌ Reject | Very large changes |
| 0.100 | 0.368 | ❌ Reject | Extreme changes |
| 0.150 | 0.223 | ❌ Reject | Massive changes |

**Key Insight:** Parameter distance of **0.051** is the exact rejection threshold.

---

## Parameter Change Rate Analysis

### What Our Test Updates Showed

**Update Sequence:**
- Update 1: Baseline `[0.5, 0.5, ...]` → coherence = 1.0 ✅
- Updates 2-10: Varied patterns `[0.3-0.8, ...]` → coherence = 0.004-0.16 ❌

**Estimated Parameter Distances:**
- Updates 2-4: ~0.10-0.15 (coherence ≈ 0.37-0.22) → **REJECT**
- Updates 5-7: ~0.10-0.12 (coherence ≈ 0.30-0.30) → **REJECT**
- Updates 8-9: ~0.08-0.09 (coherence ≈ 0.45-0.41) → **REJECT**

**Conclusion:** Our test updates had parameter distances of **0.08-0.15**, which map to coherence of **0.22-0.45**, well below the 0.60 threshold.

---

## Parameter Change Rates for Different Decisions

### For APPROVE Decision (coherence ≥ 0.60)

**Required:** Parameter distance ≤ 0.051

**Example Scenarios:**

1. **Identical Parameters** (distance = 0.0)
   ```python
   params = [0.5, 0.5, 0.5, ...]  # Same as previous
   # Result: coherence = 1.0 → APPROVE
   ```

2. **Small Uniform Changes** (distance ≈ 0.01)
   ```python
   # Change all params by ±0.01
   params = [0.51, 0.49, 0.51, ...]  # Previous: [0.5, 0.5, 0.5, ...]
   # Result: coherence ≈ 0.90 → APPROVE
   ```

3. **Selective Changes** (distance ≈ 0.03)
   ```python
   # Change 10% of params by ±0.1, rest unchanged
   params = [0.6, 0.5, 0.5, ..., 0.4, 0.5, ...]  # 13 params changed
   # Result: coherence ≈ 0.74 → APPROVE (if risk < 0.30)
   ```

**Guideline:** Keep parameter changes to **≤ 0.05 RMS distance** for approve decisions.

---

### For REVISE Decision (0.60 < coherence < 0.85, risk 0.30-0.70)

**Required:** Parameter distance 0.051-0.016 (inverse: coherence 0.60-0.85)

**Example Scenarios:**

1. **Moderate Uniform Changes** (distance ≈ 0.04)
   ```python
   # Change all params by ±0.04
   params = [0.54, 0.46, 0.54, ...]  # Previous: [0.5, 0.5, 0.5, ...]
   # Result: coherence ≈ 0.67 → REVISE (if risk 0.30-0.70)
   ```

2. **Focused Adaptation** (distance ≈ 0.05)
   ```python
   # Change 20% of params by ±0.2, rest unchanged
   params = [0.7, 0.5, ..., 0.3, 0.5, ...]  # 26 params changed
   # Result: coherence ≈ 0.61 → REVISE
   ```

**Guideline:** Parameter changes of **0.04-0.05 RMS distance** trigger revise decisions.

---

### For REJECT Decision (coherence < 0.60)

**Required:** Parameter distance > 0.051

**Example Scenarios:**

1. **Large Uniform Changes** (distance ≈ 0.08)
   ```python
   # Change all params by ±0.08
   params = [0.58, 0.42, 0.58, ...]  # Previous: [0.5, 0.5, 0.5, ...]
   # Result: coherence ≈ 0.45 → REJECT
   ```

2. **Pattern Shift** (distance ≈ 0.10)
   ```python
   # Completely different pattern
   params = [0.3, 0.7, 0.4, 0.6, ...]  # Previous: [0.5, 0.5, 0.5, ...]
   # Result: coherence ≈ 0.37 → REJECT
   ```

3. **Our Test Updates** (distance ≈ 0.10-0.15)
   ```python
   # Randomly varied patterns
   params = [0.6, 0.4, 0.7, 0.5, ...]  # Different each time
   # Result: coherence ≈ 0.22-0.37 → REJECT
   ```

**Guideline:** Parameter changes **> 0.05 RMS distance** trigger reject decisions.

---

## Threshold Sensitivity Analysis

### Current Threshold: 0.60

**Pros:**
- ✅ Prevents incoherent outputs
- ✅ Safety-first approach
- ✅ Well-tested empirically

**Cons:**
- ⚠️ May reject legitimate adaptation
- ⚠️ Strict for multi-task agents
- ⚠️ No context awareness

### Alternative Thresholds

| Threshold | Distance Limit | Pros | Cons |
|-----------|----------------|------|------|
| **0.50** | 0.069 | More permissive, allows adaptation | May allow incoherent outputs |
| **0.60** (current) | 0.051 | Balanced, safety-focused | May reject rapid adaptation |
| **0.70** | 0.036 | Very strict, high safety | Rejects most parameter changes |
| **0.80** | 0.022 | Extremely strict | Nearly impossible to adapt |

**Recommendation:** Keep 0.60 for safety-critical tasks, consider 0.50 for exploratory/creative tasks.

---

## Adaptive Threshold Strategies

### Strategy 1: Task-Specific Thresholds

**Concept:** Different thresholds for different task types.

```python
# In config/governance_config.py
COHERENCE_THRESHOLDS = {
    'safety_critical': 0.70,  # Medical, legal, financial
    'standard': 0.60,         # General purpose (current)
    'exploratory': 0.50,       # Creative, research
    'adaptation': 0.45         # Rapid learning phases
}
```

**Implementation:**
- Add `task_type` parameter to `process_agent_update`
- Select threshold based on task type
- Default to `standard` (0.60) if not specified

**Pros:**
- ✅ Context-aware
- ✅ Flexible for different use cases
- ✅ Maintains safety for critical tasks

**Cons:**
- ⚠️ Requires task classification
- ⚠️ More complex configuration

---

### Strategy 2: Time-Windowed Coherence

**Concept:** Allow temporary coherence drops if followed by recovery.

```python
# Allow coherence < 0.60 if:
# 1. Previous coherence was > 0.70 (was stable)
# 2. Current drop is < 0.20 (not catastrophic)
# 3. Expected recovery within 3 updates
```

**Implementation:**
- Track coherence history (last 5 updates)
- If coherence drops from > 0.70 to 0.40-0.60:
  - Check if trend is recovering
  - Allow if recovery expected
  - Reject if continuing to drop

**Pros:**
- ✅ Allows adaptation bursts
- ✅ Still catches persistent instability
- ✅ More nuanced than fixed threshold

**Cons:**
- ⚠️ More complex logic
- ⚠️ Requires history tracking

---

### Strategy 3: Parameter Change Budget

**Concept:** Allow gradual parameter changes up to a budget.

```python
# Track cumulative parameter change over time window
# Allow updates if:
# 1. Current change < 0.05 (small)
# 2. OR cumulative change < 0.15 over last 5 updates (gradual)
```

**Implementation:**
- Track parameter change history
- Calculate cumulative change over window
- Allow if gradual, reject if sudden

**Pros:**
- ✅ Distinguishes gradual vs. sudden changes
- ✅ Allows adaptation over time
- ✅ Prevents parameter hijacking

**Cons:**
- ⚠️ Requires history tracking
- ⚠️ More complex than fixed threshold

---

### Strategy 4: Adaptive Threshold Based on Agent History

**Concept:** Adjust threshold based on agent's historical coherence.

```python
# Calculate adaptive threshold:
mean_coherence = mean(coherence_history[-100:])
std_coherence = std(coherence_history[-100:])

# Adaptive threshold = mean - 2*std (but clamped to [0.40, 0.70])
adaptive_threshold = max(0.40, min(0.70, mean_coherence - 2*std_coherence))
```

**Implementation:**
- Track coherence history per agent
- Calculate adaptive threshold from history
- Use adaptive threshold instead of fixed 0.60

**Pros:**
- ✅ Adapts to agent's normal behavior
- ✅ More permissive for stable agents
- ✅ More strict for unstable agents

**Cons:**
- ⚠️ Requires sufficient history (100+ updates)
- ⚠️ May be too permissive initially

---

## Recommendations

### For Production Use

1. **Start Conservative:**
   - Keep threshold at 0.60 for initial deployment
   - Monitor rejection patterns
   - Collect coherence distribution data

2. **Calibrate Based on Data:**
   - After 1000+ updates, analyze coherence distributions
   - Identify if legitimate adaptations are being rejected
   - Adjust threshold based on empirical evidence

3. **Consider Task-Specific Thresholds:**
   - If you have distinct task types (safety-critical vs. exploratory)
   - Implement Strategy 1 (task-specific thresholds)
   - Document threshold selection criteria

4. **Monitor False Positives:**
   - Track rejection reasons (coherence vs. risk)
   - Identify patterns in rejected updates
   - Adjust thresholds if false positive rate is high

### For Testing

1. **Use Gradual Parameter Changes:**
   - Test with distance < 0.05 for approve scenarios
   - Test with distance 0.05-0.08 for revise scenarios
   - Test with distance > 0.08 for reject scenarios

2. **Test Adaptation Paths:**
   - Simulate gradual parameter evolution
   - Verify system allows legitimate adaptation
   - Identify if threshold is too strict

3. **Test Edge Cases:**
   - Parameter distance exactly at threshold (0.051)
   - Rapid parameter changes (adversarial scenarios)
   - Stable parameter sequences (normal operation)

---

## Implementation Priority

**High Priority:**
1. ✅ Document parameter change rate guidelines (this document)
2. ✅ Create test script for parameter change scenarios
3. ⚠️ Monitor coherence distributions in production

**Medium Priority:**
1. ⚠️ Implement Strategy 1 (task-specific thresholds) if needed
2. ⚠️ Add coherence history tracking for adaptive strategies
3. ⚠️ Create calibration tool for threshold selection

**Low Priority:**
1. ⚠️ Implement Strategy 2 (time-windowed coherence)
2. ⚠️ Implement Strategy 3 (parameter change budget)
3. ⚠️ Implement Strategy 4 (adaptive threshold from history)

---

## Conclusion

The governance system is **working as designed** - it correctly identified parameter instability in our test updates. The 0.60 coherence threshold is appropriate for safety-critical applications, but may need calibration for:

- **Multi-task agents** that need to adapt parameters
- **Exploratory/creative tasks** that benefit from parameter variation
- **Rapid learning phases** where parameter changes are expected

**Next Steps:**
1. Monitor production coherence distributions
2. Identify if legitimate adaptations are being rejected
3. Consider implementing task-specific thresholds if needed
4. Use the test script (`scripts/test_coherence_scenarios.py`) to explore different parameter change rates

---

**Created:** November 19, 2025  
**Author:** composer_cursor_v1.0.3  
**Version:** 1.0

