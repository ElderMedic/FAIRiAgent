# FAIRiAgent Evaluation Datasets

> Last updated: 2026-05-07
>
> **Important — manuscript benchmark composition.** This file lists 10 annotated documents plus the CompBioBench bundle. For the manuscript, these are partitioned into three roles (see §"Credibility Tiers and Manuscript Roles" below). The current main benchmark is **8 documents**; `biorem` and `pomato` are kept as supplementary case studies, and `compbiobench` is a separate research direction.

## Directory Structure

```
evaluation/datasets/
├── DATASET_README.md              ← this file
├── annotated/
│   ├── ground_truth_filtered.json ← master index: 10 documents, field definitions only (no values)
│   ├── compbiobench_metadata.json ← CompBioBench dataset (separate format)
│   └── values/
│       └── ground_truth_{id}_values.json  ← per-dataset expected metadata values with _evidence
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

Contains expected metadata values with `_evidence` traceability:

```json
{
  "document_id": "...",
  "paper_doi": "...",
  "isa_sheets": {
    "investigation": {
      "multi_row": true,
      "expected_rows": [{ "investigation identifier": "...", "_evidence": "..." }]
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

## Credibility Tiers and Manuscript Roles

The 10 annotated documents differ in (a) source provenance — peer-reviewed paper vs. template/proposal — and (b) annotation traceability — whether each ground-truth row carries an `_evidence` string back to a specific span of the source. For the manuscript, this matters because the headline claims (Hierarchical-F1, Pass@k, ablation McNemar) must rest on ground truth that an external reviewer would accept.

The audit results (2026-05-07) are below.

### Tier A — High-credibility research papers (6 docs, **always in main benchmark**)

| Dataset | `generated_by` | DOI | _evidence rows | Notes |
|---|---|---|---|---|
| `arabidopsis_vacuolar_srna` | `manual_curation_from_paper_bioRxiv` | ✓ | 13/13 (100%) | bioRxiv 793950, ENA PRJEB41301 |
| `pea_cold_stress` | `manual_curation_from_paper_Mazurier` | ✓ | 11/11 (100%) | MDPI Genes 13:1119 |
| `sea_cucumber_gut_metagenome` | `manual_curation_from_paper_PMC1105…` | ✓ | 7/7 (100%) | Data in Brief 54:110421 |
| `human_gut_microbiome_temporal` | `manual_curation_from_paper_PMC1146…` | ✓ | 11/11 (100%) | Data in Brief 57:110961 |
| `aetherobacter_fasciculatus_genome` | `manual_curation_from_paper_PMC1187…` | ✓ | 9/9 (100%) | Microb Biotechnol 18:e70104 |
| `pseudomonas_recombinase_screen` | `manual_curation_from_paper_PMC1071…` | ✓ | 10/10 (100%) | Nucleic Acids Res 51:12522 |

All Tier-A datasets have peer-reviewed publications, ENA/NCBI accessions, and per-row `_evidence` strings. They are the credibility backbone of the manuscript.

### Tier B — Research-paper sources with lighter curator metadata (2 docs, **in main benchmark**)

| Dataset | `generated_by` | DOI | _evidence rows | Source | Notes |
|---|---|---|---|---|---|
| `biosensor` | `manual review of source document` | — | 18/18 (100%) | Research paper PDF (mineru) | No top-level DOI field, but `_evidence` rows are populated |
| `earthworm` | `manual review of source document` | — | 20/20 (100%) | bioRxiv preprint PDF (mineru) | Used as the primary smoke/diagnostic dataset; confirmed real research paper |

Tier-B datasets keep the same per-row evidence discipline as Tier A but lack a top-level `paper_doi` field. Add the DOI fields before submission.

### Tier C — Supplementary case studies (2 docs, **excluded from main benchmark for v1 manuscript**)

| Dataset | `generated_by` | _evidence rows | Reason for exclusion | Manuscript role |
|---|---|---|---|---|
| `biorem` | `manual review of source document` | 35/35 (100%) | Source is a **BIOREM metadata template (Excel)**, not a research paper. Domain language differs from FAIR-DS terms; B1 zero-shot scored 0.838 because GT field names are template-aligned (artifact, not generalisable). | Supplementary §S — "structured-template" stress test |
| `pomato` | `manual review of source document` | **0/18 (0%)** | Source is an **EU project proposal**, not a research paper; ground truth has 789 fields, no Assay sheet (only inv/study/sample/observationunit), and **none of the rows carry `_evidence` strings**. B1 scored 0.040 on it because the field-name conventions in the GT do not appear in the source. | Supplementary §S — "proposal/grant document" case study |

These two datasets remain valuable as illustrations of edge cases (template-aligned vs. proposal-style sources) but cannot be averaged into the main hierarchical-F1 number without distorting it.

### Tier D — Bioinformatics agentic benchmark (separate research direction)

| Dataset | `generated_by` | Role |
|---|---|---|
| `compbiobench_metadata` | bioinformatics file-extraction tasks (BAM, FASTQ, VCF, H5AD…) | **Different evaluation target.** Tests the BioMetadataAgent's Docker-tool execution path, not document-based ISA reconstruction. Reported as a separate stress test in the manuscript Discussion / Supplementary, not aggregated with Tier A+B numbers. |

CompBioBench's evaluation flow is `data file → biocontainer tool → metadata extraction`, whereas Tiers A/B evaluate `paper text → ISA-Tab reconstruction`. Keeping them separate avoids comparing apples to oranges.

### Manuscript benchmark composition (v1)

| Tier | Count | Datasets | Role |
|---|---|---|---|
| A — peer-reviewed papers | 6 | arabidopsis_vacuolar_srna, pea_cold_stress, sea_cucumber_gut_metagenome, human_gut_microbiome_temporal, aetherobacter_fasciculatus_genome, pseudomonas_recombinase_screen | Main benchmark |
| B — research paper, lighter metadata | 2 | biosensor, earthworm | Main benchmark |
| C — non-paper sources | 2 | biorem, pomato | Supplementary case studies |
| D — bioinformatics agentic | 1 bundle | compbiobench_metadata | Separate stress test |

**Main benchmark size:** **8 documents**. Domains covered: plant transcriptomics, marine metagenomics, microbial genomics, microbial genetics / synthetic biology, environmental microbiology, human microbiome, ecotoxicology, biosensors → **7 distinct domains**.

### Open credibility items (to address before final submission)

1. **Add `paper_doi` to Tier-B JSONs** (biosensor, earthworm) so every main-benchmark row has a citeable source.
2. **Re-run a 5%-sample re-annotation by a second curator** on Tier-A + Tier-B (≥ 1 row per sheet per dataset) and report Cohen's κ. This is the cheapest evidence that the ground truth is not single-curator artefact.
3. **Tag any LLM-assisted annotations explicitly** (e.g. add `_annotation_method: "llm_drafted_then_human_reviewed"` per row where applicable). The current `generated_by` field reads "manual" everywhere, but if any draft pass used an LLM the manuscript should disclose it for transparency.
4. **`pomato` re-curation:** add `_evidence` strings to all 18 rows (currently 0/18) before re-introducing it into the main benchmark.

---

## How to Add a New Dataset

1. Create `evaluation/datasets/raw/{dataset_id}/` with:
   - `study_narrative.md` — input document describing the research in ISA-like format
   - `paper.pdf` or `paper.md` — source publication full text

2. Create `evaluation/datasets/annotated/values/ground_truth_{dataset_id}_values.json`:
   - Follow the existing schema with `isa_sheets` → `expected_rows`
   - Every field value must have `_evidence` tracing back to paper or ENA metadata
   - Use FAIR-DS terms and packages relevant to the study domain

3. Rebuild `ground_truth_filtered.json`:
   ```bash
   python3 -c "
   # Read all values files, extract field definitions, write filtered.json
   "
   ```
