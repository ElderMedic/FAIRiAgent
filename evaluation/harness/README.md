# Evaluation Harness

This directory contains a public harness skeleton for private FAIRiAgent evaluation.

## Intended Layout

- `example_manifest.json`: public schema example for case registration.
- `runner.py`: minimal harness runner entrypoint.
- `private/`: local-only confidential assets, gitignored.
  - `cases/`: source documents and case metadata.
  - `api_snapshots/`: optional private FAIR-DS / tool snapshots.
  - `gold/`: expected outputs or evaluator references.
  - `reports/`: local benchmark reports.
- `runs/`: local run outputs and intermediate artifacts, gitignored.

## Design Goal

Keep the harness code and evaluation schema in the repository, while keeping:
- confidential source documents
- private annotations
- institutional data
- local replay fixtures

out of Git.

## Suggested Workflow

1. Register a case in `private/cases/` and mirror its public ID in `example_manifest.json`.
2. Run the harness locally against the private case set.
3. Store private outputs under `private/reports/` or `runs/`.
4. Commit only code, schemas, evaluators, and non-sensitive metrics definitions.
