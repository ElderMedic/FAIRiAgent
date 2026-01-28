# FAIRiAgent Test Suite

This directory contains unit tests for the FAIRiAgent framework.

## Test Files

### `test_confidence_aggregator.py`
Tests for confidence aggregation functionality that combines critic scores, structural metrics, and validation results.

**Test Coverage:**
- Basic confidence aggregation with multiple components
- Empty state handling
- Validation error handling

### `test_critic_utils.py`
Tests for Critic agent utility functions, particularly JSON parsing.

**Test Coverage:**
- JSON parsing with markdown code fences
- Generic code fence handling
- Plain JSON parsing
- JSON with extra text
- Empty/invalid input handling
- Nested object parsing

### `test_critic_decision.py`
Tests for Critic agent decision-making logic (ACCEPT/RETRY/ESCALATE).

**Test Coverage:**
- Decision thresholds (ACCEPT, RETRY, ESCALATE)
- Retry count limits
- Feedback format validation
- Empty output handling
- Validation-based decisions

### `test_fairds_api_parser.py`
Tests for FAIR-DS API response parsing.

**Test Coverage:**
- Terms API response parsing
- Package API response parsing
- Field information extraction
- Term information extraction
- Malformed response handling

### `test_fair_data_station.py`
Integration tests for FAIR Data Station API client (real API connection).

**Test Coverage:**
- API connectivity and availability
- Terms API (get all, search by label/definition)
- Package API (get list, get by name)
- Data integrity validation
- Error handling (invalid URL, timeout)

**Note:** These tests require FAIR-DS API to be running and accessible.

### `test_config_saver.py`
Tests for runtime configuration saving functionality.

**Test Coverage:**
- Configuration collection
- Runtime info collection
- Sensitive data masking
- JSON file creation and validation
- Directory creation handling
- Data preservation

### `test_mineru_client.py`
Tests for MinerU document conversion service integration.

**Test Coverage:**
- Configuration validation
- CLI availability checks
- Server connectivity tests
- Client initialization
- Document conversion (integration test)

## Running Tests

### Quick Start (Unified Test Script)

We provide a unified test runner script for convenience:

```bash
# Run all tests (67 tests)
python run_tests.py all

# Run fast tests only (48 unit tests, ~6s)
python run_tests.py fast

# Run integration tests only (19 tests, requires services, ~25s)
python run_tests.py integration

# Run with coverage report
python run_tests.py coverage

# Run specific test file
python run_tests.py specific test_critic_utils.py

# Show help
python run_tests.py --help
```

### Direct Pytest Commands

#### Run All Tests
```bash
pytest tests/ -v
```

#### Run Only Fast Tests (Exclude Integration/Slow)
```bash
pytest tests/ -v -m "not integration and not slow"
```

#### Run Integration Tests Only (Requires External Services)
```bash
# Requires FAIR-DS API and MinerU server
pytest tests/ -v -m "integration"
```

#### Run Specific Test File
```bash
pytest tests/test_confidence_aggregator.py -v
pytest tests/test_fair_data_station.py -v  # Integration tests
```

#### Run Specific Test Class
```bash
pytest tests/test_mineru_client.py::TestMinerUCLI -v
```

#### Run with Coverage
```bash
pytest tests/ --cov=fairifier --cov-report=html --cov-report=term-missing
```

## Test Statistics

- **Total Tests**: 67 (✅ All passing)
- **Test Files**: 8 (7 in tests/ + conftest.py)
- **Integration Tests**: 19 (FAIR-DS API: 13, MinerU: 6)
- **Unit Tests**: 48 (fast, no external dependencies)
- **Execution Time**: 
  - Fast tests: ~3s (unit tests only)
  - Integration tests: ~25s (requires services)
  - All tests: ~16s (with services running)

## Test Coverage by Component

- ✅ Confidence Aggregation (3 tests)
- ✅ Critic Utils - JSON Parsing (7 tests)
- ✅ Critic Decision Logic (9 tests)
- ✅ FAIR-DS API Parser (9 tests)
- ✅ FAIR-DS API Client - Real Integration (13 tests)
- ✅ Config Saver (13 tests)
- ✅ MinerU Client (13 tests)

## Test Status Summary

Last run: 2025-01-28
- Python version: 3.13.7
- Pytest version: 9.0.1
- Environment: FAIRiAgent mamba environment
- Status: ✅ **All 67 tests passing**

## Test Markers

- `@pytest.mark.integration`: Tests that require external services (e.g., MinerU server)
- `@pytest.mark.slow`: Tests that take a long time to run (e.g., document conversion)

## Test Structure

All tests follow a consistent structure:
- Tests are organized into classes by functionality
- Each test class has descriptive docstrings
- Tests use descriptive names following `test_<functionality>_<scenario>` pattern
- Tests include both positive and negative test cases

## Adding New Tests

When adding new tests:
1. Follow the existing class-based structure
2. Use descriptive test names
3. Add appropriate markers (`@pytest.mark.integration`, `@pytest.mark.slow`) if needed
4. Include docstrings explaining what is being tested
5. Ensure tests are independent and can run in any order
6. Use fixtures for common setup/teardown

## Test Configuration

Test configuration is managed in:
- `pyproject.toml`: Pytest settings and markers
- `conftest.py`: Shared fixtures and configuration
