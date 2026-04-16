"""Unit tests for custom_components/saxo_portfolio/models.py.

Covers all dataclasses, validation, masking utilities, and factory methods.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.saxo_portfolio.models import (
    AccountData,
    CoordinatorData,
    PortfolioData,
    PositionData,
    calculate_portfolio_totals,
    mask_sensitive_data,
    mask_url_for_logging,
    sanitize_financial_value,
    validate_iso_currency_code,
)


# ---------------------------------------------------------------------------
# mask_sensitive_data
# ---------------------------------------------------------------------------


class TestMaskSensitiveData:
    """Tests for mask_sensitive_data."""

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        assert mask_sensitive_data("") == ""

    def test_none_like_empty(self) -> None:
        """Falsy empty string is returned unchanged."""
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


# ---------------------------------------------------------------------------
# mask_url_for_logging
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PortfolioData
# ---------------------------------------------------------------------------


class TestPortfolioData:
    """Tests for PortfolioData dataclass."""

    def test_valid_creation(self) -> None:
        """Valid data creates a PortfolioData instance."""
        p = PortfolioData(
            total_value=10000.0,
            cash_balance=5000.0,
            currency="EUR",
            positions_count=3,
        )
        assert p.total_value == 10000.0
        assert p.currency == "EUR"

    def test_negative_total_value_raises(self) -> None:
        """Negative total value raises ValueError."""
        with pytest.raises(ValueError, match="Total value cannot be negative"):
            PortfolioData(
                total_value=-1.0,
                cash_balance=0.0,
                currency="USD",
                positions_count=0,
            )

    def test_negative_positions_count_raises(self) -> None:
        """Negative positions count raises ValueError."""
        with pytest.raises(ValueError, match="Positions count cannot be negative"):
            PortfolioData(
                total_value=100.0,
                cash_balance=0.0,
                currency="USD",
                positions_count=-1,
            )

    def test_currency_wrong_length_raises(self) -> None:
        """Currency with wrong length raises ValueError."""
        with pytest.raises(ValueError, match="Currency must be 3-letter ISO code"):
            PortfolioData(
                total_value=100.0,
                cash_balance=0.0,
                currency="US",
                positions_count=0,
            )

    def test_currency_lowercase_raises(self) -> None:
        """Lowercase currency raises ValueError."""
        with pytest.raises(ValueError, match="Currency must be uppercase"):
            PortfolioData(
                total_value=100.0,
                cash_balance=0.0,
                currency="usd",
                positions_count=0,
            )

    def test_pnl_percentage_calculated(self) -> None:
        """P&L percentage is calculated when unrealized_pnl and total_value are set."""
        p = PortfolioData(
            total_value=11000.0,
            cash_balance=0.0,
            currency="USD",
            positions_count=1,
            unrealized_pnl=1000.0,
        )
        # cost_basis = 11000 - 1000 = 10000, pnl% = 1000/10000 * 100 = 10
        assert p.pnl_percentage == pytest.approx(10.0)

    def test_pnl_percentage_not_calculated_when_total_zero(self) -> None:
        """P&L percentage stays None when total_value is zero."""
        p = PortfolioData(
            total_value=0.0,
            cash_balance=0.0,
            currency="USD",
            positions_count=0,
            unrealized_pnl=None,
        )
        assert p.pnl_percentage is None

    def test_pnl_percentage_not_calculated_when_pnl_none(self) -> None:
        """P&L percentage stays None when unrealized_pnl is None."""
        p = PortfolioData(
            total_value=1000.0,
            cash_balance=500.0,
            currency="USD",
            positions_count=1,
            unrealized_pnl=None,
        )
        assert p.pnl_percentage is None

    def test_pnl_percentage_not_calculated_when_cost_basis_zero(self) -> None:
        """P&L percentage stays None when cost basis is zero."""
        p = PortfolioData(
            total_value=1000.0,
            cash_balance=0.0,
            currency="USD",
            positions_count=1,
            unrealized_pnl=1000.0,
        )
        assert p.pnl_percentage is None

    def test_zero_total_value_allowed(self) -> None:
        """Zero total value is a valid portfolio state."""
        p = PortfolioData(
            total_value=0.0,
            cash_balance=0.0,
            currency="USD",
            positions_count=0,
        )
        assert p.total_value == 0.0


# ---------------------------------------------------------------------------
# AccountData
# ---------------------------------------------------------------------------


class TestAccountData:
    """Tests for AccountData dataclass."""

    def test_valid_creation(self) -> None:
        """Valid data creates an AccountData instance with defaults."""
        a = AccountData(
            account_id="123",
            account_key="key_abc",
            balance=5000.0,
            currency="GBP",
        )
        assert a.account_id == "123"
        assert a.active is True  # default

    def test_empty_account_id_raises(self) -> None:
        """Empty account ID raises ValueError."""
        with pytest.raises(ValueError, match="Account ID cannot be empty"):
            AccountData(
                account_id="",
                account_key="key",
                balance=0.0,
                currency="USD",
            )

    def test_empty_account_key_raises(self) -> None:
        """Empty account key raises ValueError."""
        with pytest.raises(ValueError, match="Account key cannot be empty"):
            AccountData(
                account_id="123",
                account_key="",
                balance=0.0,
                currency="USD",
            )

    def test_currency_wrong_length_raises(self) -> None:
        """Currency with wrong length raises ValueError."""
        with pytest.raises(ValueError, match="Currency must be 3-letter ISO code"):
            AccountData(
                account_id="123",
                account_key="key",
                balance=0.0,
                currency="EURO",
            )

    def test_currency_lowercase_raises(self) -> None:
        """Lowercase currency raises ValueError."""
        with pytest.raises(ValueError, match="Currency must be uppercase"):
            AccountData(
                account_id="123",
                account_key="key",
                balance=0.0,
                currency="eur",
            )

    def test_optional_fields(self) -> None:
        """Optional fields are stored correctly."""
        a = AccountData(
            account_id="id",
            account_key="key",
            balance=100.0,
            currency="USD",
            account_type="Normal",
            display_name="My Account",
            active=False,
        )
        assert a.account_type == "Normal"
        assert a.display_name == "My Account"
        assert a.active is False


# ---------------------------------------------------------------------------
# PositionData
# ---------------------------------------------------------------------------


class TestPositionData:
    """Tests for PositionData dataclass."""

    def test_valid_creation(self) -> None:
        """Valid data creates a PositionData instance with defaults."""
        p = PositionData(
            position_id="pos1",
            account_id="acc1",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
        )
        assert p.position_id == "pos1"
        assert p.currency == "USD"  # default

    def test_empty_position_id_raises(self) -> None:
        """Empty position ID raises ValueError."""
        with pytest.raises(ValueError, match="Position ID cannot be empty"):
            PositionData(
                position_id="",
                account_id="acc",
                symbol="X",
                quantity=1.0,
                current_value=10.0,
            )

    def test_empty_account_id_raises(self) -> None:
        """Empty account ID raises ValueError."""
        with pytest.raises(ValueError, match="Account ID cannot be empty"):
            PositionData(
                position_id="pos",
                account_id="",
                symbol="X",
                quantity=1.0,
                current_value=10.0,
            )

    def test_empty_symbol_raises(self) -> None:
        """Empty symbol raises ValueError."""
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            PositionData(
                position_id="pos",
                account_id="acc",
                symbol="",
                quantity=1.0,
                current_value=10.0,
            )

    def test_zero_quantity_raises(self) -> None:
        """Zero quantity raises ValueError."""
        with pytest.raises(ValueError, match="Quantity cannot be zero"):
            PositionData(
                position_id="pos",
                account_id="acc",
                symbol="X",
                quantity=0.0,
                current_value=10.0,
            )

    def test_negative_current_value_raises(self) -> None:
        """Negative current value raises ValueError."""
        with pytest.raises(ValueError, match="Current value cannot be negative"):
            PositionData(
                position_id="pos",
                account_id="acc",
                symbol="X",
                quantity=1.0,
                current_value=-1.0,
            )

    def test_pnl_percentage_from_prices(self) -> None:
        """P&L percentage calculated from open and current prices."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=100.0,
            current_price=150.0,
        )
        # (150 - 100) / 100 * 100 = 50%
        assert p.pnl_percentage == pytest.approx(50.0)

    def test_pnl_percentage_not_calculated_without_open_price(self) -> None:
        """P&L percentage stays None when open_price is None."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=None,
            current_price=150.0,
        )
        assert p.pnl_percentage is None

    def test_pnl_percentage_not_calculated_with_zero_open_price(self) -> None:
        """P&L percentage stays None when open_price is zero."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=0.0,
            current_price=150.0,
        )
        assert p.pnl_percentage is None

    def test_unrealized_pnl_calculated_when_not_provided(self) -> None:
        """Unrealized P&L auto-calculated from prices when not explicitly set."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=100.0,
            current_price=150.0,
        )
        # (150 - 100) * |10| = 500
        assert p.unrealized_pnl == pytest.approx(500.0)

    def test_unrealized_pnl_calculated_with_negative_quantity(self) -> None:
        """Unrealized P&L uses absolute quantity for short positions."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=-5.0,
            current_value=500.0,
            open_price=100.0,
            current_price=90.0,
        )
        # (90 - 100) * |-5| = -50
        assert p.unrealized_pnl == pytest.approx(-50.0)

    def test_unrealized_pnl_not_overwritten_when_provided(self) -> None:
        """Explicitly provided unrealized P&L is not recalculated."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=100.0,
            current_price=150.0,
            unrealized_pnl=999.0,
        )
        assert p.unrealized_pnl == 999.0

    def test_unrealized_pnl_not_calculated_without_prices(self) -> None:
        """Unrealized P&L stays None when prices are not available."""
        p = PositionData(
            position_id="pos",
            account_id="acc",
            symbol="AAPL",
            quantity=10.0,
            current_value=1500.0,
            open_price=None,
            current_price=None,
        )
        assert p.unrealized_pnl is None


# ---------------------------------------------------------------------------
# CoordinatorData
# ---------------------------------------------------------------------------


def _make_portfolio(**overrides: object) -> PortfolioData:
    """Create a PortfolioData with sensible defaults."""
    defaults = {
        "total_value": 10000.0,
        "cash_balance": 5000.0,
        "currency": "USD",
        "positions_count": 1,
    }
    defaults.update(overrides)
    return PortfolioData(**defaults)


def _make_account(**overrides: object) -> AccountData:
    """Create an AccountData with sensible defaults."""
    defaults = {
        "account_id": "acc1",
        "account_key": "key1",
        "balance": 5000.0,
        "currency": "USD",
    }
    defaults.update(overrides)
    return AccountData(**defaults)


def _make_position(**overrides: object) -> PositionData:
    """Create a PositionData with sensible defaults."""
    defaults = {
        "position_id": "pos1",
        "account_id": "acc1",
        "symbol": "AAPL",
        "quantity": 10.0,
        "current_value": 1500.0,
    }
    defaults.update(overrides)
    return PositionData(**defaults)


class TestCoordinatorData:
    """Tests for CoordinatorData dataclass."""

    def test_valid_creation(self) -> None:
        """Valid data creates a CoordinatorData instance."""
        cd = CoordinatorData(
            portfolio=_make_portfolio(),
            accounts=[_make_account()],
            positions=[_make_position()],
            last_updated=datetime.now(),
        )
        assert len(cd.accounts) == 1
        assert len(cd.positions) == 1

    def test_warns_on_unknown_account_reference(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning logged when position references unknown account."""
        position = _make_position(account_id="unknown_acc")
        CoordinatorData(
            portfolio=_make_portfolio(),
            accounts=[_make_account(account_id="acc1")],
            positions=[position],
            last_updated=datetime.now(),
        )
        assert "unknown account" in caplog.text

    def test_debug_log_on_position_count_mismatch(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Debug message logged when portfolio count differs from actual count."""
        with caplog.at_level("DEBUG"):
            CoordinatorData(
                portfolio=_make_portfolio(positions_count=5),
                accounts=[_make_account()],
                positions=[_make_position()],
                last_updated=datetime.now(),
            )
        assert "differs from actual positions" in caplog.text

    def test_no_warning_when_counts_match(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No warnings when data is consistent."""
        CoordinatorData(
            portfolio=_make_portfolio(positions_count=1),
            accounts=[_make_account()],
            positions=[_make_position()],
            last_updated=datetime.now(),
        )
        assert "unknown account" not in caplog.text


class TestCoordinatorDataFromApiResponses:
    """Tests for CoordinatorData.from_api_responses."""

    def test_minimal_responses(self) -> None:
        """Factory method handles empty positions and accounts."""
        balance = {
            "TotalValue": 10000,
            "CashBalance": 5000,
            "Currency": "EUR",
            "OpenPositionsCount": 0,
        }
        positions = {"Data": []}
        accounts = {"Data": []}

        cd = CoordinatorData.from_api_responses(balance, positions, accounts)
        assert cd.portfolio.total_value == 10000.0
        assert cd.portfolio.currency == "EUR"
        assert cd.portfolio.positions_count == 0
        assert cd.accounts == []
        assert cd.positions == []
        assert isinstance(cd.last_updated, datetime)

    def test_full_responses(self) -> None:
        """Factory method parses complete API responses correctly."""
        balance = {
            "TotalValue": 20000,
            "CashBalance": 5000,
            "Currency": "USD",
            "OpenPositionsCount": 1,
            "UnrealizedMarginProfitLoss": 500.0,
            "MarginAvailableForTrading": 15000.0,
        }
        accounts = {
            "Data": [
                {
                    "AccountId": "acc1",
                    "AccountKey": "key1",
                    "Currency": "USD",
                    "AccountType": "Normal",
                    "DisplayName": "My Account",
                    "Active": True,
                }
            ]
        }
        positions = {
            "Data": [
                {
                    "NetPositionId": "pos1",
                    "PositionBase": {
                        "AccountId": "acc1",
                        "Symbol": "AAPL",
                        "Amount": 10,
                        "AssetType": "Stock",
                        "OpenPrice": 100.0,
                    },
                    "PositionView": {
                        "MarketValue": 1500.0,
                        "CurrentPrice": 150.0,
                        "ProfitLossOnTrade": 500.0,
                    },
                }
            ]
        }

        cd = CoordinatorData.from_api_responses(balance, positions, accounts)
        assert cd.portfolio.unrealized_pnl == 500.0
        assert cd.portfolio.margin_available == 15000.0
        assert len(cd.positions) == 1
        assert cd.positions[0].symbol == "AAPL"
        assert cd.positions[0].open_price == 100.0
        assert cd.positions[0].current_price == 150.0
        assert cd.positions[0].unrealized_pnl == 500.0
        assert cd.positions[0].currency == "USD"
        # Account balance should be sum of positions
        assert cd.accounts[0].balance == 1500.0

    def test_defaults_for_missing_fields(self) -> None:
        """Factory method applies defaults when API fields are absent."""
        balance: dict = {}
        accounts = {"Data": [{"AccountId": "a", "AccountKey": "k"}]}
        positions: dict = {"Data": []}

        cd = CoordinatorData.from_api_responses(balance, positions, accounts)
        assert cd.portfolio.total_value == 0.0
        assert cd.portfolio.currency == "USD"
        assert cd.accounts[0].currency == "USD"
        assert cd.accounts[0].active is True

    def test_account_balance_aggregated_from_positions(self) -> None:
        """Account balance is sum of its positions' current values."""
        balance = {
            "TotalValue": 3000,
            "CashBalance": 0,
            "Currency": "USD",
            "OpenPositionsCount": 2,
        }
        accounts = {"Data": [{"AccountId": "acc1", "AccountKey": "k1"}]}
        positions = {
            "Data": [
                {
                    "NetPositionId": "p1",
                    "PositionBase": {
                        "AccountId": "acc1",
                        "Symbol": "A",
                        "Amount": 1,
                        "OpenPrice": 100.0,
                    },
                    "PositionView": {
                        "MarketValue": 1000.0,
                        "CurrentPrice": 110.0,
                        "ProfitLossOnTrade": 10.0,
                    },
                },
                {
                    "NetPositionId": "p2",
                    "PositionBase": {
                        "AccountId": "acc1",
                        "Symbol": "B",
                        "Amount": 2,
                        "OpenPrice": 50.0,
                    },
                    "PositionView": {
                        "MarketValue": 2000.0,
                        "CurrentPrice": 55.0,
                        "ProfitLossOnTrade": 20.0,
                    },
                },
            ]
        }

        cd = CoordinatorData.from_api_responses(balance, positions, accounts)
        assert cd.accounts[0].balance == pytest.approx(3000.0)

    def test_account_without_positions_has_zero_balance(self) -> None:
        """Account with no positions gets zero balance."""
        balance = {
            "TotalValue": 0,
            "CashBalance": 0,
            "Currency": "USD",
            "OpenPositionsCount": 0,
        }
        accounts = {"Data": [{"AccountId": "acc1", "AccountKey": "k1"}]}
        positions: dict = {"Data": []}

        cd = CoordinatorData.from_api_responses(balance, positions, accounts)
        assert cd.accounts[0].balance == 0.0


class TestCoordinatorDataToDict:
    """Tests for CoordinatorData.to_dict."""

    def test_to_dict_structure(self) -> None:
        """to_dict returns a complete dictionary representation."""
        now = datetime(2025, 1, 1, 12, 0, 0)
        cd = CoordinatorData(
            portfolio=_make_portfolio(unrealized_pnl=500.0, margin_available=8000.0),
            accounts=[_make_account(account_type="Normal", display_name="Test")],
            positions=[
                _make_position(
                    open_price=100.0,
                    current_price=150.0,
                    asset_type="Stock",
                )
            ],
            last_updated=now,
        )
        d = cd.to_dict()

        assert d["portfolio"]["total_value"] == 10000.0
        assert d["portfolio"]["currency"] == "USD"
        assert d["portfolio"]["unrealized_pnl"] == 500.0
        assert d["portfolio"]["margin_available"] == 8000.0
        assert d["portfolio"]["positions_count"] == 1

        assert len(d["accounts"]) == 1
        assert d["accounts"][0]["account_id"] == "acc1"
        assert d["accounts"][0]["account_type"] == "Normal"
        assert d["accounts"][0]["display_name"] == "Test"
        assert d["accounts"][0]["active"] is True

        assert len(d["positions"]) == 1
        assert d["positions"][0]["position_id"] == "pos1"
        assert d["positions"][0]["symbol"] == "AAPL"
        assert d["positions"][0]["asset_type"] == "Stock"

        assert d["last_updated"] == now.isoformat()

    def test_to_dict_empty_lists(self) -> None:
        """to_dict handles empty accounts and positions lists."""
        cd = CoordinatorData(
            portfolio=_make_portfolio(positions_count=0),
            accounts=[],
            positions=[],
            last_updated=datetime.now(),
        )
        d = cd.to_dict()
        assert d["accounts"] == []
        assert d["positions"] == []


# ---------------------------------------------------------------------------
# validate_iso_currency_code
# ---------------------------------------------------------------------------


class TestValidateIsoCurrencyCode:
    """Tests for validate_iso_currency_code."""

    def test_valid_code(self) -> None:
        """Standard 3-letter uppercase codes pass validation."""
        assert validate_iso_currency_code("USD") is True
        assert validate_iso_currency_code("EUR") is True
        assert validate_iso_currency_code("GBP") is True

    def test_lowercase(self) -> None:
        """Lowercase codes fail validation."""
        assert validate_iso_currency_code("usd") is False

    def test_wrong_length(self) -> None:
        """Codes with wrong length fail validation."""
        assert validate_iso_currency_code("US") is False
        assert validate_iso_currency_code("EURO") is False

    def test_not_alpha(self) -> None:
        """Non-alphabetic characters fail validation."""
        assert validate_iso_currency_code("U$D") is False
        assert validate_iso_currency_code("12D") is False

    def test_not_string(self) -> None:
        """Non-string input fails validation."""
        assert validate_iso_currency_code(123) is False  # type: ignore[arg-type]

    def test_empty_string(self) -> None:
        """Empty string fails validation."""
        assert validate_iso_currency_code("") is False


# ---------------------------------------------------------------------------
# sanitize_financial_value
# ---------------------------------------------------------------------------


class TestSanitizeFinancialValue:
    """Tests for sanitize_financial_value."""

    def test_valid_float(self) -> None:
        """Float values pass through correctly."""
        assert sanitize_financial_value(3.14) == pytest.approx(3.14)

    def test_valid_int(self) -> None:
        """Integer values are converted to float."""
        assert sanitize_financial_value(42) == 42.0

    def test_valid_string(self) -> None:
        """Numeric strings are converted to float."""
        assert sanitize_financial_value("123.45") == pytest.approx(123.45)

    def test_nan_returns_zero(self) -> None:
        """NaN returns 0.0."""
        assert sanitize_financial_value(float("nan")) == 0.0

    def test_inf_returns_zero(self) -> None:
        """Positive infinity returns 0.0."""
        assert sanitize_financial_value(float("inf")) == 0.0

    def test_negative_inf_returns_zero(self) -> None:
        """Negative infinity returns 0.0."""
        assert sanitize_financial_value(float("-inf")) == 0.0

    def test_invalid_string_returns_zero(self) -> None:
        """Non-numeric string returns 0.0."""
        assert sanitize_financial_value("not_a_number") == 0.0

    def test_none_returns_zero(self) -> None:
        """None returns 0.0."""
        assert sanitize_financial_value(None) == 0.0  # type: ignore[arg-type]

    def test_negative_value_allowed(self) -> None:
        """Negative finite values are valid."""
        assert sanitize_financial_value(-99.5) == pytest.approx(-99.5)

    def test_zero(self) -> None:
        """Zero is a valid value."""
        assert sanitize_financial_value(0) == 0.0


# ---------------------------------------------------------------------------
# calculate_portfolio_totals
# ---------------------------------------------------------------------------


class TestCalculatePortfolioTotals:
    """Tests for calculate_portfolio_totals."""

    def test_single_position(self) -> None:
        """Single position returns correct totals and P&L percentage."""
        pos = _make_position(current_value=1000.0, unrealized_pnl=100.0)
        result = calculate_portfolio_totals([pos])
        assert result["total_value"] == 1000.0
        assert result["total_pnl"] == 100.0
        # cost_basis = 1000 - 100 = 900, pnl% = 100/900 * 100
        assert result["pnl_percentage"] == pytest.approx(100.0 / 900.0 * 100)
        assert result["positions_count"] == 1

    def test_multiple_positions(self) -> None:
        """Multiple positions are aggregated correctly."""
        p1 = _make_position(
            position_id="p1",
            current_value=1000.0,
            unrealized_pnl=50.0,
        )
        p2 = _make_position(
            position_id="p2",
            current_value=2000.0,
            unrealized_pnl=200.0,
        )
        result = calculate_portfolio_totals([p1, p2])
        assert result["total_value"] == 3000.0
        assert result["total_pnl"] == 250.0
        assert result["positions_count"] == 2

    def test_empty_positions(self) -> None:
        """Empty positions list returns zeroes."""
        result = calculate_portfolio_totals([])
        assert result["total_value"] == 0.0
        assert result["total_pnl"] == 0.0
        assert result["pnl_percentage"] == 0.0
        assert result["positions_count"] == 0

    def test_none_pnl_treated_as_zero(self) -> None:
        """None unrealized_pnl is treated as 0.0 in totals."""
        pos = _make_position(current_value=500.0, unrealized_pnl=None)
        result = calculate_portfolio_totals([pos])
        assert result["total_pnl"] == 0.0

    def test_cost_basis_zero_returns_zero_percentage(self) -> None:
        """Zero cost basis yields 0% P&L to avoid division by zero."""
        pos = _make_position(current_value=100.0, unrealized_pnl=100.0)
        result = calculate_portfolio_totals([pos])
        assert result["pnl_percentage"] == 0.0
