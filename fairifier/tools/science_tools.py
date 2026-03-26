"""External science API tools used by deepagents inner loops."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests
from langchain_core.tools import tool

from ..config import config
from ..services.retrieval_cache import get_cached_value, make_cache_key, store_cached_value

logger = logging.getLogger(__name__)


def _safe_get_json(
    url: str,
    *,
    params: Dict[str, Any] | None = None,
    timeout: int = 8,
    cache_store: Dict[str, Any] | None = None,
):
    """Fetch JSON from an external API with predictable failure semantics."""
    cache_key = None
    if cache_store is not None:
        cache_key = make_cache_key("http_get_json", {"url": url, "params": params or {}})
        cached = get_cached_value(cache_store, cache_key)
        if cached is not None:
            return True, cached, None

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if cache_store is not None and cache_key is not None:
            store_cached_value(cache_store, cache_key, payload)
        return True, payload, None
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Science API request failed: %s", exc)
        return False, None, str(exc)


def create_science_tools(
    *,
    cache_store: Dict[str, Any] | None = None,
    crossref_mailto: str | None = None,
) -> List:
    """Create zero-auth science enrichment tools."""

    @tool
    def search_ontology_term(term: str, ontology: str = "go,efo,obi,envo,ncbitaxon") -> Dict[str, Any]:
        """Search EBI OLS4 for ontology matches."""
        success, payload, error = _safe_get_json(
            "https://www.ebi.ac.uk/ols4/api/search",
            params={"q": term, "ontology": ontology, "rows": 5},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"OLS4 unavailable: {error}"}

        docs = payload.get("response", {}).get("docs", [])
        results = [
            {
                "label": doc.get("label"),
                "iri": doc.get("iri"),
                "ontology_name": doc.get("ontology_name"),
                "description": (doc.get("description") or [None])[0],
            }
            for doc in docs
        ]
        return {"success": True, "data": results, "error": None}

    @tool
    def resolve_doi_metadata(doi: str) -> Dict[str, Any]:
        """Resolve DOI metadata from Crossref."""
        doi = doi.strip().removeprefix("https://doi.org/")
        success, payload, error = _safe_get_json(
            f"https://api.crossref.org/works/{doi}",
            params={"mailto": crossref_mailto or config.crossref_mailto or "fairiagent@example.invalid"},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": None, "error": f"Crossref unavailable: {error}"}

        message = payload.get("message", {})
        data = {
            "DOI": message.get("DOI"),
            "title": (message.get("title") or [None])[0],
            "publisher": message.get("publisher"),
            "published": message.get("published", {}),
            "license": message.get("license", []),
            "funder": message.get("funder", []),
            "author": message.get("author", []),
        }
        return {"success": True, "data": data, "error": None}

    @tool
    def search_literature(query: str, n_results: int = 5) -> Dict[str, Any]:
        """Search Europe PMC for related papers and extracted terms."""
        success, payload, error = _safe_get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "pageSize": max(1, min(n_results, 10))},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"Europe PMC unavailable: {error}"}

        results = payload.get("resultList", {}).get("result", [])
        data = [
            {
                "title": item.get("title"),
                "doi": item.get("doi"),
                "journal": item.get("journalTitle"),
                "pubYear": item.get("pubYear"),
                "authorString": item.get("authorString"),
            }
            for item in results
        ]
        return {"success": True, "data": data, "error": None}

    @tool
    def search_similar_papers(query: str, n_results: int = 5) -> Dict[str, Any]:
        """Search OpenAlex for related papers and topic hints."""
        success, payload, error = _safe_get_json(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per-page": max(1, min(n_results, 10)),
                "select": "display_name,doi,publication_year,primary_topic,authorships",
            },
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"OpenAlex unavailable: {error}"}

        results = payload.get("results", [])
        data = [
            {
                "title": item.get("display_name"),
                "doi": item.get("doi"),
                "publication_year": item.get("publication_year"),
                "primary_topic": (item.get("primary_topic") or {}).get("display_name"),
                "authors": [
                    authorship.get("author", {}).get("display_name")
                    for authorship in item.get("authorships", [])[:5]
                ],
            }
            for item in results
        ]
        return {"success": True, "data": data, "error": None}

    return [
        search_ontology_term,
        resolve_doi_metadata,
        search_literature,
        search_similar_papers,
    ]
