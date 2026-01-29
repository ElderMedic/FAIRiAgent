"""Streamlit app for FAIRifier human-in-the-loop interface."""

import tempfile
import os
import threading
from pathlib import Path
import asyncio
from datetime import datetime
import logging
import json

# Add parent directories to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
from fairifier.config import config, apply_env_overrides
from fairifier.utils.run_control import set_run_stop_requested

# Check if we're running in Streamlit environment
def _is_streamlit_context():
    """Check if we're running in a Streamlit context."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        return ctx is not None
    except (ImportError, AttributeError, RuntimeError):
        return False

# Delay Streamlit import to avoid warnings in CLI mode
# We'll import it lazily in functions that need it
_st = None

# Custom StreamHandler for Streamlit
class StreamlitLogHandler(logging.Handler):
    """Custom logging handler that writes to Streamlit."""
    def __init__(self, output_container):
        super().__init__()
        self.output_container = output_container
        self.log_buffer = []
        self.max_buffer_size = 200  # Keep last 200 lines
    
    def emit(self, record):
        """Emit a log record."""
        try:
            msg = self.format(record)
            self.log_buffer.append(msg)
            # Keep only last N lines
            if len(self.log_buffer) > self.max_buffer_size:
                self.log_buffer = self.log_buffer[-self.max_buffer_size:]
            # Update Streamlit container (will be updated in real-time)
            if self.output_container:
                self.output_container.code('\n'.join(self.log_buffer), language='text')
        except Exception:
            self.handleError(record)
    
    def get_logs(self):
        """Get all logs as string."""
        return '\n'.join(self.log_buffer)


def _load_result_from_output_folder(folder_path):
    """Load a saved run from a local output folder and build a result dict for display.
    Returns (result, project_id, output_path, project_name) or (None, None, None, None) on error.
    WebUI-only; does not modify main framework.
    """
    path = Path(folder_path).resolve()
    if not path.is_dir():
        return None, None, None, None
    try:
        # Required files
        workflow_report_path = path / "workflow_report.json"
        runtime_config_path = path / "runtime_config.json"
        metadata_json_path = path / "metadata_json.json"
        if not workflow_report_path.exists() or not runtime_config_path.exists() or not metadata_json_path.exists():
            return None, None, None, None
        report = json.loads(workflow_report_path.read_text(encoding="utf-8"))
        runtime = json.loads(runtime_config_path.read_text(encoding="utf-8"))
        meta = json.loads(metadata_json_path.read_text(encoding="utf-8"))
        runtime_info = runtime.get("runtime_info", {})
        project_id = runtime_info.get("project_id", path.name)
        output_path_str = runtime_info.get("output_path", str(path))
        doc_path = runtime_info.get("document_path", "")
        project_name = runtime_info.get("document_name") or (Path(doc_path).name if doc_path else path.name)
        # Artifacts: metadata_json content (already have meta), validation_report, processing_log if present
        metadata_json_str = metadata_json_path.read_text(encoding="utf-8")
        artifacts = {"metadata_json": metadata_json_str}
        if (path / "validation_report.txt").exists():
            artifacts["validation_report"] = (path / "validation_report.txt").read_text(encoding="utf-8")
        if (path / "processing_log.jsonl").exists():
            artifacts["processing_log"] = (path / "processing_log.jsonl").read_text(encoding="utf-8")
        # Execution history from timeline (minimal: agent_name, attempt, success, start_time, end_time)
        execution_history = []
        for t in report.get("timeline", []):
            execution_history.append({
                "agent_name": t.get("agent", "unknown"),
                "attempt": t.get("attempt", 1),
                "success": t.get("success", True),
                "start_time": t.get("start_time", ""),
                "end_time": t.get("end_time", ""),
                "critic_evaluation": {},
            })
        # Confidence scores from quality_metrics (report uses critic_confidence etc.)
        qm = report.get("quality_metrics", {})
        confidence_scores = {
            "critic": qm.get("critic_confidence", 0.0),
            "structural": qm.get("structural_confidence", 0.0),
            "validation": qm.get("validation_confidence", 0.0),
            "overall": qm.get("overall_confidence", 0.0),
        }
        # Metadata fields: flatten isa_structure from metadata_json
        metadata_fields = []
        isa_structure = meta.get("isa_structure", {})
        for _sheet_name, sheet_data in isa_structure.items():
            if isinstance(sheet_data, dict) and "fields" in sheet_data:
                for f in sheet_data["fields"]:
                    if isinstance(f, dict):
                        metadata_fields.append({
                            "field_name": f.get("field_name", ""),
                            "name": f.get("field_name", ""),
                            "value": f.get("value", ""),
                            "confidence": f.get("confidence", 0.5),
                            "description": f.get("evidence", ""),
                            "required": False,
                        })
        # Document info minimal (from metadata if available)
        document_info = {}
        if isa_structure.get("investigation", {}).get("fields"):
            for f in isa_structure["investigation"]["fields"]:
                if f.get("field_name") == "investigation title":
                    document_info["title"] = f.get("value", "")
                    break
        exec_summary = report.get("execution_summary", {})
        retry_analysis = report.get("retry_analysis", {})
        result = {
            "execution_summary": exec_summary,
            "document_info": document_info,
            "document_conversion": {},
            "confidence_scores": confidence_scores,
            "needs_human_review": exec_summary.get("needs_human_review", qm.get("needs_review", False)),
            "execution_history": execution_history,
            "quality_metrics": qm,
            "metadata_fields": metadata_fields,
            "artifacts": artifacts,
            "workflow_report": report,
            "output_dir": str(path),
            "status": report.get("workflow_status", "completed"),
            "global_retries_used": retry_analysis.get("global_retries_used", 0),
            "errors": [],
        }
        return result, project_id, output_path_str, project_name
    except Exception:
        return None, None, None, None


def _write_artifacts_to_output_path(result, output_path):
    """Write result artifacts to output_path (mirrors CLI behavior). WebUI-only helper."""
    path = Path(output_path) if not isinstance(output_path, Path) else output_path
    path.mkdir(parents=True, exist_ok=True)
    artifacts = result.get("artifacts", {})
    extensions = {
        "metadata_json": ".json",
        "validation_report": ".txt",
        "processing_log": ".jsonl",
    }
    for artifact_name, content in artifacts.items():
        if not content:
            continue
        ext = extensions.get(artifact_name, ".json")
        filename = f"{artifact_name}{ext}"
        filepath = path / filename
        text = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)
        filepath.write_text(text, encoding="utf-8")
    try:
        from fairifier.utils.llm_helper import get_llm_helper, save_llm_responses
        llm_helper = get_llm_helper()
        if llm_helper and getattr(llm_helper, "llm_responses", None):
            save_llm_responses(path, llm_helper)
    except Exception:
        pass


# Global variable to store chat container for LLM responses
_streamlit_chat_container = None
_streamlit_chat_messages = {}  # Store message containers by message_id

# Run-in-background state (thread and result); used for Stop button
_current_run = {
    "thread": None,
    "result": None,
    "done": False,
    "project_id": None,
    "output_path": None,
    "project_name": None,
    "tmp_path": None,
}

def _run_workflow_worker(
    file_path, project_id, output_path, project_name, tmp_path=None, resume=False
):
    """Run app.run() in a thread; store result in _current_run. If resume=True, continue from checkpoint."""
    global _current_run
    try:
        app = FAIRifierLangGraphApp()
        result = asyncio.run(
            app.run(file_path, project_id, output_path, resume=resume)
        )
        _current_run["result"] = result
    except Exception as e:
        _current_run["result"] = {
            "status": "failed",
            "errors": [str(e)],
            "execution_summary": {},
            "artifacts": {},
        }
    finally:
        _current_run["done"] = True
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def set_streamlit_chat_container(container):
    """Set the Streamlit chat container for LLM streaming output."""
    global _streamlit_chat_container
    _streamlit_chat_container = container

def get_streamlit_chat_container():
    """Get the Streamlit chat container for LLM streaming output."""
    return _streamlit_chat_container

def create_chat_message(agent_name, operation_name, message_id=None):
    """Create a new chat message bubble in the chat container.
    
    Returns:
        tuple: (message_container, message_id)
    """
    global _streamlit_chat_container, _streamlit_chat_messages
    
    if _streamlit_chat_container is None:
        return None, None
    
    try:
        import streamlit as st
        
        # Generate message_id if not provided
        if message_id is None:
            message_id = f"{agent_name}_{operation_name}_{datetime.now().strftime('%H%M%S%f')}"
        
        # Create a new message container using the chat container
        # We need to create the message in the chat container's context
        # Since _streamlit_chat_container is an empty container, we'll create messages dynamically
        # Store message info first
        _streamlit_chat_messages[message_id] = {
            'container': None,  # Will be set when rendering
            'agent_name': agent_name,
            'operation_name': operation_name,
            'content': '',
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'rendered': False
        }
        
        # Create a placeholder container for this message
        # We'll render all messages together in the chat container
        _render_all_chat_messages()
        
        return None, message_id
    except Exception as e:
        # Silently fail if not in Streamlit context
        return None, None

def _render_all_chat_messages():
    """Render all chat messages in the chat container."""
    global _streamlit_chat_container, _streamlit_chat_messages
    
    if _streamlit_chat_container is None:
        return
    
    try:
        import streamlit as st
        import html
        
        # Build HTML for all messages
        messages_html = ""
        for message_id, message_data in _streamlit_chat_messages.items():
            agent_name = message_data['agent_name']
            operation_name = message_data['operation_name']
            content = message_data['content']
            timestamp = message_data['timestamp']
            is_streaming = message_data.get('is_streaming', False)
            
            cursor = "▌" if is_streaming else ""
            
            # Escape HTML special characters in content
            escaped_content = html.escape(content)
            escaped_agent_name = html.escape(agent_name)
            escaped_operation_name = html.escape(operation_name)
            escaped_timestamp = html.escape(timestamp)
            
            messages_html += f"""
            <div style="
                margin-bottom: 15px;
                padding: 12px 16px;
                border-radius: 18px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                max-width: 85%;
                margin-left: auto;
                margin-right: 0;
            ">
                <div style="font-size: 0.85em; opacity: 0.9; margin-bottom: 6px;">
                    <strong>🤖 {escaped_agent_name}</strong> · {escaped_operation_name} · {escaped_timestamp}
                </div>
                <div style="font-size: 0.95em; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;">
                    {escaped_content}{cursor}
                </div>
            </div>
            """
        
        # Update the chat container with all messages
        if messages_html:
            _streamlit_chat_container.markdown(messages_html, unsafe_allow_html=True)
        else:
            _streamlit_chat_container.markdown("⏳ Waiting for agent responses...", unsafe_allow_html=True)
    except Exception:
        pass

def _update_chat_message(message_id, content, is_streaming=False):
    """Update a chat message with new content."""
    global _streamlit_chat_messages
    
    if message_id not in _streamlit_chat_messages:
        return
    
    # Update content and streaming status
    _streamlit_chat_messages[message_id]['content'] = content
    _streamlit_chat_messages[message_id]['is_streaming'] = is_streaming
    
    # Re-render all messages
    _render_all_chat_messages()

def update_chat_message(message_id, content, is_streaming=False):
    """Update a chat message with new content (public API)."""
    _update_chat_message(message_id, content, is_streaming)

def finalize_chat_message(message_id):
    """Finalize a chat message (remove cursor)."""
    global _streamlit_chat_messages
    
    if message_id not in _streamlit_chat_messages:
        return
    
    message_data = _streamlit_chat_messages[message_id]
    _update_chat_message(message_id, message_data['content'], is_streaming=False)

def clear_chat_messages():
    """Clear all chat messages."""
    global _streamlit_chat_messages
    _streamlit_chat_messages = {}

# Backward compatibility
def set_streamlit_llm_output_container(container):
    """Legacy function for backward compatibility."""
    set_streamlit_chat_container(container)

def get_streamlit_llm_output_container():
    """Legacy function for backward compatibility."""
    return get_streamlit_chat_container()

# Global list to store all LLM responses for display
_llm_responses_list = []

def add_llm_response(operation_name, prompt_preview, response_content):
    """Add an LLM response to the display list."""
    global _llm_responses_list
    _llm_responses_list.append({
        "operation": operation_name,
        "prompt_preview": prompt_preview[:200] + "..." if len(prompt_preview) > 200 else prompt_preview,
        "response": response_content,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })

def get_llm_responses():
    """Get all LLM responses."""
    return _llm_responses_list

def clear_llm_responses():
    """Clear all LLM responses."""
    global _llm_responses_list
    _llm_responses_list = []

# Initialize LangSmith tracing
def setup_langsmith():
    """Setup LangSmith tracing from environment variables."""
    langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
    langsmith_project = os.getenv("LANGSMITH_PROJECT", "fairifier-streamlit")
    
    if langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
        return True
    return False

# Setup LangSmith on import
langsmith_enabled = setup_langsmith()

# Don't configure Streamlit at module level
# This will be done in main() function when Streamlit is actually running

def main():
    # Import streamlit here to ensure we're in Streamlit context
    import streamlit as st
    
    # Configure page only when actually running in Streamlit
    st.set_page_config(
        page_title="FAIRifier - FAIR Metadata Generator",
        page_icon="🧬",
        layout="wide"
    )
    
    st.title("🧬 FAIRifier - FAIR Metadata Generator")
    st.markdown("Automated generation of FAIR metadata from research documents")
    
    # Use tabs instead of sidebar dropdown
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📄 Upload & Process", "⚙️ Configuration", "🔍 Review Results", "🧠 Memory", "ℹ️ About"
    ])
    
    with tab1:
        upload_and_process_page()
    with tab2:
        configuration_page()
    with tab3:
        review_results_page()
    with tab4:
        memory_page()
    with tab5:
        about_page()

def upload_and_process_page():
    import streamlit as st
    global _current_run

    # If a run is in progress, show status and Stop button (or handle completed run)
    if st.session_state.get("run_in_progress") and _current_run.get("thread") is not None:
        thread = _current_run["thread"]
        if not thread.is_alive():
            # Run finished (or was stopped)
            result = _current_run.get("result")
            project_id = _current_run.get("project_id")
            output_path = _current_run.get("output_path")
            project_name = _current_run.get("project_name")
            st.session_state.run_in_progress = False
            _current_run["thread"] = None
            _current_run["done"] = False
            _current_run["result"] = None
            _current_run["project_id"] = None
            _current_run["output_path"] = None
            _current_run["project_name"] = None
            _current_run["tmp_path"] = None
            if result is not None and output_path:
                st.session_state.last_result = result
                st.session_state.project_id = project_id
                st.session_state.project_name = project_name or ""
                st.session_state.output_path = output_path
                _write_artifacts_to_output_path(result, output_path)
                st.success("Run finished.")
                display_results(result)
                # Offer resume when run was interrupted (LangGraph checkpoint resume)
                if result.get("status") == "interrupted":
                    st.markdown("---")
                    st.info(
                        "This run was stopped. You can resume from the last "
                        "checkpoint (requires CHECKPOINTER_BACKEND=sqlite)."
                    )
                    if st.button("▶️ Resume run", type="primary", key="resume_run"):
                        runtime_config_path = Path(output_path) / "runtime_config.json"
                        document_path = None
                        if runtime_config_path.exists():
                            try:
                                rc = json.loads(
                                    runtime_config_path.read_text(encoding="utf-8")
                                )
                                document_path = rc.get("runtime_info", {}).get(
                                    "document_path"
                                )
                            except Exception:
                                pass
                        if not document_path:
                            st.error(
                                "Could not find document_path in runtime_config.json. "
                                "Cannot resume."
                            )
                        else:
                            apply_env_overrides(config)
                            from fairifier.utils.llm_helper import reset_llm_helper
                            reset_llm_helper()
                            setup_langsmith_from_session()
                            _current_run["done"] = False
                            _current_run["result"] = None
                            _current_run["project_id"] = project_id
                            _current_run["output_path"] = output_path
                            _current_run["project_name"] = project_name or ""
                            _current_run["tmp_path"] = None
                            thread = threading.Thread(
                                target=_run_workflow_worker,
                                args=(
                                    document_path,
                                    project_id,
                                    output_path,
                                    project_name or "",
                                    None,
                                    True,
                                ),
                            )
                            _current_run["thread"] = thread
                            thread.start()
                            st.session_state.run_in_progress = True
                            st.rerun()
            else:
                st.warning("Run ended with no result.")
        else:
            st.subheader("📊 Processing Output & Logs")
            st.info("🔄 Run in progress. Click **Stop run** to interrupt.")
            if st.button("⏹ Stop run", type="secondary"):
                set_run_stop_requested(True)
                st.rerun()
        return

    st.header("📄 Document Upload & Processing")
    
    # Default example file - try different possible names
    base_path = Path(__file__).parent.parent.parent.parent / "examples" / "inputs"
    example_file_path = None
    default_file_name = None
    
    # Try different possible filenames
    possible_names = [
        "earthworm_4n_paper_bioRXiv.pdf",
        "earthworm_4n_paper_bioRxiv.pdf",
        "earthworm_4n_paper_bioRxiv.pdf"
    ]
    
    for name in possible_names:
        test_path = base_path / name
        if test_path.exists():
            example_file_path = test_path
            default_file_name = name
            break
    
    # File upload
    uploaded_file = st.file_uploader(
        "Upload a research document",
        type=['pdf', 'txt', 'md'],
        help="Upload a PDF, text, or markdown file containing your research information"
    )
    
    # Use example file option
    use_example = st.checkbox(
        "Use example file (Earthworm paper)",
        value=True if default_file_name else False,
        help="Use the example earthworm research paper for demonstration"
    )
    
    # Project name
    project_name = st.text_input(
        "Project Name (optional)",
        value="Earthworm Research" if use_example else "",
        placeholder="Enter a name for this project"
    )
    
    # Enable streaming output option
    enable_streaming = st.checkbox(
        "💬 Enable Streaming Output (like ChatGPT)",
        value=True,
        help="Show LLM responses in real-time as they are generated (streaming mode)"
    )
    
    # Store in session state
    st.session_state["enable_streaming"] = enable_streaming
    
    # Process button
    if use_example and default_file_name:
        st.info(f"📁 Example file: {default_file_name}")
        if st.button("🚀 Process Example Document", type="primary"):
            process_document_from_path(str(example_file_path), project_name or "Earthworm Research")
    elif uploaded_file is not None:
        # Display file info
        st.info(f"📁 File: {uploaded_file.name} ({uploaded_file.size} bytes)")
        
        if st.button("🚀 Process Document", type="primary"):
            process_document(uploaded_file, project_name)

def process_document(uploaded_file, project_name):
    """Start processing in a background thread so the UI can show a Stop button."""
    import streamlit as st
    global _current_run
    from fairifier.config import apply_env_overrides, config

    apply_env_overrides(config)
    from fairifier.utils.llm_helper import reset_llm_helper
    reset_llm_helper()
    setup_langsmith_from_session()

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name

    project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    langsmith_project = st.session_state.get("langsmith_project", "fairifier-streamlit")
    os.environ["LANGCHAIN_PROJECT"] = langsmith_project

    output_path = config.output_path / project_id
    output_path.mkdir(parents=True, exist_ok=True)
    from fairifier.utils.config_saver import save_runtime_config
    save_runtime_config(tmp_path, project_id, output_path)

    _current_run["done"] = False
    _current_run["result"] = None
    _current_run["project_id"] = project_id
    _current_run["output_path"] = str(output_path)
    _current_run["project_name"] = project_name or uploaded_file.name
    _current_run["tmp_path"] = tmp_path
    thread = threading.Thread(
        target=_run_workflow_worker,
        args=(tmp_path, project_id, str(output_path), _current_run["project_name"], tmp_path),
    )
    _current_run["thread"] = thread
    thread.start()
    st.session_state.run_in_progress = True
    st.rerun()

def process_document_from_path(file_path, project_name):
    """Start processing from file path in a background thread so the UI can show a Stop button."""
    import streamlit as st
    global _current_run
    from fairifier.config import apply_env_overrides, config

    apply_env_overrides(config)
    from fairifier.utils.llm_helper import reset_llm_helper
    reset_llm_helper()
    setup_langsmith_from_session()

    project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    langsmith_project = st.session_state.get("langsmith_project", "fairifier-streamlit")
    os.environ["LANGCHAIN_PROJECT"] = langsmith_project

    output_path = config.output_path / project_id
    output_path.mkdir(parents=True, exist_ok=True)
    from fairifier.utils.config_saver import save_runtime_config
    save_runtime_config(file_path, project_id, output_path)

    _current_run["done"] = False
    _current_run["result"] = None
    _current_run["project_id"] = project_id
    _current_run["output_path"] = str(output_path)
    _current_run["project_name"] = project_name or Path(file_path).name
    _current_run["tmp_path"] = None
    thread = threading.Thread(
        target=_run_workflow_worker,
        args=(file_path, project_id, str(output_path), _current_run["project_name"], None),
    )
    _current_run["thread"] = thread
    thread.start()
    st.session_state.run_in_progress = True
    st.rerun()

def setup_langsmith_from_session():
    """Setup LangSmith tracing from session state."""
    import streamlit as st
    langsmith_api_key = st.session_state.get("langsmith_api_key")
    langsmith_project = st.session_state.get("langsmith_project", "fairifier-streamlit")
    
    if langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
        st.session_state["langsmith_enabled"] = True
    else:
        st.session_state["langsmith_enabled"] = False

def display_results(result):
    """Display processing results with enhanced visualizations."""
    import streamlit as st
    
    st.success("✅ Processing completed!")
    
    # Overall status
    status = result.get("status", "unknown")
    st.metric("Status", status.upper() if status else "UNKNOWN")
    
    # Create tabs for different views
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Summary", 
        "🔍 Execution History", 
        "🎯 Confidence Details",
        "📋 Metadata Fields",
        "📦 Artifacts"
    ])
    
    with tab1:
        display_summary_tab(result)
    
    with tab2:
        display_execution_history_tab(result)
    
    with tab3:
        display_confidence_tab(result)
    
    with tab4:
        display_metadata_tab(result)
    
    with tab5:
        display_artifacts_tab(result)


def display_summary_tab(result):
    """Display summary information."""
    import streamlit as st
    
    # Execution summary
    execution_summary = result.get("execution_summary", {})
    if execution_summary:
        st.subheader("📊 Execution Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Steps", execution_summary.get("total_steps", 0))
        with col2:
            st.metric("Successful", execution_summary.get("successful_steps", 0))
        with col3:
            st.metric("Failed", execution_summary.get("failed_steps", 0))
        with col4:
            retries = execution_summary.get("steps_requiring_retry", 0)
            global_retries = result.get("global_retries_used", 0)
            st.metric("Retries", f"{retries} / {global_retries}")
    # Document info
    doc_info = result.get("document_info", {})
    if doc_info:
        st.subheader("📄 Document Information")
        col1, col2 = st.columns(2)
        
        with col1:
            title = doc_info.get("title", "N/A")
            st.write("**Title:**", str(title) if title else "N/A")
            authors = doc_info.get("authors", [])
            if isinstance(authors, list) and len(authors) > 0:
                st.write("**Authors:**", ", ".join(authors[:3]) + (f" (+ {len(authors)-3} more)" if len(authors) > 3 else ""))
            else:
                st.write("**Authors:**", "N/A")
        
        with col2:
            research_domain = doc_info.get("research_domain", "N/A")
            st.write("**Research Domain:**", str(research_domain) if research_domain else "N/A")
            keywords = doc_info.get("keywords", [])
            if isinstance(keywords, list) and len(keywords) > 0:
                st.write("**Keywords:**", ", ".join(keywords[:5]) + (f" (+ {len(keywords)-5} more)" if len(keywords) > 5 else ""))
            else:
                st.write("**Keywords:**", "N/A")
    
    # MinerU conversion info
    conversion_info = result.get("document_conversion", {})
    if conversion_info:
        st.subheader("📑 Document Conversion (MinerU)")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if conversion_info.get("markdown_path"):
                st.metric("Status", "✅ Success")
            else:
                st.metric("Status", "⚠️ Fallback")
        
        with col2:
            if conversion_info.get("images_dir"):
                st.metric("Images Extracted", "Yes")
            else:
                st.metric("Images Extracted", "No")
        
        with col3:
            if conversion_info.get("output_dir"):
                st.metric("Output Dir", "Available")
                with st.expander("View Conversion Details"):
                    st.json(conversion_info)
    
    # Human review flag
    needs_review = result.get("needs_human_review", False)
    if needs_review:
        st.warning("🔍 This result requires human review before use")
    
    # Confidence scores summary
    confidence_scores = result.get("confidence_scores", {})
    if confidence_scores:
        st.subheader("🎯 Confidence Scores (Quick View)")
        cols = st.columns(len(confidence_scores))
        
        for i, (component, score) in enumerate(confidence_scores.items()):
            with cols[i % len(cols)]:
                color = "normal" if score > 0.8 else "inverse" if score < 0.6 else "off"
                st.metric(component.replace("_", " ").title(), f"{score:.2%}", delta_color=color)

def review_results_page():
    import streamlit as st
    st.header("🔍 Review Results")
    
    # Load saved run from local output folder (static view, like LangSmith trace)
    st.subheader("📂 Load saved run")
    st.caption("Select a run output folder to view its flow and results (e.g. output/20260129_174859).")
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    output_base = project_root / "output"
    existing_runs = []
    if output_base.is_dir():
        for d in sorted(output_base.iterdir(), key=lambda x: x.name, reverse=True):
            if d.is_dir() and (d / "workflow_report.json").exists():
                existing_runs.append((d.name, str(d)))
    folder_options = [" (choose or type path below)"] + [name for name, _ in existing_runs[:20]]
    selected = st.selectbox(
        "Recent runs (output folder)",
        folder_options,
        help="Pick a run from the list or type a path in the text field below.",
    )
    if selected == folder_options[0]:
        default_path = existing_runs[0][1] if existing_runs else ""
    else:
        default_path = str(output_base / selected) if output_base.is_dir() else ""
    folder_path = st.text_input(
        "Output folder path",
        value=default_path,
        placeholder="e.g. output/20260129_174859 or absolute path",
        help="Path to a run output directory containing workflow_report.json, runtime_config.json, metadata_json.json.",
    )
    if st.button("Load run"):
        if folder_path and folder_path.strip():
            result, proj_id, out_path, proj_name = _load_result_from_output_folder(folder_path.strip())
            if result is not None:
                st.session_state.last_result = result
                st.session_state.project_id = proj_id
                st.session_state.output_path = out_path
                st.session_state.project_name = proj_name
                st.success(f"Loaded run: {proj_name} ({proj_id}). Showing below.")
                st.rerun()
            else:
                st.error("Failed to load run. Check that the folder contains workflow_report.json, runtime_config.json, and metadata_json.json.")
        else:
            st.warning("Enter an output folder path.")
    
    st.markdown("---")
    
    if "last_result" not in st.session_state:
        st.info("No results to review. Process a document in **Upload & Process**, or load a saved run above.")
        return
    
    result = st.session_state.last_result
    project_name = st.session_state.get("project_name", "Unknown Project")
    
    st.subheader(f"Project: {project_name}")
    
    # Show validation report
    validation_report = result.get("artifacts", {}).get("validation_report", "")
    if validation_report:
        st.subheader("📊 Validation Report")
        st.text(validation_report)
    
    # Allow editing of metadata fields
    metadata_fields = result.get("metadata_fields", [])
    if metadata_fields:
        st.subheader("✏️ Edit Metadata Fields")
        
        # Convert to list if it's a dict
        if isinstance(metadata_fields, dict):
            metadata_fields = list(metadata_fields.values())
        
        edited_fields = []
        for i, field in enumerate(metadata_fields):
            if not isinstance(field, dict):
                continue
                
            field_name = field.get("field_name") or field.get("name", f"Field_{i}")
            is_required = field.get("required", False)
            
            with st.expander(f"{field_name} ({'Required' if is_required else 'Optional'})"):
                col1, col2 = st.columns(2)
                
                with col1:
                    new_name = st.text_input(
                        "Field Name", 
                        value=field_name, 
                        key=f"name_{i}"
                    )
                    new_type = st.selectbox(
                        "Data Type", 
                        ["string", "number", "datetime", "boolean"],
                        index=0 if field.get('data_type', 'string') not in ["string", "number", "datetime", "boolean"] 
                              else ["string", "number", "datetime", "boolean"].index(field.get('data_type', 'string')),
                        key=f"type_{i}"
                    )
                
                with col2:
                    new_required = st.checkbox(
                        "Required", 
                        value=is_required, 
                        key=f"req_{i}"
                    )
                    new_value = st.text_input(
                        "Value", 
                        value=field.get('value', ''), 
                        key=f"val_{i}"
                    )
                
                new_desc = st.text_area(
                    "Description", 
                    value=field.get('description', ''), 
                    key=f"desc_{i}"
                )
                
                edited_field = {
                    "field_name": new_name,
                    "name": new_name,
                    "description": new_desc,
                    "data_type": new_type,
                    "required": new_required,
                    "value": new_value,
                    "confidence": field.get('confidence', 0.5)
                }
                edited_fields.append(edited_field)
        
        if st.button("💾 Save Changes"):
            st.session_state.last_result["metadata_fields"] = edited_fields
            st.success("Changes saved!")
    
    # Full run view: Summary, Execution History, Confidence, Metadata Fields, Artifacts (same as after a live run)
    st.markdown("---")
    st.subheader("Run flow and results")
    display_results(result)
    # Offer resume when viewing an interrupted run (LangGraph checkpoint resume)
    if result.get("status") == "interrupted" and st.session_state.get("output_path"):
        st.markdown("---")
        st.info(
            "This run was stopped. You can resume from the last checkpoint "
            "(requires CHECKPOINTER_BACKEND=sqlite)."
        )
        if st.button("▶️ Resume run", type="primary", key="resume_run_review"):
            output_path = st.session_state.output_path
            project_id = st.session_state.get("project_id", "")
            project_name = st.session_state.get("project_name", "")
            runtime_config_path = Path(output_path) / "runtime_config.json"
            document_path = None
            if runtime_config_path.exists():
                try:
                    rc = json.loads(runtime_config_path.read_text(encoding="utf-8"))
                    document_path = rc.get("runtime_info", {}).get("document_path")
                except Exception:
                    pass
            if not document_path:
                st.error(
                    "Could not find document_path in runtime_config.json. Cannot resume."
                )
            else:
                global _current_run
                apply_env_overrides(config)
                from fairifier.utils.llm_helper import reset_llm_helper
                reset_llm_helper()
                setup_langsmith_from_session()
                _current_run["done"] = False
                _current_run["result"] = None
                _current_run["project_id"] = project_id
                _current_run["output_path"] = output_path
                _current_run["project_name"] = project_name
                _current_run["tmp_path"] = None
                thread = threading.Thread(
                    target=_run_workflow_worker,
                    args=(
                        document_path,
                        project_id,
                        output_path,
                        project_name,
                        None,
                        True,
                    ),
                )
                _current_run["thread"] = thread
                thread.start()
                st.session_state.run_in_progress = True
                st.rerun()

def configuration_page():
    """Configuration page for .env parameters."""
    import streamlit as st
    from fairifier.config import config
    
    st.header("⚙️ Configuration")
    st.markdown("Configure environment parameters for FAIRifier")
    
    # Initialize session state for config if not exists
    if "config_initialized" not in st.session_state:
        # Load current environment variables
        st.session_state["langsmith_api_key"] = os.getenv("LANGSMITH_API_KEY", "")
        st.session_state["langsmith_project"] = os.getenv("LANGSMITH_PROJECT", "fairifier-streamlit")
        st.session_state["langsmith_endpoint"] = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        st.session_state["llm_provider"] = os.getenv("LLM_PROVIDER", config.llm_provider or "ollama")
        st.session_state["llm_model"] = os.getenv("FAIRIFIER_LLM_MODEL", config.llm_model)
        st.session_state["llm_base_url"] = os.getenv("FAIRIFIER_LLM_BASE_URL", config.llm_base_url)
        st.session_state["llm_api_key"] = os.getenv("LLM_API_KEY", "")
        st.session_state["llm_temperature"] = os.getenv("LLM_TEMPERATURE", str(config.llm_temperature))
        st.session_state["llm_max_tokens"] = os.getenv("LLM_MAX_TOKENS", str(config.llm_max_tokens))
        st.session_state["llm_enable_thinking"] = os.getenv("LLM_ENABLE_THINKING", "false")
        st.session_state["fair_ds_api_url"] = os.getenv("FAIR_DS_API_URL", config.fair_ds_api_url or "")
        st.session_state["config_initialized"] = True
    
    # LangSmith Configuration
    st.subheader("🔗 LangSmith Configuration")
    col1, col2 = st.columns(2)
    
    with col1:
        langsmith_api_key = st.text_input(
            "LangSmith API Key",
            value=st.session_state["langsmith_api_key"],
            type="password",
            help="Your LangSmith API key for tracing and monitoring",
            key="config_langsmith_api_key"
        )
        langsmith_project = st.text_input(
            "LangSmith Project",
            value=st.session_state["langsmith_project"],
            help="Project name in LangSmith for organizing traces",
            key="config_langsmith_project"
        )
    
    with col2:
        langsmith_endpoint = st.text_input(
            "LangSmith Endpoint",
            value=st.session_state["langsmith_endpoint"],
            help="LangSmith API endpoint URL",
            key="config_langsmith_endpoint"
        )
        langsmith_enabled = st.checkbox(
            "Enable LangSmith Tracing",
            value=bool(st.session_state.get("langsmith_api_key")),
            help="Enable tracing to LangSmith for monitoring and debugging",
            key="config_langsmith_enabled"
        )
    
    # LLM Configuration
    st.subheader("🤖 LLM Configuration")
    col1, col2 = st.columns(2)
    
    with col1:
        llm_provider = st.selectbox(
            "LLM Provider",
            ["qwen", "openai", "ollama", "anthropic"],
            index=["qwen", "openai", "ollama", "anthropic"].index(st.session_state["llm_provider"]) if st.session_state["llm_provider"] in ["qwen", "openai", "ollama", "anthropic"] else 0,
            help="LLM provider to use",
            key="config_llm_provider"
        )
        llm_model = st.text_input(
            "LLM Model",
            value=st.session_state["llm_model"],
            help="Model name (e.g., qwen3-30b-a3b, gpt-4, claude-3)",
            key="config_llm_model"
        )
        llm_base_url = st.text_input(
            "LLM Base URL",
            value=st.session_state["llm_base_url"],
            help="Base URL for LLM API (leave empty for default)",
            key="config_llm_base_url"
        )
    
    with col2:
        llm_api_key = st.text_input(
            "LLM API Key",
            value=st.session_state["llm_api_key"],
            type="password",
            help="API key for LLM provider",
            key="config_llm_api_key"
        )
        llm_temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=float(st.session_state["llm_temperature"]),
            step=0.1,
            help="Temperature for LLM generation (0.0 = deterministic, 2.0 = creative)",
            key="config_llm_temperature"
        )
        llm_max_tokens = st.number_input(
            "Max Tokens",
            min_value=1000,
            max_value=1000000,
            value=int(st.session_state["llm_max_tokens"]),
            step=1000,
            help="Maximum tokens for LLM response",
            key="config_llm_max_tokens"
        )
        llm_enable_thinking = st.checkbox(
            "Enable Thinking Mode",
            value=st.session_state["llm_enable_thinking"].lower() in ("true", "1", "yes"),
            help="Enable thinking mode for models that support it (requires streaming)",
            key="config_llm_enable_thinking"
        )
    
    # FAIR-DS Configuration
    st.subheader("📊 FAIR-DS API Configuration")
    fair_ds_api_url = st.text_input(
        "FAIR-DS API URL",
        value=st.session_state["fair_ds_api_url"],
        help="URL for FAIR Data Station API",
        key="config_fair_ds_api_url"
    )
    
    # Save Configuration
    st.subheader("💾 Save Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("💾 Save to Session", type="primary"):
            # Update session state
            st.session_state["langsmith_api_key"] = langsmith_api_key if langsmith_enabled else ""
            st.session_state["langsmith_project"] = langsmith_project
            st.session_state["langsmith_endpoint"] = langsmith_endpoint
            st.session_state["llm_provider"] = llm_provider
            st.session_state["llm_model"] = llm_model
            st.session_state["llm_base_url"] = llm_base_url
            st.session_state["llm_api_key"] = llm_api_key
            st.session_state["llm_temperature"] = str(llm_temperature)
            st.session_state["llm_max_tokens"] = str(llm_max_tokens)
            st.session_state["llm_enable_thinking"] = "true" if llm_enable_thinking else "false"
            st.session_state["fair_ds_api_url"] = fair_ds_api_url
            
            # Update environment variables
            if langsmith_enabled and langsmith_api_key:
                os.environ["LANGSMITH_API_KEY"] = langsmith_api_key
                os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
                os.environ["LANGCHAIN_TRACING_V2"] = "true"
                st.session_state["langsmith_enabled"] = True
            else:
                os.environ.pop("LANGSMITH_API_KEY", None)
                os.environ.pop("LANGCHAIN_API_KEY", None)
                os.environ.pop("LANGCHAIN_TRACING_V2", None)
                st.session_state["langsmith_enabled"] = False
            
            os.environ["LANGSMITH_PROJECT"] = langsmith_project
            os.environ["LANGSMITH_ENDPOINT"] = langsmith_endpoint
            os.environ["LLM_PROVIDER"] = llm_provider
            os.environ["FAIRIFIER_LLM_MODEL"] = llm_model
            os.environ["FAIRIFIER_LLM_BASE_URL"] = llm_base_url
            os.environ["LLM_API_KEY"] = llm_api_key
            os.environ["LLM_TEMPERATURE"] = str(llm_temperature)
            os.environ["LLM_MAX_TOKENS"] = str(llm_max_tokens)
            os.environ["LLM_ENABLE_THINKING"] = "true" if llm_enable_thinking else "false"
            os.environ["FAIR_DS_API_URL"] = fair_ds_api_url
            
            # Reload config
            from fairifier.config import apply_env_overrides, config
            apply_env_overrides(config)
            
            # Reset LLMHelper to force reinitialization with new config
            from fairifier.utils.llm_helper import reset_llm_helper
            reset_llm_helper()
            
            st.success("✅ Configuration saved to session! Changes will apply to next processing run.")
    
    with col2:
        if st.button("📥 Export to .env"):
            # Generate .env file content
            env_content = f"""# FAIRiAgent Configuration (Generated from Streamlit UI)
# Generated: {datetime.now().isoformat()}

# LangSmith Configuration
LANGSMITH_API_KEY={langsmith_api_key if langsmith_enabled else ""}
LANGSMITH_PROJECT={langsmith_project}
LANGSMITH_ENDPOINT={langsmith_endpoint}

# LLM Configuration
LLM_PROVIDER={llm_provider}
FAIRIFIER_LLM_MODEL={llm_model}
FAIRIFIER_LLM_BASE_URL={llm_base_url}
LLM_API_KEY={llm_api_key}
LLM_TEMPERATURE={llm_temperature}
LLM_MAX_TOKENS={llm_max_tokens}
LLM_ENABLE_THINKING={"true" if llm_enable_thinking else "false"}

# FAIR-DS API Configuration
FAIR_DS_API_URL={fair_ds_api_url}
"""
            
            st.download_button(
                "📥 Download .env File",
                env_content,
                file_name=".env",
                mime="text/plain"
            )
    
    # Show current environment status
    st.subheader("📋 Current Environment Status")
    with st.expander("View Current Environment Variables"):
        env_vars = {
            "LANGSMITH_API_KEY": "***" if os.getenv("LANGSMITH_API_KEY") else "Not set",
            "LANGSMITH_PROJECT": os.getenv("LANGSMITH_PROJECT", "Not set"),
            "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2", "Not set"),
            "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "Not set"),
            "FAIRIFIER_LLM_MODEL": os.getenv("FAIRIFIER_LLM_MODEL", "Not set"),
            "LLM_API_KEY": "***" if os.getenv("LLM_API_KEY") else "Not set",
        }
        st.json(env_vars)
    
    # LangSmith status
    if st.session_state.get("langsmith_enabled", False):
        langsmith_project = os.getenv("LANGCHAIN_PROJECT", "fairifier-streamlit")
        langsmith_url = f"https://smith.langchain.com/"
        st.success(f"✅ LangSmith tracing is enabled")
        st.info(f"🔗 View traces: [Open LangSmith Dashboard]({langsmith_url})")
        st.info(f"📊 Project: `{langsmith_project}`")
    else:
        st.warning("⚠️ LangSmith tracing is disabled. Enable it above to track runs in LangSmith.")

def display_execution_history_tab(result):
    """Display execution history timeline with Critic evaluations."""
    import streamlit as st
    import pandas as pd
    from datetime import datetime as dt
    
    execution_history = result.get("execution_history", [])
    
    if not execution_history:
        st.info("No execution history available")
        return
    
    st.subheader("🔍 Execution History & Critic Evaluations")
    
    # Create timeline visualization
    timeline_data = []
    for i, exec_record in enumerate(execution_history):
        agent_name = exec_record.get("agent_name", "Unknown")
        attempt = exec_record.get("attempt", 1)
        success = exec_record.get("success", False)
        start_time = exec_record.get("start_time", "")
        end_time = exec_record.get("end_time", "")
        
        # Calculate duration if both times available
        duration = ""
        if start_time and end_time:
            try:
                start_dt = dt.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = dt.fromisoformat(end_time.replace('Z', '+00:00'))
                duration_sec = (end_dt - start_dt).total_seconds()
                duration = f"{duration_sec:.2f}s"
            except:
                pass
        
        # Get critic evaluation
        critic_eval = exec_record.get("critic_evaluation", {})
        decision = critic_eval.get("decision", "N/A")
        score = critic_eval.get("score", 0.0)
        
        timeline_data.append({
            "Step": i + 1,
            "Agent": agent_name,
            "Attempt": attempt,
            "Success": "✅" if success else "❌",
            "Duration": duration,
            "Critic Decision": decision,
            "Critic Score": f"{score:.2f}" if score else "N/A"
        })
    
    # Display as table
    df = pd.DataFrame(timeline_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Detailed view for each step
    st.subheader("📝 Detailed Execution Records")
    for i, exec_record in enumerate(execution_history):
        agent_name = exec_record.get("agent_name", "Unknown")
        attempt = exec_record.get("attempt", 1)
        success = exec_record.get("success", False)
        
        # Status icon
        status_icon = "✅" if success else "❌"
        retry_badge = f" (Attempt {attempt})" if attempt > 1 else ""
        
        with st.expander(f"{status_icon} Step {i+1}: {agent_name}{retry_badge}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Agent:**", agent_name)
                st.write("**Attempt:**", attempt)
                st.write("**Success:**", "Yes" if success else "No")
                
                if exec_record.get("error"):
                    st.error(f"**Error:** {exec_record['error']}")
            
            with col2:
                st.write("**Start Time:**", exec_record.get("start_time", "N/A"))
                st.write("**End Time:**", exec_record.get("end_time", "N/A"))
            
            # Critic evaluation details
            critic_eval = exec_record.get("critic_evaluation", {})
            if critic_eval:
                st.markdown("---")
                st.markdown("**🔍 Critic Evaluation:**")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    decision = critic_eval.get("decision", "N/A")
                    decision_color = {
                        "ACCEPT": "green",
                        "RETRY": "orange", 
                        "ESCALATE": "red"
                    }.get(decision, "gray")
                    st.markdown(f"**Decision:** :{decision_color}[{decision}]")
                
                with col2:
                    score = critic_eval.get("score", 0.0)
                    st.metric("Quality Score", f"{score:.2f}")
                
                with col3:
                    confidence = critic_eval.get("confidence", 0.0)
                    st.metric("Confidence", f"{confidence:.2f}")
                
                # Detailed critique
                if critic_eval.get("strengths"):
                    st.success(f"**Strengths:** {', '.join(critic_eval['strengths'])}")
                
                if critic_eval.get("weaknesses"):
                    st.warning(f"**Weaknesses:** {', '.join(critic_eval['weaknesses'])}")
                
                if critic_eval.get("suggestions"):
                    st.info(f"**Suggestions:** {', '.join(critic_eval['suggestions'])}")
                
                # Rubric scores
                rubric_scores = critic_eval.get("rubric_scores", {})
                if rubric_scores:
                    st.markdown("**Rubric Scores:**")
                    score_cols = st.columns(len(rubric_scores))
                    for idx, (criterion, value) in enumerate(rubric_scores.items()):
                        with score_cols[idx]:
                            st.metric(criterion.replace("_", " ").title(), f"{value:.2f}")


def display_confidence_tab(result):
    """Display multi-dimensional confidence scores."""
    import streamlit as st
    
    st.subheader("🎯 Multi-Dimensional Confidence Scores")
    
    confidence_scores = result.get("confidence_scores", {})
    quality_metrics = result.get("quality_metrics", {})
    
    if not confidence_scores:
        st.info("No confidence scores available")
        return
    
    # Overall confidence
    overall_conf = confidence_scores.get("overall", 0.0)
    st.metric("Overall Confidence", f"{overall_conf:.2%}", 
              help="Weighted average of all confidence dimensions")
    
    # Individual confidence dimensions
    st.markdown("---")
    st.markdown("### Confidence Breakdown")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        critic_conf = confidence_scores.get("critic", 0.0)
        st.metric("Critic Confidence", f"{critic_conf:.2%}",
                  help="Confidence from Critic Agent evaluations")
    
    with col2:
        structural_conf = confidence_scores.get("structural", 0.0)
        st.metric("Structural Confidence", f"{structural_conf:.2%}",
                  help="Based on field coverage and evidence presence")
    
    with col3:
        validation_conf = confidence_scores.get("validation", 0.0)
        st.metric("Validation Confidence", f"{validation_conf:.2%}",
                  help="Based on schema validation and format compliance")
    
    # Quality metrics (flat structure: critic_scores, field_completion_ratio, evidence_coverage_ratio, etc.)
    if quality_metrics:
        st.markdown("---")
        st.markdown("### Quality Metrics Details")
        flat_labels = {
            "critic_scores": "Critic scores",
            "field_completion_ratio": "Field completion ratio",
            "evidence_coverage_ratio": "Evidence coverage ratio",
            "avg_field_confidence": "Avg field confidence",
            "validation_errors": "Validation errors",
            "validation_warnings": "Validation warnings",
        }
        for key, label in flat_labels.items():
            if key in quality_metrics:
                val = quality_metrics[key]
                if isinstance(val, (int, float)):
                    st.write(f"**{label}:** {val:.2%}" if isinstance(val, float) and 0 <= val <= 1 else f"**{label}:** {val}")
                else:
                    st.write(f"**{label}:** {val}")
        with st.expander("View All Quality Metrics (raw)"):
            st.json(quality_metrics)
    
    # Confidence weights visualization
    st.markdown("---")
    st.markdown("### Confidence Weights")
    
    from fairifier.config import config
    
    weights_data = {
        "Critic": config.confidence_weight_critic,
        "Structural": config.confidence_weight_structural,
        "Validation": config.confidence_weight_validation
    }
    
    col1, col2, col3 = st.columns(3)
    for idx, (name, weight) in enumerate(weights_data.items()):
        with [col1, col2, col3][idx]:
            st.metric(f"{name} Weight", f"{weight:.2f}")


def display_metadata_tab(result):
    """Display metadata fields organized by ISA sheet."""
    import streamlit as st
    
    st.subheader("🏷️ Generated Metadata Fields")
    
    metadata_fields = result.get("metadata_fields", [])
    
    if not metadata_fields:
        st.info("No metadata fields available")
        return
    
    # Convert to list if dict
    if isinstance(metadata_fields, dict):
        metadata_fields = list(metadata_fields.values())
    
    # Group by ISA sheet
    from collections import defaultdict
    fields_by_sheet = defaultdict(list)
    fields_without_sheet = []
    
    for field in metadata_fields:
        if not isinstance(field, dict):
            continue
        
        isa_sheet = field.get("isa_sheet")
        if isa_sheet:
            fields_by_sheet[isa_sheet].append(field)
        else:
            fields_without_sheet.append(field)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Fields", len(metadata_fields))
    
    with col2:
        required_count = sum(1 for f in metadata_fields if isinstance(f, dict) and f.get("required", False))
        st.metric("Required Fields", required_count)
    
    with col3:
        st.metric("ISA Sheets", len(fields_by_sheet))
    
    with col4:
        avg_confidence = sum(f.get("confidence", 0) for f in metadata_fields if isinstance(f, dict)) / len(metadata_fields) if metadata_fields else 0
        st.metric("Avg Confidence", f"{avg_confidence:.2%}")
    
    # Display by ISA sheet
    st.markdown("---")
    st.markdown("### Fields by ISA Sheet")
    
    sheet_order = ["investigation", "study", "assay", "sample", "observationunit"]
    
    for sheet_name in sheet_order:
        if sheet_name not in fields_by_sheet:
            continue
        
        sheet_fields = fields_by_sheet[sheet_name]
        
        with st.expander(f"📋 {sheet_name.upper()} ({len(sheet_fields)} fields)", expanded=(sheet_name == "investigation")):
            display_field_list(sheet_fields)
    
    # Fields without ISA sheet
    if fields_without_sheet:
        with st.expander(f"📋 UNASSIGNED ({len(fields_without_sheet)} fields)"):
            display_field_list(fields_without_sheet)
    
    # Download metadata as JSON
    st.markdown("---")
    import json
    metadata_json = json.dumps({"metadata_fields": metadata_fields}, indent=2)
    st.download_button(
        "📥 Download Metadata Fields (JSON)",
        metadata_json,
        file_name="metadata_fields.json",
        mime="application/json"
    )


def display_field_list(fields):
    """Display a list of metadata fields."""
    import streamlit as st
    
    for field in fields:
        field_name = field.get("field_name") or field.get("name", "Unknown")
        is_required = field.get("required", False)
        confidence = field.get("confidence", 0.0)
        value = field.get("value", "")
        evidence = field.get("evidence", "")
        package = field.get("package_source", "")
        
        # Field header
        required_badge = "🔴 Required" if is_required else "⚪ Optional"
        package_badge = f"📦 {package}" if package else ""
        
        st.markdown(f"**{field_name}** {required_badge} {package_badge}")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if field.get("description"):
                st.caption(field["description"])
            
            if value:
                st.code(value, language="text")
            else:
                st.caption("_No value extracted_")
        
        with col2:
            st.metric("Confidence", f"{confidence:.2%}")
            
            if field.get("data_type"):
                st.caption(f"Type: `{field['data_type']}`")
        
        if evidence:
            with st.expander("📖 Evidence"):
                st.text(evidence[:500] + ("..." if len(evidence) > 500 else ""))
        
        st.markdown("---")


def display_artifacts_tab(result):
    """Display and download artifacts."""
    import streamlit as st
    import json
    
    st.subheader("📦 Generated Artifacts")
    
    artifacts = result.get("artifacts", {})
    
    if not artifacts:
        st.info("No artifacts available")
        return
    
    # Metadata JSON (FAIR-DS compatible)
    if "metadata_json" in artifacts:
        st.markdown("### 📄 Metadata JSON (FAIR-DS Compatible)")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            metadata_json_str = artifacts["metadata_json"]
            if isinstance(metadata_json_str, str):
                st.download_button(
                    "📥 Download JSON",
                    metadata_json_str,
                    file_name="metadata_fairds.json",
                    mime="application/json",
                    use_container_width=True
                )
            else:
                st.download_button(
                    "📥 Download JSON",
                    json.dumps(metadata_json_str, indent=2),
                    file_name="metadata_fairds.json",
                    mime="application/json",
                    use_container_width=True
                )
        
        with col2:
            st.info("FAIR-DS compatible JSON format for direct submission to data repositories")
        
        # Preview
        with st.expander("👁️ Preview Metadata JSON"):
            if isinstance(artifacts["metadata_json"], str):
                try:
                    st.json(json.loads(artifacts["metadata_json"]))
                except:
                    st.code(artifacts["metadata_json"], language="json")
            else:
                st.json(artifacts["metadata_json"])
    
    # Validation Report
    if "validation_report" in artifacts:
        st.markdown("---")
        st.markdown("### ✅ Validation Report")
        
        validation_report = artifacts["validation_report"]
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.download_button(
                "📥 Download Report",
                validation_report,
                file_name="validation_report.txt",
                mime="text/plain",
                use_container_width=True
            )
        
        with col2:
            st.info("Quality assessment and validation results")
        
        with st.expander("👁️ View Validation Report"):
            st.text(validation_report)
    
    # Processing Log
    if "processing_log" in artifacts:
        st.markdown("---")
        st.markdown("### 📝 Processing Log")
        
        processing_log = artifacts["processing_log"]
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.download_button(
                "📥 Download Log",
                processing_log,
                file_name="processing_log.jsonl",
                mime="text/plain",
                use_container_width=True
            )
        
        with col2:
            st.info("Detailed execution log in JSONL format")
    
    # Workflow Report
    workflow_report = result.get("workflow_report")
    if workflow_report:
        st.markdown("---")
        st.markdown("### 📊 Workflow Report")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.download_button(
                "📥 Download Report (JSON)",
                json.dumps(workflow_report, indent=2),
                file_name="workflow_report.json",
                mime="application/json",
                use_container_width=True
            )
        
        with col2:
            st.info("Comprehensive workflow execution report with metrics")
        
        with st.expander("👁️ View Workflow Report"):
            st.json(workflow_report)
    
    # Output directory info
    output_path = result.get("output_dir") or st.session_state.get("output_path")
    if output_path:
        st.markdown("---")
        st.info(f"💾 **Output Directory:** `{output_path}`")
        st.caption("All artifacts have been saved to this directory")


def memory_page():
    """Memory tab: list and overview mem0 memories for a session (WebUI-only, uses existing mem0 APIs)."""
    import streamlit as st
    apply_env_overrides(config)
    
    st.header("🧠 Memory (mem0)")
    st.markdown("View memory list and overview for a workflow session. Requires mem0 enabled and Qdrant running.")
    
    # Status block
    st.subheader("Status")
    st.write("**Mem0 enabled:**", "Yes" if config.mem0_enabled else "No")
    mem0_service = None
    try:
        from fairifier.services.mem0_service import get_mem0_service
        mem0_service = get_mem0_service()
    except ImportError:
        pass
    if mem0_service and mem0_service.is_available():
        st.success("Mem0 service is available.")
        st.caption(f"Qdrant: {config.mem0_qdrant_host}:{config.mem0_qdrant_port} | Collection: {config.mem0_collection_name} | Embedding: {config.mem0_embedding_model}")
    else:
        if not config.mem0_enabled:
            st.info("Mem0 is disabled. Set MEM0_ENABLED=true in .env to enable.")
        else:
            st.warning("Mem0 is enabled but service not available. Ensure Qdrant is running and mem0ai is installed.")
    
    # Session ID input
    default_session = st.session_state.get("project_id", "")
    session_id = st.text_input(
        "Session ID (e.g. project ID from a run)",
        value=default_session,
        placeholder="e.g. fairifier_20260129_120000",
        help="Use the project ID from a completed run to view that session's memories.",
    )
    
    # Agent filter
    agent_filter = st.selectbox(
        "Filter by agent",
        ["All", "DocumentParser", "KnowledgeRetriever", "JSONGenerator"],
        help="Filter memory list by agent.",
    )
    agent_id_for_list = None if agent_filter == "All" else agent_filter
    
    # List memories
    st.subheader("Memory List")
    if st.button("List memories"):
        if not session_id or not session_id.strip():
            st.warning("Please enter a session ID.")
        elif not mem0_service or not mem0_service.is_available():
            st.warning("Mem0 is disabled or unavailable. Set MEM0_ENABLED=true and ensure Qdrant is running.")
        else:
            memories = mem0_service.list_memories(session_id.strip(), agent_id=agent_id_for_list)
            if not memories:
                st.info("No memories found for this session.")
            else:
                st.write(f"**Total:** {len(memories)} memories (showing up to 50)")
                limit = 50
                for i, m in enumerate(memories[:limit]):
                    mem_id = m.get("id", "unknown")
                    mem_id_short = (mem_id[:12] + "...") if len(str(mem_id)) > 12 else mem_id
                    agent_id = m.get("agent_id") or m.get("metadata", {}).get("agent_id", "unknown")
                    text = m.get("memory", "")
                    text_preview = (text[:200] + "...") if len(text) > 200 else text
                    meta = m.get("metadata", {})
                    ts = meta.get("timestamp", "")[:19] if meta.get("timestamp") else ""
                    with st.expander(f"ID: {mem_id_short} | Agent: {agent_id}" + (f" | {ts}" if ts else "")):
                        st.write("**Memory:**", text_preview if len(text) <= 500 else text[:500] + "...")
                        if ts:
                            st.caption(f"Timestamp: {ts}")
                if len(memories) > limit:
                    st.caption(f"... and {len(memories) - limit} more.")
    
    # Generate overview
    st.subheader("Memory Overview")
    use_llm = st.checkbox("Use LLM summary", value=True, help="Generate natural language summary (slower). Uncheck for simple summary.")
    if st.button("Generate overview"):
        if not session_id or not session_id.strip():
            st.warning("Please enter a session ID.")
        elif not mem0_service or not mem0_service.is_available():
            st.warning("Mem0 is disabled or unavailable.")
        else:
            with st.spinner("Generating overview..."):
                overview = mem0_service.generate_memory_overview(session_id.strip(), use_llm=use_llm)
            if "error" in overview:
                st.error(overview["error"])
            else:
                st.write("**Total memories:**", overview.get("total_memories", 0))
                if overview.get("agents"):
                    st.write("**Agent activity:**")
                    for ag, count in sorted(overview["agents"].items(), key=lambda x: -x[1]):
                        st.write(f"  - {ag}: {count}")
                if overview.get("themes"):
                    st.write("**Key themes:**", ", ".join(overview["themes"]))
                if overview.get("summary"):
                    st.write("**Summary:**")
                    st.write(overview["summary"])
                if overview.get("memory_texts"):
                    st.write("**Sample memories (first 5):**")
                    for j, mem_text in enumerate(overview["memory_texts"][:5], 1):
                        display_text = mem_text if len(mem_text) <= 80 else mem_text[:77] + "..."
                        st.write(f"  {j}. {display_text}")
    
    # Clear session memories (optional)
    st.subheader("Clear Session Memories")
    confirm_clear = st.checkbox("I confirm I want to delete all memories for the session ID above", value=False, key="memory_clear_confirm")
    if st.button("Clear session memories", disabled=not confirm_clear or not session_id or not session_id.strip()):
        if not mem0_service or not mem0_service.is_available():
            st.warning("Mem0 is not available.")
        else:
            deleted = mem0_service.delete_session_memories(session_id.strip())
            st.success(f"Deleted {deleted} memories for session {session_id.strip()}.")


def about_page():
    import streamlit as st
    st.header("ℹ️ About FAIRifier")
    
    st.markdown("""
    ## What is FAIRifier?
    
    FAIRifier is an agentic framework that automatically generates **FAIR-DS compatible JSON metadata**
    from research documents, following FAIR (Findable, Accessible, Interoperable, Reusable) principles.
    
    ## Features
    
    - 📄 **Document Analysis**: Extracts key information from research papers and proposals
    - 🧠 **Knowledge Enrichment**: Uses FAIR Data Station API and ontologies to enhance metadata
    - 🏷️ **FAIR-DS Output**: Produces structured JSON metadata (no RDF/RO-Crate in main flow)
    - ✅ **Validation**: Schema validation and quality assessment
    - 👥 **Human-in-the-Loop**: Supports human review and editing of results in the WebUI
    
    ## Architecture
    
    FAIRifier uses a LangGraph-based multi-agent pipeline:
    
    1. **read_file**: Loads document content (with optional MinerU conversion for PDFs)
    2. **orchestrate**: Coordinates agents with Critic-in-the-loop:
       - **Document Parser**: Extracts structured information from documents
       - **Planner**: Plans workflow strategy and agent guidance
       - **Knowledge Retriever**: Enriches with FAIR-DS packages and ontology terms
       - **JSON Generator**: Produces FAIR-DS compatible JSON metadata
       - **Critic**: Evaluates outputs and triggers retries when needed
    3. **finalize**: Aggregates confidence, generates reports, and sets status
    
    ## Supported Standards
    
    - **FAIR-DS**: FAIR Data Station compatible metadata format
    - **ISA-Tab style**: Investigation/Study/Assay–style field organization
    - Schema validation and SHACL where applicable
    """)
    
    st.subheader("🛠️ Configuration")
    st.json({
        "LLM Provider": config.llm_provider,
        "LLM Model": config.llm_model,
        "Min Confidence Threshold": config.min_confidence_threshold,
        "FAIR-DS API URL": config.fair_ds_api_url or "(not set)",
        "Max Document Size (MB)": config.max_document_size_mb,
    })

if __name__ == "__main__":
    main()
