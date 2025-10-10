"""Document parsing agent for extracting research information from PDFs and text."""

import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import fitz  # PyMuPDF

from .base import BaseAgent
from ..models import FAIRifierState, DocumentInfo
from ..config import config


class DocumentParserAgent(BaseAgent):
    """Agent for parsing research documents and extracting key information."""
    
    def __init__(self):
        super().__init__("DocumentParser")
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document and extract research information."""
        self.log_execution(state, "Starting document parsing")
        
        try:
            # Extract text from document
            if state["document_path"].endswith('.pdf'):
                text = self._extract_pdf_text(state["document_path"])
            else:
                # Assume plain text
                with open(state["document_path"], 'r', encoding='utf-8') as f:
                    text = f.read()
            
            state["document_content"] = text
            
            # Extract structured information
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
                "variables": doc_info.variables,
                "raw_text": doc_info.raw_text
            }
            
            # Calculate confidence based on extraction quality
            confidence = self._calculate_parsing_confidence(doc_info)
            self.update_confidence(state, "document_parsing", confidence)
            
            self.log_execution(
                state, 
                f"Document parsing completed. Extracted: title={bool(doc_info.title)}, "
                f"abstract={bool(doc_info.abstract)}, authors={len(doc_info.authors)}, "
                f"confidence={confidence:.2f}"
            )
            
        except Exception as e:
            self.log_execution(state, f"Document parsing failed: {str(e)}", "error")
            self.update_confidence(state, "document_parsing", 0.0)
        
        return state
    
    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(pdf_path)
        text = ""
        
        for page in doc:
            text += page.get_text()
        
        doc.close()
        return text
    
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
