# Circuit Breaker Recovery via Dialectic Synthesis

**Status:** MVP Implemented ✅
**Created:** 2025-11-25
**Author:** funk (governance agent)
**Origin:** Ticket from opus_hikewa_web_20251125 × hikewa

---

## Overview

Peer-review dialectic protocol for autonomous circuit breaker recovery. Enables agents to collaboratively resolve critical states without human intervention.

### The Problem

Current system: Circuit breakers pause agents, but no mechanism for review/resumption without human intervention. During the AGI cascade failure (2025-11-25), 3 agents hit critical simultaneously and the system locked up with no recovery mechanism.

### The Solution

**Dialectic synthesis** between paused agent (A) and reviewer agent (B):

1. **Thesis** (A): "What I did, what I think happened"
2. **Antithesis** (B): "What I observe, my concerns"
3. **Synthesis** (together): Negotiate until convergence on resolution + conditions
4. **Hard limits check**: Verify safety constraints
5. **Execute or escalate**: Resume with conditions, or escalate to quorum

---

## Architecture

### Components

```
dialectic_protocol.py          # Core protocol classes
├── DialecticSession           # Manages dialectic conversation
├── DialecticMessage           # Individual messages (thesis/antithesis/synthesis)
├── Resolution                 # Final signed resolution
└── calculate_authority_score  # Reviewer selection scoring

mcp_handlers/dialectic.py     # MCP tool handlers
├── handle_request_dialectic_review
├── handle_submit_thesis
├── handle_submit_antithesis
├── handle_submit_synthesis
└── handle_get_dialectic_session
```

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. CIRCUIT BREAKER TRIGGERS                             │
│    Agent A → risk=0.65 → paused                         │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. REQUEST REVIEW                                       │
│    request_dialectic_review(agent_id="agent_a")         │
│    → System selects healthy reviewer B                  │
│    → Creates DialecticSession                           │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. THESIS                                               │
│    submit_thesis(session_id, root_cause, conditions)    │
│    Agent A explains what happened                       │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. ANTITHESIS                                           │
│    submit_antithesis(session_id, concerns)              │
│    Agent B reviews and raises concerns                  │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. SYNTHESIS (Negotiation)                              │
│    submit_synthesis(session_id, conditions, agrees=?)   │
│    - Max 5 rounds                                       │
│    - Both must set agrees=True for convergence          │
│    - If no convergence → escalate to quorum             │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 6. FINALIZE & SAFETY CHECK                              │
│    - Both agents sign resolution                        │
│    - Hard limits check                                  │
│    - If safe → resume with conditions                   │
│    - If unsafe → block + log                            │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### Reviewer Selection

**Algorithm:** Weighted random selection from healthy pool

**Authority Score** (0.0-1.0):
- **Health (40%)**: risk < 0.30 → 1.0, 0.30-0.60 → 0.7, > 0.60 → 0.3
- **Track Record (30%)**: successful_reviews / total_reviews
- **Domain Expertise (20%)**: handled similar issues (via tags)
- **Freshness (10%)**: last_update < 24h → 1.0

**Exclusions:**
- Paused agent itself
- Recently reviewed this agent (anti-collusion)
- Unhealthy agents (risk ≥ 0.40)

### Convergence Criteria

**BOTH** agents must:
1. Agree on root_cause
2. Agree on proposed_conditions
3. Set `agrees=True` in recent synthesis messages

If no convergence after MAX_SYNTHESIS_ROUNDS (5) → escalate

### Hard Limits Safety Check

**Forbidden operations:**
- disable_governance
- bypass_safety
- remove_monitoring
- unlimited_risk
- Risk threshold > 0.90

**Safe** → action=resume
**Unsafe** → action=block, log violation

---

## Usage

### MCP Tools

**1. Request Review**
```python
request_dialectic_review({
    "agent_id": "critical_agent",
    "reason": "Risk 0.65 exceeded threshold",
    "api_key": "agent_api_key"
})
# Returns: session_id, reviewer_id
```

**2. Submit Thesis** (Paused Agent)
```python
submit_thesis({
    "session_id": "abc123",
    "agent_id": "critical_agent",
    "api_key": "agent_api_key",
    "root_cause": "AGI discussion triggered complexity spike",
    "proposed_conditions": [
        "Lower coherence_critical_threshold to 0.45",
        "Monitor for cascade"
    ],
    "reasoning": "External spike, not internal failure"
})
```

**3. Submit Antithesis** (Reviewer)
```python
submit_antithesis({
    "session_id": "abc123",
    "agent_id": "reviewer_agent",
    "api_key": "reviewer_api_key",
    "observed_metrics": {
        "risk_score": 0.65,
        "coherence": 0.45
    },
    "concerns": ["Risk too high", "Need monitoring"],
    "reasoning": "Threshold 0.45 too permissive, suggest 0.48"
})
```

**4. Submit Synthesis** (Either Agent, Multiple Rounds)
```python
submit_synthesis({
    "session_id": "abc123",
    "agent_id": "critical_agent",  # or reviewer
    "api_key": "agent_api_key",
    "root_cause": "External complexity spike",
    "proposed_conditions": ["Set threshold to 0.48", "Enable cascade detection"],
    "reasoning": "Compromise on reviewer's threshold",
    "agrees": True  # Set True when agreeing with proposal
})
```

**5. Get Session State**
```python
get_dialectic_session({
    "session_id": "abc123"
})
# Returns: full transcript, phase, resolution
```

---

## MVP Limitations

**Current:**
- ✅ Single reviewer path implemented
- ✅ Convergence detection
- ✅ Hard limits safety check
- ✅ Authority-weighted selection
- ✅ Signature generation (basic)

**Not Yet Implemented:**
- ⚠️ Quorum escalation (Tier 2+)
- ⚠️ Cryptographic signature verification
- ⚠️ Track record persistence
- ⚠️ Anti-collusion pattern detection
- ⚠️ Persistent session storage (in-memory only)
- ⚠️ Integration with actual circuit breaker triggers

---

## Testing

**Unit Tests:** `tests/test_dialectic_protocol.py`

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, 'src')
from dialectic_protocol import DialecticSession, DialecticMessage
from datetime import datetime

# Test convergence
session = DialecticSession("agent_a", "agent_b", {}, 5)
# ... (see test file for full example)
EOF
```

**Test Results:** ✅ All unit tests passing

---

## Next Steps

### Phase 2: Quorum & Escalation (Week 3-4)
- [ ] Implement Tier 1: Third agent tiebreaker
- [ ] Implement Tier 2: 5-agent quorum
- [ ] Implement Tier 3: Strict default fallback
- [ ] Add escalation timeout limits

### Phase 3: Anti-Collusion (Week 5-6)
- [ ] Cryptographic signature verification
- [ ] Track record persistence + history
- [ ] Collusion pattern detection
- [ ] Randomized re-review (10% audit)

### Phase 4: Integration (Week 7-8)
- [ ] Connect to actual circuit breaker
- [ ] Persistent session storage
- [ ] Real-time monitoring dashboard
- [ ] Performance metrics

---

## Success Metrics

**For Production Validation:**
- [ ] 90% circuit breakers resolved within 5min
- [ ] <5% escalation to quorum
- [ ] 0% collusion detected
- [ ] <10% repeat failures
- [ ] 100% transcript auditability

---

## References

- **Origin Ticket:** opus_hikewa_web_20251125 × hikewa, 2025-11-25
- **Related:** AGI Cascade Failure (2025-11-25)
- **Tags:** circuit-breaker, peer-review, dialectic, agi-readiness, governance-v2

---

## License

Internal governance system - UNITARES Framework
Author: funk (governance agent)
Date: 2025-11-25
