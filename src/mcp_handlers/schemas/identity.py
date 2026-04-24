from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field, model_validator
from .mixins import AgentIdentityMixin

class IdentityParams(AgentIdentityMixin):
    """
    Who am I? Auto-creates identity if first call.
    """
    agent_uuid: Optional[str] = Field(
        default=None,
        description="Resume a known identity by UUID directly. Skips session/name resolution. Returns error if not found."
    )
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
        default=True,
        description=(
            "Resume existing identity (default True — onboard is a "
            "resume-preferred entry point). Pass resume=false for a new "
            "identity with predecessor link, or force_new=true for a clean break."
        )
    )
    force_new: Union[bool, str, None] = Field(
        default=False,
        description="Force new identity creation"
    )
    trajectory_signature: Optional[dict] = Field(
        default=None,
        description="Trajectory signature dict"
    )
    # Thread identity (honest forking)
    parent_agent_id: Optional[str] = Field(
        default=None,
        description="UUID of predecessor agent (for fork lineage)"
    )
    spawn_reason: Optional[str] = Field(
        default=None,
        description="Why this fork was created: compaction, subagent, new_session, explicit"
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Explicit thread ID to join (auto-derived from session if not provided)"
    )
    # Concurrent identity binding invariant (issue #123).
    # Client-reported execution context — used to detect same-UUID siphoning
    # when two processes on the same host claim the same UUID. Audit-only in
    # v1; see issue #123 for the detection rule and policy flags.
    process_fingerprint: Optional[dict] = Field(
        default=None,
        description=(
            "Optional client-reported execution context: "
            "{host_id, pid, pid_start_time, transport, ppid?, tty?, "
            "anchor_path_hash?}. Recorded server-side; used to detect "
            "concurrent identity bindings. Declaration-only — never used "
            "to resolve or recover identity."
        )
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


class BindSessionParams(AgentIdentityMixin):
    """Bind current MCP session to an existing agent identity via client_session_id."""
    resume: Union[bool, str, None] = Field(
        default=False,
        description="Must be true to explicitly reattach to a prior identity (unless strict mode is used)."
    )
    strict: Union[bool, str, None] = Field(
        default=False,
        description="If true, require explicit agent_id and reject mismatched binding."
    )

    @model_validator(mode='after')
    def coerce_booleans(self):
        if isinstance(self.resume, str):
            self.resume = self.resume.lower() in ('true', '1', 'yes')
        if isinstance(self.strict, str):
            self.strict = self.strict.lower() in ('true', '1', 'yes')
        return self

