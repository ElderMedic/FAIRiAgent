"""JSON metadata generator for FAIR-DS compatible output."""

import json
from typing import Dict, Any, List, Optional
import re
from datetime import datetime
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, MetadataField
from ..config import config
from ..services.evidence_packets import build_evidence_context
from ..utils.llm_helper import get_llm_helper
from ..services.fairds_api_parser import FAIRDSAPIParser


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
            evidence_packets = state.get("evidence_packets", []) or []
            metadata_gap_hints = state.get("metadata_gap_hints", []) or []
            evidence_context = build_evidence_context(evidence_packets, max_packets=20, max_chars=3200)
            document_context = evidence_context or document_text
            
            self.log_execution(
                state, 
                f"📊 Input: {len(knowledge_items)} knowledge terms from retrieval"
            )
            
            # Get critic feedback if this is a retry
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            prior_memory_context = self.format_retrieved_memories_for_prompt(
                feedback.get("retrieved_memories") or []
            )
            
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
                doc_info, knowledge_items, document_context, critic_feedback, planner_instruction,
                prior_memory_context=prior_memory_context or None
            )
            self.log_execution(
                state, 
                f"✅ LLM generated {len(metadata_fields)} fields with values"
            )
            
            # Store fields in state
            state["metadata_fields"] = [
                self._field_to_dict(field) for field in metadata_fields
            ]
            state["inferred_metadata_extensions"] = self._build_inferred_metadata_extensions(
                metadata_gap_hints,
                doc_info,
                evidence_packets,
            )
            
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
        planner_instruction: Optional[str] = None,
        prior_memory_context: Optional[str] = None
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
            isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(
                metadata.get("isa_sheet") or metadata.get("sheet")
            )
            selected_fields.append({
                "name": term,  # Use term as name
                "description": item.get('definition', ''),
                "required": metadata.get('required', False),
                "package": metadata.get('package', ''),
                "isa_sheet": isa_sheet,
                "metadata": metadata  # Preserve full metadata
            })
        
        self.logger.info(
            f"Using all {len(selected_fields)} fields from KnowledgeRetriever "
            f"(already filtered for relevance - no additional selection needed)"
        )
        
        # Generate values for all selected fields
        self.logger.info("Generating metadata values for all selected fields...")
        mapped_fields = await self.llm_helper.generate_complete_metadata(
            doc_info, selected_fields, document_text, critic_feedback, planner_instruction,
            prior_memory_context=prior_memory_context
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
                isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(
                    fairds_metadata.get("isa_sheet") or fairds_metadata.get("sheet")
                )
            else:
                # Fallback: try to infer from selected_fields
                original_field = selected_fields_lookup.get(field_name_lower, {})
                fairds_metadata = original_field.get('metadata', {})
                package_source = fairds_metadata.get('package', 'unknown')
                isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(
                    fairds_metadata.get("isa_sheet") or fairds_metadata.get("sheet")
                )
            
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
        normalized_sheet = FAIRDSAPIParser.normalize_isa_sheet(field.isa_sheet)
        return {
            "field_name": field.field_name,
            "value": field.value,
            "evidence": field.evidence,
            "confidence": field.confidence,
            "origin": field.origin,
            "package_source": field.package_source,
            "status": field.status,
            "isa_sheet": normalized_sheet,
            "isa_level": normalized_sheet,
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
            "fairifier_version": "V1.3.0",
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
            "evidence_packets_summary": {
                "count": len(state.get("evidence_packets", []) or []),
                "fields": sorted(
                    {
                        packet.get("field_candidate")
                        for packet in (state.get("evidence_packets", []) or [])
                        if packet.get("field_candidate")
                    }
                )[:20],
            },
            "inferred_metadata_extensions": state.get("inferred_metadata_extensions", []),
            
            # Statistics
            "statistics": {
                "total_fields": len(fields),
                "investigation_fields": len(fields_by_level.get("investigation", [])),
                "study_fields": len(fields_by_level.get("study", [])),
                "assay_fields": len(fields_by_level.get("assay", [])),
                "sample_fields": len(fields_by_level.get("sample", [])),
                "observationunit_fields": len(fields_by_level.get("observationunit", [])),
                "confirmed_fields": sum(1 for f in fields if f.status == "confirmed"),
                "provisional_fields": sum(1 for f in fields if f.status == "provisional"),
                "inferred_extension_fields": len(state.get("inferred_metadata_extensions", [])),
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

        if state.get("inferred_metadata_extensions"):
            output["warnings"].append(
                f"{len(state['inferred_metadata_extensions'])} metadata extensions were inferred outside the current FAIR-DS package set."
            )
        
        return output

    def _build_inferred_metadata_extensions(
        self,
        metadata_gap_hints: List[Dict[str, Any]],
        doc_info: Dict[str, Any],
        evidence_packets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build a lightweight extension block for metadata concepts not covered by FAIR-DS."""
        extensions: List[Dict[str, Any]] = []
        seen_labels: set[str] = set()
        for hint in metadata_gap_hints[:20]:
            label = self._normalize_extension_label(
                hint.get("label"),
                source=hint.get("source"),
            )
            if not label:
                continue
            lowered = label.lower()
            if lowered in seen_labels:
                continue
            seen_labels.add(lowered)
            packet = self._select_supporting_packet(label, evidence_packets, hint)
            value, evidence, confidence = self._infer_extension_value(label, doc_info, packet, hint)
            extensions.append(
                {
                    "field_name": label,
                    "value": value,
                    "evidence": evidence,
                    "confidence": confidence,
                    "status": "provisional_extension",
                    "reason": hint.get("reason"),
                    "source": hint.get("source"),
                    "fairds_status": "not_covered_by_current_package_set",
                }
            )
        return extensions

    def _normalize_extension_label(self, raw_label: Any, source: Optional[str] = None) -> str:
        """Keep extension labels concise and semantic (avoid sentence-like noise)."""
        label = str(raw_label or "").strip()
        if not label:
            return ""
        replacements = [
            "No FAIR-DS package for ",
            "No standardized field for ",
            "No field for ",
        ]
        for prefix in replacements:
            if label.startswith(prefix):
                label = label[len(prefix):].strip()
                break
        if label.startswith("No "):
            label = label[3:].strip()

        # Planner/package hints sometimes arrive as full explanatory sentences.
        # Convert these to compact concept-like labels for output readability.
        if source == "package_request":
            compact = self._compress_extension_sentence(label)
            if compact:
                label = compact

        if len(label) > 96:
            label = label[:96].rstrip(" ,;.")
        return label

    def _compress_extension_sentence(self, label: str) -> str:
        """Compress long planner-style sentences into short semantic labels."""
        text = " ".join(str(label or "").split()).strip(" .")
        if not text:
            return ""

        lower = text.lower()
        concept_map = [
            (["mfdo", "habitat classification"], "MFDO habitat classification mapping"),
            (["pacbio", "nanopore", "platform"], "PacBio/Nanopore assay metadata"),
            (["repository", "bioproject", "zenodo", "ena"], "repository accession linkage"),
            (["orcid", "crossref", "doi", "publication"], "publication contributor linkage"),
            (["gtdb", "silva", "pr2", "greengenes", "taxonomy"], "reference taxonomy database provenance"),
            (["latitude", "longitude", "gps", "coordinate"], "sample coordinate completeness"),
            (["water", "chemistry"], "water chemistry measurement coverage"),
            (["mag", "mimags", "assembly quality", "completeness", "contamination", "binning"], "MAG quality metrics completeness"),
        ]
        for tokens, normalized in concept_map:
            if any(token in lower for token in tokens):
                return normalized

        # Fallback: keep only the first clause and trim to concise phrase length.
        clause = re.split(r"[.;:]", text, maxsplit=1)[0]
        clause = re.split(r", but |, and | but | and ", clause, maxsplit=1, flags=re.IGNORECASE)[0]
        words = clause.split()
        if len(words) > 8:
            clause = " ".join(words[:8])
        return clause.strip(" ,;.")

    def _select_supporting_packet(
        self,
        label: str,
        evidence_packets: List[Dict[str, Any]],
        hint: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Pick the most relevant evidence packet for a metadata gap hint."""
        requested_packet_id = hint.get("packet_id")
        if requested_packet_id:
            for packet in evidence_packets:
                if packet.get("packet_id") == requested_packet_id:
                    return packet

        label_tokens = {
            token for token in label.lower().replace("-", " ").replace("_", " ").split()
            if len(token) > 2
        }
        best_packet: Optional[Dict[str, Any]] = None
        best_score = 0
        for packet in evidence_packets[:30]:
            haystack = " ".join(
                str(packet.get(key, ""))
                for key in ["field_candidate", "value", "evidence_text", "section"]
            ).lower()
            score = sum(1 for token in label_tokens if token in haystack)
            if score > best_score:
                best_score = score
                best_packet = packet
        return best_packet

    def _infer_extension_value(
        self,
        label: str,
        doc_info: Dict[str, Any],
        packet: Optional[Dict[str, Any]],
        hint: Dict[str, Any],
    ) -> tuple[str, str, float]:
        """Infer a provisional value for a metadata extension without an extra LLM call."""
        normalized_label = label.lower().strip()
        for key, value in doc_info.items():
            if str(key).lower().strip() == normalized_label and value:
                return (
                    self._clip_text(str(value), max_chars=260),
                    self._clip_text(f"DocumentParser field: {key}", max_chars=180),
                    0.78,
                )

        if packet:
            packet_value = packet.get("value") or packet.get("supporting_value")
            packet_evidence = packet.get("evidence_text") or packet.get("supporting_evidence") or packet.get("section")
            if packet_value:
                return (
                    self._clip_text(str(packet_value), max_chars=260),
                    self._clip_text(str(packet_evidence or "Evidence packet"), max_chars=220),
                    round(min(float(packet.get("confidence") or 0.6), 0.82), 2),
                )

        support = hint.get("supporting_value") or hint.get("supporting_evidence")
        if support:
            return (
                self._clip_text(str(support), max_chars=260),
                self._clip_text(
                    str(
                        hint.get("supporting_evidence")
                        or "KnowledgeRetriever metadata gap hint"
                    ),
                    max_chars=220,
                ),
                round(min(float(hint.get("confidence") or 0.55), 0.75), 2),
            )

        return (
            "not explicitly captured in FAIR-DS package set",
            self._clip_text(
                "Planner/KnowledgeRetriever identified this metadata concept but FAIR-DS had no direct package/field match",
                max_chars=220,
            ),
            round(min(float(hint.get("confidence") or 0.45), 0.65), 2),
        )

    def _clip_text(self, value: str, max_chars: int) -> str:
        """Clip noisy long strings in extension output while keeping readability."""
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip(" ,;:.") + "..."

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

        # Handle nested structure: if doc_info has "metadata" key, extract it
        if "metadata" in doc_info and isinstance(doc_info["metadata"], dict):
            doc_info = doc_info["metadata"]

        # Title: direct or from common variants / first short key_information item
        title = (
            doc_info.get("title")
            or doc_info.get("investigation_title")
            or doc_info.get("project_title")
            or doc_info.get("study_title")
            or doc_info.get("document_title")
        )
        
        # Check nested metadata_for_fair_principles
        if not title:
            fair_meta = doc_info.get("metadata_for_fair_principles")
            if isinstance(fair_meta, dict):
                title = fair_meta.get("title")
        
        # Extract title from summary if it looks like a title (short first sentence)
        if not title and doc_info.get("summary"):
            summary_text = doc_info["summary"]
            if isinstance(summary_text, str):
                # Try to extract first sentence as potential title
                import re
                first_sentence = re.split(r'[.!?]\s+', summary_text, maxsplit=1)[0]
                if 10 <= len(first_sentence) <= 250:
                    title = first_sentence.strip()
        
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
            or doc_info.get("project_abstract")
            or doc_info.get("study_abstract")
        )
        
        # Check nested metadata_for_fair_principles
        if not abstract:
            fair_meta = doc_info.get("metadata_for_fair_principles")
            if isinstance(fair_meta, dict):
                abstract = fair_meta.get("abstract")
        
        if not abstract and isinstance(doc_info.get("key_information"), list):
            for item in doc_info["key_information"]:
                if isinstance(item, str) and len(item) > 200:
                    abstract = item
                    break

        # Authors: direct list or personnel/consortium (normalize to list of dicts or strings)
        authors = doc_info.get("authors") or doc_info.get("investigators") or doc_info.get("personnel")
        
        if not authors and doc_info.get("consortium"):
            raw = doc_info["consortium"]
            authors = raw if isinstance(raw, list) else [raw]
            
        if authors is None:
            authors = []
        if not isinstance(authors, list):
            authors = [authors] if authors else []
        
        # Normalize authors: if they're dicts, keep as dicts; if strings, keep as strings
        normalized_authors = []
        for author in authors:
            if author:  # Skip empty values
                if isinstance(author, dict):
                    # Keep dict structure, but ensure it has at least a 'name' field
                    if 'name' in author or 'full_name' in author or any(k in author for k in ['first_name', 'last_name']):
                        normalized_authors.append(author)
                    else:
                        # Dict without name fields, convert to string
                        normalized_authors.append(str(author))
                elif isinstance(author, str):
                    normalized_authors.append(author)
                else:
                    normalized_authors.append(str(author))
        authors = normalized_authors

        # Keywords: direct or use key_information if list of short strings
        keywords = doc_info.get("keywords") or doc_info.get("tags") or doc_info.get("topics")
        
        if not keywords and isinstance(doc_info.get("key_information"), list):
            short_strings = [x for x in doc_info["key_information"] if isinstance(x, str) and 0 < len(x) <= 150]
            if short_strings:
                keywords = short_strings[:20]
                
        if keywords is None:
            keywords = []
        if not isinstance(keywords, list):
            keywords = [keywords] if keywords else []
        
        # Clean keywords - convert any non-string items
        keywords = [str(k) if not isinstance(k, str) else k for k in keywords if k]

        # Research domain: direct or from scientific_domain (dict with primary_field / subfields)
        research_domain = (
            doc_info.get("research_domain") 
            or doc_info.get("domain") 
            or doc_info.get("scientific_domain")
            or doc_info.get("field_of_study")
            or doc_info.get("research_area")
        )
        
        # If research_domain is a dict, extract meaningful value
        if isinstance(research_domain, dict):
            sd = research_domain
            primary = sd.get("primary_field") or sd.get("domain") or sd.get("field")
            subfields = sd.get("subfields") or sd.get("subdomains") or []
            if primary:
                research_domain = primary if not subfields else f"{primary} ({', '.join(str(s) for s in subfields[:5])})"
            else:
                research_domain = None
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
            isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(getattr(field, 'isa_sheet', None))
            
            if not isa_sheet or isa_sheet == "study":
                # Fallback: try to infer from field metadata if not set
                # Check if field object has metadata dict
                if hasattr(field, 'metadata') and isinstance(field.metadata, dict):
                    isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(
                        field.metadata.get('isa_sheet') or field.metadata.get("sheet")
                    )
            
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
    
    def get_memory_query_hint(self, state: FAIRifierState) -> Optional[str]:
        """
        Generate memory query hint for JSONGenerator.
        
        Focuses on: field mapping examples, value generation patterns, and ontology URIs
        for the specific packages being used.
        
        Args:
            state: Current workflow state
            
        Returns:
            Query hint string for memory retrieval, or None for default
        """
        packages = state.get("selected_packages", [])
        doc_info = state.get("document_info", {})
        domain = doc_info.get("research_domain", "")
        
        if packages:
            # Use first 3 packages for specificity
            pkg_str = ", ".join(packages[:3])
            base_query = (
                f"Field mapping examples, value generation patterns, and ontology URIs "
                f"for packages: {pkg_str}"
            )
            if domain:
                base_query += f" in {domain} domain"
            return base_query
        else:
            return "FAIR metadata field mapping and value generation best practices"
