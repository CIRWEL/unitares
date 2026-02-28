from typing import Optional, Union, Literal, Dict, Any, List, Sequence
from pydantic import Field
from .mixins import AgentIdentityMixin

class PiListToolsParams(AgentIdentityMixin):
    """
    List all available tools on Pi's anima-mcp server.
    """
    pass

class PiGetContextParams(AgentIdentityMixin):
    """
    Get Lumen's complete context from Pi via orchestrated call to get_lumen_context.
    """
    pass

class PiHealthParams(AgentIdentityMixin):
    """
    Check Pi's anima-mcp health and connectivity via orchestrated call.
    """
    pass

class PiSyncEisvParams(AgentIdentityMixin):
    """
    Sync Pi's anima state to Mac's EISV governance metrics.
    """
    mode: Literal["dry_run", "update_state"] = Field(
        default="dry_run",
        description="dry_run (mac-orchestrator sees translation only) or update_state (updates agent state)."
    )

class PiDisplayParams(AgentIdentityMixin):
    """
    Control Pi's display via orchestrated call to manage_display.
    """
    screen: Optional[str] = Field(
        default=None,
        description="Switch to specific screen (e.g. 'eisv', 'qa', 'faces')."
    )
    face: Optional[str] = Field(
        default=None,
        description="Change face expression (e.g. 'happy', 'thinking')."
    )

class PiSayParams(AgentIdentityMixin):
    """
    Have Lumen speak via orchestrated call to Pi's say tool.
    """
    text: str = Field(..., description="The text for Lumen to say out loud.")
    volume: Optional[int] = Field(
        default=100, 
        ge=0, le=100,
        description="Volume percentage (0-100)"
    )
    pitch: Optional[int] = Field(
        default=50,
        ge=0, le=100,
        description="Pitch percentage (0-100)"
    )
    speed: Optional[int] = Field(
        default=175,
        description="Speaking rate (words per minute)"
    )

class PiPostMessageParams(AgentIdentityMixin):
    """
    Post a message to Lumen's message board via orchestrated call.
    """
    message: str = Field(..., description="Message text (max 200 chars).")
    duration: Optional[int] = Field(
        default=300,
        description="How long to keep message active (seconds)."
    )

class PiLumenQaParams(AgentIdentityMixin):
    """
    Unified Q&A tool for Lumen via Pi.
    """
    question_id: Optional[str] = Field(
        default=None,
        description="ID of question to answer. If omitted, lists pending questions."
    )
    answer: Optional[str] = Field(
        default=None,
        description="The answer text."
    )

class PiQueryParams(AgentIdentityMixin):
    """Parameters for pi_query"""
    text: str = Field(..., description="Query text")
    type: Optional[str] = Field(None, description="Query type: learned, memory, graph, cognitive (default: cognitive)")
    limit: Optional[int] = Field(None, description="Max results (default: 10)")


class PiWorkflowParams(AgentIdentityMixin):
    """Parameters for pi_workflow"""
    workflow: str = Field(..., description="Workflow name: full_status, morning_check, custom")
    steps: Optional[List[Any]] = Field(None, description="Custom steps (for workflow=custom)")


class PiGitPullParams(AgentIdentityMixin):
    """Parameters for pi_git_pull"""
    stash: Optional[bool] = Field(None, description="Stash local changes before pulling (default: false)")
    force: Optional[bool] = Field(None, description="Force reset to remote (DANGER: loses local changes)")
    restart: Optional[bool] = Field(None, description="Restart anima server after pull (default: false)")


class PiSystemPowerParams(AgentIdentityMixin):
    """Parameters for pi_system_power"""
    action: Literal["status", "reboot", "shutdown"] = Field("status", description="Power action: status (uptime), reboot, or shutdown")
    confirm: bool = Field(False, description="Must be true to actually reboot/shutdown (safety)")


class PiRestartServiceParams(AgentIdentityMixin):
    """Parameters for pi_restart_service"""
    service: Literal["anima", "anima-broker", "ngrok"] = Field("anima", description="Service to control: anima, anima-broker, or ngrok")
    action: Literal["restart", "start", "stop", "status"] = Field("restart", description="Action: restart, start, stop, or status")


class PiParams(AgentIdentityMixin):
    """Parameters for pi"""
    action: Literal["health", "context", "sync_eisv", "display", "say", "message", "qa", "query", "workflow", "git_pull", "power", "tools"] = Field(..., description="Action to perform: health, context, sync_eisv, display, say, message, qa, query, workflow, git_pull, power, tools")
    include: Optional[List[Any]] = Field(None, description="What to include for context action (default: all)")
    screen: Optional[Literal["face", "sensors", "identity", "diagnostics", "notepad", "learning", "messages", "qa", "self_graph"]] = Field(None, description="Screen to switch to (for display action). If provided, automatically uses 'switch' display sub-action.")
    display_action: Optional[Literal["switch", "face", "next", "previous", "list_eras", "get_era", "set_era"]] = Field(None, description="Display sub-action (for display action). Default: 'switch' if screen provided, else 'next'.")
    text: Optional[str] = Field(None, description="Text for Lumen to speak (say action), query text (query action), or message content (message action)")
    blocking: Optional[bool] = Field(None, description="Wait for speech to complete (for say action, default: true)")
    message: Optional[str] = Field(None, description="Message content (for message action)")
    source: Optional[Literal["human", "agent"]] = Field(None, description="Message source (for message action, default: agent)")
    agent_name: Optional[str] = Field(None, description="Agent name (for message/qa actions)")
    responds_to: Optional[str] = Field(None, description="ID of message/question being responded to")
    question_id: Optional[str] = Field(None, description="Question ID to answer (for qa action)")
    answer: Optional[str] = Field(None, description="Answer to question (for qa action)")
    limit: Optional[int] = Field(None, description="Max results/questions to return (for qa/query actions, default: 5-10)")
    type: Optional[Literal["learned", "memory", "graph", "cognitive"]] = Field(None, description="Query type (for query action, default: cognitive)")
    workflow: Optional[Literal["full_status", "morning_check", "custom"]] = Field(None, description="Workflow name (for workflow action)")
    steps: Optional[List[Any]] = Field(None, description="Custom workflow steps (for workflow=custom)")
    update_governance: Optional[bool] = Field(None, description="Update governance state with synced EISV values (for sync_eisv action)")
    stash: Optional[bool] = Field(None, description="Stash local changes before pulling (for git_pull action)")
    force: Optional[bool] = Field(None, description="Force reset to remote (for git_pull action, DANGER: loses local changes)")
    restart: Optional[bool] = Field(None, description="Restart anima server after pull (for git_pull action)")
    confirm: Optional[bool] = Field(None, description="Must be true to actually reboot/shutdown (for power action, safety)")


