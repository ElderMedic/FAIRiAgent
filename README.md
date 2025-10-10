# FAIRiAgent - FAIR Metadata Generation Framework

🧬 **Automated generation of FAIR metadata from research documents using multi-agent systems**

## 🎯 Overview

FAIRiAgent is a sophisticated multi-agent framework that automatically extracts information from research documents (PDF/text) and generates standardized FAIR metadata templates. Built with LangGraph and LangChain, it provides intelligent document processing, knowledge retrieval, and metadata generation with human-in-the-loop validation.

## ✨ Key Features

- 🤖 **Multi-Agent Architecture**: Specialized agents for document parsing, knowledge retrieval, template generation, RDF building, and validation
- 📄 **Document Processing**: Extract metadata from PDF and text documents using GROBID and OCR
- 🧠 **Knowledge Retrieval**: Integrate with FAIR Data Station and external knowledge sources
- 🏷️ **Smart Field Generation**: Generate relevant metadata fields based on research domain (MIxS standards)
- 📊 **Multiple Output Formats**: JSON Schema, YAML templates, RDF (Turtle/JSON-LD), and RO-Crate
- 🎯 **Confidence Scoring**: Quality assessment with automatic human-in-the-loop triggers
- 🔄 **Graceful Fallbacks**: Works with optional dependencies and external services

## 🏗️ Architecture

The system uses a multi-agent workflow orchestrated by LangGraph:

1. **Document Parser Agent**: Extracts structured information from documents
2. **Knowledge Retriever Agent**: Enriches metadata with external knowledge
3. **Template Generator Agent**: Creates metadata templates based on standards
4. **RDF Builder Agent**: Generates semantic representations
5. **Validator Agent**: Validates output quality and triggers human review

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd FAIRiAgent

# Install dependencies
pip install -r requirements.txt

# Or use Poetry (recommended)
poetry install
```

### Usage

#### Command Line Interface
```bash
# Process a document
python -m fairifier.cli your_document.pdf

# Specify output directory
python -m fairifier.cli document.txt --output results/

# With FAIR Data Station integration
python -m fairifier.cli paper.pdf --fair-ds-url http://localhost:8083
```

#### API Server
```bash
# Start the FastAPI server
python run_fairifier.py api

# Access API documentation at http://localhost:8000/docs
```

#### Web Interface
```bash
# Start the Streamlit UI
python run_fairifier.py ui

# Access web interface at http://localhost:8501
```

#### Docker Deployment
```bash
# Start all services
docker-compose -f docker/compose.yaml up
```

## 📊 Example Results

### Input Document
```
Title: Metagenomic Analysis of Soil Microbial Communities in Agricultural Fields
Authors: Dr. Maria Zhang, Prof. James Wilson
Keywords: soil microbiome, metagenomics, agricultural soils
```

### Generated Metadata (YAML)
```yaml
# FAIR Metadata Template
# Generated: 2025-01-27 10:30:00
# Project: Metagenomic Analysis of Soil Microbial Communities
# Domain: soil

# REQUIRED FIELDS
project_name: Metagenomic Analysis of Soil Microbial Communities in Agricultural Fields
investigation_type: metagenome
collection_date: July 15-20, 2023
geo_loc_name: USA:Iowa

# OPTIONAL FIELDS
lat_lon: 42.0308 -93.6319
env_biome: terrestrial biome
env_material: soil
seq_meth: # Sequencing method used
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

## 📁 Project Structure

```
fairifier/
├── agents/           # Multi-agent implementations
├── apps/            # API and UI applications
├── graph/           # LangGraph workflow definitions
├── services/        # External service integrations
├── config.py        # Configuration management
├── models.py        # Data models
└── cli.py          # Command-line interface

kb/                  # Knowledge base
├── schemas/         # JSON Schema definitions
├── shapes/          # SHACL validation shapes
└── ontologies.json  # Ontology mappings

examples/            # Sample documents and outputs
docker/              # Containerization files
docs/                # Documentation
```

## 📈 Quality Metrics

FAIRiAgent provides confidence scoring based on:

- ✅ **Document extraction quality** (title, abstract, authors)
- ✅ **Field completion rate** (how many fields have values)
- ✅ **Research domain identification** accuracy
- ✅ **Metadata standardization** level
- ✅ **SHACL validation** compliance

Confidence levels:
- **> 0.8**: High confidence, ready to use
- **0.5-0.8**: Good, may need minor review
- **< 0.5**: Requires manual review

## 🛠️ Dependencies

Core dependencies (required):
- `langgraph`: Multi-agent workflow orchestration
- `langchain`: Agent framework and tools
- `rdflib`: RDF processing and generation
- `fastapi`: API framework
- `streamlit`: Web interface

Optional dependencies:
- `PyMuPDF`: PDF document processing
- `grobid-client`: Advanced PDF parsing
- `qdrant-client`: Vector database
- `requests`: External API integration

## 📋 API Endpoints

- `POST /projects/run`: Upload document and start processing
- `GET /projects/{id}/status`: Check processing status
- `POST /projects/{id}/hitl-edits`: Submit human-in-the-loop edits
- `GET /projects/{id}/artifacts`: Download generated artifacts

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

## 🤝 Contributing

This is a research tool designed for:
- Scientific metadata standardization
- FAIR data principles implementation
- Research workflow automation
- Multi-agent system development

## 📄 License

MIT License - Free for academic and research use.

---

**🎯 FAIRiAgent makes your research data more Findable, Accessible, Interoperable, and Reusable!**