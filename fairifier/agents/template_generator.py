"""Template generation agent for creating metadata templates."""

import json
import yaml
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..models import FAIRifierState, MetadataField
from ..config import config


class TemplateGeneratorAgent(BaseAgent):
    """Agent for generating metadata templates from retrieved knowledge."""
    
    def __init__(self):
        super().__init__("TemplateGenerator")
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Generate metadata template from document info and retrieved knowledge."""
        self.log_execution(state, "Starting template generation")
        
        try:
            doc_info = state["document_info"]
            knowledge_items = state["retrieved_knowledge"]
            
            # Generate metadata fields
            metadata_fields = self._generate_metadata_fields(doc_info, knowledge_items)
            
            # Store fields in state
            state["metadata_fields"] = [
                {
                    "name": field.name,
                    "description": field.description,
                    "data_type": field.data_type,
                    "required": field.required,
                    "example_value": field.example_value,
                    "ontology_term": field.ontology_term,
                    "confidence": field.confidence,
                    "evidence_text": field.evidence_text
                }
                for field in metadata_fields
            ]
            
            # Generate JSON Schema
            json_schema = self._generate_json_schema(metadata_fields, doc_info)
            
            # Generate YAML template
            yaml_template = self._generate_yaml_template(metadata_fields, doc_info)
            
            # Store templates in artifacts
            if "artifacts" not in state:
                state["artifacts"] = {}
            
            state["artifacts"]["template_schema"] = json.dumps(json_schema, indent=2)
            state["artifacts"]["template_yaml"] = yaml_template
            
            # Calculate confidence
            confidence = self._calculate_generation_confidence(metadata_fields)
            self.update_confidence(state, "template_generation", confidence)
            
            self.log_execution(
                state,
                f"Template generation completed. Generated {len(metadata_fields)} fields, "
                f"confidence={confidence:.2f}"
            )
            
        except Exception as e:
            self.log_execution(state, f"Template generation failed: {str(e)}", "error")
            self.update_confidence(state, "template_generation", 0.0)
        
        return state
    
    def _generate_metadata_fields(self, doc_info: Dict[str, Any], knowledge_items: List[Dict[str, Any]]) -> List[MetadataField]:
        """Generate metadata fields from knowledge items and document info."""
        fields = []
        
        # Add core project information fields
        core_fields = self._get_core_fields(doc_info)
        fields.extend(core_fields)
        
        # Add fields from knowledge items
        for item in knowledge_items:
            field = self._knowledge_item_to_field(item, doc_info)
            if field:
                fields.append(field)
        
        # Remove duplicates and sort by importance
        fields = self._deduplicate_and_sort_fields(fields)
        
        return fields
    
    def _get_core_fields(self, doc_info: Dict[str, Any]) -> List[MetadataField]:
        """Get core metadata fields that should always be included."""
        fields = []
        
        # Project name
        fields.append(MetadataField(
            name="project_name",
            description="Name of the research project",
            data_type="string",
            required=True,
            example_value=doc_info.get("title", "Research Project"),
            confidence=0.9,
            evidence_text=doc_info.get("title")
        ))
        
        # Investigation type
        research_domain = doc_info.get("research_domain", "")
        inv_type = "metagenome" if "metagenom" in research_domain.lower() else "genome"
        
        fields.append(MetadataField(
            name="investigation_type",
            description="Type of nucleic acid sequence investigation",
            data_type="string",
            required=True,
            example_value=inv_type,
            confidence=0.8 if research_domain else 0.5,
            evidence_text=research_domain
        ))
        
        # Collection date (if mentioned)
        if self._extract_date_from_text(doc_info.get("raw_text", "")):
            fields.append(MetadataField(
                name="collection_date",
                description="Date when the sample was collected",
                data_type="datetime",
                required=True,
                example_value="2023-08-15",
                confidence=0.6,
                evidence_text="Date extracted from document"
            ))
        
        # Geographic location (if mentioned)
        location = self._extract_location_from_text(doc_info.get("raw_text", ""))
        if location:
            fields.append(MetadataField(
                name="geo_loc_name",
                description="Geographical origin of the sample",
                data_type="string",
                required=True,
                example_value=location,
                confidence=0.7,
                evidence_text=f"Location mentioned: {location}"
            ))
        
        return fields
    
    def _knowledge_item_to_field(self, item: Dict[str, Any], doc_info: Dict[str, Any]) -> MetadataField:
        """Convert a knowledge item to a metadata field."""
        # Determine if field is required based on source
        is_required = "required" in item.get("source", "").lower()
        
        # Generate example value based on field name and document content
        example_value = self._generate_example_value(item["term"], doc_info)
        
        # Extract evidence text if the term appears in document
        evidence_text = self._find_evidence_text(item["term"], doc_info.get("raw_text", ""))
        
        return MetadataField(
            name=item["term"],
            description=item["definition"],
            data_type=self._infer_data_type(item["term"]),
            required=is_required,
            example_value=example_value,
            ontology_term=item.get("ontology_uri"),
            confidence=item.get("confidence", 0.5),
            evidence_text=evidence_text
        )
    
    def _infer_data_type(self, field_name: str) -> str:
        """Infer data type from field name."""
        field_lower = field_name.lower()
        
        if any(term in field_lower for term in ["date", "time"]):
            return "datetime"
        elif any(term in field_lower for term in ["temp", "ph", "depth", "concentration", "abundance"]):
            return "number"
        elif any(term in field_lower for term in ["lat_lon", "coordinate"]):
            return "string"  # Could be more specific
        else:
            return "string"
    
    def _generate_example_value(self, field_name: str, doc_info: Dict[str, Any]) -> str:
        """Generate example value for a field based on its name and document content."""
        field_lower = field_name.lower()
        
        # Use document title for project_name
        if "project" in field_lower and "name" in field_lower:
            return doc_info.get("title", "Research Project")
        
        # Common example values
        examples = {
            "investigation_type": "metagenome",
            "collection_date": "2023-08-15",
            "lat_lon": "50.586825 6.408977",
            "geo_loc_name": "Germany:North Rhine-Westphalia:Aachen",
            "env_biome": "marine biome [ENVO:00000447]",
            "env_feature": "oceanic epipelagic zone [ENVO:00000208]",
            "env_material": "sea water [ENVO:00002149]",
            "sample_collect_device": "CTD rosette",
            "seq_meth": "Illumina HiSeq 2500",
            "depth": "10",
            "temp": "25",
            "ph": "7.5"
        }
        
        return examples.get(field_name, f"example_{field_name}")
    
    def _find_evidence_text(self, term: str, text: str) -> str:
        """Find evidence text for a term in the document."""
        import re
        
        # Simple context extraction around the term
        pattern = rf'.{{0,50}}{re.escape(term)}.{{0,50}}'
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            return match.group(0).strip()
        
        return None
    
    def _extract_date_from_text(self, text: str) -> str:
        """Extract date mentions from text."""
        import re
        
        date_patterns = [
            r'\b\d{4}-\d{2}-\d{2}\b',
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            r'\b\d{1,2}\.\d{1,2}\.\d{4}\b'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        
        return None
    
    def _extract_location_from_text(self, text: str) -> str:
        """Extract location mentions from text."""
        # Simple pattern matching for common location formats
        import re
        
        location_patterns = [
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z][a-z]+\b',  # City, Country
            r'\b\d+°[NS]\s*\d+°[EW]\b',  # Coordinates
        ]
        
        for pattern in location_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        
        return None
    
    def _deduplicate_and_sort_fields(self, fields: List[MetadataField]) -> List[MetadataField]:
        """Remove duplicate fields and sort by importance."""
        # Remove duplicates by name
        seen_names = set()
        unique_fields = []
        
        for field in fields:
            if field.name not in seen_names:
                unique_fields.append(field)
                seen_names.add(field.name)
        
        # Sort by required first, then by confidence
        unique_fields.sort(key=lambda f: (not f.required, -f.confidence))
        
        return unique_fields
    
    def _generate_json_schema(self, fields: List[MetadataField], doc_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate JSON Schema from metadata fields."""
        properties = {}
        required = []
        
        for field in fields:
            prop = {
                "type": self._json_schema_type(field.data_type),
                "description": field.description
            }
            
            if field.example_value:
                prop["examples"] = [field.example_value]
            
            if field.ontology_term:
                prop["$comment"] = f"Ontology term: {field.ontology_term}"
            
            properties[field.name] = prop
            
            if field.required:
                required.append(field.name)
        
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"fairifier-template-{datetime.now().strftime('%Y%m%d')}",
            "title": doc_info.get("title", "Research Metadata Template"),
            "description": f"Metadata template generated for: {doc_info.get('title', 'Research Project')}",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": True
        }
        
        return schema
    
    def _json_schema_type(self, data_type: str) -> str:
        """Convert internal data type to JSON Schema type."""
        type_mapping = {
            "string": "string",
            "number": "number",
            "datetime": "string",  # With format
            "boolean": "boolean"
        }
        return type_mapping.get(data_type, "string")
    
    def _generate_yaml_template(self, fields: List[MetadataField], doc_info: Dict[str, Any]) -> str:
        """Generate YAML template from metadata fields."""
        template_data = {
            "# Metadata Template": f"Generated for: {doc_info.get('title', 'Research Project')}",
            "# Generated": datetime.now().isoformat(),
            "# Instructions": "Fill in the values below. Required fields are marked with (REQUIRED)"
        }
        
        # Group fields by category
        required_fields = {}
        optional_fields = {}
        
        for field in fields:
            field_key = f"{field.name}{'  # (REQUIRED)' if field.required else ''}"
            field_value = field.example_value or f"# {field.description}"
            
            if field.required:
                required_fields[field_key] = field_value
            else:
                optional_fields[field_key] = field_value
        
        # Combine sections
        if required_fields:
            template_data["# REQUIRED FIELDS"] = None
            template_data.update(required_fields)
        
        if optional_fields:
            template_data["# OPTIONAL FIELDS"] = None
            template_data.update(optional_fields)
        
        return yaml.dump(template_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    def _calculate_generation_confidence(self, fields: List[MetadataField]) -> float:
        """Calculate confidence for template generation."""
        if not fields:
            return 0.0
        
        # Base score from number of fields
        base_score = min(len(fields) / 15.0, 0.4)
        
        # Required fields coverage
        required_count = sum(1 for f in fields if f.required)
        required_score = min(required_count / 5.0, 0.3)
        
        # Average field confidence
        avg_confidence = sum(f.confidence for f in fields) / len(fields)
        confidence_score = avg_confidence * 0.3
        
        return min(base_score + required_score + confidence_score, 1.0)
