# Auto Repair Classifier Prototype

Temporary engineering sandbox for the FAIRiAgent `auto` retrieval/repair mode.

The target product behavior is a single end-to-end pipeline, not a user-facing
choice between Shadow and Tuned:

1. Generate initial metadata with lexical-first, Shadow-style evidence context.
2. Build semantic index, evidence store, section coverage, and retrieval telemetry
   on every run.
3. Detect missing, low-confidence, weakly grounded, or value-wrong fields.
4. Use semantic fallback only for those gap fields.
5. Accept deterministic patches only on single-row ISA sheets when FAIR-DS/ISA
   guards pass; keep multi-row sample/assay/observation-unit repair trace-only
   until group-aware row repair exists.

Current production direction: rules first, classifier in shadow. The field-level
classifier is useful for ranking and later ablation, but the default pipeline
uses deterministic guards because the available positive labels are still small.
When a future eval harness supplies classifier predictions in
`state["auto_repair_classifier_predictions"]`, the main pipeline records them in
`auto_repair_trace.json` under `classifier_shadow_prediction`; those predictions
are trace-only and never decide whether a patch is accepted.

## Files

- `rules.py` - deterministic fallback policy used when no trained model is
  available or model confidence is too low.
- `build_dataset.py` - converts paired Shadow/Tuned eval runs into a field-level
  decision table.
- `train_decision_model.py` - trains/evaluates a lightweight calibrated logistic
  model with leave-one-document-out validation. Falls back to rules-only
  reporting if scikit-learn is unavailable.
- `export_shadow_predictions.py` - exports rules/model predictions as
  trace-compatible JSON for later `state["auto_repair_classifier_predictions"]`
  injection experiments.
- `run_auto_eval.py` - prepares the canonical full `auto` eval command and can
  execute it when `--execute` is passed.
  Executing it requires `--approval-id <review-id>` after reviewing the token
  and cost estimate.
- `preconvert_mineru.py` - prepares or executes MinerU preconversion for target
  PDFs that do not yet have reusable `mineru_<stem>/` Markdown output.
- `merge_gate.py` - compares a fresh `auto` eval run against Shadow/Tuned
  baselines and writes a pass/fail merge report.
- `readiness_report.py` - combines preflight and merge-gate evidence into one
  readiness report for handoff and merge audits.
- `PLAN.md` - implementation plan for moving from this sandbox into the main
  FAIRiAgent workflow.

## Run

From the repository root:

```bash
python evaluation/prototypes/auto_repair_classifier/build_dataset.py
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/train_decision_model.py --label should_repair_label
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/train_decision_model.py --label safe_accept_label
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/export_shadow_predictions.py
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/merge_gate.py
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/readiness_report.py
```

Artifacts are written to `evaluation/prototypes/auto_repair_classifier/artifacts/`
and ignored by git.

`merge_gate.py` intentionally fails until
`evaluation/runs/auto_pro_tuned/results/evaluation_results.json` exists. Use
`--no-fail` when you only want to refresh the diagnostic report before the full
auto eval has been run.

The gate checks both aggregate metrics and per-document artifacts. A passing
run must include parseable `metadata.json`, `workflow_report.json`,
`runtime_config.json`, `auto_repair_trace.json`, `isa_values_json.json`, and
`metadata_fairds.xlsx` under each `<model>/<doc_id>/run_*/` directory. This
keeps the merge decision tied to the actual files users and FAIR-DS export
consume, not only to the score table.
`metadata.json` must also pass the shared metadata format checks for required
top-level structure, field datatypes, value formats, and source-grounding
accounting.
`runtime_config.json` must prove the run used `effective_retrieval_mode=auto`
with auto repair enabled, patch application enabled, and an explicit
`auto_repair_classifier_shadow_enabled` provenance setting.
`auto_repair_trace.json` must also prove the repair node actually ran in
`deterministic_exact_patch` mode with `summary.apply_patches=true`; trace-only
or error-fallback runs are not merge-ready production evidence.
The merge report summarizes trace mode counts and the number of
non-production trace documents so a full run can be audited without opening
each run directory.
When a trace reports accepted patches, the gate also requires
`metadata.json.auto_repair_summary.accepted_patch_count` to match the sidecar
trace count. Accepted patches must also be materialized in the actual result
files: the accepted field has to appear in `metadata.json.isa_structure`, and
for single-row sheets such as investigation/study it must also appear in the
metadata row matrix, `isa_values_json.json`, and `metadata_fairds.xlsx`.

## Runtime Config In Main Pipeline

The main pipeline exposes the guarded auto path through environment variables:

```bash
FAIRIFIER_RETRIEVAL_MODE=auto
FAIRIFIER_AUTO_REPAIR_ENABLED=true
FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=true
FAIRIFIER_AUTO_REPAIR_MIN_CANDIDATE_CONFIDENCE=0.55
FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true
```

For shadow comparison runs, keep retrieval in `auto` but disable mutation:

```bash
FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=false
```

This still writes `auto_repair_trace.json` so eval can count candidates and
guard outcomes without changing `metadata.json`.

Classifier experiments remain opt-in shadow telemetry. Keep
`FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true` if the evaluation harness
injects predictions and you want them recorded for later analysis. Set it to
`false` to omit classifier annotations from the trace; deterministic repair
behavior is unchanged either way.

Export trace-compatible shadow predictions:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/export_shadow_predictions.py
```

For one document, use `--doc-id <document_id>` to write a direct field mapping
that can be assigned to `state["auto_repair_classifier_predictions"]`.

## Full Auto Eval

Prepare the canonical six-document auto eval command:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py
```

Run it only when FAIR-DS, MinerU, Mem0/Qdrant, Ollama embedding, and LLM/judge
credentials are ready:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py --execute
```

The runner writes an ignored generated model config under `artifacts/`, outputs
an ignored generated eval env under `artifacts/`, outputs to
`evaluation/runs/auto_pro_tuned`, mirrors `evaluation_results.json` into
`results/evaluation_results.json`, and then runs `merge_gate.py`.
When resuming an `auto` batch, `run_batch_evaluation.py` only reuses a prior
successful run if the merge-gate artifacts are already present:
`workflow_report.json`, `runtime_config.json`, `auto_repair_trace.json`,
`isa_values_json.json`, and `metadata_fairds.xlsx`.

Run a local preflight without starting the expensive batch:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py --preflight --skip-service-check
```

Preflight writes `auto_eval_preflight_report.json` and
`auto_eval_preflight_report.md` under `artifacts/`.
The JSON includes a machine-readable `summary` block with failed service names,
missing MinerU document ids, and stable blocker keys such as `fair_ds`,
`mineru_missing_docs`, `retrieval_embedding`, and `auto_configuration`.
When live MinerU is unreachable and target PDFs still need conversion, preflight
also checks whether the local `mineru -b pipeline` fallback can import its
required modules. Missing fallback modules are reported as
`mineru_preconvert_dependency` blockers, for example
`missing_python_module:doclayout_yolo`. The check comes from the main
FAIRiAgent MinerU health helper, so API/CLI health and eval preflight expose
the same dependency status and install hint:
`pip install 'mineru[pipeline]>=3.4.0,<4'`.

`--execute` runs preflight first and checks `FAIR_DS_API_URL`,
`MINERU_SERVER_URL`, Qdrant, and the retrieval embedding endpoint by default.
MinerU is considered required only for target inputs that do not already have
preconverted MinerU markdown. Use `--skip-service-check` only when those
services are intentionally checked elsewhere.

Prepare missing MinerU conversions without changing the main pipeline:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py
```

The default is dry-run. It writes `mineru_preconvert_report.json` and
`mineru_preconvert_report.md` under `artifacts/`, listing the exact
`mineru -b pipeline` commands and expected output directories. Run with
`--execute` only when local MinerU pipeline conversion is acceptable:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py --execute
```

Execution validates the actual Markdown output, not only the MinerU process
exit code. If local pipeline dependencies are missing, the report records
stable dependency errors such as `missing_python_module:doclayout_yolo`.
The report also includes the install hint for local pipeline support.

Build the combined handoff report:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/readiness_report.py
```

This writes `auto_readiness_report.json` and `auto_readiness_report.md` under
`artifacts/`. The readiness JSON carries a top-level `blocked_requirements`
array so other agents or CI can distinguish service blockers from the expected
`auto_results` blocker before the full auto run exists. It also includes a
`requirements` audit list that maps the rollout objective to concrete evidence:
prototype workspace, single auto pipeline config, fallback rules, service/input
preconditions, FAIR-DS metadata artifact contract, full six-document eval, and
Shadow/Tuned synthesis merge gate. If `mineru_preconvert_report.json` exists,
readiness also carries its dependency errors and conversion counts.
Runtime services are checked by default. `--skip-service-check` is only for
offline file/configuration inspection and is not merge evidence.

## Current Weak Labels

`should_repair_label` is positive when the paired run suggests Tuned helped a
field that Shadow missed or got wrong, and semantic retrieval had evidence.

`safe_accept_label` is stricter: the field improved and the deterministic
FAIR-DS/ISA guard did not flag a schema, row-linkage, or extra-field risk.

These labels are intentionally conservative. They are suitable for a pilot
decision model, not a publication-quality claim.

## Current Classifier Baseline

The paired six-document data currently produces 291 field rows, with 14
`should_repair` positives and only 3 `safe_accept` positives. Leave-one-document-out
evaluation of the calibrated logistic pilot gave `should_repair` F1 `0.133`,
while the deterministic rules baseline gave F1 `0.593`. The `safe_accept`
pilot cannot form a reliable three-fold calibration split with only three
positives. These results are generated under `artifacts/` and are intentionally
not committed. They justify the current production contract: rules and FAIR-DS
guards decide; classifier predictions remain trace-only shadow telemetry until
new held-out data materially beats that baseline.
