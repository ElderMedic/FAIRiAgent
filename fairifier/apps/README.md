# FAIRiAgent Apps

This directory contains the Streamlit web UI and optional API components for FAIRiAgent.

## 🎨 Streamlit Web UI

The Streamlit web interface provides an interactive way to use FAIRiAgent without command-line access.

### Features

- 📄 **Document Upload**: Upload PDF, text, or markdown files
- 💬 **Real-time Streaming**: Chat-like interface showing LLM responses as they're generated
- 📊 **Live Logs**: Real-time processing logs and error display
- ⚙️ **Configuration Management**: Configure LLM, LangSmith, and FAIR-DS settings
- 🔍 **Result Review**: View and download generated metadata
- 📋 **LLM API Logs**: View all LLM interactions in formatted display
- 💾 **Runtime Config Export**: Automatic export of runtime configurations

### Usage

```bash
# Start the web UI
python run_fairifier.py ui

# Access at http://localhost:8501
```

### Configuration

The web UI includes a configuration page where you can:
- Set LLM provider (Ollama, OpenAI, Qwen, Anthropic)
- Configure LLM parameters (model, temperature, max tokens, etc.)
- Set up LangSmith tracing
- Configure FAIR-DS API
- Export configuration to .env file

### Streaming Output

The UI features a chat-like streaming interface that displays:
- Agent name and operation
- Real-time LLM response streaming
- Timestamp for each message
- Formatted chat bubbles

Enable/disable streaming in the "Upload & Process" tab.

### Output Files

All outputs are saved to `output/<project_id>/`:
- `metadata_json.json` - Generated metadata
- `processing_log.jsonl` - Processing logs
- `llm_responses.json` - All LLM interactions
- `runtime_config.json` - Complete runtime configuration including:
  - Input document path
  - Environment variables (.env)
  - LLM configuration
  - Runtime settings
  - Project metadata

### Example Usage

1. **Start the UI:**
   ```bash
   python run_fairifier.py ui
   ```

2. **Upload a document:**
   - Use the "📄 Upload & Process" tab
   - Upload a PDF, text, or markdown file
   - Or use the example file option (Earthworm paper)

3. **Configure settings:**
   - Go to "⚙️ Configuration" tab
   - Set LLM provider, model, and other parameters
   - Save to session or export to .env file

4. **Process the document:**
   - Click "🚀 Process Document" button
   - Watch real-time streaming output in the chat interface
   - View processing logs and LLM API responses

5. **Review results:**
   - Go to "🔍 Review Results" tab
   - View generated metadata
   - Download artifacts

## 🚀 API Server (Optional)

The `api/` directory contains an optional FastAPI server for programmatic access.

**Status**: Optional, not maintained  
**Purpose**: REST API for web integration  
**Usage**: Not recommended for production use  
**Note**: May be removed in future versions

## 📝 Notes

- The Streamlit UI is the recommended way to interact with FAIRiAgent interactively
- All configurations can be managed through the web UI
- Runtime configurations are automatically saved for each run
- The UI supports both streaming and non-streaming modes
