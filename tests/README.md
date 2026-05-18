# FAIRiAgent Test Suite

This directory contains the repository's Python test suite for API routes, agent behavior, metadata generation, source grounding, memory services, evaluation helpers, and workflow utilities.

## Environment

Use the `FAIRiAgent` mamba environment for Python test runs:

```bash
mamba run -n FAIRiAgent python run_tests.py fast
```

If you run `pytest` directly, prefer the same interpreter:

```bash
python -m pytest tests/ -v
```

## Common Commands

```bash
# Fast local regression run
python run_tests.py fast

# Full Python suite
python run_tests.py all

# Coverage report
python run_tests.py coverage

# One file
python run_tests.py specific test_api_artifacts.py
```

`run_tests.py` disables LangSmith tracing for test subprocesses so offline/local runs do not hang on telemetry uploads.

## Markers

- `integration`: requires external services or real integrations
- `slow`: intentionally longer-running scenarios

Fast mode runs:

```bash
python run_tests.py fast
```

which maps to:

```bash
python -m pytest tests/ -v --tb=short -m "not integration and not slow"
```

## Notes

- Some legacy/manual mem0 scripts are excluded from normal pytest collection in `tests/conftest.py` because they are not hermetic unit tests.
- Current suite size changes frequently; use `pytest --collect-only` if you need an exact live count.
- A recent verification run in the `FAIRiAgent` environment completed with `475 passed, 3 skipped, 19 deselected`.
