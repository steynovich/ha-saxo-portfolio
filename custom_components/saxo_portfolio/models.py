"""Data models for Saxo Portfolio Home Assistant integration.

These models define the data structures used throughout the integration
to ensure type safety and data consistency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union
import logging

_LOGGER = logging.getLogger(__name__)


@dataclass
class PortfolioData:
    """Portfolio data model for aggregated portfolio information."""
    
    total_value: float
    cash_balance: float
    currency: str
    positions_count: int
    unrealized_pnl: Optional[float] = None
    pnl_percentage: Optional[float] = None
    margin_available: Optional[float] = None
    
    def __post_init__(self):
        """Validate portfolio data after initialization."""
        # Validate required fields
        if self.total_value < 0:
            raise ValueError("Total value cannot be negative")
        if self.positions_count < 0:
            raise ValueError("Positions count cannot be negative")
        if len(self.currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")
        if not self.currency.isupper():
            raise ValueError("Currency must be uppercase")
            
        # Calculate P&L percentage if both values available
        if self.unrealized_pnl is not None and self.total_value > 0:
            cost_basis = self.total_value - self.unrealized_pnl
            if cost_basis > 0:
                self.pnl_percentage = (self.unrealized_pnl / cost_basis) * 100


@dataclass
class AccountData:
    """Account data model for individual Saxo trading accounts."""
    
    account_id: str
    account_key: str
    balance: float
    currency: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None
    active: bool = True
    
    def __post_init__(self):
        """Validate account data after initialization."""
        if not self.account_id:
            raise ValueError("Account ID cannot be empty")
        if not self.account_key:
            raise ValueError("Account key cannot be empty")
        if len(self.currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")
        if not self.currency.isupper():
            raise ValueError("Currency must be uppercase")


@dataclass
class PositionData:
    """Position data model for individual investment holdings."""
    
    position_id: str
    account_id: str
    symbol: str
    quantity: float
    current_value: float
    asset_type: Optional[str] = None
    open_price: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    pnl_percentage: Optional[float] = None
    currency: str = "USD"
    
    def __post_init__(self):
        """Validate position data after initialization."""
        if not self.position_id:
            raise ValueError("Position ID cannot be empty")
        if not self.account_id:
            raise ValueError("Account ID cannot be empty")
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")
        if self.quantity == 0:
            raise ValueError("Quantity cannot be zero")
        if self.current_value < 0:
            raise ValueError("Current value cannot be negative")
            
        # Calculate P&L percentage if prices available
        if (self.open_price is not None and 
            self.current_price is not None and 
            self.open_price > 0):
            self.pnl_percentage = ((self.current_price - self.open_price) / self.open_price) * 100
            
        # Calculate unrealized P&L if not provided
        if (self.unrealized_pnl is None and 
            self.open_price is not None and 
            self.current_price is not None):
            self.unrealized_pnl = (self.current_price - self.open_price) * abs(self.quantity)


@dataclass
class CoordinatorData:
    """Main data structure managed by DataUpdateCoordinator."""
    
    portfolio: PortfolioData
    accounts: List[AccountData]
    positions: List[PositionData]
    last_updated: datetime
    
    def __post_init__(self):
        """Validate coordinator data consistency."""
        # Validate data consistency
        account_ids = {account.account_id for account in self.accounts}
        for position in self.positions:
            if position.account_id not in account_ids:
                _LOGGER.warning(
                    "Position %s references unknown account %s",
                    position.position_id,
                    position.account_id
                )
        
        # Validate position count consistency
        actual_positions_count = len([p for p in self.positions if p.quantity != 0])
        if abs(self.portfolio.positions_count - actual_positions_count) > 0:
            _LOGGER.debug(
                "Portfolio positions count (%d) differs from actual positions (%d)",
                self.portfolio.positions_count,
                actual_positions_count
            )
    
    @classmethod
    def from_api_responses(
        cls,
        balance_response: Dict,
        positions_response: Dict,
        accounts_response: Dict
    ) -> CoordinatorData:
        """Create CoordinatorData from Saxo API responses."""
        
        # Parse portfolio data from balance response
        portfolio = PortfolioData(
            total_value=float(balance_response.get("TotalValue", 0)),
            cash_balance=float(balance_response.get("CashBalance", 0)),
            currency=balance_response.get("Currency", "USD"),
            positions_count=int(balance_response.get("OpenPositionsCount", 0)),
            unrealized_pnl=balance_response.get("UnrealizedMarginProfitLoss"),
            margin_available=balance_response.get("MarginAvailableForTrading")
        )
        
        # Parse accounts data
        accounts = []
        for account_data in accounts_response.get("Data", []):
            account = AccountData(
                account_id=account_data["AccountId"],
                account_key=account_data["AccountKey"],
                balance=0.0,  # Will be calculated from positions
                currency=account_data.get("Currency", "USD"),
                account_type=account_data.get("AccountType"),
                display_name=account_data.get("DisplayName"),
                active=account_data.get("Active", True)
            )
            accounts.append(account)
        
        # Parse positions data
        positions = []
        for position_data in positions_response.get("Data", []):
            position_base = position_data["PositionBase"]
            position_view = position_data["PositionView"]
            
            position = PositionData(
                position_id=position_data["NetPositionId"],
                account_id=position_base["AccountId"],
                symbol=position_base.get("Symbol", "Unknown"),
                quantity=float(position_base["Amount"]),
                current_value=float(position_view.get("MarketValue", 0)),
                asset_type=position_base.get("AssetType"),
                open_price=float(position_base["OpenPrice"]),
                current_price=float(position_view["CurrentPrice"]),
                unrealized_pnl=float(position_view["ProfitLossOnTrade"]),
                currency=portfolio.currency  # Use portfolio currency for consistency
            )
            positions.append(position)
        
        # Calculate account balances from positions
        account_balances = {}
        for position in positions:
            if position.account_id not in account_balances:
                account_balances[position.account_id] = 0.0
            account_balances[position.account_id] += position.current_value
        
        # Update account balances
        for account in accounts:
            account.balance = account_balances.get(account.account_id, 0.0)
        
        return cls(
            portfolio=portfolio,
            accounts=accounts,
            positions=positions,
            last_updated=datetime.now()
        )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for Home Assistant storage."""
        return {
            "portfolio": {
                "total_value": self.portfolio.total_value,
                "cash_balance": self.portfolio.cash_balance,
                "currency": self.portfolio.currency,
                "unrealized_pnl": self.portfolio.unrealized_pnl,
                "pnl_percentage": self.portfolio.pnl_percentage,
                "positions_count": self.portfolio.positions_count,
                "margin_available": self.portfolio.margin_available
            },
            "accounts": [
                {
                    "account_id": account.account_id,
                    "account_key": account.account_key,
                    "balance": account.balance,
                    "currency": account.currency,
                    "account_type": account.account_type,
                    "display_name": account.display_name,
                    "active": account.active
                }
                for account in self.accounts
            ],
            "positions": [
                {
                    "position_id": position.position_id,
                    "account_id": position.account_id,
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "current_value": position.current_value,
                    "asset_type": position.asset_type,
                    "open_price": position.open_price,
                    "current_price": position.current_price,
                    "unrealized_pnl": position.unrealized_pnl,
                    "pnl_percentage": position.pnl_percentage,
                    "currency": position.currency
                }
                for position in self.positions
            ],
            "last_updated": self.last_updated.isoformat()
        }


def validate_iso_currency_code(currency: str) -> bool:
    """Validate that currency is a proper ISO 4217 code format."""
    if not isinstance(currency, str):
        return False
    if len(currency) != 3:
        return False
    if not currency.isupper():
        return False
    if not currency.isalpha():
        return False
    return True


def sanitize_financial_value(value: Union[str, int, float]) -> float:
    """Sanitize and validate financial values from API responses."""
    try:
        float_value = float(value)
        
        # Check for invalid values
        import math
        if math.isnan(float_value) or math.isinf(float_value):
            _LOGGER.warning("Invalid financial value received: %s", value)
            return 0.0
            
        return float_value
    except (ValueError, TypeError):
        _LOGGER.warning("Could not convert value to float: %s", value)
        return 0.0


def calculate_portfolio_totals(positions: List[PositionData]) -> Dict[str, float]:
    """Calculate portfolio totals from positions data."""
    total_value = sum(position.current_value for position in positions)
    total_pnl = sum(position.unrealized_pnl or 0.0 for position in positions)
    
    # Calculate overall P&L percentage
    cost_basis = total_value - total_pnl
    pnl_percentage = (total_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
    
    return {
        "total_value": total_value,
        "total_pnl": total_pnl,
        "pnl_percentage": pnl_percentage,
        "positions_count": len([p for p in positions if p.quantity != 0])
    }