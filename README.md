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
- 🎛️ **Multi-Model Support**: Ollama (local) / OpenAI / Anthropic
- 🔍 **LangSmith Integration**: Complete tracing and debugging support

## 🏗️ Architecture

The system uses a simplified multi-agent workflow:

```
Document → Parse → Retrieve Knowledge → Generate JSON → Validate → Output
```

**Agents:**
1. **Document Parser**: Extracts structured information from documents
2. **Knowledge Retriever**: Enriches metadata with FAIR-DS and local knowledge
3. **JSON Generator**: Creates FAIR-DS compatible metadata
4. **Validator**: Quality checks and confidence assessment

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

```bash
# Process a document
python -m fairifier.cli process your_document.pdf

# Specify output directory
python -m fairifier.cli process document.txt --output-dir results/

# Check configuration
python -m fairifier.cli config-info
```

### Configuration

```bash
# LLM Provider (Ollama/OpenAI/Anthropic)
export LLM_PROVIDER=ollama  # or "openai" or "anthropic"
export LLM_MODEL=qwen2.5:7b
export LLM_API_KEY=your_key  # for OpenAI/Anthropic

# FAIR Data Station (optional)
export FAIR_DS_API_URL=http://localhost:8083

# LangSmith (optional)
export LANGSMITH_API_KEY=your_key
export LANGSMITH_PROJECT=fairifier-testing
```

### Output Files

FAIRiAgent generates:
1. **`metadata_json.json`** - FAIR-DS compatible metadata
2. **`processing_log.jsonl`** - JSON line logs
3. **`validation_report.txt`** - Validation results (optional)

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
├── agents/           # Multi-agent implementations
│   ├── document_parser.py
│   ├── knowledge_retriever.py
│   ├── json_generator.py
│   └── validator.py
├── graph/           # LangGraph workflow
├── services/        # FAIR-DS and local knowledge
├── utils/           # JSON logger
├── cli.py           # Command-line interface
├── config.py        # Configuration
└── models.py        # Data models

kb/                  # Knowledge base
├── local_terms.json      # Local provisional terms
├── local_packages.json   # Local packages
└── ontologies.json       # Ontology mappings

examples/            # Sample documents
docs/                # Documentation
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
python -m fairifier.cli process <document> [options]

# Check status
python -m fairifier.cli status <project-id>

# Show configuration
python -m fairifier.cli config-info

# Validate document
python -m fairifier.cli validate-document <document>
```

## ⚠️ Note on API/UI

The `fairifier/apps/` directory contains optional API and UI components that are **not recommended for production use**. FAIRiAgent is designed as a **CLI-first tool**. See `fairifier/apps/README.md` for details.

## 🧪 Testing

Test with the provided sample documents:

```bash
# Test basic functionality
python -m fairifier.cli examples/inputs/soil_metagenomics_paper.txt

# Test with all features
python -m fairifier.cli examples/inputs/soil_metagenomics_paper.txt --fair-ds-url http://localhost:8083
```

### LangSmith Integration

FAIRiAgent includes comprehensive LangSmith integration for debugging and monitoring:

```bash
# Set up LangSmith (get API key from https://smith.langchain.com/)
export LANGSMITH_API_KEY="your_api_key_here"
export LANGSMITH_PROJECT="fairifier-testing"

# Run LangSmith tests
python test_langsmith.py
```

LangSmith provides:
- 🔍 **Trace Visualization**: Complete workflow execution flow
- 📊 **Performance Metrics**: Token usage, costs, and timing
- 🐛 **Debug Tools**: Step-by-step debugging and error analysis
- 📈 **Monitoring**: Track performance over time

See [LangSmith Testing Guide](docs/LANGSMITH_TESTING_GUIDE.md) for detailed instructions.

## 📚 Documentation

- [Requirements Analysis](REQUIREMENTS_ANALYSIS.md) - Detailed requirements compliance analysis
- [Implementation Summary](IMPLEMENTATION_SUMMARY.md) - Technical implementation details
- [LangSmith Testing Guide](docs/LANGSMITH_TESTING_GUIDE.md) - Testing and debugging guide
- [Design Document](DESIGN.md) - System design and architecture

## 🤝 Contributing

This is a research tool designed for:
- Scientific metadata standardization
- FAIR data principles implementation
- Multi-agent system research
- Agentic RAG development

## 📄 License

MIT License - Free for academic and research use.

---

**🎯 FAIRiAgent v0.2 - Simple, Standards-compliant, Evidence-based Metadata Generation**