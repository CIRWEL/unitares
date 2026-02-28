from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field, model_validator
from .mixins import AgentIdentityMixin

class ObserveAgentParams(AgentIdentityMixin):
    """
    Observe another agent's governance state with pattern analysis
    """
    target_agent: str = Field(..., description="UUID or label of agent to observe")

class CompareAgentsParams(AgentIdentityMixin):
    """
    Compare governance patterns across multiple agents
    """
    agent_ids: List[str] = Field(..., description="List of UUIDs or labels of agents to compare")

class CompareMeToSimilarParams(AgentIdentityMixin):
    """
    Compare yourself to similar agents automatically
    """
    agent_id: Optional[str] = Field(default=None, description="Your UUID or label (auto-detected if bound)")
    max_peers: Union[int, str, None] = Field(default=3, description="Maximum number of peers to compare against")
    focus: Literal["all", "ethics", "stability", "complexity", "knowledge"] = Field(
        default="all", 
        description="Focus area for comparison"
    )

    @model_validator(mode='after')
    def coerce_types(self):
        if isinstance(self.max_peers, str):
            try:
                self.max_peers = int(self.max_peers)
            except ValueError:
                self.max_peers = 3
        return self

class DetectAnomaliesParams(AgentIdentityMixin):
    """
    Detect anomalies across agents
    """
    focus: Literal["all", "drift", "complexity", "void", "coherence"] = Field(
        default="all",
        description="Type of anomaly to focus on"
    )

class AggregateMetricsParams(AgentIdentityMixin):
    """
    Get fleet-level health overview
    """
    group_by: Literal["none", "label_prefix", "status"] = Field(
        default="none",
        description="How to group the metrics"
    )

class ObserveParams(AgentIdentityMixin):
    """Parameters for observe"""
    action: Literal["agent", "compare", "similar", "anomalies", "aggregate"] = Field(..., description="Operation to perform")
    target_agent_id: Optional[str] = Field(None, description="Agent to observe — UUID or label (for action=agent). Use list_agents to find.")
    agent_ids: Optional[List[Any]] = Field(None, description="Agent identifiers to compare (for action=compare, min 2)")
    include_history: bool = Field(True, description="Include recent history (for action=agent). Default true.")
    analyze_patterns: bool = Field(True, description="Perform pattern analysis (for action=agent). Default true.")
    compare_metrics: Optional[List[Any]] = Field(None, description="Metrics to compare (for action=compare). Default: risk_score, coherence, E, I, S, V")
    limit: Optional[int] = Field(None, description="Max results to return (for action=similar, anomalies)")


