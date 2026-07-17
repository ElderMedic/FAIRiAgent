# Auto Hybrid Repair Plan

## Original Goal

FAIRiAgent should be an end-to-end "lazy" pipeline: users provide a scientific
document bundle and get a FAIR-DS-compatible metadata result without manually
choosing Shadow or Tuned modes.

The existing A/B results show complementary strengths:

- Shadow-style lexical prompt context preserves FAIR-DS/ISA structure better.
- Tuned semantic fallback improves qualitative context and some value matches.

The production design should combine those strengths in one `auto` mode.

## FAIR-DS / ISA Compatibility Constraints

The metadata result must remain directly useful for FAIR-DS submission and ISA
export. Semantic repair must therefore be subordinate to these invariants:

- Preserve known FAIR-DS field names and package metadata.
- Preserve ISA sheet placement: investigation, study, observationunit, sample,
  assay.
- Preserve row alignment and linkage identifiers across sample/assay/observation
  unit rows.
- Do not accept ungrounded high-confidence fields.
- Do not expand `extra_fields` merely because semantic retrieval found related
  concepts.
- Keep provenance on accepted values: source id, snippet span, retrieval method,
  confidence, and evidence-store packet id when available.

## Proposed Runtime Architecture

1. Initial pass: structure-first generation with lexical-first prompt evidence.
2. Gap detection: missing required/recommended fields, low confidence, weak
   source refs, wrong values when value-level checks exist, and structural
   diagnostics.
3. Repair decision: deterministic fallback rules are the production default;
   optional field-level classifier ranking is shadow/research-only until it
   beats rules on held-out documents.
4. Deterministic patch: accept only exact FAIR-DS field-name candidates on
   single-row sheets (`investigation`, `study`) that have value, source
   provenance, evidence text, sufficient confidence, and pass linkage/schema
   guards.
5. Semantic repair: future targeted prompts for one gap field or a linkage-safe
   group; every patch must still pass the same guard.
6. Final output: standard metadata JSON plus an `auto_repair_trace` sidecar or
   report block.

## Runtime Contract Implemented So Far

The main FAIRiAgent pipeline now has a single default `auto` behavior:

- Prompt-time retrieval is lexical-first. Semantic evidence enters prompts only
  for lexical misses in `auto` mode.
- Post-generation `AutoRepairNode` runs before finalization.
- Guarded deterministic exact-match patches update both `metadata_fields` and
  `metadata.json` when safe.
- After every accepted-candidate write, the patched `metadata.json` is checked
  for local FAIR/ISA integrity. If the patch corrupts structure, field
  datatypes, value formats, source grounding, or single-row matrix consistency,
  the node rolls back `metadata_fields`, `metadata.json`, and `isa_values_json`
  before recording a rejection.
- `auto_repair_trace.json` records candidates, accepted patches, rejected
  patches, guard failures, and whether metadata was mutated.
- When at least one patch is accepted, `metadata.json` also gets a compact
  `auto_repair_summary` pointing to `auto_repair_trace.json`. The full trace
  stays in the sidecar; the main metadata result remains FAIR-DS/ISA structured.
- `FAIRIFIER_AUTO_REPAIR_APPLY_PATCHES=false` provides trace-only fallback for
  shadow comparisons without changing result files.
- Optional classifier predictions can be supplied in
  `state["auto_repair_classifier_predictions"]` and are recorded as
  `classifier_shadow_prediction` entries in `auto_repair_trace.json` when
  `FAIRIFIER_AUTO_REPAIR_CLASSIFIER_SHADOW_ENABLED=true`. They do not influence
  deterministic patch acceptance.
- `FAIRIFIER_AUTO_REPAIR_ENABLED=false` skips the node entirely.
- Internal repair errors fall back to a non-mutating trace instead of failing
  the whole run.

## Classifier Scope

The first model should be field-level:

- `should_repair_field`: whether to run semantic repair for a field.
- `should_accept_patch`: whether to accept a proposed semantic patch after guard
  checks.

It should not be a document-level "Shadow vs Tuned" classifier.

## Training Data Plan

This sandbox builds rows from paired A/B runs:

- Shadow output field status and score.
- Tuned output field status and score.
- Retrieval telemetry: lexical hits, semantic hits, prompt mode, rerank status.
- Document-level deltas: completeness, schema, row alignment, extra fields, LLM
  judge.
- Weak labels from paired improvements and guard outcomes.

Validation must be leave-one-document-out or future-run holdout. Random
field-level split is not acceptable because fields from the same document leak
document style and run behavior.

### Current Pilot Result

The six-document paired dataset yields 291 fields, 14 `should_repair` positives,
and 3 `safe_accept` positives. Leave-one-document-out calibrated logistic
evaluation scores F1 `0.133` for `should_repair`, below the deterministic rules
baseline F1 `0.593`; `safe_accept` has too few positive examples for reliable
calibration. The classifier therefore remains shadow-only. It must beat rules
on held-out documents while preserving schema and row-alignment gates before it
can influence patch selection.

## Main Code Integration Milestones

1. Keep this sandbox until the weak labels and rule baseline are stable.
2. Add `FAIRIFIER_RETRIEVAL_MODE=auto|shadow|tuned` with `auto` as the only
   recommended production mode. **Status: implemented in config/source
   retrieval selection.**
3. Move deterministic rules into `fairifier/services/auto_repair_policy.py`.
   **Status: implemented for prompt-time auto fallback decisions.**
4. Add a post-generation `AutoRepairNode` after initial JSON generation and
   before final report/export. **Status: implemented.**
5. Add sidecar `auto_repair_trace.json`. **Status: implemented.**
6. Add tests for lexical-only fallback, no schema regression after accepted
   patch, linkage-field guards, rule-only fallback, and FAIR-DS/ISA output
   compatibility. **Status: focused tests implemented for current guarded
   exact-match patch scope.**
7. Add a shadow-only classifier prediction hook in the repair trace so future
   full eval runs can compare model recommendations against the rule baseline
   without changing metadata output. **Status: implemented.**
8. Export rules/model predictions in the same shape consumed by the trace hook
   so future eval harnesses can inject them without inventing another schema.
   **Status: implemented in `export_shadow_predictions.py`.**

## Metadata Result Requirements

The actual product artifact is `metadata.json`, not only the eval score table.
For a run to be usable end to end, the result must:

- Preserve the FAIR-DS `isa_structure.<sheet>.fields` representation used by
  validators and reports.
- Preserve or update `isa_values` / `isa_values_json` when the sheet is
  single-row and the update cannot disturb row alignment.
- Keep `metadata_fields` in LangGraph state consistent with `metadata.json`.
- Keep provenance strings compatible with source-grounding checks
  (`source_001:10-40`, table row/column references, or equivalent).
- Include `auto_repair_summary` in `metadata.json` when accepted patches changed
  values, so the single primary result file remains self-describing.
- Avoid mutating linkage/id fields and multi-row sheets unless a future
  group-aware repair can prove row alignment is preserved.
- Continue writing the standard final artifacts even when auto repair skips,
  rejects, or errors.
- Persist `auto_repair_trace` through the shared artifact filename mapping so
  both CLI/evaluation runs and Web/API runs write `auto_repair_trace.json`.

## Full Auto Eval Runbook

The canonical runner is:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py
```

The default is dry-run. It writes an ignored auto model config under
`evaluation/prototypes/auto_repair_classifier/artifacts/`, writes a matching
ignored auto eval env so later env loading cannot override auto mode, prints the
exact `run_batch_evaluation.py` command, and targets
`evaluation/runs/auto_pro_tuned`.

Run local preflight without service checks:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py --preflight --skip-service-check
```

The preflight verifies that generated config resolves to
`FAIRIFIER_RETRIEVAL_MODE=auto`, auto repair mutation is enabled, ground-truth
document paths exist, and the output parent is ready. It writes
`auto_eval_preflight_report.json` and `auto_eval_preflight_report.md` under the
prototype `artifacts/` directory. The JSON report includes a stable `summary`
with failed check names, failed services, missing MinerU document ids, and
`blocked_requirements` keys that other agents or CI can consume directly.
During `--execute`, preflight also checks `FAIR_DS_API_URL`,
`MINERU_SERVER_URL`, Qdrant, and the retrieval embedding endpoint unless
`--skip-service-check` is passed. MinerU is only blocking for target source
files that do not already have preconverted MinerU markdown. If live MinerU is
unreachable and such files exist, preflight also probes the local
`mineru -b pipeline` fallback import dependencies and emits
`mineru_preconvert_dependency` with stable errors such as
`missing_python_module:doclayout_yolo`. This check reuses the main
FAIRiAgent MinerU health helper, so API/CLI health, auto eval preflight, and
preconversion planning all report the same dependency status and install hint:
`pip install 'mineru[pipeline]>=3.4.0,<4'`.

Prepare missing MinerU preconversions without changing the pipeline:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py
```

The default is dry-run and writes `mineru_preconvert_report.json` plus
`mineru_preconvert_report.md` under `artifacts/`. The report lists exactly which
target PDFs are missing reusable `mineru_<stem>/` Markdown and the
`mineru -b pipeline` command that would create it. Execute only when local
pipeline conversion is acceptable:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/preconvert_mineru.py --execute
```

The execute path validates generated Markdown after MinerU returns. A zero exit
without reusable Markdown is a failure, and missing local pipeline modules are
reported as stable dependency errors such as
`missing_python_module:doclayout_yolo` with the local pipeline install hint.

Build one combined readiness report for handoff:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/readiness_report.py
```

This writes `auto_readiness_report.json` and `auto_readiness_report.md`,
combining preflight failures, auto-result presence, and merge-gate status. Its
top-level `blocked_requirements` distinguishes external service blockers from
the expected `auto_results` blocker before the six-document run has completed.
The same JSON includes a `requirements` audit list so merge review can separate
implemented local pieces from pending full-run evidence. When present, the
MinerU preconversion report is embedded into readiness so dependency blockers
are visible in one place.
Runtime services are checked by default. `--skip-service-check` is only for
offline file/configuration inspection and is not merge evidence.

Run the full six-document evaluation only when external services and
credentials are ready:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/run_auto_eval.py --execute
```

After execution, the runner mirrors root `evaluation_results.json` to
`results/evaluation_results.json` so the merge gate default path works, then
invokes `merge_gate.py`.

## Merge Policy

Do not merge a trained classifier into the main pipeline until it beats the
rule-only fallback on held-out documents without reducing schema compliance or
row alignment. The fallback rules are the safety baseline.

Do not merge this feature branch to `main` as production-default complete until
the current `auto` configuration has a fresh full eval run on the six target
documents and shows:

- Schema compliance no worse than Shadow.
- Row Alignment F1 no worse than Shadow beyond noise.
- Precision excluding discoveries remains near Shadow/Tuned baseline and no
  new hallucination class appears in accepted patches.
- Completeness improves or stays neutral versus Shadow on documents where exact
  candidates exist.
- `metadata.json`, `auto_repair_trace.json`, and Excel/export-facing
  `isa_values` remain parseable and FAIR-DS-compatible.
- `metadata.json` passes the shared metadata format checks for required
  top-level structure, field datatypes, value formats, and source-grounding
  accounting.
- Every auto document run has the expected artifact set:
  `metadata.json`, `workflow_report.json`, `runtime_config.json`,
  `auto_repair_trace.json`, `isa_values_json.json`, and
  `metadata_fairds.xlsx`.
- `runtime_config.json` proves `effective_retrieval_mode=auto`,
  `auto_repair_enabled=true`, `auto_repair_apply_patches=true`, and includes an
  explicit `auto_repair_classifier_shadow_enabled` setting for classifier
  provenance.
- `auto_repair_trace.json` proves the repair node ran in
  `deterministic_exact_patch` mode with `summary.apply_patches=true`; trace-only
  or `error_fallback` runs are diagnostic evidence, not production merge
  evidence.
- If `auto_repair_trace.json` reports accepted patches, `metadata.json` must
  contain a matching `auto_repair_summary.accepted_patch_count`.
- Accepted patches must be materialized in the actual FAIR-DS-facing files:
  the field must be present in `metadata.json.isa_structure`, and for
  single-row sheets it must also appear in the metadata row matrix and
  `isa_values_json.json`.
- FAIR-DS Excel export must read the patched `isa_values_json.json` matrix so
  `metadata_fairds.xlsx` contains accepted auto repair fields.

Use the local merge gate to make this decision reproducible:

```bash
mamba run -n FAIRiAgent python evaluation/prototypes/auto_repair_classifier/merge_gate.py \
  --auto-results evaluation/runs/auto_pro_tuned/results/evaluation_results.json
```

Before the auto run exists, the command should fail with
`status=missing_auto_results`. That is expected and means the branch still lacks
the full-run evidence required for a merge decision.

When the auto run exists, the gate also inspects per-document artifacts under
the inferred model run root. A score-only pass is not enough: missing or
unparseable metadata/trace/value-matrix artifacts must block merge because the
product requirement is an end-to-end usable FAIR-DS result package.
