"""Knowledge retrieval agent for enriching research information with FAIR standards."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base import BaseAgent
from ..models import FAIRifierState, KnowledgeItem
from ..config import config


class KnowledgeRetrieverAgent(BaseAgent):
    """Agent for retrieving and enriching knowledge from FAIR standards and ontologies."""
    
    def __init__(self):
        super().__init__("KnowledgeRetriever")
        self.mixs_fields = self._load_mixs_fields()
        self.ontologies = self._load_ontologies()
        
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Retrieve relevant knowledge based on document information."""
        self.log_execution(state, "Starting knowledge retrieval")
        
        try:
            doc_info = state["document_info"]
            knowledge_items = []
            
            # Determine appropriate MIxS package
            mixs_package = self._select_mixs_package(doc_info)
            self.log_execution(state, f"Selected MIxS package: {mixs_package}")
            
            # Retrieve relevant fields from MIxS
            mixs_knowledge = self._get_mixs_knowledge(mixs_package, doc_info)
            knowledge_items.extend(mixs_knowledge)
            
            # Enrich with ontology terms
            ontology_knowledge = self._get_ontology_knowledge(doc_info)
            knowledge_items.extend(ontology_knowledge)
            
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
            confidence = self._calculate_retrieval_confidence(knowledge_items, doc_info)
            self.update_confidence(state, "knowledge_retrieval", confidence)
            
            self.log_execution(
                state,
                f"Knowledge retrieval completed. Retrieved {len(knowledge_items)} items, "
                f"confidence={confidence:.2f}"
            )
            
        except Exception as e:
            self.log_execution(state, f"Knowledge retrieval failed: {str(e)}", "error")
            self.update_confidence(state, "knowledge_retrieval", 0.0)
        
        return state
    
    def _load_mixs_fields(self) -> Dict[str, Any]:
        """Load MIxS field definitions."""
        mixs_path = config.kb_path / "mixs_fields.json"
        if mixs_path.exists():
            with open(mixs_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _load_ontologies(self) -> Dict[str, Any]:
        """Load ontology definitions."""
        ont_path = config.kb_path / "ontologies.json"
        if ont_path.exists():
            with open(ont_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _select_mixs_package(self, doc_info: Dict[str, Any]) -> str:
        """Select appropriate MIxS package based on document content."""
        research_domain = doc_info.get("research_domain", "").lower()
        keywords = [k.lower() for k in doc_info.get("keywords", [])]
        text_content = doc_info.get("raw_text", "").lower()
        
        # Simple rule-based selection
        if any(term in text_content for term in ["metagenome", "metagenomic", "mag", "assembled genome"]):
            return "MIMAG"
        elif any(term in text_content for term in ["single cell", "amplified genome", "sag"]):
            return "MISAG"
        elif research_domain == "metagenomics":
            return "MIMAG"
        else:
            # Default to MIMAG
            return config.default_mixs_package
    
    def _get_mixs_knowledge(self, package: str, doc_info: Dict[str, Any]) -> List[KnowledgeItem]:
        """Get relevant MIxS fields for the selected package."""
        knowledge_items = []
        
        if package not in self.mixs_fields:
            return knowledge_items
        
        package_info = self.mixs_fields[package]
        
        # Add required fields
        for field in package_info.get("required_fields", []):
            item = KnowledgeItem(
                term=field["name"],
                definition=field["description"],
                source=f"MIxS {package}",
                confidence=0.9  # High confidence for required fields
            )
            knowledge_items.append(item)
        
        # Add relevant optional fields based on document content
        optional_fields = package_info.get("optional_fields", [])
        for field in optional_fields:
            if self._is_field_relevant(field, doc_info):
                item = KnowledgeItem(
                    term=field["name"],
                    definition=field["description"],
                    source=f"MIxS {package} (optional)",
                    confidence=0.7  # Lower confidence for optional fields
                )
                knowledge_items.append(item)
        
        return knowledge_items
    
    def _is_field_relevant(self, field: Dict[str, Any], doc_info: Dict[str, Any]) -> bool:
        """Check if an optional field is relevant to the document."""
        field_name = field["name"].lower()
        text_content = doc_info.get("raw_text", "").lower()
        variables = [v.lower() for v in doc_info.get("variables", [])]
        
        # Simple keyword matching
        if field_name in text_content:
            return True
        
        if field_name in variables:
            return True
        
        # Check for related terms
        related_terms = {
            "depth": ["depth", "deep", "meter", "m"],
            "temp": ["temperature", "temp", "celsius", "°c"],
            "ph": ["ph", "acidity", "alkalinity"],
            "salinity": ["salinity", "salt", "nacl"]
        }
        
        if field_name in related_terms:
            return any(term in text_content for term in related_terms[field_name])
        
        return False
    
    def _get_ontology_knowledge(self, doc_info: Dict[str, Any]) -> List[KnowledgeItem]:
        """Get relevant ontology terms."""
        knowledge_items = []
        
        # Extract environment-related terms
        env_terms = self._extract_environmental_terms(doc_info)
        for term, uri in env_terms.items():
            item = KnowledgeItem(
                term=term,
                definition=f"Environmental ontology term: {term}",
                source="ENVO",
                ontology_uri=uri,
                confidence=0.8
            )
            knowledge_items.append(item)
        
        return knowledge_items
    
    def _extract_environmental_terms(self, doc_info: Dict[str, Any]) -> Dict[str, str]:
        """Extract environmental terms and map to ontology URIs."""
        text_content = doc_info.get("raw_text", "").lower()
        env_terms = {}
        
        # Get ENVO terms from ontologies
        envo_terms = self.ontologies.get("environmental_ontologies", {}).get("ENVO", {}).get("common_terms", {})
        
        for term, term_id in envo_terms.items():
            if term.lower() in text_content:
                base_uri = self.ontologies["environmental_ontologies"]["ENVO"]["base_uri"]
                env_terms[term] = f"{base_uri}{term_id.split(':')[1]}"
        
        return env_terms
    
    def _calculate_retrieval_confidence(self, knowledge_items: List[KnowledgeItem], doc_info: Dict[str, Any]) -> float:
        """Calculate confidence for knowledge retrieval."""
        if not knowledge_items:
            return 0.0
        
        # Base score from number of items retrieved
        base_score = min(len(knowledge_items) / 10.0, 0.5)
        
        # Bonus for high-confidence items
        high_conf_items = [item for item in knowledge_items if item.confidence > 0.8]
        confidence_bonus = len(high_conf_items) / len(knowledge_items) * 0.3
        
        # Bonus for domain match
        domain_bonus = 0.2 if doc_info.get("research_domain") else 0.0
        
        return min(base_score + confidence_bonus + domain_bonus, 1.0)
