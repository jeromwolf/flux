"""Tests for flux.core.resilience — retry logic and timeout utilities."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from flux.core.resilience import (
    _TimeoutError,
    _is_retryable,
    retry_llm_call,
    with_timeout,
)


# ---------------------------------------------------------------------------
# retry_llm_call
# ---------------------------------------------------------------------------

def test_retry_llm_call_success():
    """Function that succeeds on first try returns the correct value."""
    fn = MagicMock(return_value="ok")
    result = retry_llm_call(fn, max_retries=3, base_delay=0.0)
    assert result == "ok"
    assert fn.call_count == 1


def test_retry_llm_call_retries():
    """Function that raises a retryable error twice then succeeds is called 3 times."""

    class FakeRateLimitError(Exception):
        status_code = 429

    fn = MagicMock(
        side_effect=[FakeRateLimitError("rate limit"), FakeRateLimitError("rate limit"), "done"]
    )
    result = retry_llm_call(fn, max_retries=3, base_delay=0.0)
    assert result == "done"
    assert fn.call_count == 3


def test_retry_llm_call_non_retryable():
    """Non-retryable error (e.g. 400) raises immediately without retrying."""

    class FakeBadRequestError(Exception):
        status_code = 400

    fn = MagicMock(side_effect=FakeBadRequestError("bad request"))
    with pytest.raises(FakeBadRequestError):
        retry_llm_call(fn, max_retries=3, base_delay=0.0)
    assert fn.call_count == 1


def test_retry_llm_call_max_retries():
    """When all retries are exhausted the last exception is re-raised."""

    class FakeServerError(Exception):
        status_code = 500

    fn = MagicMock(side_effect=FakeServerError("server error"))
    with pytest.raises(FakeServerError):
        retry_llm_call(fn, max_retries=2, base_delay=0.0)
    # 1 initial attempt + 2 retries = 3 total calls
    assert fn.call_count == 3


# ---------------------------------------------------------------------------
# with_timeout
# ---------------------------------------------------------------------------

def test_with_timeout_success():
    """Function that finishes quickly returns its result."""

    def fast_fn(x):
        return x * 2

    result = with_timeout(fast_fn, timeout_seconds=5.0, x=21)
    assert result == 42


def test_with_timeout_exceeds():
    """Function that sleeps longer than the timeout raises _TimeoutError."""

    def slow_fn():
        time.sleep(5.0)
        return "never"

    with pytest.raises(_TimeoutError):
        with_timeout(slow_fn, timeout_seconds=0.1)


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------

def test_is_retryable_429():
    """HTTP 429 (rate limit) should be retryable."""

    class FakeError(Exception):
        status_code = 429

    assert _is_retryable(FakeError()) is True


def test_is_retryable_400():
    """HTTP 400 (bad request) should NOT be retryable."""

    class FakeError(Exception):
        status_code = 400

    assert _is_retryable(FakeError()) is False
