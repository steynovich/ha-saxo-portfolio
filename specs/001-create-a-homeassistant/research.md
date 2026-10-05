# Research Findings: Saxo Portfolio Home Assistant Integration

## Technology Decisions

### Saxo OpenAPI Integration
> **Superseded**: the `saxo-openapi` package was dropped. The integration has no third-party requirements (`manifest.json` has `"requirements": []`). `SaxoApiClient` (`api/saxo_client.py`) calls the OpenAPI directly over Home Assistant's shared aiohttp session (`async_get_clientsession`), and Home Assistant's OAuth2 framework handles the token flow. The original decision is kept below for history.

**Original decision (superseded)**: Use `saxo-openapi` Python package with custom wrapper for Home Assistant compatibility
**Rationale**: 
- Most comprehensive Python SDK for Saxo OpenAPI
- Stable API with well-documented endpoints
- Handles OAuth 2.0 flow and token management
- Provides structured response objects

**Alternatives considered**:
- Direct HTTP requests with `aiohttp` - rejected due to complexity of OAuth flow (this became the chosen approach, since HA's OAuth2 helpers removed that complexity)
- `python-saxo` minimal wrapper - rejected due to limited documentation
- `saxo-apy` modern client - rejected due to lack of async support

### Home Assistant Integration Architecture
**Decision**: Custom integration with DataUpdateCoordinator pattern
**Rationale**:
- Standard Home Assistant pattern for API-based integrations
- Built-in rate limiting and error handling
- Automatic retry logic and authentication refresh
- Efficient data sharing across sensors

**Alternatives considered**:
- Simple sensor polling - rejected due to lack of coordination
- REST sensor platform - rejected due to OAuth complexity
- MQTT bridge - rejected due to unnecessary complexity

### Authentication Flow
**Decision**: OAuth 2.0 Authorization Code Grant for a confidential client (App Key and App Secret, no PKCE) with Home Assistant's OAuth2 framework and Application Credentials (ADR 0001, ADR 0005). Tokens are refreshed proactively at half their lifetime; reauthentication runs in the UI and must use the same Saxo account.
**Rationale**:
- Saxo requires OAuth 2.0 for API access
- Home Assistant provides built-in OAuth2 configuration flow
- Secure token storage in Home Assistant config system
- Automatic token refresh handling

**Alternatives considered**:
- Manual token configuration - rejected due to user experience
- API key authentication - not supported by Saxo
- Certificate-based auth - overly complex for user setup

## API Implementation Details

### Saxo OpenAPI Endpoints
**Key Endpoints for Portfolio Data**:
- `GET /openapi/port/v1/balances/me` - Account balances
- `GET /openapi/port/v1/positions` - Portfolio positions  
- `GET /openapi/port/v1/accounts` - Account information

**Rate Limits**:
- 120 requests per minute per session
- 10M requests per day per application
- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`

**Authentication URLs**:
- Simulation: `https://sim.logonvalidation.net/` (historical; not supported by the integration)
- Production: `https://live.logonvalidation.net` (the only environment the integration uses; Simulation is not supported, see README)
- API base: `https://gateway.saxobank.com/openapi`

### Data Structures
**Portfolio Balance Response**:
```json
{
    "CashBalance": 123456.18,
    "Currency": "USD", 
    "TotalValue": 125000.00,
    "UnrealizedMarginProfitLoss": 1543.82,
    "OpenPositionsCount": 5
}
```

**Position Response**:
```json
{
    "NetPositionId": "12345",
    "PositionBase": {
        "Amount": 100000,
        "AssetType": "FxSpot",
        "OpenPrice": 1.2345
    },
    "PositionView": {
        "CurrentPrice": 1.2355,
        "ProfitLossOnTrade": 100.00
    }
}
```

## Home Assistant Integration Patterns

### HACS Requirements
**Critical Finding**: No official "HACS Gold Status" exists
- HACS has validation requirements for community integrations
- "Gold status" confusion comes from Home Assistant Core tier system
- HACS validation focuses on: proper manifest, single integration, GitHub requirements

**HACS Validation Requirements**:
- Valid `manifest.json` with required fields
- Single integration per repository
- Public GitHub repo with description and topics
- `hacs.json` configuration file
- Proper documentation in README.md

### Sensor Implementation Constraints
**Important Limitation**: `device_class: monetary` cannot have `state_class`
- Financial sensors requiring statistics must choose between device class or state class
- Recommendation: Use `state_class: measurement` with currency units for tracking

### File Structure Requirements
```
custom_components/saxo_portfolio/
├── __init__.py              # Required: Integration initialization
├── manifest.json            # Required: Integration metadata
├── config_flow.py          # Required: OAuth configuration UI
├── coordinator.py          # Required: Data fetching coordination
├── sensor.py               # Required: Sensor platform
├── const.py                # Required: Constants
└── strings.json            # Required: UI translations
hacs.json                    # Required: HACS configuration (repository root)
# Also present in the real integration: application_credentials.py, button.py,
# data.py, performance.py, positions.py, diagnostics.py, token_expiry.py, icons.json
```

## Performance and Scalability

### Update Intervals
**Decision**: Dynamic intervals based on market hours
- Market hours: 5-minute updates
- After hours: 30-minute updates
- Fixed intervals (`DEFAULT_UPDATE_INTERVAL_MARKET_HOURS` / `DEFAULT_UPDATE_INTERVAL_AFTER_HOURS`); the interval is not user-configurable (ADR 0004)
- Performance data is cached for 2 h and fetched separately; positions are opt-in

**Rationale**: Balances API responsiveness with rate limit conservation

### Memory and Performance
**Targets**:
- <100MB memory usage total
- <5 second sensor update latency
- Minimal Home Assistant core impact

### Error Handling Strategy
**Decision**: Graceful degradation with user notifications
- OAuth token refresh automatic
- API rate limit respect with backoff
- Network error retry with exponential backoff
- User-friendly error messages in Home Assistant UI

## Security Considerations

### Credential Storage
**Decision**: Use Home Assistant's built-in secure storage
- OAuth tokens stored in Home Assistant config system
- No credentials in code or logs
- Automatic token refresh without user intervention

### API Security
**Implementation**:
- HTTPS only for all API communications
- OAuth state parameter for CSRF protection
- Token scope limitation to read-only portfolio access
- Secure redirect URI validation

## Testing Strategy

### Test Categories
1. **Unit Tests**: Individual component testing with mocks
2. **Integration Tests**: OAuth flow and API communication
3. **Contract Tests**: Saxo API response validation
4. **End-to-End Tests**: Full integration in Home Assistant test environment

### Mock Strategy
- Tests run against mocked API responses; no live or simulation Saxo account is needed
- Mock API responses for automated testing
- CI runs the mocked test suite (`pytest-homeassistant-custom-component`)

## Dependencies and Compatibility

### Python Dependencies
- No runtime requirements beyond Home Assistant (`manifest.json`: `"requirements": []`, `"dependencies": ["application_credentials"]`)
- `aiohttp` - Async HTTP (Home Assistant dependency)
- Development: `homeassistant>=2026.3.0`, `pytest-homeassistant-custom-component` (see `pyproject.toml`)

### Home Assistant Compatibility
- Minimum version: 2026.3.0 (`hacs.json`, `pyproject.toml`)
- Python 3.14+ requirement (`requires-python = ">=3.14.2"`)
- Async/await pattern throughout

### Browser Compatibility
- OAuth flow requires modern browser for configuration
- Redirect URI must be accessible from user's network
- Mobile device configuration support via Home Assistant app