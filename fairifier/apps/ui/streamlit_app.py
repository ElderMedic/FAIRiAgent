"""Streamlit app for FAIRifier human-in-the-loop interface."""

import tempfile
import os
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

# Global variable to store chat container for LLM responses
_streamlit_chat_container = None
_streamlit_chat_messages = {}  # Store message containers by message_id

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
    tab1, tab2, tab3, tab4 = st.tabs(["📄 Upload & Process", "⚙️ Configuration", "🔍 Review Results", "ℹ️ About"])
    
    with tab1:
        upload_and_process_page()
    with tab2:
        configuration_page()
    with tab3:
        review_results_page()
    with tab4:
        about_page()

def upload_and_process_page():
    import streamlit as st
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
    """Process the uploaded document with real-time output display."""
    import streamlit as st
    from fairifier.config import apply_env_overrides, config
    
    # Apply configuration from session state before processing
    apply_env_overrides(config)
    
    # Reset LLMHelper to ensure it uses the latest config
    from fairifier.utils.llm_helper import reset_llm_helper
    reset_llm_helper()
    
    # Setup LangSmith tracing before processing
    setup_langsmith_from_session()
    
    # Create output containers
    st.subheader("📊 Processing Output & Logs")
    
    # Create LLM chat interface (like ChatGPT) if enabled
    enable_streaming = st.session_state.get("enable_streaming", True)
    chat_container = None
    if enable_streaming:
        st.subheader("💬 Agent Chat (Real-time Streaming)")
        
        # Add CSS for chat interface
        st.markdown("""
        <style>
        .chat-container {
            max-height: 600px;
            overflow-y: auto;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Create chat container
        chat_container = st.container()
        with chat_container:
            st.markdown('<div class="chat-container">', unsafe_allow_html=True)
            chat_content = st.empty()
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Set the chat container
        set_streamlit_chat_container(chat_content)
        clear_chat_messages()
    else:
        # Clear container if streaming is disabled
        set_streamlit_chat_container(None)
        clear_chat_messages()
    
    # Create expandable sections for output and errors
    with st.expander("📋 View Processing Logs", expanded=True):
        output_container = st.empty()
    
    error_expander = st.expander("❌ Errors & Warnings", expanded=False)
    error_container = error_expander.empty()
    
    status_container = st.empty()
    
    # Initialize log handler
    log_handler = StreamlitLogHandler(output_container)
    log_handler.setFormatter(logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
    
    # Add handler to root logger
    root_logger = logging.getLogger()
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        if isinstance(handler, StreamlitLogHandler):
            root_logger.removeHandler(handler)
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.INFO)
    
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # Generate project ID
        project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Set LangSmith project for this run
        langsmith_project = st.session_state.get("langsmith_project", "fairifier-streamlit")
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
        
        # Update status
        status_container.info(f"🚀 Starting processing... Project ID: {project_id}")
        
        # Determine output directory
        from fairifier.config import config
        output_path = config.output_path / project_id
        output_path.mkdir(parents=True, exist_ok=True)
        # Save runtime configuration
        from fairifier.utils.config_saver import save_runtime_config
        config_file = save_runtime_config(tmp_path, project_id, output_path)
        logging.info(f"💾 Saved runtime configuration to {config_file}")
        
        # Run LangGraph workflow
        app = FAIRifierLangGraphApp()
        result = asyncio.run(app.run(tmp_path, project_id))
        
        # Store result in session state
        st.session_state.last_result = result
        st.session_state.project_id = project_id
        st.session_state.project_name = project_name or uploaded_file.name
        st.session_state.output_path = str(output_path)
        
        # Check for errors
        errors = result.get("errors", [])
        if errors:
            error_container.error("❌ Errors occurred during processing:")
            for error in errors:
                error_container.error(f"  - {error}")
            error_expander.expanded = True  # Auto-expand if errors exist
        
        # Display LangSmith trace link if enabled
        if st.session_state.get("langsmith_enabled", False):
            langsmith_project = os.environ.get('LANGCHAIN_PROJECT', 'fairifier-streamlit')
            langsmith_url = f"https://smith.langchain.com/"
            st.info(f"🔗 View trace in LangSmith: [Open Dashboard]({langsmith_url})")
            st.info(f"📊 Project: {langsmith_project} | Run ID: {project_id}")
        
        # Update status
        status = result.get("status", "unknown")
        if status == "completed":
            status_container.success(f"✅ Processing completed! Status: {status.upper()}")
        else:
            status_container.warning(f"⚠️ Processing finished with status: {status.upper()}")
        
        # Display final logs
        final_logs = log_handler.get_logs()
        if final_logs:
            output_container.code(final_logs, language='text')
        
        # Display all LLM responses
        llm_responses = get_llm_responses()
        if llm_responses:
            with st.expander("💬 LLM API Responses", expanded=True):
                for i, resp in enumerate(llm_responses, 1):
                    st.markdown(f"### {i}. {resp['operation']} ({resp['timestamp']})")
                    st.markdown("**Prompt Preview:**")
                    st.code(resp['prompt_preview'], language='text')
                    st.markdown("**Response:**")
                    # Try to format as JSON if possible
                    try:
                        import json
                        parsed = json.loads(resp['response'])
                        st.json(parsed)
                    except (json.JSONDecodeError, ValueError):
                        # If not JSON, display as code
                        st.code(resp['response'][:5000] + ("..." if len(resp['response']) > 5000 else ""), language='text')
                    st.markdown("---")
        else:
            st.info("ℹ️ No LLM API calls were made during processing")
        
        # Display results
        display_results(result)
        
    except Exception as e:
        error_container.error(f"❌ Processing failed: {str(e)}")
        import traceback
        error_trace = traceback.format_exc()
        error_container.code(error_trace, language='python')
        status_container.error("❌ Processing failed")
        error_expander.expanded = True  # Auto-expand on error
        
        # Also add to output logs
        log_handler.emit(logging.LogRecord(
            name="streamlit",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=f"Processing failed: {str(e)}\n{error_trace}",
            args=(),
            exc_info=None
        ))
    finally:
        # Remove log handler
        root_logger.removeHandler(log_handler)
        
        # Clean up temporary file
        try:
            if 'tmp_path' in locals():
                os.unlink(tmp_path)
        except:
            pass

def process_document_from_path(file_path, project_name):
    """Process a document from file path (for example files) with real-time output display."""
    import streamlit as st
    from fairifier.config import apply_env_overrides, config
    
    # Apply configuration from session state before processing
    apply_env_overrides(config)
    
    # Reset LLMHelper to ensure it uses the latest config
    from fairifier.utils.llm_helper import reset_llm_helper
    reset_llm_helper()
    
    # Setup LangSmith tracing before processing
    setup_langsmith_from_session()
    
    # Create output containers
    st.subheader("📊 Processing Output & Logs")
    
    # Create LLM chat interface (like ChatGPT) if enabled
    enable_streaming = st.session_state.get("enable_streaming", True)
    chat_container = None
    if enable_streaming:
        st.subheader("💬 Agent Chat (Real-time Streaming)")
        
        # Add CSS for chat interface
        st.markdown("""
        <style>
        .chat-container {
            max-height: 600px;
            overflow-y: auto;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Create chat container
        chat_container = st.container()
        with chat_container:
            st.markdown('<div class="chat-container">', unsafe_allow_html=True)
            chat_content = st.empty()
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Set the chat container
        set_streamlit_chat_container(chat_content)
        clear_chat_messages()
    else:
        # Clear container if streaming is disabled
        set_streamlit_chat_container(None)
        clear_chat_messages()
    
    # Create expandable sections for output and errors
    with st.expander("📋 View Processing Logs", expanded=True):
        output_container = st.empty()
    
    error_expander = st.expander("❌ Errors & Warnings", expanded=False)
    error_container = error_expander.empty()
    
    status_container = st.empty()
    
    # Initialize log handler
    log_handler = StreamlitLogHandler(output_container)
    log_handler.setFormatter(logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
    
    # Add handler to root logger
    root_logger = logging.getLogger()
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        if isinstance(handler, StreamlitLogHandler):
            root_logger.removeHandler(handler)
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.INFO)
    
    try:
        # Generate project ID
        project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Determine output directory
        from fairifier.config import config
        output_path = config.output_path / project_id
        output_path.mkdir(parents=True, exist_ok=True)
        # Save runtime configuration
        from fairifier.utils.config_saver import save_runtime_config
        config_file = save_runtime_config(file_path, project_id, output_path)
        logging.info(f"💾 Saved runtime configuration to {config_file}")
        
        # Set LangSmith project for this run
        langsmith_project = st.session_state.get("langsmith_project", "fairifier-streamlit")
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
        
        # Update status
        status_container.info(f"🚀 Starting processing... Project ID: {project_id}")
        
        # Run LangGraph workflow
        app = FAIRifierLangGraphApp()
        result = asyncio.run(app.run(file_path, project_id))
        
        # Store result in session state
        st.session_state.last_result = result
        st.session_state.project_id = project_id
        st.session_state.project_name = project_name or Path(file_path).name
        st.session_state.output_path = str(output_path)
        
        # Check for errors
        errors = result.get("errors", [])
        if errors:
            error_container.error("❌ Errors occurred during processing:")
            for error in errors:
                error_container.error(f"  - {error}")
            error_expander.expanded = True  # Auto-expand if errors exist
        
        # Display LangSmith trace link if enabled
        if st.session_state.get("langsmith_enabled", False):
            langsmith_project = os.environ.get('LANGCHAIN_PROJECT', 'fairifier-streamlit')
            langsmith_url = f"https://smith.langchain.com/"
            st.info(f"🔗 View trace in LangSmith: [Open Dashboard]({langsmith_url})")
            st.info(f"📊 Project: {langsmith_project} | Run ID: {project_id}")
        
        # Update status
        status = result.get("status", "unknown")
        if status == "completed":
            status_container.success(f"✅ Processing completed! Status: {status.upper()}")
        else:
            status_container.warning(f"⚠️ Processing finished with status: {status.upper()}")
        
        # Display final logs
        final_logs = log_handler.get_logs()
        if final_logs:
            output_container.code(final_logs, language='text')
        
        # Display all LLM responses
        llm_responses = get_llm_responses()
        if llm_responses:
            with st.expander("💬 LLM API Responses", expanded=True):
                for i, resp in enumerate(llm_responses, 1):
                    st.markdown(f"### {i}. {resp['operation']} ({resp['timestamp']})")
                    st.markdown("**Prompt Preview:**")
                    st.code(resp['prompt_preview'], language='text')
                    st.markdown("**Response:**")
                    # Try to format as JSON if possible
                    try:
                        import json
                        parsed = json.loads(resp['response'])
                        st.json(parsed)
                    except (json.JSONDecodeError, ValueError):
                        # If not JSON, display as code
                        st.code(resp['response'][:5000] + ("..." if len(resp['response']) > 5000 else ""), language='text')
                    st.markdown("---")
        else:
            st.info("ℹ️ No LLM API calls were made during processing")
        
        # Display results
        display_results(result)
        
    except Exception as e:
        error_container.error(f"❌ Processing failed: {str(e)}")
        import traceback
        error_trace = traceback.format_exc()
        error_container.code(error_trace, language='python')
        status_container.error("❌ Processing failed")
        error_expander.expanded = True  # Auto-expand on error
        
        # Also add to output logs
        log_handler.emit(logging.LogRecord(
            name="streamlit",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg=f"Processing failed: {str(e)}\n{error_trace}",
            args=(),
            exc_info=None
        ))
    finally:
        # Remove log handler
        root_logger.removeHandler(log_handler)

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
    
    if "last_result" not in st.session_state:
        st.info("No results to review. Please process a document first.")
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
        
        if quality_metrics.get("critic"):
            with st.expander("Critic Details"):
                critic_details = quality_metrics["critic"]
                st.json(critic_details)
    
    with col2:
        structural_conf = confidence_scores.get("structural", 0.0)
        st.metric("Structural Confidence", f"{structural_conf:.2%}",
                  help="Based on field coverage and evidence presence")
        
        if quality_metrics.get("structural"):
            with st.expander("Structural Details"):
                structural_details = quality_metrics["structural"]
                st.write(f"**Field Coverage:** {structural_details.get('field_coverage', 0):.2%}")
                st.write(f"**Evidence Coverage:** {structural_details.get('evidence_coverage', 0):.2%}")
                st.write(f"**Package Coverage:** {structural_details.get('package_coverage', 0):.2%}")
    
    with col3:
        validation_conf = confidence_scores.get("validation", 0.0)
        st.metric("Validation Confidence", f"{validation_conf:.2%}",
                  help="Based on schema validation and format compliance")
        
        if quality_metrics.get("validation"):
            with st.expander("Validation Details"):
                validation_details = quality_metrics["validation"]
                st.json(validation_details)
    
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
    
    # Quality metrics details
    if quality_metrics:
        st.markdown("---")
        st.markdown("### Quality Metrics Details")
        
        with st.expander("View All Quality Metrics"):
            st.json(quality_metrics)


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


def about_page():
    import streamlit as st
    st.header("ℹ️ About FAIRifier")
    
    st.markdown("""
    ## What is FAIRifier?
    
    FAIRifier is an agentic framework that automatically generates FAIR (Findable, Accessible, 
    Interoperable, Reusable) metadata from research documents.
    
    ## Features
    
    - 📄 **Document Analysis**: Extracts key information from research papers and proposals
    - 🧠 **Knowledge Enrichment**: Uses FAIR standards and ontologies to enhance metadata
    - 🏷️ **Template Generation**: Creates structured metadata templates (JSON Schema, YAML)
    - 🔗 **RDF Output**: Generates semantic web-compatible RDF graphs and RO-Crate packages
    - ✅ **Validation**: Performs SHACL validation and quality assessment
    - 👥 **Human-in-the-Loop**: Supports human review and editing of results
    
    ## Architecture
    
    FAIRifier uses a multi-agent architecture built on LangGraph:
    
    1. **Document Parser**: Extracts structured information from documents
    2. **Knowledge Retriever**: Enriches with FAIR standards and ontology terms
    3. **Template Generator**: Creates metadata templates
    4. **RDF Builder**: Generates RDF graphs and RO-Crate metadata
    5. **Validator**: Performs quality assessment and validation
    
    ## Supported Standards
    
    - MIxS (Minimum Information about any Sequence)
    - PROV-O (Provenance Ontology)
    - Schema.org
    - RO-Crate (Research Object Crate)
    - SHACL (Shapes Constraint Language)
    """)
    
    st.subheader("🛠️ Configuration")
    st.json({
        "LLM Model": config.llm_model,
        "Min Confidence": config.min_confidence_threshold,
        "Default MIxS Package": config.default_mixs_package,
        "Max Document Size": f"{config.max_document_size_mb}MB"
    })

if __name__ == "__main__":
    main()
