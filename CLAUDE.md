# ha-saxo Development Guidelines

## Technologies
- Home Assistant custom integration (HACS compatible)
- OAuth 2.0 against the Saxo Bank OpenAPI
- Python 3.14+

## Code Style
- Follow Home Assistant integration standards
- Strict mypy everywhere (`py.typed` marker, Python 3.14+ syntax)
- Sanitized logging — never leak tokens, client IDs, or balances

## Architecture — non-obvious decisions

### Runtime & data flow
- Runtime state lives on `entry.runtime_data = SaxoRuntimeData(coordinator)` (not `hass.data[DOMAIN]`); set in `async_setup_entry` in `__init__.py`.
- Coordinator data is typed: `SaxoPortfolioData` (`data.py`), `None` before the first update. Sensors read it through typed value functions; never index it by string key.
- API response parsing lives outside `coordinator.py`: balance in `data.py`, client details + performance in `performance.py` (`PerformanceFetcher`), net positions in `positions.py` (`PositionsFetcher`). The coordinator only schedules, keeps the token valid and assembles the data.
- `SaxoApiClient` uses HA's shared websession (`async_get_clientsession(hass)`) — no per-integration session lifecycle.
- Update cadence is market-hours aware: 5 min during market hours, 30 min after (`DEFAULT_UPDATE_INTERVAL_MARKET_HOURS` / `DEFAULT_UPDATE_INTERVAL_AFTER_HOURS`).
- Performance data is cached for 2 h (`PERFORMANCE_UPDATE_INTERVAL`, in `PerformanceFetcher`); performance-API failures must not block balance data (graceful degradation). Only a complete fetch refreshes the cache timestamp; a partial one keeps last good values and retries after `PERFORMANCE_RETRY_INTERVAL` (15 min).

### Availability & resilience
- Sticky availability: sensors stay available during transient failures and only go unavailable after `max(15 min, 3 × update_interval)` of consecutive failures (`AVAILABILITY_FAILURE_*` constants in `const.py`, applied in `sensor.py`).
- Rate limiting: 0.5 s delay between batched API calls (`API_REQUEST_DELAY` in `const.py`, used by `api/saxo_client.py`, `performance.py` and `positions.py`); 0–30 s random stagger across multi-account coordinators (`_initial_update_offset` in `coordinator.py`).

### Entity conventions
- All entities use `_attr_has_entity_name = True` with `_attr_translation_key`; user-facing strings live in `strings.json` and icons in `icons.json`.
- Balance sensors: `SensorStateClass.TOTAL`. Performance sensors: `SensorStateClass.MEASUREMENT` so HA records long-term statistics (`sensor.py`).
- Position sensors are opt-in via the options flow.

## OAuth
- Config flow is test-before-configure: credentials are validated against the API before the entry is created.
- Reauth is handled in the GUI without removing the integration; token refresh fraction is 0.5 of lifetime (`REFRESH_TOKEN_REFRESH_AT_FRACTION`).

<!-- MANUAL ADDITIONS START -->
# Important Instructions
Keep changes to what was asked. Prefer editing existing files over creating new ones, and only add documentation or README files when asked (release docs below are part of the release task).
- Before creating a release, run `ruff check`, `ruff format`, and `mypy custom_components/saxo_portfolio/`.
- Creating a new release includes updating documentation and CHANGELOG, creating and pushing a tag and finally creating a release on GitHub.
<!-- MANUAL ADDITIONS END -->
