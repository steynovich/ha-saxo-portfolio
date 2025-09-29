# ha-saxo Development Guidelines

Auto-generated from current implementation. Last updated: 2025-09-18

## Active Technologies
- Home Assistant Custom Integration
- OAuth 2.0 Authentication
- Saxo Bank OpenAPI
- Python 3.13+
- HACS Compatible

## Project Structure
```
custom_components/saxo_portfolio/
├── __init__.py                 # Integration setup
├── config_flow.py             # OAuth configuration flow with prefix support
├── coordinator.py             # Data update coordinator with market hours logic
├── sensor.py                  # Sixteen optimized sensors with shared base classes and automatic client ID naming
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
- **Optimized Architecture**: Shared base classes reduce code duplication by 31% while maintaining all functionality

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

### Conditional Sensor Creation
- **Unknown Client Name Protection**: Sensors are only created when client data is successfully retrieved from the Saxo API
- **Automatic Retry**: If client name is "unknown" during initial setup, sensor creation is skipped and automatically retried when client data becomes available
- **Config Entry Reload**: The integration automatically reloads the config entry when client data changes from "unknown" to a valid client name
- **Device Registration**: Home Assistant devices are only registered once valid client information is available, preventing orphaned devices
- **Enhanced Logging**: Clear warning messages when sensor setup is skipped due to unknown client data, with guidance for users

### Sticky Availability System

#### Enhanced Availability Logic
The integration implements a sophisticated "sticky availability" system to prevent sensors from flashing unavailable during normal coordinator updates:

**Problem Solved**: Home Assistant's `DataUpdateCoordinator` temporarily sets `last_update_success = False` at the start of each update cycle, causing sensors to briefly show as unavailable every 5-30 minutes.

**Solution**: Multi-tiered availability logic in `SaxoSensorBase.available` (Lines 84-123):

1. **Immediate Unavailable**: No data at all → `False`
2. **Immediate Available**: Current update successful → `True`
3. **Sticky Logic**: Update in progress but recent success → Check failure threshold
4. **Failure Threshold**: 15+ minutes OR 3+ failed update cycles → `False`

**Threshold Calculation**:
```python
max_failure_time = max(15 * 60, 3 * update_interval_seconds)
```

**Benefits**:
- ✅ No UI flashing during normal 1-2 second API updates
- ✅ Quick detection of real authentication/network issues
- ✅ Adaptive thresholds (market hours: 5min, after hours: 30min)
- ✅ Graceful first startup and sustained failure handling

**Enhanced Sensors**:
- `SaxoAccumulatedProfitLossSensor`: Base availability + data validation
- `SaxoPerformanceSensorBase`: Base availability + performance value validation
- `SaxoCashTransferBalanceSensor`: Base availability + specific data checks

### Optimized Sensor Architecture

#### Base Class Hierarchy
- **`SaxoSensorBase`** (Lines 29-104): Common functionality for all sensors
  - Unified entity naming, device_info, basic attributes, lifecycle methods
  - Consolidates 200+ lines of duplicated code across all sensors
- **`SaxoBalanceSensorBase`** (Lines 106-173): Specialized for monetary balance sensors
  - Inherits from SaxoSensorBase, adds currency handling and validation
  - Used by: Cash Balance, Total Value, Non-Margin Positions, Cash Transfer Balance
- **`SaxoDiagnosticSensorBase`** (Lines 175-199): Specialized for diagnostic sensors
  - Inherits from SaxoSensorBase, sets EntityCategory.DIAGNOSTIC
  - Used by: Client ID, Account ID, Name, Token Expiry, Market Status, Last Update, Timezone
- **`SaxoPerformanceSensorBase`** (Lines 340-502): Enhanced performance sensor base
  - Inherits from SaxoSensorBase, adds time period handling and performance caching
  - Used by: Investment Performance (All/YTD/Month/Quarter time periods)

#### Optimized Sensor Implementations
- **Balance Sensors** (~10 lines each, was ~100): SaxoCashBalanceSensor, SaxoTotalValueSensor, SaxoNonMarginPositionsValueSensor, SaxoCashTransferBalanceSensor
- **Performance Sensors** (~15 lines each): SaxoInvestmentPerformanceSensor, SaxoYTDInvestmentPerformanceSensor, SaxoMonthInvestmentPerformanceSensor, SaxoQuarterInvestmentPerformanceSensor
- **Diagnostic Sensors** (~15-25 lines each, was ~40-60): SaxoClientIDSensor, SaxoAccountIDSensor, SaxoNameSensor, SaxoTokenExpirySensor, SaxoMarketStatusSensor, SaxoLastUpdateSensor, SaxoTimezoneSensor
- **Special Sensors** (~30 lines): SaxoAccumulatedProfitLossSensor (inherits from SaxoSensorBase with custom logic)

### Key Files
- `sensor.py:201-243`: All sixteen entity classes instantiated in async_setup_entry
- `sensor.py:29-199`: Shared base class hierarchy (SaxoSensorBase, SaxoBalanceSensorBase, SaxoDiagnosticSensorBase)
- `sensor.py:84-123`: Enhanced availability logic with sticky availability to prevent UI flashing
- `sensor.py:340-502`: Enhanced performance sensor base class with time period handling
- `sensor.py:247-286`: Optimized balance sensor implementations using base classes
- `sensor.py:634-678`: Optimized diagnostic sensor implementations using base classes
- `coordinator.py:132-151`: Performance cache validation logic (_should_update_performance_data)
- `coordinator.py:484-618`: Smart performance data caching with hourly updates
- `coordinator.py:57`: Last successful update tracking (_last_successful_update)
- `coordinator.py:866-869`: Last successful update time property accessor
- `coordinator.py:790-799`: Account ID getter method (get_account_id)
- `coordinator.py:634`: Account ID data extraction from balance API
- `diagnostics.py`: Comprehensive diagnostic information collection
- `api/saxo_client.py:464-501`: get_performance_v4() method for all-time performance
- `api/saxo_client.py:502-540`: get_performance_v4_ytd() method for year-to-date performance
- `const.py:118`: PERFORMANCE_UPDATE_INTERVAL constant (1 hour)
- `tests/integration/test_sticky_availability.py`: Comprehensive tests for availability behavior

## Recent Changes (v2.2.5+)
- **Enhanced Timeout Handling**: Significantly improved network resilience and error reporting
  - Increased coordinator timeout from 30s to 90s in `const.py:161` for multiple API calls
  - Added progressive timeouts: Balance (45s), Performance (60s), Client Info (30s) in `const.py:156-158`
  - Enhanced timeout error handling in `coordinator.py:876-903` with timing context and user guidance
  - Smart timeout warning system: first occurrence as WARNING, subsequent as DEBUG for 5 minutes
  - Comprehensive request timing logs in `coordinator.py:544-545` and `coordinator.py:862-863`
  - Progressive timeout implementation in `coordinator.py:541-542`, `633`, `662`, `716`, `205`
  - Improved error recovery with actionable network connectivity guidance

## Recent Changes (v2.2.4+)
- **Logging Optimization**: Improved log cleanliness by reducing verbose OAuth token management messages
  - Changed "Token expires very soon, immediate refresh needed" from WARNING to DEBUG level in `coordinator.py:308`
  - Token refresh operations are normal behavior that don't require user attention
  - Cleaner Home Assistant logs with reduced noise from routine OAuth operations
  - Enhanced user experience with less verbose logging for standard operations

## Recent Changes (v2.2.3+)
- **Conditional Sensor Creation**: Enhanced integration robustness with unknown client name protection
  - Sensors are only created when valid client data is available from the Saxo API
  - Automatic config entry reload when client data becomes available via `coordinator.py:919-939`
  - Sensor setup validation in `sensor.py:273-282` checks for unknown client names
  - Enhanced error handling with clear user guidance via warning messages
  - Prevents orphaned devices and entities when API authentication initially fails
  - Sensor initialization tracking via `coordinator.py:1108-1114` prevents unnecessary reloads
  - Comprehensive test coverage in `tests/integration/test_sensor_creation.py:214-294`

## Recent Changes (v2.1.8+)
- **Enhanced Resource Management**: Improved HTTP client session handling during token refresh with comprehensive error handling
  - Enhanced fix for "Unclosed client session" errors during OAuth token refresh cycles
  - Added dedicated `_close_old_client()` method with proper error handling and logging via `coordinator.py:146-154`
  - Improved `api_client` property with safer old client closure handling via `coordinator.py:94-106`
  - Enhanced token comparison logic to detect when client needs recreation
  - Uses `async_create_task()` for proper async cleanup of old client sessions with error recovery
  - Prevents memory leaks and improves long-term resource management with comprehensive logging

## Recent Changes (v2.1.6+)
- **Comprehensive Test Suite Optimization**: Updated all tests to reflect architecture improvements
  - Contract tests validate new base class hierarchy and shared functionality
  - Integration tests verify sticky availability behavior across all sensor types
  - Removed test dependencies on non-existent sensor classes
  - Added comprehensive test coverage for availability edge cases
  - Test files properly formatted and follow pytest best practices
- **Documentation Update**: Enhanced technical documentation with detailed architecture information
  - Updated CLAUDE.md with complete base class hierarchy details
  - Added comprehensive availability system documentation with code examples
  - Updated file references and line numbers for accuracy
  - Enhanced troubleshooting and development guidelines

## Recent Changes (v2.1.5)
- **Improved Sensor Availability During Updates**: Fixed sensors briefly showing as unavailable during coordinator updates
  - Implemented "sticky availability" logic that keeps sensors available during normal update cycles
  - Sensors only become unavailable after sustained failures (15+ minutes or 3 failed update cycles)
  - Prevents UI flashing and maintains stable sensor states during API fetches
  - Graceful handling of startup scenarios and genuine failures
  - Enhanced availability logic in `SaxoSensorBase`, `SaxoAccumulatedProfitLossSensor`, `SaxoPerformanceSensorBase`, and `SaxoCashTransferBalanceSensor`
- **Device Info Cleanup**: Removed firmware version from device information display
  - Explicitly set `sw_version=None` in `DeviceInfo` to prevent automatic version display
  - Cleaner device presentation in Home Assistant UI

## Previous Changes (v2.1.4+)
- **Major Sensor Architecture Optimization**: Implemented shared base class hierarchy
  - Reduced code duplication by 31% (from 1,472+ lines to 1,017 lines)
  - Created `SaxoSensorBase` for common functionality across all sensors
  - Created `SaxoBalanceSensorBase` for monetary balance sensors with currency handling
  - Created `SaxoDiagnosticSensorBase` for diagnostic sensors with proper categorization
  - Enhanced `SaxoPerformanceSensorBase` to inherit from `SaxoSensorBase`
  - Maintained all existing functionality while improving maintainability
  - Balance sensors reduced from ~100 lines each to ~10 lines each
  - Diagnostic sensors reduced from ~40-60 lines each to ~15-25 lines each
  - All tests updated to reflect the new optimized architecture

## Previous Changes (v2.1.2+)
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
- Always run ruff and Pylance checks and format before creating a new release