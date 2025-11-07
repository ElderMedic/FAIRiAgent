"""Knowledge retrieval agent using FAIR Data Station API."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, KnowledgeItem
from ..config import config
from ..services.fair_data_station import FAIRDataStationClient
from ..services.fairds_api_parser import FAIRDSAPIParser
from ..utils.llm_helper import get_llm_helper
from . import knowledge_retriever_llm_methods as llm_methods


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
            
            # Show top packages
            self.log_execution(state, "📦 Top packages by field count:")
            for pkg in all_packages[:10]:
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
                for suggestion in critic_feedback.get("suggestions", [])[:2]:
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
            
            # Phase 2: Get all fields from selected packages (auto-deduplicated)
            self.log_execution(state, "📦 Phase 2: Collecting fields from selected packages...")
            
            all_fields_from_packages = FAIRDSAPIParser.get_fields_by_package(
                packages_by_sheet, selected_package_names
            )
            
            # Separate mandatory and optional
            mandatory_fields = [f for f in all_fields_from_packages if f.get("requirement") == "MANDATORY"]
            optional_fields = [f for f in all_fields_from_packages if f.get("requirement") == "OPTIONAL"]
            
            self.log_execution(
                state,
                f"   Collected: {len(all_fields_from_packages)} unique fields "
                f"({len(mandatory_fields)} mandatory, {len(optional_fields)} optional)"
            )
            
            # Phase 3: LLM selects relevant optional fields
            self.log_execution(state, "🤖 Phase 3: LLM selecting relevant optional fields...")
            
            selected_optional = await llm_methods.llm_select_optional_fields(
                self.llm_helper, doc_info, mandatory_fields, optional_fields, critic_feedback
            )
            
            # Combine mandatory (all) + selected optional
            final_selected_fields = mandatory_fields + selected_optional
            
            self.log_execution(
                state,
                f"✅ Final selection: {len(final_selected_fields)} fields "
                f"({len(mandatory_fields)} mandatory + {len(selected_optional)} optional)"
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
                response = await self.llm_helper.llm.ainvoke([HumanMessage(content=prompt)])
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
        """Phase 3: LLM selects specific terms from selected packages."""
        
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
            
            # Use LLM to select most relevant terms for this level
            terms_list = []
            for term in relevant_terms_for_level[:20]:  # Limit to first 20 for prompt size
                terms_list.append({
                    "name": term.get("name"),
                    "label": term.get("label"),
                    "description": term.get("description"),
                    "required": term.get("required", False)
                })
            
            prompt = f"""Select terms relevant to this document for {level.upper()} level:

Document Info:
- Title: {doc_info.get('title', 'N/A')[:100]}
- Domain: {doc_info.get('research_domain', 'N/A')}
- Keywords: {', '.join(doc_info.get('keywords', [])[:5])}
- Location: {doc_info.get('location', 'N/A')}
- Has Environmental Data: {bool(doc_info.get('environmental_parameters'))}

Available Terms ({level}):
{json.dumps(terms_list, indent=2)[:2000]}

Select terms that can be populated from the document.
Return JSON array of term names:
{{"selected_terms": ["term_1", "term_2", ...]}}

Return ONLY JSON."""

            try:
                from langchain_core.messages import HumanMessage
                response = await self.llm_helper.llm.ainvoke([HumanMessage(content=prompt)])
                result = self.llm_helper._parse_json_response(response.content)
                selected_term_names = result.get("selected_terms", [])
                
                # Find full term objects
                for term in relevant_terms_for_level:
                    if term.get("name") in selected_term_names:
                        all_selected_terms.append(term)
                        
            except Exception as e:
                self.log_info(f"⚠️  LLM term selection failed for {level}: {e}, using all terms")
                all_selected_terms.extend(relevant_terms_for_level[:10])  # Take first 10
        
        return all_selected_terms
