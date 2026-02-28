from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field, model_validator
from .mixins import AgentIdentityMixin

class IdentityParams(AgentIdentityMixin):
    """
    Who am I? Auto-creates identity if first call.
    """
    name: Optional[str] = Field(
        default=None,
        description="Optional display name to set"
    )
    model_type: Optional[str] = Field(
        default=None,
        description="Optional model type for distinct identity"
    )
    resume: Union[bool, str, None] = Field(
        default=False,
        description="Explicitly resume existing identity"
    )
    force_new: Union[bool, str, None] = Field(
        default=False,
        description="Force new identity creation"
    )

    @model_validator(mode='after')
    def coerce_booleans(self):
        if isinstance(self.resume, str):
            self.resume = self.resume.lower() in ('true', '1', 'yes')
        if isinstance(self.force_new, str):
            self.force_new = self.force_new.lower() in ('true', '1', 'yes')
        return self


class OnboardParams(AgentIdentityMixin):
    """
    Single entry point for new agents
    """
    name: Optional[str] = Field(
        default=None,
        description="Optional display name to set"
    )
    model_type: Optional[str] = Field(
        default=None,
        description="Optional model type"
    )
    client_hint: Optional[str] = Field(
        default=None,
        description="Client hint string"
    )
    resume: Union[bool, str, None] = Field(
        default=False,
        description="Explicitly resume existing identity"
    )
    force_new: Union[bool, str, None] = Field(
        default=False,
        description="Force new identity creation"
    )
    trajectory_signature: Optional[dict] = Field(
        default=None,
        description="Trajectory signature dict"
    )

    @model_validator(mode='after')
    def coerce_booleans(self):
        if isinstance(self.resume, str):
            self.resume = self.resume.lower() in ('true', '1', 'yes')
        if isinstance(self.force_new, str):
            self.force_new = self.force_new.lower() in ('true', '1', 'yes')
        return self

class LinkIdentityTrajectoryParams(AgentIdentityMixin):
    """
    Link multiple identities via behavioral trajectory
    """
    target_uuid: str = Field(
        ..., description="UUID of identity to link to"
    )
    behavioral_signature: dict = Field(
        ..., description="Behavioral signature dict for verification"
    )

class GetAgentApiKeyParams(AgentIdentityMixin):
    """
    Alias/stub for identity()
    """
    pass

class SyncMemoryContextParams(AgentIdentityMixin):
    """
    Sync memory context
    """
    memory_summary: dict = Field(..., description="Summary of current memory bindings")

class GetTrajectoryStatusParams(AgentIdentityMixin):
    """Parameters for get_trajectory_status"""


class VerifyTrajectoryIdentityParams(AgentIdentityMixin):
    """Parameters for verify_trajectory_identity"""

