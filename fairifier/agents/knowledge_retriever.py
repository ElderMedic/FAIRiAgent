"""Knowledge retrieval agent using FAIR Data Station API."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from langsmith import traceable

from .base import BaseAgent
from ..models import FAIRifierState, KnowledgeItem
from ..config import config
from ..services.fair_data_station import FAIRDataStationClient
from ..utils.llm_helper import get_llm_helper


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
            
            # Step 1: Try to fetch from FAIR-DS API first
            self.log_execution(state, "🌐 Attempting to fetch from FAIR-DS API (localhost:8083)...")
            
            if self.fair_ds_client:
                self.log_execution(state, "   📡 Trying GET /api/packages...")
                self.log_execution(state, "   📡 Trying GET /api/terms...")
                
                # Get packages and terms from API
                packages = self.fair_ds_client.get_packages()
                terms = self.fair_ds_client.get_terms()
                
                # Check if we got real data or fallback
                if packages and isinstance(packages, list) and len(packages) > 0:
                    if 'level' in packages[0]:  # This indicates it's from our structured fallback
                        self.log_execution(state, "⚠️  API returned HTML (Vaadin app), using FAIR-DS standard fallback")
                        data_source = "FAIR-DS-Fallback"
                    else:
                        self.log_execution(state, f"✅ Successfully retrieved from API: {len(packages)} packages, {len(terms)} terms")
                        data_source = "FAIR-DS-API"
                else:
                    self.log_execution(state, "⚠️  No data from API, using fallback")
                    data_source = "FAIR-DS-Fallback"
                
                # Get hierarchical structure
                structure = self.fair_ds_client.get_hierarchical_structure()
                self.log_execution(state, f"🏗️  Retrieved FAIR-DS hierarchical structure ({data_source}):")
                
                total_terms = 0
                total_packages = 0
                for level, content in structure.items():
                    level_terms = len(content.get('terms', []))
                    level_packages = len(content.get('packages', []))
                    total_terms += level_terms
                    total_packages += level_packages
                    self.log_execution(state, f"   📊 {level}: {level_terms} terms, {level_packages} packages")
                
                self.log_execution(state, f"✅ Total: {total_terms} terms, {total_packages} packages from {data_source}")
                
                # Step 2: Use LLM for intelligent analysis (broad to deep)
                if self.use_llm:
                    self.log_execution(state, "🤖 Phase 1: LLM analyzing document to determine relevant ISA levels...")
                    
                    # Phase 1: Determine which ISA levels are relevant
                    relevant_levels = await self._llm_determine_relevant_levels(doc_info, structure)
                    self.log_execution(state, f"✅ Relevant ISA levels: {relevant_levels}")
                    
                    # Phase 2: For each relevant level, select appropriate packages
                    self.log_execution(state, "🤖 Phase 2: LLM selecting relevant packages for each level...")
                    selected_packages = await self._llm_select_packages_by_level(
                        doc_info, structure, relevant_levels
                    )
                    
                    # Phase 3: For each selected package, choose specific terms
                    self.log_execution(state, "🤖 Phase 3: LLM selecting specific terms from packages...")
                    relevant_terms = await self._llm_select_terms_from_packages(
                        doc_info, structure, selected_packages
                    )
                    
                    self.log_execution(
                        state, 
                        f"✅ LLM analysis complete: {len(relevant_terms)} terms selected across {len(relevant_levels)} ISA levels"
                    )
                else:
                    # Fallback: use simple keyword matching
                    self.log_execution(state, "⚠️  Using keyword matching (LLM disabled)")
                    all_terms = []
                    for level_content in structure.values():
                        all_terms.extend(level_content.get('terms', []))
                    relevant_terms = self._simple_field_selection(doc_info, all_terms)
                
                # Convert to knowledge items with level and package information
                for term in relevant_terms:
                    item = KnowledgeItem(
                        term=term.get('name', ''),
                        definition=term.get('description', ''),
                        source=f"FAIR-DS-{term.get('level', 'unknown')}",
                        ontology_uri=term.get('uri', ''),
                        confidence=0.90,  # Higher confidence for FAIR-DS structured data
                        metadata={
                            'level': term.get('level'),
                            'package': term.get('package'),
                            'required': term.get('required'),
                            'data_type': term.get('data_type')
                        }
                    )
                    knowledge_items.append(item)
                
                # Store full hierarchical structure in state for later use
                state["fair_ds_structure"] = structure
                
                # Also store raw packages and terms for Generator
                state["fair_ds_packages"] = self.fair_ds_client.get_packages()
                state["fair_ds_terms"] = self.fair_ds_client.get_terms()
                
                self.log_execution(
                    state,
                    f"💾 Stored complete FAIR-DS data: {len(state['fair_ds_packages'])} packages, {len(state['fair_ds_terms'])} terms"
                )
                
            else:
                # Fallback to local knowledge base
                self.log_execution(
                    state, 
                    "⚠️  FAIR-DS not available, using local fallback"
                )
                knowledge_items = self._get_local_knowledge(doc_info)
            
            # Store retrieved knowledge
            state["retrieved_knowledge"] = [
                {
                    "term": item.term,
                    "definition": item.definition,
                    "source": item.source,
                    "ontology_uri": item.ontology_uri,
                    "confidence": item.confidence
                }
                for item in knowledge_items
            ]
            
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
            self.update_confidence(state, "knowledge_retrieval", 0.0)
        
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
    
    def _get_local_knowledge(
        self, 
        doc_info: Dict[str, Any]
    ) -> List[KnowledgeItem]:
        """Fallback: Get knowledge from local files."""
        knowledge_items = []
        
        # Define minimal core metadata fields
        core_fields = [
            {
                "name": "title",
                "description": "The title or name of the dataset or study",
                "required": True
            },
            {
                "name": "description",
                "description": "A detailed description of the dataset",
                "required": True
            },
            {
                "name": "creator",
                "description": "The person or organization who created the dataset",
                "required": True
            },
            {
                "name": "date_created",
                "description": "The date when the dataset was created",
                "required": False
            },
            {
                "name": "keywords",
                "description": "Keywords or tags describing the dataset",
                "required": False
            },
            {
                "name": "geographic_location",
                "description": "The geographic location where data was collected",
                "required": False
            },
            {
                "name": "temporal_coverage",
                "description": "The time period covered by the dataset",
                "required": False
            },
            {
                "name": "methodology",
                "description": "Methods and procedures used for data collection",
                "required": False
            },
            {
                "name": "instrument",
                "description": "Instruments or equipment used",
                "required": False
            },
            {
                "name": "license",
                "description": "The license under which the dataset is published",
                "required": False
            }
        ]
        
        for field in core_fields:
            item = KnowledgeItem(
                term=field["name"],
                definition=field["description"],
                source="Local",
                confidence=0.7 if field["required"] else 0.5
            )
            knowledge_items.append(item)
        
        # Add domain-specific fields if research domain is known
        domain = doc_info.get("research_domain", "").lower()
        if "genom" in domain or "metagen" in domain or "microb" in domain:
            genomics_fields = [
                {
                    "name": "sequencing_platform",
                    "description": "The sequencing platform or technology used",
                },
                {
                    "name": "assembly_method",
                    "description": "Method used for sequence assembly",
                },
                {
                    "name": "sequence_quality",
                    "description": "Quality metrics for sequences",
                }
            ]
            
            for field in genomics_fields:
                item = KnowledgeItem(
                    term=field["name"],
                    definition=field["description"],
                    source="Local (domain-specific)",
                    confidence=0.6
                )
                knowledge_items.append(item)
        
        return knowledge_items
    
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
        structure: Dict[str, Any]
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
