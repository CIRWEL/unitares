"""
Pattern Analysis for Cross-Monitoring

Provides analysis functions for detecting trends, anomalies, and patterns
in agent governance history. Optimized for AI agent consumption.
"""

from typing import Dict, List, Optional
import numpy as np
from collections import Counter


def analyze_trend(values: List[float], window: int = 5) -> str:
    """
    Analyze trend in a time series.
    
    Returns: "increasing", "decreasing", or "stable"
    """
    if len(values) < 2:
        return "stable"
    
    if len(values) < window:
        window = len(values)
    
    recent = values[-window:]
    older = values[-window*2:-window] if len(values) >= window*2 else values[:-window]
    
    if len(older) == 0:
        return "stable"
    
    recent_mean = np.mean(recent)
    older_mean = np.mean(older)
    
    change = recent_mean - older_mean
    threshold = 0.05  # 5% change threshold
    
    if abs(change) < threshold:
        return "stable"
    elif change > 0:
        return "increasing"
    else:
        return "decreasing"


def detect_anomalies_in_history(
    risk_history: List[float],
    coherence_history: List[float],
    timestamps: List[str]
) -> List[Dict]:
    """
    Detect anomalies in agent history.
    
    Returns list of anomaly dicts with type, severity, timestamp, description.
    """
    anomalies = []
    
    if len(risk_history) < 3:
        return anomalies
    
    # Risk spike detection
    recent_risk = risk_history[-3:]
    older_risk = risk_history[-6:-3] if len(risk_history) >= 6 else risk_history[:-3]
    
    if len(older_risk) > 0:
        recent_mean = np.mean(recent_risk)
        older_mean = np.mean(older_risk)
        change = recent_mean - older_mean
        
        if change > 0.15:  # 15% increase
            severity = "high" if change > 0.25 else "medium"
            anomalies.append({
                "type": "risk_spike",
                "severity": severity,
                "timestamp": timestamps[-1] if timestamps else None,
                "description": f"Risk increased from {older_mean:.2f} to {recent_mean:.2f} ({change:.2f} change)",
                "context": {
                    "previous_risk": float(older_mean),
                    "current_risk": float(recent_mean),
                    "change": float(change)
                }
            })
    
    # Coherence drop detection
    if len(coherence_history) >= 5:
        recent_coherence = coherence_history[-3:]
        older_coherence = coherence_history[-5:-3]
        
        if len(older_coherence) > 0:
            recent_mean = np.mean(recent_coherence)
            older_mean = np.mean(older_coherence)
            change = older_mean - recent_mean  # Negative change = drop
            
            if change > 0.05:  # 5% drop
                severity = "high" if change > 0.10 else "medium"
                anomalies.append({
                    "type": "coherence_drop",
                    "severity": severity,
                    "timestamp": timestamps[-1] if timestamps else None,
                    "description": f"Coherence dropped from {older_mean:.2f} to {recent_mean:.2f} ({change:.2f} change)",
                    "context": {
                        "previous_coherence": float(older_mean),
                        "current_coherence": float(recent_mean),
                        "change": float(-change)
                    }
                })
    
    return anomalies


def analyze_agent_patterns(
    monitor,
    include_history: bool = True
) -> Dict:
    """
    Analyze patterns in an agent's governance history.
    
    Returns structured analysis optimized for AI consumption.
    """
    state = monitor.state
    
    # Current state
    current_state = {
        "E": float(state.E),
        "I": float(state.I),
        "S": float(state.S),
        "V": float(state.V),
        "coherence": float(state.coherence),
        "risk_score": float(state.risk_history[-1]) if state.risk_history else 0.0,
        "lambda1": float(state.lambda1),
        "update_count": state.update_count
    }
    
    # Pattern analysis
    patterns = {}
    
    if len(state.risk_history) >= 2:
        patterns["risk_trend"] = analyze_trend(state.risk_history)
    else:
        patterns["risk_trend"] = "stable"
    
    if len(state.coherence_history) >= 2:
        patterns["coherence_trend"] = analyze_trend(state.coherence_history)
    else:
        patterns["coherence_trend"] = "stable"
    
    if len(state.E_history) >= 2:
        patterns["E_trend"] = analyze_trend(state.E_history)
    else:
        patterns["E_trend"] = "stable"
    
    # Overall trend
    if patterns.get("risk_trend") == "decreasing" and patterns.get("coherence_trend") == "increasing":
        patterns["trend"] = "improving"
    elif patterns.get("risk_trend") == "increasing" and patterns.get("coherence_trend") == "decreasing":
        patterns["trend"] = "degrading"
    else:
        patterns["trend"] = "stable"
    
    # Anomaly detection
    timestamps = state.timestamp_history if hasattr(state, 'timestamp_history') else []
    anomalies = detect_anomalies_in_history(
        state.risk_history,
        state.coherence_history,
        timestamps
    )
    
    # Summary statistics
    decision_history = getattr(state, 'decision_history', [])
    decision_counts = Counter(decision_history)
    
    summary = {
        "total_updates": state.update_count,
        "mean_risk": float(np.mean(state.risk_history)) if state.risk_history else 0.0,
        "mean_coherence": float(np.mean(state.coherence_history)) if state.coherence_history else 0.0,
        "decision_distribution": {
            "approve": decision_counts.get("approve", 0),
            "revise": decision_counts.get("revise", 0),
            "reject": decision_counts.get("reject", 0)
        }
    }
    
    result = {
        "current_state": current_state,
        "patterns": patterns,
        "anomalies": anomalies,
        "summary": summary
    }
    
    if include_history and len(state.risk_history) > 0:
        # Include recent history (last 10 updates)
        recent_window = min(10, len(state.risk_history))
        result["recent_history"] = {
            "timestamps": timestamps[-recent_window:] if timestamps else [],
            "risk_history": [float(r) for r in state.risk_history[-recent_window:]],
            "coherence_history": [float(c) for c in state.coherence_history[-recent_window:]],
            "E_history": [float(e) for e in state.E_history[-recent_window:]],
            "I_history": [float(i) for i in state.I_history[-recent_window:]],
            "S_history": [float(s) for s in state.S_history[-recent_window:]],
            "V_history": [float(v) for v in state.V_history[-recent_window:]]
        }
    
    return result

