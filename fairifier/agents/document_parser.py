"""Document parsing agent for extracting research information from PDFs and text."""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import fitz  # PyMuPDF
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState
from ..config import config
from ..utils.llm_helper import get_llm_helper
from ..services.mineru_client import MinerUClient, MinerUConversionError
from ..tools.mineru_tools import create_mineru_convert_tool


class DocumentParserAgent(BaseAgent):
    """Agent for parsing research documents and extracting key information."""
    
    def __init__(self):
        super().__init__("DocumentParser")
        self.logger = logging.getLogger(__name__)
        self.llm_helper = get_llm_helper()
        
        self.mineru_client: Optional[MinerUClient] = None
        self.mineru_tool = None
        if config.mineru_enabled and config.mineru_server_url:
            try:
                candidate = MinerUClient(
                    cli_path=config.mineru_cli_path,
                    server_url=config.mineru_server_url,
                    backend=config.mineru_backend,
                    timeout_seconds=config.mineru_timeout_seconds,
                )
                if candidate.is_available():
                    self.mineru_client = candidate
                    # Create MinerU tool for LangChain integration
                    self.mineru_tool = create_mineru_convert_tool(client=candidate)
                    self.logger.info("MinerU tool enabled for DocumentParser.")
                else:
                    self.logger.warning(
                        "MinerU CLI not available or misconfigured. Falling back to PyMuPDF."
                    )
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Failed to initialize MinerU client: %s", exc)
                self.mineru_client = None
        
    @traceable(name="DocumentParser", tags=["agent", "parsing"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document and extract research information."""
        self.log_execution(state, "📄 Starting document parsing")
        
        try:
            # Extract text from document
            document_path = state.get("document_path", "")
            text = state.get("document_content", "")
            if "document_conversion" not in state or not isinstance(state["document_conversion"], dict):
                state["document_conversion"] = {}
            
            if text:
                self.log_execution(
                    state,
                    f"📄 Using existing document content from state ({len(text)} characters)"
                )
            else:
                self.log_execution(state, f"📖 Reading document: {document_path}")
                text, conversion_info, source = self._load_document_content(document_path, state)
                state["document_content"] = text
                if conversion_info:
                    state["document_conversion"] = conversion_info
                source_label = "MinerU Markdown" if source == "mineru" else "PDF text extraction" if source == "pdf_text" else "text file"
                self.log_execution(
                    state,
                    f"✅ Loaded {len(text)} characters ({source_label})"
                )
            
            # Extract structured information using LLM
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            
            if critic_feedback:
                self.log_execution(state, "🔄 Retrying with Critic feedback...")
                critique = critic_feedback.get("critique")
                if critique:
                    self.log_execution(state, f"   Critique: {critique}")
                for idx, suggestion in enumerate(critic_feedback.get("suggestions", []), 1):
                    self.log_execution(state, f"   🔧 Suggestion {idx}: {suggestion}")
            if guidance_history:
                self.log_execution(state, f"🧾 Historical guidance: {guidance_history}")
            
            if planner_instruction:
                self.log_execution(state, f"🧭 Planner guidance: {planner_instruction}")
            
            # Detect if we have MinerU-converted content (Markdown with better structure)
            conversion_info = state.get("document_conversion", {})
            is_mineru_content = bool(conversion_info.get("markdown_path"))
            
            if is_mineru_content:
                self.log_execution(
                    state, 
                    "🪄 Using LLM with optimized prompting for MinerU Markdown (enhanced structure extraction)..."
                )
            else:
                self.log_execution(state, "🤖 Using LLM for intelligent, adaptive extraction...")
            
            doc_info_dict = await self.llm_helper.extract_document_info(
                text, 
                critic_feedback,
                is_structured_markdown=is_mineru_content,
                planner_instruction=planner_instruction
            )
            
            # Remove raw_text if LLM included it (to avoid passing large text to subsequent agents)
            if "raw_text" in doc_info_dict:
                del doc_info_dict["raw_text"]
            
            # Check if extraction actually returned meaningful content
            # Count non-empty fields (flexible - works for any document type)
            non_empty_fields = sum(
                1 for v in doc_info_dict.values()
                if v and (
                    (isinstance(v, str) and v.strip()) or
                    (isinstance(v, (list, dict)) and len(v) > 0) or
                    (not isinstance(v, (str, list, dict)))
                )
            )
            
            # Only consider extraction failed if we got almost nothing
            is_truly_empty = non_empty_fields < 3
            
            if is_truly_empty:
                # Preserve previous document_info if this is a retry and extraction failed
                previous_doc_info = state.get("document_info", {})
                if previous_doc_info and len(previous_doc_info) > 3:
                    self.log_execution(
                        state,
                        f"⚠️ LLM extraction returned minimal result ({non_empty_fields} fields). Preserving previous extraction.",
                        "warning"
                    )
                    # Merge new fields into previous extraction
                    for key, value in doc_info_dict.items():
                        if value and (
                            (isinstance(value, str) and value.strip()) or
                            (isinstance(value, list) and len(value) > 0) or
                            (isinstance(value, dict) and len(value) > 0) or
                            (not isinstance(value, (str, list, dict)))
                        ):
                            previous_doc_info[key] = value
                    doc_info_dict = previous_doc_info
                else:
                    self.log_execution(
                        state,
                        f"⚠️ LLM extraction returned minimal result ({non_empty_fields} fields) and no previous data available.",
                        "warning"
                    )
            
            self.log_execution(state, f"✅ LLM extracted: {list(doc_info_dict.keys())}")
            self.log_execution(state, f"📊 Extracted {len(doc_info_dict)} top-level fields")
            
            # Debug: Log first few fields to verify content
            if doc_info_dict:
                sample_fields = list(doc_info_dict.items())[:3]
                for key, value in sample_fields:
                    value_preview = str(value)[:100] if value else "None"
                    self.log_execution(state, f"   - {key}: {value_preview}...")
            
            # Store in state directly as dict (without raw_text - it's already in document_content)
            state["document_info"] = doc_info_dict
            self.log_execution(state, f"✅ Stored document_info in state with {len(state['document_info'])} fields")
            confidence = self._calculate_llm_confidence(doc_info_dict)
            
            self.update_confidence(state, "document_parsing", confidence)
            
            # Log extracted info
            doc_info = state["document_info"]
            authors = doc_info.get('authors', [])
            keywords = doc_info.get('keywords', [])
            self.log_execution(
                state, 
                f"✅ Parsing completed!\n"
                f"   - Title: {bool(doc_info.get('title'))}\n"
                f"   - Abstract: {bool(doc_info.get('abstract'))}\n"
                f"   - Authors: {len(authors) if authors else 0}\n"
                f"   - Keywords: {len(keywords) if keywords else 0}\n"
                f"   - Location: {doc_info.get('location', 'N/A')}\n"
                f"   - Coordinates: {doc_info.get('coordinates', 'N/A')}\n"
                f"   - Confidence: {confidence:.2%}"
            )
            
        except Exception as e:
            self.log_execution(state, f"❌ Document parsing failed: {str(e)}", "error")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Document parsing error: {str(e)}")
            self.update_confidence(state, "document_parsing", 0.0)
            # Ensure document_info exists even on error
            if "document_info" not in state:
                state["document_info"] = {"title": "Unknown", "abstract": "", "authors": [], "keywords": []}
        
        return state
    
    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(pdf_path)
        text = ""
        
        for page in doc:
            text += page.get_text()
        
        doc.close()
        return text
    
    def _load_document_content(
        self, document_path: str, state: FAIRifierState
    ) -> Tuple[str, Dict[str, Any], str]:
        """
        Load document content, preferring MinerU conversion when available.
        
        Returns:
            tuple of (text, conversion_info, source) where source is one of
            {"mineru", "pdf_text", "text_file"}.
        """
        conversion_info: Dict[str, Any] = {}
        if document_path.endswith('.pdf'):
            if self.mineru_tool:
                # Use MinerU tool for conversion
                result = self.mineru_tool.invoke({
                    "input_path": document_path,
                    "output_dir": None
                })
                
                if result["success"]:
                    # Conversion successful
                    conversion_info = {
                        "markdown_path": result["markdown_path"],
                        "output_dir": result["output_dir"],
                        "images_dir": result["images_dir"],
                        "method": result["method"]
                    }
                    self.log_execution(
                        state,
                        f"🪄 MinerU converted PDF to Markdown at {result['markdown_path']}"
                    )
                    return result["markdown_text"], conversion_info, "mineru"
                else:
                    # Conversion failed, log and fallback
                    warning_msg = f"MinerU conversion failed: {result['error']}. Falling back to local PDF extraction."
                    self.log_execution(state, f"⚠️ {warning_msg}", "warning")
                    self.logger.warning(warning_msg)
            
            text = self._extract_pdf_text(document_path)
            return text, conversion_info, "pdf_text"
        
        with open(document_path, 'r', encoding='utf-8') as file:
            text = file.read()
        return text, conversion_info, "text_file"
    
    
    def _calculate_llm_confidence(self, doc_info_dict: Dict[str, Any]) -> float:
        """Calculate confidence score for LLM-based parsing.
        
        This is a flexible heuristic based on content richness, not tied to specific fields.
        The Critic will provide a more comprehensive quality assessment.
        """
        if not doc_info_dict:
            return 0.0
        
        # Count non-empty fields at all levels
        def count_content(obj, depth=0, max_depth=3):
            """Recursively count meaningful content."""
            if depth > max_depth:
                return 0
            
            count = 0
            if isinstance(obj, dict):
                for v in obj.values():
                    if v:
                        if isinstance(v, str) and len(v.strip()) > 5:
                            count += 1
                        elif isinstance(v, (list, dict)) and len(v) > 0:
                            count += 1 + count_content(v, depth + 1, max_depth)
                        elif not isinstance(v, (str, list, dict)):
                            count += 1
            elif isinstance(obj, list):
                for item in obj:
                    if item:
                        count += count_content(item, depth + 1, max_depth)
            return count
        
        total_content = count_content(doc_info_dict)
        
        # Score based on content richness (flexible for any document type)
        if total_content >= 50:
            return 1.0
        elif total_content >= 30:
            return 0.9
        elif total_content >= 20:
            return 0.8
        elif total_content >= 10:
            return 0.6
        elif total_content >= 5:
            return 0.4
        elif total_content >= 3:
            return 0.3
        else:
            return 0.1
