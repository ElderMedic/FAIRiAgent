# FAIRiAgent Evaluation Methodology & Workflow Technical Report

## 1. System Overview & Workflow Design

The **FAIRiAgent** (FAIR-enabling Intelligent Agent) is designed as a multi-step, reflective agentic workflow capable of autonomously extracting, validating, and structuring scientific metadata from unstructured documents (PDFs) into standardized formats (ISA-Tab).

### 1.1 Agentic Architecture
The core workflow implements a **Plan-Execute-Critique-Refine** loop:

1.  **Document Ingestion & Parsing:**
    *   Utilizes **MinerU** for high-fidelity PDF parsing, converting complex layouts into structured Markdown.
2.  **Domain Knowledge Retrieval:**
    *   Context-aware retrieval of relevant ontologies and schema definitions (MIxS standards) to ground the generation process.
3.  **Structured Generation:**
    *   LLM-driven extraction of metadata fields based on the specific schema requirements.
4.  **Reflective Critic Loop (Self-Correction):**
    *   An internal "Critic" agent evaluates the generated output against a strict rubric.
    *   **Criteria:** Schema compliance, data type validity, and confidence thresholds.
    *   **Action:** If confidence is below threshold (e.g., < 0.75), the agent triggers a retry with specific feedback for improvement.

## 2. Experimental Setup (Materials)

### 2.1 Model Configurations
We evaluated the agent's performance across three major LLM families to assess reasoning capabilities, instruction following, and cost-efficiency:

*   **OpenAI Family:**
    *   `GPT-5` (Preview/Alpha)
    *   `GPT-4.1`
    *   `GPT-4o`
    *   `o3` (Reasoning-optimized)
*   **Anthropic Family:**
    *   `Claude 3.5 Sonnet` (High capability)
    *   `Claude 3.5 Haiku` (Efficiency focused)
*   **Qwen Family (Alibaba):**
    *   `Qwen-Max`
    *   `Qwen-Plus`
    *   `Qwen-Flash`

| Model Family | Model ID (Internal/API) | Context Window | Temperature | Optimization Target |
| :--- | :--- | :--- | :--- | :--- |
| **OpenAI** | `gpt-5.1` | 400k | 0.2 | Next-gen SOTA Capabilities |
| **OpenAI** | `gpt-4.1` | 256k | 0.2 | High-performance Generalist |
| **OpenAI** | `o3` | 256k | 1.0 | Complex Reasoning (Chain of Thought) |
| **OpenAI** | `gpt-4o` | 128k | 0.2 | Multimodal Efficiency |
| **Anthropic** | `claude-sonnet-4-5-20250929` | 200k | 0.2 | High-fidelity Instruction Following |
| **Anthropic** | `claude-haiku-4-5-20251001` | 200k | 0.2 | Cost-Effective Speed |
| **Qwen** | `qwen-max` | 128k | 0.5 | Complex Reasoning (Chinese/English) |
| **Qwen** | `qwen-plus` | 128k | 0.5 | Balanced Performance |
| **Qwen** | `qwen-flash` | 100k | 0.5 | High Speed / Low Latency |

### 2.2 Datasets
The evaluation utilizes a curated set of complex scientific manuscripts representing real-world heterogeneity:

*   **Earthworm Dataset:** A genomics/metagenomics study requiring extraction of sequencing metadata, environmental conditions, and sample attributes.
*   **Haarika+Bhamidipati:** A control dataset for verifying generalizability across different layout styles.
*   **BIOREM (Holdout):** Used for verifying extraction in bioremediation contexts (excluded from primary training/tuning rounds).

*Each document is accompanied by a rigorous **Ground Truth (v2)** JSON annotation manually verified by domain experts.*

## 3. Evaluation Methodology

To ensure robust and statistically significant results, we implemented a comprehensive evaluation pipeline.

### 3.1 Execution Strategy
*   **Stochasticity Control:** Each document-model pair is executed **10 times (N=10)** to quantify the stability and variance of the agent's performance.
*   **Parallelization:** Execution is distributed across 5 concurrent workers to simulate production load and reduce evaluation time.

### 3.2 Metrics Framework
We employ a multi-dimensional metric system:

#### A. External Performance Metrics (vs. Ground Truth)
1.  **Completeness Score (Field Coverage):**
    *   **Definition:** Measures the extent to which the agent extracts expected metadata fields.
    *   **Calculation:**
        \[
        \text{Completeness} = \frac{|E \cap G|}{|G|}
        \]
        Where \(E\) is the set of extracted field names and \(G\) is the set of Ground Truth field names.
    *   **Granularity:** Calculated at three levels:
        *   *Overall:* All fields.
        *   *Required:* Only fields marked as mandatory in the schema.
        *   *Recommended:* Fields marked as recommended (value-add).
    *   **Source Code:** `evaluation/evaluators/completeness_evaluator.py`

2.  **Correctness (Field Presence & Precision):**
    *   **Definition:** Evaluates the agent's ability to identify the *correct* fields without hallucinating non-existent ones.
    *   **Metrics:**
        *   **Precision:** \(\frac{TP}{TP + FP}\) (Signal-to-Noise ratio)
        *   **Recall:** \(\frac{TP}{TP + FN}\) (Sensitivity)
        *   **F1-Score:** Harmonic mean of Precision and Recall.
    *   *Note:* Currently focuses on field presence. Value-level semantic correctness is assessed via LLM-Judge in a separate pipeline component.

3.  **Schema Validity:**
    *   **Definition:** Strict boolean validation against the official JSON Schema (MIxS/ISA).
    *   **Checks:** Data types (string, number), Enum constraints, and Date formats (ISO 8601).

#### B. Internal Agent Metrics (Efficiency & Robustness)
1.  **Confidence Score:** 
    *   **Self-Reported:** The agent assigns a confidence score \(C \in [0, 1]\) to each extracted field.
    *   **Aggregated:** We report the mean confidence per document run.
    
2.  **Critic Interaction (Reflective Quality):**
    *   **Retry Rate:** Percentage of workflow steps that triggered a "Critique & Retry" loop.
    *   **Confirmation Rate:** Percentage of fields marked as "Confirmed" vs. "Provisional" by the internal Critic.

3.  **Processing Time & Latency:** End-to-end execution time.
4.  **Cost:** Token consumption per document.

## 4. Technical Infrastructure
*   **Orchestration:** Custom Python-based batch runner (`run_batch_evaluation.py`) with `asyncio` for parallel execution management.
*   **Configuration Management:** Environment-based config isolation (`.env` files) for reproducible model parameter settings.
*   **Logging & Tracing:** Full integration with **LangSmith** for trace-level debugging and **local logging** for aggregate analysis.

