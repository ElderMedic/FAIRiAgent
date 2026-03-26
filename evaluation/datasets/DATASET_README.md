# Ground Truth Dataset

## Summary

**Tracked multi-document ground truth**: `evaluation/datasets/annotated/ground_truth_filtered.json` — 3 documents (`earthworm`, `biosensor`, `pomato`). Raw inputs under `evaluation/datasets/raw/` are gitignored.

**Confidential / local-only** (`document_id: biorem`): narrative and ground truth are **not** committed to public remotes; see [Confidential evaluation assets (biorem)](#confidential-evaluation-assets-biorem) below.

## Confidential evaluation assets (biorem)

- **Do not distribute** narrative content, Excel templates, or `.local.json` ground truth publicly.
- **Paths (all gitignored except scripts)**: place `BIOREM_Metadata.xlsx` and generated `BIOREM_study_narrative.md` / `BIOREM_study_narrative.pdf` under `evaluation/datasets/raw/biorem/`. Ground truth JSON: `evaluation/datasets/annotated/ground_truth_biorem.local.json` (ignored via `*.local.json`).
- **Regenerate after template changes** (from repo root, FAIRiAgent env):
  - `python evaluation/scripts/build_biorem_study_narrative.py --excel evaluation/datasets/raw/biorem/BIOREM_Metadata.xlsx --output evaluation/datasets/raw/biorem/BIOREM_study_narrative.md`
  - `python evaluation/scripts/md_to_pdf_simple.py evaluation/datasets/raw/biorem/BIOREM_study_narrative.md evaluation/datasets/raw/biorem/BIOREM_study_narrative.pdf`
  - `python evaluation/scripts/export_biorem_ground_truth_local.py`
- **Evaluate** with `--ground-truth evaluation/datasets/annotated/ground_truth_biorem.local.json` (and your usual run flags). Optional: Pandoc can replace `md_to_pdf_simple.py` if installed locally.

---

**Legacy note**: Older docs referred to `ground_truth_v1.json`; the active combined file is `ground_truth_filtered.json`.

## Papers Included

### 1. 📄 Earthworm
- **File**: `raw/earthworm/earthworm_4n_paper_bioRxiv.pdf`
- **Metadata**: `raw/earthworm/Diagonal_RNAseq_Earthworms.xlsx`
- **Fields**: 46 total (21 required, 25 recommended)
- **Source**: Manually curated ISA-Tab Excel file
- **ISA Coverage**: investigation(9), study(4), assay(20), sample(9), observationunit(4)

### 2. 📄 Biosensor
- **File**: `raw/biosensor/aec8570_CombinedPDF_v1.pdf`
- **Metadata**: `raw/biosensor/Whole-cell_biosensor_metadata.xlsx`
- **Fields**: 43 total (21 required, 22 recommended)
- **Source**: Manually curated ISA-Tab Excel file
- **ISA Coverage**: investigation(8), study(4), assay(13), sample(14), observationunit(4)

### 3. 📄 Pomato
- **Input**: Markdown under `raw/pomato/` (MinerU output path as in `ground_truth_filtered.json`)
- **Source**: Internal multi-scenario plant-pathology style annotation (see JSON `metadata.notes`)
- **Use**: Same evaluation flow as other tracked documents; details omitted here for brevity

## Conversion Process

### Earthworm & Biosensor
- Converted from Excel ISA-Tab format using `convert_excel_to_ground_truth.py`
- Each Excel sheet (investigation, study, assay, sample, observationunit) was parsed
- Field names from column headers, values from first non-null row
- Multiple rows treated as acceptable variations

### Confidential `biorem` (local)
- Built from the expert Excel template via `evaluation/scripts/export_biorem_ground_truth_local.py` and `evaluation/archive/scripts/convert_excel_to_ground_truth.py` (skips non-ISA `Help` sheet). Narrative MD is generated with `build_biorem_study_narrative.py`. Not part of the tracked `ground_truth_filtered.json` file.

## Data Quality

- ✅ All papers have complete ISA sheet coverage
- ✅ All required fields annotated
- ✅ Evidence locations documented
- ✅ Package sources identified (default, Illumina, MIAPPE, etc.)
- ✅ ISA sheet assignments validated

## Next Steps for Evaluation

### 1. Configure Environment

```bash
# Copy and edit evaluation config
cp evaluation/config/env.evaluation.template evaluation/config/env.evaluation
# Add your LangSmith API key and LLM provider keys
```

### 2. Run Batch Evaluation

```bash
# This will run FAIRiAgent on all 3 papers with different model configs
python3 evaluation/scripts/run_batch_evaluation.py \
  --env-file evaluation/config/env.evaluation \
  --model-configs evaluation/config/model_configs/*.env \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json \
  --output-dir evaluation/runs/run_$(date +%Y%m%d) \
  --workers 2
```

### 3. Evaluate Outputs

```bash
# Compute all quality metrics
python3 evaluation/scripts/evaluate_outputs.py \
  --env-file evaluation/config/env.evaluation \
  --run-dir evaluation/runs/run_$(date +%Y%m%d) \
  --ground-truth evaluation/datasets/annotated/ground_truth_v1.json
```

### 4. Generate Manuscript Materials

```bash
# Create publication-ready figures and tables
python3 evaluation/scripts/generate_report.py \
  --results-dir evaluation/runs/run_$(date +%Y%m%d)/results \
  --output-dir evaluation/runs/run_$(date +%Y%m%d)/manuscript_materials
```

## File Structure

```
evaluation/datasets/
├── raw/                                    # Your original papers
│   ├── earthworm/
│   │   ├── earthworm_4n_paper_bioRxiv.pdf
│   │   └── Diagonal_RNAseq_Earthworms.xlsx
│   ├── biosensor/
│   │   ├── aec8570_CombinedPDF_v1.pdf
│   │   └── Whole-cell_biosensor_metadata.xlsx
│   └── biorem/
│       └── BIOREM_appendix2.pdf
│
└── annotated/
    └── ground_truth_v1.json                # ✅ Complete ground truth dataset
```

## Notes

- **Dataset Size**: 3 papers is suitable for initial model comparison and validation
- **Field Coverage**: 140 total fields across all papers (good sample size)
- **Diversity**: Mix of genomics, biosensor, and bioremediation projects
- **Quality**: High-confidence annotations from manual curation and validated extraction

## Extending the Dataset

To add more papers in the future:

1. Place PDF and Excel metadata in `raw/{paper_id}/`
2. Run conversion script:
   ```bash
   python3 evaluation/scripts/convert_excel_to_ground_truth.py \
     --raw-dir evaluation/datasets/raw \
     --output evaluation/datasets/annotated/ground_truth_v2.json
   ```
3. Or manually edit `ground_truth_v1.json` to add new documents

