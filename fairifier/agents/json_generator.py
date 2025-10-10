"""JSON metadata generator for FAIR-DS compatible output."""

import json
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..models import FAIRifierState, MetadataField
from ..config import config


class JSONGeneratorAgent(BaseAgent):
    """Agent for generating FAIR-DS compatible JSON metadata."""
    
    def __init__(self):
        super().__init__("JSONGenerator")
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Generate FAIR-DS compatible JSON from document info and knowledge."""
        self.log_execution(state, "Starting JSON metadata generation")
        
        try:
            doc_info = state["document_info"]
            knowledge_items = state["retrieved_knowledge"]
            
            # Generate metadata fields in FAIR-DS format
            metadata_fields = self._generate_fairds_fields(doc_info, knowledge_items)
            
            # Store fields in state
            state["metadata_fields"] = [self._field_to_dict(field) for field in metadata_fields]
            
            # Generate final JSON output
            json_output = self._generate_json_output(metadata_fields, doc_info, state)
            
            # Store in artifacts
            if "artifacts" not in state:
                state["artifacts"] = {}
            
            state["artifacts"]["metadata_json"] = json.dumps(json_output, indent=2, ensure_ascii=False)
            
            # Calculate confidence
            confidence = self._calculate_confidence(metadata_fields)
            self.update_confidence(state, "json_generation", confidence)
            
            self.log_execution(
                state,
                f"JSON generation completed. Generated {len(metadata_fields)} fields, "
                f"confidence={confidence:.2f}"
            )
            
        except Exception as e:
            self.log_execution(state, f"JSON generation failed: {str(e)}", "error")
            self.update_confidence(state, "json_generation", 0.0)
        
        return state
    
    def _generate_fairds_fields(
        self, 
        doc_info: Dict[str, Any], 
        knowledge_items: List[Dict[str, Any]]
    ) -> List[MetadataField]:
        """Generate metadata fields in FAIR-DS format."""
        fields = []
        
        # Core fields from document
        core_fields = self._extract_core_fields(doc_info)
        fields.extend(core_fields)
        
        # Fields from knowledge retrieval
        knowledge_fields = self._extract_knowledge_fields(knowledge_items, doc_info)
        fields.extend(knowledge_fields)
        
        # Deduplicate
        fields = self._deduplicate_fields(fields)
        
        return fields
    
    def _extract_core_fields(self, doc_info: Dict[str, Any]) -> List[MetadataField]:
        """Extract core fields from document information."""
        fields = []
        
        # Project name
        if doc_info.get("title"):
            fields.append(MetadataField(
                field_name="project_name",
                value=doc_info["title"],
                evidence=f"Extracted from document title",
                confidence=0.95,
                origin="document_parser",
                package_source=config.default_mixs_package,
                status="confirmed",
                data_type="string",
                required=True,
                description="Name of the research project"
            ))
        
        # Investigation type (inferred from domain)
        domain = doc_info.get("research_domain", "")
        if domain:
            inv_type = self._infer_investigation_type(domain)
            fields.append(MetadataField(
                field_name="investigation_type",
                value=inv_type,
                evidence=f"Inferred from research domain: {domain}",
                confidence=0.80,
                origin="document_parser",
                package_source=config.default_mixs_package,
                status="provisional",
                data_type="string",
                required=True,
                description="Type of investigation"
            ))
        
        # Authors
        if doc_info.get("authors"):
            authors_str = "; ".join(doc_info["authors"])
            fields.append(MetadataField(
                field_name="principal_investigator",
                value=doc_info["authors"][0] if doc_info["authors"] else None,
                evidence=f"Extracted from document authors: {authors_str}",
                confidence=0.90,
                origin="document_parser",
                package_source="local",
                status="provisional",
                data_type="string",
                required=False,
                description="Principal investigator"
            ))
        
        # Keywords as environmental descriptors
        if doc_info.get("keywords"):
            keywords_str = ", ".join(doc_info["keywords"])
            fields.append(MetadataField(
                field_name="env_broad_scale",
                value=keywords_str,
                evidence=f"Extracted from document keywords",
                confidence=0.70,
                origin="document_parser",
                package_source=config.default_mixs_package,
                status="provisional",
                data_type="string",
                required=False,
                description="Environmental broad scale context"
            ))
        
        return fields
    
    def _extract_knowledge_fields(
        self, 
        knowledge_items: List[Dict[str, Any]], 
        doc_info: Dict[str, Any]
    ) -> List[MetadataField]:
        """Extract fields from retrieved knowledge."""
        fields = []
        
        for item in knowledge_items:
            term = item.get("term", "")
            definition = item.get("definition", "")
            source = item.get("source", "unknown")
            confidence = item.get("confidence", 0.5)
            
            # Map knowledge items to metadata fields
            field_name = self._map_term_to_field(term)
            if field_name:
                fields.append(MetadataField(
                    field_name=field_name,
                    value=term,
                    evidence=f"Retrieved from {source}: {definition[:100]}...",
                    confidence=confidence,
                    origin="knowledge_retriever",
                    package_source=source if source in ["MIMAG", "MISAG", "MIUVIG"] else "local",
                    status="provisional",
                    data_type="string",
                    required=False,
                    description=definition
                ))
        
        return fields
    
    def _infer_investigation_type(self, domain: str) -> str:
        """Infer investigation type from research domain."""
        domain_lower = domain.lower()
        
        if any(term in domain_lower for term in ["metagenom", "microbiome", "16s"]):
            return "metagenome"
        elif any(term in domain_lower for term in ["genom", "dna", "sequenc"]):
            return "genome"
        elif any(term in domain_lower for term in ["transcriptom", "rna"]):
            return "transcriptome"
        else:
            return "other"
    
    def _map_term_to_field(self, term: str) -> str:
        """Map a knowledge term to a metadata field name."""
        term_lower = term.lower()
        
        # Simple mapping - in production, use ontology mapping
        if any(word in term_lower for word in ["soil", "terrestrial", "ground"]):
            return "env_material"
        elif any(word in term_lower for word in ["biome", "ecosystem"]):
            return "env_biome"
        elif any(word in term_lower for word in ["location", "site", "geographic"]):
            return "geo_loc_name"
        elif any(word in term_lower for word in ["latitude", "longitude", "coordinate"]):
            return "lat_lon"
        elif any(word in term_lower for word in ["date", "time", "when"]):
            return "collection_date"
        elif any(word in term_lower for word in ["method", "protocol", "procedure"]):
            return "samp_collect_method"
        else:
            # Use term as field name (sanitized)
            return term_lower.replace(" ", "_").replace("-", "_")[:50]
    
    def _deduplicate_fields(self, fields: List[MetadataField]) -> List[MetadataField]:
        """Remove duplicate fields, keeping the one with highest confidence."""
        field_dict = {}
        
        for field in fields:
            if field.field_name not in field_dict:
                field_dict[field.field_name] = field
            else:
                # Keep field with higher confidence
                if field.confidence > field_dict[field.field_name].confidence:
                    field_dict[field.field_name] = field
        
        return list(field_dict.values())
    
    def _field_to_dict(self, field: MetadataField) -> Dict[str, Any]:
        """Convert MetadataField to dictionary for FAIR-DS format."""
        return {
            "field_name": field.field_name,
            "value": field.value,
            "evidence": field.evidence,
            "confidence": field.confidence,
            "origin": field.origin,
            "package_source": field.package_source,
            "status": field.status
        }
    
    def _generate_json_output(
        self, 
        fields: List[MetadataField], 
        doc_info: Dict[str, Any],
        state: FAIRifierState
    ) -> Dict[str, Any]:
        """Generate final FAIR-DS compatible JSON output."""
        
        # Calculate overall confidence
        overall_confidence = sum(f.confidence for f in fields) / len(fields) if fields else 0.0
        
        output = {
            "fairifier_version": "0.2.0",
            "generated_at": datetime.now().isoformat(),
            "document_source": state["document_path"],
            "processing_status": state["status"],
            "overall_confidence": round(overall_confidence, 3),
            "needs_review": state.get("needs_human_review", False),
            
            # Document information
            "document_info": {
                "title": doc_info.get("title"),
                "abstract": doc_info.get("abstract"),
                "authors": doc_info.get("authors", []),
                "keywords": doc_info.get("keywords", []),
                "research_domain": doc_info.get("research_domain")
            },
            
            # Metadata fields in FAIR-DS format
            "metadata": [self._field_to_dict(field) for field in fields],
            
            # Statistics
            "statistics": {
                "total_fields": len(fields),
                "confirmed_fields": sum(1 for f in fields if f.status == "confirmed"),
                "provisional_fields": sum(1 for f in fields if f.status == "provisional"),
                "required_fields": sum(1 for f in fields if f.required),
                "package_sources": list(set(f.package_source for f in fields if f.package_source))
            },
            
            # Confidence breakdown
            "confidence_scores": state.get("confidence_scores", {}),
            
            # Errors and warnings
            "errors": state.get("errors", []),
            "warnings": []
        }
        
        # Add warnings for low confidence fields
        for field in fields:
            if field.confidence < config.min_confidence_threshold:
                output["warnings"].append(
                    f"Low confidence for field '{field.field_name}': {field.confidence:.2f}"
                )
        
        return output
    
    def _calculate_confidence(self, fields: List[MetadataField]) -> float:
        """Calculate overall confidence for JSON generation."""
        if not fields:
            return 0.0
        
        # Average confidence of all fields
        avg_confidence = sum(f.confidence for f in fields) / len(fields)
        
        # Bonus for having required fields
        required_fields = sum(1 for f in fields if f.required)
        required_bonus = min(0.1, required_fields * 0.02)
        
        # Penalty for too few fields
        field_count_penalty = 0.0
        if len(fields) < 5:
            field_count_penalty = (5 - len(fields)) * 0.05
        
        confidence = avg_confidence + required_bonus - field_count_penalty
        return max(0.0, min(1.0, confidence))

