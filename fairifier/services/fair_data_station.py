"""Client utilities for interacting with a FAIR Data Station API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - handled gracefully at runtime
    requests = None  # type: ignore

from .fairds_api_parser import FAIRDSAPIParser

logger = logging.getLogger(__name__)


class FAIRDataStationUnavailable(RuntimeError):
    """Raised when the FAIR Data Station API cannot be reached."""


def _normalize_terms_payload(raw_terms: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize FAIR-DS term payloads into a dict of term-name -> term-info."""
    normalized: Dict[str, Dict[str, Any]] = {}

    if isinstance(raw_terms, dict):
        for term_name, term_info in raw_terms.items():
            if not isinstance(term_info, dict):
                continue
            normalized[str(term_name)] = term_info
        return normalized

    if isinstance(raw_terms, list):
        for index, term_info in enumerate(raw_terms):
            if not isinstance(term_info, dict):
                continue
            term_name = (
                term_info.get("term_name")
                or term_info.get("name")
                or term_info.get("label")
                or f"term_{index}"
            )
            normalized[str(term_name)] = term_info

    return normalized


class FAIRDataStationClient:
    """Thin HTTP client for FAIR Data Station metadata endpoints.
    
    API Version: Latest (January 2026)
    Endpoints (see live ``GET {base}/api`` for the authoritative list):
        - GET /api — discovery / available subpaths
        - GET /api/terms — all terms or ``?label=`` / ``?definition=`` filters
        - GET /api/package — package name list (no query) or ``?name=`` for metadata
        - POST /api/upload — Excel upload/validation

    Package ``metadata`` rows may use ``level`` (current) or ``sheetName`` (legacy)
    for the ISA layer; both are handled via :class:`FAIRDSAPIParser`.
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
        self._package_detail_cache: Dict[str, Dict[str, Any]] = {}

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
                    self._terms_cache = _normalize_terms_payload(data["terms"])
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
                    terms = _normalize_terms_payload(data["terms"])
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

    def get_package(self, package_name: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
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
                        "level": "Study",
                        "packageName": "miappe",
                        "requirement": "MANDATORY",
                        "label": "start date of study",
                        "term": {...}
                    },
                    ...
                ]
            }
        """
        if not force_refresh and package_name in self._package_detail_cache:
            return self._package_detail_cache[package_name]

        try:
            response = self._session.get(
                f"{self._base_url}/api/package",
                params={"name": package_name},
                timeout=self._timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "metadata" in data:
                    self._package_detail_cache[package_name] = data
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

    def search_terms_for_fields(
        self,
        term_label: str,
        definition: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for metadata terms using /api/terms endpoint.
        
        This is the correct way to search for field-related terms in FAIR-DS API.
        The /api/terms endpoint supports pattern matching on label and definition.
        
        Args:
            term_label: Filter terms by label (supports pattern matching, case-insensitive)
            definition: Optional filter by definition (supports pattern matching, case-insensitive)
            
        Returns:
            List of term dictionaries matching the search criteria
            
        Example:
            # Search for temperature-related terms
            terms = client.search_terms_for_fields("temperature")
            # Returns terms like "temperature", "air temperature", "water temperature"
        """
        terms = self.search_terms(label=term_label, definition=definition)
        
        # Convert dict to list format for consistency
        result = []
        for term_name, term_info in terms.items():
            result.append({
                "term_name": term_name,
                "label": term_info.get("label", term_name),
                "definition": term_info.get("definition", ""),
                "syntax": term_info.get("syntax", ""),
                "example": term_info.get("example", ""),
                "preferred_unit": term_info.get("preferredUnit", ""),
                "url": term_info.get("url", ""),
                "regex": term_info.get("regex", ""),
            })
        
        logger.info(f"✅ Found {len(result)} terms matching '{term_label}'")
        return result
    
    def search_fields_in_packages(
        self,
        field_label: str,
        package_names: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Search for fields by label across specified packages (client-side filtering).
        
        Note: FAIR-DS API does not support server-side field search in /api/package.
        This method fetches package data and filters fields client-side.
        
        Args:
            field_label: Field label to search for (case-insensitive partial match)
            package_names: Optional list of package names to search in. If None, searches all packages.
            
        Returns:
            List of field dictionaries matching the search criteria
        """
        if package_names is None:
            package_names = self.get_available_packages()
        
        matching_fields = []
        search_label_lower = field_label.lower()
        
        for pkg_name in package_names:
            package = self.get_package(pkg_name)
            if not package or "metadata" not in package:
                continue
                
            for field in package["metadata"]:
                field_label_value = field.get("label", "")
                # Case-insensitive partial match
                if search_label_lower in field_label_value.lower():
                    matching_fields.append(field)
        
        logger.info(f"✅ Found {len(matching_fields)} fields matching '{field_label}' across {len(package_names)} packages")
        return matching_fields

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
            want = FAIRDSAPIParser.normalize_isa_sheet(sheet_name)
            fields = [
                f
                for f in fields
                if FAIRDSAPIParser.normalize_isa_sheet(
                    FAIRDSAPIParser.raw_isa_level_from_field(f)
                )
                == want
            ]
            
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
            canon = FAIRDSAPIParser.normalize_isa_sheet(
                FAIRDSAPIParser.raw_isa_level_from_field(field)
            )
            fields_by_sheet.setdefault(canon, []).append(field)
            
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
            sheet = FAIRDSAPIParser.normalize_isa_sheet(
                FAIRDSAPIParser.raw_isa_level_from_field(field)
            )
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
