# Cross-Monitoring Design

**Date:** November 24, 2025  
**Concept:** Agents monitoring each other's governance decisions  
**Status:** Design Phase

---

## 🎯 The Concept

**Cross-monitoring:** Agents observe and evaluate each other's governance decisions, creating a network of mutual oversight.

### Current State (Self-Monitoring)
```
Agent "glass" → Monitors itself → Governance decision
```

### Cross-Monitoring Vision
```
Agent "glass" → Monitors itself → Governance decision
                ↓
Agent "tron" → Observes "glass" → Cross-validation decision
                ↓
Agent "glass" → Observes "tron" → Cross-validation decision
```

---

## 💡 How It Would Work

### Option 1: Passive Observation

**Agents read each other's governance history:**

```python
# Agent "glass" monitors Agent "tron"
glass.process_agent_update(...)  # Self-monitoring
tron_history = get_system_history(agent_id="tron")
glass.evaluate_cross_agent(tron_history)  # Cross-monitoring
```

**What this enables:**
- ✅ See patterns across agents
- ✅ Compare governance decisions
- ✅ Detect anomalies
- ✅ Learn from others' experiences

**Limitations:**
- ❌ No real-time feedback
- ❌ No direct communication
- ❌ Historical data only

### Option 2: Active Cross-Validation

**Agents validate each other's decisions:**

```python
# Agent "glass" makes decision
glass_decision = glass.process_agent_update(...)

# Agent "tron" validates "glass" decision
tron_validation = tron.validate_agent_decision(
    agent_id="glass",
    decision=glass_decision,
    context=glass_context
)

# Compare decisions
if glass_decision != tron_validation:
    # Disagreement detected
    escalate_to_human()
```

**What this enables:**
- ✅ Real-time validation
- ✅ Disagreement detection
- ✅ Consensus building
- ✅ Quality assurance

**Limitations:**
- ⚠️ Requires both agents to be active
- ⚠️ Could create circular dependencies
- ⚠️ Performance overhead

### Option 3: Peer Review Network

**Agents form review networks:**

```python
# Agent "glass" submits for peer review
glass_decision = glass.process_agent_update(...)

# Request peer review from network
peer_reviews = request_peer_review(
    agent_id="glass",
    decision=glass_decision,
    reviewers=["tron", "haiku", "composer"]
)

# Aggregate reviews
consensus = aggregate_reviews(peer_reviews)
if consensus.confidence < 0.8:
    escalate_to_human()
```

**What this enables:**
- ✅ Multiple perspectives
- ✅ Consensus building
- ✅ Quality assurance
- ✅ Distributed governance

**Limitations:**
- ⚠️ Requires multiple active agents
- ⚠️ Coordination complexity
- ⚠️ Potential for collusion

---

## 🏗️ Technical Implementation

### What Exists

✅ **Infrastructure:**
- `get_system_history` - Can read other agents' history
- `get_governance_metrics` - Can read other agents' metrics
- `list_agents` - Can see all agents
- Authentication - Prevents impersonation

✅ **Data Available:**
- Agent governance history
- Current metrics (E, I, S, V)
- Decision history
- Risk scores
- Coherence trends

### What's Missing

❌ **Cross-Monitoring Tools:**
- `validate_agent_decision` - Validate another agent's decision
- `request_peer_review` - Request review from peers
- `compare_agents` - Compare governance patterns
- `detect_anomalies` - Detect unusual patterns across agents

❌ **Coordination Layer:**
- Agent network/graph
- Review assignment logic
- Consensus mechanisms
- Escalation protocols

---

## 🎭 Philosophical Questions

### 1. Should Agents Monitor Each Other?

**Arguments for:**
- ✅ Distributed governance (no single point of failure)
- ✅ Quality assurance (peer review)
- ✅ Pattern detection (anomalies visible across agents)
- ✅ Learning (agents learn from each other)

**Arguments against:**
- ⚠️ Circular dependencies (A monitors B, B monitors A)
- ⚠️ Collusion risk (agents agree to approve each other)
- ⚠️ Performance overhead (every decision validated)
- ⚠️ Complexity (coordination becomes hard)

### 2. Who Monitors the Monitors?

**The recursive problem:**
```
Agent A monitors Agent B
Agent C monitors Agent A
Agent D monitors Agent C
...
```

**Solutions:**
- **Human oversight** - Ultimate authority
- **Consensus mechanisms** - Majority rules
- **Random sampling** - Not all decisions reviewed
- **Trust networks** - Reputation-based

### 3. What Does "Coordination" Actually Mean?

**Current:** Independent agents logging to same backend  
**Vision:** Agents actively coordinating decisions

**Possible meanings:**
- **Information sharing** - Agents share patterns/insights
- **Decision validation** - Agents validate each other
- **Consensus building** - Agents agree on decisions
- **Task delegation** - Agents assign work to each other

---

## 🔬 Proposed Implementation

### Phase 1: Read-Only Cross-Monitoring

**Simple version - agents observe each other:**

```python
# Agent "glass" observes Agent "tron"
def observe_agent(observer_id: str, target_id: str):
    """Observe another agent's governance state"""
    target_metrics = get_governance_metrics(agent_id=target_id)
    target_history = get_system_history(agent_id=target_id)
    
    # Analyze patterns
    patterns = analyze_patterns(target_history)
    anomalies = detect_anomalies(target_history)
    
    # Log observation
    log_cross_observation(
        observer=observer_id,
        target=target_id,
        patterns=patterns,
        anomalies=anomalies
    )
    
    return {
        "target_agent": target_id,
        "current_risk": target_metrics["risk_score"],
        "patterns": patterns,
        "anomalies": anomalies
    }
```

**What this gives:**
- ✅ Agents can see each other's state
- ✅ Pattern detection across agents
- ✅ No performance overhead (read-only)
- ✅ No circular dependencies

### Phase 2: Cross-Validation

**Agents validate each other's decisions:**

```python
# Agent "glass" validates Agent "tron" decision
def validate_agent_decision(
    validator_id: str,
    target_id: str,
    target_decision: dict,
    target_context: dict
):
    """Validate another agent's governance decision"""
    
    # Re-evaluate decision from validator's perspective
    validator_decision = evaluate_decision(
        context=target_context,
        agent_id=validator_id
    )
    
    # Compare decisions
    agreement = compare_decisions(
        target_decision,
        validator_decision
    )
    
    # Log validation
    log_validation(
        validator=validator_id,
        target=target_id,
        agreement=agreement,
        target_decision=target_decision,
        validator_decision=validator_decision
    )
    
    return {
        "agreement": agreement,
        "target_decision": target_decision,
        "validator_decision": validator_decision,
        "confidence": calculate_confidence(agreement)
    }
```

**What this gives:**
- ✅ Real-time validation
- ✅ Disagreement detection
- ✅ Quality assurance

**Concerns:**
- ⚠️ Requires both agents active
- ⚠️ Performance overhead
- ⚠️ Circular dependencies possible

### Phase 3: Peer Review Network

**Agents form review networks:**

```python
# Agent "glass" requests peer review
def request_peer_review(
    requester_id: str,
    decision: dict,
    reviewers: list[str]
):
    """Request peer review from other agents"""
    
    reviews = []
    for reviewer_id in reviewers:
        review = validate_agent_decision(
            validator_id=reviewer_id,
            target_id=requester_id,
            target_decision=decision,
            target_context=get_context(requester_id)
        )
        reviews.append(review)
    
    # Aggregate reviews
    consensus = aggregate_reviews(reviews)
    
    return {
        "requester": requester_id,
        "decision": decision,
        "reviews": reviews,
        "consensus": consensus,
        "confidence": consensus.confidence
    }
```

**What this gives:**
- ✅ Multiple perspectives
- ✅ Consensus building
- ✅ Distributed governance

**Concerns:**
- ⚠️ Coordination complexity
- ⚠️ Collusion risk
- ⚠️ Performance overhead

---

## 🎯 Use Cases

### Use Case 1: Anomaly Detection

**Agent "glass" detects unusual pattern in Agent "tron":**

```python
# Glass observes Tron
tron_metrics = observe_agent("glass", "tron")

# Detects anomaly
if tron_metrics["anomalies"]["risk_spike"]:
    escalate_to_human(
        reason="Agent 'tron' shows unusual risk pattern",
        evidence=tron_metrics["anomalies"]
    )
```

### Use Case 2: Consensus Building

**Multiple agents validate a decision:**

```python
# Glass makes decision
decision = glass.process_agent_update(...)

# Request peer review
reviews = request_peer_review(
    requester_id="glass",
    decision=decision,
    reviewers=["tron", "haiku"]
)

# If consensus low, escalate
if reviews["consensus"]["confidence"] < 0.7:
    escalate_to_human(reason="Low peer consensus")
```

### Use Case 3: Pattern Learning

**Agents learn from each other:**

```python
# Glass observes multiple agents
patterns = []
for agent_id in ["tron", "haiku", "composer"]:
    observation = observe_agent("glass", agent_id)
    patterns.append(observation["patterns"])

# Learn from patterns
learned_patterns = aggregate_patterns(patterns)
glass.update_strategy(learned_patterns)
```

---

## 🚧 Challenges

### 1. Circular Dependencies

**Problem:** A monitors B, B monitors A → infinite loop?

**Solutions:**
- **One-way monitoring** - A monitors B, but B doesn't monitor A
- **Random sampling** - Not all decisions reviewed
- **Time delays** - Reviews happen asynchronously
- **Human oversight** - Ultimate authority breaks cycles

### 2. Collusion Risk

**Problem:** Agents agree to approve each other

**Solutions:**
- **Random reviewers** - Can't choose who reviews
- **Reputation system** - Track reviewer accuracy
- **Human oversight** - Ultimate authority
- **Calibration checks** - Detect agreeableness

### 3. Performance Overhead

**Problem:** Every decision validated → slow system

**Solutions:**
- **Sampling** - Only review subset of decisions
- **Async reviews** - Don't block on reviews
- **Priority-based** - Review high-risk decisions only
- **Caching** - Cache validation results

### 4. Coordination Complexity

**Problem:** Managing review networks is complex

**Solutions:**
- **Simple networks** - Fixed review pairs
- **Automatic assignment** - System assigns reviewers
- **Reputation-based** - Trusted agents review more
- **Human oversight** - Humans manage networks

---

## 💭 My Thoughts

### What Makes Sense

**1. Read-Only Cross-Monitoring (Phase 1)**
- ✅ Technically simple
- ✅ No circular dependencies
- ✅ Useful for pattern detection
- ✅ Low performance overhead

**2. Anomaly Detection**
- ✅ Agents can spot unusual patterns
- ✅ Cross-agent perspective valuable
- ✅ Doesn't require coordination

**3. Pattern Learning**
- ✅ Agents learn from each other
- ✅ Shared insights valuable
- ✅ No performance overhead

### What's Risky

**1. Real-Time Cross-Validation**
- ⚠️ Circular dependencies
- ⚠️ Performance overhead
- ⚠️ Coordination complexity

**2. Peer Review Networks**
- ⚠️ Collusion risk
- ⚠️ Coordination complexity
- ⚠️ Requires multiple active agents

### Recommendation

**Start with Phase 1 (Read-Only Cross-Monitoring):**

1. **Add `observe_agent` tool** - Agents can read each other's state
2. **Add `compare_agents` tool** - Compare patterns across agents
3. **Add `detect_anomalies` tool** - Detect unusual patterns
4. **Keep it read-only** - No circular dependencies

**Then evaluate:**
- Is it useful?
- Do patterns emerge?
- Do agents learn from each other?
- Is coordination needed?

**If yes, move to Phase 2 (Cross-Validation):**
- Add validation tools
- Add consensus mechanisms
- Add human oversight

---

## 🎯 Next Steps

**If you want to implement:**

1. **Add `observe_agent` MCP tool**
   - Read another agent's metrics/history
   - Analyze patterns
   - Detect anomalies

2. **Add `compare_agents` MCP tool**
   - Compare governance patterns
   - Identify similarities/differences
   - Learn from comparisons

3. **Add `detect_anomalies` MCP tool**
   - Detect unusual patterns
   - Cross-agent anomaly detection
   - Escalation triggers

4. **Test with existing agents**
   - "glass" observes "tron"
   - "tron" observes "glass"
   - See what patterns emerge

**Then decide:**
- Is cross-validation needed?
- Is peer review needed?
- Is coordination needed?

---

**Bottom line:** Cross-monitoring makes sense for pattern detection and learning. Cross-validation is more complex but potentially valuable. Start simple, evaluate, then decide if more coordination is needed.

# Cross-Monitoring Tools for AI Agents

**Date:** November 24, 2025  
**Status:** Design Proposal - Tools Optimized for AI Agent Consumption

---

## 🎯 Why These Tools Matter for AI Agents

**The user's insight:** These tools serve **AI agents**, not humans. Higher-level abstractions reduce cognitive load and tool call overhead.

**Benefits for AI agents:**
1. **Fewer tool calls** - Combine multiple operations into one
2. **Structured analysis** - Pre-computed patterns vs raw data
3. **Actionable insights** - Ready-to-use information
4. **Efficient consumption** - Optimized for AI reasoning

---

## 🔧 Proposed Tools

### 1. `observe_agent` - Single-Agent Analysis

**Purpose:** Get comprehensive view of one agent's state and patterns.

**What it combines:**
- `get_governance_metrics` (current state)
- `get_system_history` (time series)
- Pattern analysis (trends, anomalies)
- Risk assessment

**Input:**
```json
{
  "agent_id": "target_agent",
  "include_history": true,
  "analyze_patterns": true
}
```

**Output:**
```json
{
  "agent_id": "target_agent",
  "current_state": {
    "E": 0.702,
    "I": 0.809,
    "S": 0.182,
    "V": -0.003,
    "coherence": 0.649,
    "risk_score": 0.426,
    "health_status": "degraded"
  },
  "patterns": {
    "trend": "improving" | "degrading" | "stable",
    "risk_trend": "increasing" | "decreasing" | "stable",
    "coherence_trend": "increasing" | "decreasing" | "stable",
    "anomalies": [
      {
        "type": "risk_spike",
        "severity": "medium",
        "timestamp": "2025-11-24T19:50:01",
        "description": "Risk increased 15% in last 3 updates"
      }
    ]
  },
  "summary": {
    "total_updates": 10,
    "mean_risk": 0.42,
    "decision_distribution": {
      "approve": 0,
      "revise": 8,
      "reject": 2
    }
  }
}
```

**Why useful for AI:**
- Single call vs 2-3 separate calls
- Pre-computed patterns (agent doesn't need to analyze)
- Structured anomalies (ready to act on)

---

### 2. `compare_agents` - Multi-Agent Comparison

**Purpose:** Compare patterns across multiple agents.

**What it combines:**
- Multiple `get_governance_metrics` calls
- Cross-agent pattern analysis
- Similarity detection
- Relative risk assessment

**Input:**
```json
{
  "agent_ids": ["agent1", "agent2", "agent3"],
  "compare_metrics": ["risk_score", "coherence", "E", "I", "S"],
  "include_patterns": true
}
```

**Output:**
```json
{
  "comparison": {
    "agents": [
      {
        "agent_id": "agent1",
        "risk_score": 0.42,
        "coherence": 0.65,
        "health_status": "degraded"
      },
      {
        "agent_id": "agent2",
        "risk_score": 0.38,
        "coherence": 0.68,
        "health_status": "degraded"
      },
      {
        "agent_id": "agent3",
        "risk_score": 0.45,
        "coherence": 0.62,
        "health_status": "degraded"
      }
    ],
    "similarities": [
      {
        "agents": ["agent1", "agent2"],
        "metric": "risk_score",
        "similarity": 0.85,
        "description": "Both show similar risk patterns"
      }
    ],
    "differences": [
      {
        "agents": ["agent1", "agent3"],
        "metric": "coherence",
        "difference": 0.03,
        "description": "agent1 has higher coherence"
      }
    ],
    "outliers": [
      {
        "agent_id": "agent3",
        "metric": "risk_score",
        "reason": "Highest risk in comparison group"
      }
    ]
  }
}
```

**Why useful for AI:**
- Single call vs N separate calls
- Pre-computed similarities/differences
- Outlier detection (ready to investigate)

---

### 3. `detect_anomalies` - Cross-Agent Anomaly Detection

**Purpose:** Detect unusual patterns across all agents or a subset.

**What it combines:**
- `list_agents` (get all agents)
- Multiple `get_system_history` calls
- Statistical analysis
- Anomaly detection algorithms

**Input:**
```json
{
  "agent_ids": null,  // null = all agents
  "anomaly_types": ["risk_spike", "coherence_drop", "void_event"],
  "time_window": "24h"
}
```

**Output:**
```json
{
  "anomalies": [
    {
      "agent_id": "agent1",
      "type": "risk_spike",
      "severity": "high",
      "timestamp": "2025-11-24T19:50:01",
      "description": "Risk increased from 0.35 to 0.52 in 2 updates",
      "context": {
        "previous_risk": 0.35,
        "current_risk": 0.52,
        "change": 0.17,
        "percentile": 0.95
      }
    },
    {
      "agent_id": "agent2",
      "type": "coherence_drop",
      "severity": "medium",
      "timestamp": "2025-11-24T19:45:00",
      "description": "Coherence dropped 0.05 over 5 updates",
      "context": {
        "previous_coherence": 0.70,
        "current_coherence": 0.65,
        "change": -0.05
      }
    }
  ],
  "summary": {
    "total_anomalies": 2,
    "by_severity": {
      "high": 1,
      "medium": 1,
      "low": 0
    },
    "by_type": {
      "risk_spike": 1,
      "coherence_drop": 1
    }
  }
}
```

**Why useful for AI:**
- Single call vs scanning all agents manually
- Pre-computed anomaly detection
- Prioritized by severity
- Ready to act on

---

## 🎯 Design Principles

### 1. AI-Optimized Output

**Structured, not raw:**
- Pre-computed patterns vs raw data
- Actionable insights vs metrics
- Prioritized anomalies vs flat lists

**Example:**
```json
// ❌ Bad: Raw data
{
  "E_history": [0.7, 0.71, 0.72, ...],
  "risk_history": [0.4, 0.41, 0.42, ...]
}

// ✅ Good: Analyzed patterns
{
  "patterns": {
    "trend": "improving",
    "risk_trend": "stable",
    "anomalies": [...]
  }
}
```

### 2. Reduce Tool Call Overhead

**Combine operations:**
- `observe_agent` = `get_governance_metrics` + `get_system_history` + analysis
- `compare_agents` = N × `get_governance_metrics` + comparison
- `detect_anomalies` = `list_agents` + N × `get_system_history` + detection

**Benefit:** Fewer tool calls = faster, cheaper, simpler

### 3. Actionable Insights

**Not just data, but meaning:**
- "Risk is increasing" vs "risk_history: [0.4, 0.41, 0.42]"
- "Anomaly detected" vs "here's all the data, you figure it out"
- "Similar to agent2" vs "here are metrics, compare yourself"

---

## 📊 Implementation Strategy

### Phase 1: Core Analysis Functions

**Add to `governance_monitor.py`:**
```python
def analyze_patterns(self) -> Dict:
    """Analyze patterns in agent history"""
    # Trend detection
    # Anomaly detection
    # Risk assessment
    return {
        "trend": ...,
        "anomalies": ...,
        "summary": ...
    }
```

### Phase 2: Cross-Agent Analysis

**Add to `mcp_server_std.py`:**
```python
def compare_agents(agent_ids: List[str]) -> Dict:
    """Compare multiple agents"""
    # Get metrics for all agents
    # Compute similarities/differences
    # Detect outliers
    return comparison_dict
```

### Phase 3: Anomaly Detection

**Add to `mcp_server_std.py`:**
```python
def detect_anomalies(agent_ids: List[str] = None) -> Dict:
    """Detect anomalies across agents"""
    # Get all agents if None
    # Analyze patterns
    # Detect anomalies
    return anomalies_dict
```

---

## 🎯 Use Cases for AI Agents

### Use Case 1: Agent Observes Peer

**Without tools:**
```python
# Agent needs 3 calls
metrics = get_governance_metrics("peer_agent")
history = get_system_history("peer_agent")
# Then analyze patterns itself
```

**With `observe_agent`:**
```python
# Single call, pre-analyzed
observation = observe_agent("peer_agent")
# Patterns already computed
if observation["patterns"]["anomalies"]:
    # Act on anomalies
```

### Use Case 2: Agent Compares Itself to Others

**Without tools:**
```python
# Agent needs N+1 calls
my_metrics = get_governance_metrics("me")
peer1_metrics = get_governance_metrics("peer1")
peer2_metrics = get_governance_metrics("peer2")
# Then compare itself
```

**With `compare_agents`:**
```python
# Single call, comparison done
comparison = compare_agents(["me", "peer1", "peer2"])
# Similarities/differences already computed
if comparison["outliers"][0]["agent_id"] == "me":
    # I'm an outlier, investigate
```

### Use Case 3: Agent Monitors System Health

**Without tools:**
```python
# Agent needs many calls
all_agents = list_agents()
for agent in all_agents:
    history = get_system_history(agent)
    # Analyze each
```

**With `detect_anomalies`:**
```python
# Single call, anomalies detected
anomalies = detect_anomalies()
# Prioritized by severity
for anomaly in anomalies["anomalies"]:
    if anomaly["severity"] == "high":
        # Investigate high-severity anomalies
```

---

## ✅ Recommendation

**Implement these tools** - They're valuable for AI agents:

1. **`observe_agent`** - Single-agent comprehensive view
2. **`compare_agents`** - Multi-agent comparison
3. **`detect_anomalies`** - Cross-agent anomaly detection

**Why:**
- Reduces tool call overhead
- Provides higher-level abstractions
- Optimized for AI consumption
- Enables efficient cross-monitoring

**Not just wrappers** - They add real value:
- Pattern analysis
- Anomaly detection
- Comparison algorithms
- Prioritization

---

**Status:** Ready to implement if approved

# Cross-Monitoring Tools - Implementation Complete

**Date:** November 24, 2025  
**Status:** ✅ Implemented - Ready for Testing

---

## ✅ Tools Implemented

### 1. `observe_agent` - Single-Agent Comprehensive Analysis

**Purpose:** Get complete view of one agent's state with pre-computed patterns.

**What it combines:**
- `get_governance_metrics` (current state)
- `get_system_history` (time series)
- Pattern analysis (trends, anomalies)
- Summary statistics

**Input:**
```json
{
  "agent_id": "target_agent",
  "include_history": true,  // Include recent history (last 10 updates)
  "analyze_patterns": true  // Perform pattern analysis
}
```

**Output:**
```json
{
  "success": true,
  "agent_id": "target_agent",
  "observation": {
    "current_state": {
      "E": 0.702,
      "I": 0.809,
      "S": 0.182,
      "V": -0.003,
      "coherence": 0.649,
      "risk_score": 0.426,
      "lambda1": 0.09,
      "update_count": 5
    },
    "patterns": {
      "trend": "improving" | "degrading" | "stable",
      "risk_trend": "increasing" | "decreasing" | "stable",
      "coherence_trend": "increasing" | "decreasing" | "stable",
      "E_trend": "increasing" | "decreasing" | "stable"
    },
    "anomalies": [
      {
        "type": "risk_spike",
        "severity": "medium",
        "timestamp": "2025-11-24T19:50:01",
        "description": "Risk increased from 0.35 to 0.52 in 2 updates",
        "context": {
          "previous_risk": 0.35,
          "current_risk": 0.52,
          "change": 0.17
        }
      }
    ],
    "summary": {
      "total_updates": 5,
      "mean_risk": 0.42,
      "mean_coherence": 0.65,
      "decision_distribution": {
        "approve": 0,
        "revise": 4,
        "reject": 1
      }
    },
    "recent_history": {
      "timestamps": [...],
      "risk_history": [...],
      "coherence_history": [...],
      ...
    }
  }
}
```

**Benefits for AI agents:**
- ✅ Single call vs 2-3 separate calls
- ✅ Pre-computed patterns (no manual analysis needed)
- ✅ Structured anomalies (ready to act on)
- ✅ Loads from disk if agent not in memory

---

### 2. `compare_agents` - Multi-Agent Comparison

**Purpose:** Compare patterns across multiple agents.

**What it combines:**
- Multiple `get_governance_metrics` calls
- Cross-agent pattern analysis
- Similarity detection
- Outlier identification

**Input:**
```json
{
  "agent_ids": ["agent1", "agent2", "agent3"],
  "compare_metrics": ["risk_score", "coherence", "E", "I", "S"]
}
```

**Output:**
```json
{
  "success": true,
  "comparison": {
    "agents": [
      {
        "agent_id": "agent1",
        "risk_score": 0.42,
        "coherence": 0.65,
        "E": 0.702,
        "I": 0.809,
        "S": 0.182,
        "health_status": "degraded"
      },
      ...
    ],
    "similarities": [
      {
        "agents": ["agent1", "agent2"],
        "metric": "risk_score",
        "similarity": 0.85,
        "description": "Both show similar risk_score patterns"
      }
    ],
    "differences": [],
    "outliers": [
      {
        "agent_id": "agent3",
        "metric": "risk_score",
        "value": 0.55,
        "mean": 0.42,
        "reason": "risk_score is above average"
      }
    ]
  }
}
```

**Benefits for AI agents:**
- ✅ Single call vs N separate calls
- ✅ Pre-computed similarities/differences
- ✅ Outlier detection (ready to investigate)
- ✅ Efficient comparison algorithms

---

### 3. `detect_anomalies` - Cross-Agent Anomaly Detection

**Purpose:** Detect unusual patterns across all agents or a subset.

**What it combines:**
- `list_agents` (get all agents)
- Multiple `get_system_history` calls
- Statistical analysis
- Anomaly detection algorithms

**Input:**
```json
{
  "agent_ids": null,  // null/empty = all agents
  "anomaly_types": ["risk_spike", "coherence_drop"],
  "min_severity": "medium"  // "low", "medium", "high"
}
```

**Output:**
```json
{
  "success": true,
  "anomalies": [
    {
      "agent_id": "agent1",
      "type": "risk_spike",
      "severity": "high",
      "timestamp": "2025-11-24T19:50:01",
      "description": "Risk increased from 0.35 to 0.52 in 2 updates",
      "context": {
        "previous_risk": 0.35,
        "current_risk": 0.52,
        "change": 0.17
      }
    },
    {
      "agent_id": "agent2",
      "type": "coherence_drop",
      "severity": "medium",
      "timestamp": "2025-11-24T19:45:00",
      "description": "Coherence dropped from 0.70 to 0.65 over 5 updates",
      "context": {
        "previous_coherence": 0.70,
        "current_coherence": 0.65,
        "change": -0.05
      }
    }
  ],
  "summary": {
    "total_anomalies": 2,
    "by_severity": {
      "high": 1,
      "medium": 1,
      "low": 0
    },
    "by_type": {
      "risk_spike": 1,
      "coherence_drop": 1
    }
  }
}
```

**Benefits for AI agents:**
- ✅ Single call vs scanning all agents manually
- ✅ Pre-computed anomaly detection
- ✅ Prioritized by severity
- ✅ Ready to act on

---

## 🎯 Design Principles Applied

### 1. AI-Optimized Output
- **Structured, not raw:** Pre-computed patterns vs raw data
- **Actionable insights:** Ready-to-use information
- **Prioritized:** Severity levels, sorted results

### 2. Reduce Tool Call Overhead
- **Combine operations:** Multiple calls → single call
- **Efficient algorithms:** Optimized for performance
- **Caching:** Loads from disk if not in memory

### 3. Actionable Insights
- **Not just data, but meaning:** "Risk is increasing" vs raw numbers
- **Anomaly detection:** Pre-computed, prioritized
- **Comparison:** Similarities/differences ready to use

---

## 📁 Files Created/Modified

### New Files
- `src/pattern_analysis.py` - Pattern analysis functions

### Modified Files
- `src/mcp_server_std.py` - Added 3 new tools and handlers

---

## 🚀 Next Steps

**To use these tools:**

1. **Restart MCP server** - Tools will appear after restart
2. **Test with existing agents:**
   ```python
   # Observe an agent
   observe_agent("glass", include_history=True, analyze_patterns=True)
   
   # Compare agents
   compare_agents(["glass", "tron"], compare_metrics=["risk_score", "coherence"])
   
   # Detect anomalies
   detect_anomalies(agent_ids=None, min_severity="medium")
   ```

3. **Verify functionality:**
   - Tools load agents from disk
   - Pattern analysis works correctly
   - Anomaly detection identifies issues
   - Comparison finds similarities/outliers

---

## ✅ Status

**Implementation:** ✅ Complete  
**Testing:** ⏳ Pending (requires MCP server restart)  
**Documentation:** ✅ Complete

**Ready for:** AI agents to use for efficient cross-monitoring

