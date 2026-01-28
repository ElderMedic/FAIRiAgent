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
    
    def __init__(self):
        super().__init__("JSONGenerator")
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
            
            # Get critic feedback if this is a retry
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            
            if critic_feedback:
                self.log_execution(state, "🔄 Retrying metadata generation with Critic feedback...")
                critique = critic_feedback.get("critique")
                if critique:
                    self.log_execution(state, f"   Critique: {critique}")
                for idx, suggestion in enumerate(critic_feedback.get("suggestions", []), 1):
                    self.log_execution(state, f"   🔧 Suggestion {idx}: {suggestion}")
            if planner_instruction:
                self.log_execution(state, f"🧭 Planner guidance: {planner_instruction}")
            if guidance_history:
                self.log_execution(state, f"🧾 Historical guidance: {guidance_history}")
            
            self.log_execution(
                state, 
                f"🤖 Using LLM to generate values for all {len(knowledge_items)} fields "
                f"from KnowledgeRetriever (already filtered for relevance)"
            )
            metadata_fields = await self._generate_with_llm(
                doc_info, knowledge_items, document_text, critic_feedback, planner_instruction
            )
            self.log_execution(
                state, 
                f"✅ LLM generated {len(metadata_fields)} fields with values"
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
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None
    ) -> List[MetadataField]:
        """
        Generate metadata fields with LLM-based value extraction.
        
        Note: knowledge_items are already intelligently selected by KnowledgeRetriever
        based on document relevance. We use ALL of them to maximize metadata coverage
        while maintaining relevance.
        """
        # Convert knowledge_items to format expected by generate_complete_metadata
        # knowledge_items has structure: [{"term": "...", "definition": "...", "metadata": {...}}, ...]
        # These are already filtered for relevance by KnowledgeRetriever, so we use all of them
        selected_fields = []
        for item in knowledge_items:
            term = item.get('term', '')
            metadata = item.get('metadata', {})
            selected_fields.append({
                "name": term,  # Use term as name
                "description": item.get('definition', ''),
                "required": metadata.get('required', False),
                "package": metadata.get('package', ''),
                "isa_sheet": metadata.get('isa_sheet', 'study'),
                "metadata": metadata  # Preserve full metadata
            })
        
        self.logger.info(
            f"Using all {len(selected_fields)} fields from KnowledgeRetriever "
            f"(already filtered for relevance - no additional selection needed)"
        )
        
        # Generate values for all selected fields
        self.logger.info("Generating metadata values for all selected fields...")
        mapped_fields = await self.llm_helper.generate_complete_metadata(
            doc_info, selected_fields, document_text, critic_feedback, planner_instruction
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
        
        # Build lookup from selected_fields to preserve original field names
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
            "fairifier_version": "V1.0.1",
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
            
            # Document information summary (compact view; derived from flexible LLM extraction)
            "document_info": self._build_document_info_compact(doc_info),
            
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

    def _build_document_info_compact(self, doc_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build the compact document_info block (title, abstract, authors, keywords, research_domain)
        from the flexible document_info returned by DocumentParser/LLM.

        The LLM may return different keys (e.g. document_type, scientific_domain, key_information,
        metadata_for_fair_principles) instead of title/abstract/authors. This method maps those
        into the fixed compact schema so the output JSON always has a populated document_info.
        """
        if not doc_info:
            return {
                "title": None,
                "abstract": None,
                "authors": [],
                "keywords": [],
                "research_domain": None
            }

        # Title: direct or from common variants / first short key_information item
        title = (
            doc_info.get("title")
            or doc_info.get("investigation_title")
            or (doc_info.get("metadata_for_fair_principles") or {}).get("title") if isinstance(doc_info.get("metadata_for_fair_principles"), dict) else None
        )
        if not title and isinstance(doc_info.get("key_information"), list):
            for item in doc_info["key_information"]:
                if isinstance(item, str) and 10 <= len(item) <= 200:
                    title = item
                    break

        # Abstract: direct or from summary/description / first long key_information string
        abstract = (
            doc_info.get("abstract")
            or doc_info.get("summary")
            or doc_info.get("description")
            or doc_info.get("investigation_description")
            or (doc_info.get("metadata_for_fair_principles") or {}).get("abstract") if isinstance(doc_info.get("metadata_for_fair_principles"), dict) else None
        )
        if not abstract and isinstance(doc_info.get("key_information"), list):
            for item in doc_info["key_information"]:
                if isinstance(item, str) and len(item) > 200:
                    abstract = item
                    break

        # Authors: direct list or personnel/consortium (normalize to list of strings)
        authors = doc_info.get("authors")
        if not authors and doc_info.get("personnel"):
            authors = doc_info["personnel"] if isinstance(doc_info["personnel"], list) else [doc_info["personnel"]]
        if not authors and doc_info.get("consortium"):
            raw = doc_info["consortium"]
            authors = raw if isinstance(raw, list) else [raw]
        if authors is None:
            authors = []
        if not isinstance(authors, list):
            authors = [authors] if authors else []
        authors = [str(a) for a in authors if a]

        # Keywords: direct or use key_information if list of short strings
        keywords = doc_info.get("keywords")
        if not keywords and isinstance(doc_info.get("key_information"), list):
            short_strings = [x for x in doc_info["key_information"] if isinstance(x, str) and 0 < len(x) <= 150]
            if short_strings:
                keywords = short_strings[:20]
        if keywords is None:
            keywords = []
        if not isinstance(keywords, list):
            keywords = [keywords] if keywords else []

        # Research domain: direct or from scientific_domain (dict with primary_field / subfields)
        research_domain = doc_info.get("research_domain") or doc_info.get("domain")
        if not research_domain and isinstance(doc_info.get("scientific_domain"), dict):
            sd = doc_info["scientific_domain"]
            primary = sd.get("primary_field") or sd.get("domain")
            subfields = sd.get("subfields") or []
            if primary:
                research_domain = primary if not subfields else f"{primary} ({', '.join(subfields[:5])})"
        if not research_domain and isinstance(doc_info.get("scientific_domain"), str):
            research_domain = doc_info["scientific_domain"]

        return {
            "title": title or None,
            "abstract": abstract or None,
            "authors": authors,
            "keywords": keywords,
            "research_domain": research_domain or None
        }

    def _group_fields_by_isa_sheet(
        self, 
        fields: List[MetadataField]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group metadata fields by ISA sheet based on REAL 'isa_sheet' attribute from FAIR-DS.
        
        NO hardcoded mappings - uses only what FAIR-DS API provides.
        
        Deduplicates fields: For each ISA sheet, keeps only one field per field_name.
        If duplicates exist, keeps the one with highest confidence.
        """
        
        grouped = {
            "investigation": [],
            "study": [],
            "assay": [],
            "sample": [],
            "observationunit": []
        }
        
        # Track seen fields per ISA sheet: {isa_sheet: {field_name: (field_dict, confidence)}}
        seen_fields = {sheet: {} for sheet in grouped.keys()}
        
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
            
            # Convert field to dict
            field_dict = self._field_to_dict(field)
            field_name = field_dict.get("field_name", "").lower().strip()
            confidence = field_dict.get("confidence", 0.0)
            
            # Deduplicate: keep only the field with highest confidence for each field_name
            if field_name in seen_fields[isa_sheet]:
                existing_confidence = seen_fields[isa_sheet][field_name][1]
                if confidence > existing_confidence:
                    # Replace with higher confidence field
                    seen_fields[isa_sheet][field_name] = (field_dict, confidence)
            else:
                # First occurrence of this field_name in this ISA sheet
                seen_fields[isa_sheet][field_name] = (field_dict, confidence)
        
        # Build final grouped structure from deduplicated fields
        for isa_sheet, field_dicts in seen_fields.items():
            grouped[isa_sheet] = [fd[0] for fd in field_dicts.values()]
        
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

