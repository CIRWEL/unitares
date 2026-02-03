# Governance Thresholds Guide

**Date:** 2025-11-25  
**Purpose:** Explain the difference between decision thresholds and health status thresholds

---

## Overview

The governance system uses **two different sets of thresholds** for different purposes:

1. **Decision Thresholds** - Used for proceed/pause decisions
2. **Health Status Thresholds** - Used for healthy/moderate/critical health monitoring

These serve different purposes and are intentionally different.

---

## Decision Thresholds

**Purpose:** Determine whether an agent's output should be approved, revised, or rejected.

**Location:** `config/governance_config.py`

**Values:**
- `RISK_APPROVE_THRESHOLD = 0.35` (35%) - Updated from 0.30 to reduce false "revise" decisions
- `RISK_REVISE_THRESHOLD = 0.50` (50%)

**Logic:**
```python
if attention_score < 0.35:
    return APPROVE      # Agent proceeds autonomously
elif attention_score < 0.50:
    return REVISE       # Agent should self-correct
else:
    return REJECT       # Agent halts or escalates
```

**Rationale:**
- **Stricter thresholds** - Catch issues early before they become problems
- **Conservative approach** - Better to revise than approve risky outputs
- **Action-oriented** - Directly affects what the agent does next

**Used in:**
- `process_agent_update` - Main decision logic
- `make_decision` - Governance decision function

---

## Health Status Thresholds

**Purpose:** Monitor agent health for observability and alerting.

**Location:** `src/health_thresholds.py`

**Values:**
- `risk_healthy_max = 0.30` (< 30%: Healthy)
- `risk_degraded_max = 0.60` (30-60%: Degraded, ≥60%: Critical)

**Logic:**
```python
if attention_score < 0.30:
    return HEALTHY     # Agent is operating normally
elif attention_score < 0.60:
    return DEGRADED    # Agent needs monitoring
else:
    return CRITICAL    # Agent needs intervention
```

**Rationale:**
- **More lenient thresholds** - Health status is observational, not blocking
- **Monitoring focus** - Tracks trends and patterns over time
- **Alert-oriented** - Triggers alerts and circuit breakers at critical levels

**Used in:**
- `get_health_status` - Health checker function
- `get_metrics` - Status calculation
- `process_update` - Status field in metrics
- `aggregate_metrics` - Fleet health overview

---

## Why Different?

### Decision Thresholds (0.30/0.50) - Stricter

**Reason:** Decisions directly affect agent behavior. Being conservative prevents problems.

**Example:**
- Risk 0.35 → **REVISE** (agent must self-correct)
- Risk 0.55 → **REJECT** (agent halts)

**Impact:** Agent actions are blocked or modified.

---

### Health Status Thresholds (0.30/0.60) - More Lenient

**Reason:** Health status is for monitoring and alerting, not blocking. Need wider bands to track trends.

**Example:**
- Risk 0.35 → **DEGRADED** (monitor closely, but agent continues)
- Risk 0.55 → **DEGRADED** (still monitoring, not critical yet)
- Risk 0.65 → **CRITICAL** (circuit breaker triggers)

**Impact:** Alerts and monitoring, but doesn't block agent actions (except at critical).

---

## Threshold Comparison

| Attention Score | Decision | Health Status | Notes |
|------------|----------|---------------|-------|
| < 0.35 | ✅ APPROVE | ✅ HEALTHY | Both agree - low risk |
| 0.35-0.50 | ⚠️ REVISE | ⚠️ DEGRADED | Decision stricter - requires correction |
| 0.50-0.60 | ❌ REJECT | ⚠️ DEGRADED | Decision blocks, health monitors |
| ≥ 0.60 | ❌ REJECT | 🔴 CRITICAL | Both agree - critical risk |

---

## Key Differences

### 1. Purpose

- **Decisions:** Control agent behavior (proceed/pause)
- **Health:** Monitor agent state (healthy/moderate/critical)

### 2. Stricter vs Lenient

- **Decisions:** Stricter (0.50 cutoff) - catch issues early
- **Health:** More lenient (0.60 cutoff) - track trends

### 3. Action vs Observation

- **Decisions:** Directly affect agent actions
- **Health:** Observational, triggers alerts/circuit breakers

### 4. When Used

- **Decisions:** Every `process_agent_update` call
- **Health:** Monitoring, aggregation, observability tools

---

## Coherence Thresholds

**Single threshold for both:**

- `COHERENCE_CRITICAL_THRESHOLD = 0.40`

**Used for:**
- **Decisions:** If coherence < 0.40 → REJECT (safety override)
- **Health:** If coherence < 0.40 → CRITICAL (circuit breaker)

**Rationale:** Coherence is a safety-critical metric, so same threshold for both.

---

## Best Practices

### For Decision Logic

1. Use `RISK_APPROVE_THRESHOLD` and `RISK_REVISE_THRESHOLD`
2. Be conservative - better to revise than approve risky outputs
3. Consider context - some tasks may need different thresholds

### For Health Monitoring

1. Use `health_checker.get_health_status()` for consistency
2. Monitor trends over time, not just single values
3. Use health status for alerts and circuit breakers

### For Consistency

1. Always use `health_checker` thresholds for health status
2. Always use `config` thresholds for decisions
3. Don't mix thresholds - use the right one for the right purpose

---

## Configuration

**Decision thresholds:** `config/governance_config.py`
```python
RISK_APPROVE_THRESHOLD = 0.30
RISK_REVISE_THRESHOLD = 0.50
```

**Health thresholds:** `src/health_thresholds.py`
```python
risk_healthy_max = 0.30
risk_degraded_max = 0.60
```

**Runtime overrides:** `src/runtime_config.py`
- Can override thresholds at runtime
- Applies to both decision and health thresholds

---

## Related Documentation

- `docs/analysis/RISK_THRESHOLD_CRITIQUE.md` - Detailed threshold analysis
- `docs/analysis/THRESHOLD_VALIDATION_PLAN.md` - Validation methodology
- `config/governance_config.py` - Decision threshold definitions
- `src/health_thresholds.py` - Health threshold definitions

---

## Summary

**Decision thresholds (0.30/0.50):** Stricter, action-oriented, control agent behavior  
**Health thresholds (0.30/0.60):** More lenient, observational, monitor agent state

Both serve important but different purposes. Use the right threshold for the right job.

