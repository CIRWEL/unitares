from typing import Optional

from pydantic import BaseModel, Field


class DashboardParams(BaseModel):
    """Read-only system overview: all agents with EISV state."""
    recent_days: int = Field(default=1, description="Only show agents active within this many days (0=all)")
    min_updates: int = Field(default=1, description="Minimum check-in count to include")
    limit: int = Field(default=15, ge=1, le=100, description="Maximum number of agents to return")
    offset: int = Field(default=0, ge=0, description="Skip this many agents before returning results")
    basin_filter: Optional[str] = Field(default=None, description="Filter by regime/basin (e.g. 'nominal', 'critical')")
    risk_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Only show agents with risk >= this value")
