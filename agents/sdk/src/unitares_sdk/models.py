"""Pydantic response models for governance tool results."""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class _GovModel(BaseModel):
    """Base model with extra="ignore" so unknown server fields don't break parsing."""

    model_config = ConfigDict(extra="ignore")


class OnboardResult(_GovModel):
    success: bool
    client_session_id: str
    uuid: str | None = None
    continuity_token: str | None = None
    continuity_token_supported: bool = False
    is_new: bool = False
    verdict: str = "proceed"
    guidance: str | None = None
    session_resolution_source: str | None = None
    welcome: str | None = None


class IdentityResult(_GovModel):
    client_session_id: str
    uuid: str
    continuity_token: str | None = None
    resolution_source: str | None = Field(
        default=None,
        validation_alias=AliasChoices("resolution_source", "session_resolution_source"),
    )


class CheckinResult(_GovModel):
    success: bool
    verdict: str  # proceed/guide/pause/reject
    guidance: str | None = None
    margin: str | None = None
    coherence: float | None = None
    risk: float | None = None
    metrics: dict | None = None


class NoteResult(_GovModel):
    success: bool
    discovery_id: str | None = None


class SearchResult(_GovModel):
    success: bool = True
    error: str | None = None
    results: list[dict] = Field(default_factory=list)


class AuditResult(_GovModel):
    success: bool
    results: list[dict] = Field(default_factory=list)


class CleanupResult(_GovModel):
    success: bool
    cleaned: int = 0


class ArchiveResult(_GovModel):
    success: bool
    archived: int = 0


class RecoveryResult(_GovModel):
    success: bool
    action_taken: str | None = None


class MetricsResult(_GovModel):
    success: bool
    metrics: dict = Field(default_factory=dict)


class ModelResult(_GovModel):
    success: bool
    response: str | None = None
