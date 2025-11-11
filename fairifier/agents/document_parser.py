"""Document parsing agent for extracting research information from PDFs and text."""

import logging
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import fitz  # PyMuPDF
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, DocumentInfo
from ..config import config
from ..utils.llm_helper import get_llm_helper
from ..services.mineru_client import MinerUClient, MinerUConversionError


class DocumentParserAgent(BaseAgent):
    """Agent for parsing research documents and extracting key information."""
    
    def __init__(self, use_llm: bool = True):
        super().__init__("DocumentParser")
        self.use_llm = use_llm
        self.logger = logging.getLogger(__name__)
        if use_llm:
            self.llm_helper = get_llm_helper()
        
        self.mineru_client: Optional[MinerUClient] = None
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
                    self.logger.info("MinerU client enabled for DocumentParser.")
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
            if self.use_llm:
                # Get critic feedback if this is a retry
                feedback = self.get_context_feedback(state)
                critic_feedback = feedback.get("critic_feedback")
                
                if critic_feedback:
                    self.log_execution(state, "🔄 Retrying with Critic feedback...")
                    self.log_execution(state, f"   Feedback: {critic_feedback.get('feedback')}")
                
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
                    is_structured_markdown=is_mineru_content
                )
                
                # Remove raw_text if LLM included it (to avoid passing large text to subsequent agents)
                if "raw_text" in doc_info_dict:
                    del doc_info_dict["raw_text"]
                
                # Check if extraction failed (empty or minimal structure)
                # Consider empty if all key fields are missing
                has_title = bool(doc_info_dict.get("title"))
                has_abstract = bool(doc_info_dict.get("abstract"))
                has_authors = bool(doc_info_dict.get("authors")) and len(doc_info_dict.get("authors", [])) > 0
                field_count = len(doc_info_dict)
                
                # Empty if no key fields AND minimal field count (likely fallback structure)
                is_empty = (
                    not has_title and
                    not has_abstract and
                    not has_authors and
                    field_count <= 5  # Only has minimal fields (title, abstract, authors, keywords, research_domain)
                )
                
                if is_empty:
                    # Preserve previous document_info if this is a retry and extraction failed
                    previous_doc_info = state.get("document_info", {})
                    if previous_doc_info and any([
                        previous_doc_info.get("title"),
                        previous_doc_info.get("abstract"),
                        previous_doc_info.get("authors")
                    ]):
                        self.log_execution(
                            state,
                            "⚠️ LLM extraction returned empty result. Preserving previous extraction.",
                            "warning"
                        )
                        # Merge: keep previous data, but update with any new non-empty fields
                        for key, value in doc_info_dict.items():
                            if value and (isinstance(value, str) and value.strip()) or \
                               (isinstance(value, list) and len(value) > 0) or \
                               (not isinstance(value, (str, list)) and value):
                                previous_doc_info[key] = value
                        doc_info_dict = previous_doc_info
                    else:
                        self.log_execution(
                            state,
                            "⚠️ LLM extraction returned empty result and no previous data available.",
                            "warning"
                        )
                
                self.log_execution(state, f"✅ LLM extracted: {list(doc_info_dict.keys())}")
                
                # Store in state directly as dict (without raw_text - it's already in document_content)
                state["document_info"] = doc_info_dict
                # Note: raw_text is NOT included in document_info to avoid passing large text to subsequent agents
                # The full text is available in state["document_content"] if needed
                
                # Calculate confidence
                confidence = self._calculate_llm_confidence(doc_info_dict)
                
            else:
                # Fallback to regex-based extraction
                self.log_execution(state, "⚠️  Using regex-based extraction (no LLM)")
                doc_info = self._extract_document_info(text)
                state["document_info"] = {
                    "title": doc_info.title,
                    "abstract": doc_info.abstract,
                    "authors": doc_info.authors,
                    "keywords": doc_info.keywords,
                    "research_domain": doc_info.research_domain,
                    "methodology": doc_info.methodology,
                    "datasets_mentioned": doc_info.datasets_mentioned,
                    "instruments": doc_info.instruments,
                    "variables": doc_info.variables
                    # Note: raw_text is NOT included - it's already in state["document_content"]
                }
                confidence = self._calculate_parsing_confidence(doc_info)
            
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
            if self.mineru_client:
                try:
                    conversion = self.mineru_client.convert_document(document_path)
                    conversion_info = conversion.to_dict()
                    self.log_execution(
                        state,
                        f"🪄 MinerU converted PDF to Markdown at {conversion.markdown_path}"
                    )
                    return conversion.markdown_text, conversion_info, "mineru"
                except MinerUConversionError as exc:
                    warning_msg = f"MinerU conversion failed: {exc}. Falling back to local PDF extraction."
                    self.log_execution(state, f"⚠️ {warning_msg}", "warning")
                    self.logger.warning(warning_msg)
            text = self._extract_pdf_text(document_path)
            return text, conversion_info, "pdf_text"
        
        with open(document_path, 'r', encoding='utf-8') as file:
            text = file.read()
        return text, conversion_info, "text_file"
    
    def _extract_document_info(self, text: str) -> DocumentInfo:
        """Extract structured information from document text using patterns and heuristics."""
        doc_info = DocumentInfo(raw_text=text)
        
        # Extract title (usually first line or after "Title:")
        title_patterns = [
            r'^(.+?)(?:\n|$)',  # First line
            r'[Tt]itle[:\s]*(.+?)(?:\n|$)',
            r'^([A-Z][^.!?]*[.!?])\s*\n'
        ]
        
        for pattern in title_patterns:
            match = re.search(pattern, text.strip(), re.MULTILINE)
            if match and len(match.group(1).strip()) > 10:
                doc_info.title = match.group(1).strip()
                break
        
        # Extract abstract
        abstract_patterns = [
            r'[Aa]bstract[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Ss]ummary[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)'
        ]
        
        for pattern in abstract_patterns:
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                doc_info.abstract = match.group(1).strip()
                break
        
        # Extract authors (simple pattern matching)
        author_patterns = [
            r'[Aa]uthors?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Bb]y[:\s]+(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)'
        ]
        
        for pattern in author_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                authors_text = match.group(1).strip()
                # Split by common separators
                authors = re.split(r'[,;]\s*|\s+and\s+', authors_text)
                doc_info.authors = [a.strip() for a in authors if a.strip()]
                break
        
        # Extract keywords
        keywords_patterns = [
            r'[Kk]eywords?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Tt]ags?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)'
        ]
        
        for pattern in keywords_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                keywords_text = match.group(1).strip()
                keywords = re.split(r'[,;]\s*', keywords_text)
                doc_info.keywords = [k.strip() for k in keywords if k.strip()]
                break
        
        # Identify research domain based on keywords and content
        doc_info.research_domain = self._identify_research_domain(text)
        
        # Extract methodology mentions
        doc_info.methodology = self._extract_methodology(text)
        
        # Extract dataset mentions
        doc_info.datasets_mentioned = self._extract_datasets(text)
        
        # Extract instruments
        doc_info.instruments = self._extract_instruments(text)
        
        # Extract variables
        doc_info.variables = self._extract_variables(text)
        
        return doc_info
    
    def _identify_research_domain(self, text: str) -> Optional[str]:
        """Identify research domain based on content analysis."""
        domain_keywords = {
            "genomics": ["genome", "genomic", "sequencing", "DNA", "RNA", "gene"],
            "metagenomics": ["metagenome", "metagenomic", "microbiome", "16S", "amplicon"],
            "proteomics": ["protein", "proteome", "proteomic", "mass spectrometry"],
            "metabolomics": ["metabolome", "metabolomic", "metabolite", "LC-MS"],
            "ecology": ["ecosystem", "biodiversity", "species", "environmental"],
            "marine_biology": ["marine", "ocean", "sea", "coastal", "aquatic"],
            "microbiology": ["bacteria", "microbial", "microorganism", "culture"]
        }
        
        text_lower = text.lower()
        domain_scores = {}
        
        for domain, keywords in domain_keywords.items():
            score = sum(text_lower.count(keyword) for keyword in keywords)
            if score > 0:
                domain_scores[domain] = score
        
        if domain_scores:
            return max(domain_scores, key=domain_scores.get)
        return None
    
    def _extract_methodology(self, text: str) -> Optional[str]:
        """Extract methodology information."""
        method_patterns = [
            r'[Mm]ethods?[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Mm]ethodology[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Aa]pproach[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)'
        ]
        
        for pattern in method_patterns:
            match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if match:
                return match.group(1).strip()[:500]  # Limit length
        return None
    
    def _extract_datasets(self, text: str) -> List[str]:
        """Extract dataset mentions."""
        dataset_patterns = [
            r'dataset[s]?\s+([A-Z][A-Za-z0-9\-_]+)',
            r'database[s]?\s+([A-Z][A-Za-z0-9\-_]+)',
            r'([A-Z]{2,}[-_]?[0-9]+)',  # Common dataset ID patterns
        ]
        
        datasets = set()
        for pattern in dataset_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            datasets.update(matches)
        
        return list(datasets)[:10]  # Limit results
    
    def _extract_instruments(self, text: str) -> List[str]:
        """Extract scientific instruments mentioned."""
        instrument_keywords = [
            "Illumina", "PacBio", "Oxford Nanopore", "Ion Torrent",
            "mass spectrometer", "LC-MS", "GC-MS", "NMR",
            "microscope", "sequencer", "PCR", "qPCR",
            "flow cytometer", "spectrophotometer"
        ]
        
        instruments = []
        text_lower = text.lower()
        
        for instrument in instrument_keywords:
            if instrument.lower() in text_lower:
                instruments.append(instrument)
        
        return instruments
    
    def _extract_variables(self, text: str) -> List[str]:
        """Extract measured variables."""
        variable_patterns = [
            r'temperature', r'pH', r'salinity', r'depth', r'pressure',
            r'concentration', r'abundance', r'diversity', r'richness',
            r'biomass', r'coverage', r'expression'
        ]
        
        variables = []
        text_lower = text.lower()
        
        for var_pattern in variable_patterns:
            if re.search(var_pattern, text_lower):
                variables.append(var_pattern)
        
        return variables
    
    def _calculate_parsing_confidence(self, doc_info: DocumentInfo) -> float:
        """Calculate confidence score for document parsing."""
        score = 0.0
        
        # Title extraction
        if doc_info.title and len(doc_info.title) > 10:
            score += 0.3
        
        # Abstract extraction  
        if doc_info.abstract and len(doc_info.abstract) > 50:
            score += 0.3
        
        # Authors extraction
        if doc_info.authors:
            score += 0.2
        
        # Keywords extraction
        if doc_info.keywords:
            score += 0.1
        
        # Research domain identification
        if doc_info.research_domain:
            score += 0.1
        
        return min(score, 1.0)
    
    def _calculate_llm_confidence(self, doc_info_dict: Dict[str, Any]) -> float:
        """Calculate confidence score for LLM-based parsing."""
        score = 0.0
        
        # Core fields (higher weight)
        if doc_info_dict.get('title') and len(str(doc_info_dict['title'])) > 10:
            score += 0.25
        if doc_info_dict.get('abstract') and len(str(doc_info_dict['abstract'])) > 50:
            score += 0.25
        if doc_info_dict.get('authors') and len(doc_info_dict['authors']) > 0:
            score += 0.15
        
        # Additional extracted fields (bonus)
        if doc_info_dict.get('keywords'):
            score += 0.10
        if doc_info_dict.get('research_domain'):
            score += 0.10
        if doc_info_dict.get('location') or doc_info_dict.get('coordinates'):
            score += 0.10
        if doc_info_dict.get('environmental_parameters'):
            score += 0.05
        
        return min(score, 1.0)
