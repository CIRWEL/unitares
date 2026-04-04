from unittest.mock import patch
import pytest


def test_identity_continuity_status_reports_redis_mode():
    from src.services.identity_continuity import get_identity_continuity_status

    with patch("src.cache.is_redis_available", return_value=True):
        status = get_identity_continuity_status()

    assert status["mode"] == "redis"
    assert status["redis_present"] is True
    assert status["status"] == "healthy"


def test_identity_continuity_status_reports_degraded_local_mode():
    from src.services.identity_continuity import get_identity_continuity_status

    with patch("src.cache.is_redis_available", return_value=False):
        status = get_identity_continuity_status()

    assert status["mode"] == "degraded-local"
    assert status["redis_present"] is False
    assert status["status"] == "healthy"


def test_identity_continuity_startup_message_mentions_mode_and_redis_presence():
    from src.services.identity_continuity import format_identity_continuity_startup_message

    message = format_identity_continuity_startup_message(
        {
            "mode": "degraded-local",
            "redis_present": False,
        }
    )

    assert "degraded-local" in message
    assert "Redis absent" in message


@pytest.mark.asyncio
async def test_probe_identity_continuity_status_degrades_when_redis_probe_fails():
    from src.services.identity_continuity import probe_identity_continuity_status

    with patch("src.cache.is_redis_available", return_value=True), \
         patch("src.cache.get_redis", return_value=None):
        status = await probe_identity_continuity_status()

    assert status["mode"] == "degraded-local"
    assert status["redis_present"] is False
    assert status["configured_but_unavailable"] is True
