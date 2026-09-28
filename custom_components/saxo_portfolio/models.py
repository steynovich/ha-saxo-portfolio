"""Logging-safety utilities for the Saxo Portfolio integration."""

from __future__ import annotations

import re


def mask_sensitive_data(text: str) -> str:
    """Mask sensitive data in strings for safe logging.

    Args:
        text: Input string that may contain sensitive data

    Returns:
        String with sensitive data masked with '**REDACTED**'

    """
    from .const import DIAGNOSTICS_REDACTED, SENSITIVE_URL_PATTERNS

    if not text:
        return text

    masked_text = text
    for pattern in SENSITIVE_URL_PATTERNS:
        masked_text = re.sub(
            pattern, r"\1" + DIAGNOSTICS_REDACTED, masked_text, flags=re.IGNORECASE
        )

    return masked_text


def mask_url_for_logging(url: str) -> str:
    """Mask sensitive parts of URLs for safe logging.

    Args:
        url: URL that may contain sensitive parameters

    Returns:
        URL with sensitive parameters masked

    """
    if not url:
        return url

    # Mask the whole URL: identifiers can live in the path as well as the query
    return mask_sensitive_data(url)
