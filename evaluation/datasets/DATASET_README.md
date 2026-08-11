# FAIRiAgent Evaluation Datasets

> Last updated: 2026-07-21
>
> **Important — historical manuscript inventory.** This file lists 10 annotated
> documents plus the CompBioBench bundle. The former v1 composition used **8
> documents** as a main candidate and kept `biorem` and `pomato` supplementary;
> the benchmark version 2 release split is recorded in the approved split map
> below. `compbiobench` remains a separate research direction.

> **Ground-truth policy for benchmark version 2 (2026-07-21).** Ground truth is
> the human-annotated result converted into the repository format. A converter
> does not create evidence annotations. Evidence fields are optional metadata
> only and must never be required or inferred for PETase ground truth. The local
> PETase package is treated as the FAIR-DS package it mirrors; local transport is
> not a contamination condition. See
> `evaluation/EVALUATION_IMPROVEMENT_PLAN.md` for the maintained benchmark
> contract.

> **Public curated collection (2026-07-21).**
> `ground_truth_public_curated.json` is now the canonical 27-document public
> collection: 19 expert-annotated PETase papers, six published mixed-domain
> studies, `biosensor`, and `earthworm`. `biorem`, `pomato`, and
> `compbiobench` are explicitly excluded and were not altered by this curation
> pass. This collection resolves the PETase overlap by treating
> `ground_truth_petase_only.json`/the expert PETase JSON sources as authoritative
> for all 19 PETase documents. Development/held-out roles are recorded in the
> approved split map below.

## Benchmark version 2 split checkpoint

The annotation-authority part of this checkpoint is resolved for the new public
collection: expert PETase JSON is authoritative for the 19-paper PETase series,
and the three excluded datasets are outside this collection. The approved
development/held-out assignment is recorded separately from the curation audit.
For the current release decision, `biorem` and `pomato` are excluded from the
evaluation manifest; they remain available for a future separately labelled
stress/case-study release.
See [RELEASE_DECISION_CHECKPOINT.md](RELEASE_DECISION_CHECKPOINT.md) for the
exact choices and their effects. The current token-free 7-development/
20-held-out proposal is recorded in
[SPLIT_PROPOSAL_20260721.md](SPLIT_PROPOSAL_20260721.md). It was approved as
`researcher-approved:benchmark-v2-split-20260721` and persisted in
[APPROVED_SPLIT_MAP_20260721.json](APPROVED_SPLIT_MAP_20260721.json).

The repository also retains two historical annotation collections that must not
be silently merged into a release manifest:

| Collection | Documents | Current contents | Release role |
|---|---:|---|---|
| `ground_truth_phase4_ab.json` | 8 | six mixed-domain documents plus two PETase papers | Historical collection definition; no GT authority |
| `ground_truth_petase_only.json` | 19 | PETase papers, including the same two papers above | PETase-specialized view; canonical authority for all 19 PETase documents |

The PETase overlap is exactly `petase_10_1002_anie_202218390` and
`petase_10_1038_s41586-020-2149-4`; the active release uses the complete
canonical v3 value asset from `petase_only` for both and never merges fields
across collections. `ground_truth_biorem.local.json` is a separate historical
case-study collection and is outside the current release. The
development/held-out roles are now fixed by the approved split map. The
frozen-panel production manifest is now materialized at
`output/benchmark_v2_20260721_release_prep/production_manifest_20260721.json`;
its post-panel release gate passes all preparation checks and remains blocked
only until a campaign run index is attached.

### Measured source-layout signals

`evaluation/benchmark/dataset_inventory.py` reports measured PDF layout signals
separately from declared benchmark strata. These include text-block counts,
image-page counts, sparse/no-text pages, and PyMuPDF table-detection counts and
status. They are diagnostic observations, not automatic OCR-quality or
table-density labels; Markdown and other non-PDF sources remain explicitly
`not_measured` where a signal does not apply. Production stress strata still
require a documented sampling/adjudication decision.

For a historical collection other than `ground_truth_public_curated.json`, use
`evaluation.benchmark.annotation_audit` with repeated
`--authoritative-overlap DOCUMENT_ID=COLLECTION_PATH` arguments to create a
non-overlapping collection. The helper copies one complete annotation per
document and carries adjacent `values/ground_truth_<id>_values.json` references;
it does not merge fields or add evidence. The current token-free audit report
is persisted at
`output/benchmark_v2_20260721_release_prep/annotation_audit_20260721.json`;
it compares canonical value files separately from legacy metadata/path fields.

All PETase ground truth in both collections is the human-annotated result
converted into repository JSON. The current files contain no `_evidence`
annotations; the benchmark does not add or infer them.

## Directory Structure

```
evaluation/datasets/
├── DATASET_README.md              ← this file
├── annotated/
│   ├── ground_truth_filtered.json ← master index: 10 documents, field definitions only (no values)
│   ├── ground_truth_public_curated.json ← canonical public index (27 documents; three exclusions)
│   ├── public_schema_profile.json  ← observed core/extension field frequencies; descriptive, not required
│   ├── compbiobench_metadata.json ← CompBioBench dataset (separate format)
│   └── values/
│       └── ground_truth_{id}_values.json  ← source-backed values under the permissive v3 contract
├── raw/
│   ├── {dataset_id}/
│   │   ├── study_narrative.md     ← input document: research description in ISA-like format
│   │   ├── paper.pdf / paper.md   ← source publication (full text)
│   │   └── ...                    ← supplementary materials, mineru output, etc.
│   └── compbiobench_metadata/     ← CompBioBench raw data (bioinformatics files)
```

## Dataset Overview (10 documents)

### Research datasets (6) — expert-curated from published papers + ENA metadata

| # | Dataset ID | Domain | ENA/NCBI Project | Publication |
|---|-----------|--------|-----------------|-------------|
| 1 | `arabidopsis_vacuolar_srna` | Plant cell biology — vacuolar sRNA degradation | PRJEB41301 | Hickl et al. (2019) bioRxiv 793950 |
| 2 | `pea_cold_stress` | Crop stress physiology — cold miRNA-mRNA time series | PRJNA543764 | Mazurier et al. (2022) Genes 13:1119 |
| 3 | `sea_cucumber_gut_metagenome` | Marine microbiology — gut metagenome | PRJNA1061805 | Rivera-Lopez et al. (2024) Data in Brief 54:110421 |
| 4 | `human_gut_microbiome_temporal` | Human microbiome — preservation time course | PRJNA827663 | Kumar & Bhadury (2024) Data in Brief 57:110961 |
| 5 | `aetherobacter_fasciculatus_genome` | Bacterial genomics — ONT WGS + BGC mining | PRJEB72099 | Campos-Magana et al. (2025) Microb Biotechnol 18:e70104 |
| 6 | `pseudomonas_recombinase_screen` | Synthetic biology — SSAP recombinase screen | PRJEB56403 | Asin-Garcia et al. (2023) Nucleic Acids Res 51:12522 |

### Original datasets (4) — curated from templates, proposals, and metadata spreadsheets

| # | Dataset ID | Domain | Source |
|---|-----------|--------|--------|
| 7 | `biorem` | Environmental biotechnology — bioremediation project | BIOREM metadata template (Excel) |
| 8 | `biosensor` | Synthetic biology — whole-cell biosensor | Research paper (PDF + mineru) |
| 9 | `earthworm` | Environmental toxicology — RNA-seq | Research paper (bioRxiv PDF + mineru) |
| 10 | `pomato` | Plant metabolomics — potato project proposal | EU project proposal (PDF + mineru) |

### Bioinformatics benchmark

| # | Dataset ID | Description |
|---|-----------|-------------|
| — | `compbiobench_metadata` | 31 documents, 231 FAIR-DS fields. Bioinformatic file analysis tasks (BAM, FASTQ, VCF, H5AD, etc.) |

## Ground Truth Format

### `ground_truth_filtered.json` (master index)

Contains field definitions only — which metadata fields should be extracted, organized by ISA sheet:

```json
{
  "documents": [{
    "document_id": "...",
    "document_path": "...",
    "metadata": { "domain": "...", "experiment_type": "..." },
    "ground_truth_fields": [
      { "field_name": "...", "isa_sheet": "investigation", "is_required": true, ... }
    ],
    "ground_truth_stats": {
      "total_required_fields": N,
      "total_recommended_fields": N,
      "by_isa_sheet": { "investigation": { "total": N, "required": N, "recommended": N }, ... }
    }
  }]
}
```

### `values/ground_truth_{id}_values.json` (per-dataset)

Contains expected source-reported metadata values under the permissive
`fairiagent.ground_truth_values.v3` contract. Every document records original
source assets and checksums, publication metadata where verified, annotation
policy, a linked ISA core, and domain extensions. Missing/unreported fields are
omitted and are not scored; placeholder strings are prohibited. The schema is
`evaluation/schemas/ground_truth_values.schema.json`.

```json
{
  "document_id": "...",
  "schema_version": "fairiagent.ground_truth_values.v3",
  "publication": {"doi": "...", "title": "..."},
  "schema_profile": {
    "core": "fairds_isa_linked_core_v1",
    "extensions": ["domain_extension"],
    "field_policy": "source_reported_fields_only"
  },
  "source_assets": [{"path": "...", "role": "primary_source", "sha256": "..."}],
  "isa_sheets": {
    "investigation": {
      "multi_row": true,
      "expected_rows": [{ "investigation identifier": "..." }]
    },
    "study": { ... },
    "assay": { ... },
    "sample": { ... },
    "observationunit": { ... }
  }
}
```

## ISA Sheet Coverage

Each dataset populates ISA sheets according to its study design:

| Dataset | Investigation | Study | Assay | Sample | ObsUnit |
|---------|:---:|:---:|:---:|:---:|:---:|
| arabidopsis_vacuolar_srna | ✓ | ✓ | ✓ (sRNA-seq) | ✓ (9) | ✓ (sRNome) |
| pea_cold_stress | ✓ | ✓ | ✓ (sRNA + mRNA) | ✓ (24) | ✓ (miRNA) |
| sea_cucumber_gut_metagenome | ✓ | ✓ | ✓ (metagenome) | ✓ (3) | ✓ (taxonomy) |
| human_gut_microbiome_temporal | ✓ | ✓ | ✓ (Illumina + ONT) | ✓ (6) | ✓ (taxonomy) |
| aetherobacter_fasciculatus_genome | ✓ | ✓ | ✓ (ONT + annotation + TAR) | ✓ (1) | ✓ (genome + BGC) |
| pseudomonas_recombinase_screen | ✓ | ✓ | ✓ (ONT screen + WGS + ARF) | ✓ (4 species) | ✓ (ARF) |
| biorem | ✓ | ✓ | ✓ (metagenomic WGS) | ✓ (multiple) | ✓ (sample metadata) |
| biosensor | ✓ | ✓ | ✓ (biosensor assay) | ✓ (multiple) | ✓ |
| earthworm | ✓ | ✓ | ✓ (RNA-seq) | ✓ (multiple) | ✓ |
| pomato | ✓ | ✓ | — | ✓ (multiple) | ✓ (64 fields) |

Numbers in parentheses = number of expected rows (for multi-row sheets).

## Paper Sources

| Dataset | Paper File | Format | Source |
|---------|-----------|--------|--------|
| arabidopsis_vacuolar_srna | `paper.md` (102 KB) | Markdown | bioRxiv web_fetch |
| pea_cold_stress | `paper.pdf` (1.6 MB) | PDF | MDPI OA direct download |
| sea_cucumber_gut_metagenome | `paper.pdf` (954 KB) | PDF | Europe PMC render (PMC11058721) |
| human_gut_microbiome_temporal | `paper.pdf` (627 KB) | PDF | Europe PMC render (PMC11467544) |
| aetherobacter_fasciculatus_genome | `paper.pdf` (630 KB) | PDF | Europe PMC render (PMC11876861) |
| pseudomonas_recombinase_screen | `paper.pdf` (1.5 MB) | PDF | Europe PMC render (PMC10711431) |

## Historical credibility tiers and manuscript roles

The following tiers are a historical provenance inventory, not the benchmark
version 2 split. They describe source type and curation history; a legacy
`_evidence` count is shown only as a diagnostic where it was recorded. It is
not a ground-truth quality gate, and it is never required for PETase.

> **Structural/Hierarchical F1, precisely defined:** this is *not* a single opaque number. It is `StructuralEvaluator` (Layer 3, `evaluation/evaluators/structural_evaluator.py`), reported as two independently-computed sub-metrics plus their combination -- see the Metrics Glossary in `evaluation/README.md` for exact formulas:
> - **3a. Sheet-placement accuracy** -- did each extracted field land on the correct ISA sheet (`investigation`/`study`/`sample`/`observationunit`/`assay`), independent of its value?
> - **3b. Row-alignment F1** -- CEAF-style (Hungarian-algorithm) optimal one-to-one matching between predicted and ground-truth rows for multi-row sheets, reported as `row_alignment_recall`/`row_alignment_precision`/`row_alignment_f1`. This catches merged/split-entity failures (e.g. 3 samples collapsed into 1 row) that a flat field-name F1 cannot see.
>
> This requires the per-document *value*-level ground truth under `values/ground_truth_{document_id}_values.json` (see "`values/ground_truth_{id}_values.json` (per-dataset)" below for its schema) -- not just the `ground_truth_fields` field-presence GT used for Layer 1. Documents without a matching `values/` file are skipped for Layer 2/3 and only scored on Layer 1 (field-name coverage).

The legacy audit results (2026-05-07) are below. They do not freeze the v2
development, held-out, generalization, or supplemental roles.

### Tier A — High-credibility research papers (6 docs, v1 candidate core)

| Dataset | `generated_by` | DOI | legacy evidence diagnostic | Notes |
|---|---|---|---|---|
| `arabidopsis_vacuolar_srna` | `manual_curation_from_paper_bioRxiv` | ✓ | 13/13 (100%) | bioRxiv 793950, ENA PRJEB41301 |
| `pea_cold_stress` | `manual_curation_from_paper_Mazurier` | ✓ | 11/11 (100%) | MDPI Genes 13:1119 |
| `sea_cucumber_gut_metagenome` | `manual_curation_from_paper_PMC1105…` | ✓ | 7/7 (100%) | Data in Brief 54:110421 |
| `human_gut_microbiome_temporal` | `manual_curation_from_paper_PMC1146…` | ✓ | 11/11 (100%) | Data in Brief 57:110961 |
| `aetherobacter_fasciculatus_genome` | `manual_curation_from_paper_PMC1187…` | ✓ | 9/9 (100%) | Microb Biotechnol 18:e70104 |
| `pseudomonas_recombinase_screen` | `manual_curation_from_paper_PMC1071…` | ✓ | 10/10 (100%) | Nucleic Acids Res 51:12522 |

All Tier-A datasets have peer-reviewed publications and ENA/NCBI accessions.
Their legacy evidence diagnostics must not be confused with human annotation
requirements.

### Tier B — Research-paper sources with lighter curator metadata (2 docs, v1 candidate core)

| Dataset | `generated_by` | DOI | legacy evidence diagnostic | Source | Notes |
|---|---|---|---|---|---|
| `biosensor` | `manual review of source document` | — | 18/18 (100%) | Research paper PDF (mineru) | No top-level DOI field, but `_evidence` rows are populated |
| `earthworm` | `manual review of source document` | — | 20/20 (100%) | bioRxiv preprint PDF (mineru) | Used as the primary smoke/diagnostic dataset; confirmed real research paper |

Tier-B rows were historically audited with the same optional diagnostic, but
that diagnostic is not required by the v2 contract. Add DOI fields if they are
needed for publication provenance.

### Tier C — Supplementary case-study candidates (2 docs)

| Dataset | `generated_by` | legacy evidence diagnostic | Source/role consideration | Manuscript role |
|---|---|---|---|---|
| `biorem` | `manual review of source document` | 35/35 (100%) | Source is a **BIOREM metadata template (Excel)**, not a research paper. Domain language differs from FAIR-DS terms; B1 zero-shot scored 0.838 because GT field names are template-aligned (artifact, not generalisable). | Supplementary §S — "structured-template" stress test |
| `pomato` | `manual review of source document` | **0/18 (0%)** | Source is an **EU project proposal**, not a research paper; ground truth has 789 fields, no Assay sheet (only inv/study/sample/observationunit), and **none of the rows carry `_evidence` strings**. B1 scored 0.040 on it because the field-name conventions in the GT do not appear in the source. | Supplementary §S — "proposal/grant document" case study |

These two datasets remain valuable as illustrations of edge cases
(template-aligned vs. proposal-style sources). Their v2 role and weighting must
be decided by the release split, not inferred from legacy scores.

### Tier D — Bioinformatics agentic benchmark (separate research direction)

| Dataset | `generated_by` | Role |
|---|---|---|
| `compbiobench_metadata` | bioinformatics file-extraction tasks (BAM, FASTQ, VCF, H5AD…) | **Different evaluation target.** Tests the BioMetadataAgent's Docker-tool execution path, not document-based ISA reconstruction. Reported as a separate stress test in the manuscript Discussion / Supplementary, not aggregated with Tier A+B numbers. |

CompBioBench's evaluation flow is `data file → biocontainer tool → metadata extraction`, whereas Tiers A/B evaluate `paper text → ISA-Tab reconstruction`. Keeping them separate avoids comparing apples to oranges.

### Historical manuscript benchmark composition (v1)

| Tier | Count | Datasets | Role |
|---|---|---|---|
| A — peer-reviewed papers | 6 | arabidopsis_vacuolar_srna, pea_cold_stress, sea_cucumber_gut_metagenome, human_gut_microbiome_temporal, aetherobacter_fasciculatus_genome, pseudomonas_recombinase_screen | Main benchmark |
| B — research paper, lighter metadata | 2 | biosensor, earthworm | Main benchmark |
| C — non-paper sources | 2 | biorem, pomato | Supplementary case studies |
| D — bioinformatics agentic | 1 bundle | compbiobench_metadata | Separate stress test |

This historical composition had **8 documents** in the main benchmark. It is
not the v2 release composition; v2 uses the approved 27-document map described
above.

### Open credibility items (to address before final submission)

1. **Publication provenance:** completed for Earthworm using the verified
   bioRxiv DOI `10.1101/2025.06.16.660036`. Biosensor remains explicitly tagged
   `doi_status: not_present_in_source`; a DOI must not be invented before the
   manuscript has a verifiable registration.
2. **Re-run a 5%-sample re-annotation by a second curator** on Tier-A + Tier-B (≥ 1 row per sheet per dataset) and report Cohen's κ. This is the cheapest evidence that the ground truth is not single-curator artefact.
3. **Tag any LLM-assisted annotations explicitly** (e.g. add `_annotation_method: "llm_drafted_then_human_reviewed"` per row where applicable). The current `generated_by` field reads "manual" everywhere, but if any draft pass used an LLM the manuscript should disclose it for transparency.
4. **Case-study role decision:** resolved for this release — `biorem` and
   `pomato` are excluded from the evaluation manifest and remain available for
   a future separately labelled stress/case-study release.

---

## How to Add a New Dataset

1. Create `evaluation/datasets/raw/{dataset_id}/` with:
   - `study_narrative.md` — input document describing the research in ISA-like format
   - `paper.pdf` or `paper.md` — source publication full text

2. Create `evaluation/datasets/annotated/values/ground_truth_{dataset_id}_values.json`:
   - Follow the existing schema with `isa_sheets` → `expected_rows`
   - Preserve the evidence policy of the annotation protocol. Do not invent `_evidence`; PETase annotations are valid without it.
   - Use FAIR-DS terms and packages relevant to the study domain

3. Rebuild `ground_truth_filtered.json`:
   ```bash
   python3 -c "
   # Read all values files, extract field definitions, write filtered.json
   "
   ```
