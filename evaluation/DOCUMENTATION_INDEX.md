# Evaluation Documentation Index

**Purpose:** Authoritative navigation for benchmark design, implementation, and
historical results

**Last updated:** 2026-07-25

Interactive run check / handout draft: `docs/manuscript/paper_ready_dashboard.html`
(ACTIVE-120 + **可发表 Handout** checklist via `tables/dashboard_active_runs.json`;
refresh with `docs/manuscript/scripts/build_dashboard_active_runs.py`). Manuscript
draft updates await approval.

## Current source of truth

Read these documents in order:

1. [Evaluation Benchmark Methodology](../docs/en/EVALUATION_METHODOLOGY.md) —
   concise scientific contract: benchmark object, data, six axes, success rate,
   baselines, models, and statistics.
2. [Evaluation Benchmark Redesign and Implementation Plan](EVALUATION_IMPROVEMENT_PLAN.md)
   — complete design, implementation stages, acceptance criteria, decisions,
   and maintained development status.
3. [Evaluation Framework README](README.md) — current commands and existing
   evaluator layout. Legacy aggregate commands are compatibility-only; the v2
   manifest/run-index path is authoritative for new results.
4. [Evaluation harness](harness/README.md) — current public/private fixture
   skeleton; this will be extended by the redesign plan.

The methodology states what the benchmark means. The implementation plan is the
living project record. Code and command examples in the framework README describe
what currently exists and do not override either document.

## Design references

- [Consensus review of LLM multi-agent evaluation](../docs/en/development/local/LLM/MAS%20evaluation%20consensus.md)
- [Hybrid Retrieval and Coverage Upgrade Plan](../docs/en/development/HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md)
- [Benchmark datasheet template](datasets/BENCHMARK_DATASHEET_TEMPLATE.md)
- [Benchmark v2 dataset datasheet (2026-07-21 candidate)](datasets/BENCHMARK_DATASHEET_20260721.md)
- [Operational sampling protocol template](datasets/OPERATIONAL_SAMPLING_PROTOCOL_TEMPLATE.md)
- [Benchmark v2 release decision checkpoint](datasets/RELEASE_DECISION_CHECKPOINT.md)
- [Benchmark execution checklist (2026-07-21)](EXECUTION_CHECKLIST_20260721.md)
- [Current development status (2026-07-21)](DEVELOPMENT_STATUS_20260721.md)
- [Pilot execution blocker (2026-07-22)](PILOT_BLOCKER_20260722.md)
- [Evaluation v2 handover (2026-07-22)](HANDOVER_EVALUATION_PLAN_20260722.md)
- [Model Classification and Metadata](analysis/MODEL_CLASSIFICATION.md) —
  historical/current candidate registry; exact benchmark models are frozen by
  preflight, not by this file.

## Current implementation documentation

- `evaluation/evaluators/` — existing metric implementations
- `evaluation/baselines/README.md` and `evaluation/baselines/run_publication_baselines.py`
  — unified v2 baseline conditions and token-free dry-run output
- `evaluation/scripts/evaluate_outputs.py` — historical single-run aggregate
  evaluator; it rejects repeated runs rather than selecting a best repetition
- `evaluation/scripts/run_batch_evaluation.py` — current batch runner
- `evaluation/config/` — current environment and model candidates
- `evaluation/harness/` — manifest and private-fixture skeleton
- `evaluation/benchmark/` — version 2 contracts, per-run attachment, scoring,
  statistics, reporting, token-free release-gate, and explicit dataset-manifest
  materialization/budget/preflight-plan entry points, and condition-difference
  audits for progressive and focused comparisons. `agentic_campaign.py` is the
  approval-gated campaign planner/executor for non-baseline cells;
  `model_preflight_runner.py` is the separate approval-gated interface probe
  boundary and is dry-run by default;
  `context_snapshots.py` materializes explicit package and lexical retrieval
  context assets without model calls; `pilot.py` expands development-only
  repetitions without exposing held-out instances; `merge_run_indices.py`
  combines disjoint execution partitions while preserving the denominator;
  `threshold_calibration.py` describes pilot score distributions without
  freezing thresholds.
- `evaluation/analysis/README.md` — existing analysis workflow

## Historical reports and runs

The following are diagnostic and historical, not benchmark version 2 results:

- `evaluation/reports/FINAL_EVALUATION_RESULTS.md`
- `evaluation/reports/README.md`
- `evaluation/analysis/output/key_figures/`
- `evaluation/archive/docs/`
- `evaluation/analysis/output/archive/`
- existing directories under `evaluation/runs/`

Historical run names may contain engineering aliases such as `shadow` or
`phase4`. Do not reuse those names for new publication conditions. Historical
scores are comparable with the redesigned benchmark only when the canonical
output and scoring contracts can be reconstructed.

## Documentation maintenance rule

Any implementation change that completes a redesign stage must update the stage
status, acceptance evidence, and decision log in
`evaluation/EVALUATION_IMPROVEMENT_PLAN.md` in the same change. A benchmark
release must also update the methodology if its scientific contract changes.
