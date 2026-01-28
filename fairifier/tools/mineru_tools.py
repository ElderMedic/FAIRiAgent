"""LangChain tools for MinerU document conversion."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@dataclass
class MinerUToolResult:
    """Structured result from MinerU conversion tool."""
    success: bool
    markdown_text: Optional[str] = None
    markdown_path: Optional[str] = None
    output_dir: Optional[str] = None
    images_dir: Optional[str] = None
    method: str = "mineru"
    error: Optional[str] = None


def create_mineru_convert_tool(client=None):
    """Create MinerU document conversion tool.
    
    Args:
        client: Optional MinerUClient instance. If None, tool will
                create client from config when invoked.
    
    Returns:
        LangChain tool for MinerU document conversion.
    """
    from ..services.mineru_client import MinerUClient, MinerUConversionError
    from ..config import config
    
    # Create client if not provided
    if client is None:
        if config.mineru_enabled and config.mineru_server_url:
            try:
                client = MinerUClient(
                    cli_path=config.mineru_cli_path,
                    server_url=config.mineru_server_url,
                    backend=config.mineru_backend,
                    timeout_seconds=config.mineru_timeout_seconds,
                )
                if not client.is_available():
                    logger.warning("MinerU CLI not available")
                    client = None
            except Exception as exc:
                logger.warning("Failed to create MinerU client: %s", exc)
                client = None
        else:
            logger.debug("MinerU not enabled in config")
            client = None
    
    # Closure variable for tool to access client
    _client = client
    
    @tool
    def convert_document(input_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Convert a document (PDF) to Markdown using MinerU.
        
        Uses MinerU's VLM-based extraction for better structure preservation
        compared to basic PDF text extraction. Falls back gracefully if conversion fails.
        
        Args:
            input_path: Path to the source document (e.g., PDF file)
            output_dir: Optional directory to store MinerU artifacts.
                       If None, a temporary directory is created.
        
        Returns:
            Dictionary with conversion result:
            {
                "success": bool,
                "markdown_text": str or None,
                "markdown_path": str or None,
                "output_dir": str or None,
                "images_dir": str or None,
                "method": "mineru",
                "error": str or None
            }
            
            If success=False, caller should fallback to PyMuPDF or other methods.
        """
        if _client is None:
            return {
                "success": False,
                "markdown_text": None,
                "markdown_path": None,
                "output_dir": None,
                "images_dir": None,
                "method": "mineru",
                "error": "MinerU client not available or not enabled"
            }
        
        try:
            # Convert path to Path object for output_dir if provided
            output_path = Path(output_dir) if output_dir else None
            
            # Call MinerU conversion
            result = _client.convert_document(
                input_path=input_path,
                output_dir=output_path
            )
            
            # Build response from MinerUConversionResult
            return {
                "success": True,
                "markdown_text": result.markdown_text,
                "markdown_path": str(result.markdown_path),
                "output_dir": str(result.output_dir),
                "images_dir": str(result.images_dir) if result.images_dir else None,
                "method": "mineru",
                "error": None
            }
            
        except MinerUConversionError as exc:
            logger.warning("MinerU conversion failed for %s: %s", input_path, exc)
            return {
                "success": False,
                "markdown_text": None,
                "markdown_path": None,
                "output_dir": None,
                "images_dir": None,
                "method": "mineru",
                "error": f"Conversion failed: {str(exc)}"
            }
        except Exception as exc:
            logger.error("Unexpected error in MinerU conversion: %s", exc)
            return {
                "success": False,
                "markdown_text": None,
                "markdown_path": None,
                "output_dir": None,
                "images_dir": None,
                "method": "mineru",
                "error": f"Unexpected error: {str(exc)}"
            }
    
    return convert_document
