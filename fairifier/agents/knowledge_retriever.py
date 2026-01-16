"""Knowledge retrieval agent using FAIR Data Station API."""

import json
import logging
from typing import Dict, Any, List, Optional
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, KnowledgeItem
from ..config import config
from ..services.fair_data_station import FAIRDataStationClient
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.llm_helper import get_llm_helper
from . import knowledge_retriever_llm_methods as llm_methods

logger = logging.getLogger(__name__)


class KnowledgeRetrieverAgent(BaseAgent):
    """Agent for retrieving knowledge from FAIR Data Station."""
    
    def __init__(self):
        super().__init__("KnowledgeRetriever")
        self.llm_helper = get_llm_helper()
        
        # Initialize FAIR-DS client if configured
        self.fair_ds_client = None
        if config.fair_ds_api_url:
            try:
                self.fair_ds_client = FAIRDataStationClient(
                    config.fair_ds_api_url
                )
                if self.fair_ds_client.is_available():
                    self.log_info("✅ FAIR-DS API is available")
                else:
                    self.log_info("⚠️  FAIR-DS API not responding")
                    self.fair_ds_client = None
            except Exception as e:
                self.log_info(f"⚠️  Failed to connect to FAIR-DS: {e}")
                self.fair_ds_client = None
        else:
            self.log_info("⚠️  FAIR-DS API URL not available, using local fallback")
    
    def log_info(self, message: str):
        """Helper for logging without state."""
        import logging
        logging.getLogger(__name__).info(message)
        
    @traceable(name="KnowledgeRetriever", tags=["agent", "knowledge"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """
        Retrieve relevant knowledge from FAIR Data Station using LLM-driven ReAct pattern.
        
        ReAct Loop:
        1. REASON: LLM analyzes document and decides what metadata packages/terms to query
        2. ACT: Execute FAIR-DS API queries based on LLM's decision
        3. OBSERVE: Review retrieved results
        4. REASON: LLM evaluates if information is sufficient or needs more queries
        5. Repeat if needed
        
        The agent autonomously decides:
        - Which packages to query
        - Which ISA sheets to focus on
        - How many optional fields to select per sheet
        - Whether retrieved information is sufficient
        """
        self.log_execution(state, "🔍 Starting knowledge retrieval (LLM-driven ReAct)")
        
        try:
            doc_info = state.get("document_info", {})
            self.log_execution(state, f"📥 Received document_info with {len(doc_info)} fields")
            if doc_info:
                self.log_execution(state, f"   Keys: {list(doc_info.keys())[:10]}...")
            else:
                self.log_execution(state, "⚠️  WARNING: document_info is empty!", "warning")
            knowledge_items = []
            
            # Fetch from FAIR-DS API (strict mode - no local fallback)
            self.log_execution(state, "🌐 Fetching metadata from FAIR-DS API...")
            
            if not self.fair_ds_client:
                error_msg = "FAIR-DS API client not available. Please ensure FAIR-DS is running at localhost:8083"
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            self.log_execution(state, "   📡 GET /api/package (list all packages)...")
            self.log_execution(state, "   📡 GET /api/terms...")
            
            # Step 1: Get list of all available packages
            available_package_names = self.fair_ds_client.get_available_packages()
            self.log_execution(state, f"   ✅ Found {len(available_package_names)} available packages: {available_package_names}")
            
            if not available_package_names:
                error_msg = "FAIR-DS API returned no packages. Ensure API is properly configured."
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            # Step 2: Fetch fields from all packages
            self.log_execution(state, f"   📦 Fetching fields from {len(available_package_names)} packages...")
            all_packages_metadata = []
            for pkg_name in available_package_names:
                package_data = self.fair_ds_client.get_package(pkg_name)
                if package_data and "metadata" in package_data:
                    fields = package_data["metadata"]
                    all_packages_metadata.extend(fields)
                    self.log_execution(state, f"      • {pkg_name}: {len(fields)} fields")
            
            # Get terms from FAIR-DS API
            terms = self.fair_ds_client.get_terms()  # Returns Dict[str, Dict] - already parsed
            
            # Group all fields by sheet
            packages_by_sheet = FAIRDSAPIParser.group_fields_by_sheet(all_packages_metadata)
            
            # Validate we got real API data
            if not packages_by_sheet or len(packages_by_sheet) == 0:
                error_msg = "FAIR-DS API returned no data. Ensure API is properly configured."
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            # Get all unique package names with stats
            all_packages = FAIRDSAPIParser.get_all_package_names(packages_by_sheet)
            
            self.log_execution(state, f"✅ Retrieved from FAIR-DS API:")
            self.log_execution(state, f"   ISA Sheets: {list(packages_by_sheet.keys())}")
            self.log_execution(state, f"   Total unique packages: {len(all_packages)}")
            self.log_execution(state, f"   Total terms: {len(terms)}")
            
            # Show all packages (no truncation)
            self.log_execution(state, "📦 All packages by field count:")
            for pkg in all_packages:  # ALL packages - no truncation
                self.log_execution(
                    state,
                    f"   • {pkg['name']}: {pkg['field_count']} fields "
                    f"({pkg['mandatory_count']} mandatory, {pkg['optional_count']} optional)"
                )
                
            # Use LLM for intelligent, adaptive analysis (required)
            # Get critic feedback if this is a retry
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            
            if critic_feedback:
                self.log_execution(state, "🔄 Retrying with Critic feedback...")
                critique = critic_feedback.get("critique")
                if critique:
                    self.log_execution(state, f"   Critique: {critique}")
                for idx, suggestion in enumerate(critic_feedback.get("suggestions", []), 1):
                    self.log_execution(state, f"   💡 Suggestion {idx}: {suggestion}")
            if guidance_history:
                self.log_execution(state, f"🧾 Historical guidance: {guidance_history}")
            
            if planner_instruction:
                self.log_execution(state, f"🧭 Planner guidance: {planner_instruction}")
            
            self.log_execution(state, "🤖 Phase 1: LLM selecting relevant metadata packages...")
            
            # Phase 1: LLM selects relevant packages based on research type
            self.log_execution(state, "   Calling LLM to select relevant packages...")
            # Phase 1: LLM selects packages (no fallback - must succeed or retry)
            selected_package_names = await llm_methods.llm_select_relevant_packages(
                self.llm_helper,
                doc_info,
                all_packages,
                critic_feedback,
                planner_instruction=planner_instruction
            )
            self.log_execution(state, f"✅ LLM selected packages: {selected_package_names}")
            
            # Phase 2: Get all fields from selected packages, grouped by ISA sheet
            self.log_execution(state, "📦 Phase 2: Collecting fields from selected packages (by ISA sheet)...")
            
            # Get fields grouped by ISA sheet, with mandatory/optional separation
            fields_by_isa_sheet = FAIRDSAPIParser.get_fields_by_package_and_isa_sheet(
                packages_by_sheet, selected_package_names
            )
            
            # Log statistics for each ISA sheet
            isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
            for sheet in isa_sheets:
                mandatory_count = len(fields_by_isa_sheet[sheet]["mandatory"])
                optional_count = len(fields_by_isa_sheet[sheet]["optional"])
                if mandatory_count > 0 or optional_count > 0:
                    self.log_execution(
                        state,
                        f"   {sheet}: {mandatory_count} mandatory, {optional_count} optional"
                    )
            
            # Check if critical ISA levels (investigation, study) have mandatory fields
            # If not, automatically add "default" package to ensure completeness
            critical_sheets = ["investigation", "study"]
            missing_critical_fields = []
            for sheet in critical_sheets:
                if len(fields_by_isa_sheet[sheet]["mandatory"]) == 0:
                    missing_critical_fields.append(sheet)
            
            # Check if "default" package exists and has fields for missing ISA levels
            if missing_critical_fields:
                # Check if "default" package (case-insensitive) exists in available packages
                default_package_name = None
                for pkg in all_packages:
                    if pkg["name"].lower() == "default":
                        default_package_name = pkg["name"]  # Use actual name (may be "default" or "Default")
                        break
                
                # Check if default package is already selected (case-insensitive)
                default_already_selected = any(
                    pkg_name.lower() == "default" for pkg_name in selected_package_names
                )
                
                if default_package_name and not default_already_selected:
                    # Check if default package has fields for missing ISA levels
                    default_fields = FAIRDSAPIParser.get_fields_by_package_and_isa_sheet(
                        packages_by_sheet, [default_package_name]
                    )
                    
                    has_missing_fields = any(
                        len(default_fields[sheet]["mandatory"]) > 0 
                        for sheet in missing_critical_fields
                    )
                    
                    if has_missing_fields:
                        selected_package_names.append(default_package_name)
                        self.log_execution(
                            state,
                            f"⚠️  Auto-adding '{default_package_name}' package to cover "
                            f"missing ISA levels: {missing_critical_fields}"
                        )
                        
                        # Re-fetch fields with default package included
                        fields_by_isa_sheet = FAIRDSAPIParser.get_fields_by_package_and_isa_sheet(
                            packages_by_sheet, selected_package_names
                        )
                        
                        # Log updated statistics
                        self.log_execution(
                            state, 
                            f"📦 Updated field statistics after adding '{default_package_name}' package:"
                        )
                        for sheet in isa_sheets:
                            mandatory_count = len(fields_by_isa_sheet[sheet]["mandatory"])
                            optional_count = len(fields_by_isa_sheet[sheet]["optional"])
                            if mandatory_count > 0 or optional_count > 0:
                                self.log_execution(
                                    state,
                                    f"   {sheet}: {mandatory_count} mandatory, "
                                    f"{optional_count} optional"
                                )
            
            # Phase 3: Use LLM to intelligently select optional fields for each ISA sheet
            self.log_execution(state, "🤖 Phase 3: LLM selecting relevant optional fields (by ISA sheet)...")
            
            # Collect all mandatory fields (from all ISA sheets)
            all_mandatory_fields = []
            for sheet in isa_sheets:
                all_mandatory_fields.extend(fields_by_isa_sheet[sheet]["mandatory"])
            
            # Start with all mandatory fields
            final_selected_fields = list(all_mandatory_fields)
            
            # Collect all terms to search (from LLM requests)
            all_terms_to_search = []
            
            # Use LLM to select optional fields for each ISA sheet
            for sheet in isa_sheets:
                optional_fields_for_sheet = fields_by_isa_sheet[sheet]["optional"]
                if optional_fields_for_sheet:
                    self.log_execution(
                        state,
                        f"   LLM selecting optional fields for {sheet} ({len(optional_fields_for_sheet)} available)..."
                    )
                    
                    # Use LLM to intelligently select optional fields (no fallback)
                    # Returns: {"selected_fields": [...], "terms_to_search": [...]}
                    llm_result = await llm_methods.llm_select_fields_from_package(
                        self.llm_helper,
                        doc_info,
                        sheet,  # ISA sheet level (investigation, study, assay, sample, observationunit)
                        f"{sheet}_fields",  # Package name for logging
                        fields_by_isa_sheet[sheet]["mandatory"],
                        optional_fields_for_sheet,
                        critic_feedback
                    )
                    
                    selected_optional = llm_result.get("selected_fields", [])
                    terms_to_search = llm_result.get("terms_to_search", [])
                    
                    final_selected_fields.extend(selected_optional)
                    all_terms_to_search.extend(terms_to_search)
                    
                    self.log_execution(
                        state,
                        f"   ✅ {sheet}: LLM selected {len(selected_optional)} optional fields"
                    )
                    if terms_to_search:
                        self.log_execution(
                            state,
                            f"   🔍 {sheet}: LLM requested term search for: {terms_to_search}"
                        )
            
            # Phase 4: Search for additional terms/fields if LLM requested
            if all_terms_to_search and self.fair_ds_client:
                self.log_execution(state, f"🔍 Phase 4: Searching for {len(all_terms_to_search)} additional terms...")
                
                for term in all_terms_to_search:
                    # Search using /api/terms endpoint
                    found_terms = self.fair_ds_client.search_terms_for_fields(term)
                    if found_terms:
                        self.log_execution(
                            state,
                            f"   📚 Found {len(found_terms)} terms matching '{term}'"
                        )
                        # Store found terms in state for JSON generator to use
                        if "additional_terms" not in state:
                            state["additional_terms"] = []
                        state["additional_terms"].extend(found_terms)
                    
                    # Also search across packages for fields with matching labels
                    found_fields = self.fair_ds_client.search_fields_in_packages(term, available_package_names)
                    if found_fields:
                        self.log_execution(
                            state,
                            f"   📦 Found {len(found_fields)} fields matching '{term}' across packages"
                        )
                        # Add unique fields to final selection
                        existing_labels = {f.get("label") for f in final_selected_fields}
                        for field in found_fields:
                            if field.get("label") not in existing_labels:
                                final_selected_fields.append(field)
                                existing_labels.add(field.get("label"))
            
            # Log final statistics
            total_mandatory = len(all_mandatory_fields)
            total_optional = len(final_selected_fields) - total_mandatory
            
            # Count ISA sheets that have fields
            sheets_with_fields = [
                s for s in isa_sheets
                if fields_by_isa_sheet[s]["mandatory"]
                or any(
                    f in final_selected_fields
                    for f in fields_by_isa_sheet[s]["optional"]
                )
            ]
            
            self.log_execution(
                state,
                f"✅ Final selection: {len(final_selected_fields)} fields "
                f"({total_mandatory} mandatory + {total_optional} optional) "
                f"across {len(sheets_with_fields)} ISA sheets"
            )
            
            # Convert to KnowledgeItem objects
            knowledge_items = []
            for field in final_selected_fields:
                field_info = FAIRDSAPIParser.extract_field_info(field)
                
                item = KnowledgeItem(
                    term=field_info['name'],
                    definition=field_info['definition'],
                    source="FAIR-DS-API",
                    ontology_uri=field_info.get('ontology_uri'),
                    confidence=0.95 if field_info['required'] else 0.85,
                    metadata=field_info
                )
                knowledge_items.append(item)
            
            # Store retrieved knowledge in state
            state["retrieved_knowledge"] = [
                {
                    "term": item.term,
                    "definition": item.definition,
                    "source": item.source,
                    "ontology_uri": item.ontology_uri,
                    "confidence": item.confidence,
                    "metadata": item.metadata
                }
                for item in knowledge_items
            ]
            
            # Store API capability info for Critic to understand limitations
            state["api_capabilities"] = {
                "available_packages": available_package_names,
                "total_packages_available": len(available_package_names),
                "packages_requested_by_planner": self._extract_requested_packages(planner_instruction),
                "packages_actually_available": all_packages,
                "limitation_note": (
                    f"FAIR-DS API only has {len(available_package_names)} package(s) available: {available_package_names}. "
                    "The agent can only select from packages that actually exist in the API."
                ) if len(available_package_names) <= 1 else None
            }
            
            self.log_execution(
                state,
                f"✅ Knowledge retrieval completed: {len(knowledge_items)} FAIR-DS fields"
            )
            
            # Calculate confidence
            confidence = self._calculate_retrieval_confidence(
                knowledge_items, doc_info
            )
            self.update_confidence(state, "knowledge_retrieval", confidence)
            
            self.log_execution(
                state,
                f"✅ Knowledge retrieval completed!\n"
                f"   - Retrieved {len(knowledge_items)} metadata terms\n"
                f"   - Source: {'FAIR-DS API' if self.fair_ds_client else 'Local KB'}\n"
                f"   - Confidence: {confidence:.2%}"
            )
            
        except Exception as e:
            self.log_execution(
                state, 
                f"❌ Knowledge retrieval failed: {str(e)}", 
                "error"
            )
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Knowledge retrieval error: {str(e)}")
            self.update_confidence(state, "knowledge_retrieval", 0.0)
            # Ensure knowledge_items exists even on error
            if "knowledge_items" not in state:
                state["knowledge_items"] = []
        
        return state
    
    def _calculate_retrieval_confidence(
        self, 
        knowledge_items: List[KnowledgeItem], 
        doc_info: Dict[str, Any]
    ) -> float:
        """Calculate confidence for knowledge retrieval."""
        if not knowledge_items:
            return 0.0
        
        # Base score from number of items retrieved
        base_score = min(len(knowledge_items) / 15.0, 0.5)
        
        # Bonus for high-confidence items
        high_conf_items = [
            item for item in knowledge_items if item.confidence > 0.8
        ]
        confidence_bonus = len(high_conf_items) / len(knowledge_items) * 0.3
        
        # Bonus for using FAIR-DS API
        api_bonus = 0.2 if self.fair_ds_client else 0.0
        
        return min(base_score + confidence_bonus + api_bonus, 1.0)
    
    def _extract_requested_packages(self, planner_instruction: Optional[str]) -> List[str]:
        """Extract package names/keywords mentioned in planner instruction."""
        if not planner_instruction:
            return []
        
        # Common domain keywords that Planner might request
        domain_keywords = [
            "transcriptomics", "RNA-seq", "genomics", "proteomics", "metabolomics",
            "ecotoxicology", "environmental", "soil", "nanomaterial", "exposure",
            "time-series", "longitudinal", "temporal", "bioinformatics",
            "organism", "species", "taxonomy", "biodata", "omics"
        ]
        
        instruction_lower = planner_instruction.lower()
        requested = []
        for keyword in domain_keywords:
            if keyword.lower() in instruction_lower:
                requested.append(keyword)
        
        return requested