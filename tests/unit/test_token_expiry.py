"""Unit tests for the shared token-expiry status helpers."""

from __future__ import annotations

import pytest

from custom_components.saxo_portfolio.token_expiry import (
    token_expiry_status,
    token_seconds_remaining,
)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (-1, "expired"),
        (0, "expired"),
        (0.001, "critical"),
        (60, "critical"),
        (60.001, "warning"),
        (300, "warning"),
        (300.001, "valid"),
        (3600, "valid"),
    ],
)
def test_status_boundaries(seconds: float, expected: str) -> None:
    """Status flips at 0, 60 and 300 seconds, upper bound inclusive."""
    assert token_expiry_status(seconds) == expected


def test_seconds_remaining() -> None:
    """Remaining time is expires_at minus now."""
    assert token_seconds_remaining({"expires_at": 1500.0}, now=1000.0) == 500.0


@pytest.mark.parametrize("token_data", [None, {}, {"access_token": "x"}])
def test_seconds_remaining_without_expiry(token_data: dict | None) -> None:
    """Missing token or expires_at yields None."""
    assert token_seconds_remaining(token_data, now=0.0) is None
