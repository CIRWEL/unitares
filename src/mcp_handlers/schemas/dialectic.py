from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field, model_validator
from .mixins import AgentIdentityMixin

class RequestDialecticReviewParams(AgentIdentityMixin):
    """
    Create a dialectic recovery session
    """
    issue_description: str = Field(
        ..., description="Description of the issue or current state"
    )

class GetDialecticSessionParams(AgentIdentityMixin):
    """
    View historical dialectic sessions
    """
    session_id: Optional[str] = Field(
        default=None,
        description="ID of specific session to retrieve"
    )

class ListDialecticSessionsParams(AgentIdentityMixin):
    """
    List all dialectic sessions with optional filtering
    """
    agent_id: Optional[str] = Field(
        default=None,
        description="Filter by agent UUID/label (paused or reviewer)"
    )
    status: Optional[str] = Field(
        default=None,
        description="Filter by status (active, converged, failed, canceled)"
    )
    limit: Union[int, str, None] = Field(
        default=10,
        description="Max results"
    )
    include_transcript: Union[bool, str, None] = Field(
        default=False,
        description="Include full transcript"
    )

    @model_validator(mode='after')
    def coerce_types(self):
        if isinstance(self.limit, str):
            try:
                self.limit = int(self.limit)
            except ValueError:
                self.limit = 10
        if isinstance(self.include_transcript, str):
            self.include_transcript = self.include_transcript.lower() in ('true', '1', 'yes')
        return self

class SubmitThesisParams(AgentIdentityMixin):
    """
    Paused agent submits thesis
    """
    session_id: str = Field(..., description="Dialectic session ID")
    root_cause: str = Field(..., description="Agent's understanding of root cause")
    proposed_conditions: List[str] = Field(..., description="List of conditions for resumption")
    reasoning: Optional[str] = Field(default=None, description="Natural language explanation")

class SubmitAntithesisParams(AgentIdentityMixin):
    """
    Reviewer agent submits antithesis
    """
    session_id: str = Field(..., description="Dialectic session ID")
    observed_metrics: dict = Field(..., description="Metrics observed about paused agent")
    concerns: List[str] = Field(..., description="List of concerns")
    reasoning: Optional[str] = Field(default=None, description="Natural language explanation")

class SubmitSynthesisParams(AgentIdentityMixin):
    """
    Either agent submits synthesis proposal
    """
    session_id: str = Field(..., description="Dialectic session ID")
    proposed_conditions: List[str] = Field(..., description="Proposed resumption conditions")
    reasoning: Optional[str] = Field(default=None, description="Natural language explanation")
    agrees: Union[bool, str, None] = Field(default=None, description="Whether this agent agrees with current proposal")
    
    @model_validator(mode='after')
    def coerce_types(self):
        if isinstance(self.agrees, str):
            self.agrees = self.agrees.lower() in ('true', '1', 'yes')
        return self

class LlmAssistedDialecticParams(AgentIdentityMixin):
    """
    Run LLM-assisted dialectic recovery
    """
    root_cause: str = Field(..., description="Your understanding of what caused the issue")
    proposed_conditions: List[str] = Field(..., description="Your proposed conditions for resumption")
    reasoning: Optional[str] = Field(default=None, description="Your explanation/reasoning")

class DialecticParams(AgentIdentityMixin):
    """Parameters for dialectic"""
    action: Literal["get", "list"] = Field(..., description="Operation to perform (default: list)")
    session_id: Optional[str] = Field(None, description="Dialectic session ID (for action=get)")
    agent_id: Optional[str] = Field(None, description="Filter by agent (for action=get or list)")
    status: Optional[str] = Field(None, description="Filter by phase: thesis, antithesis, synthesis, resolved, escalated, failed (for action=list)")
    limit: Optional[int] = Field(None, description="Max sessions to return (for action=list, default 50)")
    include_transcript: Optional[bool] = Field(None, description="Include full transcript (for action=list, default false)")


