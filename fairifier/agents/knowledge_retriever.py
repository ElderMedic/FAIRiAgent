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
    
    def __init__(self, use_llm: bool = True):
        super().__init__("KnowledgeRetriever")
        self.use_llm = use_llm
        if use_llm:
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
        """Retrieve relevant knowledge from FAIR Data Station."""
        self.log_execution(state, "🔍 Starting knowledge retrieval from FAIR-DS")
        
        try:
            doc_info = state.get("document_info", {})
            knowledge_items = []
            
            # Fetch from FAIR-DS API (strict mode - no local fallback)
            self.log_execution(state, "🌐 Fetching metadata from FAIR-DS API...")
            
            if not self.fair_ds_client:
                error_msg = "FAIR-DS API client not available. Please ensure FAIR-DS is running at localhost:8083"
                self.log_execution(state, f"❌ {error_msg}", "error")
                state["errors"] = state.get("errors", []) + [error_msg]
                self.update_confidence(state, "knowledge_retrieval", 0.0)
                return state
            
            self.log_execution(state, "   📡 GET /api/packages...")
            self.log_execution(state, "   📡 GET /api/terms...")
            
            # Get packages and terms from FAIR-DS API
            packages_response = self.fair_ds_client.get_packages()
            terms_response = self.fair_ds_client.get_terms()
            
            # Parse API responses
            packages_by_sheet = FAIRDSAPIParser.parse_packages_response(packages_response)
            terms = FAIRDSAPIParser.parse_terms_response(terms_response)
            
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
            
            if critic_feedback:
                self.log_execution(state, "🔄 Retrying with Critic feedback...")
                for suggestion in critic_feedback.get("suggestions", []):  # ALL suggestions - no truncation
                    self.log_execution(state, f"   💡 {suggestion}")
            
            self.log_execution(state, "🤖 Phase 1: LLM selecting relevant metadata packages...")
            
            # Phase 1: LLM selects relevant packages based on research type
            self.log_execution(state, "   Calling LLM to select relevant packages...")
            try:
                selected_package_names = await llm_methods.llm_select_relevant_packages(
                    self.llm_helper, doc_info, all_packages, critic_feedback
                )
                self.log_execution(state, f"✅ LLM selected packages: {selected_package_names}")
            except Exception as e:
                logger.error(f"Error in llm_select_relevant_packages: {e}", exc_info=True)
                self.log_execution(state, f"❌ LLM package selection failed: {e}", "error")
                # Use top 3 packages as fallback
                selected_package_names = [pkg["name"] for pkg in all_packages[:3]]
                self.log_execution(state, f"   Using default packages: {selected_package_names}")
            
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
            
            # Phase 3: LLM selects relevant optional fields for each ISA sheet
            self.log_execution(state, "🤖 Phase 3: LLM selecting relevant optional fields (by ISA sheet)...")
            
            # Collect all mandatory fields (from all ISA sheets)
            all_mandatory_fields = []
            for sheet in isa_sheets:
                all_mandatory_fields.extend(fields_by_isa_sheet[sheet]["mandatory"])
            
            # Select optional fields for each ISA sheet separately
            final_selected_fields = list(all_mandatory_fields)  # Start with all mandatory
            
            for sheet in isa_sheets:
                optional_fields_for_sheet = fields_by_isa_sheet[sheet]["optional"]
                if optional_fields_for_sheet:
                    self.log_execution(
                        state,
                        f"   Selecting optional fields for {sheet} ({len(optional_fields_for_sheet)} available)..."
                    )
                    
                    # Select optional fields for this ISA sheet
                    selected_optional_for_sheet = await llm_methods.llm_select_optional_fields_by_isa_sheet(
                        self.llm_helper,
                        doc_info,
                        sheet,
                        fields_by_isa_sheet[sheet]["mandatory"],
                        optional_fields_for_sheet,
                        critic_feedback
                    )
                    
                    final_selected_fields.extend(selected_optional_for_sheet)
                    
                    self.log_execution(
                        state,
                        f"   ✅ {sheet}: selected {len(selected_optional_for_sheet)} optional fields"
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
    
    def _simple_field_selection(
        self, 
        doc_info: Dict[str, Any], 
        all_terms: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Simple keyword-based field selection fallback."""
        selected = []
        
        # Extract keywords from document
        keywords = set()
        if doc_info.get('keywords'):
            keywords.update([k.lower() for k in doc_info['keywords']])
        if doc_info.get('research_domain'):
            keywords.add(doc_info['research_domain'].lower())
        
        # Common core fields to always include
        core_field_names = {
            'title', 'description', 'creator', 'date', 'identifier',
            'location', 'geographic', 'temporal', 'sample', 'method'
        }
        
        for term in all_terms:
            term_name = term.get('name', '').lower()
            term_desc = term.get('description', '').lower()
            
            # Include if matches core fields
            if any(core in term_name for core in core_field_names):
                selected.append(term)
                continue
            
            # Include if matches document keywords
            if keywords:
                if any(kw in term_name or kw in term_desc for kw in keywords):
                    selected.append(term)
                    if len(selected) >= 20:
                        break
        
        return selected[:20]  # Limit to 20 fields
    
    def _keyword_based_selection(
        self, 
        doc_info: Dict[str, Any], 
        all_terms: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Basic keyword-based field selection when LLM is not available.
        Only uses FAIR-DS terms, no local fallback.
        """
        selected = []
        
        # Extract keywords from document
        keywords = set()
        if doc_info.get('keywords'):
            keywords.update([k.lower() for k in doc_info['keywords']])
        if doc_info.get('research_domain'):
            keywords.add(doc_info['research_domain'].lower())
        
        # Identify core investigation-level fields (always include)
        investigation_terms = [t for t in all_terms if t.get('isa_level') == 'investigation']
        selected.extend(investigation_terms[:10])  # Include first 10 investigation fields
        
        # Add study-level fields if mentioned in keywords
        study_terms = [t for t in all_terms if t.get('isa_level') == 'study']
        for term in study_terms:
            term_name = term.get('name', '').lower()
            term_desc = term.get('description', '').lower()
            
            if keywords and any(kw in term_name or kw in term_desc for kw in keywords):
                selected.append(term)
                if len(selected) >= 20:
                    break
        
        # Add relevant assay-level fields based on research domain
        if len(selected) < 20:
            assay_terms = [t for t in all_terms if t.get('isa_level') == 'assay']
            for term in assay_terms:
                term_name = term.get('name', '').lower()
                term_desc = term.get('description', '').lower()
                
                if keywords and any(kw in term_name or kw in term_desc for kw in keywords):
                    selected.append(term)
                    if len(selected) >= 20:
                        break
        
        return selected[:25]  # Limit to 25 fields
    
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
    
    async def _llm_determine_relevant_levels(
        self, 
        doc_info: Dict[str, Any],
        structure: Dict[str, Any],
        critic_feedback: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Phase 1: LLM determines which ISA levels are relevant for this document."""
        
        prompt = f"""Analyze this research document and determine which ISA metadata levels are relevant:

Document Summary:
- Title: {doc_info.get('title', 'N/A')}
- Research Domain: {doc_info.get('research_domain', 'N/A')}
- Keywords: {', '.join(doc_info.get('keywords', [])[:10])}
- Methodology: {doc_info.get('methodology', 'N/A')[:200]}
- Has Location: {bool(doc_info.get('location'))}
- Has Environmental Data: {bool(doc_info.get('environmental_parameters'))}

ISA Hierarchy Levels Available:
1. investigation - High-level project/investigation metadata
2. study - Study design and research questions
3. assay - Measurement types and technologies used
4. sample - Biological samples (if applicable)
5. observation_unit - Sampling sites and environmental context

Return a JSON array of relevant level names:
{{"relevant_levels": ["investigation", "study", ...]}}

Consider:
- All documents need "investigation" and "study" 
- "assay" if measurements/technologies mentioned
- "sample" if biological samples mentioned
- "observation_unit" if location/environmental data present

Return ONLY JSON."""

        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm_helper.llm.ainvoke([HumanMessage(content=prompt)])
            result = self.llm_helper._parse_json_response(response.content)
            return result.get("relevant_levels", ["investigation", "study", "assay", "observation_unit"])
        except:
            # Default: all levels
            return ["investigation", "study", "assay", "sample", "observation_unit"]
    
    async def _llm_select_packages_by_level(
        self,
        doc_info: Dict[str, Any],
        structure: Dict[str, Any],
        relevant_levels: List[str]
    ) -> Dict[str, List[str]]:
        """Phase 2: LLM selects appropriate packages for each relevant level."""
        
        selected = {}
        
        for level in relevant_levels:
            level_packages = structure.get(level, {}).get('packages', [])
            
            if not level_packages:
                continue
            
            # Build package list for LLM
            pkg_list = []
            for pkg in level_packages:
                pkg_list.append({
                    "name": pkg.get("name"),
                    "label": pkg.get("label"),
                    "description": pkg.get("description"),
                    "required_fields": pkg.get("required_fields", [])[:5]  # Show first 5
                })
            
            prompt = f"""Select relevant metadata packages for the {level.upper()} level:

Document: {doc_info.get('title', 'N/A')}
Research Domain: {doc_info.get('research_domain', 'N/A')}

Available Packages:
{json.dumps(pkg_list, indent=2)}

Return JSON array of package names to include:
{{"selected_packages": ["package_name_1", "package_name_2", ...]}}

Return ONLY JSON."""

            try:
                from langchain_core.messages import HumanMessage
                response = await self.llm_helper._call_llm([HumanMessage(content=prompt)], operation_name="Knowledge Retriever - Extract Terms")
                result = self.llm_helper._parse_json_response(response.content)
                selected[level] = result.get("selected_packages", [pkg["name"] for pkg in pkg_list])
            except:
                # Default: use all available packages
                selected[level] = [pkg.get("name") for pkg in level_packages]
        
        return selected
    
    async def _llm_select_terms_from_packages(
        self,
        doc_info: Dict[str, Any],
        structure: Dict[str, Any],
        selected_packages: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """Phase 3: LLM selects specific terms from selected packages.
        
        IMPORTANT: All mandatory terms are automatically included.
        LLM only selects from optional terms.
        """
        
        all_selected_terms = []
        
        for level, package_names in selected_packages.items():
            level_terms = structure.get(level, {}).get('terms', [])
            
            # Filter terms by selected packages
            relevant_terms_for_level = []
            for term in level_terms:
                # Include term if it's in one of the selected packages or is core
                if term.get('package') in package_names or 'core' in term.get('package', ''):
                    relevant_terms_for_level.append(term)
            
            if not relevant_terms_for_level:
                continue
            
            # Separate mandatory and optional terms
            mandatory_terms = []
            optional_terms = []
            for term in relevant_terms_for_level:
                if term.get("required", False):
                    mandatory_terms.append(term)
                else:
                    optional_terms.append(term)
            
            # Always include all mandatory terms
            all_selected_terms.extend(mandatory_terms)
            
            if not optional_terms:
                # No optional terms to select
                continue
            
            # Use LLM to select relevant optional terms for this level
            optional_terms_list = []
            for term in optional_terms[:30]:  # Limit to first 30 for prompt size
                optional_terms_list.append({
                    "name": term.get("name"),
                    "label": term.get("label"),
                    "description": term.get("description"),
                    "required": False  # All are optional
                })
            
            # Prepare mandatory terms summary for context
            mandatory_summary = [
                {
                    "name": term.get("name"),
                    "label": term.get("label"),
                    "description": term.get("description")
                }
                for term in mandatory_terms[:10]  # Show first 10 mandatory terms
            ]
            
            prompt = f"""Select OPTIONAL terms relevant to this document for {level.upper()} level:

Document Info:
- Title: {doc_info.get('title', 'N/A')[:100]}
- Domain: {doc_info.get('research_domain', 'N/A')}
- Keywords: {', '.join(doc_info.get('keywords', [])[:5])}
- Location: {doc_info.get('location', 'N/A')}
- Has Environmental Data: {bool(doc_info.get('environmental_parameters'))}

**IMPORTANT:**
- Mandatory terms ({len(mandatory_terms)} terms) are ALREADY INCLUDED and do not need to be selected
- You only need to select from OPTIONAL terms below

Mandatory Terms (already included - for reference only):
{json.dumps(mandatory_summary, indent=2)[:1000]}

Available OPTIONAL Terms ({level}):
{json.dumps(optional_terms_list, indent=2)[:2000]}

**Your task:** Select 5-15 most relevant OPTIONAL terms that can be populated from the document.

Return JSON array of term names:
{{"selected_terms": ["term_1", "term_2", ...]}}

Return ONLY JSON."""

            try:
                from langchain_core.messages import HumanMessage
                response = await self.llm_helper._call_llm([HumanMessage(content=prompt)], operation_name="Knowledge Retriever - Extract Terms")
                result = self.llm_helper._parse_json_response(response.content)
                selected_term_names = result.get("selected_terms", [])
                
                # Find full term objects for selected optional terms
                for term in optional_terms:
                    if term.get("name") in selected_term_names:
                        all_selected_terms.append(term)
                
                self.log_info(
                    f"✅ {level}: {len(mandatory_terms)} mandatory + "
                    f"{len([t for t in optional_terms if t.get('name') in selected_term_names])} optional terms"
                )
                        
            except Exception as e:
                self.log_info(f"⚠️  LLM term selection failed for {level}: {e}, using mandatory terms only")
                # At least keep all mandatory terms
                # Optionally add some optional terms as fallback
                all_selected_terms.extend(optional_terms[:5])  # Take first 5 optional as fallback
        
        return all_selected_terms
