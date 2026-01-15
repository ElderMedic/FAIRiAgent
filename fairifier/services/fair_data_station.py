"""Client utilities for interacting with a FAIR Data Station API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - handled gracefully at runtime
    requests = None  # type: ignore

logger = logging.getLogger(__name__)


class FAIRDataStationUnavailable(RuntimeError):
    """Raised when the FAIR Data Station API cannot be reached."""


class FAIRDataStationClient:
    """Thin HTTP client for FAIR Data Station metadata endpoints.
    
    API Version: Latest (January 2026)
    Endpoints:
        - GET /api - API overview
        - GET /api/terms - Get all terms or filter by label/definition
        - GET /api/package - Get all packages or specific package by name
        - POST /api/upload - Upload and validate Excel file
    """

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        if not requests:
            raise ImportError(
                "The 'requests' package is required for FAIR Data Station integration."
            )

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        
        # Caches
        self._packages_cache: Optional[List[Dict[str, Any]]] = None
        self._terms_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._available_packages_cache: Optional[List[str]] = None

    def is_available(self) -> bool:
        """Return True if the FAIR Data Station API responds."""
        try:
            response = self._session.get(
                f"{self._base_url}/api", timeout=self._timeout
            )
            return response.status_code == 200
        except Exception as exc:  # pragma: no cover - network failure path
            logger.debug("FAIR-DS availability check failed: %s", exc)
            return False

    # =========================================================================
    # Terms API
    # =========================================================================

    def get_terms(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Fetch and cache all terms available from the FAIR Data Station.
        
        Returns:
            Dictionary mapping term names to term details
        """
        if self._terms_cache is not None and not force_refresh:
            return self._terms_cache

        try:
            response = self._session.get(
                f"{self._base_url}/api/terms", timeout=self._timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                # API returns {"total": N, "terms": {...}}
                if isinstance(data, dict) and "terms" in data:
                    self._terms_cache = data["terms"]
                    logger.info(f"✅ Fetched {data.get('total', len(self._terms_cache))} terms from FAIR-DS API")
                    return self._terms_cache
                    
        except Exception as exc:
            logger.warning("Unable to fetch FAIR-DS terms: %s", exc)

        # Return empty dict on failure
        self._terms_cache = {}
        return self._terms_cache

    def search_terms(
        self, 
        label: Optional[str] = None, 
        definition: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Search terms by label and/or definition using server-side filtering.
        
        Args:
            label: Filter terms by label (supports pattern matching, case-insensitive)
            definition: Filter terms by definition (supports pattern matching, case-insensitive)
            
        Returns:
            Dictionary mapping term names to term details
        """
        if not label and not definition:
            return self.get_terms()
            
        try:
            params = {}
            if label:
                params["label"] = label
            if definition:
                params["definition"] = definition
                
            response = self._session.get(
                f"{self._base_url}/api/terms",
                params=params,
                timeout=self._timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "terms" in data:
                    terms = data["terms"]
                    logger.info(f"✅ Found {data.get('total', len(terms))} terms matching filters")
                    return terms
                    
        except Exception as exc:
            logger.warning("Unable to search FAIR-DS terms: %s", exc)
            
        return {}

    def get_term_by_label(self, label: str) -> Optional[Dict[str, Any]]:
        """Get a specific term by its exact label.
        
        Args:
            label: The exact label of the term
            
        Returns:
            Term details or None if not found
        """
        terms = self.search_terms(label=label)
        
        # Look for exact match
        for term_name, term_info in terms.items():
            if term_info.get("label", "").lower() == label.lower():
                return term_info
        
        # Return first match if no exact match
        if terms:
            return next(iter(terms.values()))
            
        return None

    # =========================================================================
    # Package API
    # =========================================================================

    def get_available_packages(self, force_refresh: bool = False) -> List[str]:
        """Get list of all available package names.
        
        Returns:
            List of package names
        """
        if self._available_packages_cache is not None and not force_refresh:
            return self._available_packages_cache

        try:
            response = self._session.get(
                f"{self._base_url}/api/package", timeout=self._timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                # API returns {"message": "...", "packages": [...], "example": "..."}
                if isinstance(data, dict) and "packages" in data:
                    self._available_packages_cache = data["packages"]
                    logger.info(f"✅ Found {len(self._available_packages_cache)} available packages")
                    return self._available_packages_cache
                    
        except Exception as exc:
            logger.warning("Unable to fetch FAIR-DS package list: %s", exc)

        self._available_packages_cache = []
        return self._available_packages_cache

    def get_package(self, package_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific package with all its metadata fields.
        
        Args:
            package_name: Name of the package (e.g., "miappe", "soil", "default")
            
        Returns:
            Package data with structure:
            {
                "packageName": "miappe",
                "itemCount": 63,
                "metadata": [
                    {
                        "sheetName": "Study",
                        "packageName": "miappe",
                        "requirement": "MANDATORY",
                        "label": "start date of study",
                        "term": {...}
                    },
                    ...
                ]
            }
        """
        try:
            response = self._session.get(
                f"{self._base_url}/api/package",
                params={"name": package_name},
                timeout=self._timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "metadata" in data:
                    logger.info(
                        f"✅ Fetched package '{package_name}' with "
                        f"{data.get('itemCount', len(data['metadata']))} fields"
                    )
                    return data
                    
            elif response.status_code == 404:
                logger.warning(f"⚠️ Package '{package_name}' not found")
                
        except Exception as exc:
            logger.warning(f"Unable to fetch package '{package_name}': {exc}")
            
        return None

    def get_package_fields(
        self, 
        package_name: str, 
        requirement: Optional[str] = None,
        sheet_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get fields from a specific package with optional filtering.
        
        Args:
            package_name: Name of the package
            requirement: Filter by requirement level ("MANDATORY", "OPTIONAL", "RECOMMENDED")
            sheet_name: Filter by ISA sheet name ("Investigation", "Study", etc.)
            
        Returns:
            List of field dictionaries
        """
        package = self.get_package(package_name)
        if not package:
            return []
            
        fields = package.get("metadata", [])
        
        # Filter by requirement
        if requirement:
            requirement_upper = requirement.upper()
            fields = [f for f in fields if f.get("requirement") == requirement_upper]
            
        # Filter by sheet name
        if sheet_name:
            sheet_lower = sheet_name.lower()
            fields = [f for f in fields if f.get("sheetName", "").lower() == sheet_lower]
            
        return fields

    def get_mandatory_fields(self, package_name: str) -> List[Dict[str, Any]]:
        """Get all mandatory fields from a specific package.
        
        Args:
            package_name: Name of the package
            
        Returns:
            List of mandatory field dictionaries
        """
        return self.get_package_fields(package_name, requirement="MANDATORY")

    def get_packages(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and cache all metadata fields from the default package.
        
        Note: This fetches the 'default' package for backward compatibility.
        Use get_package(name) to get specific packages.
        
        Returns:
            List of field dictionaries
        """
        if self._packages_cache is not None and not force_refresh:
            return self._packages_cache

        package = self.get_package("default")
        if package:
            self._packages_cache = package.get("metadata", [])
        else:
            self._packages_cache = []
            
        return self._packages_cache

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_fields_by_sheet(
        self, 
        package_name: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get package fields grouped by ISA sheet.
        
        Args:
            package_name: Name of the package
            
        Returns:
            Dictionary mapping sheet names to lists of fields
        """
        package = self.get_package(package_name)
        if not package:
            return {}
            
        fields_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
        
        for field in package.get("metadata", []):
            sheet = field.get("sheetName", "Unknown")
            if sheet not in fields_by_sheet:
                fields_by_sheet[sheet] = []
            fields_by_sheet[sheet].append(field)
            
        return fields_by_sheet

    def get_fields_summary(
        self, 
        package_name: str
    ) -> Dict[str, Any]:
        """Get a summary of package fields by sheet and requirement level.
        
        Args:
            package_name: Name of the package
            
        Returns:
            Summary dictionary with structure:
            {
                "packageName": "miappe",
                "totalFields": 63,
                "bySheet": {
                    "Investigation": {"total": 5, "mandatory": 2, "optional": 3},
                    "Study": {"total": 20, "mandatory": 8, "optional": 12},
                    ...
                }
            }
        """
        package = self.get_package(package_name)
        if not package:
            return {}
            
        summary = {
            "packageName": package.get("packageName", package_name),
            "totalFields": package.get("itemCount", 0),
            "bySheet": {}
        }
        
        for field in package.get("metadata", []):
            sheet = field.get("sheetName", "Unknown")
            requirement = field.get("requirement", "OPTIONAL")
            
            if sheet not in summary["bySheet"]:
                summary["bySheet"][sheet] = {"total": 0, "mandatory": 0, "optional": 0, "recommended": 0}
                
            summary["bySheet"][sheet]["total"] += 1
            
            if requirement == "MANDATORY":
                summary["bySheet"][sheet]["mandatory"] += 1
            elif requirement == "RECOMMENDED":
                summary["bySheet"][sheet]["recommended"] += 1
            else:
                summary["bySheet"][sheet]["optional"] += 1
                
        return summary

    def get_packages_by_level(self, level: str) -> List[Dict[str, Any]]:
        """Get fields at specified ISA hierarchy level.
        
        Args:
            level: ISA level name (investigation, study, observationunit, sample, assay)
            
        Returns:
            List of fields from the default package at the specified level
        """
        return self.get_package_fields("default", sheet_name=level)

    def get_terms_by_level(self, level: str) -> List[Dict[str, Any]]:
        """Get terms at specified hierarchy level.
        
        Note: Terms don't have level information in the new API.
        This method searches for terms with the level name in their label.
        
        Args:
            level: ISA level name
            
        Returns:
            List of terms matching the level
        """
        terms = self.search_terms(label=level)
        return list(terms.values())

    def get_hierarchical_structure(self) -> Dict[str, Dict[str, Any]]:
        """Get hierarchical metadata structure from the default package.
        
        Returns:
            Dictionary with ISA levels and their fields
        """
        fields_by_sheet = self.get_fields_by_sheet("default")
        
        # Map sheet names to standardized ISA levels
        level_mapping = {
            "investigation": "investigation",
            "study": "study",
            "observationunit": "observation_unit",
            "sample": "sample",
            "assay": "assay"
        }
        
        structure = {}
        for sheet_name, fields in fields_by_sheet.items():
            level = level_mapping.get(sheet_name.lower(), sheet_name.lower())
            
            mandatory = [f for f in fields if f.get("requirement") == "MANDATORY"]
            optional = [f for f in fields if f.get("requirement") != "MANDATORY"]
            
            structure[level] = {
                "fields": fields,
                "mandatory_count": len(mandatory),
                "optional_count": len(optional),
                "total_count": len(fields)
            }
            
        return structure


__all__ = ["FAIRDataStationClient", "FAIRDataStationUnavailable"]
