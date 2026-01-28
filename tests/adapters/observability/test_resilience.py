"""Tests for resilience utilities."""

from __future__ import annotations

import pytest
from oneiric.adapters.observability.resilience import with_retry


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_third_attempt():
    """Test retry decorator eventually succeeds."""
    attempt_count = 0

    @with_retry(max_attempts=3)
    async def flaky_function():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionError("Temporary failure")
        return "success"

    result = await flaky_function()
    assert result == "success"
    assert attempt_count == 3


@pytest.mark.asyncio
async def test_with_retry_fails_after_max_attempts():
    """Test retry decorator gives up after max attempts."""
    @with_retry(max_attempts=2)
    async def always_failing_function():
        raise ConnectionError("Always fails")

    with pytest.raises(ConnectionError):
        await always_failing_function()
