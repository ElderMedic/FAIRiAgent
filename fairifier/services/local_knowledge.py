"""Local provisional knowledge base for terms and packages not in FAIR-DS."""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class LocalTerm:
    """A local provisional term."""
    name: str
    label: str
    description: str
    source: str = "local"
    status: str = "provisional"
    ontology_uri: Optional[str] = None
    created_by: Optional[str] = None
    confidence: float = 0.7  # Lower default confidence for local terms


@dataclass
class LocalPackage:
    """A local provisional metadata package."""
    name: str
    description: str
    source: str = "local"
    status: str = "provisional"
    fields: List[str] = None
    created_by: Optional[str] = None
    
    def __post_init__(self):
        if self.fields is None:
            self.fields = []


class LocalKnowledgeBase:
    """Manager for local provisional terms and packages."""
    
    def __init__(self, kb_path: Path):
        self.kb_path = kb_path
        self.local_terms_file = kb_path / "local_terms.json"
        self.local_packages_file = kb_path / "local_packages.json"
        
        # Ensure files exist
        self._ensure_files()
        
        # Load data
        self.terms = self._load_terms()
        self.packages = self._load_packages()
    
    def _ensure_files(self) -> None:
        """Ensure local knowledge files exist."""
        self.kb_path.mkdir(parents=True, exist_ok=True)
        
        if not self.local_terms_file.exists():
            self._save_json(self.local_terms_file, [])
        
        if not self.local_packages_file.exists():
            self._save_json(self.local_packages_file, [])
    
    def _load_terms(self) -> List[LocalTerm]:
        """Load local terms from file."""
        data = self._load_json(self.local_terms_file)
        return [LocalTerm(**term) for term in data]
    
    def _load_packages(self) -> List[LocalPackage]:
        """Load local packages from file."""
        data = self._load_json(self.local_packages_file)
        return [LocalPackage(**pkg) for pkg in data]
    
    def _load_json(self, filepath: Path) -> List[Dict[str, Any]]:
        """Load JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _save_json(self, filepath: Path, data: List[Dict[str, Any]]) -> None:
        """Save JSON file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add_term(self, term: LocalTerm) -> None:
        """Add a new local term."""
        # Check if term already exists
        existing = self.get_term(term.name)
        if existing:
            # Update existing term
            self.terms = [t for t in self.terms if t.name != term.name]
        
        self.terms.append(term)
        self._save_terms()
    
    def add_package(self, package: LocalPackage) -> None:
        """Add a new local package."""
        # Check if package already exists
        existing = self.get_package(package.name)
        if existing:
            # Update existing package
            self.packages = [p for p in self.packages if p.name != package.name]
        
        self.packages.append(package)
        self._save_packages()
    
    def get_term(self, name: str) -> Optional[LocalTerm]:
        """Get a local term by name."""
        for term in self.terms:
            if term.name.lower() == name.lower():
                return term
        return None
    
    def get_package(self, name: str) -> Optional[LocalPackage]:
        """Get a local package by name."""
        for package in self.packages:
            if package.name.lower() == name.lower():
                return package
        return None
    
    def search_terms(self, query: str) -> List[LocalTerm]:
        """Search local terms."""
        query_lower = query.lower()
        results = []
        
        for term in self.terms:
            if (query_lower in term.name.lower() or
                query_lower in term.label.lower() or
                query_lower in term.description.lower()):
                results.append(term)
        
        return results
    
    def get_all_terms(self) -> List[LocalTerm]:
        """Get all local terms."""
        return self.terms
    
    def get_all_packages(self) -> List[LocalPackage]:
        """Get all local packages."""
        return self.packages
    
    def _save_terms(self) -> None:
        """Save terms to file."""
        data = [asdict(term) for term in self.terms]
        self._save_json(self.local_terms_file, data)
    
    def _save_packages(self) -> None:
        """Save packages to file."""
        data = [asdict(pkg) for pkg in self.packages]
        self._save_json(self.local_packages_file, data)
    
    def to_fairds_format(self, term: LocalTerm) -> Dict[str, Any]:
        """Convert local term to FAIR-DS compatible format."""
        return {
            "name": term.name,
            "label": term.label,
            "description": term.description,
            "source": "local",
            "status": "provisional",
            "ontology_uri": term.ontology_uri,
            "confidence": term.confidence
        }
    
    def create_default_terms(self) -> None:
        """Create some default local terms for common scenarios."""
        default_terms = [
            LocalTerm(
                name="project_description",
                label="Project Description",
                description="Detailed description of the research project",
                confidence=0.8
            ),
            LocalTerm(
                name="funding_source",
                label="Funding Source",
                description="Organization or grant funding the research",
                confidence=0.8
            ),
            LocalTerm(
                name="data_availability",
                label="Data Availability",
                description="Information about where and how data can be accessed",
                confidence=0.8
            ),
            LocalTerm(
                name="ethical_approval",
                label="Ethical Approval",
                description="Ethics committee approval information",
                confidence=0.9
            ),
            LocalTerm(
                name="sample_processing",
                label="Sample Processing",
                description="Methods used for sample processing and preparation",
                confidence=0.7
            )
        ]
        
        for term in default_terms:
            if not self.get_term(term.name):
                self.add_term(term)
    
    def create_default_packages(self) -> None:
        """Create some default local packages."""
        default_packages = [
            LocalPackage(
                name="basic_research",
                description="Basic research project metadata",
                fields=["project_name", "project_description", "principal_investigator", 
                       "funding_source", "start_date", "end_date"]
            ),
            LocalPackage(
                name="sample_collection",
                description="Sample collection metadata",
                fields=["collection_date", "geo_loc_name", "lat_lon", 
                       "sample_processing", "collection_method"]
            )
        ]
        
        for package in default_packages:
            if not self.get_package(package.name):
                self.add_package(package)


def initialize_local_kb(kb_path: Path) -> LocalKnowledgeBase:
    """Initialize local knowledge base with defaults."""
    local_kb = LocalKnowledgeBase(kb_path)
    local_kb.create_default_terms()
    local_kb.create_default_packages()
    return local_kb

