"""Unit tests for custom_components/saxo_portfolio/models.py masking helpers."""

from __future__ import annotations

from custom_components.saxo_portfolio.models import (
    mask_sensitive_data,
    mask_url_for_logging,
)


class TestMaskSensitiveData:
    """Tests for mask_sensitive_data."""

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        assert mask_sensitive_data("") == ""

    def test_no_sensitive_data(self) -> None:
        """String without sensitive patterns is returned unchanged."""
        text = "some normal log text"
        assert mask_sensitive_data(text) == text

    def test_masks_token_param(self) -> None:
        """Token query parameter is redacted."""
        result = mask_sensitive_data("token=abc123&other=val")
        assert "abc123" not in result
        assert "**REDACTED**" in result
        assert "other=val" in result

    def test_masks_access_token_param(self) -> None:
        """Access token query parameter is redacted."""
        result = mask_sensitive_data("access_token=secret_value&x=1")
        assert "secret_value" not in result
        assert "**REDACTED**" in result

    def test_masks_authorization_bearer(self) -> None:
        """Authorization Bearer header value is redacted."""
        result = mask_sensitive_data("Authorization: Bearer my_secret_jwt")
        assert "my_secret_jwt" not in result
        assert "**REDACTED**" in result

    def test_masks_app_key(self) -> None:
        """App key query parameter is redacted."""
        result = mask_sensitive_data("app_key=key123&foo=bar")
        assert "key123" not in result
        assert "**REDACTED**" in result

    def test_masks_app_secret(self) -> None:
        """App secret query parameter is redacted."""
        result = mask_sensitive_data("app_secret=supersecret&a=b")
        assert "supersecret" not in result
        assert "**REDACTED**" in result

    def test_case_insensitive(self) -> None:
        """Pattern matching is case-insensitive."""
        result = mask_sensitive_data("TOKEN=xyz")
        assert "xyz" not in result

    def test_multiple_patterns(self) -> None:
        """Multiple sensitive patterns in one string are all redacted."""
        result = mask_sensitive_data("token=aaa&app_key=bbb")
        assert "aaa" not in result
        assert "bbb" not in result


class TestMaskUrlForLogging:
    """Tests for mask_url_for_logging."""

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        assert mask_url_for_logging("") == ""

    def test_url_without_query(self) -> None:
        """URL without query parameters is returned unchanged."""
        url = "https://api.example.com/v1/balances/me"
        assert mask_url_for_logging(url) == url

    def test_url_with_sensitive_query(self) -> None:
        """URL with sensitive query parameters has them redacted."""
        url = "https://api.example.com/v1?token=secret123&limit=10"
        result = mask_url_for_logging(url)
        assert "secret123" not in result
        assert "**REDACTED**" in result
        assert "limit=10" in result

    def test_url_with_no_sensitive_query(self) -> None:
        """URL with non-sensitive query parameters is returned unchanged."""
        url = "https://api.example.com/v1?limit=10&offset=20"
        result = mask_url_for_logging(url)
        assert result == url
