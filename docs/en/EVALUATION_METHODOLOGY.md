# FAIRiAgent Evaluation Benchmark Methodology

**Status:** Methodological contract for benchmark version 2; implementation is
in progress

**Last updated:** 2026-07-21

**Implementation plan and development log:**
[Evaluation Benchmark Redesign and Implementation Plan](../../evaluation/EVALUATION_IMPROVEMENT_PLAN.md)

## Purpose

FAIRiAgent is evaluated as a system that converts real scientific documents
into usable FAIR-DS/ISA metadata packages. The benchmark therefore judges the
final artifact, not merely workflow completion, model confidence, retrieval
activity, or an LLM judge's general impression.

The methodology follows the real-task and executable-success principle of
[SWE-bench](https://arxiv.org/abs/2310.06770), the realistic tool-task and
held-out design of [GAIA](https://arxiv.org/abs/2311.12983), and the end-state
and repeated-reliability design of
[tau-bench](https://arxiv.org/abs/2406.12045).

## Evaluation unit

A benchmark instance contains one primary scientific document, declared
supplementary assets, a human-annotated reference result, an applicable FAIR-DS
package, stratum labels, and immutable checksums. A document-run is one model,
one scientific condition, one instance, and one repetition.

Every condition emits the same canonical metadata envelope. All scheduled
document-runs remain in the denominator. Timeouts, invalid serialization,
missing artifacts, and validation failures are explicit outcomes; the evaluator
does not select the best repetition.

## Ground truth and FAIR-DS packages

Human annotation is the sole source of reference answers. In particular, the
PETase ground truth was converted from human annotation into the repository
format. Its annotators did not supply evidence spans, so `_evidence` is neither
required nor reconstructed. Model-generated provenance is evaluated separately
and is never presented as human ground truth.

The local PETase FAIR-DS package is a temporary transport mirror of a package
awaiting service synchronization. Loading the identical package locally or from
FAIR-DS is treated as equivalent input. Transport source is recorded for
reproducibility but is not a benchmark condition or a contamination label.

## Benchmark collections

The benchmark uses versioned, complementary collections:

- a visible development collection for debugging and calibration;
- a core human-annotated collection for comparable results;
- a prospectively sampled operational-distribution collection;
- held-out domain-generalization documents;
- a document-stress collection for long, table-heavy, OCR-impaired, sparse, and
  supplementary-material cases; and
- an independently checked verified collection for the headline result.

Splits occur at document, project, and study-family level. Held-out answers are
frozen before model, prompt, or threshold selection. Reports include both
prevalence-weighted operational estimates and document/stratum macro-averages.

Each instance may also declare a reporting role: `core`, `supplemental`, or
`stress`. Headline scores use an explicit `--scope core` over core-role
instances; supplemental and stress outcomes remain in the run index and are
reported separately rather than silently changing the headline denominator.

## Six-axis scorecard

All axes use a fixed zero-to-one scale.

1. **Field recovery / presence** — populated GT-field recovery, required-field
   recall, and entity/row coverage. In a values-first GT release this is a
   populated-value presence proxy, not a complete metadata-selection score.
2. **GT-wide value score** — type-aware correctness over all populated GT fields,
   including unit normalization and partial credit. Missing/unselected fields
   score zero, so this is an end-to-end yield measure rather than independent
   conditional value-filling accuracy.
3. **ISA structural fidelity** — sheet placement, entity alignment, identifier
   integrity, parent-child relationships, and input-output links.
4. **Standards and interoperability** — canonical schema validity, FAIR-DS
   validation, ISA round trip, and material-loss checks.
5. **Reliability** — completion, repeated success, variance, worst-decile
   quality, and pass-to-the-power-of-k.
6. **Computational efficiency** — latency, tokens, calls, monetary cost, and
   local compute use where measurable.

The radar chart is the primary quality profile. Efficiency is normalized for
visual comparison but does not increase the composite quality score.

## Headline measures

**Provisional joint end-to-end success rate** is the percentage of all scheduled
document-runs that pass the current code-defined hard artifact, validation,
field-recovery, GT-wide-value, structure, and interoperability requirements.
The project protocol labels the current Standard and Strict thresholds
provisional pre-calibration requirements. They must be reviewed against
development distributions, human agreement, and error severity, then frozen
before held-out evaluation. This joint rate is a secondary outcome when the
scientific objectives are field selection and value filling separately.

The two task-specific outcomes are reported independently:

- **Task A — metadata selection:** package accuracy, field recall, required-field
  recall, and evidence-audited precision or unsupported-field rate;
- **Task B — value filling:** type-aware conditional value score, full-match rate,
  missing rate, and field-type breakdown after every model receives the same
  oracle package and field list.

The secondary **Benchmark Quality Score** is a weighted geometric mean:

```text
100 × coverage^0.20
    × value_accuracy^0.30
    × structural_fidelity^0.20
    × interoperability^0.20
    × reliability^0.10
```

Weights and provisional thresholds are finalized during calibration. A hard
validation failure remains a benchmark failure regardless of graded quality.
Success rates, six axes, composite quality, latency, tokens, and cost are always
reported together.

## Baselines and progressive ablation

The main controlled comparison contains five conditions:

1. Single-pass structured extraction.
2. Standards-guided extraction.
3. Retrieval-assisted extraction.
4. Iterative agentic extraction.
5. Complete FAIRiAgent system.

Within a comparison, conditions use the same model, source assets, FAIR-DS
package, output contract, preprocessing, context policy, evaluator, and
repetition schedule. The direct baseline receives the complete document and is
not artificially weakened by an arbitrary character-prefix limit.

Two focused paired studies compare lexical with hybrid retrieval, and compare
deterministic metadata correction disabled with enabled. Retrieval candidate
counts are diagnostic only; causal claims depend on final coverage, accuracy,
structure, interoperability, and success.

## Model study

Architecture effects and model effects are analyzed separately. The progressive
comparison uses the same hosted model within all paired conditions and is
repeated with one feasible local model. The model-generalization study runs the
complete system and the standards-guided baseline across at most six model
slots: hosted efficient, hosted high-capability, hosted independent-family,
local compact, local medium, and local large.

Exact model identifiers are frozen only after endpoint, context, structured
output, and tool-use preflight. Local results record image digest, quantization,
serving version, hardware, memory, offload, and throughput.

The current read-only Ollama tag observation confirms the requested local
identifiers and records their digests; it is endpoint metadata only and does
not count as a generation or interface preflight.

The current release candidate contains DeepSeek V4 Flash and Pro, gpt-oss 20B,
Qwen3.6 27B, and Gemma4 26B. This is an explicitly requested capability and
access panel, not a dense-only comparison: the official cards identify DeepSeek
V4, gpt-oss 20B, and Gemma4 26B as sparse/MoE architectures. Architecture
labels and model-card sampler settings are recorded in
`evaluation/config/model_card_registry.json` and remain part of the frozen
panel artifact.

## Repetition and statistics

The protocol uses one-run interface preflight, three-run pilot evaluation,
five-run confirmatory evaluation, and ten repetitions on a stratified reliability
subset. Pilot variance may increase the confirmatory count before held-out
rankings are inspected.

Reports include paired document-level differences, stratified bootstrap
confidence intervals, macro and micro estimates, effect sizes, corrected paired
tests, variance decomposition, failure categories, pass-to-the-power-of-k, and
cost-quality Pareto frontiers. Exploratory analyses are labeled separately from
the frozen confirmatory analysis.

## Naming and reproducibility

Figures and manifests use explicit scientific condition names. Historical names
such as `shadow`, `phase4`, `auto`, `dimfix`, and `tuned` are migration aliases,
not publication terminology.

Each batch manifest records benchmark version, asset checksums, exact condition,
repository and evaluator commits, package identity, model identity, prompts and
tool-contract hashes, service versions, local hardware where applicable,
resource ceilings, repetition schedule, price table, and every outcome.

The complete schemas, provisional success thresholds, implementation stages,
test fixtures, acceptance criteria, and decision log are maintained in the
[implementation plan](../../evaluation/EVALUATION_IMPROVEMENT_PLAN.md).
