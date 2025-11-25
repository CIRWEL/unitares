"""
Observability tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import sys
from .utils import success_response, error_response, require_argument
from src.governance_monitor import UNITARESMonitor

# Import from mcp_server_std module
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    import src.mcp_server_std as mcp_server


async def handle_observe_agent(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle observe_agent tool"""
    agent_id, error = require_argument(arguments, "agent_id", "agent_id is required")
    if error:
        return [error]
    
    include_history = arguments.get("include_history", True)
    analyze_patterns_flag = arguments.get("analyze_patterns", True)
    
    # Try to get from loaded monitor first
    monitor = mcp_server.monitors.get(agent_id)
    if monitor is None:
        # Try to load from disk if not in memory
        persisted_state = mcp_server.load_monitor_state(agent_id)
        if persisted_state is None:
            return [error_response(
                f"Agent '{agent_id}' not found. No observation data available."
            )]
        # Create temporary monitor for analysis
        monitor = UNITARESMonitor(agent_id, load_state=False)
        monitor.state = persisted_state
    
    # Perform pattern analysis
    if analyze_patterns_flag:
        observation = mcp_server.analyze_agent_patterns(monitor, include_history=include_history)
    else:
        # Just return current state without analysis
        observation = {
            "current_state": {
                "E": float(monitor.state.E),
                "I": float(monitor.state.I),
                "S": float(monitor.state.S),
                "V": float(monitor.state.V),
                "coherence": float(monitor.state.coherence),
                "risk_score": float(monitor.state.risk_history[-1]) if monitor.state.risk_history else 0.0,
                "lambda1": float(monitor.state.lambda1),
                "update_count": monitor.state.update_count
            }
        }
    
    return success_response({
        "agent_id": agent_id,
        "observation": observation
    })


async def handle_compare_agents(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle compare_agents tool"""
    agent_ids = arguments.get("agent_ids", [])
    if not agent_ids or len(agent_ids) < 2:
        return [error_response("At least 2 agent_ids required for comparison")]
    
    compare_metrics = arguments.get("compare_metrics", ["risk_score", "coherence", "E", "I", "S"])
    
    # Get metrics for all agents
    agents_data = []
    for agent_id in agent_ids:
        monitor = mcp_server.monitors.get(agent_id)
        if monitor is None:
            persisted_state = mcp_server.load_monitor_state(agent_id)
            if persisted_state:
                monitor = UNITARESMonitor(agent_id, load_state=False)
                monitor.state = persisted_state
        
        if monitor:
            metrics = monitor.get_metrics()
            agents_data.append({
                "agent_id": agent_id,
                "risk_score": metrics.get("mean_risk", 0.0),
                "coherence": float(monitor.state.coherence),
                "E": float(monitor.state.E),
                "I": float(monitor.state.I),
                "S": float(monitor.state.S),
                "health_status": metrics.get("status", "unknown")
            })
    
    if len(agents_data) < 2:
        return [error_response(
            f"Could not load data for at least 2 agents. Loaded: {len(agents_data)}"
        )]
    
    # Import numpy for statistical operations
    import numpy as np
    
    # Compute similarities and differences
    similarities = []
    differences = []
    outliers = []
    
    # Compare each metric
    for metric in compare_metrics:
        values = [(a["agent_id"], a.get(metric, 0)) for a in agents_data if metric in a]
        if len(values) < 2:
            continue
        
        metric_values = [v[1] for v in values]
        mean_val = np.mean(metric_values)
        std_val = np.std(metric_values) if len(metric_values) > 1 else 0.0
        
        # Find similar pairs (within 1 std dev)
        for i, (id1, val1) in enumerate(values):
            for j, (id2, val2) in enumerate(values[i+1:], i+1):
                if abs(val1 - val2) < std_val * 0.5:  # Similar if within 0.5 std dev
                    similarities.append({
                        "agents": [id1, id2],
                        "metric": metric,
                        "similarity": 1.0 - abs(val1 - val2) / (mean_val + 0.001),
                        "description": f"Both show similar {metric} patterns"
                    })
        
        # Find outliers (beyond 2 std dev)
        for agent_id, val in values:
            if std_val > 0 and abs(val - mean_val) > 2 * std_val:
                outliers.append({
                    "agent_id": agent_id,
                    "metric": metric,
                    "value": float(val),
                    "mean": float(mean_val),
                    "reason": f"{metric} is {'above' if val > mean_val else 'below'} average"
                })
    
    return success_response({
        "comparison": {
            "agents": agents_data,
            "similarities": similarities[:10],  # Limit to top 10
            "differences": differences,
            "outliers": outliers
        }
    })


async def handle_detect_anomalies(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle detect_anomalies tool"""
    agent_ids = arguments.get("agent_ids")
    anomaly_types = arguments.get("anomaly_types", ["risk_spike", "coherence_drop"])
    min_severity = arguments.get("min_severity", "medium")
    
    severity_levels = {"low": 0, "medium": 1, "high": 2}
    min_severity_level = severity_levels.get(min_severity, 1)
    
    # Get agent list
    if not agent_ids:
        # Scan all agents
        agent_ids = list(mcp_server.agent_metadata.keys())
    
    all_anomalies = []
    
    for agent_id in agent_ids:
        monitor = mcp_server.monitors.get(agent_id)
        if monitor is None:
            persisted_state = mcp_server.load_monitor_state(agent_id)
            if persisted_state:
                monitor = UNITARESMonitor(agent_id, load_state=False)
                monitor.state = persisted_state
        
        if monitor:
            # Analyze patterns for this agent
            analysis = mcp_server.analyze_agent_patterns(monitor, include_history=False)
            
            # Filter anomalies by type and severity
            for anomaly in analysis.get("anomalies", []):
                if anomaly["type"] in anomaly_types:
                    anomaly_severity_level = severity_levels.get(anomaly.get("severity", "low"), 0)
                    if anomaly_severity_level >= min_severity_level:
                        anomaly["agent_id"] = agent_id
                        all_anomalies.append(anomaly)
    
    # Sort by severity (high first)
    all_anomalies.sort(key=lambda x: severity_levels.get(x.get("severity", "low"), 0), reverse=True)
    
    # Count by severity and type
    by_severity = {"high": 0, "medium": 0, "low": 0}
    by_type = {}
    for anomaly in all_anomalies:
        severity = anomaly.get("severity", "low")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        anomaly_type = anomaly.get("type", "unknown")
        by_type[anomaly_type] = by_type.get(anomaly_type, 0) + 1
    
    return success_response({
        "anomalies": all_anomalies,
        "summary": {
            "total_anomalies": len(all_anomalies),
            "by_severity": by_severity,
            "by_type": by_type
        }
    })


async def handle_aggregate_metrics(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle aggregate_metrics tool"""
    import numpy as np
    
    agent_ids = arguments.get("agent_ids")
    include_health_breakdown = arguments.get("include_health_breakdown", True)
    
    # Get agent list
    if not agent_ids:
        agent_ids = [aid for aid, meta in mcp_server.agent_metadata.items() if meta.status == "active"]
    
    # Aggregate metrics
    total_agents = len(agent_ids)
    agents_with_data = 0
    total_updates = 0
    risk_scores = []
    coherence_scores = []
    health_statuses = {"healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}
    decision_counts = {"approve": 0, "revise": 0, "reject": 0}
    
    for agent_id in agent_ids:
        monitor = mcp_server.monitors.get(agent_id)
        if monitor is None:
            persisted_state = mcp_server.load_monitor_state(agent_id)
            if persisted_state:
                monitor = UNITARESMonitor(agent_id, load_state=False)
                monitor.state = persisted_state
        
        if monitor:
            agents_with_data += 1
            metrics = monitor.get_metrics()
            
            # Aggregate risk and coherence
            if monitor.state.risk_history:
                risk_scores.extend(monitor.state.risk_history[-10:])  # Last 10 updates
            coherence_scores.append(float(monitor.state.coherence))
            
            # Aggregate health status
            status = metrics.get("status", "unknown")
            health_statuses[status] = health_statuses.get(status, 0) + 1
            
            # Aggregate decisions
            decision_stats = metrics.get("decision_statistics", {})
            decision_counts["approve"] += decision_stats.get("approve", 0)
            decision_counts["revise"] += decision_stats.get("revise", 0)
            decision_counts["reject"] += decision_stats.get("reject", 0)
            
            # Count total updates
            total_updates += monitor.state.update_count
    
    # Compute aggregate statistics
    aggregate_data = {
        "total_agents": total_agents,
        "agents_with_data": agents_with_data,
        "total_updates": total_updates,
        "mean_risk": float(np.mean(risk_scores)) if risk_scores else 0.0,
        "mean_coherence": float(np.mean(coherence_scores)) if coherence_scores else 0.0,
        "decision_distribution": {
            **decision_counts,
            "total": sum(decision_counts.values())
        }
    }
    
    if include_health_breakdown:
        aggregate_data["health_breakdown"] = health_statuses
    
    return success_response({"aggregate": aggregate_data})
