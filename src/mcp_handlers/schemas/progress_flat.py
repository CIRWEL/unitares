"""Pydantic schema for the record_progress_pulse MCP tool."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class RecordProgressPulseParams(BaseModel):
    """Parameters for the record_progress_pulse tool."""

    metric_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Metric identifier. Alphanumeric characters plus '._-' only."
        ),
    )
    value: int = Field(
        ...,
        ge=0,
        description="Non-negative integer metric value.",
    )
    resident_uuid: str | None = Field(
        default=None,
        description=(
            "UUID of the resident posting the pulse. If provided, MUST match "
            "the authenticated agent's bound UUID."
        ),
    )

    @field_validator("metric_name")
    @classmethod
    def metric_name_chars(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", v):
            raise ValueError(
                "metric_name must contain only alphanumeric characters, "
                "dots, underscores, or hyphens"
            )
        return v
