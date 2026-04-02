"""Knowledge retrieval agent using FAIR Data Station API."""

import logging
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.tools import tool
from langsmith import traceable

from .base import BaseAgent
from .react_loop import ReactLoopMixin
from .response_models import KnowledgeResponse
from ..models import FAIRifierState, KnowledgeItem
from ..config import config
from ..services.evidence_packets import build_evidence_context
from ..skills import load_skill_files
from ..services.fair_data_station import FAIRDataStationClient
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.llm_helper import get_llm_helper
from . import knowledge_retriever_llm_methods as llm_methods
from ..tools.fair_ds_tools import create_fair_ds_tools
from ..tools.science_tools import create_science_tools

logger = logging.getLogger(__name__)


class KnowledgeRetrieverAgent(ReactLoopMixin, BaseAgent):
    """Agent for retrieving knowledge from FAIR Data Station."""
    
    def __init__(self):
        super().__init__("KnowledgeRetriever")
        self.llm_helper = get_llm_helper()
        self._inner_kr_agent = None
        self._fairds_runtime_cache: Dict[str, Any] = {}
        self._science_runtime_cache: Dict[str, Any] = {}
        
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
        
        # Create FAIR-DS tools (pass client for reuse)
        tools_list = create_fair_ds_tools(client=self.fair_ds_client)
        self.tools = {tool.name: tool for tool in tools_list}

    def _build_runtime_tools(self, state: FAIRifierState) -> Dict[str, Any]:
        """Build FAIR-DS tools backed by the current run cache."""
        required_methods = (
            "get_available_packages",
            "get_package",
            "get_terms",
            "search_terms_for_fields",
            "search_fields_in_packages",
        )
        if not self.fair_ds_client or not all(
            hasattr(self.fair_ds_client, method) for method in required_methods
        ):
            return self.tools

        retrieval_cache = state.setdefault("retrieval_cache", {})
        state_bucket = retrieval_cache.get("fairds_tools")
        if isinstance(state_bucket, dict) and state_bucket is not self._fairds_runtime_cache:
            self._fairds_runtime_cache.update(state_bucket)
        retrieval_cache["fairds_tools"] = self._fairds_runtime_cache
        fairds_cache = self._fairds_runtime_cache
        tools_list = create_fair_ds_tools(
            client=self.fair_ds_client,
            cache_store=fairds_cache,
        )
        return {tool.name: tool for tool in tools_list}

    def _get_science_cache(self, state: FAIRifierState) -> Dict[str, Any]:
        """Return a shared science-tool cache for the current agent run."""
        retrieval_cache = state.setdefault("retrieval_cache", {})
        state_bucket = retrieval_cache.get("science_tools")
        if isinstance(state_bucket, dict) and state_bucket is not self._science_runtime_cache:
            self._science_runtime_cache.update(state_bucket)
        retrieval_cache["science_tools"] = self._science_runtime_cache
        return self._science_runtime_cache

    def _build_kr_inner_agent(
        self,
        *,
        science_cache: Optional[Dict[str, Any]] = None,
        default_candidate_packages: Optional[List[str]] = None,
    ):
        """Create the deepagents-backed inner loop for knowledge retrieval."""
        science_tools = create_science_tools(cache_store=science_cache)

        @tool
        def list_packages() -> Dict[str, Any]:
            """List FAIR-DS package names available through the configured API."""
            return self.tools["get_available_packages"].invoke({"force_refresh": False})

        @tool
        def get_package_info(package_name: str) -> Dict[str, Any]:
            """Fetch a FAIR-DS package and all of its fields."""
            return self.tools["get_package"].invoke({"package_name": package_name})

        @tool
        def search_metadata_term(term_label: str, definition: str = "") -> Dict[str, Any]:
            """Search FAIR-DS terms relevant to a metadata label."""
            return self.tools["search_terms_for_fields"].invoke(
                {"term_label": term_label, "definition": definition or None}
            )

        @tool
        def search_package_fields(field_label: str, package_names: str = "") -> Dict[str, Any]:
            """Search FAIR-DS package fields by label."""
            scoped_package_names = package_names or ",".join(default_candidate_packages or [])
            return self.tools["search_fields_in_packages"].invoke(
                {
                    "field_label": field_label,
                    "package_names": scoped_package_names or None,
                }
            )

        system_prompt = (
            "You are the internal KnowledgeRetriever loop for FAIRiAgent. "
            "Inspect /workspace/packages_summary.json and /workspace/doc_info.json, "
            "use FAIR-DS and science tools when needed, and return selected_packages, "
            "selected_optional_fields keyed by ISA sheet, terms_to_search, and metadata_gap_hints. "
            "Favor package names and field labels that exist in FAIR-DS. "
            "If a useful metadata concept is not represented as a real FAIR-DS package, do not invent "
            "a package name; keep selected_packages constrained to real FAIR-DS packages and record the "
            "uncovered concept in metadata_gap_hints instead."
        )
        subagents = [
            {
                "name": "package-selector",
                "description": "Choose the minimal but sufficient FAIR-DS packages for the document.",
                "system_prompt": (
                    "Select real FAIR-DS packages only. Bias toward investigation/study completeness."
                ),
                "tools": [list_packages, get_package_info],
            },
            {
                "name": "field-selector",
                "description": "Choose high-value optional FAIR-DS fields per ISA sheet.",
                "system_prompt": (
                    "Return field labels exactly as they appear in FAIR-DS when possible."
                ),
                "tools": [get_package_info, search_metadata_term, search_package_fields],
            },
        ]
        tools = [
            list_packages,
            get_package_info,
            search_metadata_term,
            search_package_fields,
            *science_tools,
        ]
        return self._build_react_agent(
            tools=tools,
            subagents=subagents,
            response_format=KnowledgeResponse,
            system_prompt=system_prompt,
            memory_files=self._get_memory_files(),
        )

    def _build_kr_seed_files(
        self,
        doc_info: Dict[str, Any],
        pkg_summary: Dict[str, Any],
        evidence_packets: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build virtual files for the deepagents knowledge retrieval loop."""
        seed_files: Dict[str, Any] = {}
        packages_file = self._maybe_create_file_data(
            json.dumps(pkg_summary, indent=2, ensure_ascii=False)
        )
        if packages_file is not None:
            seed_files["/workspace/packages_summary.json"] = packages_file

        doc_file = self._maybe_create_file_data(
            json.dumps(doc_info, indent=2, ensure_ascii=False)
        )
        if doc_file is not None:
            seed_files["/workspace/doc_info.json"] = doc_file

        evidence_file = self._maybe_create_file_data(
            json.dumps(evidence_packets or [], indent=2, ensure_ascii=False)
        )
        if evidence_file is not None:
            seed_files["/workspace/evidence_packets.json"] = evidence_file

        seed_files.update(load_skill_files(config.skills_dir))
        return seed_files

    def _select_optional_fields_from_structured(
        self,
        optional_fields: List[Dict[str, Any]],
        preferred_labels: List[str],
    ) -> List[Dict[str, Any]]:
        """Map deepagents-selected field labels back to real FAIR-DS field objects."""
        if not preferred_labels:
            return []

        wanted = {label.strip().lower() for label in preferred_labels if label}
        selected: List[Dict[str, Any]] = []
        for field in optional_fields:
            label = str(field.get("label", "")).strip().lower()
            if label in wanted:
                selected.append(field)
        return selected

    def _normalize_structured_field_map(
        self,
        structured_field_map: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        """Normalize ISA sheet keys from model output to the lowercase runtime convention."""
        normalized: Dict[str, List[str]] = {}
        for sheet, labels in (structured_field_map or {}).items():
            if not sheet:
                continue
            normalized[str(sheet).strip().lower()] = labels or []
        return normalized
    
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
            self.tools = self._build_runtime_tools(state)
            doc_info = state.get("document_info", {})
            evidence_packets = state.get("evidence_packets", []) or []
            self.log_execution(state, f"📥 Received document_info with {len(doc_info)} fields")
            if doc_info:
                self.log_execution(state, f"   Keys: {list(doc_info.keys())[:10]}...")
            else:
                self.log_execution(state, "⚠️  WARNING: document_info is empty!", "warning")
            if evidence_packets:
                self.log_execution(
                    state,
                    f"📦 Received {len(evidence_packets)} evidence packets"
                )
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
            
            # Step 1: Get list of all available packages (using tool)
            packages_result = self.tools["get_available_packages"].invoke({"force_refresh": False})
            if not packages_result["success"]:
                error_msg = f"Failed to get available packages: {packages_result['error']}"
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            available_package_names = packages_result["data"]
            self.log_execution(state, f"   ✅ Found {len(available_package_names)} available packages: {available_package_names}")
            
            if not available_package_names:
                error_msg = "FAIR-DS API returned no packages. Ensure API is properly configured."
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            prior_memory_context = self.format_retrieved_memories_for_prompt(
                feedback.get("retrieved_memories") or []
            )
            evidence_context = build_evidence_context(evidence_packets)
            llm_context = "\n\n".join(
                part for part in [prior_memory_context or None, evidence_context or None] if part
            ) or None

            priority_package_hints = self._infer_priority_packages(
                doc_info,
                planner_instruction,
                available_package_names,
                critic_feedback=critic_feedback,
                evidence_packets=evidence_packets,
            )
            guided_package_hints = self._extract_guided_package_names(
                available_package_names,
                critic_feedback=critic_feedback,
                planner_instruction=planner_instruction,
                guidance_history=guidance_history,
            )
            excluded_package_names = set()
            if len(available_package_names) > 5:
                excluded_package_names = self._infer_excluded_packages(
                    doc_info,
                    planner_instruction,
                    available_package_names,
                    evidence_packets,
                )
            candidate_package_names = self._build_candidate_package_names(
                doc_info,
                planner_instruction,
                available_package_names,
                evidence_packets,
                priority_package_hints,
                excluded_package_names,
            )

            if priority_package_hints:
                self.log_execution(
                    state,
                    f"🧭 Publication/domain priority packages: {priority_package_hints}"
                )
            if guided_package_hints:
                self.log_execution(
                    state,
                    f"🎯 Critic/planner-guided packages: {guided_package_hints}"
                )
            if excluded_package_names:
                self.log_execution(
                    state,
                    f"🚫 Excluding domain-mismatched packages from first-pass retrieval: {sorted(excluded_package_names)}"
                )

            self.log_execution(
                state,
                f"   📦 Fetching fields from {len(candidate_package_names)}/{len(available_package_names)} candidate packages..."
            )
            all_packages_metadata = []
            for pkg_name in candidate_package_names:
                pkg_result = self.tools["get_package"].invoke({"package_name": pkg_name})
                if pkg_result["success"] and pkg_result["data"] and "metadata" in pkg_result["data"]:
                    fields = pkg_result["data"]["metadata"]
                    all_packages_metadata.extend(fields)
                    self.log_execution(state, f"      • {pkg_name}: {len(fields)} fields")
                else:
                    self.log_execution(state, f"      ⚠️ {pkg_name}: failed or no metadata", "warning")
            
            # Get terms from FAIR-DS API (using tool)
            terms_result = self.tools["get_terms"].invoke({"force_refresh": False})
            if not terms_result["success"]:
                self.log_execution(state, f"⚠️ Failed to get terms: {terms_result['error']}", "warning")
                terms = {}
            else:
                terms = terms_result["data"]  # Returns Dict[str, Dict] - already parsed
            
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
            self.log_execution(state, "🤖 Phase 1: selecting relevant metadata packages...")

            structured_knowledge: Optional[KnowledgeResponse] = None
            if config.enable_deep_agents and self._should_skip_deep_react(candidate_package_names):
                self.log_execution(
                    state,
                    "⏭️ Skipping deep ReAct package planner for broad Qwen candidate set; using direct LLM selection for budget/stability."
                )
            elif config.enable_deep_agents:
                self._inner_kr_agent = self._build_kr_inner_agent(
                    science_cache=self._get_science_cache(state),
                    default_candidate_packages=candidate_package_names,
                )
                pkg_summary = {
                    "all_packages": all_packages,
                    "available_package_names": candidate_package_names,
                    "priority_package_hints": priority_package_hints,
                }
                task_desc = (
                    "Plan FAIR-DS retrieval for /workspace/doc_info.json using "
                    "/workspace/packages_summary.json and /workspace/evidence_packets.json. "
                    "Return selected_packages, "
                    "selected_optional_fields by ISA sheet, terms_to_search, and metadata_gap_hints. "
                    "Only put real FAIR-DS package names in selected_packages."
                )
                evidence_context = build_evidence_context(evidence_packets)
                if evidence_context:
                    task_desc += "\nGround package and field choices in the provided evidence packets."
                structured_result = await self._invoke_react_agent(
                    self._inner_kr_agent,
                    task_message=self._compose_task_message(state, task_desc),
                    seed_files=self._build_kr_seed_files(
                        doc_info,
                        pkg_summary,
                        evidence_packets=evidence_packets,
                    ),
                    thread_id=f"{state.get('session_id', 'default')}-kr-inner",
                    state=state,
                    scratchpad_name=self.name,
                )
                if structured_result:
                    structured_knowledge = structured_result

            # Phase 1 fallback: existing LLM package selector
            structured_package_gap_hints: List[str] = []
            if structured_knowledge and structured_knowledge.selected_packages:
                raw_structured_packages = list(dict.fromkeys(structured_knowledge.selected_packages))
                selected_package_names, structured_package_gap_hints = self._normalize_selected_packages(
                    raw_structured_packages,
                    available_package_names,
                )
                self.log_execution(
                    state,
                    f"🧠 Deep ReAct selected packages: {selected_package_names}"
                )
                if structured_package_gap_hints:
                    self.log_execution(
                        state,
                        f"🧩 Deep ReAct metadata gaps (not FAIR-DS packages): {structured_package_gap_hints}"
                    )
            else:
                self.log_execution(state, "   Calling LLM to select relevant packages...")
                selected_package_names = await llm_methods.llm_select_relevant_packages(
                    self.llm_helper,
                    doc_info,
                    all_packages,
                    critic_feedback,
                    planner_instruction=planner_instruction,
                    prior_memory_context=llm_context,
                    priority_package_hints=priority_package_hints
                )
                self.log_execution(state, f"✅ LLM selected packages: {selected_package_names}")

            if excluded_package_names:
                filtered_package_names = [
                    name for name in selected_package_names
                    if name not in excluded_package_names
                ]
                if filtered_package_names != selected_package_names:
                    self.log_execution(
                        state,
                        f"🧹 Filtered excluded packages from selection: {sorted(set(selected_package_names) - set(filtered_package_names))}"
                    )
                    selected_package_names = filtered_package_names

            selected_package_names = list(dict.fromkeys(selected_package_names))
            if guided_package_hints:
                merged_selected_packages: List[str] = []
                for package_name in selected_package_names + guided_package_hints:
                    if package_name not in merged_selected_packages:
                        merged_selected_packages.append(package_name)
                selected_package_names = merged_selected_packages
            if not selected_package_names:
                selected_package_names = priority_package_hints[:]
            if not selected_package_names:
                selected_package_names = candidate_package_names[:3]

            # Ensure metadata is available for all finally selected packages.
            # Guided/planner-added packages can fall outside the initial candidate fetch set.
            fetched_packages = {
                field.get("packageName")
                for field in all_packages_metadata
                if field.get("packageName")
            }
            missing_selected_packages = [
                pkg for pkg in selected_package_names if pkg not in fetched_packages
            ]
            if missing_selected_packages:
                self.log_execution(
                    state,
                    f"📦 Fetching metadata for {len(missing_selected_packages)} selected package(s) outside initial candidate set: {missing_selected_packages}"
                )
                for pkg_name in missing_selected_packages:
                    pkg_result = self.tools["get_package"].invoke({"package_name": pkg_name})
                    if pkg_result["success"] and pkg_result["data"] and "metadata" in pkg_result["data"]:
                        fields = pkg_result["data"]["metadata"]
                        all_packages_metadata.extend(fields)
                        self.log_execution(
                            state,
                            f"   ✅ {pkg_name}: loaded {len(fields)} additional fields"
                        )
                    else:
                        self.log_execution(
                            state,
                            f"   ⚠️ {pkg_name}: failed to load metadata for selected package",
                            "warning",
                        )
                packages_by_sheet = FAIRDSAPIParser.group_fields_by_sheet(all_packages_metadata)
                all_packages = FAIRDSAPIParser.get_all_package_names(packages_by_sheet)
            
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
            self.log_execution(state, "🤖 Phase 3: selecting relevant optional fields (by ISA sheet)...")
            
            # Collect all mandatory fields (from all ISA sheets)
            all_mandatory_fields = []
            for sheet in isa_sheets:
                all_mandatory_fields.extend(fields_by_isa_sheet[sheet]["mandatory"])
            
            # Start with all mandatory fields
            final_selected_fields = list(all_mandatory_fields)
            
            # Collect all terms to search (from LLM requests)
            all_terms_to_search = []
            required_search_terms = self._infer_required_search_terms(
                doc_info,
                planner_instruction,
                critic_feedback=critic_feedback,
                evidence_packets=evidence_packets,
            )
            priority_search_terms = self._infer_priority_search_terms(
                doc_info,
                planner_instruction,
                evidence_packets,
                critic_feedback=critic_feedback,
            )
            if required_search_terms:
                self.log_execution(
                    state,
                    f"🎯 Required metadata search terms from planner/critic guidance: {required_search_terms}"
                )
            if priority_search_terms:
                self.log_execution(
                    state,
                    f"🧭 Priority metadata search terms: {priority_search_terms}"
                )
            
            structured_field_map = self._normalize_structured_field_map(
                structured_knowledge.selected_optional_fields
                if structured_knowledge else {}
            )
            structured_terms_to_search = (
                structured_knowledge.terms_to_search
                if structured_knowledge else []
            )

            # Use LLM/deepagents to select optional fields for each ISA sheet
            for sheet in isa_sheets:
                optional_fields_for_sheet = fields_by_isa_sheet[sheet]["optional"]
                if optional_fields_for_sheet:
                    preferred_labels = structured_field_map.get(sheet, [])
                    if preferred_labels:
                        selected_optional = self._select_optional_fields_from_structured(
                            optional_fields_for_sheet,
                            preferred_labels,
                        )
                        terms_to_search = []
                        final_selected_fields.extend(selected_optional)
                        self.log_execution(
                            state,
                            f"   🧠 {sheet}: Deep ReAct selected {len(selected_optional)} optional fields"
                        )
                    else:
                        self.log_execution(
                            state,
                            f"   LLM selecting optional fields for {sheet} ({len(optional_fields_for_sheet)} available)..."
                        )
                        llm_result = await llm_methods.llm_select_fields_from_package(
                            self.llm_helper,
                            doc_info,
                            sheet,
                            f"{sheet}_fields",
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

            # Safety net: every MANDATORY field for the selected packages must be retained
            # (sheet name variants or earlier filtering can otherwise drop required fields).
            present_labels = {
                f.get("label")
                for f in final_selected_fields
                if f.get("label")
            }
            for sheet in isa_sheets:
                for mf in fields_by_isa_sheet[sheet]["mandatory"]:
                    lab = mf.get("label")
                    if lab and lab not in present_labels:
                        final_selected_fields.append(mf)
                        present_labels.add(lab)
                        self.log_execution(
                            state,
                            f"   ➕ Added missing mandatory field from package set: {lab} ({sheet})",
                        )
            
            # Add deterministic publication/domain search hints before final FAIR-DS lookup.
            all_terms_to_search = list(
                dict.fromkeys(
                    required_search_terms
                    + priority_search_terms
                    + structured_terms_to_search
                    + all_terms_to_search
                )
            )

            # Phase 4: Search for additional terms/fields if LLM requested (using tools)
            if all_terms_to_search and self.fair_ds_client:
                self.log_execution(state, f"🔍 Phase 4: Searching for {len(all_terms_to_search)} additional terms...")
                term_search_outcomes: Dict[str, Dict[str, int]] = {}
                # Only attribute fields to packages the workflow actually selected (Phase 1).
                # Searching all available packages and deduping by label alone used to pull
                # MIxS duplicates (e.g. "target gene" from "human oral") even when that package
                # was never selected — disagreeing with LangSmith package-selection traces.
                selected_pkg_norm = {
                    str(p).strip().lower()
                    for p in selected_package_names
                    if str(p).strip()
                }
                for term in all_terms_to_search:
                    term_key = str(term).strip().lower()
                    if not term_key:
                        continue
                    # Search using /api/terms endpoint (tool)
                    terms_search_result = self.tools["search_terms_for_fields"].invoke({
                        "term_label": term,
                        "definition": None
                    })
                    term_hits = 0
                    if terms_search_result["success"] and terms_search_result["data"]:
                        found_terms = terms_search_result["data"]
                        term_hits = len(found_terms)
                        self.log_execution(
                            state,
                            f"   📚 Found {len(found_terms)} terms matching '{term}'"
                        )
                        # Store found terms in state for JSON generator to use
                        if "additional_terms" not in state:
                            state["additional_terms"] = []
                        state["additional_terms"].extend(found_terms)
                    
                    # Also search across packages for fields with matching labels (tool).
                    # Scope is selected + publication/domain hints — never the full registry
                    # (required terms used to search everything and pick arbitrary MIxS duplicates).
                    search_scope_packages = list(
                        dict.fromkeys(selected_package_names + priority_package_hints)
                    )
                    package_names_str = ",".join(search_scope_packages) if search_scope_packages else None
                    fields_search_result = self.tools["search_fields_in_packages"].invoke({
                        "field_label": term,
                        "package_names": package_names_str
                    })
                    field_hits = 0
                    if fields_search_result["success"] and fields_search_result["data"]:
                        found_fields = fields_search_result["data"]
                        field_hits = len(found_fields)
                        self.log_execution(
                            state,
                            f"   📦 Found {len(found_fields)} fields matching '{term}' across packages"
                        )
                        # Add unique fields to final selection (label-level), only from
                        # selected packages so package_source matches agent-chosen packages.
                        existing_labels = {f.get("label") for f in final_selected_fields}
                        for field in found_fields:
                            label = field.get("label")
                            pkg_norm = str(field.get("packageName") or "").strip().lower()
                            if not label or pkg_norm not in selected_pkg_norm:
                                continue
                            if label not in existing_labels:
                                final_selected_fields.append(field)
                                existing_labels.add(label)
                    term_search_outcomes[term_key] = {
                        "terms_found": term_hits,
                        "fields_found": field_hits,
                    }
            else:
                term_search_outcomes = {}

            uncovered_required_terms = [
                term
                for term in required_search_terms
                if not self._selected_fields_cover_term(term, final_selected_fields)
            ]
            if uncovered_required_terms:
                self.log_execution(
                    state,
                    f"⚠️ Planner-critical metadata still uncovered after FAIR-DS retrieval: {uncovered_required_terms}",
                    "warning",
                )
            
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
            state["selected_packages"] = selected_package_names
            metadata_gap_hints = self._build_metadata_gap_hints(
                doc_info=doc_info,
                evidence_packets=evidence_packets,
                final_selected_fields=final_selected_fields,
                planner_instruction=planner_instruction,
                structured_gap_hints=(
                    structured_package_gap_hints
                    + (structured_knowledge.metadata_gap_hints if structured_knowledge else [])
                ),
                all_terms_to_search=all_terms_to_search,
                term_search_outcomes=term_search_outcomes,
                selected_package_names=selected_package_names,
                available_package_names=available_package_names,
            )
            state["metadata_gap_hints"] = metadata_gap_hints
            
            # Store API capability info for Critic to understand limitations
            state["api_capabilities"] = {
                "available_packages": available_package_names,
                "total_packages_available": len(available_package_names),
                "candidate_packages_considered": candidate_package_names,
                "guided_packages_considered": guided_package_hints,
                "packages_requested_by_planner": self._extract_requested_packages(planner_instruction),
                "required_metadata_terms": required_search_terms,
                "uncovered_required_metadata_terms": uncovered_required_terms,
                "selected_packages": selected_package_names,
                "unavailable_requested_packages": [
                    hint["label"] for hint in metadata_gap_hints
                    if hint.get("source") == "package_request"
                ],
                "requested_metadata_gaps": [hint["label"] for hint in metadata_gap_hints],
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

    def _normalize_selected_packages(
        self,
        requested_packages: List[str],
        available_package_names: List[str],
    ) -> Tuple[List[str], List[str]]:
        """Resolve package requests to real FAIR-DS package names and surface unmapped requests."""
        package_lookup = {name.lower(): name for name in available_package_names}
        selected: List[str] = []
        unmapped: List[str] = []
        for package_name in requested_packages:
            raw_name = str(package_name or "").strip()
            if not raw_name:
                continue
            actual_name = package_lookup.get(raw_name.lower())
            if actual_name:
                if actual_name not in selected:
                    selected.append(actual_name)
            elif raw_name not in unmapped:
                unmapped.append(raw_name)
        return selected, unmapped

    def _build_metadata_gap_hints(
        self,
        *,
        doc_info: Dict[str, Any],
        evidence_packets: List[Dict[str, Any]],
        final_selected_fields: List[Dict[str, Any]],
        planner_instruction: Optional[str],
        structured_gap_hints: List[str],
        all_terms_to_search: List[str],
        term_search_outcomes: Dict[str, Dict[str, int]],
        selected_package_names: List[str],
        available_package_names: List[str],
    ) -> List[Dict[str, Any]]:
        """Capture useful metadata concepts that FAIR-DS could not map directly."""
        selected_labels = {
            str(field.get("label", "")).strip().lower()
            for field in final_selected_fields
            if field.get("label")
        }
        selected_packages_lower = {pkg.lower() for pkg in selected_package_names}
        available_packages_lower = {pkg.lower() for pkg in available_package_names}
        doc_keys = {str(key).strip().lower() for key in doc_info.keys()}
        hints: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def add_hint(
            label: str,
            *,
            source: str,
            reason: str,
            confidence: float = 0.65,
            packet: Optional[Dict[str, Any]] = None,
        ) -> None:
            normalized = str(label or "").strip()
            lowered = normalized.lower()
            if not normalized or lowered in seen:
                return
            if lowered in selected_packages_lower or lowered in available_packages_lower:
                return
            if lowered in selected_labels:
                return
            seen.add(lowered)
            hints.append(
                {
                    "label": normalized,
                    "source": source,
                    "status": "unmapped_to_fairds",
                    "reason": reason,
                    "confidence": round(max(0.3, min(confidence, 0.95)), 2),
                    "packet_id": packet.get("packet_id") if packet else None,
                    "supporting_value": packet.get("value") if packet else None,
                    "supporting_evidence": packet.get("evidence_text") if packet else None,
                }
            )

        for label in structured_gap_hints:
            add_hint(
                label,
                source="package_request",
                reason="The planner identified a useful metadata concept that is not a real FAIR-DS package.",
                confidence=0.72,
            )

        for term in all_terms_to_search:
            normalized = str(term or "").strip()
            if not normalized:
                continue
            outcome = term_search_outcomes.get(normalized.lower(), {})
            if outcome.get("terms_found", 0) == 0 and outcome.get("fields_found", 0) == 0:
                add_hint(
                    normalized,
                    source="term_search",
                    reason="The workflow searched FAIR-DS for this metadata concept but found no matching term or field.",
                    confidence=0.68,
                )

        for packet in evidence_packets[:20]:
            candidate = str(packet.get("field_candidate") or "").strip()
            if not candidate:
                continue
            if candidate.lower() in doc_keys or candidate.lower() in selected_labels:
                continue
            add_hint(
                candidate,
                source="evidence_packet",
                reason="DocumentParser extracted this candidate, but KnowledgeRetriever could not map it to FAIR-DS fields.",
                confidence=float(packet.get("confidence") or 0.6),
                packet=packet,
            )

        for requested in self._extract_requested_packages(planner_instruction):
            if requested.lower() not in available_packages_lower and requested.lower() not in selected_labels:
                add_hint(
                    requested,
                    source="planner_request",
                    reason="Planner requested this domain concept, but FAIR-DS does not expose it as a package in the current API.",
                    confidence=0.62,
                )

        return hints

    def _infer_priority_packages(
        self,
        doc_info: Dict[str, Any],
        planner_instruction: Optional[str],
        available_package_names: List[str],
        critic_feedback: Optional[Dict[str, Any]] = None,
        evidence_packets: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Infer high-confidence package hints from document domain and publication context."""
        packet_values = " ".join(
            str(packet.get("value", ""))
            for packet in (evidence_packets or [])[:12]
            if packet.get("value")
        )
        critic_text = " ".join(
            str(part)
            for part in [
                critic_feedback.get("critique") if critic_feedback else "",
                " ".join(critic_feedback.get("suggestions", []) or []) if critic_feedback else "",
                " ".join(critic_feedback.get("issues", []) or []) if critic_feedback else "",
            ]
            if part
        )
        package_lookup = {name.lower(): name for name in available_package_names}
        text = " ".join(
            str(part)
            for part in [
                doc_info.get("title", ""),
                doc_info.get("document_type", ""),
                doc_info.get("research_domain", ""),
                " ".join(doc_info.get("keywords", []) or []),
                packet_values,
                planner_instruction or "",
                critic_text,
            ]
            if part
        ).lower()

        hints: List[str] = []

        def add(package_name: str):
            actual_name = package_lookup.get(package_name.lower())
            if actual_name and actual_name not in hints:
                hints.append(actual_name)

        # Always bias toward core investigation/study coverage.
        add("default")

        if any(
            keyword in text
            for keyword in [
                "plant", "crop", "potato", "tomato", "solanum", "miappe",
                "plant pathology", "phytopathology"
            ]
        ):
            add("miappe")
            add("plant associated")
            add("Plant Sample Checklist")
            add("Crop Plant sample enhanced annotation checklist")

        if any(
            keyword in text
            for keyword in [
                "pathogen", "phytopathogen", "bacteria", "bacterial",
                "quarantine pest", "clavibacter", "ralstonia", "infection",
                "biosafety"
            ]
        ):
            add("ENA prokaryotic pathogen minimal sample checklist")

        if any(keyword in text for keyword in ["soil", "rhizosphere", "environmental samples"]):
            add("soil")

        if any(
            keyword in text
            for keyword in ["rna-seq", "rna seq", "transcriptomic", "transcriptome", "illumina"]
        ):
            add("Illumina")

        if any(keyword in text for keyword in ["metabolomics", "metabolite", "metabolites"]):
            add("Metabolomics")

        if any(keyword in text for keyword in ["genome", "genomic", "gwas", "pangenome"]):
            add("Genome")

        if any(
            keyword in text
            for keyword in ["mag", "mags", "metagenome", "metagenomic", "mimags"]
        ):
            add("GSC MIMAGS")

        if any(
            keyword in text
            for keyword in [
                "diversity",
                "alpha diversity",
                "beta diversity",
                "gamma diversity",
                "shannon",
                "species richness",
                "bray-curtis",
            ]
        ):
            add("Diversity")

        return hints

    def _infer_priority_search_terms(
        self,
        doc_info: Dict[str, Any],
        planner_instruction: Optional[str],
        evidence_packets: Optional[List[Dict[str, Any]]] = None,
        critic_feedback: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Infer metadata labels that matter for publication-ready FAIR outputs."""
        packet_values = " ".join(
            str(packet.get("value", ""))
            for packet in (evidence_packets or [])[:12]
            if packet.get("value")
        )
        critic_text = " ".join(
            str(part)
            for part in [
                critic_feedback.get("critique") if critic_feedback else "",
                " ".join(critic_feedback.get("suggestions", []) or []) if critic_feedback else "",
                " ".join(critic_feedback.get("issues", []) or []) if critic_feedback else "",
            ]
            if part
        )
        text = " ".join(
            str(part)
            for part in [
                doc_info.get("title", ""),
                doc_info.get("document_type", ""),
                doc_info.get("research_domain", ""),
                " ".join(doc_info.get("keywords", []) or []),
                packet_values,
                planner_instruction or "",
                critic_text,
            ]
            if part
        ).lower()

        terms: List[str] = []

        def add(term: str):
            if term not in terms:
                terms.append(term)

        # Core publication-grade identifiers and study descriptors.
        for term in [
            "investigation identifier",
            "study identifier",
            "study title",
            "study description",
            "sample identifier",
            "sample description",
            "observation unit identifier",
        ]:
            add(term)

        if any(
            keyword in text
            for keyword in [
                "project", "proposal", "grant", "horizon", "consortium",
                "work package", "deliverable", "dmp", "data management"
            ]
        ):
            for term in [
                "project name",
                "collection date",
                "geographic location (country and/or sea)",
            ]:
                add(term)

        if any(
            keyword in text
            for keyword in [
                "plant", "crop", "pathogen", "potato", "tomato",
                "clavibacter", "ralstonia", "biosafety"
            ]
        ):
            for term in [
                "scientific name",
                "ncbi taxonomy id",
                "biosafety level",
                "plant tissue type",
                "pathogen isolate",
                "pathogen type",
                "sampling timepoint",
                "time post inoculation",
            ]:
                add(term)

        return terms

    def _infer_required_search_terms(
        self,
        doc_info: Dict[str, Any],
        planner_instruction: Optional[str],
        critic_feedback: Optional[Dict[str, Any]] = None,
        evidence_packets: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Infer planner-critical metadata concepts that must be searched across FAIR-DS."""
        packet_text = " ".join(
            " ".join(
                str(packet.get(key, ""))
                for key in ["field_candidate", "value", "evidence_text"]
                if packet.get(key)
            )
            for packet in (evidence_packets or [])[:16]
        )
        critic_text = " ".join(
            str(part)
            for part in [
                critic_feedback.get("critique") if critic_feedback else "",
                " ".join(critic_feedback.get("suggestions", []) or []) if critic_feedback else "",
                " ".join(critic_feedback.get("issues", []) or []) if critic_feedback else "",
            ]
            if part
        )
        text = " ".join(
            str(part)
            for part in [
                doc_info.get("title", ""),
                doc_info.get("document_type", ""),
                doc_info.get("research_domain", ""),
                doc_info.get("scientific_domain", ""),
                doc_info.get("methodology", ""),
                " ".join(doc_info.get("keywords", []) or []),
                planner_instruction or "",
                critic_text,
                packet_text,
            ]
            if part
        ).lower()

        terms: List[str] = []

        def add(term: str):
            if term not in terms:
                terms.append(term)

        concept_rules = [
            {
                "triggers": [
                    "diversity",
                    "alpha diversity",
                    "beta diversity",
                    "gamma diversity",
                    "shannon",
                    "species richness",
                    "bray-curtis",
                ],
                "terms": [
                    "diversity",
                    "alpha diversity",
                    "beta diversity",
                    "gamma diversity",
                    "species richness",
                    "shannon diversity",
                    "bray-curtis dissimilarity",
                ],
            },
            {
                "triggers": [
                    "license",
                    "licence",
                    "access rights",
                    "usage rights",
                    "reuse",
                    "copyright",
                ],
                "terms": [
                    "license",
                    "data usage license",
                    "access rights",
                ],
            },
            {
                "triggers": [
                    "shotgun metagenome",
                    "metagenome",
                    "metagenomic",
                    "16s",
                    "18s",
                    "rrna",
                    "amplicon",
                    "library strategy",
                    "dataset split",
                    "separate dataset",
                    "dataset type",
                ],
                "terms": [
                    "dataset type",
                    "library strategy",
                    "target gene",
                    "sequencing method",
                    "shotgun metagenome",
                    "16s rrna",
                    "18s rrna",
                    "amplicon sequencing",
                ],
            },
        ]

        for rule in concept_rules:
            if any(trigger in text for trigger in rule["triggers"]):
                for term in rule["terms"]:
                    add(term)

        return terms

    def _selected_fields_cover_term(
        self,
        term: str,
        selected_fields: List[Dict[str, Any]],
    ) -> bool:
        """Best-effort coverage check between required concepts and selected FAIR-DS labels."""
        normalized_term = self._normalize_metadata_text(term)
        if not normalized_term:
            return False

        synonyms = {
            "license": ["license", "licence", "access rights", "usage rights"],
            "data usage license": ["license", "usage rights", "access rights"],
            "diversity": ["diversity", "richness", "shannon", "bray curtis"],
            "alpha diversity": ["alpha diversity", "richness", "shannon"],
            "beta diversity": ["beta diversity", "bray curtis", "distance matrix"],
            "gamma diversity": ["gamma diversity", "regional diversity"],
            "dataset type": ["dataset type", "library strategy", "target gene", "sequencing method"],
            "shotgun metagenome": ["shotgun metagenome", "library strategy", "metagenome"],
            "16s rrna": ["16s", "rrna", "target gene", "amplicon"],
            "18s rrna": ["18s", "rrna", "target gene", "amplicon"],
            "amplicon sequencing": ["amplicon", "target gene", "library strategy"],
        }
        expected_tokens = synonyms.get(normalized_term, [normalized_term])

        for field in selected_fields:
            label = self._normalize_metadata_text(field.get("label", ""))
            if not label:
                continue
            if normalized_term in label or label in normalized_term:
                return True
            if any(token in label for token in expected_tokens):
                return True
        return False

    def _normalize_metadata_text(self, value: Any) -> str:
        """Normalize metadata labels and search terms for fuzzy matching."""
        text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
        return " ".join(text.split())

    def _infer_excluded_packages(
        self,
        doc_info: Dict[str, Any],
        planner_instruction: Optional[str],
        available_package_names: List[str],
        evidence_packets: Optional[List[Dict[str, Any]]] = None,
    ) -> set[str]:
        """Infer package names that are clearly domain-mismatched for the current document."""
        packet_values = " ".join(
            str(packet.get("value", ""))
            for packet in (evidence_packets or [])[:12]
            if packet.get("value")
        )
        text = " ".join(
            str(part)
            for part in [
                doc_info.get("title", ""),
                doc_info.get("document_type", ""),
                doc_info.get("research_domain", ""),
                doc_info.get("scientific_domain", ""),
                " ".join(doc_info.get("keywords", []) or []),
                packet_values,
                planner_instruction or "",
            ]
            if part
        ).lower()

        excludes: set[str] = set()

        def has_keyword(*keywords: str) -> bool:
            return any(re.search(r"\b" + re.escape(keyword) + r"\b", text) for keyword in keywords)

        for package_name in available_package_names:
            lower = package_name.lower()
            if any(token in lower for token in ["human oral", "human vaginal", "human gut", "human skin", "human associated", "person"]):
                if not has_keyword("human", "oral", "skin", "gut", "vaginal", "patient", "clinical"):
                    excludes.add(package_name)
            if any(token in lower for token in ["pig", "pig_", "pig "]):
                if not has_keyword("pig", "swine", "porcine"):
                    excludes.add(package_name)
            if any(token in lower for token in ["plant sample checklist", "crop plant", "miappe", "plant associated"]):
                if not has_keyword("plant", "crop", "leaf", "root", "stem", "seed", "pathology", "phytopathology"):
                    excludes.add(package_name)
        return excludes

    def _extract_guided_package_names(
        self,
        available_package_names: List[str],
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None,
        guidance_history: Optional[List[str]] = None,
    ) -> List[str]:
        """Extract explicitly named FAIR-DS packages from planner/critic guidance."""
        texts: List[str] = []
        if planner_instruction:
            texts.append(str(planner_instruction))
        if critic_feedback:
            texts.extend(str(item) for item in critic_feedback.get("issues", []) if item)
            texts.extend(str(item) for item in critic_feedback.get("suggestions", []) if item)
            critique = critic_feedback.get("critique")
            if critique:
                texts.append(str(critique))
        if guidance_history:
            texts.extend(str(item) for item in guidance_history if item)

        combined_text = "\n".join(texts).lower()
        guided_packages: List[str] = []
        for package_name in available_package_names:
            pattern = r"(?<![a-z0-9])" + re.escape(package_name.lower()) + r"(?![a-z0-9])"
            if re.search(pattern, combined_text) and package_name not in guided_packages:
                guided_packages.append(package_name)
        return guided_packages

    def _build_candidate_package_names(
        self,
        doc_info: Dict[str, Any],
        planner_instruction: Optional[str],
        available_package_names: List[str],
        evidence_packets: Optional[List[Dict[str, Any]]],
        priority_package_hints: List[str],
        excluded_package_names: set[str],
    ) -> List[str]:
        """Build a small, high-signal candidate package set for first-pass retrieval."""
        package_lookup = {name.lower(): name for name in available_package_names}
        packet_values = " ".join(
            str(packet.get("value", ""))
            for packet in (evidence_packets or [])[:16]
            if packet.get("value")
        )
        text = " ".join(
            str(part)
            for part in [
                doc_info.get("title", ""),
                doc_info.get("document_type", ""),
                doc_info.get("research_domain", ""),
                doc_info.get("scientific_domain", ""),
                doc_info.get("methodology", ""),
                " ".join(doc_info.get("keywords", []) or []),
                packet_values,
                planner_instruction or "",
            ]
            if part
        ).lower()

        candidates: List[str] = []

        def add(package_name: str):
            actual_name = package_lookup.get(package_name.lower())
            if actual_name and actual_name not in excluded_package_names and actual_name not in candidates:
                candidates.append(actual_name)

        for package_name in priority_package_hints:
            add(package_name)

        if any(token in text for token in ["ecotoxic", "nanotoxic", "exposure", "soil", "earthworm", "sediment"]):
            for package_name in ["soil", "sediment", "water", "miscellaneous natural or artificial environment"]:
                add(package_name)

        if any(token in text for token in ["rna-seq", "rna seq", "transcriptom", "illumina"]):
            for package_name in ["Illumina", "Genome"]:
                add(package_name)

        if any(token in text for token in ["proteom"]):
            add("Proteomics")
        if any(token in text for token in ["metabolom"]):
            add("Metabolomics")

        stop_tokens = {
            "checklist", "sample", "reporting", "standard", "pilot", "global",
            "enhanced", "annotation", "associated", "default", "ena", "gsc",
        }
        lexical_scores: List[tuple[int, str]] = []
        for package_name in available_package_names:
            if package_name in excluded_package_names:
                continue
            tokens = [
                token for token in package_name.lower().replace("-", " ").replace("_", " ").split()
                if len(token) > 3 and token not in stop_tokens
            ]
            score = sum(1 for token in tokens if token in text)
            if score > 0:
                lexical_scores.append((score, package_name))

        for _, package_name in sorted(lexical_scores, reverse=True):
            add(package_name)
            if len(candidates) >= 12:
                break

        if not candidates:
            return [name for name in available_package_names if name not in excluded_package_names]

        if len(candidates) < 4:
            for package_name in available_package_names:
                if package_name not in excluded_package_names:
                    add(package_name)
                if len(candidates) >= 6:
                    break

        return candidates

    def _should_skip_deep_react(
        self,
        candidate_package_names: List[str],
    ) -> bool:
        """Skip expensive KR inner loops when they are unlikely to be stable or cost-effective."""
        return config.llm_provider == "qwen" and len(candidate_package_names) >= 8
    
    def get_memory_query_hint(self, state: FAIRifierState) -> Optional[str]:
        """
        Generate memory query hint for KnowledgeRetriever.
        
        Focuses on: domain-specific package recommendations, ontology preferences,
        and field mappings learned from similar research domains.
        
        Args:
            state: Current workflow state
            
        Returns:
            Query hint string for memory retrieval, or None for default
        """
        doc_info = state.get("document_info", {})
        domain = doc_info.get("research_domain", "")
        keywords = doc_info.get("keywords", [])
        
        # Build domain description
        domain_desc = f"{domain} research" if domain else "this research domain"
        
        # Include keywords for more specific query
        if keywords:
            # Use first 3 keywords for specificity without being too narrow
            kw_str = ", ".join(keywords[:3])
            return (
                f"Recommended FAIR-DS packages, ontologies, and field mappings "
                f"for {domain_desc} with topics: {kw_str}"
            )
        else:
            return f"Recommended FAIR-DS packages and ontologies for {domain_desc}"
