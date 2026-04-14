"""SDK exception hierarchy."""


class GovernanceError(Exception):
    """Base exception for all SDK errors."""


class GovernanceConnectionError(GovernanceError):
    """Cannot reach governance server."""


class GovernanceTimeoutError(GovernanceError):
    """MCP call exceeded timeout (likely anyio deadlock)."""


class IdentityDriftError(GovernanceError):
    """Agent UUID changed unexpectedly during session."""

    def __init__(self, expected_uuid: str, received_uuid: str, message: str = ""):
        self.expected_uuid = expected_uuid
        self.received_uuid = received_uuid
        super().__init__(
            message
            or f"Identity drift: expected {expected_uuid[:12]}... got {received_uuid[:12]}..."
        )


class VerdictError(GovernanceError):
    """Governance issued a pause or reject verdict."""

    def __init__(self, verdict: str, guidance: str | None = None):
        self.verdict = verdict
        self.guidance = guidance
        msg = f"Governance verdict: {verdict}"
        if guidance:
            msg += f" — {guidance}"
        super().__init__(msg)
