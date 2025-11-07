"""JSON metadata generator for FAIR-DS compatible output."""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, MetadataField
from ..config import config
from ..utils.llm_helper import get_llm_helper


class JSONGeneratorAgent(BaseAgent):
    """Agent for generating FAIR-DS compatible JSON metadata."""
    
    def __init__(self, use_llm: bool = True):
        super().__init__("JSONGenerator")
        self.use_llm = use_llm
        if use_llm:
            self.llm_helper = get_llm_helper()
        
    @traceable(name="JSONGenerator", tags=["agent", "generation"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Generate FAIR-DS compatible JSON from document info and knowledge."""
        self.log_execution(state, "📝 Starting JSON metadata generation")
        
        try:
            doc_info = state.get("document_info", {})
            knowledge_items = state.get("retrieved_knowledge", [])
            document_text = state.get("document_content", "")
            
            self.log_execution(
                state, 
                f"📊 Input: {len(knowledge_items)} knowledge terms from retrieval"
            )
            
            # Generate metadata fields with LLM value extraction
            if self.use_llm:
                # Get critic feedback if this is a retry
                feedback = self.get_context_feedback(state)
                critic_feedback = feedback.get("critic_feedback")
                
                if critic_feedback:
                    self.log_execution(state, "🔄 Retrying metadata generation with Critic feedback...")
                
                self.log_execution(state, "🤖 Using LLM for intelligent, adaptive metadata generation...")
                metadata_fields = await self._generate_with_llm(
                    doc_info, knowledge_items, document_text, critic_feedback
                )
                self.log_execution(
                    state, 
                    f"✅ LLM generated {len(metadata_fields)} fields with values"
                )
            else:
                self.log_execution(state, "⚠️  Using rule-based generation (no LLM)")
                metadata_fields = self._generate_fairds_fields(
                    doc_info, knowledge_items
                )
            
            # Store fields in state
            state["metadata_fields"] = [
                self._field_to_dict(field) for field in metadata_fields
            ]
            
            # Generate final JSON output
            json_output = self._generate_json_output(
                metadata_fields, doc_info, state
            )
            
            # Store in artifacts
            if "artifacts" not in state:
                state["artifacts"] = {}
            
            state["artifacts"]["metadata_json"] = json.dumps(
                json_output, indent=2, ensure_ascii=False
            )
            
            # Calculate confidence
            confidence = self._calculate_confidence(metadata_fields)
            self.update_confidence(state, "json_generation", confidence)
            
            # Count fields with actual values
            fields_with_values = sum(
                1 for f in metadata_fields 
                if f.value and str(f.value) != f.field_name
            )
            
            self.log_execution(
                state,
                f"✅ JSON generation completed!\n"
                f"   - Total fields: {len(metadata_fields)}\n"
                f"   - Fields with values: {fields_with_values}\n"
                f"   - Required fields: {sum(1 for f in metadata_fields if f.required)}\n"
                f"   - Confidence: {confidence:.2%}"
            )
            
        except Exception as e:
            self.log_execution(
                state, 
                f"❌ JSON generation failed: {str(e)}", 
                "error"
            )
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"JSON generation error: {str(e)}")
            self.update_confidence(state, "json_generation", 0.0)
            # Ensure metadata_fields exists even on error
            if "metadata_fields" not in state:
                state["metadata_fields"] = []
        
        return state
    
    async def _generate_with_llm(
        self,
        doc_info: Dict[str, Any],
        knowledge_items: List[Dict[str, Any]],
        document_text: str,
        critic_feedback: Optional[Dict[str, Any]] = None
    ) -> List[MetadataField]:
        """Generate metadata fields with LLM-based value extraction (adaptive)."""
        # Convert knowledge_items to format expected by select_relevant_metadata_fields
        # knowledge_items has structure: [{"term": "...", "definition": "...", "metadata": {...}}, ...]
        available_fields = []
        for item in knowledge_items:
            term = item.get('term', '')
            metadata = item.get('metadata', {})
            available_fields.append({
                "name": term,  # Use term as name
                "description": item.get('definition', ''),
                "required": metadata.get('required', False),
                "package": metadata.get('package', ''),
                "isa_sheet": metadata.get('isa_sheet', 'study'),
                "metadata": metadata  # Preserve full metadata
            })
        
        # Step 1: Select relevant fields intelligently
        self.logger.info("Step 1: Selecting relevant metadata fields based on document content...")
        selected_fields = await self.llm_helper.select_relevant_metadata_fields(
            doc_info, available_fields, critic_feedback
        )
        
        self.logger.info(f"Selected {len(selected_fields)} relevant fields")
        
        # Step 2: Generate values for selected fields
        self.logger.info("Step 2: Generating metadata values for selected fields...")
        mapped_fields = await self.llm_helper.generate_complete_metadata(
            doc_info, selected_fields, document_text, critic_feedback
        )
        
        # Build lookup for knowledge items (to get FAIR-DS metadata)
        # Use multiple keys for matching: term, name, label (normalized)
        knowledge_lookup = {}
        for item in knowledge_items:
            term = item.get('term', '').lower().strip()
            # Add multiple lookup keys for flexible matching
            knowledge_lookup[term] = item
            # Also add normalized versions (remove spaces, underscores, etc.)
            normalized = term.replace(' ', '').replace('_', '').replace('-', '')
            if normalized and normalized != term:
                knowledge_lookup[normalized] = item
        
        # Also build lookup from selected_fields to preserve original field names
        selected_fields_lookup = {f.get('name', '').lower().strip(): f for f in selected_fields}
        
        # Convert to MetadataField objects with REAL FAIR-DS metadata
        fields = []
        for field_data in mapped_fields:
            field_name = field_data.get('field_name', '')
            field_name_lower = field_name.lower().strip()
            
            # Try multiple matching strategies:
            # 1. Direct match with knowledge_items term
            knowledge_item = knowledge_lookup.get(field_name_lower, None)
            
            # 2. Try normalized match (remove spaces/underscores)
            if not knowledge_item:
                normalized = field_name_lower.replace(' ', '').replace('_', '').replace('-', '')
                knowledge_item = knowledge_lookup.get(normalized, None)
            
            # 3. Try matching with selected_fields original name
            if not knowledge_item:
                original_field = selected_fields_lookup.get(field_name_lower, None)
                if original_field:
                    original_name = original_field.get('name', '').lower().strip()
                    knowledge_item = knowledge_lookup.get(original_name, None)
                    if not knowledge_item:
                        normalized_original = original_name.replace(' ', '').replace('_', '').replace('-', '')
                        knowledge_item = knowledge_lookup.get(normalized_original, None)
            
            # 4. Fuzzy match: find best match in knowledge_items
            if not knowledge_item:
                # Try to find similar field names
                for item in knowledge_items:
                    term = item.get('term', '').lower().strip()
                    # Simple similarity check: if field_name contains term or vice versa
                    if (field_name_lower in term or term in field_name_lower) and len(term) > 3:
                        knowledge_item = item
                        break
            
            # Extract metadata
            if knowledge_item:
                fairds_metadata = knowledge_item.get('metadata', {})
                package_source = fairds_metadata.get('package', 'unknown')
                isa_sheet = fairds_metadata.get('isa_sheet', 'study')
            else:
                # Fallback: try to infer from selected_fields
                original_field = selected_fields_lookup.get(field_name_lower, {})
                fairds_metadata = original_field.get('metadata', {})
                package_source = fairds_metadata.get('package', 'unknown')
                isa_sheet = fairds_metadata.get('isa_sheet', 'study')
            
            field = MetadataField(
                field_name=field_name,
                value=field_data.get('value'),
                evidence=field_data.get('evidence', ''),
                confidence=field_data.get('confidence', 0.5),
                origin="llm_extraction",
                package_source=package_source,  # From FAIR-DS API
                isa_sheet=isa_sheet,  # From FAIR-DS API
                status="provisional" if field_data.get('confidence', 0) < 0.9 else "confirmed",
                data_type=fairds_metadata.get('type', 'string'),
                required=fairds_metadata.get('required', False),
                description=fairds_metadata.get('definition', field_data.get('evidence', '')),
                metadata=fairds_metadata  # Store complete FAIR-DS metadata
            )
            fields.append(field)
        
        return fields
    
    def _generate_fairds_fields(
        self, 
        doc_info: Dict[str, Any], 
        knowledge_items: List[Dict[str, Any]]
    ) -> List[MetadataField]:
        """Generate metadata fields in FAIR-DS format (fallback without LLM)."""
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
        
        # Title
        if doc_info.get("title"):
            fields.append(MetadataField(
                field_name="title",
                value=doc_info["title"],
                evidence="Extracted from document title",
                confidence=0.95,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=True,
                description="Title of the research study or dataset"
            ))
        
        # Description (from abstract)
        if doc_info.get("abstract"):
            fields.append(MetadataField(
                field_name="description",
                value=doc_info["abstract"],
                evidence="Extracted from document abstract",
                confidence=0.95,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=True,
                description="Detailed description of the dataset"
            ))
        
        # Creator (authors)
        if doc_info.get("authors"):
            authors_str = "; ".join(doc_info["authors"])
            fields.append(MetadataField(
                field_name="creator",
                value=authors_str,
                evidence=f"Extracted from document authors",
                confidence=0.95,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=True,
                description="Creator(s) of the dataset"
            ))
        
        # Keywords
        if doc_info.get("keywords"):
            keywords_str = ", ".join(doc_info["keywords"])
            fields.append(MetadataField(
                field_name="keywords",
                value=keywords_str,
                evidence="Extracted from document keywords",
                confidence=0.90,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Keywords describing the dataset"
            ))
        
        # Geographic location
        if doc_info.get("location"):
            fields.append(MetadataField(
                field_name="geographic_location",
                value=doc_info["location"],
                evidence="Extracted from document content",
                confidence=0.85,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Geographic location where data was collected"
            ))
        
        # Coordinates
        if doc_info.get("coordinates"):
            fields.append(MetadataField(
                field_name="coordinates",
                value=doc_info["coordinates"],
                evidence="Extracted from document content",
                confidence=0.90,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Latitude and longitude coordinates"
            ))
        
        # Collection date
        if doc_info.get("collection_date"):
            fields.append(MetadataField(
                field_name="temporal_coverage",
                value=doc_info["collection_date"],
                evidence="Extracted from document content",
                confidence=0.85,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Time period of data collection"
            ))
        
        # Environmental parameters
        if doc_info.get("environmental_parameters"):
            env_params = doc_info["environmental_parameters"]
            for param_name, param_value in env_params.items():
                fields.append(MetadataField(
                    field_name=param_name,
                    value=str(param_value),
                    evidence=f"Extracted environmental parameter from document",
                    confidence=0.80,
                    origin="document_parser",
                    package_source="FAIR-DS",
                    status="provisional",
                    data_type="string",
                    required=False,
                    description=f"Environmental parameter: {param_name}"
                ))
        
        # Instruments
        if doc_info.get("instruments"):
            instruments_str = ", ".join(doc_info["instruments"])
            fields.append(MetadataField(
                field_name="instrument",
                value=instruments_str,
                evidence="Extracted from document content",
                confidence=0.85,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Instruments and equipment used"
            ))
        
        # Methodology
        if doc_info.get("methodology"):
            fields.append(MetadataField(
                field_name="methodology",
                value=doc_info["methodology"],
                evidence="Extracted from document content",
                confidence=0.80,
                origin="document_parser",
                package_source="FAIR-DS",
                status="confirmed",
                data_type="string",
                required=False,
                description="Methods and procedures used"
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
        """Generate ISA-structured metadata template (5 layers) - uses ONLY real FAIR-DS data."""
        
        # Calculate overall confidence
        overall_confidence = sum(f.confidence for f in fields) / len(fields) if fields else 0.0
        
        # Group fields by ISA level based on their actual 'isa_sheet' attribute from FAIR-DS
        fields_by_level = self._group_fields_by_isa_sheet(fields)
        
        # Collect actual packages used (from KnowledgeRetriever, stored in field.package_source)
        packages_used = set()
        for field in fields:
            if hasattr(field, 'package_source') and field.package_source:
                if isinstance(field.package_source, list):
                    packages_used.update(field.package_source)
                else:
                    packages_used.add(field.package_source)
        
        # Build ISA-structured output - NO HARDCODED PACKAGE NAMES
        output = {
            "fairifier_version": "0.2.0",
            "generated_at": datetime.now().isoformat(),
            "document_source": state.get("document_path", ""),
            "overall_confidence": round(overall_confidence, 3),
            "needs_review": state.get("needs_human_review", False),
            
            # Packages used (from FAIR-DS API, selected by LLM)
            "packages_used": sorted(list(packages_used)) if packages_used else [],
            
            # ISA 5-sheet structure (based on actual field.isa_sheet from FAIR-DS)
            "isa_structure": {
                "investigation": {
                    "description": "Investigation-level metadata (project info)",
                    "fields": fields_by_level.get("investigation", [])
                },
                "study": {
                    "description": "Study-level metadata (experimental design)",
                    "fields": fields_by_level.get("study", [])
                },
                "assay": {
                    "description": "Assay-level metadata (measurement details)",
                    "fields": fields_by_level.get("assay", [])
                },
                "sample": {
                    "description": "Sample-level metadata (biological material)",
                    "fields": fields_by_level.get("sample", [])
                },
                "observationunit": {
                    "description": "ObservationUnit-level metadata (individual observations)",
                    "fields": fields_by_level.get("observationunit", [])
                }
            },
            
            # Document information summary
            "document_info": {
                "title": doc_info.get("title"),
                "abstract": doc_info.get("abstract"),
                "authors": doc_info.get("authors", []),
                "keywords": doc_info.get("keywords", []),
                "research_domain": doc_info.get("research_domain")
            },
            
            # Statistics
            "statistics": {
                "total_fields": len(fields),
                "investigation_fields": len(fields_by_level.get("investigation", [])),
                "study_fields": len(fields_by_level.get("study", [])),
                "assay_fields": len(fields_by_level.get("assay", [])),
                "sample_fields": len(fields_by_level.get("sample", [])),
                "observationunit_fields": len(fields_by_level.get("observationunit", [])),
                "confirmed_fields": sum(1 for f in fields if f.status == "confirmed"),
                "provisional_fields": sum(1 for f in fields if f.status == "provisional")
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
    
    def _group_fields_by_isa_sheet(
        self, 
        fields: List[MetadataField]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group metadata fields by ISA sheet based on REAL 'isa_sheet' attribute from FAIR-DS.
        
        NO hardcoded mappings - uses only what FAIR-DS API provides.
        """
        
        grouped = {
            "investigation": [],
            "study": [],
            "assay": [],
            "sample": [],
            "observationunit": []
        }
        
        for field in fields:
            # Use the actual 'isa_sheet' attribute from FAIR-DS metadata
            # This is set by KnowledgeRetriever when it retrieves fields from the API
            isa_sheet = getattr(field, 'isa_sheet', None)
            
            if not isa_sheet:
                # Fallback: try to infer from field metadata if not set
                # Check if field object has metadata dict
                if hasattr(field, 'metadata') and isinstance(field.metadata, dict):
                    isa_sheet = field.metadata.get('isa_sheet')
            
            # If still no isa_sheet, assign to 'study' as default (most common)
            if not isa_sheet or isa_sheet not in grouped:
                isa_sheet = "study"
            
            # Convert field to dict and add to appropriate group
            grouped[isa_sheet].append(self._field_to_dict(field))
        
        return grouped
    
    def _group_fields_by_isa_level_OLD_DEPRECATED(
        self, 
        fields: List[MetadataField],
        doc_info: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        DEPRECATED: This method uses hardcoded field name mappings.
        Use _group_fields_by_isa_sheet instead which uses real FAIR-DS data.
        """
        
        # ISA level mapping based on field characteristics
        level_mapping = {
            # Investigation level - high-level project info
            "investigation": ["title", "description", "identifier", "submission_date", 
                             "public_release_date", "investigation_title", "investigation_description"],
            
            # Study level - study design and scope  
            "study": ["study_title", "study_description", "study_design", "research_domain",
                     "keywords", "methodology", "study_factor"],
            
            # Assay level - measurements and technology
            "assay": ["assay_title", "measurement_type", "technology_type", "technology_platform",
                     "instrument", "protocol"],
            
            # Sample level - biological samples
            "sample": ["sample_id", "sample_type", "organism", "tissue", "developmental_stage"],
            
            # ObservationUnit level - environmental and spatial
            "observationunit": ["geographic_location", "latitude", "longitude", "elevation",
                               "collection_date", "environmental_medium", "temperature", "pH",
                               "salinity", "depth", "environmental_parameters"]
        }
        
        grouped = {
            "investigation": [],
            "study": [],
            "assay": [],
            "sample": [],
            "observationunit": []
        }
        
        # Categorize each field
        for field in fields:
            field_dict = self._field_to_dict(field)
            field_name_lower = field.field_name.lower()
            
            # Find which level this field belongs to
            assigned = False
            for level, level_keywords in level_mapping.items():
                if any(keyword in field_name_lower for keyword in level_keywords):
                    grouped[level].append(field_dict)
                    assigned = True
                    break
            
            # Default to study level if not clearly categorized
            if not assigned:
                grouped["study"].append(field_dict)
        
        return grouped
    
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

