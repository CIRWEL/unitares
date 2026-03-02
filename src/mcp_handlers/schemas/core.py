from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field, model_validator
from .mixins import AgentIdentityMixin


class GetGovernanceMetricsParams(AgentIdentityMixin):
    """
    Get current governance state and metrics for an agent without updating state.
    """
    include_state: Union[bool, str, None] = Field(
        default=False,
        description="Include nested state dict in response (can be large). Default false to reduce context bloat. Accepts boolean or string ('true'/'false')."
    )
    lite: Union[bool, str, None] = Field(
        default=True,
        description="If true (default), returns minimal essential metrics only. Set lite=false for full diagnostic data."
    )

    @model_validator(mode='after')
    def coerce_booleans(self):
        if isinstance(self.include_state, str):
            self.include_state = self.include_state.lower() in ('true', '1', 'yes')
        if isinstance(self.lite, str):
            self.lite = self.lite.lower() in ('true', '1', 'yes')
        return self


class SimulateUpdateParams(AgentIdentityMixin):
    """
    Dry-run governance cycle without persisting state.
    """
    parameters: List[float] = Field(
        default_factory=list,
        description="Agent parameters vector (optional)."
    )
    ethical_drift: List[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="Ethical drift signals (3 components)."
    )
    response_text: Optional[str] = Field(
        default="",
        description="Agent's response text (optional)."
    )
    complexity: Union[float, str, None] = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Estimated task complexity (0-1)."
    )
    confidence: Union[float, str, None] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence level for this update (0-1)."
    )
    lite: Union[bool, str, None] = Field(
        default=False,
        description="If true, returns minimalist output."
    )

    @model_validator(mode='after')
    def coerce_types(self):
        if isinstance(self.complexity, str):
            try:
                self.complexity = float(self.complexity)
            except ValueError:
                self.complexity = 0.5
        if isinstance(self.confidence, str):
            try:
                self.confidence = float(self.confidence)
            except ValueError:
                self.confidence = None
        if isinstance(self.lite, str):
            self.lite = self.lite.lower() in ('true', '1', 'yes')
        return self


class ProcessAgentUpdateParams(AgentIdentityMixin):
    """
    Share your work and get supportive feedback. Your main tool for checking in.
    """
    parameters: List[float] = Field(
        default_factory=list,
        description="Agent parameters vector (optional, deprecated)."
    )
    ethical_drift: List[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="Ethical drift signals (3 components): [primary_drift, coherence_loss, complexity_contribution]"
    )
    response_text: Optional[str] = Field(
        default=None,
        description="Agent's response text (optional, for analysis)"
    )
    complexity: Union[float, str, None] = Field(
        default=0.5,
        ge=0.0, 
        le=1.0,
        description="Estimated task complexity (0-1, optional)."
    )
    confidence: Union[float, str, None] = Field(
        default=None,
        ge=0.0, 
        le=1.0,
        description="Confidence level for this update (0-1, optional)."
    )
    response_mode: Literal["minimal", "compact", "standard", "full", "auto"] = Field(
        default="auto",
        description="Response verbosity mode. 'compact' or 'minimal' returns a smaller payload."
    )
    lite: Union[bool, str, None] = Field(
        default=None,
        description="If true, returns minimal response. Alias for response_mode='minimal'."
    )
    auto_export_on_significance: bool = Field(
        default=False,
        description="If true, automatically export governance history when thermodynamically significant events occur."
    )
    task_type: Literal[
        "convergent", "divergent", "mixed", "refactoring", "bugfix", "testing",
        "documentation", "feature", "exploration", "research", "design", "debugging",
        "review", "deployment", "introspection"
    ] = Field(
        default="mixed",
        description="Task type context. Core types: convergent | divergent | mixed. Use 'introspection' for epistemic self-examination where low confidence is appropriate."
    )
    trajectory_signature: Optional[dict] = Field(
        default=None,
        description="Trajectory identity signature from anima-mcp."
    )
    agent_name: Optional[str] = Field(
        default=None,
        description="Your display name for identity reconnection."
    )

    @model_validator(mode='after')
    def coerce_types(self):
        if isinstance(self.complexity, str):
            try:
                self.complexity = float(self.complexity)
            except ValueError:
                self.complexity = 0.5
        if isinstance(self.confidence, str):
            try:
                self.confidence = float(self.confidence)
            except ValueError:
                self.confidence = None
        if isinstance(self.lite, str):
            val = str(self.lite).lower() in ('true', '1', 'yes')
            if val and self.response_mode == "auto":
                self.response_mode = "minimal"
        return self

class OutcomeEventParams(AgentIdentityMixin):
    """Parameters for outcome_event"""
    outcome_type: Literal["drawing_completed", "drawing_abandoned", "test_passed", "test_failed", "tool_rejected", "task_completed", "task_failed"] = Field(..., description="Type of outcome event")
    outcome_score: Optional[float] = Field(None, description="Quality score 0.0 (worst) to 1.0 (best). Inferred from type if omitted.")
    is_bad: Optional[bool] = Field(None, description="Whether this is a negative outcome. Inferred from type if omitted.")
    detail: Optional[Dict[str, Any]] = Field(None, description="Type-specific metadata (e.g., mark_count, test_name, error_message)")
    agent_id: Optional[str] = Field(None, description="Agent ID. Falls back to session-bound agent_id if omitted.")


class CirsProtocolParams(AgentIdentityMixin):
    """Parameters for cirs_protocol"""
    protocol: Literal["void_alert", "state_announce", "coherence_report", "boundary_contract", "governance_action"] = Field(..., description="Which CIRS protocol to use")
    action: Optional[str] = Field(None, description="Action within the protocol (emit/query/compute/set/get/initiate/respond)")
    target_agent_id: Optional[str] = Field(None, description="Target agent (for coherence_report)")
    severity: Optional[Literal["warning", "critical"]] = Field(None, description="Alert severity (for void_alert)")
    limit: Optional[int] = Field(None, description="Max results for queries")


class ValidateFilePathParams(AgentIdentityMixin):
    """Parameters for validate_file_path"""
    file_path: str = Field(..., description="File path to validate against project policies")


class GetWorkspaceHealthParams(AgentIdentityMixin):
    """Parameters for get_workspace_health"""
    pass


class CallModelParams(AgentIdentityMixin):
    """Parameters for call_model"""
    prompt: str = Field(..., description="The prompt/question to send to the model (required)")
    model: str = Field("auto", description="Model to use. Options: auto (HF default), deepseek-ai/DeepSeek-R1 (HF, free), gemini-flash (Google, free), llama-3.1-8b (Ollama, local). Default: auto")
    provider: Literal["auto", "hf", "gemini", "ollama"] = Field("auto", description="Provider to use. Options: auto (HF first), hf (Hugging Face), gemini (Google), ollama (local). Default: auto")
    task_type: Literal["reasoning", "generation", "analysis"] = Field("reasoning", description="Type of task. Options: reasoning, generation, analysis. Default: reasoning")
    max_tokens: float = Field(500, description="Maximum tokens in response. Default: 500")
    temperature: float = Field(0.7, description="Temperature (creativity). Range: 0.0-1.0. Default: 0.7")
    privacy: Literal["local", "auto", "cloud"] = Field("local", description="Privacy mode. Options: local (Ollama, default), auto (system chooses), cloud (external providers)")


