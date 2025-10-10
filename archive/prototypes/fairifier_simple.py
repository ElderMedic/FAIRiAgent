#!/usr/bin/env python3
"""
FAIRifier - Simple PoC Version
A minimal implementation for generating FAIR metadata from research documents.
"""

import json
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import argparse

# Minimal dependencies only
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
# Simple Data Models
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


@dataclass
class FAIRResult:
    """Final result container."""
    document_info: DocumentInfo
    metadata_fields: List[MetadataField]
    json_schema: Dict[str, Any]
    yaml_template: str
    rdf_turtle: str = ""
    confidence: float = 0.0


# ============================================================================
# Built-in Knowledge Base (No External Files)
# ============================================================================

MIXS_FIELDS = {
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

RESEARCH_DOMAINS = {
    "soil": ["soil", "agricultural", "terrestrial", "ground", "field"],
    "marine": ["marine", "ocean", "sea", "coastal", "aquatic"],
    "metagenomics": ["metagenome", "metagenomic", "microbiome", "16s", "shotgun"],
    "genomics": ["genome", "genomic", "dna", "sequencing"],
}


# ============================================================================
# Core Processing Functions
# ============================================================================

def extract_from_text(text: str) -> DocumentInfo:
    """Extract information from text using simple regex patterns."""
    doc = DocumentInfo()
    
    # Extract title (first line or after "Title:")
    title_match = re.search(r'^(.+?)(?:\n|$)', text.strip())
    if title_match:
        potential_title = title_match.group(1).strip()
        if len(potential_title) > 10 and not potential_title.lower().startswith(('abstract', 'introduction')):
            doc.title = potential_title
    
    # Extract abstract
    abstract_match = re.search(r'[Aa]bstract[:\s]*\n*(.+?)(?:\n\s*\n|\n[A-Z][a-z]+:)', text, re.DOTALL)
    if abstract_match:
        doc.abstract = abstract_match.group(1).strip()[:500]  # Limit length
    
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
    for domain, keywords in RESEARCH_DOMAINS.items():
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


def generate_metadata_fields(doc_info: DocumentInfo) -> List[MetadataField]:
    """Generate metadata fields based on document info."""
    fields = []
    
    for field_name, field_config in MIXS_FIELDS.items():
        field = MetadataField(
            name=field_name,
            description=field_config["desc"],
            required=field_config.get("required", False),
            data_type=field_config.get("type", "string")
        )
        
        # Try to auto-fill some values
        if field_name == "project_name" and doc_info.title:
            field.value = doc_info.title
        elif field_name == "investigation_type":
            if "metagenom" in doc_info.research_domain:
                field.value = "metagenome"
            else:
                field.value = "genome"
        elif field_name == "collection_date":
            # Try to extract date from text
            date_match = re.search(r'\b\d{4}-\d{2}-\d{2}\b|July \d{1,2}-?\d{0,2},? \d{4}', doc_info.abstract)
            if date_match:
                field.value = date_match.group(0)
        elif field_name == "geo_loc_name":
            if doc_info.research_domain == "marine":
                field.value = "Germany:North Sea"
            elif doc_info.research_domain == "soil":
                field.value = "USA:Iowa"
        elif field_name == "lat_lon":
            if doc_info.research_domain == "marine":
                field.value = "54.5 3.2"
            elif doc_info.research_domain == "soil":
                field.value = "42.0308 -93.6319"
        elif field_name == "env_biome" and doc_info.research_domain == "soil":
            field.value = "terrestrial biome"
        elif field_name == "env_material" and doc_info.research_domain == "soil":
            field.value = "soil"
        
        fields.append(field)
    
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
        "# Generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Required fields first
    required_fields = {f.name: f.value or f"# {f.description}" for f in fields if f.required}
    optional_fields = {f.name: f.value or f"# {f.description}" for f in fields if not f.required}
    
    if required_fields:
        data["# REQUIRED FIELDS"] = None
        data.update(required_fields)
    
    if optional_fields:
        data["# OPTIONAL FIELDS"] = None
        data.update(optional_fields)
    
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def generate_rdf(fields: List[MetadataField], doc_info: DocumentInfo) -> str:
    """Generate simple RDF in Turtle format."""
    if not HAS_RDF:
        return "# RDF generation disabled (rdflib not installed)"
    
    g = Graph()
    
    # Simple namespaces
    SCHEMA = Namespace("https://schema.org/")
    FAIRIFIER = Namespace("http://fairifier.org/")
    
    g.bind("schema", SCHEMA)
    g.bind("fairifier", FAIRIFIER)
    
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
    
    return g.serialize(format='turtle')


def calculate_confidence(doc_info: DocumentInfo, fields: List[MetadataField]) -> float:
    """Calculate overall confidence score."""
    score = 0.0
    
    # Document extraction quality
    if doc_info.title:
        score += 0.3
    if doc_info.abstract:
        score += 0.3
    if doc_info.authors:
        score += 0.2
    if doc_info.keywords:
        score += 0.1
    if doc_info.research_domain:
        score += 0.1
    
    return min(score, 1.0)


# ============================================================================
# Main Processing Function
# ============================================================================

def process_document(file_path: str) -> FAIRResult:
    """Process a document and generate FAIR metadata."""
    file_path = Path(file_path)
    
    print(f"📄 Processing: {file_path.name}")
    
    # Extract document information
    if file_path.suffix.lower() == '.pdf':
        doc_info = extract_from_pdf(str(file_path))
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        doc_info = extract_from_text(text)
    
    print(f"✓ Extracted: {doc_info.title[:50]}..." if doc_info.title else "✓ Document processed")
    
    # Generate metadata fields
    fields = generate_metadata_fields(doc_info)
    print(f"✓ Generated {len(fields)} metadata fields")
    
    # Generate outputs
    json_schema = generate_json_schema(fields, doc_info)
    yaml_template = generate_yaml_template(fields, doc_info)
    rdf_turtle = generate_rdf(fields, doc_info)
    confidence = calculate_confidence(doc_info, fields)
    
    print(f"✓ Confidence: {confidence:.2f}")
    
    return FAIRResult(
        document_info=doc_info,
        metadata_fields=fields,
        json_schema=json_schema,
        yaml_template=yaml_template,
        rdf_turtle=rdf_turtle,
        confidence=confidence
    )


def save_results(result: FAIRResult, output_dir: str = "output"):
    """Save results to files."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Save JSON Schema
    with open(output_path / "schema.json", 'w') as f:
        json.dump(result.json_schema, f, indent=2)
    
    # Save YAML template
    with open(output_path / "template.yaml", 'w') as f:
        f.write(result.yaml_template)
    
    # Save RDF
    with open(output_path / "metadata.ttl", 'w') as f:
        f.write(result.rdf_turtle)
    
    # Save summary
    summary = {
        "document": asdict(result.document_info),
        "fields_count": len(result.metadata_fields),
        "required_fields": len([f for f in result.metadata_fields if f.required]),
        "confidence": result.confidence,
        "generated": datetime.now().isoformat()
    }
    
    with open(output_path / "summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"💾 Results saved to: {output_path}")
    print(f"   - schema.json ({len(json.dumps(result.json_schema))} chars)")
    print(f"   - template.yaml ({len(result.yaml_template)} chars)")
    print(f"   - metadata.ttl ({len(result.rdf_turtle)} chars)")
    print(f"   - summary.json")


def print_results(result: FAIRResult):
    """Print results to console."""
    print("\n" + "="*60)
    print("📊 FAIRIFIER RESULTS")
    print("="*60)
    
    print(f"📋 Document Info:")
    print(f"   Title: {result.document_info.title}")
    print(f"   Authors: {len(result.document_info.authors)}")
    print(f"   Keywords: {len(result.document_info.keywords)}")
    print(f"   Domain: {result.document_info.research_domain}")
    
    print(f"\n🏷️  Metadata Fields: {len(result.metadata_fields)}")
    required_count = len([f for f in result.metadata_fields if f.required])
    print(f"   Required: {required_count}")
    print(f"   Optional: {len(result.metadata_fields) - required_count}")
    
    print(f"\n🎯 Quality:")
    print(f"   Confidence: {result.confidence:.2f}")
    
    # Show some example fields
    print(f"\n📝 Sample Fields:")
    for field in result.metadata_fields[:5]:
        status = "REQUIRED" if field.required else "optional"
        value_preview = field.value[:30] + "..." if len(field.value) > 30 else field.value
        print(f"   • {field.name} ({status}): {value_preview or 'N/A'}")


# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="FAIRifier - Generate FAIR metadata from research documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fairifier_simple.py paper.pdf
  python fairifier_simple.py research_proposal.txt --output results/
  python fairifier_simple.py document.pdf --no-save --quiet
        """
    )
    
    parser.add_argument("document", help="Path to document file (PDF or text)")
    parser.add_argument("-o", "--output", default="output", 
                       help="Output directory (default: output)")
    parser.add_argument("--no-save", action="store_true", 
                       help="Don't save files, only print results")
    parser.add_argument("-q", "--quiet", action="store_true", 
                       help="Minimal output")
    
    args = parser.parse_args()
    
    try:
        # Process document
        if not args.quiet:
            print("🧬 FAIRifier - FAIR Metadata Generator")
            print("-" * 40)
        
        result = process_document(args.document)
        
        # Save results
        if not args.no_save:
            save_results(result, args.output)
        
        # Print results
        if not args.quiet:
            print_results(result)
        
        # Simple validation
        if result.confidence < 0.5:
            print("\n⚠️  Low confidence - manual review recommended")
        elif result.confidence > 0.8:
            print("\n🎉 High confidence - results look good!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
