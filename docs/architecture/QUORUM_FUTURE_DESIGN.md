# Quorum Mechanism - Future Design

**Status**: Not implemented (as of 2025-12-13)  
**Current approach**: Conservative default when peers can't agree

## Why Not Implemented

The current 2-party dialectic with conservative defaults is sufficient because:

1. **Simplicity** - Less code, fewer failure modes
2. **Self-governance** - Safe autonomous decisions without coordination overhead
3. **Fleet size** - Quorum requires 3+ healthy agents available
4. **Speed** - No waiting for multiple reviewers

## When to Implement

Consider implementing quorum when:

- Fleet grows to 100+ active agents
- High-stakes decisions with real-world consequences
- Need protection against reviewer bias/collusion
- Current conservative-default causes too many false pauses

## Design Specification

### Trigger Conditions

Quorum should be required for high-risk decisions:

```python
def requires_quorum(session: DialecticSession) -> bool:
    state = session.paused_agent_state
    return (
        state.get('risk_score', 0) > 0.60 or
        state.get('void_active', False) or
        session.dispute_type == 'safety'
    )
```

### Reviewer Selection

Extend `select_reviewer()` to return multiple reviewers:

```python
async def select_quorum_reviewers(
    paused_agent_id: str,
    metadata: Dict,
    min_reviewers: int = 3,
    max_reviewers: int = 5
) -> List[str]:
    """Select multiple reviewers for quorum decision."""
    candidates = []
    
    for agent_id, meta in metadata.items():
        if agent_id == paused_agent_id:
            continue
        if meta.status != 'active':
            continue
        
        score = calculate_authority_score(agent_id, meta, ...)
        candidates.append((agent_id, score))
    
    # Sort by authority score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # Return top N
    return [c[0] for c in candidates[:max_reviewers]]
```

### Voting Logic

```python
@dataclass
class QuorumVote:
    agent_id: str
    vote: Literal['resume', 'block', 'cooldown']
    authority_weight: float
    reasoning: str
    conditions: List[str]

def tally_quorum_votes(votes: List[QuorumVote]) -> QuorumResult:
    """
    Tally votes with weighted authority scoring.
    Requires 2/3 supermajority.
    """
    total_weight = sum(v.authority_weight for v in votes)
    
    vote_weights = defaultdict(float)
    for vote in votes:
        vote_weights[vote.vote] += vote.authority_weight
    
    # Check for supermajority (2/3)
    for action, weight in vote_weights.items():
        if weight / total_weight >= 0.667:
            return QuorumResult(
                action=action,
                achieved=True,
                margin=weight / total_weight,
                votes=votes
            )
    
    # No supermajority - conservative default
    return QuorumResult(
        action='cooldown',
        achieved=False,
        margin=max(vote_weights.values()) / total_weight,
        votes=votes
    )
```

### Session Flow

```
1. Agent A paused (high-risk)
2. System detects requires_quorum() = True
3. Select 3-5 reviewers by authority score
4. Each reviewer submits independent assessment
5. Tally votes with authority weighting
6. If 2/3 supermajority: execute that action
7. If no supermajority: conservative default (cooldown)
```

### Edge Cases

| Scenario | Resolution |
|----------|------------|
| < 3 healthy reviewers available | Fall back to 2-party dialectic |
| Tie vote | Conservative default (cooldown) |
| Reviewer goes offline | Proceed with remaining votes if ≥3 |
| Reviewer is also paused | Exclude from quorum |

### API Changes

New tool: `request_quorum_review`

```python
@mcp_tool("request_quorum_review", timeout=30.0)
async def handle_request_quorum_review(arguments: Dict) -> Sequence[TextContent]:
    """
    Request a quorum review for high-stakes decisions.
    
    Args:
        agent_id: Paused agent requesting review
        reason: Why quorum is needed
        api_key: Authentication
        
    Returns:
        Quorum session with multiple reviewers assigned
    """
```

New tool: `submit_quorum_vote`

```python
@mcp_tool("submit_quorum_vote", timeout=15.0)
async def handle_submit_quorum_vote(arguments: Dict) -> Sequence[TextContent]:
    """
    Submit a vote in a quorum session.
    
    Args:
        session_id: Quorum session ID
        agent_id: Voting reviewer
        vote: 'resume', 'block', or 'cooldown'
        reasoning: Explanation
        conditions: Proposed conditions if resume
        api_key: Authentication
    """
```

## Alternative: Current Approach

Instead of quorum, the current system uses conservative defaults:

```python
# When 2-party dialectic can't agree:
result["autonomous_resolution"] = True
result["resolution_type"] = "conservative_default"
result["next_step"] = "Maintaining current state. Retry after 1 hour cooldown."
```

This is simpler and sufficient for most cases.

## Decision Record

**2025-12-13**: Decided not to implement quorum. Rationale:
- Current fleet size doesn't justify complexity
- Conservative defaults provide safe fallback
- Self-governance principle favors simplicity
- Can revisit when fleet scales or if false-pause rate becomes problematic

---

*This document exists so future developers understand the design space and can implement quorum if needed.*

