"""Typed coordinator data for the Saxo Portfolio integration.

``SaxoCoordinator.data`` is a :class:`SaxoPortfolioData` (or ``None`` before
the first successful update). Sensors and diagnostics read its typed
attributes instead of indexing a dict by string key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

UNKNOWN = "unknown"
DEFAULT_CURRENCY = "USD"


def to_float(value: Any) -> float | None:
    """Convert an API value with ``float()`` semantics, or None if impossible."""
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def numeric_or_none(value: Any) -> float | None:
    """Return ``value`` as float if it is a number, else None ("unknown")."""
    return float(value) if isinstance(value, int | float) else None


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """Identity of the Saxo client behind a config entry."""

    client_id: str = UNKNOWN
    account_id: str = UNKNOWN
    client_name: str = UNKNOWN

    @property
    def has_any_value(self) -> bool:
        """Return True if any identity field is known."""
        return any(
            value not in ("", UNKNOWN)
            for value in (self.client_id, self.account_id, self.client_name)
        )


@dataclass(frozen=True, slots=True)
class BalanceData:
    """Account balance, from the balances endpoint.

    A value is None only when the API returned something that is not a
    number; a missing field reads as 0.0.
    """

    cash_balance: float | None = 0.0
    currency: str = DEFAULT_CURRENCY
    total_value: float | None = 0.0
    non_margin_positions_value: float | None = 0.0

    @classmethod
    def from_api(cls, balance: dict[str, Any]) -> BalanceData:
        """Build from a ``/port/v1/balances/me`` response."""
        return cls(
            cash_balance=to_float(balance.get("CashBalance", 0.0)),
            currency=str(balance.get("Currency", DEFAULT_CURRENCY)),
            total_value=to_float(balance.get("TotalValue", 0.0)),
            non_margin_positions_value=to_float(
                balance.get("NonMarginPositionsValue", 0.0)
            ),
        )

    @property
    def has_any_value(self) -> bool:
        """Return True if at least one balance figure is a number."""
        return any(
            value is not None
            for value in (
                self.cash_balance,
                self.total_value,
                self.non_margin_positions_value,
            )
        )


@dataclass(frozen=True, slots=True)
class PerformanceData:
    """Performance metrics from the v3 and v4 performance endpoints.

    Every field is None until it has been fetched successfully at least once
    (issue #15): a 0.0 would be recorded as a real measurement in long-term
    statistics.
    """

    # v3 BalancePerformance.AccumulatedProfitLoss (a currency amount; the
    # field name is historical)
    ytd_earnings_percentage: float | None = None
    # v4 ReturnFraction * 100 for AllTime / year-to-date / Month / Quarter
    investment_performance_percentage: float | None = None
    ytd_investment_performance_percentage: float | None = None
    month_investment_performance_percentage: float | None = None
    quarter_investment_performance_percentage: float | None = None
    # v4 AllTime Balance.CashTransfer, latest value
    cash_transfer_balance: float | None = None
    # v4 year-to-date Balance.YearlyProfitLoss / Balance.CashTransfer
    ytd_profit_loss: float | None = None
    ytd_cash_transfer: float | None = None

    @property
    def has_any_value(self) -> bool:
        """Return True if at least one metric has been fetched."""
        return any(
            value is not None
            for value in (
                self.ytd_earnings_percentage,
                self.investment_performance_percentage,
                self.ytd_investment_performance_percentage,
                self.month_investment_performance_percentage,
                self.quarter_investment_performance_percentage,
                self.cash_transfer_balance,
                self.ytd_profit_loss,
                self.ytd_cash_transfer,
            )
        )


@dataclass(frozen=True, slots=True)
class SaxoPortfolioData:
    """Everything one coordinator update produces (positions are cached separately)."""

    balance: BalanceData
    last_updated: datetime
    performance: PerformanceData = field(default_factory=PerformanceData)
    client: ClientInfo = field(default_factory=ClientInfo)

    @property
    def field_names(self) -> list[str]:
        """Flat names of all data fields, for diagnostics (never values)."""
        return [
            *BalanceData.__dataclass_fields__,
            *PerformanceData.__dataclass_fields__,
            *ClientInfo.__dataclass_fields__,
            "last_updated",
        ]
