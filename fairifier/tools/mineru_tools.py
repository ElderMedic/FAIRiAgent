"""LangChain tools for MinerU document conversion."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.tools import tool

from ..services.mineru_client import (
    MinerUClient,
    MinerUConversionError,
    mineru_client_from_config,
    mineru_runtime_enabled,
    structured_output_metadata,
)

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


def _result_payload(result) -> Dict[str, Any]:
    """Build tool response dict from :class:`MinerUConversionResult`."""
    payload = {
        "success": True,
        "markdown_text": result.markdown_text,
        "markdown_path": str(result.markdown_path),
        "output_dir": str(result.output_dir),
        "images_dir": str(result.images_dir) if result.images_dir else None,
        "method": "mineru",
        "error": None,
    }
    payload.update(structured_output_metadata(result))
    return payload


def create_mineru_convert_tool(client=None):
    """Create MinerU document conversion tool."""
    from ..config import config

    if client is None:
        if mineru_runtime_enabled(
            enabled=config.mineru_enabled,
            backend=config.mineru_backend,
            server_url=config.mineru_server_url,
        ):
            try:
                client = mineru_client_from_config(config)
                if not client.is_available():
                    logger.warning("MinerU CLI not available")
                    client = None
            except Exception as exc:
                logger.warning("Failed to create MinerU client: %s", exc)
                client = None
        else:
            logger.debug("MinerU not enabled in config")
            client = None

    _client = client

    @tool
    def convert_document(
        input_path: str, output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Convert a document (PDF, DOCX, PPTX, XLSX) to Markdown using MinerU.

        Returns success=False on failure so callers can fall back to PyMuPDF.
        """
        if _client is None:
            return {
                "success": False,
                "markdown_text": None,
                "markdown_path": None,
                "output_dir": None,
                "images_dir": None,
                "method": "mineru",
                "error": "MinerU client not available or not enabled",
            }

        try:
            output_path = Path(output_dir) if output_dir else None
            result = _client.convert_document(
                input_path=input_path,
                output_dir=output_path,
            )
            return _result_payload(result)

        except MinerUConversionError as exc:
            logger.warning("MinerU conversion failed for %s: %s", input_path, exc)
            return {
                "success": False,
                "markdown_text": None,
                "markdown_path": None,
                "output_dir": None,
                "images_dir": None,
                "method": "mineru",
                "error": f"Conversion failed: {str(exc)}",
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
                "error": f"Unexpected error: {str(exc)}",
            }

    return convert_document
