# ha-saxo Development Guidelines

Auto-generated from current implementation. Last updated: 2025-09-11

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
├── sensor.py                  # CashBalance and TotalValue sensors with custom prefixes
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
- **Two Sensors**: `SaxoCashBalanceSensor` and `SaxoTotalValueSensor` from `/port/v1/balances/me` endpoint
- **Custom Prefixes**: User-defined prefixes with `saxo_` base (e.g., `saxo_mybank_cash_balance`, `saxo_mybank_total_value`)
- **OAuth 2.0**: Secure authentication with Home Assistant credential management (production endpoints only)
- **Market Hours**: Dynamic update intervals (5 min market hours, 30 min after hours)
- **Rate Limiting**: Intelligent API throttling with exponential backoff

### Entity Naming Pattern
- Default: `sensor.saxo_cash_balance` + `sensor.saxo_total_value`
- Custom: `sensor.saxo_{user_prefix}_cash_balance` + `sensor.saxo_{user_prefix}_total_value`
- Device: `"Saxo Portfolio"` or `"Saxo {UserPrefix} Portfolio"`

### Configuration Options
- `CONF_ENTITY_PREFIX`: User-defined prefix (default: "saxo")
- Production endpoints only (no environment selection)
- Automatic token refresh with proper security handling

### Key Files
- `sensor.py:59-65`: Entity prefix logic combining `saxo_` with user input
- `sensor.py:179-305`: SaxoTotalValueSensor implementation
- `coordinator.py:403-423`: get_cash_balance() and get_total_value() methods
- `config_flow.py`: Simplified OAuth flow without environment selection
- `api/saxo_client.py:333-377`: Balance endpoint handling (CashBalance + TotalValue)

## Recent Changes
- Simplified to two sensors: CashBalance and TotalValue from balance endpoint
- Removed positions and accounts functionality (no longer supported)
- Added user-defined entity prefix functionality
- Removed environment selection - production endpoints only
- Enhanced entity naming with saxo_ base prefix pattern
- Removed unused imports and cleaned up codebase

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