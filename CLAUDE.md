# ha-saxo Development Guidelines

## Technologies
- Home Assistant Custom Integration (HACS compatible)
- OAuth 2.0 Authentication with Saxo Bank OpenAPI
- Python 3.13+

## Project Structure
```
custom_components/saxo_portfolio/
├── __init__.py           # Integration setup, service registration
├── button.py             # Refresh button entity
├── config_flow.py        # OAuth configuration flow
├── coordinator.py        # Data update coordinator with market hours logic
├── sensor.py             # Sensors with shared base classes
├── const.py              # Constants and configuration
├── services.yaml         # Service definitions
├── application_credentials.py
└── api/saxo_client.py    # API client with rate limiting
tests/
├── contract/             # API contract tests
├── integration/          # End-to-end tests
└── test_structure.py     # Repository structure validation
```

## Commands
```bash
ruff check .              # Linting
ruff format .             # Formatting
python -m pytest tests/   # Run tests
```

## Code Style
- Follow Home Assistant integration standards
- Type hints throughout (Python 3.11+ syntax)
- Comprehensive error handling with sanitized logging

## Sensors

### Balance Sensors (from `/port/v1/balances/me`)
- `SaxoCashBalanceSensor`, `SaxoTotalValueSensor`, `SaxoNonMarginPositionsValueSensor`

### Performance Sensors (from `/hist/v4/performance/timeseries`)
- `SaxoInvestmentPerformanceSensor` (all-time), `SaxoYTDInvestmentPerformanceSensor`
- `SaxoMonthInvestmentPerformanceSensor`, `SaxoQuarterInvestmentPerformanceSensor`
- `SaxoAccumulatedProfitLossSensor` (from `/hist/v3/perf/`)
- `SaxoCashTransferBalanceSensor`
- All performance sensors support long-term statistics (`state_class="measurement"`)

### Diagnostic Sensors
- `SaxoClientIDSensor`, `SaxoAccountIDSensor`, `SaxoNameSensor`
- `SaxoTokenExpirySensor`, `SaxoMarketStatusSensor`, `SaxoLastUpdateSensor`, `SaxoTimezoneSensor`

### Position Sensors (opt-in via options flow)
- `SaxoPositionSensor` - One per portfolio position with price as state
- `SaxoMarketDataAccessSensor` - Market data access status

### Other Entities
- `SaxoRefreshButton` - Manual data refresh
- `saxo_portfolio.refresh_data` service

## Entity Naming
Pattern: `sensor.saxo_{client_id}_{sensor_type}`
Device: `"Saxo {ClientId} Portfolio"`

## Architecture

### Sensor Base Classes
- `SaxoSensorBase` - Common functionality for all sensors
- `SaxoBalanceSensorBase` - Monetary sensors with currency handling, `state_class="total"`
- `SaxoDiagnosticSensorBase` - EntityCategory.DIAGNOSTIC
- `SaxoPerformanceSensorBase` - Time period handling, caching, and long-term statistics (`state_class="measurement"`)

### Key Behaviors
- **Market Hours**: 5 min updates during market hours, 30 min after hours
- **Performance Caching**: 2-hour cache for performance data
- **Long-Term Statistics**: Performance sensors support HA statistics for historical tracking
- **Sticky Availability**: Sensors stay available during updates, unavailable after 15+ min failures
- **Graceful Degradation**: Performance API failures don't block balance data
- **GUI Reauthentication**: OAuth reauth without removing integration

### Rate Limiting
- Batched API calls with 0.5s delays
- Staggered multi-account updates (0-30s random offset)
- 2-hour performance cache interval

## Key Files Reference
- `sensor.py`: Base classes (lines 29-228), sensor implementations
- `coordinator.py`: Data fetching, OAuth token refresh, performance caching
- `api/saxo_client.py`: API client with `get_performance_v4_batch()`

## Security
- OAuth 2.0 with CSRF protection (`secrets.token_urlsafe(32)`)
- Data masking for sensitive information in logs
- Type-safe cache management with dataclasses

<!-- MANUAL ADDITIONS START -->
# Important Instructions
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Always run ruff and Pylance checks and format before creating a new release
- Creating a new release includes updating documentation and CHANGELOG, creating and pushing a tag and finally creating a release on GitHub.
<!-- MANUAL ADDITIONS END -->
