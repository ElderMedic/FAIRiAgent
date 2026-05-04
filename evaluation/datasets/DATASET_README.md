# FAIRiAgent Evaluation Datasets

> Last updated: 2026-05-04

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
