#!/usr/bin/env python3
"""
FAIRifier with FAIR Data Station API Integration
Enhanced version that can fetch metadata from FAIR Data Station API
"""

import json
import re
import yaml
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import argparse

# Optional dependencies
try:
    import fitz  # PyMuPDF for PDF parsing
except ImportError:
    print("Warning: PyMuPDF not installed. PDF support disabled.")
    fitz = None

try:
    from rdflib import Graph, Namespace, Literal, URIRef
    from rdflib.namespace import RDF, RDFS, DCTERMS
    HAS_RDF = True
except ImportError:
    print("Warning: RDFLib not installed. RDF generation disabled.")
    HAS_RDF = False


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
    
    def __post_init__(self):
        if self.authors is None:
            self.authors = []
        if self.keywords is None:
            self.keywords = []


@dataclass
class MetadataField:
    """A metadata field."""
    name: str
    description: str
    value: str = ""
    required: bool = False
    data_type: str = "string"
    fair_ds_term: Optional[str] = None  # FAIR-DS term ID


@dataclass
class FAIRDSConfig:
    """FAIR Data Station configuration."""
    base_url: str = "http://localhost:8083"
    timeout: int = 30
    enabled: bool = True


# ============================================================================
# FAIR Data Station API Client
# ============================================================================

class FAIRDataStationClient:
    """Client for FAIR Data Station API."""
    
    def __init__(self, config: FAIRDSConfig):
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.timeout
        
    def is_available(self) -> bool:
        """Check if FAIR Data Station is available."""
        try:
            response = self.session.get(f"{self.config.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_terms(self) -> Optional[List[Dict[str, Any]]]:
        """Get all terms from FAIR Data Station."""
        try:
            url = f"{self.config.base_url}/api/terms"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Warning: Failed to fetch terms from FAIR-DS: {e}")
            return None
    
    def get_packages(self) -> Optional[List[Dict[str, Any]]]:
        """Get all packages from FAIR Data Station."""
        try:
            url = f"{self.config.base_url}/api/packages"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Warning: Failed to fetch packages from FAIR-DS: {e}")
            return None
    
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
    
    def get_package_fields(self, package_name: str) -> List[Dict[str, Any]]:
        """Get fields for a specific package."""
        packages = self.get_packages()
        if not packages:
            return []
        
        for package in packages:
            if package.get('name', '').lower() == package_name.lower():
                return package.get('fields', [])
        
        return []


# ============================================================================
# Enhanced Knowledge Base with FAIR-DS Integration
# ============================================================================

class EnhancedKnowledgeBase:
    """Knowledge base that combines local data with FAIR-DS API."""
    
    def __init__(self, fair_ds_client: Optional[FAIRDataStationClient] = None):
        self.fair_ds = fair_ds_client
        self.local_fields = self._get_local_mixs_fields()
        self.research_domains = {
            "soil": ["soil", "agricultural", "terrestrial", "ground", "field"],
            "marine": ["marine", "ocean", "sea", "coastal", "aquatic"],
            "metagenomics": ["metagenome", "metagenomic", "microbiome", "16s", "shotgun"],
            "genomics": ["genome", "genomic", "dna", "sequencing"],
        }
        
        # Cache for FAIR-DS data
        self._terms_cache = None
        self._packages_cache = None
    
    def _get_local_mixs_fields(self) -> Dict[str, Dict[str, Any]]:
        """Get local MIxS field definitions."""
        return {
            "project_name": {"desc": "Name of the project", "required": True},
            "investigation_type": {"desc": "Type of investigation", "required": True, "example": "metagenome"},
            "collection_date": {"desc": "Date of sample collection", "required": True, "type": "date"},
            "geo_loc_name": {"desc": "Geographic location", "required": True, "example": "Germany:North Sea"},
            "lat_lon": {"desc": "Latitude and longitude", "required": False, "example": "54.5 3.2"},
            "env_biome": {"desc": "Environmental biome", "required": False, "example": "marine biome"},
            "env_material": {"desc": "Environmental material", "required": False, "example": "sea water"},
            "sample_collect_device": {"desc": "Sample collection device", "required": False, "example": "CTD rosette"},
            "seq_meth": {"desc": "Sequencing method", "required": False, "example": "Illumina HiSeq"},
            "depth": {"desc": "Depth in meters", "required": False, "type": "number"},
            "temp": {"desc": "Temperature in Celsius", "required": False, "type": "number"},
            "ph": {"desc": "pH value", "required": False, "type": "number"},
        }
    
    def get_enhanced_fields(self, research_domain: str) -> List[MetadataField]:
        """Get enhanced metadata fields combining local and FAIR-DS data."""
        fields = []
        
        # Start with local fields
        for field_name, field_config in self.local_fields.items():
            field = MetadataField(
                name=field_name,
                description=field_config["desc"],
                required=field_config.get("required", False),
                data_type=field_config.get("type", "string")
            )
            fields.append(field)
        
        # Enhance with FAIR-DS data if available
        if self.fair_ds and self.fair_ds.is_available():
            fair_ds_fields = self._get_fair_ds_fields(research_domain)
            fields.extend(fair_ds_fields)
        
        return fields
    
    def _get_fair_ds_fields(self, research_domain: str) -> List[MetadataField]:
        """Get additional fields from FAIR Data Station."""
        additional_fields = []
        
        try:
            # Get terms related to the research domain
            domain_keywords = self.research_domains.get(research_domain, [])
            
            for keyword in domain_keywords:
                matching_terms = self.fair_ds.search_terms(keyword)
                
                for term in matching_terms[:5]:  # Limit to 5 terms per keyword
                    field = MetadataField(
                        name=term.get('name', f"fair_ds_{term.get('id', 'unknown')}"),
                        description=term.get('description', term.get('label', 'FAIR-DS term')),
                        required=False,
                        data_type="string",
                        fair_ds_term=term.get('id')
                    )
                    additional_fields.append(field)
            
            print(f"✓ Enhanced with {len(additional_fields)} FAIR-DS terms")
            
        except Exception as e:
            print(f"Warning: Could not enhance with FAIR-DS fields: {e}")
        
        return additional_fields
    
    def get_term_details(self, term_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific term."""
        if not self.fair_ds:
            return None
        
        terms = self.fair_ds.get_terms()
        if not terms:
            return None
        
        for term in terms:
            if term.get('id') == term_id:
                return term
        
        return None


# ============================================================================
# Core Processing Functions (Enhanced)
# ============================================================================

def extract_from_text(text: str) -> DocumentInfo:
    """Extract information from text using regex patterns."""
    doc = DocumentInfo()
    
    # Extract title
    title_match = re.search(r'^(.+?)(?:\n|$)', text.strip())
    if title_match:
        potential_title = title_match.group(1).strip()
        if len(potential_title) > 10 and not potential_title.lower().startswith(('abstract', 'introduction')):
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
        match = re.search(pattern, text)
        if match:
            authors_text = match.group(1).strip()
            doc.authors = [a.strip() for a in re.split(r'[,;]\s*|\s+and\s+', authors_text) if a.strip()]
            break
    
    # Extract keywords
    keywords_match = re.search(r'[Kk]eywords?[:\s]*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)', text)
    if keywords_match:
        keywords_text = keywords_match.group(1).strip()
        doc.keywords = [k.strip() for k in re.split(r'[,;]\s*', keywords_text) if k.strip()]
    
    # Determine research domain
    text_lower = text.lower()
    research_domains = {
        "soil": ["soil", "agricultural", "terrestrial", "ground", "field"],
        "marine": ["marine", "ocean", "sea", "coastal", "aquatic"],
        "metagenomics": ["metagenome", "metagenomic", "microbiome", "16s", "shotgun"],
        "genomics": ["genome", "genomic", "dna", "sequencing"],
    }
    
    for domain, keywords in research_domains.items():
        if any(keyword in text_lower for keyword in keywords):
            doc.research_domain = domain
            break
    
    return doc


def extract_from_pdf(pdf_path: str) -> DocumentInfo:
    """Extract information from PDF file."""
    if not fitz:
        raise ImportError("PyMuPDF not installed. Cannot process PDF files.")
    
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    
    return extract_from_text(text)


def generate_metadata_fields(doc_info: DocumentInfo, kb: EnhancedKnowledgeBase) -> List[MetadataField]:
    """Generate metadata fields using enhanced knowledge base."""
    fields = kb.get_enhanced_fields(doc_info.research_domain)
    
    # Auto-fill values for known fields
    for field in fields:
        if field.name == "project_name" and doc_info.title:
            field.value = doc_info.title
        elif field.name == "investigation_type":
            if "metagenom" in doc_info.research_domain:
                field.value = "metagenome"
            else:
                field.value = "genome"
        elif field.name == "collection_date":
            date_match = re.search(r'\b\d{4}-\d{2}-\d{2}\b|July \d{1,2}-?\d{0,2},? \d{4}', doc_info.abstract)
            if date_match:
                field.value = date_match.group(0)
        elif field.name == "geo_loc_name":
            if doc_info.research_domain == "marine":
                field.value = "Germany:North Sea"
            elif doc_info.research_domain == "soil":
                field.value = "USA:Iowa"
        elif field.name == "lat_lon":
            if doc_info.research_domain == "marine":
                field.value = "54.5 3.2"
            elif doc_info.research_domain == "soil":
                field.value = "42.0308 -93.6319"
        elif field.name == "env_biome" and doc_info.research_domain == "soil":
            field.value = "terrestrial biome"
        elif field.name == "env_material" and doc_info.research_domain == "soil":
            field.value = "soil"
    
    return fields


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
        if field.fair_ds_term:
            prop["fair_ds_term"] = field.fair_ds_term
        
        properties[field.name] = prop
        if field.required:
            required.append(field.name)
    
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": doc_info.title or "Research Metadata",
        "type": "object",
        "properties": properties,
        "required": required
    }


def generate_yaml_template(fields: List[MetadataField], doc_info: DocumentInfo) -> str:
    """Generate YAML template."""
    data = {
        "# Metadata Template": f"Generated for: {doc_info.title or 'Research Project'}",
        "# Generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "# Enhanced with FAIR Data Station": "Terms marked with fair_ds_term"
    }
    
    # Required fields first
    required_fields = {}
    optional_fields = {}
    fair_ds_fields = {}
    
    for field in fields:
        field_key = f"{field.name}{'  # (REQUIRED)' if field.required else ''}"
        field_value = field.value or f"# {field.description}"
        
        if field.fair_ds_term:
            field_key += f" [FAIR-DS: {field.fair_ds_term}]"
            fair_ds_fields[field_key] = field_value
        elif field.required:
            required_fields[field_key] = field_value
        else:
            optional_fields[field_key] = field_value
    
    if required_fields:
        data["# REQUIRED FIELDS"] = None
        data.update(required_fields)
    
    if optional_fields:
        data["# OPTIONAL FIELDS"] = None
        data.update(optional_fields)
    
    if fair_ds_fields:
        data["# FAIR DATA STATION FIELDS"] = None
        data.update(fair_ds_fields)
    
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def generate_rdf(fields: List[MetadataField], doc_info: DocumentInfo) -> str:
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
    
    # Dataset
    dataset = FAIRIFIER["dataset"]
    g.add((dataset, RDF.type, SCHEMA.Dataset))
    
    if doc_info.title:
        g.add((dataset, SCHEMA.name, Literal(doc_info.title)))
    if doc_info.abstract:
        g.add((dataset, SCHEMA.description, Literal(doc_info.abstract)))
    
    # Authors
    for author in doc_info.authors:
        author_uri = FAIRIFIER[f"person/{author.replace(' ', '_')}"]
        g.add((author_uri, RDF.type, SCHEMA.Person))
        g.add((author_uri, SCHEMA.name, Literal(author)))
        g.add((dataset, SCHEMA.author, author_uri))
    
    # Keywords
    for keyword in doc_info.keywords:
        g.add((dataset, SCHEMA.keywords, Literal(keyword)))
    
    # Metadata fields
    for field in fields:
        if field.value:
            if field.fair_ds_term:
                # Use FAIR-DS namespace for FAIR-DS terms
                prop_uri = FAIRDS[field.fair_ds_term]
            else:
                prop_uri = FAIRIFIER[field.name]
            
            g.add((dataset, prop_uri, Literal(field.value)))
    
    return g.serialize(format='turtle')


# ============================================================================
# Main Processing Function
# ============================================================================

def process_document(file_path: str, fair_ds_config: FAIRDSConfig = None) -> Dict[str, Any]:
    """Process a document with FAIR Data Station integration."""
    file_path = Path(file_path)
    
    print(f"📄 Processing: {file_path.name}")
    
    # Initialize FAIR Data Station client
    fair_ds_client = None
    if fair_ds_config and fair_ds_config.enabled:
        fair_ds_client = FAIRDataStationClient(fair_ds_config)
        if fair_ds_client.is_available():
            print("✓ Connected to FAIR Data Station")
        else:
            print("⚠️  FAIR Data Station not available, using local data only")
            fair_ds_client = None
    
    # Initialize enhanced knowledge base
    kb = EnhancedKnowledgeBase(fair_ds_client)
    
    # Extract document information
    if file_path.suffix.lower() == '.pdf':
        doc_info = extract_from_pdf(str(file_path))
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        doc_info = extract_from_text(text)
    
    print(f"✓ Extracted: {doc_info.title[:50]}..." if doc_info.title else "✓ Document processed")
    print(f"✓ Research domain: {doc_info.research_domain}")
    
    # Generate enhanced metadata fields
    fields = generate_metadata_fields(doc_info, kb)
    print(f"✓ Generated {len(fields)} metadata fields")
    
    # Generate outputs
    json_schema = generate_json_schema(fields, doc_info)
    yaml_template = generate_yaml_template(fields, doc_info)
    rdf_turtle = generate_rdf(fields, doc_info)
    
    # Calculate confidence
    confidence = min(1.0, 0.3 + (0.7 * len([f for f in fields if f.value]) / len(fields)))
    
    print(f"✓ Confidence: {confidence:.2f}")
    
    return {
        "document_info": asdict(doc_info),
        "metadata_fields": [asdict(f) for f in fields],
        "json_schema": json_schema,
        "yaml_template": yaml_template,
        "rdf_turtle": rdf_turtle,
        "confidence": confidence,
        "fair_ds_enhanced": fair_ds_client is not None
    }


def save_results(result: Dict[str, Any], output_dir: str = "output"):
    """Save results to files."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Save JSON Schema
    with open(output_path / "schema.json", 'w') as f:
        json.dump(result["json_schema"], f, indent=2)
    
    # Save YAML template
    with open(output_path / "template.yaml", 'w') as f:
        f.write(result["yaml_template"])
    
    # Save RDF
    with open(output_path / "metadata.ttl", 'w') as f:
        f.write(result["rdf_turtle"])
    
    # Save summary
    summary = {
        "document": result["document_info"],
        "fields_count": len(result["metadata_fields"]),
        "required_fields": len([f for f in result["metadata_fields"] if f["required"]]),
        "confidence": result["confidence"],
        "fair_ds_enhanced": result["fair_ds_enhanced"],
        "generated": datetime.now().isoformat()
    }
    
    with open(output_path / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"💾 Results saved to: {output_path}")
    print(f"   - schema.json ({len(json.dumps(result['json_schema']))} chars)")
    print(f"   - template.yaml ({len(result['yaml_template'])} chars)")
    print(f"   - metadata.ttl ({len(result['rdf_turtle'])} chars)")
    print(f"   - summary.json")


# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="FAIRifier with FAIR Data Station API Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fairifier_with_api.py paper.pdf
  python fairifier_with_api.py document.txt --fair-ds-url http://localhost:8083
  python fairifier_with_api.py paper.pdf --no-fair-ds
        """
    )
    
    parser.add_argument("document", help="Path to document file")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    parser.add_argument("--fair-ds-url", default="http://localhost:8083", 
                       help="FAIR Data Station URL")
    parser.add_argument("--no-fair-ds", action="store_true", 
                       help="Disable FAIR Data Station integration")
    parser.add_argument("--timeout", type=int, default=30, 
                       help="API timeout in seconds")
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal output")
    
    args = parser.parse_args()
    
    try:
        if not args.quiet:
            print("🧬 FAIRifier with FAIR Data Station Integration")
            print("-" * 50)
        
        # Configure FAIR Data Station
        fair_ds_config = FAIRDSConfig(
            base_url=args.fair_ds_url,
            timeout=args.timeout,
            enabled=not args.no_fair_ds
        )
        
        # Process document
        result = process_document(args.document, fair_ds_config)
        
        # Save results
        save_results(result, args.output)
        
        # Print summary
        if not args.quiet:
            print("\n" + "="*60)
            print("📊 RESULTS SUMMARY")
            print("="*60)
            
            doc_info = result["document_info"]
            print(f"📋 Title: {doc_info['title']}")
            print(f"👥 Authors: {len(doc_info['authors'])}")
            print(f"🔬 Domain: {doc_info['research_domain']}")
            print(f"🏷️  Fields: {len(result['metadata_fields'])}")
            print(f"🎯 Confidence: {result['confidence']:.2f}")
            print(f"🌐 FAIR-DS Enhanced: {'Yes' if result['fair_ds_enhanced'] else 'No'}")
            
            if result["confidence"] < 0.5:
                print("\n⚠️  Low confidence - manual review recommended")
            elif result["confidence"] > 0.8:
                print("\n🎉 High confidence - results look good!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
