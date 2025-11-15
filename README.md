# FAIRiAgent - FAIR Metadata Generation Framework

🧬 **CLI-first, JSON-only FAIR metadata generation with FAIR-DS compatibility**

## 🎯 Overview

FAIRiAgent is a CLI-first multi-agent framework that automatically extracts information from research documents (PDF/text) and generates **FAIR-DS compatible JSON metadata**. Built with LangGraph and LangChain, it focuses on simplicity, standards compliance, and evidence-based metadata generation.

## ✨ Key Features

- 🤖 **Multi-Agent Architecture**: Specialized agents for document parsing, knowledge retrieval, and JSON generation
- 📄 **Document Processing**: Extract metadata from PDF and text documents
- 🧠 **Knowledge Retrieval**: Integrate with FAIR Data Station and local knowledge base
- 🏷️ **Evidence-based Fields**: Every field includes evidence, confidence, origin, and package source
- 📊 **JSON-only Output**: FAIR-DS compatible metadata format (no RDF/RO-Crate)
- 📝 **JSON Line Logging**: Structured logging for debugging and monitoring
- 🔧 **Local Provisional Support**: Extend with local terms (source=local, status=provisional)
- 🎛️ **Multi-Model Support**: Ollama (local) / OpenAI / Qwen / Anthropic
- 🔍 **LangSmith Integration**: Complete tracing and debugging support (默认启用)
- 🎨 **Streamlit Web UI**: Interactive web interface with real-time streaming output
- 💬 **Chat-like Streaming**: Real-time LLM response streaming with chat bubble interface
- ⚙️ **Configuration Management**: Save and manage runtime configurations
- 📋 **Runtime Config Export**: Automatic export of input, .env, and runtime configurations

## 🏗️ Architecture

The system uses a LangGraph-based multi-agent workflow:

```
Document → Parse → Plan → Retrieve Knowledge → Generate JSON → Evaluate → Output
```

**Agents:**
1. **Document Parser**: Extracts structured information from documents
2. **Orchestrator**: Plans workflow strategy based on document content
3. **Knowledge Retriever**: Enriches metadata with FAIR-DS and local knowledge
4. **JSON Generator**: Creates FAIR-DS compatible metadata
5. **Critic**: Evaluates quality and provides feedback for retry/escalation

**Workflow Features:**
- 🔄 **Retry Logic**: Automatic retry with feedback from Critic agent
- 🎯 **Conditional Routing**: Dynamic workflow based on evaluation results
- 📊 **Execution Summary**: Track steps, retries, and outcomes
- 💾 **State Persistence**: LangGraph checkpointer for state management

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd FAIRiAgent

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

**CLI Mode:**
```bash
# Process a document
python run_fairifier.py process your_document.pdf

# Specify output directory
python run_fairifier.py process document.txt --output-dir results/

# Check configuration
python run_fairifier.py config-info
```

**Web UI Mode:**
```bash
# Start Streamlit web interface
python run_fairifier.py ui

# Access at http://localhost:8501
```

**LangGraph Studio (Development):**
```bash
# Start LangGraph dev server
langgraph dev

# Access LangGraph Studio at http://localhost:8123
```

### Configuration

**Environment Variables (.env file):**
```bash
# LLM Provider (Ollama/OpenAI/Qwen/Anthropic)
LLM_PROVIDER=ollama  # or "openai", "qwen", or "anthropic"
FAIRIFIER_LLM_MODEL=llama3  # Model name
FAIRIFIER_LLM_BASE_URL=http://localhost:11434  # For Ollama
LLM_API_KEY=your_key  # For OpenAI/Qwen/Anthropic
LLM_TEMPERATURE=0.5
LLM_MAX_TOKENS=100000
LLM_ENABLE_THINKING=false  # For Qwen models

# FAIR Data Station (optional)
FAIR_DS_API_URL=http://localhost:8083

# LangSmith (optional)
LANGSMITH_API_KEY=your_key
LANGSMITH_PROJECT=fairifier-testing
```

**Web UI Configuration:**
- Access the "⚙️ Configuration" tab in the Streamlit UI
- Configure LLM, LangSmith, and FAIR-DS settings
- Save to session or export to .env file
- Changes apply to next processing run

### Output Files

FAIRiAgent generates (in `output/<project_id>/`):
1. **`metadata_json.json`** - FAIR-DS compatible metadata
2. **`processing_log.jsonl`** - JSON line logs
3. **`llm_responses.json`** - All LLM API interactions
4. **`runtime_config.json`** - Complete runtime configuration including:
   - Input document path
   - Environment variables (.env)
   - LLM configuration
   - Runtime settings
   - Project metadata
5. **`validation_report.txt`** - Validation results (optional)

## 📊 Output Format

### FAIR-DS Compatible JSON

```json
{
  "fairifier_version": "0.2.0",
  "generated_at": "2025-01-27T10:30:00",
  "document_source": "paper.pdf",
  "overall_confidence": 0.85,
  
  "metadata": [
    {
      "field_name": "project_name",
      "value": "Soil Metagenomics Study",
      "evidence": "Extracted from document title",
      "confidence": 0.95,
      "origin": "document_parser",
      "package_source": "MIMAG",
      "status": "confirmed"
    },
    {
      "field_name": "investigation_type",
      "value": "metagenome",
      "evidence": "Inferred from research domain",
      "confidence": 0.80,
      "origin": "document_parser",
      "package_source": "MIMAG",
      "status": "provisional"
    }
  ],
  
  "statistics": {
    "total_fields": 15,
    "confirmed_fields": 8,
    "provisional_fields": 7
  }
}
```

### JSON Line Logging

```json
{"timestamp": "2025-01-27T10:30:00", "level": "info", "event": "processing_started", "document_path": "paper.pdf"}
{"timestamp": "2025-01-27T10:30:05", "level": "info", "event": "field_extracted", "field_name": "project_name", "confidence": 0.95}
{"timestamp": "2025-01-27T10:30:10", "level": "info", "event": "processing_completed", "status": "completed"}
```

## 🧬 FAIR Data Station Integration

When connected to a FAIR Data Station instance, FAIRiAgent can:

- 🔍 Search for standardized terms relevant to your research
- 📦 Use community-approved metadata packages
- 🏷️ Enhance fields with validated definitions
- 🌐 Ensure better interoperability

### Setup FAIR Data Station

```bash
# Download and start FAIR Data Station
wget http://download.systemsbiology.nl/unlock/fairds-latest.jar
java -jar fairds-latest.jar

# Access at http://localhost:8083
```

## 🔧 Local Provisional Extensions

Add custom terms not in FAIR-DS:

```python
from fairifier.services.local_knowledge import initialize_local_kb, LocalTerm
from pathlib import Path

# Initialize local knowledge base
local_kb = initialize_local_kb(Path("kb"))

# Add custom term
local_kb.add_term(LocalTerm(
    name="custom_field",
    label="Custom Field",
    description="Project-specific metadata field",
    source="local",
    status="provisional",
    confidence=0.7
))
```

Local terms are automatically included with `source=local` and `status=provisional`.

## 📁 Project Structure

```
fairifier/
├── agents/              # Multi-agent implementations
│   ├── document_parser.py
│   ├── knowledge_retriever.py
│   ├── json_generator.py
│   ├── critic.py
│   └── orchestrator.py
├── graph/               # LangGraph workflow
│   ├── langgraph_app.py # Main LangGraph application
│   └── __dev__.py       # LangGraph Studio entry point
├── apps/                # Web UI and API
│   ├── ui/
│   │   └── streamlit_app.py  # Streamlit web interface
│   └── api/             # FastAPI (optional)
├── services/            # FAIR-DS and local knowledge
├── utils/               # Utilities
│   ├── llm_helper.py    # LLM interaction utilities
│   ├── config_saver.py # Runtime config export
│   └── json_logger.py  # JSON logging
├── cli.py               # Command-line interface
├── config.py            # Configuration management
└── models.py            # Data models

kb/                      # Knowledge base
├── local_terms.json     # Local provisional terms
├── local_packages.json  # Local packages
└── ontologies.json      # Ontology mappings

output/                  # Generated outputs
└── <project_id>/
    ├── metadata_json.json
    ├── processing_log.jsonl
    ├── llm_responses.json
    └── runtime_config.json

examples/                # Sample documents
docs/                    # Documentation
langgraph.json           # LangGraph Studio config
```

## 📈 Quality Metrics

FAIRiAgent provides confidence scoring based on:

- ✅ **Document extraction quality** (title, abstract, authors)
- ✅ **Field completion rate** (how many fields have values)
- ✅ **Research domain identification** accuracy
- ✅ **Evidence quality** (how well fields are supported)

Confidence levels:
- **> 0.8**: High confidence, ready to use
- **0.5-0.8**: Good, may need minor review
- **< 0.5**: Requires manual review

## 🛠️ Dependencies

Core dependencies:
- `langgraph`: Multi-agent workflow orchestration
- `langchain`: Agent framework and tools
- `langsmith`: Tracing and debugging
- `rdflib`: RDF processing (minimal use)
- `PyMuPDF`: PDF document processing
- `click`: CLI framework

## 📋 CLI Commands

```bash
# Process document
python run_fairifier.py process <document> [options]

# Start web UI
python run_fairifier.py ui

# Check status
python run_fairifier.py status <project-id>

# Show configuration
python run_fairifier.py config-info

# Validate document
python run_fairifier.py validate-document <document>
```

**Options:**
- `--output-dir, -o`: Specify output directory
- `--project-id, -p`: Custom project ID
- `--env-file, -e`: Use custom .env file
- `--json-log`: Enable JSON line logging (default: True)
- `--verbose, -v`: Show detailed processing steps

## 🎨 Web UI Features

The Streamlit web interface provides:

- 📄 **Document Upload**: Drag-and-drop or use example files
- 💬 **Real-time Streaming**: Chat-like interface showing LLM responses as they're generated
- 📊 **Live Logs**: Real-time processing logs and error display
- ⚙️ **Configuration Management**: Configure LLM, LangSmith, and FAIR-DS settings
- 🔍 **Result Review**: View and download generated metadata
- 📋 **LLM API Logs**: View all LLM interactions in formatted display

**Access the UI:**
```bash
python run_fairifier.py ui
```

Then open http://localhost:8501 in your browser.

## 🧪 Testing

Test with the provided sample documents:

```bash
# Test basic functionality (CLI)
python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRXiv.pdf

# Test with all features
python run_fairifier.py process examples/inputs/earthworm_4n_paper_bioRXiv.pdf --fair-ds-url http://localhost:8083

# Test web UI
python run_fairifier.py ui
# Then use the example file option in the UI
```

**Example Files:**
- `examples/inputs/earthworm_4n_paper_bioRXiv.pdf` - Research paper example

### LangSmith Integration

FAIRiAgent includes comprehensive LangSmith integration for debugging and monitoring:

```bash
# Set up LangSmith (get API key from https://smith.langchain.com/)
export LANGSMITH_API_KEY="your_api_key_here"
export LANGSMITH_PROJECT="fairifier-testing"

# Or configure in Streamlit UI under "⚙️ Configuration" tab
```

LangSmith provides:
- 🔍 **Trace Visualization**: Complete workflow execution flow
- 📊 **Performance Metrics**: Token usage, costs, and timing
- 🐛 **Debug Tools**: Step-by-step debugging and error analysis
- 📈 **Monitoring**: Track performance over time
- 🔗 **Trace Links**: Direct links to traces from Streamlit UI

**LangGraph Studio Integration:**
```bash
# Start LangGraph dev server
langgraph dev

# Access LangGraph Studio at http://localhost:8123
# Visualize and debug the workflow graph
```

See [LangGraph Studio Setup](docs/guides/LANGGRAPH_STUDIO_SETUP.md) and [LangSmith Testing Guide](docs/LANGSMITH_TESTING_GUIDE.md) for detailed instructions.

## 📚 Documentation

- **Core**
  - [Project Summary](docs/PROJECT_SUMMARY.md) – End-to-end overview
  - [Design Document](docs/DESIGN.md) – System design and architecture
  - [LLM Integration Guide](docs/LLM_INTEGRATION_GUIDE.md) – Provider configuration
  - [LangSmith Testing Guide](docs/LANGSMITH_TESTING_GUIDE.md) – Testing and debugging
- **Guides**
  - [LangGraph Studio Setup](docs/guides/LANGGRAPH_STUDIO_SETUP.md) – Local LangGraph + Studio
  - [Quick Start (中文)](docs/guides/QUICKSTART_CN.md) – 最简运行步骤
  - [Test Guide](docs/guides/TEST_GUIDE.md) – 环境验证与测试流程
- **Development Notes**
  - [System Ready Checklist](docs/development/SYSTEM_READY.md) – 全面特性验证
  - [Workflow Summary](docs/development/WORKFLOW_SUMMARY.md) – 当前工作流说明
  - [FAIR-DS API Exploration](docs/development/FAIRDS_API_EXPLORATION.md) – API 结构调研
  - [Implementation Notes](docs/development/README_IMPLEMENTATION.md) – 历史实现记录
- **Web UI**
  - [Web UI Guide](fairifier/apps/README.md) – Streamlit UI features and usage

## 🤝 Contributing

This is a research tool designed for:
- Scientific metadata standardization
- FAIR data principles implementation
- Multi-agent system research
- Agentic RAG development

## 📄 License

MIT License - Free for academic and research use.

---

**🎯 FAIRiAgent v0.3 - LangGraph-powered, Web UI-enabled, Standards-compliant Metadata Generation**

---

## 🔄 Recent Updates (v0.3)

- ✅ **LangGraph Integration**: Full LangGraph workflow with state persistence
- ✅ **Streamlit Web UI**: Interactive web interface with real-time streaming
- ✅ **Chat-like Streaming**: Real-time LLM response display with chat bubbles
- ✅ **Configuration Management**: Web-based configuration with .env export
- ✅ **Runtime Config Export**: Automatic export of all runtime configurations
- ✅ **Multi-Provider Support**: Enhanced support for Ollama, OpenAI, Qwen, Anthropic
- ✅ **LangGraph Studio**: Visual workflow debugging and development
- ✅ **Improved Retry Logic**: Critic-based evaluation with automatic retry/escalation