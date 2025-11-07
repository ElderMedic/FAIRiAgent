"""
LangGraph Studio Development Server Entry Point

This file is used by `langgraph dev` to start the LangGraph Studio server.
It exposes the compiled graph and checkpointer for local development.

Usage:
    langgraph dev

The graph will be available at http://localhost:2024
LangGraph Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
"""

import os
import logging
from pathlib import Path

# Ensure LangSmith tracing is enabled
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = os.getenv(
    "LANGCHAIN_PROJECT", 
    "fairifier-studio"
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the LangGraph app
# Use absolute import to avoid issues with langgraph dev
try:
    from .langgraph_app import FAIRifierLangGraphApp
except ImportError:
    # Fallback to absolute import if relative import fails
    from fairifier.graph.langgraph_app import FAIRifierLangGraphApp

# Create the app instance
app = FAIRifierLangGraphApp()

# Expose the compiled graph for LangGraph Studio
# Note: LangGraph API handles persistence automatically, so we use a graph without checkpointer
graph = app.get_graph_without_checkpointer()

logger.info("✅ LangGraph Studio entry point loaded")
logger.info(f"   LangSmith project: {os.getenv('LANGCHAIN_PROJECT', 'fairifier-studio')}")
logger.info("   Graph is ready for LangGraph Studio (persistence handled by API)")

