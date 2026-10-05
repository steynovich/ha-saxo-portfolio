"""Token-expiry status shared by the Token Expiry sensor and diagnostics."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

TOKEN_EXPIRY_CRITICAL_SECONDS: Final = 60
TOKEN_EXPIRY_WARNING_SECONDS: Final = 300


class TokenExpiryStatus(StrEnum):
    """Token Expiry sensor states (values are the translation state keys)."""

    VALID = "valid"
    WARNING = "warning"
    CRITICAL = "critical"
    EXPIRED = "expired"


TOKEN_EXPIRY_STATES: Final = [status.value for status in TokenExpiryStatus]


def token_seconds_remaining(
    token_data: dict[str, Any] | None, now: float
) -> float | None:
    """Return seconds until the access token expires at ``now``, None if unknown."""
    if not token_data or "expires_at" not in token_data:
        return None
    remaining: float = token_data["expires_at"] - now
    return remaining


def token_expiry_status(seconds_remaining: float) -> TokenExpiryStatus:
    """Classify remaining token lifetime as expired/critical/warning/valid."""
    if seconds_remaining <= 0:
        return TokenExpiryStatus.EXPIRED
    if seconds_remaining <= TOKEN_EXPIRY_CRITICAL_SECONDS:
        return TokenExpiryStatus.CRITICAL
    if seconds_remaining <= TOKEN_EXPIRY_WARNING_SECONDS:
        return TokenExpiryStatus.WARNING
    return TokenExpiryStatus.VALID
