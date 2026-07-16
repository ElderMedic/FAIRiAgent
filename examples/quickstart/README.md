# 🐛 FAIRiAgent Quickstart: Earthworm RNA-seq Toxicology Study

Welcome to the FAIRiAgent Quickstart! This folder contains a pre-packaged, non-sensitive, fully public test dataset designed to help you quickly run and experience the complete FAIRiAgent multi-agent workflow.

This dataset demonstrates FAIRiAgent metadata extraction and ISA-Tab reconstruction on a complex multi-experimental biomedical study.

---

## 📂 Dataset Overview

The test dataset is based on the following peer-reviewed bioRxiv preprint:
*   **Study Title**: *Gene expression profile dynamics of earthworms exposed to ZnO and ZnO:Mn nanomaterials*
*   **Subject**: Environmental Toxicology / Transcriptomics (RNA-seq)
*   **Host Organism**: *Eisenia fetida* (Earthworm)
*   **Experimental Design**: Three distinct exposure experiments profiling gene expression dynamics over a time series (days 2, 3, 4, 7, and 14) under control, zinc oxide nanomaterial (ZnO NM), zinc oxide/manganese multicomponent nanomaterial (ZnO:Mn MCNM), and manganese chloride ($MnCl_2$) conditions.

### Files Included:
1. **`earthworm_4n_paper_bioRxiv.md`**: The preprint text converted to Markdown. Running on Markdown avoids requiring MinerU PDF conversion for this example.
2. **`Diagonal_RNAseq_Earthworms.xlsx`**: A supplementary spreadsheet with wet-lab measurements such as sample volumes, concentrations, and RQN values.
3. **`ground_truth_earthworm_values.json`**: Expert-curated reference values for evaluating extraction results.

---

## 🌟 Key Capabilities Showcased

Running this quickstart demonstrates the core advanced features of FAIRiAgent:

1. **Multi-Source Ingestion Auto-Discovery**:
    When you pass the `.md` paper to FAIRiAgent, it automatically scans the parent directory, discovers the adjacent `Diagonal_RNAseq_Earthworms.xlsx` spreadsheet, parses its rows, and makes them searchable. The agent will retrieve wet-lab measurements from the Excel sheets and merge them with paper text context.
2. **Multi-Agent Critique and Self-Correction**:
    The agent iterates across 6 distinct stages (Document Parsing, Knowledge Retrieval, JSON Generation, Value Mapping, and LLM Critic loops) to align the multi-row `observationunit`, `sample`, and `assay` tables, achieving clean structural conformity.

---

## 🚀 Execution Instructions

### Step 1: Environment Setup
Make sure you have configured your LLM provider in your `.env` file.

### Step 2: Run the Workflow
Execute the CLI pipeline command:
```bash
mamba run -n FAIRiAgent python run_fairifier.py process examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose
```

### Step 3: Inspect the Outputs
Once completed, a run output folder will be generated under `output/fairifier_<timestamp>_xxxxxx/` containing:
*   `metadata.json`: The fully structured ISA-Tab metadata JSON.
*   `metadata_fairds.xlsx`: The spreadsheet ready to be loaded into the FAIR Data Station.
*   `workflow_report.txt` / `workflow_report.json`: Detailed execution report and quality metrics.

---

## Evaluation note

Outputs depend on the selected model, runtime configuration, and service availability. Use `ground_truth_earthworm_values.json` with the evaluation utilities when you need reproducible quality measurements; the quickstart does not promise a fixed score across providers or model versions.
