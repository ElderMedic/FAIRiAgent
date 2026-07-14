# 🐛 FAIRiAgent Quickstart: Earthworm RNA-seq Toxicology Study

Welcome to the FAIRiAgent Quickstart! This folder contains a pre-packaged, non-sensitive, fully public test dataset designed to help you quickly run and experience the complete FAIRiAgent multi-agent workflow.

This dataset showcase highlights FAIRiAgent's ability to achieve **extraordinarily high-quality metadata extraction and ISA-Tab reconstruction** on complex multi-experimental biomedical datasets.

---

## 📂 Dataset Overview

The test dataset is based on the following peer-reviewed bioRxiv preprint:
*   **Study Title**: *Gene expression profile dynamics of earthworms exposed to ZnO and ZnO:Mn nanomaterials*
*   **Subject**: Environmental Toxicology / Transcriptomics (RNA-seq)
*   **Host Organism**: *Eisenia fetida* (Earthworm)
*   **Experimental Design**: Three distinct exposure experiments profiling gene expression dynamics over a time series (days 2, 3, 4, 7, and 14) under control, zinc oxide nanomaterial (ZnO NM), zinc oxide/manganese multicomponent nanomaterial (ZnO:Mn MCNM), and manganese chloride ($MnCl_2$) conditions.

### Files Included:
1.  **[earthworm_4n_paper_bioRxiv.md](file:///Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent/examples/quickstart/earthworm_4n_paper_bioRxiv.md)**: The full text of the research paper preprint pre-converted to clean Markdown. By running directly on Markdown, you bypass the need for a MinerU PDF conversion server, making your trial **lightning-fast** and **100% reproducible**.
2.  **[Diagonal_RNAseq_Earthworms.xlsx](file:///Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent/examples/quickstart/Diagonal_RNAseq_Earthworms.xlsx)**: The supplementary excel spreadsheet containing the precise wet-lab measurements (sample volumes, concentrations, RQN values, etc.) not described in the main manuscript text.
3.  **[ground_truth_earthworm_values.json](file:///Users/changlinke/Documents/Main/SSB/PhD/Research/FAIRiAgent/examples/quickstart/ground_truth_earthworm_values.json)**: The expert-curated ground truth metadata values (with specific text span evidence) used to measure the extraction accuracy.

---

## 🌟 Key Capabilities Showcased

Running this quickstart demonstrates the core advanced features of FAIRiAgent:

1.  **Multi-Source Ingestion Auto-Discovery**: 
    When you pass the `.md` paper to FAIRiAgent, it automatically scans the parent directory, discovers the adjacent `Diagonal_RNAseq_Earthworms.xlsx` spreadsheet, parses its rows, and makes them searchable. The agent will retrieve wet-lab measurements from the Excel sheets and merge them with paper text context.
2.  **External Grounding (NCBI & ENA)**:
    The agent detects the host organism (*Eisenia fetida*) and uses science tools to query the NCBI Taxonomy Registry to resolve its Taxonomy ID (`1510822`).
3.  **Multi-Agent Critique and Self-Correction**:
    The agent iterates across 6 distinct stages (Document Parsing, Knowledge Retrieval, JSON Generation, Value Mapping, and LLM Critic loops) to align the multi-row `observationunit`, `sample`, and `assay` tables, achieving clean structural conformity.

---

## 🚀 Execution Instructions

### Step 1: Environment Setup
Make sure you have configured your LLM provider in your `.env` file (e.g., using DeepSeek, GPT-4, or Qwen). 

### Step 2: Run the Workflow
Execute the CLI pipeline command:
```bash
python run_fairifier.py process examples/quickstart/earthworm_4n_paper_bioRxiv.md --verbose
```

### Step 3: Inspect the Outputs
Once completed, a run output folder will be generated under `output/fairifier_<timestamp>_xxxxxx/` containing:
*   `metadata.json`: The fully structured ISA-Tab metadata JSON.
*   `metadata_fairds.xlsx`: The spreadsheet ready to be loaded into the FAIR Data Station.
*   `workflow_report.txt` / `workflow_report.json`: Detailed execution report and quality metrics.
*   `auto_repair_trace.json`: Log of the self-correction patches applied.

---

## 📈 Expected Performance Metrics

When run with advanced models (such as **Qwen-Max** or **DeepSeek Pro**), this dataset achieves the highest tier of evaluation results:

| Evaluation Metric | Target Performance | Description |
| :--- | :---: | :--- |
| **Mandatory Field Coverage** | **100.00%** 🏆 | All mandatory metadata fields required by ENA/ISA are successfully extracted. |
| **Overall Completeness (Recall)** | **81.00% - 83.33%** | Captures all experimental details, sample mappings, and laboratory measurements. |
| **Sheet-Placement Accuracy** | **>99.00%** | Flawlessly routes properties to the correct sheet (Investigation, Study, Sample, Assay, etc.). |
| **JSON Schema Compliance** | **100.00%** | The generated JSON structure is fully valid under the target schema definitions. |
