# Parameter Change Rate Guidelines

**Quick Reference for Governance System Usage**

---

## Key Thresholds

| Parameter Distance | Coherence | Decision | Use Case |
|-------------------|-----------|----------|----------|
| ≤ 0.051 | ≥ 0.60 | ✅ **APPROVE** | Normal operation, stable parameters |
| 0.051 - 0.060 | 0.60 - 0.55 | ⚠️ **REVISE** | Moderate changes, may need review |
| > 0.060 | < 0.55 | ❌ **REJECT** | Large changes, parameter instability |

---

## Quick Guidelines

### For Approve Decisions
- **Keep parameter distance ≤ 0.051**
- Use gradual, small changes
- Maintain parameter stability

### For Revise Decisions  
- **Parameter distance 0.051 - 0.060**
- Requires risk score 0.30 - 0.70
- May need human review

### For Reject Decisions
- **Parameter distance > 0.060**
- Indicates parameter instability
- System correctly identifies as unsafe

---

## Example Scenarios

### ✅ Safe: Gradual Adaptation
```python
# Small changes per update (distance ≈ 0.01)
params = [0.51, 0.49, 0.51, ...]  # Previous: [0.5, 0.5, 0.5, ...]
# Result: coherence ≈ 0.90 → APPROVE
```

### ⚠️ Caution: Moderate Changes
```python
# Moderate changes (distance ≈ 0.05)
params = [0.55, 0.45, 0.55, ...]  # Previous: [0.5, 0.5, 0.5, ...]
# Result: coherence ≈ 0.61 → APPROVE (if risk < 0.30)
#         coherence ≈ 0.61 → REVISE (if risk 0.30-0.70)
```

### ❌ Unsafe: Large Changes
```python
# Large changes (distance ≈ 0.10)
params = [0.6, 0.4, 0.7, 0.3, ...]  # Previous: [0.5, 0.5, 0.5, ...]
# Result: coherence ≈ 0.37 → REJECT
```

---

## Testing Your Parameters

Run the test script to analyze your parameter changes:

```bash
python3 scripts/test_coherence_scenarios.py
```

This will show you:
- Exact coherence for your parameter distance
- Expected decision (approve/revise/reject)
- Risk score estimation

---

## Our Test Results Summary

**9/10 updates rejected** because:
- Parameter distances were **0.08 - 0.15** (too large)
- Coherence dropped to **0.004 - 0.16** (below 0.60 threshold)
- System correctly identified parameter instability

**This is expected behavior** - the system is working as designed to prevent unstable parameter changes.

---

## Recommendations

1. **For Production:** Keep parameter changes gradual (distance < 0.05)
2. **For Testing:** Use the test script to verify your parameter distances
3. **For Adaptation:** Allow gradual changes over multiple updates, not sudden shifts

See `COHERENCE_ANALYSIS.md` for detailed analysis and adaptive threshold strategies.

