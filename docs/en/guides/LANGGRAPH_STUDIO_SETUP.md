# LangGraph Studio Setup Guide

This guide explains how to start a local LangGraph server using `langgraph dev` and connect it to LangSmith for visualization and debugging.

## 📋 Prerequisites

1. Install LangGraph CLI (including inmem extension):
```bash
pip install -U "langgraph-cli[inmem]"
```

2. Ensure project dependencies are installed:
```bash
pip install -r requirements.txt
```

## 🔧 Configuration Steps

### 1. Set LangSmith API Key

Add your LangSmith API Key to the `.env` file in the project root directory:

```bash
# .env file
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=fairifier-studio
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=fairifier-studio
```

### 2. Start LangGraph Development Server

Run the following command in the project root directory:

```bash
langgraph dev
```

If started successfully, you will see output similar to:

```
Ready!

* API: http://localhost:2024
* Docs: http://localhost:2024/docs
* LangGraph Studio Web UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

### 3. Access LangGraph Studio

Open your browser and visit the LangGraph Studio Web UI link provided in the logs:

```
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

## 🎯 Features

In LangGraph Studio, you can:

1. **Visualize Workflow**: View the complete FAIRifier workflow graph.
2. **Debug Execution**: Step through execution and view the state of each node.
3. **View State**: View workflow state changes in real-time.
4. **Test Inputs**: Test different inputs directly within the workflow.
5. **View LangSmith Traces**: All executions are automatically recorded to LangSmith.

## 🔍 Workflow Nodes

The FAIRifier workflow contains the following nodes:

- `read_file`: Reads document content.
- `plan_workflow`: LLM plans workflow strategy.
- `parse_document`: Parses document and extracts information.
- `evaluate_parsing`: Critic evaluates parsing results.
- `retrieve_knowledge`: Retrieves knowledge from FAIR-DS API.
- `evaluate_retrieval`: Critic evaluates retrieval results.
- `generate_json`: Generates FAIR-DS compatible JSON metadata.
- `evaluate_generation`: Critic evaluates generation results.
- `finalize`: Completes workflow and generates summary.

## 🐛 Troubleshooting

### Safari Browser Connection Issues

If you encounter connection issues using Safari, use the `--tunnel` parameter:

```bash
langgraph dev --tunnel
```

### Debug Mode

If you need step-by-step debugging, use the `--debug-port` parameter:

```bash
langgraph dev --debug-port 5678
```

### Check Configuration

Ensure the `langgraph.json` file is in the project root with the following content:

```json
{
  "graphs": {
    "fairifier": "./fairifier/graph/__dev__.py:graph"
  },
  "env": ".env",
  "dependencies": [
    "."
  ]
}
```

**Note**: The `dependencies` field is required and must contain at least one dependency. Use `"."` to represent the current project directory.

## 📝 Notes

1. **LangSmith Tracing**: All executions are automatically logged to LangSmith, ensure `LANGSMITH_API_KEY` is set.
2. **State Management**: The workflow uses an in-memory checkpointer (MemorySaver), state is lost when the server restarts.
3. **File Paths**: When testing in Studio, ensure `document_path` points to a valid file path.

## 🚀 Quick Start

```bash
# 1. Set environment variables
export LANGSMITH_API_KEY=your_key_here

# 2. Start development server
langgraph dev

# 3. Access Studio UI (open the link displayed in logs in your browser)
```

Now you can visualize and debug the FAIRifier workflow in LangGraph Studio!

