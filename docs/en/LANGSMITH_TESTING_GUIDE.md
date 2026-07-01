# LangSmith Testing & Tracing Guide for FAIRiAgent

## 🎯 Overview

LangSmith is LangChain's official debugging and monitoring platform. Since FAIRiAgent is built using LangGraph, it integrates natively with LangSmith. When enabled, every agent decision, tool call, self-correction loop, and LLM input/output is automatically traced and visualized on your LangSmith dashboard.

This is highly recommended during development to trace reasoning trajectories and troubleshoot Critic scoring decisions.

---

## 🚀 Quick Setup

To trace your FAIRiAgent runs to LangSmith, follow these steps:

### 1. Create a LangSmith Account & Get an API Key

1. Go to [LangSmith](https://smith.langchain.com/) and sign up.
2. Navigate to **Settings** → **API Keys** (or click on your profile icon).
3. Create a new API key and copy it.

### 2. Configure Environment Variables

Create or open your `.env` file in the project root and add the following lines (replacing `"your_api_key_here"` with your actual key):

```bash
# Enable LangChain tracing
export LANGCHAIN_TRACING_V2="true"

# Paste your API key
export LANGCHAIN_API_KEY="your_api_key_here"

# Set a project name for trace grouping (default is "fairifier")
export LANGCHAIN_PROJECT="fairifier-testing"

# (Optional) Endpoint URL, defaults to LangSmith SaaS
export LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
```

### 3. Run the Program

No extra Python wrapper script is required. When tracing environment variables are exported, any standard FAIRiAgent execution will automatically push tracing logs to LangSmith:

```bash
# Run metadata extraction CLI
python run_fairifier.py process examples/inputs/sample_study.txt

# Or run API / Web UI mode
python run_fairifier.py webui

# Or run the regression tests
pytest tests/
```

---

## 📊 What You Can Monitor in LangSmith

Once a run completes, log into your [LangSmith Dashboard](https://smith.langchain.com/) and open the project (`fairifier-testing`). You will see:

### 1. Trace Trees (Run Trajectories)
A hierarchical visualization of the LangGraph multi-agent execution steps:
*   `FAIRifierLangGraphApp` (the root graph)
    *   `read_file` (Node)
    *   `parse_document` (Node) → `Critic` (LLM-as-Judge Evaluator)
    *   `plan_workflow` (Node)
    *   `retrieve_knowledge` (Node) → `Critic`
    *   `generate_json` (Node) → `Critic` (Hard-gate schema validation)
    *   `finalize` (Node)

### 2. Inner-Loop Logs (ReAct Tools)
Expand any agent node (like `KnowledgeRetriever`) to inspect:
*   Tool calls made by the agent (e.g. querying the FAIR-DS API).
*   Raw LLM thinking blocks, system prompts, and responses.

### 3. State Ingestion & Token Consumption
*   **Context Tokens**: Monitor token window sizes (to diagnose binary splitting of large sheets).
*   **Latency**: Analyze execution speed for individual agents to find bottlenecks.
*   **Costs**: Estmated token-based run costs.

---

## 🔧 Debugging Scenarios

### Inspecting LLM-as-Judge Critic Rubrics
If an agent execution gets stuck in a retry loop or fails to meet the quality score:
1. Search the LangSmith runs for `Critic` calls.
2. Compare the output score against the thresholds defined in `.env` (e.g. `FAIRIFIER_CRITIC_ACCEPT_THRESHOLD_JSON_GENERATOR`).
3. View the raw feedback text passed back to the optimizer node to understand why a document failed.

### Local Studio Visualizer (Alternative)
For local debugging without cloud logging, you can use LangGraph Studio:
```bash
# Install LangGraph CLI
pip install langgraph-cli

# Start dev server
langgraph dev
# Open the local web studio at http://localhost:8123
```

---

## 📚 SDK-based Trace Querying (Advanced)

If you want to query or evaluate run data programmatically, use the official `langsmith` client SDK:

```python
from langsmith import Client

client = Client()

# List recent runs in your project
runs = client.list_runs(
    project_name="fairifier-testing",
    run_type="chain",
    limit=10
)

for run in runs:
    print(f"Run ID: {run.id} | Name: {run.name} | Status: {run.status}")
    if run.error:
        print(f"Error: {run.error}")
```

For custom evaluation benchmarks and dataset uploading instructions, please consult the official [LangSmith Documentation](https://docs.smith.langchain.com/).
