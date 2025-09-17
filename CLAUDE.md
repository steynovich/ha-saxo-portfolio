# ha-saxo Development Guidelines

Auto-generated from current implementation. Last updated: 2025-09-17

## Active Technologies
- Home Assistant Custom Integration
- OAuth 2.0 Authentication
- Saxo Bank OpenAPI
- Python 3.11+
- HACS Compatible

## Project Structure
```
custom_components/saxo_portfolio/
├── __init__.py                 # Integration setup
├── config_flow.py             # OAuth configuration flow with prefix support
├── coordinator.py             # Data update coordinator with market hours logic
├── sensor.py                  # Seven comprehensive sensors with automatic client ID naming
├── const.py                   # Constants and configuration
├── application_credentials.py  # OAuth credential management
└── api/
    ├── __init__.py
    └── saxo_client.py         # API client with rate limiting
tests/
├── contract/                  # API contract tests
├── integration/              # End-to-end tests
└── test_structure.py         # Repository structure validation
```

## Commands
```bash
# Development
ruff check .                   # Linting (used in CI/CD)
ruff format .                  # Code formatting
python -m pytest tests/       # Run tests

# Quality checks
source venv/bin/activate       # Activate virtual environment
python -m py_compile custom_components/saxo_portfolio/sensor.py
```

## Code Style
- Follow Home Assistant integration standards
- Use type hints throughout (Python 3.11+ syntax)
- Comprehensive error handling with sanitized logging
- Security-first approach with data masking

## Current Implementation

### Core Features
- **Sixteen Entities**: Complete portfolio monitoring with balance, performance, transfer tracking, and diagnostics
  - `SaxoCashBalanceSensor` from `/port/v1/balances/me`
  - `SaxoTotalValueSensor` from `/port/v1/balances/me`
  - `SaxoNonMarginPositionsValueSensor` from `/port/v1/balances/me`
  - `SaxoAccumulatedProfitLossSensor` from `/hist/v3/perf/`
  - `SaxoInvestmentPerformanceSensor` from `/hist/v4/performance/timeseries` (all-time)
  - `SaxoYTDInvestmentPerformanceSensor` from `/hist/v4/performance/timeseries` (year-to-date)
  - `SaxoMonthInvestmentPerformanceSensor` from `/hist/v4/performance/timeseries` (month-to-date)
  - `SaxoQuarterInvestmentPerformanceSensor` from `/hist/v4/performance/timeseries` (quarter-to-date)
  - `SaxoCashTransferBalanceSensor` from `/hist/v4/performance/timeseries`
  - `SaxoClientIDSensor` - Client ID diagnostic information
  - `SaxoAccountIDSensor` - Account ID from `/port/v1/accounts/{AccountKey}` (hourly)
  - `SaxoNameSensor` - Client name from `/port/v1/clients/me` with `mdi:account-box` icon
  - `SaxoTokenExpirySensor` - OAuth token expiration monitoring
  - `SaxoMarketStatusSensor` - Real-time market status detection
  - `SaxoLastUpdateSensor` - Successful data update timestamp tracking
  - `SaxoTimezoneSensor` - Timezone configuration and market hours display
- **Automatic Client ID Naming**: Entity names use actual Saxo Client ID (e.g., `saxo_123456_cash_balance`)
- **OAuth 2.0**: Secure authentication with Home Assistant credential management (production endpoints only)
- **Market Hours**: Dynamic update intervals (5 min market hours, 30 min after hours)
- **Performance Caching**: Smart caching system that updates performance data hourly while maintaining real-time balance updates
- **Rate Limiting**: Intelligent API throttling with exponential backoff
- **Comprehensive Diagnostics**: Built-in diagnostic support and real-time monitoring sensors

### Entity Naming Pattern
- All entities use Client ID: `sensor.saxo_{client_id}_{sensor_type}`
- Examples with Client ID "123456":
  - `sensor.saxo_123456_cash_balance`
  - `sensor.saxo_123456_total_value`
  - `sensor.saxo_123456_non_margin_positions_value`
  - `sensor.saxo_123456_accumulated_profit_loss`
  - `sensor.saxo_123456_investment_performance`
  - `sensor.saxo_123456_ytd_investment_performance`
  - `sensor.saxo_123456_month_investment_performance`
  - `sensor.saxo_123456_quarter_investment_performance`
  - `sensor.saxo_123456_cash_transfer_balance`
  - `sensor.saxo_123456_client_id` (diagnostic)
  - `sensor.saxo_123456_account_id` (diagnostic)
  - `sensor.saxo_123456_name` (diagnostic)
  - `sensor.saxo_123456_token_expiry` (diagnostic)
  - `sensor.saxo_123456_market_status` (diagnostic)
  - `sensor.saxo_123456_last_update` (diagnostic)
  - `sensor.saxo_123456_timezone` (diagnostic)
- Device: `"Saxo {ClientId} Portfolio"`

### Configuration Options
- No user configuration needed - automatic Client ID detection
- Production endpoints only (no environment selection)
- Automatic token refresh with proper security handling
- Entity names automatically generated from Saxo Client ID

### Key Files
- `sensor.py:56-62`: All thirteen entity classes instantiated in async_setup_entry (7 portfolio + 6 diagnostic)
- `sensor.py:527-643`: Base performance sensor class with code deduplication (SaxoPerformanceSensorBase)
  - Includes enhanced extra_state_attributes with last_updated and time_period
  - Abstract _get_time_period() method for StandardPeriod values
- `sensor.py:670-689`: Investment performance sensors with time_period attributes
  - SaxoInvestmentPerformanceSensor: time_period="AllTime"
  - SaxoYTDInvestmentPerformanceSensor: time_period="Year"
- `sensor.py:661-757`: Cash transfer balance sensor implementation
- `sensor.py:779-862`: Account/Client ID diagnostic sensors (SaxoClientIDSensor, SaxoAccountIDSensor)
- `sensor.py:863-1277`: Other diagnostic sensor implementations (Token, Market Status, Last Update, Timezone)
- `coordinator.py:132-151`: Performance cache validation logic (_should_update_performance_data)
- `coordinator.py:484-618`: Smart performance data caching with hourly updates
- `coordinator.py:790-799`: Account ID getter method (get_account_id)
- `coordinator.py:634`: Account ID data extraction from balance API
- `diagnostics.py`: Comprehensive diagnostic information collection
- `api/saxo_client.py:464-501`: get_performance_v4() method for all-time performance
- `api/saxo_client.py:502-540`: get_performance_v4_ytd() method for year-to-date performance
- `const.py:118`: PERFORMANCE_UPDATE_INTERVAL constant (1 hour)

## Recent Changes (v2.1.2+)
- **Expanded to sixteen entities**: Added comprehensive portfolio monitoring including Month/Quarter performance tracking
- **Additional Performance Sensors**: Month-to-Date and Quarter-to-Date investment performance sensors
  - SaxoMonthInvestmentPerformanceSensor using "Month" StandardPeriod
  - SaxoQuarterInvestmentPerformanceSensor using "Quarter" StandardPeriod
- **Fixed Performance Sensor Timestamps**: Performance sensors now properly display last_updated attribute
  - Converted datetime objects to ISO format strings for Home Assistant display
  - Performance sensors show when performance data was last fetched from API
- **Display Name Sensor Icon Fix**: Fixed missing icon for SaxoNameSensor
  - Changed from invalid `mdi:account-card-details` to valid `mdi:account-box` icon
  - Added explicit icon property method for reliable display
- **OAuth Token Refresh Enhancement**: Added fallback redirect_uri for token refresh operations
  - Prevents token refresh failures when redirect_uri is missing from config entry
  - Uses standard Home Assistant OAuth redirect URL as fallback
- **Enhanced Diagnostic Suite**: Seven diagnostic entities for complete integration monitoring
  - Client ID and Account ID sensors for identification and troubleshooting
  - Display Name sensor with proper icon showing client name from API
  - Token Expiry sensor with countdown and status indicators
  - Market Status sensor showing current market state
  - Last Update sensor with timestamp tracking
  - Timezone sensor displaying configuration details
- **Performance Data Caching**: Smart hourly caching system for performance data to optimize API usage
  - Balance data: Updates every 5-30 minutes (real-time based on market hours)
  - Performance data: Updates every 1 hour (cached) - reduces API calls by ~90%
- **Code Deduplication**: Refactored performance sensors with SaxoPerformanceSensorBase class
- **Enhanced Sensor Attributes**: Improved attribute consistency across all sensors
  - Performance sensors include time_period attribute with StandardPeriod values ("AllTime"/"Year"/"Month"/"Quarter")
  - Fixed last_updated timestamps to match data source and format properly for display
- **V4 API Integration**: Added `/hist/v4/performance/timeseries` endpoint support for all time periods
- **Enhanced Data Coverage**: Now covers balance, performance (all periods), transfer, and system health data

## Security & Quality
- OAuth 2.0 with CSRF protection using `secrets.token_urlsafe(32)`
- Comprehensive data masking for sensitive information
- Platinum-grade quality compliance
- HACS validation with GitHub Actions workflows
- Full type coverage and modern Python practices

<!-- MANUAL ADDITIONS START -->
# Important Instructions
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
<!-- MANUAL ADDITIONS END -->