# ha-saxo Development Guidelines

Auto-generated from current implementation. Last updated: 2025-09-12

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
├── sensor.py                  # Six comprehensive sensors with automatic client ID naming
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
- **Ten Entities**: Complete portfolio monitoring with balance, performance, transfer tracking, and diagnostics
  - `SaxoCashBalanceSensor` from `/port/v1/balances/me`
  - `SaxoTotalValueSensor` from `/port/v1/balances/me`
  - `SaxoNonMarginPositionsValueSensor` from `/port/v1/balances/me`
  - `SaxoAccumulatedProfitLossSensor` from `/hist/v3/perf/`
  - `SaxoInvestmentPerformanceSensor` from `/hist/v4/performance/timeseries`
  - `SaxoCashTransferBalanceSensor` from `/hist/v4/performance/timeseries`
  - `SaxoTokenExpirySensor` - OAuth token expiration monitoring
  - `SaxoMarketStatusSensor` - Real-time market status detection
  - `SaxoLastUpdateSensor` - Successful data update timestamp tracking
  - `SaxoTimezoneSensor` - Timezone configuration and market hours display
- **Automatic Client ID Naming**: Entity names use actual Saxo Client ID (e.g., `saxo_123456_cash_balance`)
- **OAuth 2.0**: Secure authentication with Home Assistant credential management (production endpoints only)
- **Market Hours**: Dynamic update intervals (5 min market hours, 30 min after hours)
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
  - `sensor.saxo_123456_cash_transfer_balance`
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
- `sensor.py:56-59`: All ten entity classes instantiated in async_setup_entry (6 portfolio + 4 diagnostic)
- `sensor.py:520-722`: Performance sensor implementations (SaxoInvestmentPerformanceSensor, SaxoCashTransferBalanceSensor)
- `sensor.py:730-1105`: Diagnostic sensor implementations (Token, Market Status, Last Update, Timezone)
- `coordinator.py:657-677`: New getter methods for performance and cash transfer data
- `coordinator.py:472-502`: V4 performance API data fetching
- `diagnostics.py`: Comprehensive diagnostic information collection
- `api/saxo_client.py:464-502`: get_performance_v4() method for new endpoint
- `const.py:23`: API_PERFORMANCE_V4_ENDPOINT constant

## Recent Changes (v2.1.0)
- **Expanded to ten entities**: Added comprehensive portfolio monitoring with diagnostic capabilities
- **Diagnostic Sensors**: Four new diagnostic entities for real-time monitoring
  - Token Expiry sensor with countdown and status indicators
  - Market Status sensor showing current market state
  - Last Update sensor with timestamp tracking
  - Timezone sensor displaying configuration details
- **Comprehensive Diagnostics**: Built-in diagnostic information collection
- **Performance Sensors**: Investment performance (ReturnFraction * 100) and cash transfer balance
- **V4 API Integration**: Added `/hist/v4/performance/timeseries` endpoint support
- **Enhanced Data Coverage**: Now covers balance, performance, transfer, and system health data
- **Documentation Updates**: Updated CHANGELOG.md, README.md, and CLAUDE.md for new features

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