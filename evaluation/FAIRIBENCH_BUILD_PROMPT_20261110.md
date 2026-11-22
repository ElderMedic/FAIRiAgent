# Prompt: build and complete FAIRiBench

Paste everything below the line into a Claude Code session (or use it as the
brief for an orchestrating agent) opened at the FAIRiAgent repository root.

---

## Your role and goal

You are building **FAIRiBench**, the open benchmark described in the FAIRiAgent
manuscript. FAIRiBench measures how well any system (FAIRiAgent, a single LLM
call, another agent, a human curator) turns text about a life-science
experiment into a **FAIR Data Station (FAIR-DS) record**.

The manuscript defines two uses, and the benchmark must score both:

- **FAIR by Design.** From an experiment *plan*, propose the right *template*:
  ISOSA levels (investigation, study, observation unit, sample, assay), FAIR-DS
  packages and terms, and the layout (how many rows per level and how they link).
- **FAIRification.** From a published *paper* with supplements, rebuild the
  *full record*: the template plus the filled-in values.

It is **one task with two scores**, not separate tracks: every submitted record
is scored on **Template** and on **Values**. A study counts as **resolved** only
if its record passes all of that study's **design tests**.

When you finish, someone outside the project can download FAIRiBench, run one
command against their own system's outputs, and get a reproducible score card.

## What already exists (read before writing anything)

Start by reading these, and build on them rather than replacing them:

- `CLAUDE.md` and `evaluation/README.md`, `evaluation/DOCUMENTATION_INDEX.md`
- `evaluation/datasets/DATASET_README.md`: the current collection of 56 study
  records in `evaluation/datasets/annotated/ground_truth_public_curated.json`,
  with per-study values files (`fairiagent.ground_truth_values.v3`, ISA rows
  with parent links) under `annotated/values/`
- `evaluation/schemas/`: `ground_truth_values.schema.json`,
  `benchmark_manifest.schema.json`, `result_envelope.schema.json`
- `evaluation/benchmark/`: manifests and contracts (`contracts.py`), scoring
  (`scorer.py`, Wilson intervals), splits and leakage audit
  (`annotation_audit.py`, `dataset_inventory.py`), release gate
  (`release_gate.py`), model panel and preflight
- `evaluation/evaluators/value_accuracy_evaluator.py` and `_value_matching.py`:
  content-based entity alignment (Hungarian matching, invariant to IDs),
  parent-link scoring, unit-aware numeric matching; regression tests in
  `tests/test_evaluator_value_semantics.py`
- `evaluation/datasets/BENCHMARK_DATASHEET_20260721.md` and
  `APPROVED_SPLIT_MAP_20260721.json`: the frozen July release (27 studies)
- `evaluation/config/packages/petase_enzyme_engineering_package.json`: a
  temporary local package injection, not yet a published FAIR-DS package
- `fairifier/services/fair_data_station.py` and the FAIR-DS Excel export in
  `fairifier/graph/excel.py`: how FAIRiAgent reads packages and writes workbooks

- `docs/manuscript/SEMINAR_RUNS_WRAPUP_20261109.md` (read only): the
  `seminar_context_demo_20261102` run is the **earliest design-test
  prototype**. Its Task 1 is a membership test ("which samples belong to which
  group") and Task 2 a key-quantities test, both still answered through an LLM.
  The wrap-up plans to land deterministic design tests on the Hofmann 2019
  study first and to **rescore the saved outputs** (the 2026-11-01 runs, plus
  the B1/B2 baselines and full-system outputs) **without new agent runs**.
  Follow that plan: it gives the first real result for "field scores hide
  unusable records".

Known gaps you are here to close: **design tests do not exist yet**; Template
is not a first-class score; there are **no plan inputs**; the test suite itself
has never been validated; there is no public submission format, harness or
leaderboard.

## Hard rules

1. **Do not create, edit or "fix" expert reference records.** Annotations are
   the experts' responsibility. You may convert formats, validate against the
   schema and *report* suspected inconsistencies in a list for humans. Never
   invent a value, evidence quote or entity to make a test pass.
2. **Do not touch anything under `docs/manuscript/`**, and never open or edit
   the user's online documents.
3. **Do not revert or overwrite uncommitted changes** already in the working
   tree. Work on a new branch (or a worktree), commit in small steps, and do
   not push or open a PR unless asked.
4. **Source papers and annotations stay gitignored.** Version only code,
   schemas, configs, docs and small synthetic fixtures.
5. **The primary scores are deterministic.** No LLM judge in Template, Values
   or Resolved. An LLM may help *draft* design tests, but a human approves them
   before they count.
6. **Never inspect held-out results to tune anything.** Thresholds and design
   choices are fixed on the development split only.
7. **Keep the July 2026 artifacts unchanged.** A new instance set, split,
   scoring rule or package version means a new versioned release.
8. When a decision belongs to the researchers (see "Decisions to escalate"),
   **stop and ask**. Do not guess and move on.

## The ideal FAIRiBench: what to build

### 1. Task and submission format

- **Input bundle per instance:** the source text (PDF and/or extracted text),
  supplements and tables, plus a pinned FAIR-DS package snapshot (packages,
  terms, requirement levels M/R/O, allowed values), so that scores do not drift
  when the live FAIR-DS changes.
- **Two input views per study:**
  - `paper`: the published paper and supplements. Scored on Template and Values.
  - `plan`: a description of the experiment *before* it was run. Scored on
    Template only, plus planned factor levels. Prefer real plans linked to the
    paper (preregistration, registered report, published protocol). Where none
    exists, a *derived plan* (methods with results and measured values removed)
    is allowed only if it is labelled as derived and checked by a human.
- **Submission:** one JSON record per instance in a published schema
  (`fairibench.submission.v1`): selected packages, ISOSA rows per level with
  local IDs and parent links, field values with units, and optional evidence
  locators and confidence flags. Also accept a FAIR-DS Excel workbook through a
  converter, so that FAIR-DS users and FAIRiAgent outputs work unchanged.
- A validator rejects malformed submissions with a clear message. It does not
  silently repair them.

### 2. Instances

- Studies across several life-science fields, stratified by **design
  complexity**: number of factors, levels per factor, entities per level and
  depth of the ISOSA tree. Record these strata in the manifest; results are
  reported per stratum.
- A **post-cutoff subset** (published after the training cutoffs of the panel
  models), a canary string in all released files, and **private answers** for
  the test split.
- Splits: public development set with answers; test set with answers held by
  the scorer only. Keep the leakage audit passing.
- A datasheet for the release (reuse `BENCHMARK_DATASHEET_TEMPLATE.md`),
  including licences: redistribute only open-licence sources, otherwise ship
  DOIs plus a fetch script.

### 3. Design tests (the core new piece)

Design tests are short, executable questions about one study's experiment,
with answers fixed by the paper through the reference record. Example: *"Which
samples received treatment X at day 7?"*

- **Structure tests** score the template: counts per ISOSA level, which
  factors cross with which, which samples share a parent, which assay was run
  on which samples, whether required packages and terms are present.
- **Value tests** score the population: the value and unit of a field for an
  entity identified by its content, such as "the incubation temperature of the
  samples in the 40 °C arm".
- Define a small declarative query format (JSON) evaluated over the submitted
  ISOSA graph. Queries identify entities by **content, never by local IDs**,
  and reuse `_value_matching.py` for units, numbers and synonyms.
- **Equivalent encodings must score alike.** Implement an explicit,
  reviewable equivalence layer: synonym fields across packages, and placements
  that FAIR-DS allows on more than one level. The list of allowed equivalences
  is a researcher decision (escalate it), not something you infer.
- **Generation:** derive candidate tests automatically from each reference
  record using templates (counts, crossings, parent sets, key values). An LLM
  may phrase or extend them from the paper. Every test carries a source
  locator (section, table, figure) and a `status` of `draft` or `approved`.
  Only approved tests count toward the score.
- Store tests next to each study, for example
  `annotated/design_tests/<document_id>.json`, with a JSON schema and a CLI
  to list, run and review them.

### 4. Validate the test suite before trusting it

Show that the tests measure what they claim, using generated variants of the
reference records:

- **Equivalence transforms must pass:** renamed IDs, reordered rows, allowed
  alternative encodings.
- **Minimal corruptions must fail:** two samples merged, one entity dropped, a
  parent link swapped, a unit changed, a factor level shifted, a measurement
  attached to the wrong sample.
- **Null baselines must score near zero:** an empty record, the package
  template with no rows, majority or constant values, and a copy of another
  study's record.
- Report the **false-pass and false-fail rates** per test type. Tests that fail
  this check are fixed or dropped before release. This is Figure 1 of the
  manuscript.

### 5. Scores

- **Template score:** package and term selection (weighted by requirement
  level) plus structure tests.
- **Values score:** value tests plus field-level accuracy after
  content-based entity alignment.
- **Resolved rate:** share of studies whose record passes all approved tests.
  This is the headline number.
- **Field-level F1** as a secondary metric, reported next to Resolved, to show
  how field scores hide unusable records (manuscript Figure 3).
- **Reliability:** pass^k over k ≥ 3 reruns.
- **Cost:** tokens, wall time and hardware per instance, from the result
  envelope.
- Confidence intervals for every headline score; break down results by stratum
  and field of study.

### 6. Baselines

Ship runnable configs, all at an equal token budget where that applies:

- null baselines (from section 4);
- a single LLM call with the package in context;
- a single agent with the same tools and budget as FAIRiAgent;
- FAIRiAgent itself (existing harness);
- a **timed human-curator protocol** on a small subset. Prepare the protocol,
  forms and timing sheet only; humans run it.

### 7. Harness and release

- One command: `fairibench score --submissions <dir> --split dev` prints a
  score card (JSON and Markdown).
- A `fairibench run` adapter so any system can be plugged in through a small
  interface (input bundle in, submission out).
- Deterministic and reproducible: pinned package snapshot, versioned schemas,
  checksums in the manifest, a container or a locked environment.
- A leaderboard file format and a static page generator. Test-split scoring
  runs only on the maintainer side.
- Docs: a quickstart, the task definition, the submission schema, how design
  tests work, and how to add a study.

## Work packages and order

Run independent packages in parallel. Each package ends with tests passing and
a short note in `evaluation/fairibench/STATUS.md`.

| WP | Content | Depends on | Done when |
|---|---|---|---|
| 1 | Submission schema, validator, Excel-to-submission converter | none | FAIRiAgent outputs and all reference records validate; malformed fixtures are rejected |
| 2 | Pinned FAIR-DS package snapshots per study | none | every instance names a snapshot with a checksum; scoring makes no network calls |
| 3 | Design-test format, evaluator and equivalence layer; pilot on the Hofmann 2019 study by turning the context-demo tasks into deterministic queries | 1 | unit tests cover ID invariance, units, synonyms, equivalences; saved outputs for the pilot study are rescored with no new agent runs |
| 4 | Automatic test generation plus review CLI | 3 | draft tests exist for every development study; review workflow works end to end |
| 5 | Test-suite validation (mutations, null baselines) | 3, 4 | false-pass and false-fail table produced on the dev split |
| 6 | Scores and score card (Template, Values, Resolved, F1, pass^k, cost, CIs, strata) | 3 | the score card reproduces bit for bit from the same inputs |
| 7 | Plan view: collect linked real plans; derived-plan builder flagged for human check | 2 | each dev study has a plan view or a recorded reason why not |
| 8 | Baseline configs and the human-curator protocol | 1, 6 | every baseline runs on the dev split and appears on the score card |
| 9 | Release: manifest, splits, canary, datasheet, licences, leaderboard, docs | all | `release_gate.py` passes; a clean clone can score sample submissions |

## Decisions to escalate (ask; do not decide)

- Which equivalent encodings are allowed (needs FAIR-DS experts).
- The FAIR-DS package version to pin, and how to treat the temporary local
  package for one domain.
- The source of plan inputs: real linked plans only, or derived plans as well.
- The new split and the post-cutoff date.
- Which design tests are approved (humans approve; you only propose).
- Licences for redistributing each source.

## How to report back

At the end of each work package, and when you stop, report:

1. What now works, with the exact command that shows it.
2. Test results (paste the summary, including failures).
3. Suspected annotation inconsistencies found (list only; do not fix).
4. Open decisions waiting on the researchers.
5. What is not done or not verified.

Do not claim a score, a validation rate or a release is final until the
command that produces it has run and you have read its output.
