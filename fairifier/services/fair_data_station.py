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
            response = self._session.get(
                f"{self._base_url}/api/terms", timeout=self._timeout
            )
            response.raise_for_status()
            terms: List[Dict[str, Any]] = response.json()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Unable to fetch FAIR-DS terms: %s", exc)
            terms = []

        self._terms_cache = terms
        return terms

    def get_packages(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and cache all metadata packages from the FAIR Data Station."""
        if self._packages_cache is not None and not force_refresh:
            return self._packages_cache

        try:
            response = self._session.get(
                f"{self._base_url}/api/packages", timeout=self._timeout
            )
            response.raise_for_status()
            packages: List[Dict[str, Any]] = response.json()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Unable to fetch FAIR-DS packages: %s", exc)
            packages = []

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


__all__ = ["FAIRDataStationClient", "FAIRDataStationUnavailable"]
