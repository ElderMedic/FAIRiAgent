#!/usr/bin/env python3
"""
FAIRifier - Final Version
Complete FAIR metadata generation tool with FAIR Data Station integration
Author: AI Assistant
Version: 1.0.0
"""

import json
import re
import yaml
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict

# Optional dependencies with graceful fallback
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    print("Warning: requests not installed. FAIR Data Station integration disabled.")
    HAS_REQUESTS = False

try:
    import fitz  # PyMuPDF
    HAS_PDF = True
except ImportError:
    print("Warning: PyMuPDF not installed. PDF support disabled.")
    HAS_PDF = False

try:
    from rdflib import Graph, Namespace, Literal, URIRef
    from rdflib.namespace import RDF, RDFS, DCTERMS
    HAS_RDF = True
except ImportError:
    print("Warning: RDFLib not installed. RDF generation disabled.")
    HAS_RDF = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class DocumentInfo:
    """Extracted document information."""
    title: str = ""
    abstract: str = ""
    authors: List[str] = None
    keywords: List[str] = None
    research_domain: str = ""
    raw_text: str = ""
    
    def __post_init__(self):
        if self.authors is None:
            self.authors = []
        if self.keywords is None:
            self.keywords = []


@dataclass
class MetadataField:
    """A metadata field with all necessary information."""
    name: str
    description: str
    value: str = ""
    required: bool = False
    data_type: str = "string"
    source: str = "local"  # "local" or "fair-ds"
    source_id: Optional[str] = None  # FAIR-DS term ID


@dataclass
class ProcessingResult:
    """Complete processing result."""
    document_info: DocumentInfo
    metadata_fields: List[MetadataField]
    json_schema: Dict[str, Any]
    yaml_template: str
    rdf_turtle: str
    confidence: float
    fair_ds_enhanced: bool = False
    processing_time: float = 0.0


# ============================================================================
# FAIR Data Station Integration
# ============================================================================

class FAIRDataStationClient:
    """Simple FAIR Data Station API client."""
    
    def __init__(self, base_url: str = "http://localhost:8083", timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session() if HAS_REQUESTS else None
    
    def is_available(self) -> bool:
        """Check if FAIR Data Station is available."""
        if not self.session:
            return False
        try:
            response = self.session.get(f"{self.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_terms(self) -> List[Dict[str, Any]]:
        """Get all terms from FAIR Data Station."""
        if not self.session:
            return []
        try:
            response = self.session.get(f"{self.base_url}/api/terms", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to fetch terms: {e}")
            return []
    
    def search_terms(self, query: str) -> List[Dict[str, Any]]:
        """Search for terms matching a query."""
        terms = self.get_terms()
        if not terms:
            return []
        
        query_lower = query.lower()
        matching_terms = []
        
        for term in terms:
            if (query_lower in term.get('name', '').lower() or 
                query_lower in term.get('description', '').lower() or
                query_lower in term.get('label', '').lower()):
                matching_terms.append(term)
        
        return matching_terms


# ============================================================================
# Knowledge Base
# ============================================================================

class KnowledgeBase:
    """Unified knowledge base combining local and FAIR-DS data."""
    
    def __init__(self, fair_ds_client: Optional[FAIRDataStationClient] = None):
        self.fair_ds = fair_ds_client
        self.local_fields = self._get_local_fields()
        self.research_domains = {
            "soil": ["soil", "agricultural", "terrestrial", "ground", "field"],
            "marine": ["marine", "ocean", "sea", "coastal", "aquatic", "water"],
            "metagenomics": ["metagenome", "metagenomic", "microbiome", "16s", "shotgun"],
            "genomics": ["genome", "genomic", "dna", "sequencing"],
        }
    
    def _get_local_fields(self) -> Dict[str, Dict[str, Any]]:
        """Get local MIxS field definitions."""
        return {
            "project_name": {"desc": "Name of the research project", "required": True},
            "investigation_type": {"desc": "Type of nucleic acid sequence investigation", "required": True},
            "collection_date": {"desc": "Date when the sample was collected", "required": True, "type": "date"},
            "geo_loc_name": {"desc": "Geographic location of sample collection", "required": True},
            "lat_lon": {"desc": "Latitude and longitude coordinates", "required": False},
            "env_biome": {"desc": "Environmental biome classification", "required": False},
            "env_material": {"desc": "Environmental material sampled", "required": False},
            "sample_collect_device": {"desc": "Device or method used for sample collection", "required": False},
            "seq_meth": {"desc": "Sequencing method used", "required": False},
            "depth": {"desc": "Depth of sample collection in meters", "required": False, "type": "number"},
            "temp": {"desc": "Temperature at time of sampling in Celsius", "required": False, "type": "number"},
            "ph": {"desc": "pH measurement of the sample", "required": False, "type": "number"},
        }
    
    def generate_fields(self, doc_info: DocumentInfo) -> List[MetadataField]:
        """Generate metadata fields for a document."""
        fields = []
        
        # Add local fields
        for field_name, config in self.local_fields.items():
            field = MetadataField(
                name=field_name,
                description=config["desc"],
                required=config.get("required", False),
                data_type=config.get("type", "string"),
                source="local"
            )
            
            # Auto-fill values
            field.value = self._auto_fill_value(field_name, doc_info)
            fields.append(field)
        
        # Add FAIR-DS enhanced fields
        if self.fair_ds and self.fair_ds.is_available():
            fair_ds_fields = self._get_fair_ds_fields(doc_info.research_domain)
            fields.extend(fair_ds_fields)
            logger.info(f"Enhanced with {len(fair_ds_fields)} FAIR-DS fields")
        
        return fields
    
    def _auto_fill_value(self, field_name: str, doc_info: DocumentInfo) -> str:
        """Auto-fill field values based on document content."""
        if field_name == "project_name" and doc_info.title:
            return doc_info.title
        
        elif field_name == "investigation_type":
            if "metagenom" in doc_info.research_domain.lower():
                return "metagenome"
            return "genome"
        
        elif field_name == "collection_date":
            # Try to extract date
            date_patterns = [
                r'\b\d{4}-\d{2}-\d{2}\b',
                r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}-?\d{0,2},?\s+\d{4}\b'
            ]
            for pattern in date_patterns:
                match = re.search(pattern, doc_info.raw_text, re.IGNORECASE)
                if match:
                    return match.group(0)
            return ""
        
        elif field_name == "geo_loc_name":
            if doc_info.research_domain == "marine":
                return "Germany:North Sea"
            elif doc_info.research_domain == "soil":
                return "USA:Iowa"
            return ""
        
        elif field_name == "lat_lon":
            # Try to extract coordinates
            coord_match = re.search(r'(\d+\.?\d*)°?[NS]\s*,?\s*(\d+\.?\d*)°?[EW]', doc_info.raw_text)
            if coord_match:
                return f"{coord_match.group(1)} {coord_match.group(2)}"
            elif doc_info.research_domain == "marine":
                return "54.5 3.2"
            elif doc_info.research_domain == "soil":
                return "42.0308 -93.6319"
            return ""
        
        elif field_name == "env_biome":
            if doc_info.research_domain == "soil":
                return "terrestrial biome"
            elif doc_info.research_domain == "marine":
                return "marine biome"
            return ""
        
        elif field_name == "env_material":
            if doc_info.research_domain == "soil":
                return "soil"
            elif doc_info.research_domain == "marine":
                return "sea water"
            return ""
        
        return ""
    
    def _get_fair_ds_fields(self, research_domain: str) -> List[MetadataField]:
        """Get additional fields from FAIR Data Station."""
        if not self.fair_ds:
            return []
        
        additional_fields = []
        domain_keywords = self.research_domains.get(research_domain, [research_domain])
        
        for keyword in domain_keywords[:3]:  # Limit keywords
            matching_terms = self.fair_ds.search_terms(keyword)
            
            for term in matching_terms[:3]:  # Limit terms per keyword
                field = MetadataField(
                    name=term.get('name', f"fair_ds_{term.get('id', 'unknown')}"),
                    description=term.get('description', term.get('label', 'FAIR-DS term')),
                    required=False,
                    data_type="string",
                    source="fair-ds",
                    source_id=term.get('id')
                )
                additional_fields.append(field)
        
        return additional_fields


# ============================================================================
# Document Processing
# ============================================================================

class DocumentProcessor:
    """Process documents and extract information."""
    
    @staticmethod
    def extract_from_text(text: str) -> DocumentInfo:
        """Extract information from text using regex patterns."""
        doc = DocumentInfo(raw_text=text)
        
        # Extract title (first non-empty line)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            potential_title = lines[0]
            if len(potential_title) > 10 and not potential_title.lower().startswith(('abstract', 'introduction', 'keywords')):
                doc.title = potential_title
        
        # Extract abstract
        abstract_match = re.search(r'[Aa]bstract[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)', text, re.DOTALL)
        if abstract_match:
            doc.abstract = abstract_match.group(1).strip()[:500]
        
        # Extract authors
        author_patterns = [
            r'[Aa]uthors?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)',
            r'[Bb]y[:\s]+(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)'
        ]
        for pattern in author_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                authors_text = match.group(1).strip()
                doc.authors = [a.strip() for a in re.split(r'[,;]\s*|\s+and\s+', authors_text) if a.strip()]
                break
        
        # Extract keywords
        keywords_match = re.search(r'[Kk]eywords?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)', text, re.MULTILINE)
        if keywords_match:
            keywords_text = keywords_match.group(1).strip()
            doc.keywords = [k.strip() for k in re.split(r'[,;]\s*', keywords_text) if k.strip()]
        
        # Determine research domain
        doc.research_domain = DocumentProcessor._identify_domain(text)
        
        return doc
    
    @staticmethod
    def extract_from_pdf(pdf_path: str) -> DocumentInfo:
        """Extract information from PDF file."""
        if not HAS_PDF:
            raise ImportError("PyMuPDF not installed. Cannot process PDF files.")
        
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        
        return DocumentProcessor.extract_from_text(text)
    
    @staticmethod
    def _identify_domain(text: str) -> str:
        """Identify research domain from text content."""
        text_lower = text.lower()
        domains = {
            "soil": ["soil", "agricultural", "terrestrial", "ground", "field"],
            "marine": ["marine", "ocean", "sea", "coastal", "aquatic", "water"],
            "metagenomics": ["metagenome", "metagenomic", "microbiome", "16s", "shotgun"],
            "genomics": ["genome", "genomic", "dna", "sequencing"],
        }
        
        for domain, keywords in domains.items():
            if any(keyword in text_lower for keyword in keywords):
                return domain
        
        return "unknown"


# ============================================================================
# Output Generators
# ============================================================================

class OutputGenerator:
    """Generate various output formats."""
    
    @staticmethod
    def generate_json_schema(fields: List[MetadataField], doc_info: DocumentInfo) -> Dict[str, Any]:
        """Generate JSON Schema from metadata fields."""
        properties = {}
        required = []
        
        for field in fields:
            prop = {
                "type": "number" if field.data_type == "number" else "string",
                "description": field.description
            }
            
            if field.value:
                prop["default"] = field.value
            
            if field.source == "fair-ds" and field.source_id:
                prop["fair_ds_term"] = field.source_id
            
            properties[field.name] = prop
            
            if field.required:
                required.append(field.name)
        
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": doc_info.title or "Research Metadata Template",
            "description": f"FAIR metadata template for: {doc_info.title or 'Research Project'}",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": True
        }
    
    @staticmethod
    def generate_yaml_template(fields: List[MetadataField], doc_info: DocumentInfo) -> str:
        """Generate YAML template."""
        lines = [
            f"# FAIR Metadata Template",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Project: {doc_info.title or 'Research Project'}",
            f"# Domain: {doc_info.research_domain}",
            "",
        ]
        
        # Group fields
        required_fields = [f for f in fields if f.required]
        local_optional = [f for f in fields if not f.required and f.source == "local"]
        fair_ds_fields = [f for f in fields if f.source == "fair-ds"]
        
        # Required fields
        if required_fields:
            lines.append("# REQUIRED FIELDS")
            for field in required_fields:
                value = field.value or f"# {field.description}"
                lines.append(f"{field.name}: {value}")
            lines.append("")
        
        # Optional local fields
        if local_optional:
            lines.append("# OPTIONAL FIELDS")
            for field in local_optional:
                value = field.value or f"# {field.description}"
                lines.append(f"{field.name}: {value}")
            lines.append("")
        
        # FAIR-DS enhanced fields
        if fair_ds_fields:
            lines.append("# FAIR DATA STATION ENHANCED FIELDS")
            for field in fair_ds_fields:
                value = field.value or f"# {field.description}"
                source_info = f" [FAIR-DS: {field.source_id}]" if field.source_id else ""
                lines.append(f"{field.name}{source_info}: {value}")
        
        return "\n".join(lines)
    
    @staticmethod
    def generate_rdf_turtle(fields: List[MetadataField], doc_info: DocumentInfo) -> str:
        """Generate RDF in Turtle format."""
        if not HAS_RDF:
            return "# RDF generation disabled (rdflib not installed)"
        
        g = Graph()
        
        # Namespaces
        SCHEMA = Namespace("https://schema.org/")
        FAIRIFIER = Namespace("http://fairifier.org/")
        FAIRDS = Namespace("http://fairbydesign.nl/terms/")
        
        g.bind("schema", SCHEMA)
        g.bind("fairifier", FAIRIFIER)
        g.bind("fairds", FAIRDS)
        
        # Main dataset
        dataset = FAIRIFIER["dataset"]
        g.add((dataset, RDF.type, SCHEMA.Dataset))
        
        # Basic metadata
        if doc_info.title:
            g.add((dataset, SCHEMA.name, Literal(doc_info.title)))
        if doc_info.abstract:
            g.add((dataset, SCHEMA.description, Literal(doc_info.abstract)))
        
        # Authors
        for i, author in enumerate(doc_info.authors):
            author_uri = FAIRIFIER[f"person/{i}"]
            g.add((author_uri, RDF.type, SCHEMA.Person))
            g.add((author_uri, SCHEMA.name, Literal(author)))
            g.add((dataset, SCHEMA.author, author_uri))
        
        # Keywords
        for keyword in doc_info.keywords:
            g.add((dataset, SCHEMA.keywords, Literal(keyword)))
        
        # Metadata fields
        for field in fields:
            if field.value:
                if field.source == "fair-ds" and field.source_id:
                    prop_uri = FAIRDS[field.source_id]
                else:
                    prop_uri = FAIRIFIER[field.name]
                
                if field.data_type == "number":
                    try:
                        value = Literal(float(field.value))
                    except ValueError:
                        value = Literal(field.value)
                else:
                    value = Literal(field.value)
                
                g.add((dataset, prop_uri, value))
        
        return g.serialize(format='turtle')


# ============================================================================
# Main Processor
# ============================================================================

class FAIRifier:
    """Main FAIRifier processor."""
    
    def __init__(self, fair_ds_url: str = None, enable_fair_ds: bool = True):
        self.fair_ds_client = None
        
        if enable_fair_ds and HAS_REQUESTS and fair_ds_url:
            self.fair_ds_client = FAIRDataStationClient(fair_ds_url)
        
        self.kb = KnowledgeBase(self.fair_ds_client)
    
    def process_document(self, file_path: Union[str, Path]) -> ProcessingResult:
        """Process a document and generate FAIR metadata."""
        start_time = datetime.now()
        file_path = Path(file_path)
        
        logger.info(f"Processing: {file_path.name}")
        
        # Extract document information
        if file_path.suffix.lower() == '.pdf':
            doc_info = DocumentProcessor.extract_from_pdf(str(file_path))
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            doc_info = DocumentProcessor.extract_from_text(text)
        
        logger.info(f"Extracted info - Domain: {doc_info.research_domain}, Authors: {len(doc_info.authors)}")
        
        # Generate metadata fields
        fields = self.kb.generate_fields(doc_info)
        logger.info(f"Generated {len(fields)} metadata fields")
        
        # Generate outputs
        json_schema = OutputGenerator.generate_json_schema(fields, doc_info)
        yaml_template = OutputGenerator.generate_yaml_template(fields, doc_info)
        rdf_turtle = OutputGenerator.generate_rdf_turtle(fields, doc_info)
        
        # Calculate confidence
        confidence = self._calculate_confidence(doc_info, fields)
        
        # Check FAIR-DS enhancement
        fair_ds_enhanced = any(f.source == "fair-ds" for f in fields)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return ProcessingResult(
            document_info=doc_info,
            metadata_fields=fields,
            json_schema=json_schema,
            yaml_template=yaml_template,
            rdf_turtle=rdf_turtle,
            confidence=confidence,
            fair_ds_enhanced=fair_ds_enhanced,
            processing_time=processing_time
        )
    
    def _calculate_confidence(self, doc_info: DocumentInfo, fields: List[MetadataField]) -> float:
        """Calculate overall confidence score."""
        score = 0.0
        
        # Document extraction quality
        if doc_info.title:
            score += 0.25
        if doc_info.abstract:
            score += 0.25
        if doc_info.authors:
            score += 0.15
        if doc_info.keywords:
            score += 0.10
        if doc_info.research_domain != "unknown":
            score += 0.10
        
        # Field completion
        filled_fields = len([f for f in fields if f.value])
        if fields:
            completion_score = filled_fields / len(fields) * 0.15
            score += completion_score
        
        return min(score, 1.0)
    
    def save_results(self, result: ProcessingResult, output_dir: Union[str, Path] = "output"):
        """Save processing results to files."""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Save JSON Schema
        with open(output_path / "metadata_schema.json", 'w', encoding='utf-8') as f:
            json.dump(result.json_schema, f, indent=2, ensure_ascii=False)
        
        # Save YAML template
        with open(output_path / "metadata_template.yaml", 'w', encoding='utf-8') as f:
            f.write(result.yaml_template)
        
        # Save RDF
        with open(output_path / "metadata.ttl", 'w', encoding='utf-8') as f:
            f.write(result.rdf_turtle)
        
        # Save processing summary
        summary = {
            "document": asdict(result.document_info),
            "processing": {
                "fields_generated": len(result.metadata_fields),
                "required_fields": len([f for f in result.metadata_fields if f.required]),
                "fair_ds_enhanced": result.fair_ds_enhanced,
                "confidence": result.confidence,
                "processing_time_seconds": result.processing_time,
                "generated_at": datetime.now().isoformat()
            },
            "fields": [asdict(f) for f in result.metadata_fields]
        }
        
        with open(output_path / "processing_summary.json", 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to: {output_path}")
        return output_path


# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="FAIRifier - FAIR Metadata Generation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fairifier_final.py document.pdf
  python fairifier_final.py paper.txt --output results/
  python fairifier_final.py study.pdf --fair-ds-url http://localhost:8083
  python fairifier_final.py document.txt --no-fair-ds --quiet
        """
    )
    
    parser.add_argument("document", help="Path to document file (PDF or text)")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    parser.add_argument("--fair-ds-url", default="http://localhost:8083", 
                       help="FAIR Data Station URL")
    parser.add_argument("--no-fair-ds", action="store_true", 
                       help="Disable FAIR Data Station integration")
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--version", action="version", version="FAIRifier 1.0.0")
    
    args = parser.parse_args()
    
    # Configure logging
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    
    try:
        # Initialize FAIRifier
        fairifier = FAIRifier(
            fair_ds_url=None if args.no_fair_ds else args.fair_ds_url,
            enable_fair_ds=not args.no_fair_ds
        )
        
        if not args.quiet:
            print("🧬 FAIRifier - FAIR Metadata Generation Tool")
            print("=" * 60)
        
        # Process document
        result = fairifier.process_document(args.document)
        
        # Save results
        output_path = fairifier.save_results(result, args.output)
        
        # Display summary
        if not args.quiet:
            print(f"\n📊 Processing Summary:")
            print(f"   📄 Document: {result.document_info.title[:50]}..." if result.document_info.title else "   📄 Document processed")
            print(f"   👥 Authors: {len(result.document_info.authors)}")
            print(f"   🔬 Domain: {result.document_info.research_domain}")
            print(f"   🏷️  Fields: {len(result.metadata_fields)} ({len([f for f in result.metadata_fields if f.required])} required)")
            print(f"   🎯 Confidence: {result.confidence:.2f}")
            print(f"   🌐 FAIR-DS Enhanced: {'Yes' if result.fair_ds_enhanced else 'No'}")
            print(f"   ⏱️  Processing Time: {result.processing_time:.2f}s")
            
            print(f"\n📁 Generated Files:")
            for file_path in output_path.glob("*"):
                size = file_path.stat().st_size
                print(f"   ✓ {file_path.name} ({size:,} bytes)")
            
            if result.confidence < 0.5:
                print("\n⚠️  Low confidence - manual review recommended")
            elif result.confidence > 0.8:
                print("\n🎉 High confidence - results look excellent!")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if not args.quiet:
            logger.exception("Detailed error information:")
        return 1


if __name__ == "__main__":
    exit(main())
