"""JSON metadata generator for FAIR-DS compatible output."""

import json
from typing import Dict, Any, List, Optional
import re
from datetime import datetime
from pathlib import Path
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
            workspace_context = self._build_source_workspace_context(
                state.get("source_workspace", {}) or {}
            )
            context_parts = [part for part in (evidence_context, workspace_context) if part]
            document_context = "\n\n".join(context_parts)
            if not document_context and config.metadata_allow_direct_document_fallback:
                document_context = document_text
            
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
                doc_info,
                knowledge_items,
                document_context,
                critic_feedback,
                planner_instruction,
                prior_memory_context=prior_memory_context or None,
                selected_packages=state.get("selected_packages"),
            )
            metadata_fields = self._ensure_mandatory_fields_present(
                metadata_fields=metadata_fields,
                knowledge_items=knowledge_items,
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

    def _build_source_workspace_context(self, source_workspace: Dict[str, Any]) -> str:
        """Build a compact source inventory for metadata generation prompts."""
        summary_path = source_workspace.get("summary_path")
        if not summary_path:
            return ""
        try:
            summary = Path(summary_path).read_text(encoding="utf-8")
        except OSError:
            return ""
        budget = max(1, int(config.metadata_max_context_chars_per_field))
        if len(summary) > budget:
            keep = max(1, budget - 80)
            summary = (
                summary[:keep].rstrip()
                + "\n[... source workspace inventory truncated by configurable metadata budget ...]"
            )
        return (
            "Source workspace inventory:\n"
            "Use source_id/path references in evidence when possible. "
            "Full source files are preserved in the run output source_workspace directory.\n"
            f"{summary}"
        )
    
    async def _generate_with_llm(
        self,
        doc_info: Dict[str, Any],
        knowledge_items: List[Dict[str, Any]],
        document_text: str,
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None,
        prior_memory_context: Optional[str] = None,
        selected_packages: Optional[List[str]] = None,
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
        
        # Order items so KnowledgeRetriever's selected_packages wins duplicate MIxS labels
        pref_index = {
            str(p).strip().lower(): i
            for i, p in enumerate(selected_packages or [])
            if str(p).strip()
        }

        def _pkg_order(item: Dict[str, Any]) -> tuple[int, str]:
            pkg = str(item.get("metadata", {}).get("package", "")).strip().lower()
            return (pref_index.get(pkg, 10_000), pkg)

        knowledge_items_ordered = sorted(knowledge_items, key=_pkg_order)

        # Build lookup for knowledge items (to get FAIR-DS metadata)
        # Use multiple keys for matching: term, name, label (normalized)
        knowledge_lookup: Dict[str, Dict[str, Any]] = {}
        for item in knowledge_items_ordered:
            term = item.get('term', '').lower().strip()
            if not term:
                continue
            if term not in knowledge_lookup:
                knowledge_lookup[term] = item
            normalized = term.replace(' ', '').replace('_', '').replace('-', '')
            if normalized and normalized != term and normalized not in knowledge_lookup:
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
            
            # 4. Fuzzy match: find best match (prefer packages earlier in selected_packages)
            if not knowledge_item:
                for item in knowledge_items_ordered:
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
        metadata = field.metadata if isinstance(field.metadata, dict) else {}
        requirement = str(metadata.get("requirement", "")).strip().upper()
        if requirement not in {"MANDATORY", "RECOMMENDED", "OPTIONAL"}:
            requirement = "MANDATORY" if field.required else "OPTIONAL"
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
            "required": requirement == "MANDATORY",
            "requirement": requirement,
        }

    def _is_mandatory_metadata_item(self, metadata: Dict[str, Any]) -> bool:
        """Return True if FAIR-DS metadata marks the field as mandatory."""
        if not isinstance(metadata, dict):
            return False
        requirement = str(metadata.get("requirement", "")).strip().upper()
        if requirement == "MANDATORY":
            return True
        return bool(metadata.get("required"))

    def _normalize_field_key(self, value: Any) -> str:
        """Normalize labels for coverage checks."""
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip().split()
        )

    def _ensure_mandatory_fields_present(
        self,
        metadata_fields: List[MetadataField],
        knowledge_items: List[Dict[str, Any]],
    ) -> List[MetadataField]:
        """Guarantee mandatory FAIR-DS fields from retrieval are present in output."""
        if not metadata_fields:
            metadata_fields = []
        existing_names = {
            self._normalize_field_key(field.field_name)
            for field in metadata_fields
            if getattr(field, "field_name", None)
        }
        injected_count = 0
        for item in knowledge_items:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata", {}) or {}
            if not self._is_mandatory_metadata_item(metadata):
                continue
            label = str(item.get("term") or metadata.get("label") or "").strip()
            normalized_label = self._normalize_field_key(label)
            if not normalized_label:
                continue
            if normalized_label in existing_names:
                continue
            isa_sheet = FAIRDSAPIParser.normalize_isa_sheet(
                metadata.get("isa_sheet") or metadata.get("sheet")
            )
            metadata_fields.append(
                MetadataField(
                    field_name=label,
                    value=None,
                    evidence="Mandatory field injected from FAIR-DS package selection.",
                    confidence=0.0,
                    origin="mandatory_enforcement",
                    package_source=metadata.get("package"),
                    isa_sheet=isa_sheet,
                    status="provisional",
                    data_type=metadata.get("type", "string"),
                    required=True,
                    description=metadata.get("definition") or item.get("definition"),
                    metadata=metadata,
                )
            )
            existing_names.add(normalized_label)
            injected_count += 1
        if injected_count:
            self.logger.info(
                "Injected %s mandatory field(s) that were missing from LLM output.",
                injected_count,
            )
        return metadata_fields
    
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
            "fairifier_version": "V1.3.1",
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
            "multi_file_parse_summary": {
                "source_count": len(state.get("document_info_by_source", []) or []),
                "sources": [
                    {
                        "source_path": item.get("source_path"),
                        "field_count": item.get("field_count"),
                        "status": item.get("status"),
                    }
                    for item in (state.get("document_info_by_source", []) or [])[:20]
                    if isinstance(item, dict)
                ],
            },
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
            suggested_isa_level, suggested_requirement = self._infer_extension_schema(label, hint)
            extensions.append(
                {
                    "field_name": label,
                    "value": value,
                    "evidence": evidence,
                    "confidence": confidence,
                    "suggested_isa_level": suggested_isa_level,
                    "suggested_requirement": suggested_requirement,
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
            "FAIR-DS fields for ",
            "FAIR-DS field for ",
            "FAIR-DS package specific to ",
            "FAIR-DS package for ",
        ]
        for prefix in replacements:
            if label.lower().startswith(prefix.lower()):
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

        concept_label = self._canonical_extension_label(label)
        if concept_label:
            label = concept_label

        label = re.sub(
            r"\b(not represented|not captured|not covered|outside fair-?ds.*)$",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip(" ,;:.")
        if len(label) > 64:
            label = label[:64]
            if " " in label:
                label = label.rsplit(" ", 1)[0]
            label = label.strip(" ,;:.")
        while label.lower().endswith((" not", " and", " or", " but")):
            label = label.rsplit(" ", 1)[0].strip(" ,;:.")
        label = self._repair_unbalanced_label(label)
        return label

    def _canonical_extension_label(self, label: str) -> str:
        """Map noisy search concepts to concise metadata-style labels."""
        text = " ".join(str(label or "").split()).strip(" .")
        lower = text.lower()
        concept_map = [
            (
                ["de novo transcriptome assembly", "transcriptome assembly"],
                "transcriptome assembly method",
            ),
            (
                ["gene ontology enrichment", "go enrichment"],
                "gene ontology enrichment analysis",
            ),
            (["analysis pipeline", "deseq2", "masigpro"], "analysis pipeline"),
            (
                ["bioinformatics quality control", "quality control metric"],
                "bioinformatics quality metric",
            ),
            (
                ["time-series experimental design", "time series experimental design"],
                "time-series design",
            ),
            (["nanomaterial characterization"], "nanomaterial characterization"),
            (["toxicology", "ecotoxicology", "exposure"], "exposure domain"),
            (["icp-oes", "icp-ms", "elemental analysis"], "elemental analysis method"),
            (["library strategy", "rna-seq"], "library strategy"),
            (["library source"], "library source"),
            (["experimental factor"], "experimental factor"),
            (
                ["chemical administration", "chemical perturbation", "perturbation"],
                "chemical perturbation",
            ),
            (["differential gene expression"], "analysis method"),
            (["soil exposure"], "exposure environment"),
            (["transcriptomics"], "assay type"),
        ]
        for tokens, normalized in concept_map:
            if any(token in lower for token in tokens):
                return normalized
        if re.fullmatch(r"[A-Z][a-z]+ [a-z]+", text):
            return "organism"
        if re.search(r"\b(zno|nanomaterial|nanoparticle|mncl2)\b", lower):
            return "exposure material"
        return ""

    def _repair_unbalanced_label(self, label: str) -> str:
        """Avoid labels ending in truncated punctuation such as an open parenthesis."""
        text = str(label or "").strip(" ,;:.")
        if text.count("(") > text.count(")"):
            text = text.rsplit("(", 1)[0].strip(" ,;:.")
        if text.count("[") > text.count("]"):
            text = text.rsplit("[", 1)[0].strip(" ,;:.")
        return text

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

    def _extension_concept_tokens(self, label: str) -> set[str]:
        """Extract informative tokens for evidence matching."""
        stop = {
            "fair", "fields", "field", "package", "specific", "metadata",
            "method", "methods", "metric", "metrics", "result", "results",
            "analysis", "assay", "type", "domain", "source", "strategy",
            "study", "sample", "experimental",
        }
        normalized = re.sub(r"[^a-zA-Z0-9]+", " ", str(label or "").lower())
        return {
            token for token in normalized.split()
            if len(token) > 2 and token not in stop
        }

    def _packet_relevance_score(self, label: str, packet: Dict[str, Any]) -> int:
        tokens = self._extension_concept_tokens(label)
        if not tokens:
            return 0
        haystack = " ".join(
            str(packet.get(key, ""))
            for key in ["field_candidate", "value", "evidence_text", "section"]
        ).lower()
        return sum(1 for token in tokens if token in haystack)

    def _select_supporting_packet(
        self,
        label: str,
        evidence_packets: List[Dict[str, Any]],
        hint: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Pick the most relevant evidence packet for a metadata gap hint."""
        requested_packet_id = hint.get("packet_id")
        evidence_label = f"{label} {hint.get('label') or ''}"
        if requested_packet_id:
            for packet in evidence_packets:
                if (
                    packet.get("packet_id") == requested_packet_id
                    and self._packet_relevance_score(evidence_label, packet) > 0
                ):
                    return packet

        best_packet: Optional[Dict[str, Any]] = None
        best_score = 0
        for packet in evidence_packets[:30]:
            score = self._packet_relevance_score(evidence_label, packet)
            if score > best_score:
                best_score = score
                best_packet = packet
        return best_packet if best_score > 0 else None

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
            packet_evidence = (
                packet.get("evidence_text")
                or packet.get("supporting_evidence")
                or packet.get("section")
            )
            if packet_value:
                packet_confidence = float(packet.get("confidence") or hint.get("confidence") or 0.6)
                return (
                    self._clip_text(str(packet_value), max_chars=260),
                    self._clip_text(str(packet_evidence or "Evidence packet"), max_chars=220),
                    round(max(0.45, min(packet_confidence - 0.08, 0.84)), 2),
                )

        support = hint.get("supporting_value") or hint.get("supporting_evidence")
        supporting_evidence = str(hint.get("supporting_evidence") or "")
        if support and self._text_matches_extension_label(label, str(support), supporting_evidence):
            return (
                self._clip_text(str(support), max_chars=260),
                self._clip_text(
                    str(
                        supporting_evidence
                        or "KnowledgeRetriever metadata gap hint"
                    ),
                    max_chars=220,
                ),
                round(max(0.4, min(float(hint.get("confidence") or 0.55) - 0.1, 0.72)), 2),
            )

        return (
            "not reported in source evidence",
            self._clip_text(
                "No source excerpt matched this inferred metadata concept.",
                max_chars=220,
            ),
            round(max(0.3, min(float(hint.get("confidence") or 0.45) - 0.18, 0.62)), 2),
        )

    def _text_matches_extension_label(self, label: str, *texts: str) -> bool:
        tokens = self._extension_concept_tokens(label)
        if not tokens:
            return False
        haystack = " ".join(str(text or "") for text in texts).lower()
        return any(token in haystack for token in tokens)

    def _infer_extension_schema(
        self,
        label: str,
        hint: Dict[str, Any],
    ) -> tuple[str, str]:
        """Infer where an extension would likely sit if curated into FAIR-DS."""
        text = " ".join(
            [
                str(label or ""),
                str(hint.get("label") or ""),
                str(hint.get("reason") or ""),
            ]
        ).lower()
        if any(
            token in text
            for token in ["organism", "exposure", "material", "environment", "nanomaterial"]
        ):
            isa_level = "sample"
        elif any(
            token in text
            for token in [
                "library", "rna-seq", "sequencing", "assay", "analysis",
                "pipeline", "assembly", "ontology", "quality",
            ]
        ):
            isa_level = "assay"
        elif any(token in text for token in ["domain", "design"]):
            isa_level = "study"
        else:
            isa_level = "study"

        if any(token in text for token in ["required", "mandatory", "identifier", "accession"]):
            requirement = "mandatory"
        elif "not reported" in text or "gap" in text:
            requirement = "recommended"
        else:
            requirement = "recommended"
        return isa_level, requirement

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
