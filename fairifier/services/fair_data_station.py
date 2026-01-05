"""Client utilities for interacting with a FAIR Data Station API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional
import json as json_lib

try:
    import requests
except ImportError:  # pragma: no cover - handled gracefully at runtime
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger(__name__)


class FAIRDataStationUnavailable(RuntimeError):
    """Raised when the FAIR Data Station API cannot be reached."""


class FAIRDataStationClient:
    """Thin HTTP client for FAIR Data Station metadata endpoints."""

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        if not requests:
            raise ImportError(
                "The 'requests' package is required for FAIR Data Station integration."
            )

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._packages_cache: Optional[List[Dict[str, Any]]] = None
        self._terms_cache: Optional[List[Dict[str, Any]]] = None

    def is_available(self) -> bool:
        """Return True if the FAIR Data Station API health endpoint responds."""
        try:
            response = self._session.get(
                f"{self._base_url}/api/health", timeout=self._timeout
            )
            return response.status_code == 200
        except Exception as exc:  # pragma: no cover - network failure path
            logger.debug("FAIR-DS health check failed: %s", exc)
            return False

    def get_terms(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and cache all terms available from the FAIR Data Station."""
        if self._terms_cache is not None and not force_refresh:
            return self._terms_cache

        try:
            # Try JSON API endpoints first
            endpoints = ["/api/terms", "/api/v1/terms", "/terms", "/metadata/terms"]
            terms = []
            
            for endpoint in endpoints:
                try:
                    response = self._session.get(
                        f"{self._base_url}{endpoint}", timeout=self._timeout
                    )
                    if response.status_code == 200:
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' in content_type:
                            data = response.json()
                            # FAIR-DS API returns {"total": N, "terms": {...}}
                            if isinstance(data, dict) and "terms" in data:
                                terms = list(data["terms"].values())
                                logger.info(f"✅ Successfully fetched {len(terms)} terms from JSON API {endpoint}")
                            else:
                                terms = data if isinstance(data, list) else []
                                logger.info(f"✅ Successfully fetched terms from JSON API {endpoint}")
                            break
                except Exception as e:
                    logger.debug(f"Endpoint {endpoint} failed: {e}")
                    continue
            
            # If JSON API didn't work, try scraping the web interface
            if not terms:
                logger.info("📡 JSON API not available, attempting to scrape FAIR-DS web interface...")
                terms = self._scrape_terms_from_web()
                
            # If scraping didn't work, use fallback
            if not terms:
                logger.info("⚠️  Web scraping failed, using FAIR-DS standard fallback")
                terms = self._get_fallback_terms()
                
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Unable to fetch FAIR-DS terms: %s", exc)
            terms = self._get_fallback_terms()

        self._terms_cache = terms
        return terms
    
    def _scrape_terms_from_web(self) -> List[Dict[str, Any]]:
        """Scrape terms from FAIR-DS web interface using browser automation."""
        try:
            logger.info(f"🌐 Accessing FAIR-DS web interface at {self._base_url}/terms")
            
            # Import here to avoid dependency if not needed
            from playwright.sync_api import sync_playwright
            import time
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Navigate to terms page
                logger.info("📡 Loading FAIR-DS terms page...")
                page.goto(f"{self._base_url}/terms", timeout=30000)
                
                # Wait for Vaadin to initialize and load data
                time.sleep(5)  # Give Vaadin time to load
                
                # Try to wait for table content
                try:
                    page.wait_for_selector('row gridcell', timeout=20000)
                except:
                    logger.warning("Timeout waiting for table, attempting to scrape anyway...")
                
                # Extract all rows from the table
                rows = page.query_selector_all('row')
                
                terms = []
                logger.info(f"📊 Found {len(rows)} rows in terms table")
                
                for i, row in enumerate(rows):
                    try:
                        cells = row.query_selector_all('gridcell')
                        if len(cells) >= 5:
                            sheet_name = cells[0].inner_text().strip()
                            package_name = cells[1].inner_text().strip()
                            field_name = cells[2].inner_text().strip()
                            example = cells[3].inner_text().strip()
                            description = cells[4].inner_text().strip()
                            
                            # Skip header row
                            if not sheet_name or sheet_name == "Sheet Name":
                                continue
                            
                            term = {
                                "level": sheet_name.lower(),
                                "package": package_name,
                                "name": field_name,
                                "label": field_name,
                                "example": example,
                                "description": description,
                                "required": "default" in package_name.lower(),
                                "source": "FAIR-DS-Web",
                                "uri": f"http://fairbydesign.nl/terms/{field_name.replace(' ', '_')}"
                            }
                            terms.append(term)
                            
                            # Log progress every 50 terms
                            if (i + 1) % 50 == 0:
                                logger.info(f"   Scraped {i+1} terms...")
                                
                    except Exception as e:
                        logger.debug(f"Failed to parse row {i}: {e}")
                        continue
                
                browser.close()
                
                if terms:
                    logger.info(f"✅ Successfully scraped {len(terms)} terms from web interface")
                else:
                    logger.warning("⚠️  No terms scraped from web interface")
                    
                return terms
                
        except Exception as e:
            logger.warning(f"❌ Web scraping failed: {e}")
            return []

    def get_packages(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and cache all metadata packages from the FAIR Data Station."""
        if self._packages_cache is not None and not force_refresh:
            return self._packages_cache

        try:
            # Try multiple possible endpoints
            endpoints = ["/api/packages", "/api/v1/packages", "/packages", "/metadata/packages"]
            packages = []
            
            for endpoint in endpoints:
                try:
                    response = self._session.get(
                        f"{self._base_url}{endpoint}", timeout=self._timeout
                    )
                        if response.status_code == 200:
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' in content_type:
                            data = response.json()
                            # FAIR-DS API new format: {"total": N, "metadata": {...}}
                            # Old format: {"total": N, "packages": {...}}
                            packages_dict = data.get("metadata") or data.get("packages")
                            if isinstance(packages_dict, dict):
                                packages = []
                                for level, level_data in packages_dict.items():
                                    # New format: level_data is {"name": ..., "metadata": [...]}
                                    if isinstance(level_data, dict) and "metadata" in level_data:
                                        level_packages = level_data["metadata"]
                                    # Old format: level_data is directly a list of fields
                                    elif isinstance(level_data, list):
                                        level_packages = level_data
                                    else:
                                        continue
                                    for pkg in level_packages:
                                        pkg["level"] = level  # Add level info
                                        packages.append(pkg)
                                logger.info(f"Successfully fetched {len(packages)} packages from {endpoint}")
                            else:
                                packages = data if isinstance(data, list) else []
                                logger.info(f"Successfully fetched packages from {endpoint}")
                            break
                except Exception as e:
                    logger.debug(f"Endpoint {endpoint} failed: {e}")
                    continue
            
            if not packages:
                logger.info("FAIR-DS API returns HTML (Vaadin app), using standard FAIR-DS packages")
                packages = self._get_fallback_packages()
                
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Unable to fetch FAIR-DS packages: %s", exc)
            packages = self._get_fallback_packages()

        self._packages_cache = packages
        return packages

    def search_terms(self, query: str) -> List[Dict[str, Any]]:
        """Return terms that contain the query in name, label, or description."""
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        for term in self.get_terms():
            fields_to_search = self._iter_term_strings(term)
            if any(query_lower in value for value in fields_to_search):
                results.append(term)

        return results

    @staticmethod
    def _iter_term_strings(term: Dict[str, Any]) -> Iterable[str]:
        """Yield searchable string values from a FAIR-DS term payload."""
        candidate_keys = ("name", "label", "description")
        for key in candidate_keys:
            value = term.get(key)
            if isinstance(value, str):
                yield value.lower()


    def _get_fallback_terms(self) -> List[Dict[str, Any]]:
        """Provide fallback FAIR-DS standard terms, organized by hierarchy."""
        return [
            # Investigation Level
            {
                "name": "investigation_title",
                "label": "Investigation Title", 
                "description": "The title of the investigation study",
                "level": "investigation",
                "package": "investigation_core",
                "uri": "http://fair-ds.org/terms/investigation_title",
                "required": True,
                "data_type": "string"
            },
            {
                "name": "investigation_description",
                "label": "Investigation Description",
                "description": "A description of the investigation study", 
                "level": "investigation",
                "package": "investigation_core",
                "uri": "http://fair-ds.org/terms/investigation_description",
                "required": True,
                "data_type": "text"
            },
            {
                "name": "investigation_identifier",
                "label": "Investigation Identifier",
                "description": "A unique identifier for the investigation",
                "level": "investigation", 
                "package": "investigation_core",
                "uri": "http://fair-ds.org/terms/investigation_identifier",
                "required": True,
                "data_type": "string"
            },
            
            # Study Level
            {
                "name": "study_title",
                "label": "Study Title",
                "description": "The title of the study within the investigation",
                "level": "study",
                "package": "study_core", 
                "uri": "http://fair-ds.org/terms/study_title",
                "required": True,
                "data_type": "string"
            },
            {
                "name": "study_description", 
                "label": "Study Description",
                "description": "A description of the study design and objectives",
                "level": "study",
                "package": "study_core",
                "uri": "http://fair-ds.org/terms/study_description", 
                "required": True,
                "data_type": "text"
            },
            {
                "name": "study_design_type",
                "label": "Study Design Type",
                "description": "The type of study design employed",
                "level": "study",
                "package": "study_design",
                "uri": "http://fair-ds.org/terms/study_design_type",
                "required": False,
                "data_type": "controlled_vocabulary"
            },
            
            # Assay Level
            {
                "name": "assay_title",
                "label": "Assay Title", 
                "description": "The title of the assay within the study",
                "level": "assay",
                "package": "assay_core",
                "uri": "http://fair-ds.org/terms/assay_title",
                "required": True,
                "data_type": "string"
            },
            {
                "name": "measurement_type",
                "label": "Measurement Type",
                "description": "The type of measurement being performed",
                "level": "assay", 
                "package": "assay_measurement",
                "uri": "http://fair-ds.org/terms/measurement_type",
                "required": True,
                "data_type": "controlled_vocabulary"
            },
            {
                "name": "technology_type", 
                "label": "Technology Type",
                "description": "The technology used to perform the measurement",
                "level": "assay",
                "package": "assay_technology",
                "uri": "http://fair-ds.org/terms/technology_type",
                "required": True,
                "data_type": "controlled_vocabulary"
            },
            
            # Observation Unit Level
            {
                "name": "sample_id",
                "label": "Sample ID",
                "description": "A unique identifier for the sample or observation unit",
                "level": "observation_unit",
                "package": "observation_core", 
                "uri": "http://fair-ds.org/terms/sample_id",
                "required": True,
                "data_type": "string"
            },
            {
                "name": "sample_type",
                "label": "Sample Type", 
                "description": "The type of sample being observed",
                "level": "observation_unit",
                "package": "observation_core",
                "uri": "http://fair-ds.org/terms/sample_type",
                "required": True,
                "data_type": "controlled_vocabulary"
            },
            {
                "name": "collection_date",
                "label": "Collection Date",
                "description": "The date when the sample was collected", 
                "level": "observation_unit",
                "package": "observation_temporal",
                "uri": "http://fair-ds.org/terms/collection_date",
                "required": False,
                "data_type": "date"
            },
            {
                "name": "geographic_location",
                "label": "Geographic Location",
                "description": "The geographic location where the sample was collected",
                "level": "observation_unit",
                "package": "observation_spatial",
                "uri": "http://fair-ds.org/terms/geographic_location", 
                "required": False,
                "data_type": "string"
            },
            
            # Environmental/Context Terms
            {
                "name": "environmental_medium",
                "label": "Environmental Medium",
                "description": "The environmental medium from which the sample was obtained",
                "level": "observation_unit", 
                "package": "environmental_context",
                "uri": "http://fair-ds.org/terms/environmental_medium",
                "required": False,
                "data_type": "controlled_vocabulary"
            },
            {
                "name": "temperature",
                "label": "Temperature", 
                "description": "The temperature at the time of sampling",
                "level": "observation_unit",
                "package": "environmental_measurements",
                "uri": "http://fair-ds.org/terms/temperature",
                "required": False,
                "data_type": "numeric"
            }
        ]
    
    def _get_fallback_packages(self) -> List[Dict[str, Any]]:
        """Provide fallback FAIR-DS standard packages, organized by hierarchy."""
        return [
            {
                "name": "investigation_core",
                "label": "Investigation Core Package",
                "description": "Core metadata fields required for any investigation",
                "level": "investigation",
                "version": "1.0.0",
                "required_fields": ["investigation_title", "investigation_description", "investigation_identifier"],
                "optional_fields": ["investigation_submission_date", "investigation_public_release_date"]
            },
            {
                "name": "study_core", 
                "label": "Study Core Package",
                "description": "Core metadata fields required for any study within an investigation",
                "level": "study",
                "version": "1.0.0", 
                "required_fields": ["study_title", "study_description"],
                "optional_fields": ["study_submission_date", "study_public_release_date"]
            },
            {
                "name": "study_design",
                "label": "Study Design Package",
                "description": "Metadata fields describing the study design and methodology", 
                "level": "study",
                "version": "1.0.0",
                "required_fields": [],
                "optional_fields": ["study_design_type", "study_factor_type", "study_factor_value"]
            },
            {
                "name": "assay_core",
                "label": "Assay Core Package", 
                "description": "Core metadata fields required for any assay",
                "level": "assay",
                "version": "1.0.0",
                "required_fields": ["assay_title", "measurement_type", "technology_type"],
                "optional_fields": ["assay_description"]
            },
            {
                "name": "assay_measurement",
                "label": "Assay Measurement Package",
                "description": "Metadata fields describing the measurement performed in the assay",
                "level": "assay", 
                "version": "1.0.0",
                "required_fields": ["measurement_type"],
                "optional_fields": ["measurement_unit", "measurement_protocol"]
            },
            {
                "name": "assay_technology", 
                "label": "Assay Technology Package",
                "description": "Metadata fields describing the technology used in the assay",
                "level": "assay",
                "version": "1.0.0",
                "required_fields": ["technology_type"],
                "optional_fields": ["technology_platform", "technology_protocol"]
            },
            {
                "name": "observation_core",
                "label": "Observation Unit Core Package",
                "description": "Core metadata fields for observation units (samples)",
                "level": "observation_unit",
                "version": "1.0.0", 
                "required_fields": ["sample_id", "sample_type"],
                "optional_fields": ["sample_description"]
            },
            {
                "name": "observation_temporal",
                "label": "Observation Temporal Package", 
                "description": "Temporal metadata for observation units",
                "level": "observation_unit",
                "version": "1.0.0",
                "required_fields": [],
                "optional_fields": ["collection_date", "collection_time", "storage_date"]
            },
            {
                "name": "observation_spatial",
                "label": "Observation Spatial Package",
                "description": "Spatial metadata for observation units",
                "level": "observation_unit", 
                "version": "1.0.0",
                "required_fields": [],
                "optional_fields": ["geographic_location", "latitude", "longitude", "elevation"]
            },
            {
                "name": "environmental_context",
                "label": "Environmental Context Package",
                "description": "Environmental context metadata for samples", 
                "level": "observation_unit",
                "version": "1.0.0",
                "required_fields": [],
                "optional_fields": ["environmental_medium", "habitat_type", "ecosystem_type"]
            },
            {
                "name": "environmental_measurements",
                "label": "Environmental Measurements Package",
                "description": "Environmental measurement metadata",
                "level": "observation_unit",
                "version": "1.0.0", 
                "required_fields": [],
                "optional_fields": ["temperature", "pH", "salinity", "dissolved_oxygen"]
            }
        ]

    def get_packages_by_level(self, level: str) -> List[Dict[str, Any]]:
        """Get packages at specified hierarchy level."""
        packages = self.get_packages()
        return [pkg for pkg in packages if pkg.get('level') == level]
    
    def get_terms_by_level(self, level: str) -> List[Dict[str, Any]]:
        """Get terms at specified hierarchy level."""
        terms = self.get_terms()
        return [term for term in terms if term.get('level') == level]

    def get_hierarchical_structure(self) -> Dict[str, Dict[str, Any]]:
        """Get hierarchical metadata structure."""
        packages = self.get_packages()
        terms = self.get_terms()
        
        structure = {
            "investigation": {
                "packages": [pkg for pkg in packages if pkg.get('level') == 'investigation'],
                "terms": [term for term in terms if term.get('level') == 'investigation']
            },
            "study": {
                "packages": [pkg for pkg in packages if pkg.get('level') == 'study'], 
                "terms": [term for term in terms if term.get('level') == 'study']
            },
            "assay": {
                "packages": [pkg for pkg in packages if pkg.get('level') == 'assay'],
                "terms": [term for term in terms if term.get('level') == 'assay']
            },
            "observation_unit": {
                "packages": [pkg for pkg in packages if pkg.get('level') == 'observation_unit'],
                "terms": [term for term in terms if term.get('level') == 'observation_unit']
            }
        }
        
        return structure


__all__ = ["FAIRDataStationClient", "FAIRDataStationUnavailable"]
