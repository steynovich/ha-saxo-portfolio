# Tasks: Saxo Portfolio Home Assistant Integration

**Input**: Design documents from `/specs/001-create-a-homeassistant/`
**Prerequisites**: plan.md (✓), research.md (✓), data-model.md (✓), contracts/ (✓)

## Execution Flow (main)
```
1. Load plan.md from feature directory ✓
   → Tech stack: Python 3.11+, Home Assistant, saxo-openapi, pytest
   → Structure: Single project (Home Assistant integration)
2. Load design documents: ✓
   → data-model.md: Portfolio, Account, Position, Sensor entities
   → contracts/: Saxo API and Home Assistant integration contracts
   → quickstart.md: OAuth setup, validation scenarios
3. Generate tasks by category ✓
   → Setup: Home Assistant integration structure, dependencies
   → Tests: Contract tests, OAuth flow, sensor creation, data refresh
   → Core: Models, coordinator, API client, sensors
   → Integration: Config flow, authentication, HACS compliance
   → Polish: Unit tests, documentation, validation
4. Task rules applied ✓
   → Different files = [P] for parallel execution
   → Same file = sequential (no [P])
   → Tests before implementation (TDD)
5. Tasks numbered T001-T032 ✓
6. Dependencies validated ✓
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
- **Home Assistant Integration**: `custom_components/saxo_portfolio/` at repository root
- **Tests**: `tests/` with contract/, integration/, unit/ subdirectories
- All paths are absolute from repository root `/Users/steyn/projects/ha-saxo/`

## Phase 3.1: Setup
- [ ] **T001** Create Home Assistant integration directory structure `custom_components/saxo_portfolio/` with required subdirectories
- [ ] **T002** Initialize Python project with Home Assistant dependencies (homeassistant>=2024.1.0, saxo-openapi, aiohttp, pytest)
- [ ] **T003** [P] Configure pytest, ruff linting, and mypy type checking in project root

## Phase 3.2: Contract Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### Saxo API Contract Tests
- [ ] **T004** [P] Contract test for Saxo balance endpoint in `tests/contract/test_saxo_balance_contract.py`
- [ ] **T005** [P] Contract test for Saxo positions endpoint in `tests/contract/test_saxo_positions_contract.py` 
- [ ] **T006** [P] Contract test for Saxo accounts endpoint in `tests/contract/test_saxo_accounts_contract.py`

### Home Assistant Integration Contract Tests  
- [ ] **T007** [P] Contract test for DataUpdateCoordinator interface in `tests/contract/test_coordinator_contract.py`
- [ ] **T008** [P] Contract test for sensor state schema in `tests/contract/test_sensor_contract.py`
- [ ] **T009** [P] Contract test for config flow data schema in `tests/contract/test_config_flow_contract.py`

### Integration Tests (User Stories)
- [ ] **T010** [P] Integration test for OAuth authentication flow in `tests/integration/test_oauth_flow.py`
- [ ] **T011** [P] Integration test for sensor creation and updates in `tests/integration/test_sensor_creation.py`
- [ ] **T012** [P] Integration test for data refresh cycle in `tests/integration/test_data_refresh.py`
- [ ] **T013** [P] Integration test for error handling and recovery in `tests/integration/test_error_handling.py`

## Phase 3.3: Core Implementation (ONLY after tests are failing)

### Core Data Models and Services
- [ ] **T014** [P] Portfolio data model in `custom_components/saxo_portfolio/models.py`
- [ ] **T015** [P] Constants and configuration in `custom_components/saxo_portfolio/const.py`
- [ ] **T016** [P] Saxo API client wrapper in `custom_components/saxo_portfolio/api/saxo_client.py`
- [ ] **T017** DataUpdateCoordinator implementation in `custom_components/saxo_portfolio/coordinator.py`

### Home Assistant Integration Files
- [ ] **T018** Integration manifest in `custom_components/saxo_portfolio/manifest.json`
- [ ] **T019** Integration initialization in `custom_components/saxo_portfolio/__init__.py`
- [ ] **T020** OAuth configuration flow in `custom_components/saxo_portfolio/config_flow.py`
- [ ] **T021** Sensor platform implementation in `custom_components/saxo_portfolio/sensor.py`

### Translation and Configuration
- [ ] **T022** [P] UI text translations in `custom_components/saxo_portfolio/strings.json`
- [ ] **T023** [P] Application credentials platform in `custom_components/saxo_portfolio/application_credentials.py`

## Phase 3.4: Integration and Authentication
- [ ] **T024** OAuth token storage and refresh logic in coordinator
- [ ] **T025** Rate limiting and error handling in API client
- [ ] **T026** Sensor state management and Home Assistant device registry
- [ ] **T027** Dynamic update intervals (market hours vs after hours)

## Phase 3.5: HACS Compliance and Documentation
- [ ] **T028** [P] HACS configuration in `hacs.json`
- [ ] **T029** [P] Integration README with setup instructions in `README.md`
- [ ] **T030** [P] GitHub repository configuration (topics, description, issues)

## Phase 3.6: Polish and Validation
- [ ] **T031** [P] Unit tests for validation logic in `tests/unit/test_validation.py`
- [ ] **T032** Run quickstart validation scenarios from quickstart.md

## Dependencies
```
Setup (T001-T003) → Contract Tests (T004-T013) → Core Implementation (T014-T023) → Integration (T024-T027) → HACS/Docs (T028-T030) → Polish (T031-T032)

Specific blocking dependencies:
- T015 (const.py) blocks T016, T017, T020, T021
- T016 (API client) blocks T017 (coordinator)
- T017 (coordinator) blocks T019, T021
- T018 (manifest) blocks T019
- T020 (config_flow) blocks T019
- All tests (T004-T013) must FAIL before implementation (T014-T027)
```

## Parallel Execution Examples

### Phase 3.2: Launch all contract tests together
```bash
# All contract tests can run in parallel (different files)
Task: "Contract test for Saxo balance endpoint in tests/contract/test_saxo_balance_contract.py"
Task: "Contract test for Saxo positions endpoint in tests/contract/test_saxo_positions_contract.py"  
Task: "Contract test for Saxo accounts endpoint in tests/contract/test_saxo_accounts_contract.py"
Task: "Contract test for DataUpdateCoordinator interface in tests/contract/test_coordinator_contract.py"
Task: "Contract test for sensor state schema in tests/contract/test_sensor_contract.py"
Task: "Contract test for config flow data schema in tests/contract/test_config_flow_contract.py"
```

### Phase 3.2: Launch all integration tests together
```bash
# All integration tests can run in parallel (different files)
Task: "Integration test for OAuth authentication flow in tests/integration/test_oauth_flow.py"
Task: "Integration test for sensor creation and updates in tests/integration/test_sensor_creation.py"
Task: "Integration test for data refresh cycle in tests/integration/test_data_refresh.py"
Task: "Integration test for error handling and recovery in tests/integration/test_error_handling.py"
```

### Phase 3.3: Launch independent model/config files together
```bash
# These files are independent and can be created in parallel
Task: "Portfolio data model in custom_components/saxo_portfolio/models.py"
Task: "Constants and configuration in custom_components/saxo_portfolio/const.py" 
Task: "Saxo API client wrapper in custom_components/saxo_portfolio/api/saxo_client.py"
Task: "Integration manifest in custom_components/saxo_portfolio/manifest.json"
Task: "UI text translations in custom_components/saxo_portfolio/strings.json"
Task: "Application credentials platform in custom_components/saxo_portfolio/application_credentials.py"
```

### Phase 3.5: Launch all documentation tasks together
```bash
# Documentation tasks are independent
Task: "HACS configuration in hacs.json"
Task: "Integration README with setup instructions in README.md"
Task: "GitHub repository configuration (topics, description, issues)"
```

## File-Specific Task Groups
**Files that cannot be edited in parallel** (sequential execution required):
- `custom_components/saxo_portfolio/coordinator.py`: T017 → T024
- `custom_components/saxo_portfolio/__init__.py`: T019 must wait for T017, T018, T020
- `custom_components/saxo_portfolio/config_flow.py`: T020 → part of T024
- `custom_components/saxo_portfolio/sensor.py`: T021 → T026

## Validation Checklist
*GATE: Verified before task execution*

- [x] All contracts have corresponding tests (T004-T009 cover both contracts)
- [x] All entities have model tasks (T014 covers Portfolio, Account, Position, Sensor)
- [x] All tests come before implementation (T004-T013 before T014-T027)
- [x] Parallel tasks truly independent (verified file paths don't conflict)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task

## Task Generation Rules Applied
*Applied during main() execution*

1. **From Contracts**: ✓
   - saxo_api_contract.yaml → T004, T005, T006 (3 contract tests)
   - home_assistant_integration_contract.yaml → T007, T008, T009 (3 contract tests)
   - OAuth endpoints → T010 integration test
   
2. **From Data Model**: ✓
   - Portfolio, Account, Position, Sensor entities → T014 (models.py)
   - DataUpdateCoordinator interface → T017
   - API client interface → T016
   
3. **From User Stories (quickstart.md)**: ✓
   - OAuth setup → T010 (auth flow test)
   - Sensor verification → T011 (sensor creation test)  
   - Data refresh → T012 (data refresh test)
   - Error handling → T013 (error handling test)
   - Manual validation → T032 (quickstart scenarios)

4. **From Technical Context**: ✓
   - Home Assistant integration structure → T001, T018, T019
   - HACS Gold requirements → T028, T029, T030
   - Python/pytest setup → T002, T003, T031

## Notes
- [P] tasks = different files, no shared dependencies
- Verify all contract/integration tests FAIL before implementing (RED phase of TDD)
- Commit after each task completion
- Home Assistant integration follows single project structure
- OAuth 2.0 flow uses Home Assistant's built-in framework
- Dynamic update intervals: 5min (market hours) / 30min (after hours)
- HACS validation requirements incorporated in T028-T030