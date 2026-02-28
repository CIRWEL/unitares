from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import BaseModel, Field

class AgentIdentityMixin(BaseModel):
    """Common parameters for tools that require agent orchestration."""
    client_session_id: Optional[str] = Field(
        default=None,
        description="Session continuity token from identity(). Include in all calls to maintain identity."
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="UNIQUE agent identifier. Optional if session-bound (auto-injected)."
    )
