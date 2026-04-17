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
- Runtime state lives on `entry.runtime_data = SaxoRuntimeData(coordinator)` (not `hass.data[DOMAIN]`); see `__init__.py:65`.
- `SaxoApiClient` uses HA's shared websession (`async_get_clientsession(hass)`) — no per-integration session lifecycle.
- Update cadence is market-hours aware: 5 min during market hours, 30 min after (`const.py:44-45`).
- Performance data is cached for 2 h (`PERFORMANCE_UPDATE_INTERVAL`); performance-API failures must not block balance data (graceful degradation).

### Availability & resilience
- Sticky availability: sensors stay available during transient failures and only go unavailable after `max(15 min, 3 × update_interval)` of consecutive failures (`sensor.py:169`).
- Rate limiting: 0.5 s delay between batched API calls (`saxo_client.py:515`); 0–30 s random stagger across multi-account coordinators (`coordinator.py:146`).

### Entity conventions
- All entities use `_attr_has_entity_name = True` with `_attr_translation_key`; user-facing strings live in `strings.json` and icons in `icons.json`.
- Balance sensors: `state_class="total"`. Performance sensors: `state_class="measurement"` so HA records long-term statistics (`sensor.py:407,470,1167`).
- Position sensors are opt-in via the options flow.

## OAuth
- Config flow is test-before-configure: credentials are validated against the API before the entry is created.
- Reauth is handled in the GUI without removing the integration; token refresh fraction is 0.5 of lifetime (`const.py:179`).

<!-- MANUAL ADDITIONS START -->
# Important Instructions
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Always run ruff and Pylance checks and format before creating a new release
- Creating a new release includes updating documentation and CHANGELOG, creating and pushing a tag and finally creating a release on GitHub.
<!-- MANUAL ADDITIONS END -->
