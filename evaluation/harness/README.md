# Evaluation Harness

This directory contains a public harness skeleton for private FAIRiAgent evaluation.

## Benchmark version 2 contract

The maintained benchmark contract is defined by:

- `../schemas/benchmark_manifest.schema.json` — instances, conditions, models,
  and every scheduled document-run;
- `../schemas/result_envelope.schema.json` — the canonical output of one
  document-condition-model-repetition run; and
- `../schemas/condition_registry.json` — publication-facing condition names.

The manifest validator rejects condition identifiers that are not in this
registry. Historical aliases must be translated at the input boundary and
never appear in publication-facing results.

Validate and expand a matrix without calling a model:

```bash
mamba run -n FAIRiAgent python evaluation/harness/runner.py \
  --manifest evaluation/benchmark/fixtures/benchmark_v2_smoke_manifest.json \
  --project-root . \
  --dry-run
```

The dry-run hashes every source and human ground-truth asset and fails on
duplicate or cross-split project/study-family membership. It reports
`model_or_api_calls_performed: false`; no endpoint or model is initialized.

The version 2 scorer treats every manifest entry as scheduled. A missing result
becomes an explicit `not_observed` failure; it cannot be removed to improve the
success rate. See `evaluation/benchmark/scorer.py` for the golden-fixture-backed
implementation.

Before execution, use the manifest asset and distribution checks:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.dataset_inventory \
  --manifest evaluation/benchmark/fixtures/benchmark_v2_smoke_manifest.json \
  --project-root .
```

Before freezing a release, run the token-free release gate. It reports missing
human decisions and preflight/run-index artifacts as explicit blockers:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.release_gate \
  --manifest <benchmark-manifest.json> \
  --project-root . \
  --model-inventory <model-inventory.json> \
  --preflight <model-preflight.json> \
    --run-index <run-index.json>
```

For the publication baselines, materialize explicit context assets before the
manifest is executed. The compiler below uses the local FAIR-DS package as the
standards context and creates a reproducible lexical retrieval snapshot from
the source documents. It does not read ground-truth values, overwrite the
input manifest, or call a model. Semantic/hybrid snapshots require a separate
indexed campaign and are rejected by this command.

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.context_snapshots \
  --manifest <candidate-manifest.json> \
  --project-root . \
  --output-dir <context-snapshot-directory> \
  --output <context-report.json> \
  --manifest-output <candidate-manifest-with-context.json>
```

For progressive and focused ablations, verify the condition definitions before
the run matrix is scheduled:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.condition_comparison \
  --manifest <benchmark-manifest.json> \
  --output <condition-comparison.json>
```

The audit fails if a ladder step changes an undeclared component or if a
focused retrieval pair is not controlled. It is token-free.

After a release manifest and model panel are approved, create the development
pilot separately from held-out data:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.pilot \
  --manifest <approved-manifest.json> \
  --pilot-split development \
  --repetitions 3 \
  --output <pilot-manifest.json>
```

This command only expands repetitions for the selected split and rejects
held-out/verified pilot splits. It does not execute a model.

When multiple annotation collections overlap, audit them before creating a
non-overlapping release collection:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.annotation_audit \
  --ground-truth <collection-a.json> \
  --ground-truth <collection-b.json> \
  --output <annotation-audit.json>
```

The audit reports annotation hashes and differences. `_evidence` is reported
only as an annotation-policy diagnostic and is never required for PETase GT.
After the researcher chooses an authoritative source for every overlap, the
same tool can materialize a lossless, non-overlapping collection:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.annotation_audit \
  --ground-truth <collection-a.json> \
  --ground-truth <collection-b.json> \
  --authoritative-overlap <document-id>=<collection-a.json> \
  --merged-output <approved-ground-truth.json> \
  --output <annotation-audit.json>
```

It copies one complete human annotation per document; it never merges fields
or adds evidence.

After a batch, score its persisted index with:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.score_run_index \
  --manifest <benchmark-manifest.json> \
  --run-index <run-index.json> \
  --scope core \
  --report-dir <report-directory>
```

The `--scope` option is required for a headline score when a manifest contains
supplemental or stress instances. It filters by the manifest instance
`reporting_role` and reports the excluded denominator explicitly. Omitting it
scores all scheduled roles together for an overall diagnostic.

For artifacts produced by the current evaluator, attach deterministic
per-document metrics before scoring. This reads existing files only; it does
not call a model or an LLM judge:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.attach_evaluator \
  --manifest <benchmark-manifest.json> \
  --run-index <run-index.json> \
  --output <evaluated-run-index.json>
```

Compare two persisted condition scores with deterministic paired bootstrap
statistics:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.compare_conditions \
  --baseline <baseline-score.json> \
  --treatment <treatment-score.json> \
  --output <paired-comparison.json>
```

The one-step authoritative path (attachment, scoring, and optional report)
is:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.evaluate_run_index \
  --manifest <benchmark-manifest.json> \
  --run-index <run-index.json> \
  --output <benchmark-score.json> \
  --report-dir <report-directory>
```

`evaluation/scripts/evaluate_outputs.py` is retained only for historical
single-run compatibility. It refuses to choose among repeated runs; repeated
experiments must use the v2 run index and `evaluate_run_index` above.

## Materialize a production manifest

After the researcher has assigned every document to a split and approved the
model panel, materialize the manifest from those explicit decisions. The
materializer refuses missing or extra split assignments and requires a
human-authored freeze confirmation; it never guesses a split:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.dataset_manifest \
  --ground-truth <approved-non-overlapping-ground-truth-collection.json> \
  --split-map <approved-split-map.json> \
  --model-panel <frozen-model-panel.json> \
  --conditions evaluation/schemas/condition_registry.json \
  --package-id fairds \
  --package-version <package-version> \
  --package-path <fairds-package.json> \
  --benchmark-release <release-id> \
  --evaluator-version <evaluator-version> \
  --repetitions 3 \
  --repetitions-by-split <repetition-schedule.json> \
  --reporting-roles <approved-reporting-roles.json> \
  --freeze-confirmation "researcher-approved:<decision-id>" \
  --output <benchmark-manifest.json>
```

Do not pass both current collections unchanged: they contain two document IDs
with different converted annotations. First create an approved, non-overlapping
collection (and checksum it), then materialize the release.

For a supplemental BIOREM release, the reporting-roles file maps every core
instance to `core` and BIOREM to `supplemental` (or `stress`). The split map and
reporting-role map are separate explicit decisions.

The command only reads and hashes files; it performs no model, endpoint, or
token call. Every persisted v2 run index is also checked for complete counts,
scheduled identities, and canonical result envelopes before attachment or
scoring.

For the non-baseline agentic and retrieval-ablation cells, generate the
approval-gated campaign plan before execution:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.agentic_campaign \
  --manifest <benchmark-manifest.json> \
  --output-dir <campaign-output> \
  --model-config <model-id>=<model-config.env> \
  --base-env <evaluation-env-file> \
  --condition-env <condition-id>=<condition-env-file> \
  --output <agentic-campaign-plan.json>
```

The planner records source bundles, model/config identities, expected output
directories, and the execution adapter without importing or launching the
workflow. It fails closed when a model or condition environment is missing.
Only after reviewing the budget may the same command add
`--execute --approval-id <researcher-decision-id>`. Execution writes the scoped
manifest and denominator-preserving run index before the first subprocess;
evaluator attachment remains a separate deterministic step.

Before requesting approval for preflight or a pilot, produce a token-free
budget report. Agentic conditions must declare their expected calls per
document-run; missing price entries remain `null` rather than being guessed:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.budget \
  --manifest <benchmark-manifest.json> \
  --project-root . \
  --condition-calls <condition-call-estimates.json> \
  --price-table <approved-price-table.json> \
  --output <budget.json>
```

The candidate inventory can also emit a deduplicated preflight plan. This is a
plan only; it does not contact endpoints:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.model_preflight \
  --model-dir evaluation/config/model_configs \
  --development-instance <development-instance-id> \
  --plan-output <preflight-plan.json>
```

For a researcher-specified panel, repeat `--model-id`. This is required when
multiple models share one resource slot (for example, two local medium models)
so that the explicit panel cannot silently discard one of them:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.model_preflight \
  --model-dir evaluation/config/model_configs \
  --model-card-registry evaluation/config/model_card_registry.json \
  --model-id deepseek_v4-flash_v1.4.0 \
  --model-id deepseek_v4-pro_v1.4.0 \
  --model-id ollama_gpt-oss \
  --model-id ollama_qwen3.6-27b_v1.4.0 \
  --model-id ollama_gemma4-26b_v1.4.0 \
  --output <selected-inventory.json> \
  --development-instance <development-instance-id> \
  --plan-output <selected-preflight-plan.json>
```

The model-card registry is static provenance only. It records architecture,
active/total parameters, context, capabilities, and official source URLs; it
never substitutes for endpoint, structured-output, or tool-contract evidence.

The execution boundary is approval-gated. Without `--execute`, the command
below is a dry-run and cannot initialize a provider:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.model_preflight_runner \
  --inventory <selected-inventory.json> \
  --preflight-plan <selected-preflight-plan.json> \
  --output <preflight-dry-run.json>
```

Only after the token and cost estimate has been reviewed may the same command
be run with `--execute --approval-id <researcher-decision-id>`. Every planned
job receives a record, including timeouts and failed serialization; no failed
job is removed from the panel denominator.

After all planned probes have been recorded and local serving details have
been reviewed, freeze the exact panel as a separate, deterministic artifact.
This command only validates and serializes existing evidence; it does not
contact a model or endpoint:

```bash
mamba run -n FAIRiAgent python -m evaluation.benchmark.model_panel \
  --inventory <model-inventory.json> \
  --preflight-plan <preflight-plan.json> \
  --preflight-records <preflight-records.json> \
  --hardware-records <local-hardware.json> \
  --freeze-confirmation researcher-approved:<decision-id> \
  --output <frozen-model-panel.json>
```

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
