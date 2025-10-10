# Optional Web Components

⚠️ **Note**: The API and UI components in this directory are **optional** and not part of the core FAIRifier functionality.

## Core FAIRifier

The core FAIRifier is a **CLI-only tool** that:
- Processes documents via command line
- Outputs JSON metadata in FAIR-DS format
- Uses JSON line logging
- Supports LangSmith tracing

## Optional Components

### API Server (`api/`)
- **Status**: Optional, not maintained
- **Purpose**: REST API for web integration
- **Usage**: Not recommended for production use
- **Note**: May be removed in future versions

### Web UI (`ui/`)
- **Status**: Optional, not maintained  
- **Purpose**: Streamlit-based web interface
- **Usage**: For demonstration only
- **Note**: May be removed in future versions

## Recommended Usage

Use the CLI tool instead:

```bash
# Process a document
python -m fairifier.cli process your_document.pdf

# With custom output directory
python -m fairifier.cli process document.pdf --output-dir results/

# Check configuration
python -m fairifier.cli config-info
```

## Why CLI Only?

Following the minimal requirements:
1. **Simplicity**: No server management needed
2. **Portability**: Works anywhere Python runs
3. **Automation**: Easy to integrate in scripts and pipelines
4. **Debugging**: Direct access to JSON logs and LangSmith traces
5. **Security**: No authentication/authorization complexity

If you need web access, consider building a thin wrapper around the CLI tool rather than using these optional components.

