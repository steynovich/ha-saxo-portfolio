# Data Model: Saxo Portfolio Home Assistant Integration

## Core Entities

### Portfolio Entity
**Purpose**: Represents a complete Saxo investment portfolio
**Attributes**:
- `portfolio_id`: Unique identifier for the portfolio
- `total_value`: Total portfolio value in base currency (float)
- `cash_balance`: Available cash balance (float)
- `currency`: Base currency code (string, e.g., "USD", "EUR")
- `unrealized_pnl`: Unrealized profit/loss (float)
- `margin_available`: Available margin for trading (float)
- `positions_count`: Number of open positions (integer)
- `last_updated`: Timestamp of last data refresh (datetime)

**Validation Rules**:
- `total_value` >= 0
- `cash_balance` can be negative (margin accounts)
- `currency` must be valid ISO 4217 code
- `positions_count` >= 0
- `last_updated` must be within last 24 hours for active portfolios

**State Transitions**:
- `Active` → `Refreshing` (during data updates)
- `Refreshing` → `Active` (successful update)
- `Refreshing` → `Error` (failed update)
- `Error` → `Refreshing` (retry attempt)

### Account Entity
**Purpose**: Individual Saxo trading account within a portfolio
**Attributes**:
- `account_id`: Saxo account identifier (string)
- `account_key`: Saxo account key for API calls (string)
- `account_type`: Type of account (string: "Normal", "Margin", "ISA")
- `client_key`: Client key for account access (string)
- `active`: Account active status (boolean)
- `base_currency`: Account base currency (string)
- `name`: Display name for account (string)

**Validation Rules**:
- `account_id` must be unique within integration
- `account_type` must be one of allowed values
- `base_currency` must be valid ISO 4217 code
- `active` accounts must have valid API credentials

**Relationships**:
- `Portfolio` 1:N `Account` (portfolio can have multiple accounts)
- `Account` 1:N `Position` (account can have multiple positions)

### Position Entity
**Purpose**: Individual investment holding within an account
**Attributes**:
- `position_id`: Unique position identifier (string)
- `account_id`: Associated account ID (string, foreign key)
- `symbol`: Investment symbol/ticker (string)
- `asset_type`: Type of asset (string: "Stock", "FxSpot", "Bond", "Option")
- `quantity`: Number of units held (float)
- `open_price`: Average opening price (float)
- `current_price`: Current market price (float)
- `market_value`: Current market value of position (float)
- `unrealized_pnl`: Unrealized profit/loss (float)
- `pnl_percentage`: P&L as percentage (float)
- `currency`: Position currency (string)
- `status`: Position status (string: "Open", "Closed", "Pending")

**Validation Rules**:
- `quantity` > 0 for open positions
- `open_price` > 0
- `current_price` > 0 for active positions
- `market_value` = `quantity` × `current_price` (with currency conversion)
- `pnl_percentage` = (`current_price` - `open_price`) / `open_price` × 100
- `symbol` must be valid for the given `asset_type`

**Relationships**:
- `Account` 1:N `Position`
- `Position` relates to market data updates

### Sensor Entity
**Purpose**: Home Assistant sensor representation of financial data
**Attributes**:
- `sensor_id`: Unique sensor identifier (string)
- `entity_id`: Home Assistant entity ID (string)
- `friendly_name`: Display name in Home Assistant (string)
- `sensor_type`: Type of sensor (enum: see below)
- `unit_of_measurement`: Measurement unit (string)
- `device_class`: Home Assistant device class (string)
- `state_class`: Home Assistant state class (string)
- `value`: Current sensor value (float/string)
- `attributes`: Additional sensor attributes (dict)
- `last_updated`: Last update timestamp (datetime)

**Sensor Types**:
- `portfolio_total_value`: Total portfolio value
- `portfolio_cash_balance`: Available cash
- `portfolio_unrealized_pnl`: Unrealized profit/loss
- `portfolio_positions_count`: Number of positions
- `account_balance`: Individual account balance
- `position_value`: Individual position value
- `position_pnl`: Individual position P&L

**Validation Rules**:
- `sensor_id` must be unique within Home Assistant instance
- `entity_id` follows Home Assistant naming conventions
- `sensor_type` must be from allowed enum values
- `unit_of_measurement` must match sensor type requirements
- Financial values must include currency in attributes

## Data Flow Relationships

### Portfolio → Account → Position Hierarchy
```
Portfolio (1)
├── total_value (calculated from all accounts)
├── cash_balance (sum of account cash)
└── positions_count (sum of all positions)

Account (N)
├── account_balance (individual account total)
├── positions (list of positions in account)
└── currency (account base currency)

Position (N)
├── market_value (quantity × current_price)
├── unrealized_pnl (current_value - cost_basis)
└── pnl_percentage ((current_price - open_price) / open_price)
```

### Data Aggregation Rules
1. **Portfolio Total Value** = Σ(Account Values) converted to base currency
2. **Portfolio Cash Balance** = Σ(Account Cash Balances) converted to base currency  
3. **Portfolio Unrealized P&L** = Σ(Position Unrealized P&L) converted to base currency
4. **Portfolio Positions Count** = Σ(Active Positions across all accounts)

### Currency Conversion
- All portfolio-level values displayed in user's preferred currency
- Account-level values in account's base currency
- Position-level values in position's trading currency
- Conversion rates updated with market data

## State Management

### Entity States
**Portfolio States**:
- `Active`: Normal operation, data current
- `Refreshing`: Data update in progress
- `Stale`: Data older than refresh interval
- `Error`: Update failed, previous data shown
- `Unavailable`: No data available (initial load or auth failure)

**Sensor States**:
- Numeric value for financial data
- `unavailable` during initial load
- `unknown` for calculation errors
- Previous value maintained during temporary failures

### Data Consistency Rules
1. **Atomic Updates**: All related sensors update together
2. **Rollback on Failure**: Maintain previous state if update fails
3. **Timestamp Validation**: Reject data older than current state
4. **Currency Consistency**: All related values use consistent exchange rates

## Validation and Constraints

### Business Rules
1. **Account Limits**: Maximum 10 accounts per integration instance
2. **Position Limits**: Maximum 100 positions per account
3. **Update Frequency**: Minimum 1 minute between updates
4. **Data Retention**: Historical data not stored (Home Assistant handles statistics)

### Data Quality Checks
1. **Value Validation**: All monetary values must be finite numbers
2. **Consistency Checks**: Portfolio totals match sum of account values
3. **Timestamp Validation**: Updates must be newer than previous data
4. **Currency Validation**: All currencies must be valid ISO codes

### Error Handling
1. **Partial Updates**: Accept partial data if some accounts/positions fail
2. **Graceful Degradation**: Show cached data during API failures
3. **User Notification**: Surface authentication and configuration errors
4. **Logging**: Detailed error logging for troubleshooting

## Home Assistant Integration Specifics

### Entity Registry
- All sensors registered with unique IDs
- Entities survive integration reloads
- Device registry entry for the Saxo Portfolio integration
- Entity categories: "diagnostic" for technical sensors, default for user data

### Configuration Storage
- OAuth tokens in Home Assistant's credential store
- User preferences in integration config data
- No sensitive data in entity attributes
- Configuration validation on startup

### Update Coordination
- Single DataUpdateCoordinator instance per integration
- All sensors share the same data fetch cycle
- Rate limiting applied at coordinator level
- Error states propagated to all dependent sensors