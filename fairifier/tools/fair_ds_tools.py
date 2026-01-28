"""LangChain tools for FAIR Data Station API operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@dataclass
class FAIRDSToolResult:
    """Structured result from FAIR-DS tools."""
    success: bool
    data: Any
    error: Optional[str] = None


def create_fair_ds_tools(client=None) -> List:
    """Create FAIR Data Station API tools.
    
    Args:
        client: Optional FAIRDataStationClient instance. If None, tools will
                create client from config when invoked.
    
    Returns:
        List of LangChain tools for FAIR-DS operations.
    """
    from ..services.fair_data_station import FAIRDataStationClient
    from ..config import config
    
    # Create client if not provided
    if client is None:
        if config.fair_ds_api_url:
            try:
                client = FAIRDataStationClient(config.fair_ds_api_url)
                if not client.is_available():
                    logger.warning("FAIR-DS API not available at %s", config.fair_ds_api_url)
                    client = None
            except Exception as exc:
                logger.warning("Failed to create FAIR-DS client: %s", exc)
                client = None
        else:
            logger.warning("FAIR-DS API URL not configured")
            client = None
    
    # Closure variables for tools to access client
    _client = client
    
    @tool
    def get_available_packages(force_refresh: bool = False) -> Dict[str, Any]:
        """Get list of all available FAIR-DS metadata package names.
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            Dictionary with 'success', 'data' (list of package names), and optional 'error'
        """
        if _client is None:
            return {
                "success": False,
                "data": [],
                "error": "FAIR-DS client not available"
            }
        
        try:
            packages = _client.get_available_packages(force_refresh=force_refresh)
            return {
                "success": True,
                "data": packages,
                "error": None
            }
        except Exception as exc:
            logger.error("get_available_packages failed: %s", exc)
            return {
                "success": False,
                "data": [],
                "error": str(exc)
            }
    
    @tool
    def get_package(package_name: str) -> Dict[str, Any]:
        """Get a specific FAIR-DS metadata package with all its fields.
        
        Args:
            package_name: Name of the package (e.g., "miappe", "soil", "default")
            
        Returns:
            Dictionary with 'success', 'data' (package metadata), and optional 'error'
            Package data structure:
            {
                "packageName": str,
                "itemCount": int,
                "metadata": [
                    {
                        "sheetName": str,
                        "packageName": str,
                        "requirement": str,
                        "label": str,
                        "term": {...}
                    },
                    ...
                ]
            }
        """
        if _client is None:
            return {
                "success": False,
                "data": None,
                "error": "FAIR-DS client not available"
            }
        
        try:
            package = _client.get_package(package_name)
            if package is None:
                return {
                    "success": False,
                    "data": None,
                    "error": f"Package '{package_name}' not found"
                }
            return {
                "success": True,
                "data": package,
                "error": None
            }
        except Exception as exc:
            logger.error("get_package('%s') failed: %s", package_name, exc)
            return {
                "success": False,
                "data": None,
                "error": str(exc)
            }
    
    @tool
    def get_terms(force_refresh: bool = False) -> Dict[str, Any]:
        """Get all FAIR-DS terms (metadata field definitions).
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            Dictionary with 'success', 'data' (dict mapping term names to term details), and optional 'error'
        """
        if _client is None:
            return {
                "success": False,
                "data": {},
                "error": "FAIR-DS client not available"
            }
        
        try:
            terms = _client.get_terms(force_refresh=force_refresh)
            return {
                "success": True,
                "data": terms,
                "error": None
            }
        except Exception as exc:
            logger.error("get_terms failed: %s", exc)
            return {
                "success": False,
                "data": {},
                "error": str(exc)
            }
    
    @tool
    def search_terms_for_fields(term_label: str, definition: Optional[str] = None) -> Dict[str, Any]:
        """Search for metadata terms by label and/or definition.
        
        Uses FAIR-DS API /api/terms endpoint with pattern matching (case-insensitive).
        
        Args:
            term_label: Filter terms by label (supports pattern matching)
            definition: Optional filter by definition (supports pattern matching)
            
        Returns:
            Dictionary with 'success', 'data' (list of matching terms), and optional 'error'
            Each term has: term_name, label, definition, syntax, example, preferred_unit, url, regex
        """
        if _client is None:
            return {
                "success": False,
                "data": [],
                "error": "FAIR-DS client not available"
            }
        
        try:
            terms = _client.search_terms_for_fields(term_label, definition)
            return {
                "success": True,
                "data": terms,
                "error": None
            }
        except Exception as exc:
            logger.error("search_terms_for_fields('%s') failed: %s", term_label, exc)
            return {
                "success": False,
                "data": [],
                "error": str(exc)
            }
    
    @tool
    def search_fields_in_packages(
        field_label: str, 
        package_names: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for fields by label across FAIR-DS packages.
        
        Note: Client-side filtering (FAIR-DS API doesn't support server-side field search).
        
        Args:
            field_label: Field label to search for (case-insensitive partial match)
            package_names: Optional comma-separated package names to search in.
                          If None, searches all packages.
                          Example: "miappe,soil,default"
            
        Returns:
            Dictionary with 'success', 'data' (list of matching fields), and optional 'error'
        """
        if _client is None:
            return {
                "success": False,
                "data": [],
                "error": "FAIR-DS client not available"
            }
        
        try:
            # Parse package_names if provided
            pkg_list = None
            if package_names:
                pkg_list = [p.strip() for p in package_names.split(",")]
            
            fields = _client.search_fields_in_packages(field_label, pkg_list)
            return {
                "success": True,
                "data": fields,
                "error": None
            }
        except Exception as exc:
            logger.error("search_fields_in_packages('%s') failed: %s", field_label, exc)
            return {
                "success": False,
                "data": [],
                "error": str(exc)
            }
    
    return [
        get_available_packages,
        get_package,
        get_terms,
        search_terms_for_fields,
        search_fields_in_packages,
    ]
