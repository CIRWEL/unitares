from pydantic import BaseModel, Field


class DashboardParams(BaseModel):
    """Read-only system overview: all agents with EISV state."""
    recent_days: int = Field(default=1, description="Only show agents active within this many days (0=all)")
    min_updates: int = Field(default=1, description="Minimum check-in count to include")
