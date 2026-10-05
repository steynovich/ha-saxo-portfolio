# Implementation Plan: Saxo Portfolio Home Assistant Integration

**Branch**: `001-create-a-homeassistant` | **Spec**: [spec.md](spec.md)
**Status**: Implemented and released. This plan replaces the unfilled template; it describes the architecture as built. Authoritative sources: `CLAUDE.md` (Architecture), `README.md` and `docs/adr/`.

## Summary
A HACS-installable Home Assistant custom integration that exposes Saxo Bank portfolio balances, performance and (opt-in) positions as sensors. It authenticates with the OAuth 2.0 Authorization Code grant for a confidential client (no PKCE) through Home Assistant Application Credentials, and polls the Saxo OpenAPI on a market-hours-aware schedule.

## Technical Context
- **Language/Version**: Python 3.14+ (`requires-python >=3.14.2`), strict mypy, `py.typed`
- **Home Assistant**: 2026.3.0 or later (`hacs.json`, `pyproject.toml`)
- **Dependencies**: none beyond Home Assistant (`manifest.json` has `"requirements": []` and `"dependencies": ["application_credentials"]`); HA's shared aiohttp session is used for API calls
- **Storage**: config entry (token, entity prefix, timezone) and options; no extra storage. Long-term statistics are left to Home Assistant
- **Testing**: pytest with `pytest-homeassistant-custom-component`, mocked Saxo responses; ruff and mypy in CI
- **Target platform**: Home Assistant (cloud polling, `integration_type: service`), production Saxo environment only
- **Constraints**: respect Saxo rate limits (0.5 s between batched calls), no secrets, tokens or balances in logs

## Architecture
- **Runtime state**: `entry.runtime_data = SaxoRuntimeData(coordinator)`, set in `async_setup_entry` (`__init__.py`); not `hass.data[DOMAIN]`.
- **Coordinator** (`coordinator.py`): schedules updates, keeps the token valid and assembles the data. It does not parse API responses.
- **Typed data** (`data.py`): `SaxoPortfolioData` (`BalanceData`, `PerformanceData`, `ClientInfo`); sensors read typed attributes. See [data-model.md](data-model.md).
- **Fetchers**: balance in `data.py`; client details and performance in `performance.py` (`PerformanceFetcher`, 2 h cache); net positions in `positions.py` (`PositionsFetcher`).
- **API client** (`api/saxo_client.py`): `SaxoApiClient` over `async_get_clientsession(hass)`; no SDK.
- **Auth** (`application_credentials.py`, `config_flow.py`): user supplies App Key and Secret through Application Credentials; the config flow validates against the API before creating the entry; tokens refresh at 0.5 of their lifetime (`REFRESH_TOKEN_REFRESH_AT_FRACTION`); reauthentication works in the UI and must use the same Saxo account (ADR 0001, ADR 0005).
- **Platforms**: `sensor.py` (balance `TOTAL`, performance and position `MEASUREMENT`; diagnostic sensors), `button.py` (refresh, reauthenticate), `services.yaml` (`refresh_data`), `diagnostics.py`. Strings in `strings.json`, icons in `icons.json`; all entities use `has_entity_name` with translation keys.
- **Entity IDs**: built from the Saxo Client ID, e.g. `sensor.saxo_123456_cash_balance`.

## Behaviour decisions (see ADRs)
- **Polling** (ADR 0004): 5 min during market hours, 30 min after hours (15 min in "Any" timezone mode); fixed, not configurable. The market timezone is an option, changeable live.
- **Availability** (ADR 0002): sensors stay available through transient failures and go unavailable after `max(15 min, 3 x update_interval)` of consecutive failures.
- **Graceful degradation** (ADR 0003): performance failures never block balance data; only a complete fetch refreshes the cache timestamp.
- **Position sensors** are opt-in via the options flow.
- **Rate limiting**: `API_REQUEST_DELAY` between batched calls, plus a 0-30 s random stagger across multi-account coordinators.

## Structure
```
custom_components/saxo_portfolio/   # integration (see Architecture)
tests/                              # pytest suite with mocked API responses
docs/adr/                           # architecture decision records
specs/001-create-a-homeassistant/   # this feature's spec, research, data model, contracts, quickstart, tasks
hacs.json, README.md, CHANGELOG.md  # HACS and user docs
```

## Phases
Research ([research.md](research.md)), design ([data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)) and the task list ([tasks.md](tasks.md)) were produced for v1 and then kept in line with the code. The tasks list is historical; ongoing work is tracked in GitHub issues and the CHANGELOG.
